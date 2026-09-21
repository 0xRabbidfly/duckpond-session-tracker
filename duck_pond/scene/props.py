"""Floating pool toys: the things a real lido has lying about that nothing in the app needs.

They carry no data and mean nothing -- that is the point. Every other object in the pool is a
readout, so the eye has nowhere to rest; a beach ball drifting in the corner gives the scene a
sense of place and makes the ducks look like they are *in* somewhere rather than on a chart.

Most of them keep out of the way on purpose: a ball or a lily pad drifts inside its own small
patch near the pool edges, away from the swim lanes. The noodles are the exception. They float
anywhere, carried by a lazy current, and they bump into the ducks and into each other, which is
what a noodle in a real pool does. Everything here is marked "deck", so clicking one does
nothing.
"""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Matrix

from . import materials as M
from . import meshes as MS
from . import pool as P

DRIFT = 0.32   # metres a toy wanders from its anchor
BOB = 0.022    # metres of bob

# (kind, x, y, hex colour, scale). Anchors hug the east end and the north/south strips, which is
# where the lanes are not; the pool's working middle stays clear.
LAYOUT = [
    ("flamingo", 14.55, 0.95, "#FF5FA2", 1.0),
    ("ring",     14.85, 6.90, "#49B6FF", 1.0),
    ("ball",     13.70, 0.50, "#FFD93D", 1.0),
    ("ball",     15.05, 4.15, "#FF4D6D", 0.85),
    ("lily",      0.75, 0.60, "#2F8F4E", 1.0),
    ("lily",      0.95, 7.40, "#3AA55D", 0.8),
]


# The noodles roam. A noodle is a capsule, so it is collided as a segment with a radius rather
# than as a ball: hitting one end spins it, which is most of why they read as noodles.
NOODLES = [
    (1.35, 2.40, "#2EE6A8", 0.6),
    (6.20, 6.10, "#FF8A3D", 2.1),
    (10.40, 1.80, "#4FA8FF", 3.4),
    (12.90, 5.50, "#FFE14D", 5.0),
]
NOODLE_L = 1.70          # length of the capsule
NOODLE_R = 0.10          # its radius, a little over the mesh so contacts are not flush
DUCK_R = 0.42            # a duck, treated as a disc for this
CURRENT = 0.135          # how hard the lazy current pushes, m/s^2. With DAMP this settles
                         # at about 0.25 m/s, which crosses the pool in a minute: drifting,
                         # not racing. At 0.055 they moved 7 m in a minute and looked stuck.
DAMP = 0.55              # velocity lost per second: water, not ice
SPIN_DAMP = 1.1
MAX_SPEED = 0.42
PUSH = 0.55              # fraction of an overlap resolved per frame; damped, so it settles


def _seg(it):
    """The two ends of a noodle, from its centre and heading."""
    hx, hy = math.cos(it["heading"]), math.sin(it["heading"])
    half = NOODLE_L * 0.5 * it["scale"]
    return (it["x"] - hx * half, it["y"] - hy * half), (it["x"] + hx * half, it["y"] + hy * half)


def _closest_on_seg(a, b, p):
    """Closest point to p on segment ab, and how far along it lies (0..1)."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    den = abx * abx + aby * aby
    if den <= 1e-9:
        return a, 0.0
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / den
    t = max(0.0, min(1.0, t))
    return (a[0] + abx * t, a[1] + aby * t), t


def _closest_between(a1, b1, a2, b2):
    """A good-enough closest pair between two segments: try every endpoint against the other
    segment and keep the nearest. Exact for the cases that matter here and far shorter than
    the general solution."""
    best = None
    for p, (u, v), flip in ((a1, (a2, b2), False), (b1, (a2, b2), False),
                            (a2, (a1, b1), True), (b2, (a1, b1), True)):
        q, _t = _closest_on_seg(u, v, p)
        d = math.dist(p, q)
        if best is None or d < best[0]:
            best = (d, (q, p) if flip else (p, q))
    return best[0], best[1][0], best[1][1]


def _ball_mesh(mat):
    me = MS._existing("PropBall")
    if me:
        return me
    b = MS._Builder()
    b.sphere(0.21, at=(0, 0, 0))
    return b.finish("PropBall", [mat])


def _ring_mesh(mat):
    me = MS._existing("PropRing")
    if me:
        return me
    b = MS._Builder()
    b.torus(0.34, 0.10)
    return b.finish("PropRing", [mat])


def _noodle_mesh(mat):
    me = MS._existing("PropNoodle")
    if me:
        return me
    b = MS._Builder()
    b.cylinder(0.075, 1.7, rot=Matrix.Rotation(math.radians(90), 4, "Y"))
    return b.finish("PropNoodle", [mat])


def _lily_mesh(mat):
    me = MS._existing("PropLily")
    if me:
        return me
    b = MS._Builder()
    b.cylinder(0.33, 0.03)
    return b.finish("PropLily", [mat])


def _flamingo_mesh(mat):
    """A ring float with a neck and a head: the one toy anyone would name."""
    me = MS._existing("PropFlamingo")
    if me:
        return me
    b = MS._Builder()
    b.torus(0.36, 0.11)
    b.cylinder(0.055, 0.46, at=(0.30, 0.0, 0.23))
    b.sphere(0.10, at=(0.30, 0.0, 0.48))
    b.cone(0.055, 0.005, 0.16, at=(0.40, 0.0, 0.47), rot=Matrix.Rotation(math.radians(90), 4, "Y"))
    return b.finish("PropFlamingo", [mat])


_MESH = {"ball": _ball_mesh, "ring": _ring_mesh, "noodle": _noodle_mesh,
         "lily": _lily_mesh, "flamingo": _flamingo_mesh}


class PoolProps:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.noodles: list[dict] = []

    def ensure(self) -> None:
        if self.items and self.items[0]["obj"].name in bpy.data.objects:
            return
        self.items = []
        rnd = random.Random(20260919)  # fixed: the toys should be in the same places every run
        for i, (kind, x, y, hexc, scale) in enumerate(LAYOUT):
            mat = M.flat_material(f"Prop_{kind}_{i}", hexc, roughness=0.35)
            obj = P.new_object(f"DP_Prop_{kind}_{i}", _MESH[kind](mat))
            obj.location = (x, y, P.WATER_Z)
            obj.scale = (scale, scale, scale)
            obj["dp_kind"] = "deck"  # decoration: hovering or clicking one does nothing
            self.items.append({
                "obj": obj, "x": x, "y": y, "scale": scale,
                "spin": rnd.uniform(-0.25, 0.25),           # radians per second
                "phase": rnd.uniform(0.0, 6.28),
                "rate": rnd.uniform(0.045, 0.085),          # how fast it wanders its patch
                "lobe": rnd.uniform(0.55, 1.0),             # the wander's second axis
                "heading": rnd.uniform(0.0, 6.28),
            })
        self.noodles = []
        for i, (x, y, hexc, heading) in enumerate(NOODLES):
            mat = M.flat_material(f"Prop_noodle_{i}", hexc, roughness=0.35)
            obj = P.new_object(f"DP_Prop_noodle_{i}", _noodle_mesh(mat))
            obj.location = (x, y, P.WATER_Z)
            obj["dp_kind"] = "deck"
            self.noodles.append({
                "obj": obj, "x": x, "y": y, "scale": 1.0, "heading": heading,
                "vx": 0.0, "vy": 0.0, "spin": 0.0,
                "phase": rnd.uniform(0.0, 6.28),        # where its current is pointing
                "drift": rnd.uniform(0.020, 0.045),     # how fast that direction turns
            })

    def update(self, now: float, dt: float, ducks=None) -> None:
        """Anchored toys drift on their Lissajous path; the noodles are simulated."""
        self._drift_noodles(now, dt, ducks or {})
        for it in self.items:
            obj = it["obj"]
            t = now * it["rate"] * 2 * math.pi + it["phase"]
            try:
                obj.location = (
                    it["x"] + DRIFT * math.sin(t),
                    it["y"] + DRIFT * it["lobe"] * math.sin(2 * t + it["phase"]),
                    P.WATER_Z + BOB * math.sin(t * 3.1 + it["phase"]),
                )
                it["heading"] += it["spin"] * dt
                obj.rotation_euler = (
                    math.radians(4) * math.sin(t * 2.2),
                    math.radians(4) * math.cos(t * 1.7),
                    it["heading"],
                )
            except ReferenceError:  # the scene was reset under us
                return

    def _drift_noodles(self, now: float, dt: float, ducks) -> None:
        """Move the noodles, then push them out of the ducks and out of each other.

        Positions are resolved rather than impulses exchanged: a duck is driven by the motion
        layer and cannot be shoved, so a noodle always yields to one, and two noodles each give
        half. With the water damping this settles in a frame or two and never jitters.
        """
        dt = max(0.0, min(0.1, dt))
        if dt <= 0.0 or not self.noodles:
            return
        margin = NOODLE_R + 0.05
        try:
            for it in self.noodles:
                # a lazy current that slowly changes direction, different for each noodle
                a = it["phase"] + now * it["drift"] * 2 * math.pi
                it["vx"] += math.cos(a) * CURRENT * dt
                it["vy"] += math.sin(a) * CURRENT * dt
                k = math.exp(-DAMP * dt)
                it["vx"] *= k
                it["vy"] *= k
                it["spin"] *= math.exp(-SPIN_DAMP * dt)
                sp = math.hypot(it["vx"], it["vy"])
                if sp > MAX_SPEED:
                    it["vx"] *= MAX_SPEED / sp
                    it["vy"] *= MAX_SPEED / sp
                it["x"] += it["vx"] * dt
                it["y"] += it["vy"] * dt
                it["heading"] += it["spin"] * dt

            for it in self.noodles:
                for d in ducks.values():
                    self._separate(it, (d.x, d.y), DUCK_R, 1.0)
            for i, a in enumerate(self.noodles):
                for b in self.noodles[i + 1:]:
                    self._separate_pair(a, b)
            for it in self.noodles:
                self._keep_in_pool(it, margin)
                it["obj"].location = (it["x"], it["y"], P.WATER_Z + BOB * math.sin(now * 1.7 + it["phase"]))
                it["obj"].rotation_euler = (0.0, math.radians(90), it["heading"])
        except ReferenceError:
            self.noodles = []

    def _separate(self, it, point, radius, yield_all: float) -> None:
        """Push one noodle clear of a disc, and spin it by how far off centre it was hit."""
        a, b = _seg(it)
        c, t = _closest_on_seg(a, b, point)
        nx, ny = c[0] - point[0], c[1] - point[1]
        d = math.hypot(nx, ny)
        overlap = (NOODLE_R + radius) - d
        if overlap <= 0.0:
            return
        if d < 1e-6:
            nx, ny, d = math.cos(it["heading"] + 1.57), math.sin(it["heading"] + 1.57), 1.0
        nx, ny = nx / d, ny / d
        it["x"] += nx * overlap * PUSH * yield_all
        it["y"] += ny * overlap * PUSH * yield_all
        it["vx"] += nx * overlap * 1.2
        it["vy"] += ny * overlap * 1.2
        it["spin"] += (t - 0.5) * overlap * 2.4     # hit an end, it turns; hit the middle, it does not

    def _separate_pair(self, a, b) -> None:
        a1, b1 = _seg(a)
        a2, b2 = _seg(b)
        d, pa, pb = _closest_between(a1, b1, a2, b2)
        overlap = 2 * NOODLE_R - d
        if overlap <= 0.0:
            return
        nx, ny = pa[0] - pb[0], pa[1] - pb[1]
        n = math.hypot(nx, ny)
        if n < 1e-3:
            # Two capsules lying along the same line have no useful contact normal, and the
            # obvious fallback -- push along +x -- slides them down their own axis, which
            # barely changes the distance between the segments. Push across a noodle instead.
            nx, ny, n = -math.sin(a["heading"]), math.cos(a["heading"]), 1.0
        nx, ny = nx / n, ny / n
        for it, sign, contact in ((a, 1.0, pa), (b, -1.0, pb)):
            it["x"] += nx * overlap * 0.5 * PUSH * sign
            it["y"] += ny * overlap * 0.5 * PUSH * sign
            it["vx"] += nx * overlap * 0.6 * sign
            it["vy"] += ny * overlap * 0.6 * sign
            s0, s1 = _seg(it)
            _c, t = _closest_on_seg(s0, s1, contact)
            it["spin"] += (t - 0.5) * overlap * 1.6 * sign

    @staticmethod
    def _keep_in_pool(it, margin: float) -> None:
        """Bounce off the walls on whichever end reached one first."""
        for end in _seg(it):
            for axis, lo, hi, vk in ((0, margin, P.POOL_X - margin, "vx"), (1, margin, P.POOL_Y - margin, "vy")):
                over = lo - end[axis] if end[axis] < lo else (end[axis] - hi if end[axis] > hi else 0.0)
                if over > 0.0:
                    sign = 1.0 if end[axis] < lo else -1.0
                    it["x" if axis == 0 else "y"] += over * sign
                    if it[vk] * sign < 0.0:
                        it[vk] = -it[vk] * 0.55
                    it["spin"] += sign * over * 0.8
