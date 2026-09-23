"""The deck mosaic: which project spent what, and when, set into the near paving.

The board across the top says what the whole fleet spent in the last day. It never says
*which* folder spent it or *when*, and that is the question you actually have when you come
back to the desk and the number is bigger than you left it. One row per project, one tile
per hour, brightness for spend: an overnight run shows up as a bright band at 03:00 in one
row and nothing in the others, which no single total can tell you.

It goes on the south deck because that paving is the nearest thing to the camera and the only
large piece of the frame with nothing in it. Lying flat it would be unreadable -- a horizontal
plane at this camera is compressed by half and text on it foreshortens to nothing -- so the
panel is tilted until its face points back up the view axis, like the information boards at a
real lido. Its height is held just under the sight line that grazes the pool's near edge, so
it fills dead space without eating any water.
"""
from __future__ import annotations

import math

import bpy

from ..theme import heat_color
from . import materials as M
from . import meshes as MS
from . import pool as P
from .deck import _set_body, _text

# The south deck slab spans y -2.1..-0.1 with its top at z 0.10. Set left of the frame's
# centre, not the pool's: this paving is a third of the distance away, so it magnifies about
# 1.7x, and the on-screen key owns the bottom-right corner. The panel stops where the key
# starts rather than running underneath it, and sits far enough forward on the paving to
# share the key's band: measured, its top lands on 0.185 of the frame height and the
# key's on 0.184. Its base sits at the very front of the paving, which is what puts its
# foot on the same line as the key's: measured from the render, not reasoned about, because
# a wide panel's top edge does not project where its centre does.
AT = (3.475, -2.14, 0.11)
TILT = math.radians(58)     # face normal back up the view axis; the camera looks down ~30
# Measured, not guessed: one world unit here is 0.068 of the frame width. At 9.0 the panel
# reached from the left margin all the way to the key and the hours were wider than they
# needed to be to be read; the columns are squeezed to 72 % of that and the slate pulled in
# with them, so the panel keeps its left edge and gives back the middle of the frame. A
# height of 1.12 stops at the water's near edge.
W, H = 6.95, 1.12
ROWS = 4                    # cards.HEAT_ROWS; a fifth row costs every row its legible label

# Everything below is in the panel's own space: x from -W/2 to W/2, y from 0 at the bottom.
# Text sizes are chosen backwards from pixels: 0.075 of the frame width per unit means 0.135
# is about 16px at 1600 wide, which is the lane signs' own detail line.
PAD_X = 0.22
TITLE_Y, TITLE_SIZE = 0.985, 0.135
GRID_TOP, ROW_H = 0.92, 0.160
LABEL_SIZE = 0.115
LABEL_W = 1.25              # room for a folder name at the left of each row
TICK_Y, TICK_SIZE = 0.200, 0.092
FOOT_Y, FOOT_SIZE = 0.075, 0.092   # any lower and the foot lip eats the descenders
TILE_GAP = 0.048
TEXT_Z = 0.050              # clear of the rails, which stand 0.035 off the slate

# no legs: the panel leans back onto the paving, and two little posts in front of it only
# ever stood in the way of the footnote
SLATE = "#0B0F18"
EDGE = "#2A3444"
NOW_MARK = "#F5C542"


def _panel_mesh(slate, edge):
    me = MS._existing("Mosaic")
    if me:
        return me
    b = MS._Builder()
    b.box(W, H, 0.05, at=(0.0, H / 2, 0.0), slot=0)                       # the slate
    b.box(W, 0.035, 0.07, at=(0.0, 0.012, 0.0), slot=1)                   # a lip along the foot
    b.box(0.035, H, 0.07, at=(-W / 2 + 0.017, H / 2, 0.0), slot=1)        # and up both sides
    b.box(0.035, H, 0.07, at=(W / 2 - 0.017, H / 2, 0.0), slot=1)
    return b.finish("Mosaic", [slate, edge])


def _tile_mesh(mat, w: float, h: float):
    # The width is in the name: the cache is by name, and the ranges do not agree on it.
    # Keyed on "MosaicTile" alone, the minute view (60 columns) drew 24-column tiles at a
    # fifth of their step and the row came out as one smear; the week view (8) drew islands.
    name = f"MosaicTile_{w:.3f}"
    me = MS._existing(name)
    if me:
        return me
    b = MS._Builder()
    b.box(w, h, 0.02)
    return b.finish(name, [mat])


class DeckMosaic:
    """The panel, its tiles, and the text around them."""

    def __init__(self) -> None:
        self.objects: dict = {}
        self.tiles: list[list] = []          # [row][col]
        self.last_text: dict[str, str] = {}
        self._cols = 0

    # ---------------------------------------------------------------- build
    def ensure(self, cols: int = 24) -> None:
        if self.objects and self.objects["root"].name in bpy.data.objects and self._cols == cols:
            return
        self.wipe()
        self._cols = cols
        slate = M.flat_material("MosaicSlate", SLATE, roughness=0.65)
        edge = M.flat_material("MosaicEdge", EDGE, roughness=0.45)
        # one material, a colour per object: 120 tiles would otherwise be 120 materials
        tile_mat = M.object_color_material("MosaicTile", roughness=0.38, emission=1.25,
                                          alpha_from_object=False)

        root = P.new_object("DP_MosaicRoot")
        root.location = AT
        root.rotation_euler = (TILT, 0.0, 0.0)
        panel = P.new_object("DP_Mosaic", _panel_mesh(slate, edge))
        panel.parent = root

        grid_x0 = -W / 2 + PAD_X + LABEL_W
        grid_w = (W / 2 - PAD_X) - grid_x0
        step = grid_w / cols
        # The gap is a fixed distance until the columns get too close for it: at 60 of them
        # it was more than half the step and an hour of spend read as a hairline.
        gap = min(TILE_GAP, step * 0.25)
        tw, th = step - gap, ROW_H - TILE_GAP
        tile_me = _tile_mesh(tile_mat, tw, th)

        self.tiles = []
        labels = []
        for r in range(ROWS):
            cy = GRID_TOP - (r + 0.5) * ROW_H
            row = []
            for c in range(cols):
                t = P.new_object(f"DP_MosaicTile_{r}_{c}", tile_me)
                t.parent = root
                t.location = (grid_x0 + (c + 0.5) * step, cy, 0.035)
                t.color = heat_color(0.0)
                row.append(t)
            self.tiles.append(row)
            lab = _text(f"DP_MosaicRow_{r}", "", LABEL_SIZE, M.text_material(), "RIGHT")
            lab.parent = root
            lab.location = (grid_x0 - 0.12, cy - 0.040, TEXT_Z)
            labels.append(lab)

        title = _text("DP_MosaicTitle", "", TITLE_SIZE, M.text_material(), "LEFT")
        title.parent = root
        title.location = (-W / 2 + PAD_X, TITLE_Y, TEXT_Z)
        foot = _text("DP_MosaicFoot", "", FOOT_SIZE,
                     M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "LEFT")
        foot.parent = root
        foot.location = (-W / 2 + PAD_X, FOOT_Y, TEXT_Z)
        ticks = [_text(f"DP_MosaicTick_{i}", "", TICK_SIZE,
                       M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "CENTER")
                 for i in range(4)]
        for t in ticks:
            t.parent = root
            t.location = (0.0, TICK_Y, TEXT_Z)
            t.hide_viewport = t.hide_render = True
        # a gold bar over the column we are living in. Under the grid it sat in the band of
        # a row that was not there, and read as a cell rather than as a marker.
        mark = P.new_object("DP_MosaicNow", MS.plate_mesh(  # width in the name, as the tiles do
            f"MosaicNow_{tw:.3f}", tw, 0.028, M.flat_material("MosaicNow", NOW_MARK, roughness=0.3, emission=1.6)))
        mark.parent = root
        mark.location = (grid_x0 + (cols - 0.5) * step, GRID_TOP + 0.042, 0.04)

        for o in (root, panel, title, foot, mark, *labels, *ticks,
                  *(t for row in self.tiles for t in row)):
            o["dp_kind"] = "deck"
        self.objects = {"root": root, "panel": panel, "title": title, "foot": foot,
                        "mark": mark, "labels": labels, "ticks": ticks,
                        "grid_x0": grid_x0, "step": step}

    def wipe(self) -> None:
        for name in list(bpy.data.objects.keys()):
            if name.startswith("DP_Mosaic"):
                P.remove_object(bpy.data.objects[name])
        self.objects = {}
        self.tiles = []
        self._cols = 0

    # ---------------------------------------------------------------- update
    def update(self, heat) -> None:
        """Paint the tiles and write the text from a `cards.Heat`. Nothing here decides
        anything: what it says is worked out in `cards.heat_model`, which a test can read."""
        cols = len(heat.rows[0][1]) if heat.rows else self._cols or 24
        self.ensure(cols)
        try:
            self._write("title", heat.title.upper())
            self._write("foot", heat.foot)
            peak = heat.peak or 1.0
            for r in range(ROWS):
                has = r < len(heat.rows)
                name, vals = heat.rows[r] if has else ("", [])
                lab = self.objects["labels"][r]
                if lab.hide_viewport == has:
                    lab.hide_viewport = lab.hide_render = not has
                if has and self.last_text.get(f"row{r}") != name:
                    self.last_text[f"row{r}"] = name
                    _set_body(lab, name)
                for c, tile in enumerate(self.tiles[r]):
                    if tile.hide_viewport == has:
                        tile.hide_viewport = tile.hide_render = not has
                    if has:
                        v = vals[c] if c < len(vals) else 0.0
                        tile.color = heat_color(v / peak if v > 0 else 0.0)
            # the ticks: at most four, parked under their own column
            x0, step = self.objects["grid_x0"], self.objects["step"]
            for i, t in enumerate(self.objects["ticks"]):
                on = i < len(heat.ticks)
                if t.hide_viewport == on:
                    t.hide_viewport = t.hide_render = not on
                if on:
                    col, text = heat.ticks[i]
                    t.location.x = x0 + (col + 0.5) * step
                    if self.last_text.get(f"tick{i}") != text:
                        self.last_text[f"tick{i}"] = text
                        _set_body(t, text)
            mark = self.objects["mark"]
            on = heat.now_col >= 0 and bool(heat.rows)
            if mark.hide_viewport == on:
                mark.hide_viewport = mark.hide_render = not on
            if on:
                mark.location.x = x0 + (heat.now_col + 0.5) * step
        except ReferenceError:
            self.objects = {}
            self.tiles = []

    def _write(self, slot: str, text: str) -> None:
        if self.last_text.get(slot) != text:
            self.last_text[slot] = text
            _set_body(self.objects[slot], text)
