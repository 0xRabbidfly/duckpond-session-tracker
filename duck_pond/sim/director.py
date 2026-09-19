"""Camera for a second monitor: it frames the duck you focus, and nothing else.

The camera rests on the overview. Focus a duck -- click it, or press F to follow it -- and the
camera springs in to frame it and its ducklings; drop the focus and it springs back out. It
never picks a target of its own: an unattended pool holds the wide shot no matter what happens
in it, so the view only ever moves because you moved it.

The position is critically damped (a velocity-state spring), so the path is C1-continuous
however abruptly the focus changes; tests/headless_director.py asserts the second difference
stays bounded.
"""
from __future__ import annotations

import math

from mathutils import Vector

from ..scene import pool as P

Key = tuple[str, str]


class Director:
    def __init__(self) -> None:
        self.enabled = False
        self.target: Key | None = None
        self.vel = Vector((0.0, 0.0, 0.0))
        self.look = Vector(P.CAM_OVERVIEW[1])
        self.look_vel = Vector((0.0, 0.0, 0.0))
        self.mode = "overview"

    # ------------------------------------------------------------ step
    def step(self, fleet, ducks, lanes, cam, now: float, dt: float, focus: Key | None = None) -> None:
        """Ease the camera toward `focus`, or back to the overview when there is none."""
        if cam is None:
            return
        d = ducks.get(focus) if focus else None
        self.target = focus if d is not None else None
        self.mode = "duck" if d is not None else "overview"
        if d is None:
            desired_pos, desired_look = Vector(P.CAM_OVERVIEW[0]), Vector(P.CAM_OVERVIEW[1])
        else:
            try:
                t = Vector(d.obj.location)
            except ReferenceError:  # the duck left while we were framing it
                self.target = None
                self.mode = "overview"
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
