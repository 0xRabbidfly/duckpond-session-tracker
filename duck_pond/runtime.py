"""Runtime: timer drains adapters into the fleet; frame handler animates the scene."""
from __future__ import annotations

import queue
import threading
import time
import traceback

import bpy
from mathutils import Vector

from .adapters.base import Adapter
from .model import Fleet
from .scene import pool as P
from .scene.deck import LaneSigns, Scoreboard
from .scene.duck import DuckObj
from .scene.fx import FX
from .scene.ripples import Ripples
from .scene.sky import Sky
from .scene.tether import PacketSystem, Tether
from .sim.director import Director
from .sim.motion import Motion
from .theme import harness_color

POLL_INTERVAL = 0.25
IDLE_AFTER_S = 180.0
END_AFTER_S = 1800.0  # 30 min of silence -> the duck leaves
REMOVE_AFTER_S = 60.0
PACKET_MAX_AGE_S = 10.0
FX_MAX_AGE_S = 10.0  # effects for events older than this (startup replay) are not shown

Key = tuple[str, str]


class Runtime:
    def __init__(self) -> None:
        self.fleet = Fleet()
        self.adapters: list[Adapter] = []
        self.ducks: dict[Key, DuckObj] = {}
        self.tethers: dict[Key, Tether] = {}
        self.lanes = P.Lanes()
        self.ripples = Ripples()
        self.packets = PacketSystem()
        self.motion = Motion()
        self.fx = FX()
        self.motion.fx = self.fx
        self.board = Scoreboard()
        self.signs = LaneSigns()
        self.sky = Sky()
        self.director = Director()
        self.sound = None  # set by the addon when enabled (sound.Sound)
        self.tags_for_all = False  # kiosk: screen-space name tags on every duck
        self.running = False
        self.paused = False
        self.last_frame_t = 0.0
        self.last_tick_t = 0.0
        self.pinned: Key | None = None
        self.hover: Key | None = None
        self.hover_kind = ""
        self.redact = True
        self.color_overrides: dict = {}
        self.hat_overrides: list = []
        self.status = "stopped"
        self.last_error = ""
        self.hover_started = False
        self.poll_interval = POLL_INTERVAL
        self.idle_after = IDLE_AFTER_S
        self.end_after = END_AFTER_S
        self.remove_after = REMOVE_AFTER_S
        self._queue: queue.Queue[dict] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_stop = threading.Event()
        self.threaded = True

    # ------------------------------------------------------------ lifecycle
    def start(self, adapters: list[Adapter], gui: bool | None = None) -> None:
        if self.running:
            self.stop()
        self.adapters = adapters
        P.ensure_pool()
        self.ripples.ensure_pools()
        self.packets.ensure_pools()
        self.fx.ensure_pools()
        self.sky.ensure()
        self.board.ensure()
        self.packets.redact_enabled = self.redact
        self.running = True
        self.paused = False
        self.last_frame_t = time.time()
        self.status = "running: " + ", ".join(a.describe() for a in adapters)
        gui = (not bpy.app.background) if gui is None else gui
        if gui and self.threaded:
            self._start_worker()
        if gui:
            if not bpy.app.timers.is_registered(_timer):
                bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)
            if _frame not in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.append(_frame)
            bpy.app.timers.register(_gui_bootstrap, first_interval=0.5)

    def stop(self) -> None:
        self.running = False
        self.status = "stopped"
        self._stop_worker()
        try:
            if bpy.app.timers.is_registered(_timer):
                bpy.app.timers.unregister(_timer)
        except ValueError:
            pass
        if _frame in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(_frame)

    def reset(self) -> None:
        self.stop()
        for d in list(self.ducks.values()):
            d.remove()
        for t in list(self.tethers.values()):
            t.remove()
        self.ducks.clear()
        self.tethers.clear()
        self.packets = PacketSystem()
        self.ripples = Ripples()
        self.lanes = P.Lanes()
        self.motion = Motion()
        self.fx = FX()
        self.motion.fx = self.fx
        self.board = Scoreboard()
        self.signs = LaneSigns()
        self.sky = Sky()
        self.director = Director()
        self.fleet = Fleet()
        coll = bpy.data.collections.get(P.COLL_NAME)
        if coll:
            for o in list(coll.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(coll)
        for store in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
            for db in list(store):
                if db.name.startswith("DP_") and db.users == 0:
                    store.remove(db)
        self.pinned = None
        self.hover = None
        self.status = "reset"

    # ------------------------------------------------------------ data tick
    # Adapters parse transcripts (pure Python, no bpy) on a worker thread so a 40 MB
    # transcript discovered mid-session never stalls the viewport. The main thread only
    # drains ready events.
    def _start_worker(self) -> None:
        self._worker_stop.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="duck_pond-adapters", daemon=True)
        self._worker.start()

    def _stop_worker(self) -> None:
        self._worker_stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        self._worker = None

    def _worker_loop(self) -> None:
        while not self._worker_stop.is_set():
            if not self.paused:
                self._poll_adapters(time.time(), self._queue.put)
            self._worker_stop.wait(self.poll_interval)

    def _poll_adapters(self, now: float, sink) -> None:
        for a in self.adapters:
            try:
                for ev in a.poll(now):
                    sink(ev)
            except Exception:
                self.last_error = traceback.format_exc(limit=3)
                print("[duck_pond] adapter error:", self.last_error)

    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.last_tick_t = now
        if self._worker is not None:
            for _ in range(20000):  # bounded drain per tick
                try:
                    self.fleet.apply(self._queue.get_nowait())
                except queue.Empty:
                    break
        elif not self.paused:
            self._poll_adapters(now, self.fleet.apply)
        self.fleet.housekeeping(now, self.idle_after, self.end_after, self.remove_after)
        self.sync(now)

    def sync(self, now: float) -> None:
        # lanes follow the set of live working directories
        cwds = [s.cwd or "(no cwd)" for s in self.fleet.live_sessions()]
        self.lanes.update(cwds, now)
        # ducks for sessions
        for s in self.fleet.sessions.values():
            key = (s.id, "")
            d = self.ducks.get(key)
            if d is None:
                d = DuckObj(s.id, "", s.harness, s.model, s.branch, False, self.color_overrides, self.hat_overrides)
                self.ducks[key] = d
                self.motion.state_for(key, self.lanes.y_range(s.cwd))
                self.motion.ripple_for(key, self.ducks, self.ripples, big=True)
            else:
                d.set_hat(s.model)
                d.set_color((*harness_color(s.harness, self.color_overrides)[:3], d.obj.color[3]))
            for sub in s.subagents.values():
                skey = (s.id, sub.id)
                if skey not in self.ducks and not sub.done:
                    dd = DuckObj(s.id, sub.id, s.harness, sub.model or s.model, "", True, self.color_overrides, self.hat_overrides)
                    self.ducks[skey] = dd
                    self.tethers[skey] = Tether(s.id, sub.id, harness_color(s.harness, self.color_overrides))
                    self.motion.ripple_for(key, self.ducks, self.ripples, big=True)
                elif skey in self.ducks:
                    self.ducks[skey].set_hat(sub.model or s.model)
        # cues
        for cue in self.fleet.drain_cues():
            key = (cue.session_id, cue.agent_id or "")
            fresh = (now - cue.at) <= FX_MAX_AGE_S if cue.at else True
            if cue.kind in ("prompt_drop", "report_up", "tool_chip", "tool_done", "denied", "question",
                            "queued", "compaction", "done"):
                if fresh:
                    self._fx_cue(cue, key, now)
                continue
            if cue.kind in ("big_ripple",):
                if fresh:
                    self.motion.ripple_for(key, self.ducks, self.ripples, big=True)
            elif cue.kind == "error_ripple":
                if fresh:
                    self.motion.ripple_for(key, self.ducks, self.ripples, error=True)
                    self.director.notice(key, "error", now)
                    self._sound("error")
            elif cue.kind == "spawn_sub":
                if fresh:
                    self.director.notice(key, "spawn", now)
            elif cue.kind == "ripple":
                self.motion.ripple_for(key, self.ducks, self.ripples)
            elif cue.kind == "packet":
                t = self.tethers.get(key)
                if t and now - cue.payload.at <= PACKET_MAX_AGE_S:  # skip history replayed at startup
                    self.packets.spawn(cue.payload, t)
            elif cue.kind == "despawn":
                self._remove_key(key)
                for skey in [k for k in self.ducks if k[0] == cue.session_id]:
                    self._remove_key(skey)
        # sessions the fleet dropped
        for key in [k for k in self.ducks if k[0] not in self.fleet.sessions]:
            self._remove_key(key)
        # the world and the deck
        self.sky.tick(self.fleet, now)
        self.board.update(self.fleet, now)
        self.signs.update(self.lanes, self.fleet, now, self.redact)

    def _duck_pos(self, key: Key):
        d = self.ducks.get(key)
        if d is None:
            return None
        try:
            return Vector(d.obj.location)
        except ReferenceError:
            return None

    def _sound(self, name: str) -> None:
        if self.sound is not None:
            try:
                self.sound.play(name)
            except Exception:  # noqa: BLE001 - sound is decoration
                pass

    def _fx_cue(self, cue, key: Key, now: float) -> None:
        pos = self._duck_pos(key)
        if pos is None:
            return
        k = cue.kind
        if k == "prompt_drop":
            def land(p, key=key):
                self.motion.ripple_for(key, self.ducks, self.ripples, big=True)
            self.fx.prompt_drop(pos + Vector((0.0, 0.0, 0.25)), on_land=land)
            self.director.notice(key, "prompt", now)
            self._sound("prompt")
        elif k == "report_up":
            self.fx.report_up(pos + Vector((0.0, 0.0, 0.3)))
            self.ripples.ring(Vector((pos.x, pos.y, 0.0)), size=1.6, color=(1.0, 0.85, 0.35), strength=0.8, life=2.2)
            self.director.notice(key, "done", now)
            self._sound("done")
        elif k == "tool_chip":
            self.fx.tool_chip(pos, str(cue.payload))
            if cue.payload == "agent":
                self.director.notice(key, "spawn", now)
        elif k == "tool_done":
            cat, ok = cue.payload
            self.fx.tool_done(pos, cat, ok)
            if cat == "test":
                col = (0.3, 0.85, 0.4) if ok else (1.0, 0.15, 0.1)
                self.ripples.ring(Vector((pos.x, pos.y, 0.0)), size=1.4, color=col, strength=0.8, life=2.0)
                self._sound("pass" if ok else "fail")
            elif not ok:
                self.motion.ripple_for(key, self.ducks, self.ripples, error=True)
        elif k == "denied":
            self.fx.denied(pos, str(cue.payload))
            self.motion.ripple_for(key, self.ducks, self.ripples, error=True)
            self.director.notice(key, "blocked", now)
            self._sound("error")
        elif k == "question":
            self.fx.question(pos)
            self.director.notice(key, "question", now)
            self._sound("question")
        elif k == "queued":
            self.fx.queued(pos)
        elif k == "compaction":
            self.fx.geyser(pos, self.ripples)
            self.director.notice(key, "compaction", now)
            self._sound("geyser")
        elif k == "done":
            pass  # the hop is in the motion layer; report_up carries the visual

    def _remove_key(self, key: Key) -> None:
        d = self.ducks.pop(key, None)
        if d:
            d.remove()
        t = self.tethers.pop(key, None)
        if t:
            self.packets.release_tether(t)
            t.remove()
        self.motion.forget(key)
        if self.pinned == key:
            self.pinned = None
        if self.hover == key:
            self.hover = None

    # ------------------------------------------------------------ frame
    def frame(self, now: float | None = None, dt: float | None = None) -> None:
        now = time.time() if now is None else now
        if dt is None:
            dt = min(0.1, max(0.0, now - self.last_frame_t))
        self.last_frame_t = now
        cam = P.get("DP_Camera")
        self.motion.night = self.sky.night
        self.motion.pinned = self.pinned
        focus = self.pinned or self.hover
        self.packets.label_session = focus[0] if focus else None
        if not bpy.app.background:
            for key, d in self.ducks.items():
                d.set_world_label_visible(not (self.tags_for_all or key == focus))
        self.fx.rain = self.sky.rain
        finished = self.motion.step(self.fleet, self.ducks, self.tethers, self.lanes, self.ripples, cam, now, dt)
        for key in finished:
            self._remove_key(key)
            self.motion.ripple_for((key[0], ""), self.ducks, self.ripples)
        for vis in self.packets.update(dt):
            recv = (vis.packet.session_id, "" if vis.packet.direction == "up" else vis.packet.agent_id)
            self.motion.ripple_for(recv, self.ducks, self.ripples)
            vis.tether.flash()
        self.ripples.update(dt)
        self.fx.update(dt)
        self.sky.update(now, dt)
        if self.director.enabled and self.motion.follow is None:
            self.director.step(self.fleet, self.ducks, self.lanes, cam, now, dt)

    # ------------------------------------------------------------ queries for UI
    def agent_for_object(self, obj) -> tuple[str, Key | None]:
        if obj is None or "dp_kind" not in obj:
            return "", None
        kind = obj["dp_kind"]
        if kind in ("duck", "duckling", "tether", "hat", "label") and "dp_session_id" in obj:
            return kind, (obj["dp_session_id"], obj["dp_agent_id"])
        return "", None

    def toggle_follow(self) -> None:
        self.motion.follow = None if self.motion.follow else self.pinned

    def set_redact(self, enabled: bool) -> None:
        self.redact = enabled
        self.packets.redact_enabled = enabled
        self.motion.redact = enabled


RT = Runtime()


# ---------------------------------------------------------------- bpy callbacks
def _timer():
    if not RT.running:
        return None
    try:
        RT.tick()
    except Exception:
        RT.last_error = traceback.format_exc(limit=4)
        print("[duck_pond] tick error:", RT.last_error)
    return RT.poll_interval


def _frame(scene, *args):
    if not RT.running:
        return
    try:
        RT.frame()
    except Exception:
        RT.last_error = traceback.format_exc(limit=4)
        print("[duck_pond] frame error:", RT.last_error)


def _gui_bootstrap():
    """Start playback (drives the water shader + frame handler) and the hover operator."""
    if bpy.app.background or not RT.running:
        return None
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            try:
                with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
                    if not screen.is_animation_playing:
                        bpy.ops.screen.animation_play()
                    if not RT.hover_started:
                        bpy.ops.duck_pond.hover("INVOKE_DEFAULT")
                        RT.hover_started = True
            except Exception as exc:
                print("[duck_pond] gui bootstrap:", exc)
            return None
    return 1.0
