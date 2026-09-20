"""An android sitting on the edge with her feet in the water.

A robot rather than a person on purpose. Duck Pond builds everything from primitives, and a
robot *is* primitives: shells, seams and visible joints read honestly at this poly count,
where a human reads as a mannequin. She also keeps her animation, which a downloaded mesh
would not -- an unrigged import can only sit there.

(Free CC0 model libraries do exist: Quaternius, Kenney, KayKit, indexed on npm by
`@jgengine/assets`. None of them was usable here. The providers' CDNs are blocked by the
network filter on this machine; the only robot reachable on GitHub ships under a Poser EULA,
which cannot go into an MIT repo; and the CC0 packs that are reachable are environment kits,
fantasy humans and skeletons. Drop a `.glb` in and it can be imported instead.)

She carries no data and means nothing, like the floating toys. She is there so the pool looks
occupied rather than like a chart with a duck on it. She idles continuously -- a slow sway,
feet waving in the water -- and every so often leans back on her hands, tips her face up to
the sun and swings her head slowly side to side. Nothing here is allowed to be a statue, and
a motion that only ever loops is nearly one.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P

# The north deck slab starts at y = 8.1; further forward she sat on the water, not the deck,
# and her thighs vanished into the pool edge so her feet read as two loose lumps.
AT = (1.70, 8.18)
# Everything on this deck is built oversized so it reads from across a room: a sangria jug is
# 0.58 m tall here against about 0.28 m in life. Built at life scale she stood barely twice a
# jug's height next to them, where a real person is over three times one.
SCALE = 1.75
HIP_BOTTOM = 0.15            # local z of her underside, so she can be sat on the deck slab
DECK_TOP = 0.10
# Her visor and knees are built on -Y, so zero already points her down the pool at the camera.
FACING = 0.0

SHELL = "#E9EBEF"            # the panels: off-white ceramic
ACCENT = "#C08552"           # rose gold, a hue no signal in this scene uses
JOINT = "#2E3238"            # the dark rubber at every articulation
VISOR = "#14161A"            # her sunglasses, which on an android is a visor

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

# Her right arm is its own object so it can be raised. Built pointing straight up from the
# shoulder, which makes both poses easy to state: REST swings it down and back to the deck,
# WAVE brings it up and out. Blending the X angle between them sweeps through "straight
# forward", which is the arc an arm actually takes.
ARM_SHOULDER = (0.145, 0.03, 0.655)
ARM_REST = (math.radians(-159), math.radians(14), 0.0)
ARM_WAVE = (math.radians(-18), math.radians(30), 0.0)
WAVE_SWING = math.radians(17)   # how far the raised hand swings either side
WAVE_HZ = 0.85
WAVE_EASE = 1.8                 # how fast the arm goes up and comes down, per second.
# Measured: at 2.6 the arm moved 11 deg in a frame at 30 fps, which is a flick rather
# than a raise. At 1.8 the worst frame is about 8 deg and it still reads as prompt.

SH, AC, JT, VI = 0, 1, 2, 3  # material slots


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


def _limb(b, p0, p1, r0, r1, slot=SH, segments=12):
    """A tapered segment from p0 to p1. Placing limbs by joint rather than by eye is the whole
    point: hand-placed cones and spheres did not meet the body and she came apart."""
    a, c = Vector(p0), Vector(p1)
    d = c - a
    b.cone(r0, r1, d.length, at=tuple((a + c) / 2),
           rot=d.to_track_quat("Z", "Y").to_matrix().to_4x4(), slot=slot, segments=segments)


def _body_mesh(shell, accent, joint, visor):
    me = MS._existing("Bather")
    if me:
        return me
    b = MS._Builder()
    b.sphere(1.0, at=(0, 0.02, 0.28), scale=(0.205, 0.165, 0.150), slot=SH)   # hip shell
    b.sphere(1.0, at=(0, 0.02, 0.255), scale=(0.212, 0.172, 0.055), slot=AC)  # hip band
    b.cylinder(0.105, 0.10, at=(0, 0.02, 0.40), slot=JT, segments=16)         # waist joint
    b.sphere(1.0, at=(0, 0.025, 0.56), scale=(0.175, 0.13, 0.195), slot=SH)   # chest shell
    b.sphere(1.0, at=(0, -0.055, 0.575), scale=(0.115, 0.09, 0.115), slot=AC) # chest plate
    b.cylinder(0.052, 0.075, at=(0, 0.02, 0.715), slot=JT, segments=14)       # neck
    # her left arm stays propped on the deck and is part of the body; the right one is a
    # separate object so it can be raised, and only its shoulder ball is built here
    b.sphere(0.058, at=ARM_SHOULDER, slot=JT)
    sx = -1
    shoulder = (sx * 0.145, 0.03, 0.655)
    elbow = (sx * 0.205, 0.165, 0.38)
    hand = (sx * 0.225, 0.255, 0.07)
    b.sphere(0.058, at=shoulder, slot=JT)
    _limb(b, shoulder, elbow, 0.048, 0.040, slot=SH)
    b.sphere(0.042, at=elbow, slot=JT)
    _limb(b, elbow, hand, 0.040, 0.033, slot=SH)
    b.sphere(0.048, at=hand, scale=(1.0, 1.25, 0.65), slot=AC)                # palm on the deck
    return b.finish("Bather", [shell, accent, joint, visor])


def _arm_mesh(shell, accent, joint):
    """Her right arm, origin at the shoulder, built pointing straight up."""
    me = MS._existing("BatherArm")
    if me:
        return me
    b = MS._Builder()
    elbow, hand = (0.018, 0.0, 0.275), (0.048, -0.022, 0.555)
    _limb(b, (0.0, 0.0, 0.0), elbow, 0.048, 0.040, slot=SH)
    b.sphere(0.042, at=elbow, slot=JT)
    _limb(b, elbow, hand, 0.040, 0.033, slot=SH)
    b.sphere(0.049, at=hand, scale=(1.0, 0.72, 1.15), slot=AC)                # the hand itself
    return b.finish("BatherArm", [shell, accent, joint])


def _head_mesh(shell, accent, joint, visor):
    """Head and visor, with the origin at the neck so it can turn and tip."""
    me = MS._existing("BatherHead")
    if me:
        return me
    b = MS._Builder()
    b.sphere(1.0, at=(0, 0.0, 0.13), scale=(0.118, 0.125, 0.135), slot=SH)    # skull
    b.sphere(1.0, at=(0, 0.052, 0.155), scale=(0.132, 0.118, 0.128), slot=AC) # swept crest
    b.sphere(1.0, at=(0, 0.105, 0.02), scale=(0.075, 0.055, 0.115), slot=AC)  # nape, down the back
    b.sphere(1.0, at=(0, -0.055, 0.128), scale=(0.112, 0.085, 0.048), slot=VI)  # wraparound visor
    b.cylinder(0.031, 0.026, at=(0, 0.0, 0.03), slot=JT, segments=12)         # neck collar
    return b.finish("BatherHead", [shell, accent, joint, visor])


def _leg_mesh(shell, accent, joint):
    """One leg, with the origin at the hip so the object can swing from it."""
    me = MS._existing("BatherLeg")
    if me:
        return me
    b = MS._Builder()
    hip, knee, ankle = (0.0, 0.0, 0.0), (0.0, -0.235, -0.115), (0.0, -0.275, -0.60)
    b.sphere(0.064, at=hip, slot=JT)                                          # hip ball
    _limb(b, hip, knee, 0.060, 0.048, slot=SH)                                # thigh
    b.sphere(0.050, at=knee, slot=JT)                                         # knee
    _limb(b, knee, ankle, 0.046, 0.036, slot=SH)                              # shin
    b.sphere(0.038, at=ankle, slot=JT)                                        # ankle
    b.sphere(0.046, at=(0.0, -0.315, -0.625), scale=(0.85, 1.5, 0.6), slot=AC)  # foot
    return b.finish("BatherLeg", [shell, accent, joint])


class Bather:
    def __init__(self) -> None:
        self.body = None
        self.head = None
        self.arm = None
        self.legs: list = []
        self._last_ring = 0.0
        self._wave = 0.0     # 0 propped on the deck, 1 arm up; eased, never snapped

    def ensure(self) -> None:
        if self.body is not None and self.body.name in bpy.data.objects:
            return
        shell = M.flat_material("Shell", SHELL, roughness=0.28)
        accent = M.flat_material("Accent", ACCENT, roughness=0.32)
        joint = M.flat_material("Joint", JOINT, roughness=0.6)
        visor = M.flat_material("Visor", VISOR, roughness=0.08)
        x, y = AT
        self.body = P.new_object("DP_Bather", _body_mesh(shell, accent, joint, visor))
        self.body.location = (x, y, DECK_TOP - HIP_BOTTOM * SCALE)
        self.body.scale = (SCALE, SCALE, SCALE)
        self.body.rotation_euler = (0.0, 0.0, FACING)
        self.body["dp_kind"] = "deck"
        self.head = P.new_object("DP_BatherHead", _head_mesh(shell, accent, joint, visor))
        self.head.parent = self.body
        self.head.location = NECK
        self.head["dp_kind"] = "deck"
        self.arm = P.new_object("DP_BatherArm", _arm_mesh(shell, accent, joint))
        self.arm.parent = self.body
        self.arm.location = ARM_SHOULDER
        self.arm.rotation_euler = ARM_REST
        self.arm["dp_kind"] = "deck"
        self.legs = []
        for i, hip in enumerate(HIPS):
            leg = P.new_object(f"DP_BatherLeg{i}", _leg_mesh(shell, accent, joint))
            leg.parent = self.body
            leg.location = hip
            leg["dp_kind"] = "deck"
            self.legs.append(leg)

    def update(self, now: float, dt: float = 0.0, ripples=None, waving: bool = False) -> None:
        """`waving` is set when at least one duck is waiting on you. She puts her hand up.

        The flag is a step function -- a duck finishes a turn and it flips -- so the arm eases
        toward it rather than following it, and she stops sunbathing while her hand is up: you
        cannot lean back on an arm you are waving with.
        """
        if self.body is None:
            return
        target = 1.0 if waving else 0.0
        self._wave += (target - self._wave) * min(1.0, max(0.0, dt) * WAVE_EASE)
        wave = self._wave
        lean = _envelope(now) * (1.0 - wave)
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
            # the arm: down on the deck, or up and swinging
            self.arm.rotation_euler = (
                ARM_REST[0] + (ARM_WAVE[0] - ARM_REST[0]) * wave,
                ARM_REST[1] + (ARM_WAVE[1] - ARM_REST[1]) * wave
                + WAVE_SWING * wave * math.sin(now * 2 * math.pi * WAVE_HZ),
                0.0,
            )
            # feet waving, livelier when she is stretched out or when she wants your attention
            amp = KICK * (1.0 + 0.7 * lean + 0.5 * wave)
            for i, leg in enumerate(self.legs):
                phase = now * 2 * math.pi * KICK_HZ * (1.0 + 0.5 * lean) + i * math.pi * 0.7
                leg.rotation_euler = (amp * math.sin(phase), 0.0, 0.0)
        except ReferenceError:
            self.body = self.head = self.arm = None
            self.legs = []
            return
        # a small ring at her feet, so the water knows she is there
        if ripples is not None and now - self._last_ring > 2.4:
            self._last_ring = now
            x, y = AT
            ripples.ring(Vector((x, y - 0.42 * SCALE, P.WATER_Z)), size=0.55 * SCALE,
                         color=(0.75, 0.86, 0.92), strength=0.35, life=1.8)
