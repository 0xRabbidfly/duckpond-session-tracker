"""Procedural meshes built with bmesh (no external .blend needed)."""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

PREFIX = "DP_"

# duck local frame: faces +X, waterline z=0
HEAD_TOP = Vector((0.19, 0.0, 0.38))
TAIL_TIP = Vector((-0.36, 0.0, 0.22))
CHEST = Vector((0.30, 0.0, 0.10))


def _T(x, y, z):
    return Matrix.Translation((x, y, z))


def _S(x, y, z):
    return Matrix.Diagonal((x, y, z, 1.0))


def _RY(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Y")


def _RZ(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Z")


class _Builder:
    def __init__(self) -> None:
        self.bm = bmesh.new()

    def _mark(self):
        return len(self.bm.faces)

    def _assign(self, start: int, slot: int, smooth: bool = True):
        self.bm.faces.ensure_lookup_table()
        for f in self.bm.faces[start:]:
            f.material_index = slot
            f.smooth = smooth

    def sphere(self, r, at=(0, 0, 0), scale=(1, 1, 1), slot=0, u=20, v=12):
        m = self._mark()
        bmesh.ops.create_uvsphere(self.bm, u_segments=u, v_segments=v, radius=r,
                                  matrix=_T(*at) @ _S(*scale))
        self._assign(m, slot)

    def cone(self, r1, r2, depth, at=(0, 0, 0), rot=None, slot=0, segments=20, smooth=True):
        m = self._mark()
        mat = _T(*at) @ (rot or Matrix.Identity(4))
        bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=r1, radius2=r2, depth=depth, matrix=mat)
        self._assign(m, slot, smooth)

    def cylinder(self, r, depth, at=(0, 0, 0), rot=None, slot=0, segments=24, smooth=True):
        self.cone(r, r, depth, at, rot, slot, segments, smooth)

    def box(self, sx, sy, sz, at=(0, 0, 0), rot=None, slot=0):
        m = self._mark()
        mat = _T(*at) @ (rot or Matrix.Identity(4)) @ _S(sx, sy, sz)
        bmesh.ops.create_cube(self.bm, size=1.0, matrix=mat)
        self._assign(m, slot, smooth=False)

    def torus(self, R, r, at=(0, 0, 0), slot=0, seg_major=32, seg_minor=12):
        m = self._mark()
        bm = self.bm
        ring = []
        for i in range(seg_major):
            a = 2 * math.pi * i / seg_major
            row = []
            for j in range(seg_minor):
                b = 2 * math.pi * j / seg_minor
                x = (R + r * math.cos(b)) * math.cos(a) + at[0]
                y = (R + r * math.cos(b)) * math.sin(a) + at[1]
                z = r * math.sin(b) + at[2]
                row.append(bm.verts.new((x, y, z)))
            ring.append(row)
        for i in range(seg_major):
            for j in range(seg_minor):
                v1 = ring[i][j]
                v2 = ring[(i + 1) % seg_major][j]
                v3 = ring[(i + 1) % seg_major][(j + 1) % seg_minor]
                v4 = ring[i][(j + 1) % seg_minor]
                bm.faces.new((v1, v2, v3, v4))
        self._assign(m, slot)

    def annulus(self, r_in, r_out, segments=48, slot=0):
        m = self._mark()
        bm = self.bm
        inner, outer = [], []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            inner.append(bm.verts.new((r_in * math.cos(a), r_in * math.sin(a), 0.0)))
            outer.append(bm.verts.new((r_out * math.cos(a), r_out * math.sin(a), 0.0)))
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((inner[i], outer[i], outer[j], inner[j]))
        self._assign(m, slot, smooth=False)

    def grid(self, sx, sy, nx, ny, at=(0, 0, 0), slot=0):
        m = self._mark()
        bm = self.bm
        rows = []
        for j in range(ny + 1):
            row = []
            for i in range(nx + 1):
                row.append(bm.verts.new((at[0] + sx * i / nx, at[1] + sy * j / ny, at[2])))
            rows.append(row)
        for j in range(ny):
            for i in range(nx):
                bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
        self._assign(m, slot, smooth=True)

    def finish(self, name: str, materials) -> bpy.types.Mesh:
        me = bpy.data.meshes.new(PREFIX + name)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-6)
        self.bm.to_mesh(me)
        self.bm.free()
        for mat in materials:
            me.materials.append(mat)
        return me


def _existing(name: str):
    return bpy.data.meshes.get(PREFIX + name)


# ---------------------------------------------------------------- duck
def duck_mesh(body_mat, bill_mat, eye_mat) -> bpy.types.Mesh:
    me = _existing("Duck")
    if me:
        return me
    b = _Builder()
    b.sphere(1.0, at=(0, 0, 0.06), scale=(0.30, 0.21, 0.17), slot=0)  # body
    b.sphere(0.14, at=(0.19, 0, 0.24), slot=0)  # head
    b.cone(0.055, 0.02, 0.14, at=(0.36, 0, 0.21), rot=_RY(90), slot=1, segments=16)  # bill
    b.sphere(0.022, at=(0.28, 0.095, 0.28), slot=2, u=10, v=6)
    b.sphere(0.022, at=(0.28, -0.095, 0.28), slot=2, u=10, v=6)
    b.cone(0.075, 0.0, 0.18, at=(-0.30, 0, 0.14), rot=_RY(-55), slot=0, segments=14)  # tail
    return b.finish("Duck", [body_mat, bill_mat, eye_mat])


# ---------------------------------------------------------------- hats (origin at hat base)
def hat_mesh(kind: str, main_mat, accent_mat) -> bpy.types.Mesh:
    me = _existing(f"Hat_{kind}")
    if me:
        return me
    b = _Builder()
    if kind == "top_hat":
        b.cylinder(0.085, 0.17, at=(0, 0, 0.085), slot=0)
        b.cylinder(0.135, 0.012, at=(0, 0, 0.006), slot=0)
        b.cylinder(0.088, 0.02, at=(0, 0, 0.03), slot=1)  # band
    elif kind == "wizard":
        b.cone(0.11, 0.0, 0.30, at=(0, 0, 0.15), rot=_RY(-8), slot=0, segments=20)
        b.cylinder(0.16, 0.012, at=(0, 0, 0.006), slot=0)
        for i, (x, y, z) in enumerate(((0.05, 0.03, 0.10), (-0.04, 0.05, 0.16), (0.02, -0.06, 0.20))):
            b.sphere(0.014, at=(x, y, z), slot=1, u=8, v=5)
    elif kind == "beret":
        b.sphere(1.0, at=(0.01, 0, 0.03), scale=(0.135, 0.135, 0.055), slot=0)
        b.cylinder(0.012, 0.035, at=(0.01, 0, 0.09), slot=1, segments=10)
    elif kind == "kasa":
        b.cone(0.23, 0.0, 0.13, at=(0, 0, 0.065), slot=0, segments=24)
        b.cylinder(0.02, 0.02, at=(0, 0, 0.135), slot=1, segments=10)
    elif kind == "crown":
        b.cylinder(0.09, 0.09, at=(0, 0, 0.045), slot=0, segments=12, smooth=False)
        for i in range(6):
            a = 2 * math.pi * i / 6
            b.cone(0.022, 0.0, 0.06, at=(0.08 * math.cos(a), 0.08 * math.sin(a), 0.12), slot=0, segments=6, smooth=False)
        b.sphere(0.022, at=(0, 0, 0.16), slot=1, u=10, v=6)
    elif kind == "cap":
        b.sphere(1.0, at=(0, 0, 0.02), scale=(0.105, 0.105, 0.075), slot=0)
        b.box(0.13, 0.11, 0.012, at=(0.11, 0, 0.02), slot=0)
        b.sphere(0.014, at=(0, 0, 0.095), slot=1, u=8, v=5)
    elif kind == "propeller":
        b.sphere(1.0, at=(0, 0, 0.02), scale=(0.105, 0.105, 0.075), slot=0)
        b.cylinder(0.008, 0.05, at=(0, 0, 0.11), slot=1, segments=8)
        b.box(0.20, 0.03, 0.006, at=(0, 0, 0.135), slot=1)
        b.box(0.03, 0.20, 0.006, at=(0, 0, 0.135), slot=1)
    else:  # newspaper boat: 4-sided pyramid squashed into a hull
        b.cone(0.16, 0.0, 0.13, at=(0, 0, 0.065), rot=_RZ(45), slot=0, segments=4, smooth=False)
        b.box(0.22, 0.02, 0.01, at=(0, 0, 0.005), rot=_RZ(45), slot=1)
    return b.finish(f"Hat_{kind}", [main_mat, accent_mat])


# ---------------------------------------------------------------- misc
def ring_mesh(mat) -> bpy.types.Mesh:
    me = _existing("Ring")
    if me:
        return me
    b = _Builder()
    b.annulus(0.10, 0.125)
    return b.finish("Ring", [mat])


def sphere_mesh(name: str, r: float, mat) -> bpy.types.Mesh:
    me = _existing(name)
    if me:
        return me
    b = _Builder()
    b.sphere(r, u=14, v=8)
    return b.finish(name, [mat])


def lifering_mesh(mat_a, mat_b) -> bpy.types.Mesh:
    me = _existing("LifeRing")
    if me:
        return me
    b = _Builder()
    b.torus(0.175, 0.03, slot=0)
    return b.finish("LifeRing", [mat_a, mat_b])


def box_mesh(name: str, sx, sy, sz, mat, at=(0, 0, 0)) -> bpy.types.Mesh:
    me = _existing(name)
    if me:
        return me
    b = _Builder()
    b.box(sx, sy, sz, at=at)
    return b.finish(name, [mat])


def grid_mesh(name: str, sx, sy, nx, ny, mat) -> bpy.types.Mesh:
    me = _existing(name)
    if me:
        return me
    b = _Builder()
    b.grid(sx, sy, nx, ny)
    return b.finish(name, [mat])


def lane_rope_mesh(length: float, mat) -> bpy.types.Mesh:
    """Rope along +X from 0..length with floats every metre."""
    name = f"LaneRope_{int(length * 10)}"
    me = _existing(name)
    if me:
        return me
    b = _Builder()
    b.cylinder(0.012, length, at=(length / 2, 0, 0), rot=_RY(90), slot=0, segments=8)
    x = 0.5
    while x < length:
        b.sphere(0.06, at=(x, 0, 0), slot=0, u=10, v=6)
        x += 1.0
    return b.finish(name, [mat])


def ladder_mesh(mat) -> bpy.types.Mesh:
    me = _existing("Ladder")
    if me:
        return me
    b = _Builder()
    for y in (-0.25, 0.25):
        b.cylinder(0.02, 1.9, at=(0, y, -0.65), slot=0, segments=10)
        b.cylinder(0.02, 0.5, at=(-0.25, y, 0.3), rot=_RY(90), slot=0, segments=10)
        b.cylinder(0.02, 0.9, at=(-0.5, y, 0.05), slot=0, segments=10)
    for z in (-1.2, -0.8, -0.4, 0.0):
        b.cylinder(0.018, 0.5, at=(0, 0, z), rot=Matrix.Rotation(math.radians(90), 4, "X"), slot=0, segments=10)
    return b.finish("Ladder", [mat])


# ---------------------------------------------------------------- reimagined additions
def pole_mesh(mat) -> bpy.types.Mesh:
    """Beacon pole (0..1.1 m) — the light ball is a separate object so it can pulse."""
    me = _existing("Pole")
    if me:
        return me
    b = _Builder()
    b.cylinder(0.012, 1.1, at=(0, 0, 0.55), slot=0, segments=8)
    return b.finish("Pole", [mat])


def halo_mesh(mat) -> bpy.types.Mesh:
    """Flat glowing ring on the water under a duck: its state colour, always visible."""
    me = _existing("Halo")
    if me:
        return me
    b = _Builder()
    b.annulus(0.40, 0.52, segments=64)
    return b.finish("Halo", [mat])


def coin_mesh(mat) -> bpy.types.Mesh:
    me = _existing("Coin")
    if me:
        return me
    b = _Builder()
    b.cylinder(0.11, 0.035, at=(0, 0, 0.0175), slot=0, segments=20)
    return b.finish("Coin", [mat])


def plate_mesh(name: str, sx: float, sy: float, mat) -> bpy.types.Mesh:
    """Thin dark plate: backs the scoreboard and lane signs so text reads against any water."""
    me = _existing(name)
    if me:
        return me
    b = _Builder()
    b.box(sx, sy, 0.02)
    return b.finish(name, [mat])


def drop_mesh(mat) -> bpy.types.Mesh:
    """Raindrop: a thin vertical capsule."""
    me = _existing("Drop")
    if me:
        return me
    b = _Builder()
    b.sphere(1.0, scale=(0.018, 0.018, 0.16), u=8, v=5)
    return b.finish("Drop", [mat])


def tray_mesh(mat) -> bpy.types.Mesh:
    """A queued-prompt 'letter': a small flat amber slab."""
    me = _existing("Tray")
    if me:
        return me
    b = _Builder()
    b.box(0.16, 0.11, 0.025)
    return b.finish("Tray", [mat])
