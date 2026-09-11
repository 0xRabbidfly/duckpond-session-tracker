"""Auto camera for a second monitor: the director watches the fleet and frames what matters.

Priorities (highest first): a duck blocked on a permission, a duck asking you a question, a
fresh sub-agent fan-out, a compaction geyser, a finished report, then whoever is generating
hardest. Between beats it returns to the overview. The camera position is critically damped
(a velocity-state spring), so the path is C1-continuous however abruptly the target changes;
tests/headless_director.py asserts the second difference stays bounded.
"""
from __future__ import annotations

import math

from mathutils import Vector

from ..scene import pool as P

Key = tuple[str, str]

PRIORITY = {"blocked": 100, "question": 80, "spawn": 60, "compaction": 55, "error": 50, "done": 35, "prompt": 30}
HOLD_S = 9.0          # how long a beat holds the camera
OVERVIEW_EVERY_S = 40.0
COOLDOWN_S = 30.0     # do not revisit the same duck sooner than this


class Director:
    def __init__(self) -> None:
        self.enabled = False
        self.target: Key | None = None
        self.target_until = 0.0
        self.last_overview = 0.0
        self.last_visit: dict[Key, float] = {}
        self.notices: dict[Key, tuple[int, float]] = {}
        self.vel = Vector((0.0, 0.0, 0.0))
        self.look = Vector(P.CAM_OVERVIEW[1])
        self.look_vel = Vector((0.0, 0.0, 0.0))
        self.mode = "overview"

    def notice(self, key: Key, kind: str, now: float) -> None:
        pr = PRIORITY.get(kind, 10)
        cur = self.notices.get(key)
        if cur is None or pr >= cur[0]:
            self.notices[key] = (pr, now)

    # ------------------------------------------------------------ choose
    def _pick(self, fleet, ducks, now: float) -> Key | None:
        best, best_score = None, -1.0
        for key, (pr, at) in list(self.notices.items()):
            if now - at > 30.0 or key not in ducks:
                del self.notices[key]
                continue
            if now - self.last_visit.get(key, -1e9) < COOLDOWN_S and pr < 100:
                continue
            score = pr - (now - at) * 0.5
            if score > best_score:
                best, best_score = key, score
        if best is not None:
            return best
        # nothing happened: the hardest-working duck, if any
        live = [(s.tokens_per_sec(now), (s.id, "")) for s in fleet.live_sessions()
                if s.state in ("generating", "tool_running") and (s.id, "") in ducks]
        live = [(t, k) for t, k in live if now - self.last_visit.get(k, -1e9) > COOLDOWN_S]
        if live:
            live.sort(reverse=True)
            return live[0][1]
        return None

    # ------------------------------------------------------------ step
    def step(self, fleet, ducks, lanes, cam, now: float, dt: float) -> None:
        if cam is None:
            return
        if now >= self.target_until:
            key = self._pick(fleet, ducks, now)
            if key is not None and (self.mode == "overview" or now - self.last_overview < OVERVIEW_EVERY_S):
                self.target = key
                self.mode = "duck"
                self.last_visit[key] = now
                self.notices.pop(key, None)
            else:
                self.target = None
                self.mode = "overview"
                self.last_overview = now
            self.target_until = now + HOLD_S
        d = ducks.get(self.target) if self.target else None
        if d is None:
            desired_pos, desired_look = Vector(P.CAM_OVERVIEW[0]), Vector(P.CAM_OVERVIEW[1])
        else:
            try:
                t = Vector(d.obj.location)
            except ReferenceError:
                self.target = None
                return
            # three-quarter view from the south side, a touch above, framing the duck and its ducklings
            desired_pos = Vector((t.x - 2.6, t.y - 4.4, 2.6))
            desired_look = Vector((t.x, t.y, 0.25))
        self._spring(cam, desired_pos, desired_look, dt)

    def _spring(self, cam, desired_pos: Vector, desired_look: Vector, dt: float) -> None:
        """Critically damped springs on position and look-at: no snaps, no overshoot."""
        omega = 1.3
        pos = Vector(cam.location)
        self.vel, pos = _cd_spring(pos, self.vel, desired_pos, omega, dt)
        self.look_vel, self.look = _cd_spring(self.look, self.look_vel, desired_look, omega, dt)
        cam.location = pos
        P.look_at(cam, self.look)


def _cd_spring(x: Vector, v: Vector, target: Vector, omega: float, dt: float):
    """Closed-form critically damped spring step (Bhatia / Gordon): stable for any dt."""
    e = math.exp(-omega * dt)
    dx = x - target
    temp = (v + dx * omega) * dt
    new_x = target + (dx + temp) * e
    new_v = (v - temp * omega) * e
    return new_v, new_x
