"""Floating pool toys: the things a real lido has lying about that nothing in the app needs.

They carry no data and mean nothing -- that is the point. Every other object in the pool is a
readout, so the eye has nowhere to rest; a beach ball drifting in the corner gives the scene a
sense of place and makes the ducks look like they are *in* somewhere rather than on a chart.

They keep out of the way on purpose: each one drifts inside its own small patch near the pool
edges, away from the swim lanes, and is marked "deck" so clicking one does nothing.
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
    ("noodle",   14.25, 7.35, "#2EE6A8", 1.0),
    ("lily",      0.75, 0.60, "#2F8F4E", 1.0),
    ("lily",      0.95, 7.40, "#3AA55D", 0.8),
]


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

    def update(self, now: float, dt: float) -> None:
        """Drift each toy around its anchor on a slow Lissajous path, bobbing as it goes."""
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
