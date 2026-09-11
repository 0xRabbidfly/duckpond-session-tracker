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

import time

import blf
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..runtime import RT
from ..scene import pool as P
from ..theme import hex_to_rgba
from . import cards

FONT = 0
PAD = 12
LINE_H = 18
TITLE_SIZE = 20
TAG_SIZE = 26
TAG_SIZE_SMALL = 15
BG = (0.04, 0.05, 0.08, 0.86)


class DUCKPOND_OT_hover(bpy.types.Operator):
    bl_idname = "duck_pond.hover"
    bl_label = "Duck Pond hover"
    bl_options = {"REGISTER", "INTERNAL"}

    _handle = None
    _last_cast = 0.0

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
        if event.type == "LEFTMOUSE" and event.value == "PRESS" and RT.hover:
            RT.pinned = None if RT.pinned == RT.hover else RT.hover
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
        return {"PASS_THROUGH"}

    def _cast(self, context, event):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return
        coord = (event.mouse_region_x, event.mouse_region_y)
        if not (0 <= coord[0] <= region.width and 0 <= coord[1] <= region.height):
            RT.hover = None
            return
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        depsgraph = context.evaluated_depsgraph_get()
        hit, _loc, _n, _i, obj, _m = context.scene.ray_cast(depsgraph, origin, direction)
        kind, key = RT.agent_for_object(obj.original if hit and obj else None)
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
        footer = cards.totals_line(RT.fleet, now)
        if RT.paused:
            footer += "   ·   PAUSED"
        if not RT.redact:
            footer += "   ·   REDACTION OFF"
        if RT.director.enabled:
            footer += "   ·   DIRECTOR"
        self._draw_card(context, region, card, footer, key)
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
        height = rows * LINE_H + LINE_H + 2 * PAD + (TITLE_SIZE + 10 if card else 0)
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
        blf.color(FONT, 0.6, 0.75, 0.85, 1.0)
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
        self._rect(x - 10, y - sh - 10, x + bw + 10, y + h + 8, (0.04, 0.05, 0.08, 0.9))
        self._rect(x - 10, y - sh - 10, x + bw + 10, y - sh - 6, (sc[0], sc[1], sc[2], 1.0))
        if pinned:
            self._rect(x - 10, y + h + 5, x + bw + 10, y + h + 8, (1.0, 0.7, 0.3, 0.95))
        blf.size(FONT, size)
        blf.color(FONT, 1.0, 0.96, 0.88, 1.0)
        blf.position(FONT, x + (bw - w) / 2, y, 0)
        blf.draw(FONT, name)
        blf.size(FONT, max(11, int(size * 0.55)))
        blf.color(FONT, min(1.0, sc[0] * 1.5 + 0.3), min(1.0, sc[1] * 1.5 + 0.3), min(1.0, sc[2] * 1.5 + 0.3), 1.0)
        blf.position(FONT, x + (bw - sw) / 2, y - sh - 4, 0)
        blf.draw(FONT, status)
        blf.size(FONT, 13)

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
