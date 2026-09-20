"""Someone sitting on the edge with her feet in the water.

Built from the same primitives as the ducks, so she is stylised and low-poly rather than a
figure: a person-shaped silhouette at pool scale, read at a glance from across a room. She
carries no data and means nothing, like the floating toys. She is there so the pool looks
occupied rather than like a chart with a duck on it.

She idles continuously (a slow sway, feet waving in the water) and every so often leans back
on her hands, tips her face up to the sun and swings her head slowly side to side. Nothing in
this scene is allowed to be a statue, and a motion that only ever loops is nearly one.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P

# The north deck slab starts at y = 8.1; at 8.02 she was sitting on the water, not the deck,
# and her thighs vanished into the pool edge so her feet read as two loose lumps.
AT = (1.70, 8.18)
# Everything on this deck is built oversized so it reads from across a room: a sangria jug is
# 0.58 m tall here against about 0.28 m in life. Built at life scale she stood barely twice a
# jug's height next to them, where a real person is over three times one. SCALE puts her back
# in proportion with the furniture rather than with the metre.
SCALE = 1.75
HIP_BOTTOM = 0.15            # local z of her underside, so she can be sat on the deck slab
DECK_TOP = 0.10
# Her face, sunglasses and knees are all built on -Y, so zero already points her down the
# pool at the camera. The 180 degrees she had turned her back on the room.
FACING = 0.0
SKIN = "#C98B63"
SUIT = "#F4F1EA"
HAIR = "#3A2A22"
GLASS = "#14161A"

NECK = (0.0, 0.02, 0.74)     # where the head pivots, in her local space (-Y is forward)
HIPS = ((0.108, -0.01, 0.28), (-0.108, -0.01, 0.28))

LEAN_EVERY = 34.0            # seconds between sunbathes
LEAN_HOLD = 9.0              # how long she stays back
LEAN_BACK = math.radians(26)
LEAN_RISE = 2.2              # seconds to go back, and to come up again

KICK_HZ = 0.16               # feet waving, all the time
KICK = math.radians(17)
HEAD_HZ = 0.085              # the slow side-to-side while she is looking up
HEAD_YAW = math.radians(26)
HEAD_UP = math.radians(30)
SWAY_HZ = 0.06


def _envelope(now: float) -> float:
    """0 to 1 and back: how far into the lean she is, rising and falling smoothly."""
    t = now % LEAN_EVERY
    if t >= LEAN_HOLD + 2 * LEAN_RISE:
        return 0.0
    if t < LEAN_RISE:
        k = t / LEAN_RISE
    elif t < LEAN_RISE + LEAN_HOLD:
        return 1.0
    else:
        k = 1.0 - (t - LEAN_RISE - LEAN_HOLD) / LEAN_RISE
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, k)))


def _limb(b, p0, p1, r0, r1, slot=0, segments=10):
    """A tapered segment from p0 to p1. Placing limbs by joint rather than by eye is the whole
    point: hand-placed cones and spheres did not meet the body and she came apart."""
    a, c = Vector(p0), Vector(p1)
    d = c - a
    rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    b.cone(r0, r1, d.length, at=tuple((a + c) / 2), rot=rot, slot=slot, segments=segments)


def _body_mesh(skin, suit):
    me = MS._existing("Bather")
    if me:
        return me
    b = MS._Builder()
    b.sphere(1.0, at=(0, 0.02, 0.28), scale=(0.21, 0.17, 0.155), slot=1)     # hips, swimsuit
    b.sphere(1.0, at=(0, 0.025, 0.55), scale=(0.175, 0.13, 0.20), slot=0)    # torso, skin
    b.sphere(1.0, at=(0, 0.02, 0.63), scale=(0.181, 0.137, 0.065), slot=1)   # swimsuit top
    b.sphere(1.0, at=(0, 0.02, 0.40), scale=(0.155, 0.125, 0.13), slot=0)    # waist, joins the two
    for sx in (1, -1):
        shoulder = (sx * 0.145, 0.03, 0.67)
        elbow = (sx * 0.205, 0.165, 0.38)
        hand = (sx * 0.225, 0.255, 0.07)
        b.sphere(0.056, at=shoulder, slot=0)
        _limb(b, shoulder, elbow, 0.048, 0.040)                              # upper arm, back
        _limb(b, elbow, hand, 0.040, 0.034)                                  # forearm, to the deck
        b.sphere(0.05, at=hand, scale=(1.0, 1.25, 0.65), slot=0)             # hand flat on the deck
    return b.finish("Bather", [skin, suit])


def _head_mesh(skin, hair, glass):
    """Head, hair and sunglasses, with the origin at the neck so it can turn and tip."""
    me = MS._existing("BatherHead")
    if me:
        return me
    b = MS._Builder()
    b.sphere(0.125, at=(0, 0.0, 0.13), slot=0)
    b.sphere(0.142, at=(0, 0.045, 0.155), scale=(1.0, 1.0, 0.92), slot=1)    # hair
    b.sphere(0.10, at=(0, 0.10, 0.00), scale=(1.0, 0.7, 1.4), slot=1)        # hair down the back
    b.box(0.215, 0.035, 0.055, at=(0, -0.105, 0.145), slot=2)                # sunglasses
    return b.finish("BatherHead", [skin, hair, glass])


def _leg_mesh(skin):
    """One leg, with the origin at the hip so the object can swing from it."""
    me = MS._existing("BatherLeg")
    if me:
        return me
    b = MS._Builder()
    hip, knee, ankle = (0.0, 0.0, 0.0), (0.0, -0.235, -0.115), (0.0, -0.275, -0.60)
    b.sphere(0.062, at=hip, slot=0)                                          # fills the hip socket
    _limb(b, hip, knee, 0.060, 0.048)                                        # thigh, out over the edge
    b.sphere(0.049, at=knee, slot=0)                                         # knee
    _limb(b, knee, ankle, 0.046, 0.036)                                      # shin, down into the water
    b.sphere(0.048, at=(0.0, -0.315, -0.625), scale=(0.85, 1.5, 0.6), slot=0)   # foot
    return b.finish("BatherLeg", [skin])


class Bather:
    def __init__(self) -> None:
        self.body = None
        self.head = None
        self.legs: list = []
        self._last_ring = 0.0

    def ensure(self) -> None:
        if self.body is not None and self.body.name in bpy.data.objects:
            return
        skin = M.flat_material("Skin", SKIN, roughness=0.65)
        suit = M.flat_material("Swimsuit", SUIT, roughness=0.5)
        hair = M.flat_material("Hair", HAIR, roughness=0.4)
        glass = M.flat_material("Sunglasses", GLASS, roughness=0.12)
        x, y = AT
        self.body = P.new_object("DP_Bather", _body_mesh(skin, suit))
        self.body.location = (x, y, DECK_TOP - HIP_BOTTOM * SCALE)
        self.body.scale = (SCALE, SCALE, SCALE)
        self.body.rotation_euler = (0.0, 0.0, FACING)
        self.body["dp_kind"] = "deck"
        self.head = P.new_object("DP_BatherHead", _head_mesh(skin, hair, glass))
        self.head.parent = self.body
        self.head.location = NECK
        self.head["dp_kind"] = "deck"
        self.legs = []
        for i, hip in enumerate(HIPS):
            leg = P.new_object(f"DP_BatherLeg{i}", _leg_mesh(skin))
            leg.parent = self.body
            leg.location = hip
            leg["dp_kind"] = "deck"
            self.legs.append(leg)

    def update(self, now: float, ripples=None) -> None:
        if self.body is None:
            return
        lean = _envelope(now)
        try:
            # back on her hands during the lean; the rest of the time she just sways
            self.body.rotation_euler = (
                math.radians(2.5) * math.sin(now * 2 * math.pi * SWAY_HZ) + LEAN_BACK * lean,
                0.0,
                FACING + math.radians(2.0) * math.sin(now * 2 * math.pi * SWAY_HZ * 0.6),
            )
            # face up to the sun as she goes back, and swing it slowly side to side while there
            self.head.rotation_euler = (
                -HEAD_UP * lean,
                0.0,
                HEAD_YAW * lean * math.sin(now * 2 * math.pi * HEAD_HZ),
            )
            # feet waving, livelier when she is stretched out
            amp = KICK * (1.0 + 0.7 * lean)
            for i, leg in enumerate(self.legs):
                phase = now * 2 * math.pi * KICK_HZ * (1.0 + 0.5 * lean) + i * math.pi * 0.7
                leg.rotation_euler = (amp * math.sin(phase), 0.0, 0.0)
        except ReferenceError:
            self.body = self.head = None
            self.legs = []
            return
        # a small ring at her feet, so the water knows she is there
        if ripples is not None and now - self._last_ring > 2.4:
            self._last_ring = now
            x, y = AT
            ripples.ring(Vector((x, y - 0.42 * SCALE, P.WATER_Z)), size=0.55 * SCALE,
                         color=(0.75, 0.86, 0.92), strength=0.35, life=1.8)
