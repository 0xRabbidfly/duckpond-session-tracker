"""Modal operator: ray-cast under the mouse, draw the card and name tags, handle hotkeys.

Screen-space overlay rules (SPEC §7, reimagined):
  * Names are always big, high-contrast and horizontal. The hovered / pinned duck gets a
    tag; in kiosk mode (`K`) every duck and duckling gets one, with a one-word status under
    it and a state-coloured underline, so the pool reads like a departures board.
  * The card sits bottom-left. Its left edge is a state-coloured bar; a context-fill meter
    runs under the title; the tool mix of the last 10 minutes is a row of coloured chips.
  * A question or a denial is drawn in the state colour: it is the one line you must read.
"""
from __future__ import annotations

import math
import time

import blf
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .. import herdr
from ..runtime import RT
from ..scene import pool as P
from ..theme import (
    CONTEXT_LEGEND,
    HARNESS_LABELS,
    HAT_COLORS,
    HAT_LEGEND,
    context_ring_color,
    harness_color,
    hex_to_rgba,
)
from . import cards

FONT = 0
PAD = 12
LINE_H = 18
TITLE_SIZE = 20
STATUS_SIZE = 31    # the pool status, top row of the board: the biggest text on screen
TAB_SIZE = 16
LINE_SIZE = 20
FOOT_SIZE = 14
TAB_H = 26
TAB_PAD = 14
TAB_GAP = 8
BAR_H = 34
BOARD_PAD = 14
BOARD_BG = (0.04, 0.05, 0.08, 0.80)
GOLD = (1.0, 0.77, 0.26, 0.95)
TEAL = (0.37, 0.92, 0.83, 0.9)
TAG_SIZE = 19       # big enough to read across a room, small enough not to own the frame
TAG_SIZE_SMALL = 12
TAG_BG = (0.04, 0.05, 0.08, 0.52)  # see-through: a tag sits over water and ducks, not beside them
BG = (0.04, 0.05, 0.08, 0.86)
# (state, word) for the on-screen key; idle has no halo, so its swatch is an empty ring.
# No explanations: "working", "waiting", "blocked" and "idle" say what they mean.
LEGEND_STATES = (
    ("generating", "working"),
    ("awaiting_user", "waiting"),
    ("awaiting_permission", "blocked"),
    ("idle", "idle"),
)


class DUCKPOND_OT_hover(bpy.types.Operator):
    bl_idname = "duck_pond.hover"
    bl_label = "Duck Pond hover"
    bl_options = {"REGISTER", "INTERNAL"}

    _handle = None
    _last_cast = 0.0
    _hit = None  # the object under the last cast (original, not evaluated)
    _tab_rects = ()  # range-tab hit boxes, refreshed every time the board is drawn
    _board_rect = None

    def invoke(self, context, event):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"WARNING"}, "Duck Pond hover needs a 3D viewport")
            return {"CANCELLED"}
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (context,), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        RT.hover_started = True
        return {"RUNNING_MODAL"}

    def _finish(self):
        if self._handle:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            self._handle = None
        RT.hover_started = False

    def modal(self, context, event):
        if not RT.running:
            self._finish()
            for a in context.screen.areas:
                a.tag_redraw()
            return {"FINISHED"}
        if event.type == "MOUSEMOVE":
            now = time.time()
            if now - self._last_cast > 0.06:
                self._last_cast = now
                self._cast(context, event)
            return {"PASS_THROUGH"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS" and self._over_pool(context, event):
            # The board is drawn on top of the pool, so it gets the click first: a range tab
            # switches the range and leaves the pin alone, and a click anywhere else on the
            # board is swallowed rather than unpinning the duck you were reading about.
            tab = self._board_tab_at(context.region, event.mouse_region_x, event.mouse_region_y)
            if tab:
                context.window_manager.duck_pond.board_range = tab
                context.area.tag_redraw()
                return {"RUNNING_MODAL"}
            if self._over_board(context.region, event.mouse_region_x, event.mouse_region_y):
                return {"RUNNING_MODAL"}
            # cast where the click landed: a swimming duck has usually left the last hover cast
            # behind. A duck, duckling or tether pins its card and tag; anywhere else releases it.
            self._cast(context, event)
            RT.pinned = RT.hover
            if RT.pinned and RT.herdr_focus:
                # A duckling belongs to its parent's session, so key[0] is the terminal either way.
                herdr.focus_session(RT.pinned[0])
            context.area.tag_redraw()
            return {"PASS_THROUGH"}
        if event.value == "PRESS" and not (event.ctrl or event.alt or event.oskey):
            props = context.window_manager.duck_pond
            if event.type == "R" and event.shift is False:
                RT.set_redact(not RT.redact)
                props.redact = RT.redact
                return {"RUNNING_MODAL"}
            if event.type == "F":
                RT.toggle_follow()
                return {"RUNNING_MODAL"}
            if event.type == "HOME":
                RT.motion.follow = None
                RT.director.enabled = False
                props.director = False
                P.camera_overview()
                return {"RUNNING_MODAL"}
            if event.type == "L":
                RT.motion.follow = None
                RT.director.enabled = False
                props.director = False
                keys = RT.lanes.keys
                if keys:
                    idx = (getattr(RT, "_lane_idx", -1) + 1) % len(keys)
                    RT._lane_idx = idx
                    P.camera_lane(*RT.lanes.bounds[keys[idx]])
                return {"RUNNING_MODAL"}
            if event.type == "P":
                RT.paused = not RT.paused
                props.paused = RT.paused
                return {"RUNNING_MODAL"}
            if event.type == "K":
                props.tags_for_all = not props.tags_for_all
                return {"RUNNING_MODAL"}
            if event.type == "C":
                props.director = not props.director
                return {"RUNNING_MODAL"}
            if event.type == "S":
                props.sound = not props.sound
                return {"RUNNING_MODAL"}
            if event.type == "T":
                props.board_range = RT.next_board_range()
                return {"RUNNING_MODAL"}
            if event.type == "H":
                props.legend = not props.legend
                return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    @staticmethod
    def _over_pool(context, event) -> bool:
        """The event is over the viewport itself, not a sidebar, toolbar or header drawn on top of it."""
        region, area = context.region, context.area
        if region is None or area is None:
            return False
        mx, my = event.mouse_x, event.mouse_y
        if not (region.x <= mx < region.x + region.width and region.y <= my < region.y + region.height):
            return False
        return not any(r.type != "WINDOW" and r.width > 1 and r.height > 1
                       and r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height
                       for r in area.regions)

    def _cast(self, context, event):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        coord = (event.mouse_region_x, event.mouse_region_y)
        if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
            RT.hover = None
            self._hit = None
            return
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, _loc, _n, _i, obj, _m = context.scene.ray_cast(depsgraph, origin, direction)
        self._hit = obj.original if hit and obj else None
        kind, key = RT.agent_for_object(self._hit)
        changed = key != RT.hover or kind != RT.hover_kind
        RT.hover, RT.hover_kind = key, kind
        if changed:
            region.tag_redraw()

    # ------------------------------------------------------------ drawing
    def _draw(self, context):
        if not RT.running:
            return
        region = context.region
        rv3d = bpy.context.region_data or context.region_data
        if region is None or rv3d is None:
            return
        now = time.time()
        key = RT.pinned or RT.hover
        kind = RT.hover_kind if key == RT.hover else "duck" if not (key and key[1]) else "duckling"
        if RT.tags_for_all:
            self._draw_all_tags(region, rv3d, now, key)
        elif key:
            self._draw_name_tag(region, rv3d, key, now)
        card = cards.card_for(RT.fleet, kind, key, now, RT.redact)
        # The pool-wide totals used to sit down here permanently. They are on the board at
        # the top of the screen, and a second copy in the corner only ever got read as
        # belonging to the duck whose card was above it. What is left is the modes, which
        # are warnings about the pond lying to you and have to be visible somewhere.
        flags = [f for f, on in (("PAUSED", RT.paused), ("REDACTION OFF", not RT.redact),
                                 ("DIRECTOR", RT.director.enabled)) if on]
        footer = "   ·   ".join(flags)
        if card or footer:
            self._draw_card(context, region, card, footer, key)
        if RT.show_legend:
            self._draw_legend(context, region)
        self._draw_board(region, now)  # last: the one thing that must never be covered
        if RT.last_error:
            blf.size(FONT, 13)
            blf.color(FONT, 1.0, 0.4, 0.4, 1.0)
            blf.position(FONT, 16, 16, 0)
            blf.draw(FONT, "duck pond error — see console")

    def _draw_card(self, context, region, card, footer: str, key) -> None:
        blf.size(FONT, 13)
        lines = list(card.lines) if card else []
        widths = [blf.dimensions(FONT, ln)[0] for ln in lines + [footer]]
        if card:
            widths.append(blf.dimensions(FONT, card.subtitle)[0])
            blf.size(FONT, TITLE_SIZE)
            widths.append(blf.dimensions(FONT, card.title)[0] + 16 + blf.dimensions(FONT, "")[0])
            blf.size(FONT, 13)
            widths.append(blf.dimensions(FONT, card.state_text)[0] + 120)
            if card.highlight:
                widths.append(blf.dimensions(FONT, card.highlight)[0])
        width = min(max(widths + [260]) + 2 * PAD + 6, region.width - 48)
        rows = len(lines) + (3 if card else 0) + (1 if card and card.highlight else 0) + (1 if card and card.tool_mix else 0)
        height = rows * LINE_H + (LINE_H if footer else 0) + 2 * PAD + (TITLE_SIZE + 10 if card else 0)
        tools_w = 0
        if context.area:
            for r in context.area.regions:
                if r.type == "TOOLS":
                    tools_w = r.width
        x0 = tools_w + 24
        y0 = 24
        y1 = y0 + height
        self._rect(x0, y0, x0 + width, y1, BG)
        if card:
            sc = cards.state_rgba(card.state)
            self._rect(x0, y0, x0 + 6, y1, (sc[0], sc[1], sc[2], 1.0))
            if RT.pinned and RT.pinned == key:
                self._rect(x0, y1 - 3, x0 + width, y1, (1.0, 0.7, 0.3, 0.9))
        x = x0 + PAD + 6
        y = y1 - PAD - TITLE_SIZE
        if card:
            blf.size(FONT, TITLE_SIZE)
            blf.color(FONT, 1.0, 0.95, 0.85, 1.0)
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, card.title)
            # state, right-aligned on the title row, in the state colour
            blf.size(FONT, 13)
            sc = cards.state_rgba(card.state)
            sw = blf.dimensions(FONT, card.state_text)[0]
            blf.color(FONT, min(1.0, sc[0] * 1.6 + 0.2), min(1.0, sc[1] * 1.6 + 0.2), min(1.0, sc[2] * 1.6 + 0.2), 1.0)
            blf.position(FONT, x0 + width - PAD - sw, y + 4, 0)
            blf.draw(FONT, card.state_text)
            y -= LINE_H + 4
            blf.color(FONT, 0.75, 0.8, 0.9, 1.0)
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, card.subtitle)
            y -= LINE_H
            # context meter
            if card.context_text:
                bar_w = width - 2 * PAD - 6
                self._rect(x, y + 3, x + bar_w, y + 9, (1.0, 1.0, 1.0, 0.12))
                frac = max(0.0, min(1.0, card.context_frac))
                col = (0.37, 0.92, 0.83, 0.95) if frac < 0.7 else (1.0, 0.7, 0.3, 0.95) if frac < 0.9 else (1.0, 0.25, 0.2, 0.95)
                self._rect(x, y + 3, x + bar_w * frac, y + 9, col)
                blf.size(FONT, 11)
                blf.color(FONT, 0.8, 0.85, 0.9, 1.0)
                blf.position(FONT, x, y - 7, 0)
                blf.draw(FONT, card.context_text)
                blf.size(FONT, 13)
                y -= LINE_H + 10
            if card.highlight:
                sc = cards.state_rgba(card.state)
                blf.color(FONT, min(1.0, sc[0] * 1.6 + 0.25), min(1.0, sc[1] * 1.6 + 0.25), min(1.0, sc[2] * 1.6 + 0.25), 1.0)
                blf.position(FONT, x, y, 0)
                blf.draw(FONT, card.highlight)
                y -= LINE_H
        blf.color(FONT, 0.92, 0.92, 0.92, 1.0)
        for ln in lines:
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, ln)
            y -= LINE_H
        if card and card.tool_mix:
            cx = x
            for text, n, hexc in card.tool_mix:
                label = f"{text} ×{n}"
                w = blf.dimensions(FONT, label)[0] + 12
                c = hex_to_rgba(hexc)
                self._rect(cx, y - 4, cx + w, y + 13, (c[0], c[1], c[2], 0.35))
                blf.color(FONT, 1.0, 1.0, 1.0, 1.0)
                blf.position(FONT, cx + 6, y, 0)
                blf.draw(FONT, label)
                cx += w + 6
            y -= LINE_H
        if footer:
            # a rule, so the modes do not read as another line of the card above them
            if card:
                self._rect(x0 + PAD, y + LINE_H - 5, x0 + width - PAD, y + LINE_H - 4,
                           (1.0, 1.0, 1.0, 0.16))
            blf.color(FONT, 0.85, 0.72, 0.45, 1.0)   # amber: these are all "not the normal pond"
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, footer)

    # ------------------------------------------------------------ tags
    def _anchor(self, region, rv3d, d, lift: float):
        try:
            world = d.obj.matrix_world.translation + Vector((0.0, 0.0, lift * d.obj.scale.x))
        except ReferenceError:
            return None
        return view3d_utils.location_3d_to_region_2d(region, rv3d, world)

    def _draw_name_tag(self, region, rv3d, key, now) -> None:
        """Big, high-contrast name floating over the hovered or pinned duck, in screen space."""
        d = RT.ducks.get(key)
        if d is None:
            return
        name, status, state = cards.tag_for(RT.fleet, key, now, RT.redact)
        if not name:
            return
        p = self._anchor(region, rv3d, d, 1.35)
        if p is None:
            return
        self._tag(region, p, name, status, state, TAG_SIZE, RT.pinned == key)

    def _draw_all_tags(self, region, rv3d, now, focus) -> None:
        """Every duck gets a tag; sessions first and biggest, ducklings smaller. Tags that would
        overlap are pushed up so the pool reads like a departures board, not a pile."""
        items = []
        for key, d in list(RT.ducks.items()):
            name, status, state = cards.tag_for(RT.fleet, key, now, RT.redact)
            if not name:
                continue
            p = self._anchor(region, rv3d, d, 1.35 if not key[1] else 1.0)
            if p is None:
                continue
            size = TAG_SIZE if (key == focus or not key[1]) else TAG_SIZE_SMALL
            items.append((0 if not key[1] else 1, key, p, name, status, state, size))
        items.sort(key=lambda it: (it[0], -it[2].y))
        placed = []
        for _, key, p, name, status, state, size in items:
            blf.size(FONT, size)
            w, h = blf.dimensions(FONT, name)
            blf.size(FONT, max(11, int(size * 0.55)))
            sw, sh = blf.dimensions(FONT, status)
            bw = max(w, sw) + 20
            bh = h + sh + 18
            x = min(max(p.x - bw / 2, 8), region.width - bw - 8)
            y = min(max(p.y - sh - 10, 8), region.height - bh - 8)
            for _ in range(12):  # push up until clear of every placed tag
                hit = next((r for r in placed if x < r[2] and x + bw > r[0] and y < r[3] and y + bh > r[1]), None)
                if hit is None:
                    break
                y = hit[3] + 4
            placed.append((x, y, x + bw, y + bh))
            if abs((y - 4) - (p.y - sh - 14)) > 24 or abs((x + bw / 2) - p.x) > bw / 2:
                sc = cards.state_rgba(state)
                self._line((x + bw / 2, y), (p.x, p.y - 0.9 * sh), (sc[0], sc[1], sc[2], 0.85))
            self._tag(region, Vector((x + bw / 2, y + sh + 10)), name, status, state, size, RT.pinned == key)

    def _tag(self, region, p, name: str, status: str, state: str, size: int, pinned: bool) -> None:
        blf.size(FONT, size)
        w, h = blf.dimensions(FONT, name)
        blf.size(FONT, max(11, int(size * 0.55)))
        sw, sh = blf.dimensions(FONT, status)
        bw = max(w, sw)
        x = min(max(p.x - bw / 2, 8), region.width - bw - 8)
        y = min(max(p.y, 8 + sh + 6), region.height - h - 8)
        sc = cards.state_rgba(state)
        self._rect(x - 8, y - sh - 9, x + bw + 8, y + h + 7, TAG_BG)
        self._rect(x - 8, y - sh - 9, x + bw + 8, y - sh - 6, (sc[0], sc[1], sc[2], 0.95))
        if pinned:
            self._rect(x - 8, y + h + 4, x + bw + 8, y + h + 7, (1.0, 0.7, 0.3, 0.95))
        blf.size(FONT, size)
        blf.color(FONT, 1.0, 0.96, 0.88, 1.0)
        blf.position(FONT, x + (bw - w) / 2, y, 0)
        blf.draw(FONT, name)
        blf.size(FONT, max(11, int(size * 0.55)))
        blf.color(FONT, min(1.0, sc[0] * 1.5 + 0.3), min(1.0, sc[1] * 1.5 + 0.3), min(1.0, sc[2] * 1.5 + 0.3), 1.0)
        blf.position(FONT, x + (bw - sw) / 2, y - sh - 4, 0)
        blf.draw(FONT, status)
        blf.size(FONT, 13)

    def _draw_board(self, region, now: float) -> None:
        """The whole board, drawn across the top of the screen.

        It used to be geometry standing on the north deck, where duck name tags parked on top of
        it and the far half was read at an angle. In screen space it is flat, square-on, always
        the same size, and drawn last of everything, so nothing can cover it. The range tabs stay
        clickable: their rectangles are recorded here and hit-tested on the next click.
        """
        b = cards.board_model(RT.fleet, now, RT.board_range)
        pad = BOARD_PAD

        blf.size(FONT, STATUS_SIZE)
        sep = "  ·  "
        st_sep_w = blf.dimensions(FONT, sep)[0]
        st_w = [blf.dimensions(FONT, t)[0] for t, _s in b.status]
        status_w = sum(st_w) + st_sep_w * (len(b.status) - 1)
        status_h = blf.dimensions(FONT, "M")[1]

        blf.size(FONT, TAB_SIZE)
        tab_w = [blf.dimensions(FONT, n)[0] + 2 * TAB_PAD for n, _sel in b.tabs]
        tabs_w = sum(tab_w) + TAB_GAP * (len(b.tabs) - 1)

        blf.size(FONT, LINE_SIZE)
        lines_w = max(blf.dimensions(FONT, t)[0] for t in (b.range_line, b.month_line or " "))
        blf.size(FONT, FOOT_SIZE)
        foot_w = blf.dimensions(FONT, b.foot)[0]

        inner = max(status_w, tabs_w, lines_w, foot_w, 420)
        width = min(inner + 2 * pad, region.width - 32)
        inner = width - 2 * pad
        height = pad + status_h + 12 + TAB_H + 10 + 2 * (LINE_SIZE + 8) + BAR_H + 10 + FOOT_SIZE + 6 + pad
        x0 = (region.width - width) / 2
        y1 = region.height - 14
        y0 = y1 - height
        self._rect(x0, y0, x0 + width, y1, BOARD_BG)
        self._board_rect = (x0, y0, x0 + width, y1)
        cx = x0 + width / 2

        # row 1: who is doing what, one colour per state
        blf.size(FONT, STATUS_SIZE)
        y = y1 - pad - status_h
        x = cx - status_w / 2
        for i, ((text, state), w) in enumerate(zip(b.status, st_w)):
            c = cards.state_rgba(state)
            blf.color(FONT, min(1.0, c[0] * 1.5 + 0.25), min(1.0, c[1] * 1.5 + 0.25), min(1.0, c[2] * 1.5 + 0.25), 1.0)
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, text)
            x += w
            if i < len(b.status) - 1:
                blf.color(FONT, 0.5, 0.55, 0.62, 1.0)
                blf.position(FONT, x, y, 0)
                blf.draw(FONT, sep)
                x += st_sep_w

        # row 2: range tabs, recorded for the click handler
        y -= 12 + TAB_H
        x = cx - tabs_w / 2
        self._tab_rects = []
        blf.size(FONT, TAB_SIZE)
        for (name, sel), w in zip(b.tabs, tab_w):
            self._rect(x, y, x + w, y + TAB_H, (0.12, 0.15, 0.22, 0.95) if sel else (0.09, 0.11, 0.16, 0.8))
            if sel:
                self._rect(x, y, x + w, y + 2, GOLD)
            blf.color(FONT, *((1.0, 0.85, 0.35, 1.0) if sel else (0.66, 0.71, 0.80, 1.0)))
            blf.position(FONT, x + TAB_PAD, y + 7, 0)
            blf.draw(FONT, name)
            self._tab_rects.append((x, y, x + w, y + TAB_H, name))
            x += w + TAB_GAP

        # rows 3-4: spend for the picked range, then the month so far
        blf.size(FONT, LINE_SIZE)
        y -= 10 + LINE_SIZE + 4
        blf.color(FONT, 1.0, 0.85, 0.35, 1.0)
        blf.position(FONT, cx - blf.dimensions(FONT, b.range_line)[0] / 2, y, 0)
        blf.draw(FONT, b.range_line)
        if b.month_line:
            y -= LINE_SIZE + 8
            blf.color(FONT, 0.93, 0.94, 0.96, 1.0)
            blf.position(FONT, cx - blf.dimensions(FONT, b.month_line)[0] / 2, y, 0)
            blf.draw(FONT, b.month_line)
        else:
            y -= LINE_SIZE + 8

        # the sparkline: one bar per bucket, the current one in gold
        y -= 8 + BAR_H
        if b.bars:
            n = len(b.bars)
            slot = inner / n
            bw = max(2.0, slot * 0.68)
            for i, v in enumerate(b.bars):
                bh = max(1.0, BAR_H * v / b.peak) if b.peak > 0 else 1.0
                bx = x0 + pad + slot * (i + 0.5) - bw / 2
                self._rect(bx, y, bx + bw, y + bh, GOLD if i == n - 1 else TEAL)

        # the footer: peak and the clock
        blf.size(FONT, FOOT_SIZE)
        y -= 6 + FOOT_SIZE
        blf.color(FONT, 0.55, 0.78, 0.74, 1.0)
        blf.position(FONT, cx - foot_w / 2, y, 0)
        blf.draw(FONT, b.foot)
        blf.size(FONT, 13)

    def _over_board(self, region, mx: int, my: int) -> bool:
        r = getattr(self, "_board_rect", None)
        return bool(r) and r[0] <= mx <= r[2] and r[1] <= my <= r[3]

    def _board_tab_at(self, region, mx: int, my: int) -> str | None:
        """The range tab under a click in region coordinates, or None."""
        for x0, y0, x1, y1, name in getattr(self, "_tab_rects", ()):
            if x0 <= mx <= x1 and y0 <= my <= y1:
                return name
        return None

    # ------------------------------------------------------------ legend
    def _draw_legend(self, context, region) -> None:
        """Bottom-right key, laid out as columns across the strip of empty deck down there.

        Four sections side by side rather than one tall stack: the pool fills the middle of the
        frame and the card owns the bottom-left, so a horizontal strip is the one place a key can
        sit without covering a duck. Hats are drawn as their own silhouettes rather than colour
        swatches -- a hat is a shape you recognise on the duck, and half of them (top hat,
        newspaper, kasa) are told apart by outline, not hue.
        """
        cols = []  # each: (heading, [(kind, colour, name, note), ...])
        cols.append(("HALO = STATE", [
            ("ring", None if st == "idle" else cards.state_rgba(st), word, "")
            for st, word in LEGEND_STATES]))
        cols.append(("RING = CONTEXT", [
            ("swatch", context_ring_color(f), label, "")
            for f, label in CONTEXT_LEGEND]))
        cols.append(("BODY = TOOL", [
            ("swatch", harness_color(h, RT.color_overrides), label, "")
            for h, label in HARNESS_LABELS.items() if h != "unknown"]))
        cols.append(("HAT = MODEL", [
            ("hat:" + kind, hex_to_rgba(HAT_COLORS[kind]), kind.replace("_", " "), who)
            for kind, who in HAT_LEGEND]))

        blf.size(FONT, 12)
        glyph_w, gap, col_gap = 20, 10, 22
        metrics = []
        for heading, rows in cols:
            name_w = max([blf.dimensions(FONT, n)[0] for _k, _c, n, _h in rows] or [0])
            note_w = max([blf.dimensions(FONT, h)[0] for _k, _c, _n, h in rows if h] or [0])
            body_w = glyph_w + name_w + (gap + note_w if note_w else 0)
            metrics.append((max(body_w, blf.dimensions(FONT, heading)[0]), name_w))
        width = sum(w for w, _ in metrics) + col_gap * (len(cols) - 1) + 2 * PAD
        body_rows = max(len(rows) for _h, rows in cols)
        height = (body_rows + 1) * LINE_H + 8 + 2 * PAD

        ui_w = 0
        if context.area:
            ui_w = sum(r.width for r in context.area.regions if r.type == "UI" and r.width > 1)
        x1 = region.width - ui_w - 24
        x0 = max(24, x1 - width)
        y0 = 24
        y1 = y0 + height
        self._rect(x0, y0, x1, y1, BG)

        head_y = y1 - PAD - LINE_H + 4
        row0_y = head_y - LINE_H - 8
        x = x0 + PAD
        for (heading, rows), (col_w, name_w) in zip(cols, metrics):
            y = head_y
            blf.size(FONT, 12)
            blf.color(FONT, 0.55, 0.72, 0.86, 1.0)
            blf.position(FONT, x, y, 0)
            blf.draw(FONT, heading)
            self._rect(x, y - 5, x + col_w, y - 4, (1.0, 1.0, 1.0, 0.10))
            y -= LINE_H + 8
            for kind, rgba, name, note in rows:
                cx, cy = x + 8, y + 5
                if kind == "ring":
                    if rgba is None:
                        self._circle(cx, cy, 6, (0.6, 0.63, 0.7, 0.9), filled=False)
                    else:
                        self._circle(cx, cy, 6, (rgba[0], rgba[1], rgba[2], 1.0))
                elif kind == "swatch":
                    self._rect(cx - 7, cy - 6, cx + 7, cy + 6, (0.8, 0.82, 0.86, 0.9))
                    self._rect(cx - 6, cy - 5, cx + 6, cy + 5, (rgba[0], rgba[1], rgba[2], 1.0))
                else:
                    self._hat_glyph(kind.split(":", 1)[1], cx, cy, (rgba[0], rgba[1], rgba[2], 1.0))
                blf.color(FONT, 0.94, 0.94, 0.94, 1.0)
                blf.position(FONT, x + glyph_w, y, 0)
                blf.draw(FONT, name)
                if note:
                    blf.color(FONT, 0.62, 0.67, 0.74, 1.0)
                    blf.position(FONT, x + glyph_w + name_w + gap, y, 0)
                    blf.draw(FONT, note)
                y -= LINE_H
            x += col_w + col_gap
        # The hint goes in the hole the short columns leave. Hats run two rows longer than
        # every other column, so the bottom-left corner is empty: putting it there instead of
        # on a line of its own takes a whole row off the height of the box.
        hint = "H hides this key"
        blf.color(FONT, 0.45, 0.50, 0.58, 1.0)
        blf.position(FONT, x0 + PAD, row0_y - (body_rows - 1) * LINE_H, 0)
        blf.draw(FONT, hint)
        blf.size(FONT, 13)

    @classmethod
    def _hat_glyph(cls, kind: str, cx: float, cy: float, color) -> None:
        """A small silhouette of the hat itself, in the hat's own colour.

        Every shape is drawn over a faint backing shadow one pixel down and out, so the black
        top hat and the near-white newspaper both stay visible against the dark panel.
        """
        shade = (1.0, 1.0, 1.0, 0.22)
        for col, dx, dy, grow in ((shade, 0.0, -1.0, 1.0), (color, 0.0, 0.0, 0.0)):
            x, y = cx + dx, cy + dy
            if kind == "top_hat":
                cls._rect(x - 8 - grow, y - 5 - grow, x + 8 + grow, y - 3 + grow, col)   # brim
                cls._rect(x - 4 - grow, y - 4 - grow, x + 4 + grow, y + 6 + grow, col)   # crown
            elif kind == "wizard":
                cls._poly([(x - 6 - grow, y - 3), (x + 6 + grow, y - 3), (x, y + 8 + grow)], col)
                cls._rect(x - 8 - grow, y - 5 - grow, x + 8 + grow, y - 3 + grow, col)
            elif kind == "beret":
                cls._poly(cls._arc(x, y - 2, 7 + grow, 0.0, math.pi), col)
                cls._rect(x - 7 - grow, y - 3 - grow, x + 7 + grow, y - 2 + grow, col)
                cls._circle(x + 1, y + 6 + grow, 1.6 + grow, col)                        # the nub
            elif kind == "kasa":
                cls._poly([(x - 9 - grow, y - 3), (x + 9 + grow, y - 3), (x, y + 5 + grow)], col)
            elif kind == "cap":
                cls._poly(cls._arc(x - 1, y - 1, 6 + grow, 0.0, math.pi), col)
                cls._rect(x - 7 - grow, y - 2 - grow, x + 8 + grow, y - 0 + grow, col)   # peak
            elif kind == "propeller":
                cls._poly(cls._arc(x, y - 2, 6 + grow, 0.0, math.pi), col)
                cls._rect(x - 8 - grow, y + 4 - grow, x + 8 + grow, y + 5 + grow, col)   # blades
                cls._circle(x, y + 4 + grow, 1.6 + grow, col)
            elif kind == "newspaper":
                cls._poly([(x - 8 - grow, y - 3), (x + 8 + grow, y - 3), (x, y + 6 + grow)], col)
                cls._rect(x - 8 - grow, y - 4 - grow, x + 8 + grow, y - 3 + grow, col)
            else:  # crown, and anything added later: a plain band with points
                cls._rect(x - 7 - grow, y - 4 - grow, x + 7 + grow, y + 1 + grow, col)
                for px in (-5, 0, 5):
                    cls._poly([(x + px - 2.5, y + 1), (x + px + 2.5, y + 1), (x + px, y + 6 + grow)], col)

    @staticmethod
    def _arc(cx, cy, r, a0, a1, steps: int = 12):
        """Points along an arc, closed back along its chord: a filled dome."""
        return [(cx + r * math.cos(a0 + (a1 - a0) * i / steps),
                 cy + r * math.sin(a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]

    @staticmethod
    def _poly(points, color):
        """Filled convex polygon."""
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRI_FAN", {"pos": [tuple(p) for p in points]})
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.blend_set("NONE")

    @staticmethod
    def _circle(cx, cy, r, color, filled: bool = True):
        pts = [(cx + r * math.cos(2 * math.pi * i / 20), cy + r * math.sin(2 * math.pi * i / 20)) for i in range(20)]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRI_FAN" if filled else "LINE_LOOP", {"pos": pts})
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.blend_set("NONE")

    @staticmethod
    def _line(a, b, color):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": [a, b]})
        gpu.state.blend_set("ALPHA")
        gpu.state.line_width_set(2.0)
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")

    @staticmethod
    def _rect(x0, y0, x1, y1, color):
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "TRI_FAN", {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]})
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.blend_set("NONE")
