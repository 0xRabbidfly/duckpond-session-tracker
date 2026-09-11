"""Event effects: tool chips, prompt drops, report risers, geysers, thought bubbles, rain.

Everything is pooled and driven from Python each frame. The vertical axis is the metaphor:
you are the sky (prompts fall in, reports rise out), tools are under the water (the duck
dips its head), peers are on the surface (tethers). A chip names the tool in a word and a
colour so a Bash call, an edit, a read, a web fetch and a test run each look different.
"""
from __future__ import annotations

import math
import random
from typing import List, Optional

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P
from ..theme import STATE_COLORS, hex_to_rgba, tool_chip

CHIP_POOL = 48
ORB_POOL = 48
RAIN_POOL = 90
CHIP_LIFE = 2.2
DROP_S = 0.75
RISE_S = 1.4
SKY_Z = 4.5
GOLD = hex_to_rgba("#F5C542")
AMBER = hex_to_rgba("#FFB347")
RED = hex_to_rgba("#FF3B30")
WHITE = hex_to_rgba("#F4F8FF")


class _Chip:
    __slots__ = ("obj", "age", "life", "start", "rise", "color")

    def __init__(self, obj, start, rise, color, life=CHIP_LIFE):
        self.obj, self.age, self.life, self.start, self.rise, self.color = obj, 0.0, life, start, rise, color


class _Orb:
    __slots__ = ("obj", "age", "life", "a", "b", "color", "kind", "on_land")

    def __init__(self, obj, a, b, color, kind, life, on_land=None):
        self.obj, self.age, self.life, self.a, self.b, self.color, self.kind, self.on_land = obj, 0.0, life, a, b, color, kind, on_land


class _Drop:
    __slots__ = ("obj", "vz")

    def __init__(self, obj, vz):
        self.obj, self.vz = obj, vz


class FX:
    def __init__(self) -> None:
        self.chips: List[bpy.types.Object] = []
        self.free_chips: List[bpy.types.Object] = []
        self.active_chips: List[_Chip] = []
        self.orbs: List[bpy.types.Object] = []
        self.free_orbs: List[bpy.types.Object] = []
        self.active_orbs: List[_Orb] = []
        self.drops: List[bpy.types.Object] = []
        self.free_drops: List[bpy.types.Object] = []
        self.active_drops: List[_Drop] = []
        self.rain = 0.0  # 0..1 intensity, set by the world layer
        self._rain_acc = 0.0

    # ------------------------------------------------------------ pools
    def ensure_pools(self) -> None:
        if self.chips:
            return
        cam = P.camera()
        for i in range(CHIP_POOL):
            cu = bpy.data.curves.new(f"DP_Chip_{i:02d}", "FONT")
            cu.body = ""
            cu.size = 0.30
            cu.align_x = "CENTER"
            cu.materials.append(M.object_text_material())
            o = P.new_object(f"DP_Chip_{i:02d}", cu)
            c = o.constraints.new("COPY_ROTATION")
            c.target = cam
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "fx"
            self.chips.append(o)
        self.free_chips = list(self.chips)
        mesh = MS.sphere_mesh("Orb", 0.07, M.glow_material())
        for i in range(ORB_POOL):
            o = P.new_object(f"DP_Orb_{i:02d}", mesh)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "fx"
            self.orbs.append(o)
        self.free_orbs = list(self.orbs)
        dmesh = MS.drop_mesh(M.glow_material())
        for i in range(RAIN_POOL):
            o = P.new_object(f"DP_Rain_{i:02d}", dmesh)
            o.color = (0.75, 0.86, 1.0, 0.8)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "fx"
            self.drops.append(o)
        self.free_drops = list(self.drops)

    @staticmethod
    def _show(o, on: bool) -> None:
        if o.hide_viewport == on:
            o.hide_viewport = not on
            o.hide_render = not on

    # ------------------------------------------------------------ chips
    def chip(self, pos: Vector, text: str, color, rise: float = 0.7, life: float = CHIP_LIFE, size: float = 0.30) -> None:
        """A word that pops out of the duck and floats up, fading. Screen-aligned."""
        self.ensure_pools()
        if not self.free_chips:
            return
        o = self.free_chips.pop()
        o.data.body = text
        o.data.size = size
        o.color = (color[0], color[1], color[2], 1.0)
        o.location = pos
        self._show(o, True)
        self.active_chips.append(_Chip(o, pos.copy(), rise, color, life))

    def tool_chip(self, pos: Vector, category: str) -> None:
        text, hexc = tool_chip(category)
        col = hex_to_rgba(hexc)
        if category == "bash":
            col = hex_to_rgba("#E6E9F2")  # dark chips vanish against the water; bash reads as pale
        self.chip(pos + Vector((0.65, 0.0, 0.05)), text, col, rise=0.6)

    def tool_done(self, pos: Vector, category: str, ok: bool) -> None:
        if category == "test":
            self.chip(pos + Vector((0.65, 0.0, 0.05)), "tests pass" if ok else "tests FAIL",
                      hex_to_rgba("#4CD964") if ok else RED, rise=0.9, life=3.0, size=0.34)
        elif not ok:
            self.chip(pos + Vector((0.65, 0.0, 0.05)), "error", RED, rise=0.9, life=2.6)

    def denied(self, pos: Vector, kind: str) -> None:
        self.chip(pos + Vector((0.65, 0.0, 0.05)), "denied" if kind == "user-rejected" else "blocked by rule",
                  RED, rise=0.9, life=3.0, size=0.36)

    def question(self, pos: Vector) -> None:
        self.chip(pos + Vector((0.65, 0.0, 0.05)), "asking you", hex_to_rgba(STATE_COLORS["awaiting_user"]),
                  rise=0.6, life=3.5, size=0.36)

    def queued(self, pos: Vector) -> None:
        self.chip(pos + Vector((0.65, 0.0, 0.05)), "+1 queued", AMBER, rise=0.6, life=2.5, size=0.26)

    # ------------------------------------------------------------ orbs (drops and risers)
    def _orb(self, a: Vector, b: Vector, color, kind: str, life: float, on_land=None) -> None:
        self.ensure_pools()
        if not self.free_orbs:
            return
        o = self.free_orbs.pop()
        o.location = a
        o.scale = (1, 1, 1)
        o.color = color
        self._show(o, True)
        self.active_orbs.append(_Orb(o, a.copy(), b.copy(), color, kind, life, on_land))

    def prompt_drop(self, target: Vector, on_land=None) -> None:
        """Your prompt falls out of the sky onto the duck and splashes."""
        self._orb(Vector((target.x, target.y, SKY_Z)), target, AMBER, "drop", DROP_S, on_land)

    def report_up(self, origin: Vector) -> None:
        """The finished report rises out of the duck up to you."""
        self._orb(origin, Vector((origin.x, origin.y, SKY_Z)), GOLD, "rise", RISE_S)

    def thought(self, head: Vector) -> None:
        """Three small bubbles drifting up from the head: thinking, not yet speaking."""
        for i in range(3):
            off = Vector((random.uniform(-0.08, 0.08), random.uniform(-0.08, 0.08), 0.18 + 0.12 * i))
            self._orb(head + off, head + off + Vector((0.0, 0.0, 0.45)), (0.95, 0.98, 1.0, 0.75), "thought", 1.1 + 0.15 * i)

    def geyser(self, pos: Vector, ripples) -> None:
        """Context compaction: the duck blows everything out and pops back up."""
        for _ in range(14):
            off = Vector((random.uniform(-0.15, 0.15), random.uniform(-0.15, 0.15), 0.0))
            top = pos + off * 3.0 + Vector((0.0, 0.0, random.uniform(1.6, 2.6)))
            self._orb(pos + off, top, (0.85, 0.95, 1.0, 0.9), "geyser", random.uniform(0.7, 1.1))
        ripples.ring(Vector((pos.x, pos.y, 0.0)), size=2.6, color=(0.9, 0.97, 1.0), strength=0.9, life=2.5)
        self.chip(pos + Vector((0.0, 0.0, 1.2)), "compacted", WHITE, rise=1.0, life=3.0, size=0.34)

    # ------------------------------------------------------------ frame
    def update(self, dt: float) -> None:
        for c in list(self.active_chips):
            c.age += dt
            k = c.age / c.life
            if k >= 1.0:
                self.active_chips.remove(c)
                self._show(c.obj, False)
                c.obj.data.body = ""
                self.free_chips.append(c.obj)
                continue
            ease = 1.0 - (1.0 - k) ** 2
            c.obj.location = c.start + Vector((0.0, 0.0, c.rise * ease))
            pop = 1.0 + 0.35 * math.exp(-k * 9.0)
            c.obj.scale = (pop, pop, pop)
            alpha = 1.0 if k < 0.6 else (1.0 - k) / 0.4
            col = c.color
            c.obj.color = (col[0], col[1], col[2], alpha)
        for o in list(self.active_orbs):
            o.age += dt
            k = o.age / o.life
            if k >= 1.0:
                if o.kind == "drop" and o.on_land:
                    o.on_land(o.b)
                self.active_orbs.remove(o)
                self._show(o.obj, False)
                self.free_orbs.append(o.obj)
                continue
            if o.kind == "drop":
                e = k * k  # gravity
                alpha = 1.0
                s = 1.0
            elif o.kind == "rise":
                e = 1.0 - (1.0 - k) ** 3  # fast launch, slow fade at the top
                alpha = 1.0 - k ** 2
                s = 1.0 + 0.6 * k
            elif o.kind == "geyser":
                e = 1.0 - (1.0 - k) ** 2
                alpha = 1.0 - k
                s = 0.6 + 0.6 * k
            else:  # thought
                e = k
                alpha = 1.0 - k
                s = 0.45 + 0.5 * k
            o.obj.location = o.a.lerp(o.b, e)
            o.obj.scale = (s, s, s)
            c = o.color
            o.obj.color = (c[0], c[1], c[2], c[3] * alpha)
        self._rain_step(dt)

    # ------------------------------------------------------------ rain (errors)
    def _rain_step(self, dt: float) -> None:
        if self.rain > 0.02 and self.free_drops:
            self._rain_acc += dt * self.rain * 140.0
            while self._rain_acc >= 1.0 and self.free_drops:
                self._rain_acc -= 1.0
                o = self.free_drops.pop()
                o.location = (random.uniform(-1.0, P.POOL_X + 1.0), random.uniform(-1.0, P.POOL_Y + 1.0), random.uniform(3.5, 5.5))
                self._show(o, True)
                self.active_drops.append(_Drop(o, random.uniform(5.5, 7.5)))
        for d in list(self.active_drops):
            z = d.obj.location.z - d.vz * dt
            if z <= P.WATER_Z:
                self.active_drops.remove(d)
                self._show(d.obj, False)
                self.free_drops.append(d.obj)
                continue
            d.obj.location.z = z

    def clear(self) -> None:
        for c in list(self.active_chips):
            self.active_chips.remove(c)
            self._show(c.obj, False)
            self.free_chips.append(c.obj)
        for o in list(self.active_orbs):
            self.active_orbs.remove(o)
            self._show(o.obj, False)
            self.free_orbs.append(o.obj)
        for d in list(self.active_drops):
            self.active_drops.remove(d)
            self._show(d.obj, False)
            self.free_drops.append(d.obj)
