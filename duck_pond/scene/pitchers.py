"""Two jugs of sangria on a table: your Anthropic limits, as drinks.

The 5-hour window and the 7-day window each get a jug. How full it is, is how much of that
window you have spent; the label under it says when it clears. Numbers for both come from the
Claude Code CLI (see `usage_limits`), so an empty jug means a fresh window and a full one
means you are about to be cut off.

It reads at a glance from across a room, which a percentage on a board does not.
"""
from __future__ import annotations

import bpy
from mathutils import Vector

from ..theme import hex_to_rgba
from . import materials as M
from . import meshes as MS
from . import pool as P
from .deck import _text

TABLE_AT = (15.15, 9.35)   # the outer corner of the north-east deck, well back from the water
TABLE_R = 1.15
TABLE_TOP_Z = 0.92
JUG_DX = 0.58              # the two jugs either side of the table's centre
JUG_R, JUG_H = 0.26, 0.72
WALL = 0.016               # glass thickness, so the sangria sits inside the jug
# The labels float above the jugs, not under them: below, they sat over the busy end of the
# pool. They are wider apart than the jugs and overhang the table, because they are signage
# rather than furniture -- and they are scaled to the camera at the lane signs' own reference
# distance, so a jug label and a lane sign are exactly the same size on screen.
LABEL_DX = 1.36
LABEL_DY = -0.22
LABEL_Z = 2.20
LABEL_REF_DIST = 15.2
PLATE_W, PLATE_H = 1.78, 1.00
SANGRIA = "#8E0A2C"        # deep: the frosted glass in front lightens whatever is behind it
SANGRIA_LOW = "#C43A2E"    # barely touched: lighter, like a jug just poured
FRUIT = "#F0A030"

WINDOWS = (("5 HOURS", "session"), ("THIS WEEK", "week"))


def _jug_mesh(glass_mat):
    me = MS._existing("Jug")
    if me:
        return me
    b = MS._Builder()
    b.cylinder(JUG_R, JUG_H, at=(0, 0, JUG_H / 2), segments=28)
    b.torus(JUG_R, 0.018, at=(0, 0, JUG_H), seg_major=28, seg_minor=8)   # rim
    b.torus(0.085, 0.022, at=(JUG_R + 0.05, 0, JUG_H * 0.6), seg_major=20, seg_minor=8)  # handle
    return b.finish("Jug", [glass_mat])


def _fill_mesh(mat):
    """A unit-height cylinder; the object's z scale is how full the jug is."""
    me = MS._existing("JugFill")
    if me:
        return me
    b = MS._Builder()
    b.cylinder(JUG_R - WALL, 1.0, at=(0, 0, 0.5), segments=26)
    return b.finish("JugFill", [mat])


def _table_mesh(mat):
    me = MS._existing("SangriaTable")
    if me:
        return me
    b = MS._Builder()
    b.cylinder(TABLE_R, 0.06, at=(0, 0, TABLE_TOP_Z), segments=32)          # top
    b.cylinder(0.075, TABLE_TOP_Z, at=(0, 0, TABLE_TOP_Z / 2), segments=16)  # stem
    b.cylinder(0.34, 0.04, at=(0, 0, 0.02), segments=24)                     # foot
    return b.finish("SangriaTable", [mat])


class Pitchers:
    """The table, the two jugs, and a label under each."""

    def __init__(self) -> None:
        self.objects: dict = {}
        self.last_text: dict[str, str] = {}

    def ensure(self) -> None:
        if self.objects and self.objects["table"].name in bpy.data.objects:
            return
        self.objects = {}
        x, y = TABLE_AT
        glass = M.glass_material()
        table = P.new_object("DP_SangriaTable", _table_mesh(M.flat_material("TableTop", "#2B3444", roughness=0.45)))
        table.location = (x, y, 0.0)
        table["dp_kind"] = "deck"
        self.objects["table"] = table
        for i, (title, key) in enumerate(WINDOWS):
            dx = JUG_DX * (i * 2 - 1)
            jug = P.new_object(f"DP_Jug_{key}", _jug_mesh(glass))
            jug.location = (x + dx, y, TABLE_TOP_Z + 0.03)
            fill = P.new_object(f"DP_JugFill_{key}", _fill_mesh(
                M.object_color_material("Sangria", roughness=0.12, emission=0.0, alpha_from_object=False)))
            fill.location = (x + dx, y, TABLE_TOP_Z + 0.045)
            fill.scale = (1.0, 1.0, 0.001)
            fruit = P.new_object(f"DP_JugFruit_{key}", MS.sphere_mesh(
                "JugFruit", 0.032, M.flat_material("JugFruit", FRUIT, roughness=0.4)))
            fruit.location = (x + dx + 0.04, y, TABLE_TOP_Z + 0.05)
            # one screen-aligned plate under the jug: the window and when it clears
            root = P.new_object(f"DP_JugLabel_{key}")
            root.location = (x + LABEL_DX * (i * 2 - 1), y + LABEL_DY, LABEL_Z)
            c = root.constraints.new("COPY_ROTATION")
            c.target = P.camera()
            plate = P.new_object(f"DP_JugPlate_{key}",
                                 MS.plate_mesh("JugPlate", PLATE_W, PLATE_H, M.board_material()))
            plate.location = (0.0, PLATE_H / 2, -0.02)  # stands above the jugs
            head = _text(f"DP_JugTitle_{key}", title, 0.27, M.text_material(), "CENTER")
            head.location = (0.0, PLATE_H - 0.33, 0.0)
            pct = _text(f"DP_JugPct_{key}", "", 0.30,
                        M.flat_material("TextGold", "#F5C542", roughness=0.8, emission=1.4), "CENTER")
            pct.location = (0.0, PLATE_H - 0.66, 0.0)
            sub = _text(f"DP_JugSub_{key}", "", 0.185,
                        M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "CENTER")
            sub.location = (0.0, PLATE_H - 0.90, 0.0)
            for o in (plate, head, pct, sub):
                o.parent = root
            for o in (jug, fill, fruit, root, plate, head, pct, sub):
                o["dp_kind"] = "deck"
            self.objects[key] = {"jug": jug, "fill": fill, "fruit": fruit, "root": root,
                                 "head": head, "pct": pct, "sub": sub, "x": x + dx, "y": y}

    def update(self, usage) -> None:
        """Pour each jug to its window's fraction and write the reset time under it."""
        self.ensure()
        for _title, key in WINDOWS:
            d = self.objects.get(key)
            if not d:
                continue
            g = getattr(usage, key)
            frac = max(0.0, min(1.0, g.frac))
            inner = JUG_H - 2 * WALL
            try:
                d["fill"].scale = (1.0, 1.0, max(0.0015, inner * frac))
                d["fill"].color = hex_to_rgba(SANGRIA if frac >= 0.12 else SANGRIA_LOW)
                d["fruit"].location.z = TABLE_TOP_Z + 0.05 + inner * frac
                show_fruit = frac > 0.06
                if d["fruit"].hide_viewport == show_fruit:
                    d["fruit"].hide_viewport = not show_fruit
                    d["fruit"].hide_render = not show_fruit
            except ReferenceError:
                self.objects = {}
                return
            pct = f"{int(round(frac * 100))}%" if usage.ok else "—"
            sub = (f"resets {g.resets}" if g.resets else "") if usage.ok else "no reading"
            for slot, text in (("pct", pct), ("sub", sub)):
                if self.last_text.get(key + slot) != text:
                    self.last_text[key + slot] = text
                    d[slot].data.body = text

    def scale_to_camera(self, cam) -> None:
        """Keep the jug labels exactly the size of a lane sign, whatever the camera does."""
        if cam is None:
            return
        try:
            eye = Vector(cam.location)
        except (AttributeError, ReferenceError):
            return
        for _title, key in WINDOWS:
            d = self.objects.get(key)
            if not d:
                continue
            try:
                k = max(0.6, min(2.5, (Vector(d["root"].location) - eye).length / LABEL_REF_DIST))
                if abs(d["root"].scale.x - k) > 1e-4:
                    d["root"].scale = (k, k, k)
            except ReferenceError:
                return
