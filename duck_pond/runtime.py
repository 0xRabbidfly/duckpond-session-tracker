"""Runtime: timer drains adapters into the fleet; frame handler animates the scene.

Everything that moves (ducks, ripples, packets, sky, camera) is driven by `frame_change_post`,
which only fires while the viewport is playing back. Playback can stop on its own -- resuming
from sleep is the usual culprit -- and the pond then freezes on a stale frame while the data
timer keeps running, so the scoreboard is stuck and no new duck ever shows up. `_watchdog`
checks the moving parts every few seconds and re-arms whichever one died.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

import bpy
from mathutils import Matrix, Vector

from .adapters.base import Adapter
from .ledger import RANGE_ORDER
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
WATCHDOG_S = 3.0  # how often to check that playback, the timer, the handler and the worker are alive
STALL_AFTER_S = 8.0  # no frame for this long while running -> the scene is frozen, re-arm playback
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
        self.view_locked = False  # app mode: viewports copy DP_Camera every frame (see lock_views)
        self.board_range = "hour"  # scoreboard bars and 'this range' line: min | hour | day | week | month
        self.show_legend = True  # on-screen key: halo = state, body = tool, hat = model (H)
        self.running = False
        self.paused = False
        self.last_frame_t = 0.0
        self.last_tick_t = 0.0
        self.frames = 0  # frame-handler calls; the watchdog watches this for a stall
        self.revivals = 0  # how often the watchdog had to re-arm something (shown in the sidebar)
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
            self._start_worker()  # the worker backfills the ledger before it polls
        else:
            self._backfill(self.fleet.apply)
        if gui:
            if not bpy.app.timers.is_registered(_timer):
                bpy.app.timers.register(_timer, first_interval=0.1, persistent=True)
            if _frame not in bpy.app.handlers.frame_change_post:
                bpy.app.handlers.frame_change_post.append(_frame)
            if not bpy.app.timers.is_registered(_watchdog):
                bpy.app.timers.register(_watchdog, first_interval=WATCHDOG_S, persistent=True)
            bpy.app.timers.register(_gui_bootstrap, first_interval=0.5)

    def stop(self) -> None:
        self.running = False
        self.status = "stopped"
        self._stop_worker()
        for fn in (_timer, _watchdog):
            try:
                if bpy.app.timers.is_registered(fn):
                    bpy.app.timers.unregister(fn)
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

    def _backfill(self, sink) -> None:
        """Past usage for the ledger, once, before live polling (a month of transcripts reads in ~1 s).
        BackfillDone is sent even when an adapter fails, so the board stops saying 'scanning logs'."""
        for a in self.adapters:
            try:
                for ev in a.backfill(time.time()):
                    sink(ev)
            except Exception:
                self.last_error = traceback.format_exc(limit=3)
                print("[duck_pond] backfill error:", self.last_error)
        sink({"type": "BackfillDone"})

    def _worker_loop(self) -> None:
        self._backfill(self._queue.put)
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
                rgb = harness_color(s.harness, self.color_overrides)[:3]
                if s.state == "idle":  # drain most of the colour: idle reads at a glance, not by halo
                    grey = sum(rgb) / 3.0
                    rgb = tuple(grey + (c - grey) * 0.25 for c in rgb)
                d.set_color((*rgb, d.obj.color[3]))
            for sub in s.subagents.values():
                skey = (s.id, sub.id)
                if skey not in self.ducks and not sub.done:
                    dd = DuckObj(s.id, sub.id, s.harness, sub.model or s.model, "", True, self.color_overrides, self.hat_overrides)
                    self.ducks[skey] = dd
                    self.tethers[skey] = Tether(s.id, sub.id, harness_color(s.harness, self.color_overrides))
                    self.motion.ripple_for(key, self.ducks, self.ripples, big=True)
                elif skey in self.ducks:
                    self.ducks[skey].set_hat(sub.model or s.model)
        for d in self.ducks.values():
            d.fit_badges()  # here in the timer, not in the frame handler: fitting evaluates the depsgraph
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
        self.board.update(self.fleet, now, self.board_range)
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
        self.frames += 1
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
        if self.view_locked and not bpy.app.background:
            self.lock_views(cam)

    def lock_views(self, cam=None) -> None:
        """Every 3D viewport sees exactly what DP_Camera sees, as a plain perspective view that
        fills the window. Looking *through* the camera would draw Blender's dashed camera frame
        and darken everything outside it."""
        cam = cam or P.get("DP_Camera")
        if cam is None:
            return
        view = Matrix.LocRotScale(cam.location, cam.rotation_euler.to_quaternion(), None).inverted()
        # tangents of the camera's half field of view (sensor fit AUTO: the sensor spans the longer side)
        render = bpy.context.scene.render
        rw, rh = render.resolution_x * render.pixel_aspect_x, render.resolution_y * render.pixel_aspect_y
        tan_long = cam.data.sensor_width / 2.0 / cam.data.lens
        tan_w, tan_h = (tan_long, tan_long * rh / rw) if rw >= rh else (tan_long * rw / rh, tan_long)
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is None or region.width < 2 or region.height < 2:
                    continue
                space = area.spaces[0]
                rv3d = space.region_3d
                if rv3d.view_perspective != "PERSP":
                    rv3d.view_perspective = "PERSP"
                rv3d.view_matrix = view
                # A free perspective view spans 36 mm over the longer side of the region at twice its lens
                # (Blender's CAMERA_PARAM_ZOOM_INIT_PERSP). Take the longest lens that still shows the whole
                # camera shot, so a window wider or taller than the render shows more pool, never less.
                w, h = region.width, region.height
                m = max(w, h)
                space.lens = min(36.0 * w / (m * tan_w), 36.0 * h / (m * tan_h))
                space.clip_start = cam.data.clip_start
                space.clip_end = cam.data.clip_end

    # ------------------------------------------------------------ queries for UI
    def agent_for_object(self, obj) -> tuple[str, Key | None]:
        if obj is None or "dp_kind" not in obj:
            return "", None
        kind = obj["dp_kind"]
        if kind in ("duck", "duckling", "tether", "hat", "label") and "dp_session_id" in obj:
            return kind, (obj["dp_session_id"], obj["dp_agent_id"])
        return "", None

    def set_board_range(self, name: str) -> None:
        if name in RANGE_ORDER and name != self.board_range:
            self.board_range = name
            self.board.last_update = 0.0  # redraw on the next tick, not a second later

    def next_board_range(self) -> str:
        return RANGE_ORDER[(RANGE_ORDER.index(self.board_range) + 1) % len(RANGE_ORDER)]

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


def _viewports():
    """(window, screen, area, region) for every 3D viewport, or an empty list when there is none."""
    out = []
    wm = getattr(bpy.context, "window_manager", None)
    for window in getattr(wm, "windows", []) or []:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            out.append((window, screen, area, region))
    return out


def _arm_viewport(play: bool = True, hover: bool = True) -> bool:
    """Start playback and the hover operator in the first 3D viewport. True once a viewport was found.

    Playback is what calls `frame_change_post`, so it is the heartbeat of every moving thing in
    the pond. It is started here rather than once at launch because it does not always survive
    the session (waking from sleep drops it), and a pond that has stopped moving looks identical
    to a pond with nothing in it.
    """
    for window, screen, area, region in _viewports():
        try:
            with bpy.context.temp_override(window=window, screen=screen, area=area, region=region):
                if play and not screen.is_animation_playing:
                    bpy.ops.screen.animation_play()
                if hover and not RT.hover_started:
                    bpy.ops.duck_pond.hover("INVOKE_DEFAULT")
                    RT.hover_started = True
        except Exception as exc:  # noqa: BLE001 - a viewport mid-teardown is not worth a traceback
            print("[duck_pond] arm viewport:", exc)
        return True
    return False


def _gui_bootstrap():
    """Start playback (drives the water shader + frame handler) and the hover operator."""
    if bpy.app.background or not RT.running:
        return None
    return None if _arm_viewport() else 1.0


def _watchdog():
    """Re-arm whatever stopped: playback, the data timer, the frame handler, the worker thread.

    A frozen pond is indistinguishable from an empty one at a glance, so nothing here waits for
    a person to notice. Each revival is counted and the reason printed once, which is what turns
    a silent freeze into a line in the log.
    """
    if not RT.running:
        return None
    now = time.time()
    revived = []
    try:
        if not bpy.app.timers.is_registered(_timer):
            bpy.app.timers.register(_timer, first_interval=0.0, persistent=True)
            revived.append("data timer")
        if _frame not in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.append(_frame)
            revived.append("frame handler")
        if RT.threaded and (RT._worker is None or not RT._worker.is_alive()):
            RT._start_worker()
            revived.append("adapter worker")
        # the pond stops moving when playback stops; last_frame_t is only touched by the handler.
        # Background Blender has no viewport: _viewports() is empty and this half quietly no-ops.
        stalled = bool(RT.last_frame_t) and now - RT.last_frame_t > STALL_AFTER_S
        playing = any(screen.is_animation_playing for _w, screen, _a, _r in _viewports())
        if (stalled or not playing) and _arm_viewport(play=True, hover=False):
            if not playing:
                revived.append("playback")
        if stalled:
            for _w, _s, area, _r in _viewports():
                area.tag_redraw()
    except Exception:  # noqa: BLE001 - the watchdog must outlive whatever it is watching
        RT.last_error = traceback.format_exc(limit=3)
        print("[duck_pond] watchdog error:", RT.last_error)
        return WATCHDOG_S
    if revived:
        RT.revivals += len(revived)
        note = f" after {now - RT.last_frame_t:.0f}s without a frame" if stalled else ""
        print(f"[duck_pond] watchdog revived: {', '.join(revived)}{note}")
    return WATCHDOG_S
