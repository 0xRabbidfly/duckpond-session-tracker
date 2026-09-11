"""Ripple rings on the water and bubbles for tool calls. Pooled objects."""
from __future__ import annotations

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P

RING_POOL = 96
BUBBLE_POOL = 48
RING_LIFE = 1.6
BUBBLE_LIFE = 1.3
WHITE = (0.9, 0.97, 1.0)
RED = (1.0, 0.15, 0.1)


class _Ring:
    __slots__ = ("obj", "age", "life", "size", "color", "strength")

    def __init__(self, obj, size, color, strength, life):
        self.obj = obj
        self.age = 0.0
        self.life = life
        self.size = size
        self.color = color
        self.strength = strength


class _Bubble:
    __slots__ = ("obj", "age", "vel")

    def __init__(self, obj, vel):
        self.obj = obj
        self.age = 0.0
        self.vel = vel


class Ripples:
    def __init__(self) -> None:
        self.rings: list[bpy.types.Object] = []
        self.bubbles: list[bpy.types.Object] = []
        self.free_rings: list[bpy.types.Object] = []
        self.free_bubbles: list[bpy.types.Object] = []
        self.active_rings: list[_Ring] = []
        self.active_bubbles: list[_Bubble] = []

    def ensure_pools(self) -> None:
        if self.rings:
            return
        ring_mesh = MS.ring_mesh(M.ring_material())
        for i in range(RING_POOL):
            o = P.new_object(f"DP_Ring_{i:03d}", ring_mesh)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "fx"
            self.rings.append(o)
        self.free_rings = list(self.rings)
        bmesh_ = MS.sphere_mesh("Bubble", 0.02, M.bubble_material())
        for i in range(BUBBLE_POOL):
            o = P.new_object(f"DP_Bubble_{i:03d}", bmesh_)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "fx"
            self.bubbles.append(o)
        self.free_bubbles = list(self.bubbles)

    def ring(self, pos: Vector, size: float = 1.0, color=WHITE, strength: float = 0.8, life: float = RING_LIFE) -> None:
        self.ensure_pools()
        if not self.free_rings:
            return
        o = self.free_rings.pop()
        o.location = (pos.x, pos.y, P.WATER_Z + 0.01)
        o.scale = (size, size, 1.0)
        o.color = (color[0], color[1], color[2], strength)
        o.hide_viewport = False
        o.hide_render = False
        self.active_rings.append(_Ring(o, size, color, strength, life))

    def bubbles_at(self, pos: Vector, count: int = 4, color=None) -> None:
        self.ensure_pools()
        import random
        for _ in range(count):
            if not self.free_bubbles:
                return
            o = self.free_bubbles.pop()
            o.location = (pos.x + random.uniform(-0.08, 0.08), pos.y + random.uniform(-0.08, 0.08), P.WATER_Z - 0.25)
            o.scale = (1, 1, 1)
            c = color or (0.85, 0.95, 1.0)
            o.color = (c[0], c[1], c[2], 0.55)
            o.hide_viewport = False
            o.hide_render = False
            self.active_bubbles.append(_Bubble(o, Vector((random.uniform(-0.05, 0.05), random.uniform(-0.05, 0.05), random.uniform(0.25, 0.4)))))

    def update(self, dt: float) -> None:
        for r in list(self.active_rings):
            r.age += dt
            k = r.age / r.life
            if k >= 1.0:
                self._free_ring(r)
                continue
            grow = 1.0 + 7.0 * k
            r.obj.scale = (r.size * grow, r.size * grow, 1.0)
            c = r.color
            r.obj.color = (c[0], c[1], c[2], r.strength * (1.0 - k) ** 1.5)
        for b in list(self.active_bubbles):
            b.age += dt
            if b.age >= BUBBLE_LIFE or b.obj.location.z >= P.WATER_Z:
                self._free_bubble(b)
                continue
            b.obj.location = Vector(b.obj.location) + b.vel * dt
            s = 1.0 + b.age * 0.6
            b.obj.scale = (s, s, s)

    def _free_ring(self, r: _Ring) -> None:
        self.active_rings.remove(r)
        r.obj.hide_viewport = True
        r.obj.hide_render = True
        self.free_rings.append(r.obj)

    def _free_bubble(self, b: _Bubble) -> None:
        self.active_bubbles.remove(b)
        b.obj.hide_viewport = True
        b.obj.hide_render = True
        self.free_bubbles.append(b.obj)

    def clear(self) -> None:
        for r in list(self.active_rings):
            self._free_ring(r)
        for b in list(self.active_bubbles):
            self._free_bubble(b)
