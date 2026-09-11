from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from mathutils import Euler, Vector, noise

from ..scene import meshes as MS
from ..scene import pool as P
from ..scene.ripples import RED, WHITE
from ..theme import STATE_COLORS, hex_to_rgba, redact, tool_chip

SPEED_GENERATING = 0.45
SPEED_ENDED = 0.2
BOB_HZ = 1.2
FADE_S = 60.0
SPAWN_S = 0.6
DESPAWN_S = 0.8
ORBIT_R = 1.4
ORBIT_R_NESTED = 0.7
ORBIT_R_OVERFLOW = 2.1
ORBIT_SLOTS = 8
# Smoothness contract (tests/headless_motion.py): a heading never changes faster than MAX_YAW,
# so no frame can show a snap. Ropes and walls are avoided by steering that ramps up over
# WALL_LOOKAHEAD metres, never by reflecting the heading; a duck whose lane moved under it
# paddles back at SPEED_RELOCATE instead of being slid sideways.
MAX_YAW = math.radians(150)
WALL_LOOKAHEAD = 1.0
SPEED_RELOCATE = 0.35
CENTER_PULL = 0.5
RELOCATE_DONE_FRAC = 0.5
HOP_S = 0.6
POP_S = 1.0
SEPARATION_R = 1.6      # ducks closer than this steer apart (names stop overlapping)
SEPARATION_SPEED = 0.14  # a waiting duck drifts apart at most this fast

# One colour per state, on the beacon lamp AND the halo on the water. Working is teal, waiting
# is yellow, blocked is red, idle is grey. No glyphs: a glyph reads the same in every state.
STATE_RGBA = {k: hex_to_rgba(v) for k, v in STATE_COLORS.items()}
WORKING = ("generating", "tool_running")
QUIET_AFTER_S = 600.0  # a duck waiting this long stops asking for attention (dims, no pulse)


@dataclass
class Personality:
    """Who this duck is, within the contract. Derived from the id so it is stable across restarts."""
    speed_mul: float = 1.0    # 0.8..1.0 of SPEED_GENERATING (never above: the test bounds use it)
    wander: float = 1.8       # heading noise gain
    bob_hz: float = BOB_HZ
    bob_mul: float = 1.0
    curiosity: float = 0.0    # how much it turns toward the camera while waiting


def personality_for(key: Tuple[str, str]) -> Personality:
    h = abs(hash(key[0] + "|" + key[1]))
    r = [(h >> (8 * i)) & 0xFF for i in range(5)]
    return Personality(
        speed_mul=0.8 + 0.2 * r[0] / 255.0,
        wander=1.1 + 1.6 * r[1] / 255.0,
        bob_hz=BOB_HZ * (0.85 + 0.3 * r[2] / 255.0),
        bob_mul=0.8 + 0.5 * r[3] / 255.0,
        curiosity=0.4 + 0.6 * r[4] / 255.0,
    )


@dataclass
class MState:
    x: float
    y: float
    heading: float
    seed: float = field(default_factory=lambda: random.uniform(0, 100))
    speed: float = 0.0
    bob_phase: float = field(default_factory=lambda: random.uniform(0, 6.28))
    wake_t: float = 0.0
    still_t: float = 0.0
    bubble_t: float = 0.0
    thought_t: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    orbit_angle: float = 0.0
    spawn_t: float = 0.0
    z: float = 0.0
    scale: float = 1.0
    relocating: bool = False
    avoid_dir: float = 0.0  # committed turn direction while escaping a wall (0 = free)
    z_extra: float = 0.0    # hop / pop offset, low-passed so a celebration never pops the mesh
    ring_t: float = 0.0     # timer for the state ring while waiting / blocked
    p: Personality = field(default_factory=Personality)


def _wrap(d: float) -> float:
    return (d + math.pi) % (2 * math.pi) - math.pi


def _lerp_angle(a: float, b: float, k: float) -> float:
    return a + _wrap(b - a) * k


def _turn_toward(heading: float, desired: float, gain: float) -> float:
    """Yaw rate (rad/s) of a proportional turn toward `desired`, capped at MAX_YAW."""
    return _clamp(_wrap(desired - heading) * gain, -MAX_YAW, MAX_YAW)


def _sgn(v: float) -> float:
    return -1.0 if v < 0 else 1.0


def _room(x: float, y: float, lx: float, ly: float, xr, yr) -> float:
    """Distance from (x, y) to the nearest boundary along the unit direction (lx, ly)."""
    room = 1e9
    if lx > 1e-6:
        room = min(room, (xr[1] - x) / lx)
    elif lx < -1e-6:
        room = min(room, (x - xr[0]) / -lx)
    if yr is not None:
        if ly > 1e-6:
            room = min(room, (yr[1] - y) / ly)
        elif ly < -1e-6:
            room = min(room, (y - yr[0]) / -ly)
    return room


def _wall_steer(st: "MState", xr, yr) -> Tuple[float, float]:
    """Continuous avoidance of the pool ends (`xr`) and, when given, the lane ropes (`yr`).

    Every boundary the duck is closing on gets an urgency that grows linearly from zero at
    WALL_LOOKAHEAD to one at the boundary, times how squarely it approaches. The urgent
    boundaries' inward normals are summed into ONE escape direction (so a corner asks for a
    single U-turn instead of two rules fighting), and the duck is turned toward it at a rate
    proportional to the heading error, capped at MAX_YAW and scaled by the largest urgency.
    Everything here is a continuous function of position and heading, which is what keeps
    the heading free of snaps. Returns (yaw rate, urgency in 0..1).

    A head-on approach has no shortest way round, and letting the sign of the error decide
    each frame made ducks saw at the wall; so once the error passes 120 deg the duck COMMITS
    to the side with more room and keeps that direction until the error is under 60 deg."""
    x, y, heading, speed = st.x, st.y, st.heading, st.speed
    vx, vy = math.cos(heading), math.sin(heading)
    look = max(WALL_LOOKAHEAD, speed * 1.6)
    walls = [(xr[1] - x, vx, -1.0, 0.0), (x - xr[0], -vx, 1.0, 0.0)]
    if yr is not None:
        walls += [(yr[1] - y, vy, 0.0, -1.0), (y - yr[0], -vy, 0.0, 1.0)]
    rx = ry = umax = 0.0
    for dist, approach, nx, ny in walls:
        if approach <= 0.0:
            continue
        u = _clamp(1.0 - dist / look, 0.0, 1.0) * approach
        if u > 0.0:
            rx += u * nx
            ry += u * ny
            umax = max(umax, u)
    # a duck that is not moving is not about to hit anything
    umax *= _clamp(speed / 0.15, 0.0, 1.0)
    if umax <= 0.0:
        st.avoid_dir = 0.0
        return 0.0, 0.0
    err = _wrap(math.atan2(ry, rx) - heading)
    if st.avoid_dir and abs(err) > math.radians(60):
        err = st.avoid_dir * abs(err)
    elif abs(err) > math.radians(120):
        # commit: turn toward whichever side has more room to swing through
        left = _room(x, y, -vy, vx, xr, yr)
        right = _room(x, y, vy, -vx, xr, yr)
        st.avoid_dir = 1.0 if left > right else -1.0
        err = st.avoid_dir * abs(err)
    else:
        st.avoid_dir = 0.0
    return _clamp(err * 4.0, -MAX_YAW, MAX_YAW) * umax, umax


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _bump(now: float, at: float, dur: float, height: float) -> float:
    """A smooth one-shot lift starting at `at`: 0 at both ends, `height` in the middle."""
    if not at or now < at or now > at + dur:
        return 0.0
    k = (now - at) / dur
    return height * math.sin(math.pi * k) ** 2


class Motion:
    def __init__(self) -> None:
        self.states: Dict[Tuple[str, str], MState] = {}
        self.follow: Optional[Tuple[str, str]] = None
        self.redact = True
        self.fx = None          # scene.fx.FX, set by the runtime (optional)
        self.night = 0.0        # 0..1 from the sky, for the glow
        self.pinned: Optional[Tuple[str, str]] = None
        self._dt = 1.0 / 30.0

    # ------------------------------------------------------------ helpers
    def state_for(self, key, lane_y: Tuple[float, float], near: Optional[Vector] = None) -> MState:
        st = self.states.get(key)
        if st is None:
            if near is not None:
                x, y = near.x, near.y
            else:
                x = random.uniform(P.X_MARGIN + 1.0, P.POOL_X - P.X_MARGIN - 1.0)
                y = random.uniform(lane_y[0], lane_y[1])
            st = MState(x=x, y=y, heading=random.uniform(-math.pi, math.pi), p=personality_for(key))
            self.states[key] = st
        return st

    def forget(self, key) -> None:
        self.states.pop(key, None)

    @staticmethod
    def world_point(st: MState, local: Vector, scale: float) -> Vector:
        rot = Euler((st.roll, st.pitch, st.heading)).to_matrix()
        return Vector((st.x, st.y, st.z)) + rot @ (local * scale)

    # ------------------------------------------------------------ main step
    def step(self, fleet, ducks, tethers, lanes, ripples, cam, now: float, dt: float) -> List[Tuple[str, str]]:
        """Returns keys of ducklings whose despawn animation finished."""
        finished: List[Tuple[str, str]] = []
        self._dt = dt
        for s in list(fleet.sessions.values()):
            key = (s.id, "")
            d = ducks.get(key)
            if d is None:
                continue
            lane_y = lanes.y_range(s.cwd)
            st = self.state_for(key, lane_y)
            self._step_session(s, d, st, lane_y, ripples, cam, now, dt)
            subs = sorted(s.subagents.values(), key=lambda a: a.started_at)
            live_subs = [a for a in subs if not a.done]
            pscale = d.obj.scale.x
            # top-level ducklings orbit the duck; nested ones orbit their parent duckling
            top = [a for a in live_subs if not (a.parent_agent_id and (s.id, a.parent_agent_id) in ducks)]
            for idx, sub in enumerate(top):
                self._step_duckling(s, st, pscale, sub, idx, len(top), ducks, tethers, lane_y, ripples, cam, now, dt, finished)
            nested = [a for a in live_subs if a not in top]
            by_parent: Dict[str, List] = {}
            for a in nested:
                by_parent.setdefault(a.parent_agent_id, []).append(a)
            for pid, group in by_parent.items():
                pst = self.states.get((s.id, pid))
                pd = ducks.get((s.id, pid))
                if pst is None or pd is None:
                    continue
                for idx, sub in enumerate(group):
                    self._step_duckling(s, pst, pd.obj.scale.x, sub, idx, len(group), ducks, tethers, lane_y, ripples,
                                        cam, now, dt, finished, radius=ORBIT_R_NESTED)
            for sub in subs:
                if sub.done and (s.id, sub.id) in ducks:
                    host = self.states.get((s.id, sub.parent_agent_id)) if sub.parent_agent_id else None
                    self._step_duckling(s, host or st, pscale, sub, 0, 1, ducks, tethers, lane_y, ripples, cam, now, dt, finished)
        self._camera(ducks, cam, dt)
        return finished

    # ------------------------------------------------------------ session ducks
    def _separation(self, key, st: MState):
        """(away-heading, closeness 0..1) from the nearest other session duck, or (None, 0)."""
        best, best_d = None, SEPARATION_R
        for k, o in self.states.items():
            if k == key or k[1]:
                continue
            dx, dy = st.x - o.x, st.y - o.y
            dist = math.hypot(dx, dy)
            if dist < best_d:
                best, best_d = (dx, dy), dist
        if best is None:
            return None, 0.0
        if best_d < 1e-3:
            return st.heading, 1.0
        return math.atan2(best[1], best[0]), 1.0 - best_d / SEPARATION_R

    def _step_session(self, s, d, st: MState, lane_y, ripples, cam, now, dt) -> None:
        state = s.state
        p = st.p
        away, close = self._separation((s.id, ""), st)
        if state == "generating":
            # paddling speed follows output throughput a little (a streaming duck hurries), but
            # never exceeds SPEED_GENERATING, which the smoothness test uses as the top speed
            tps = s.tokens_per_sec(now)
            target_speed = SPEED_GENERATING * p.speed_mul * (0.9 + 0.1 * _clamp(tps / 60.0, 0.0, 1.0))
        elif state == "ended":
            target_speed = SPEED_ENDED
        else:
            target_speed = 0.0
        x0, x1 = P.X_MARGIN, P.POOL_X - P.X_MARGIN
        y0, y1 = lane_y
        yc, half = (y0 + y1) / 2, max(0.1, (y1 - y0) / 2)
        confined = state != "ended"
        # Lanes move when a session appears or leaves. A duck that finds itself outside its
        # lane paddles back to the centre (hysteresis: it is "relocating" until it is well
        # inside, so it does not stop at the rope it just crossed).
        if confined and not (y0 <= st.y <= y1):
            st.relocating = True
        elif not confined or abs(st.y - yc) < half * RELOCATE_DONE_FRAC:
            st.relocating = False

        # Every heading change is a yaw RATE, summed then capped: the heading is continuous.
        ropes = (y0, y1) if confined and not st.relocating else None
        turn, urgency = _wall_steer(st, (x0, x1), ropes)
        if state == "ended":
            ty = 0.35 if st.y < P.POOL_Y / 2 else P.POOL_Y - 0.35
            if abs(st.y - ty) < 0.15:
                target_speed = 0.0
            else:
                turn += _turn_toward(st.heading, math.atan2(ty - st.y, 0.0), 2.0)
        elif st.relocating:
            target_speed = max(target_speed, SPEED_RELOCATE)
            tx = _clamp(st.x + math.copysign(1.5, math.cos(st.heading)), x0 + 0.6, x1 - 0.6)
            turn += _turn_toward(st.heading, math.atan2(yc - st.y, tx - st.x), 3.0)
        elif state == "generating":
            wander = noise.noise(Vector((now * 0.25, st.seed, 0.0))) * p.wander
            # a gentle pull to the lane centre keeps a swimmer off the ropes in a narrow lane
            pull = _sgn(math.cos(st.heading)) * _clamp((yc - st.y) / half, -1.0, 1.0) * CENTER_PULL
            turn += (wander + pull) * (1.0 - urgency)
        elif state in ("awaiting_user", "awaiting_permission") and cam is not None:
            desired = math.atan2(cam.location.y - st.y, cam.location.x - st.x)
            turn += _turn_toward(st.heading, desired, 0.6 * p.curiosity) * (1.0 - urgency) * (1.0 - close)
        if away is not None and confined and not st.relocating:
            # too close to a neighbour: turn away and, if floating, drift apart slowly
            turn += _turn_toward(st.heading, away, 2.5 * close) * (1.0 - urgency)
            if state != "generating":
                target_speed = max(target_speed, SEPARATION_SPEED * close)
        st.heading += _clamp(turn, -MAX_YAW, MAX_YAW) * dt
        st.speed += (target_speed - st.speed) * min(1.0, dt * 2.0)

        nx = _clamp(st.x + math.cos(st.heading) * st.speed * dt, x0, x1)
        ny = st.y + math.sin(st.heading) * st.speed * dt
        if ropes is not None:
            ny = _clamp(ny, y0, y1)  # steering keeps the duck off the rope; this only guarantees it
        st.x, st.y = nx, _clamp(ny, 0.2, P.POOL_Y - 0.2)

        # --- vertical: bob, context fill (sinking), idle droop, done hop, compaction pop
        st.bob_phase += dt * 2 * math.pi * p.bob_hz
        amp = (0.02 if state == "generating" else 0.0 if state == "ended" else 0.01) * p.bob_mul
        frac = s.context_frac
        droop = 0.03 if state == "idle" else 0.0
        z_extra_target = _bump(now, s.last_done_at, HOP_S, 0.09) + _bump(now, s.last_compaction_at, POP_S, 0.14)
        st.z_extra += (z_extra_target - st.z_extra) * min(1.0, dt * 12.0)
        st.z = P.WATER_Z - 0.12 * frac - droop + math.sin(st.bob_phase) * amp + st.z_extra

        target_pitch = math.radians(15) if state == "tool_running" else math.radians(4) if state == "idle" else 0.0
        st.pitch += (target_pitch - st.pitch) * min(1.0, dt * 4.0)
        roll = math.sin(st.bob_phase) * math.radians(3) * p.bob_mul if state == "generating" else 0.0
        if state == "awaiting_permission":
            roll += math.sin(now * 2.2) * math.radians(6)  # impatient rocking
        if s.error_at and now - s.error_at < 0.6:
            k = (now - s.error_at) / 0.6
            roll += math.radians(25) * math.sin(math.pi * k) * (1.0 - k)
        if s.denied_at and now - s.denied_at < 0.8:
            k = (now - s.denied_at) / 0.8
            roll += math.radians(14) * math.sin(3 * math.pi * k) * (1.0 - k)  # a head-shake "no"
        st.roll = roll

        alpha = 1.0
        if state == "ended":
            alpha = max(0.0, 1.0 - (now - s.ended_at) / FADE_S)
        d.place(st.x, st.y, st.z, st.heading, st.pitch, st.roll)
        d.set_alpha(alpha)
        d.set_lifering(frac >= 0.95)
        d.set_flag(s.branch or "")
        d.set_label(redact(s.display_name, self.redact, 40))
        self._beacon(d, s, now, st, ripples, alpha)
        d.set_mail(s.queued)
        d.set_glow(self._glow((s.id, ""), state))

        self._fx(st, s, d.obj.scale.x, ripples, now, dt)

    def _glow(self, key, state: str) -> float:
        g = 0.55 * self.night if state not in ("ended",) else 0.0
        if self.pinned == key:
            g = max(g, 0.35)
        return g

    def _beacon(self, d, agent, now: float, st: Optional[MState] = None, ripples=None, alpha: float = 1.0) -> None:
        """Traffic light per duck: lamp on the pole + halo on the water, both in the state colour.
        working = steady teal · waiting = breathing yellow (quiet after 10 min) · blocked = flashing red
        · idle = dim grey · error = a red flash over whatever it was."""
        state = agent.state
        col = STATE_RGBA.get(state, STATE_RGBA["idle"])
        if state in WORKING:
            pulse = 0.85 + 0.15 * math.sin(2 * math.pi * 0.5 * now)
            halo_a = 0.75
        elif state == "awaiting_user":
            waited = now - agent.state_since
            quiet = _clamp((waited - QUIET_AFTER_S) / 120.0, 0.0, 1.0)
            pulse = (0.5 + 0.5 * math.sin(2 * math.pi * 0.6 * now)) * (1.0 - quiet) + 0.35 * quiet
            halo_a = 0.8 - 0.5 * quiet
            if agent.question:
                pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 1.2 * now)  # a question keeps asking
                halo_a = 0.85
        elif state == "awaiting_permission":
            pulse = 0.5 + 0.5 * math.sin(2 * math.pi * 2.2 * now)
            halo_a = 0.6 + 0.4 * pulse
        elif state == "idle":
            pulse = 0.3
            halo_a = 0.25
        else:  # ended
            d.set_beacon(None)
            d.set_halo((col[0], col[1], col[2], 0.15 * alpha))
            return
        if agent.error_at and now - agent.error_at < 0.8:
            col = STATE_RGBA["error"]
            pulse = 1.0
            halo_a = 0.9
        d.set_beacon(col, pulse)
        d.set_halo((col[0], col[1], col[2], halo_a * alpha))
        # blocked: a red ring keeps spreading on the water so it reads from the far deck
        if st is not None and ripples is not None and state == "awaiting_permission":
            st.ring_t += self._dt
            if st.ring_t >= 1.1:
                st.ring_t = 0.0
                ripples.ring(Vector((st.x, st.y, 0.0)), size=1.3 * d.obj.scale.x, color=col[:3], strength=0.55, life=1.0)

    # ------------------------------------------------------------ ducklings
    def _step_duckling(self, s, pst: MState, pscale: float, sub, idx, n, ducks, tethers, lane_y, ripples, cam, now, dt,
                       finished, radius: float = ORBIT_R) -> None:
        key = (s.id, sub.id)
        d = ducks.get(key)
        if d is None:
            return
        st = self.state_for(key, lane_y, near=Vector((pst.x, pst.y, 0.0)))
        p = st.p
        scale_mul = 1.0
        tether = tethers.get(key)
        if sub.done:
            k = _clamp((now - sub.done_at) / DESPAWN_S, 0.0, 1.0)
            st.x += (pst.x - st.x) * min(1.0, dt * 6.0)
            st.y += (pst.y - st.y) * min(1.0, dt * 6.0)
            scale_mul = max(0.05, 1.0 - k)
            st.z = P.WATER_Z - 0.25 * k
            if tether:
                tether.retract = 1.0 - k
            if k >= 1.0:
                finished.append(key)
            d.set_beacon(None)
            d.set_halo((0.5, 0.5, 0.5, 0.0))
        else:
            st.spawn_t = min(SPAWN_S, st.spawn_t + dt)
            k = st.spawn_t / SPAWN_S
            scale_mul = 0.2 + 0.8 * k
            generating = sub.state in ("generating", "tool_running")
            if sub.state == "generating":
                st.orbit_angle += dt * 0.35 * p.speed_mul
            r = radius if idx < ORBIT_SLOTS else ORBIT_R_OVERFLOW
            if sub.background:
                r *= 1.35  # background agents drift further out: they outlive the turn
            a = 2 * math.pi * (idx % ORBIT_SLOTS) / max(1, min(n, ORBIT_SLOTS)) + st.orbit_angle
            tx = _clamp(pst.x + r * math.cos(a), P.X_MARGIN, P.POOL_X - P.X_MARGIN)
            ty = _clamp(pst.y + r * math.sin(a), lane_y[0] - 0.3, lane_y[1] + 0.3)
            st.x += (tx - st.x) * min(1.0, dt * 3.0)
            st.y += (ty - st.y) * min(1.0, dt * 3.0)
            desired = a + math.pi / 2 if sub.state == "generating" else math.atan2(pst.y - st.y, pst.x - st.x)
            st.heading += _turn_toward(st.heading, desired, 3.0) * dt
            st.speed = 0.3 if sub.state == "generating" else 0.0
            st.bob_phase += dt * 2 * math.pi * p.bob_hz * 1.3
            amp = 0.015 if generating else 0.008
            st.z = P.WATER_Z - 0.3 * (1.0 - k) - 0.06 * sub.context_frac + math.sin(st.bob_phase) * amp
            target_pitch = math.radians(15) if sub.state == "tool_running" else 0.0
            st.pitch += (target_pitch - st.pitch) * min(1.0, dt * 4.0)
            st.roll = math.sin(st.bob_phase) * math.radians(4) if sub.state == "generating" else 0.0
            if sub.error_at and now - sub.error_at < 0.6:
                kk = (now - sub.error_at) / 0.6
                st.roll += math.radians(25) * math.sin(math.pi * kk) * (1.0 - kk)
            self._fx(st, sub, d.obj.scale.x, ripples, now, dt)
            self._beacon(d, sub, now, st, ripples)
            d.set_glow(self._glow(key, sub.state))
        st.scale = scale_mul
        d.place(st.x, st.y, st.z, st.heading, st.pitch, st.roll, scale_mul)
        d.set_label(redact(sub.description or sub.agent_type or sub.id[:8], self.redact, 32))
        if tether:
            tps = sub.tokens_per_sec(now)
            eps = sub.events_per_sec(now)
            amp = _clamp(tps / 200.0, 0.005, 0.06) if (tps > 0 or eps > 0) else 0.0
            freq = _clamp(1.0 + eps * 3.0, 1.0, 12.0)
            p0 = self.world_point(pst, MS.TAIL_TIP, pscale)
            p1 = self.world_point(st, MS.CHEST, d.obj.scale.x)
            tether.update(p0, p1, amp, freq, now, dt)
            tether.set_style(background=sub.background, active=not sub.done and sub.state in ("generating", "tool_running"))

    # ------------------------------------------------------------ effects
    def _fx(self, st: MState, agent, scale, ripples, now, dt) -> None:
        pos = Vector((st.x, st.y, 0.0))
        if st.speed > 0.2:
            st.wake_t += dt
            st.still_t = 0.0
            if st.wake_t > 0.4:
                st.wake_t = 0.0
                tail = self.world_point(st, MS.TAIL_TIP, scale)
                # a streaming duck leaves a stronger wake: throughput you can see from the deck
                tps = agent.tokens_per_sec(now)
                ripples.ring(Vector((tail.x, tail.y, 0)), size=0.7 * scale * (1.0 + 0.5 * _clamp(tps / 80.0, 0.0, 1.0)),
                             strength=0.45 + 0.35 * _clamp(tps / 80.0, 0.0, 1.0))
        else:
            st.still_t += dt
            if st.still_t > 3.0:
                st.still_t = random.uniform(0.0, 0.8)
                ripples.ring(pos, size=0.9 * scale, strength=0.22)
        if agent.state == "tool_running":
            st.bubble_t += dt
            if st.bubble_t > 0.45:
                st.bubble_t = 0.0
                head = self.world_point(st, Vector((0.36, 0.0, 0.0)), scale)
                _, hexc = tool_chip(agent.current_tool_category or "other")
                col = hex_to_rgba(hexc)
                if agent.current_tool_category == "bash":
                    col = (0.15, 0.17, 0.22, 1.0)  # bash breathes dark bubbles
                ripples.bubbles_at(head, 3, color=col[:3])
        elif agent.state == "generating" and agent.thinking and self.fx is not None:
            st.thought_t += dt
            if st.thought_t > 0.7:
                st.thought_t = 0.0
                head = self.world_point(st, MS.HEAD_TOP, scale)
                self.fx.thought(head)

    def ripple_for(self, key, ducks, ripples, big: bool = False, error: bool = False) -> None:
        d = ducks.get(key)
        if not d:
            return
        pos = Vector((d.obj.location.x, d.obj.location.y, 0.0))
        scale = d.obj.scale.x
        if error:
            ripples.ring(pos, size=1.6 * scale, color=RED, strength=0.9, life=2.0)
        elif big:
            ripples.ring(pos, size=1.8 * scale, color=WHITE, strength=0.8, life=2.0)
        else:
            ripples.ring(pos, size=1.0 * scale, color=WHITE, strength=0.5)

    # ------------------------------------------------------------ camera
    def _camera(self, ducks, cam, dt) -> None:
        if cam is None or self.follow is None:
            return
        d = ducks.get(self.follow)
        if d is None:
            self.follow = None
            return
        target = Vector(d.obj.location)
        desired = target + Vector((-3.0, -4.2, 2.8))
        cam.location = Vector(cam.location).lerp(desired, min(1.0, dt * 2.0))
        P.look_at(cam, target + Vector((0.0, 0.0, 0.2)))
