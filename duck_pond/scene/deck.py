"""The deck is the dashboard: a scoreboard on the far side, lane signs that tell a story.

Numbers live here, on purpose. The water is for feeling; the deck is for reading.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P
from ..theme import STATE_COLORS, hex_to_rgba, redact

BOARD_W = 9.0
BOARD_H = 2.2
SPARK_BARS = 30
COINS_MAX = 24
COIN_USD = 1.0  # one coin per dollar


def _text(name: str, body: str, size: float, mat, align="LEFT") -> bpy.types.Object:
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align
    cu.materials.append(mat)
    return P.new_object(name, cu)


def _set_body(obj, text: str) -> None:
    if obj is not None and obj.data.body != text:
        obj.data.body = text


def fmt_tokens(n: float) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


class Scoreboard:
    """A dark board standing on the north deck. Line 1: who is doing what. Line 2: spend and
    throughput. Below: a 30-minute bar chart of output tokens per minute, as real geometry."""

    def __init__(self) -> None:
        self.board: Optional[bpy.types.Object] = None
        self.line1 = None
        self.line2 = None
        self.line3 = None
        self.bars: List[bpy.types.Object] = []
        self.last_update = 0.0

    def ensure(self) -> None:
        if self.board is not None and self.board.name in bpy.data.objects:
            return
        x0 = P.POOL_X / 2
        y = P.POOL_Y + P.DECK + 0.05
        z = 1.3
        self.board = P.new_object("DP_Board", MS.plate_mesh("Board", BOARD_W, BOARD_H, M.board_material()))
        self.board.location = (x0, y, z)
        self.board.rotation_euler = (1.5708, 0.0, 0.0)  # stand it up, facing the pool (-Y)
        self.board["dp_kind"] = "deck"
        white = M.text_material()
        gold = M.flat_material("TextGold", "#F5C542", roughness=0.8, emission=1.4)
        teal = M.flat_material("TextTeal", "#5EEAD4", roughness=0.8, emission=1.4)
        self.line1 = _text("DP_Board_L1", "", 0.42, white, "CENTER")
        self.line2 = _text("DP_Board_L2", "", 0.26, gold, "CENTER")
        self.line3 = _text("DP_Board_L3", "", 0.2, teal, "CENTER")
        for o, dz in ((self.line1, 0.62), (self.line2, 0.2), (self.line3, -0.12)):
            o.location = (x0, y - 0.03, z + dz)
            o.rotation_euler = (1.5708, 0.0, 0.0)
            o["dp_kind"] = "deck"
        bar_mat = M.object_color_material("Bar", roughness=0.6, emission=0.8, alpha_from_object=False)
        bw = (BOARD_W - 0.8) / SPARK_BARS
        for i in range(SPARK_BARS):
            b = P.new_object(f"DP_Bar_{i:02d}", MS.box_mesh("Bar", bw * 0.7, 0.05, 1.0, bar_mat, at=(0, 0, 0.5)))
            b.location = (x0 - (BOARD_W - 0.8) / 2 + bw * (i + 0.5), y - 0.05, z - BOARD_H / 2 + 0.12)
            b.scale = (1.0, 1.0, 0.02)
            b.color = hex_to_rgba("#5EEAD4")
            b["dp_kind"] = "deck"
            self.bars.append(b)

    def update(self, fleet, now: float, extra: str = "") -> None:
        if now - self.last_update < 1.0:
            return
        self.last_update = now
        self.ensure()
        t = fleet.totals(now)
        parts = [f"{t['active']} WORKING", f"{t['waiting']} WAITING"]
        if t["blocked"]:
            parts.append(f"{t['blocked']} BLOCKED")
        idle = t["ducks"] - t["active"] - t["waiting"]
        if idle > 0:
            parts.append(f"{idle} IDLE")
        _set_body(self.line1, "  ·  ".join(parts) if t["ducks"] else "POOL IS EMPTY")
        lines = sum(s.lines_added for s in fleet.sessions.values()), sum(s.lines_removed for s in fleet.sessions.values())
        _set_body(self.line2, f"${t['cost_usd']:.2f} spent  ·  {fmt_tokens(t['tokens_per_min'])} tok/min  ·  "
                              f"+{lines[0]} −{lines[1]} lines  ·  {t['ducklings']} sub-agents")
        _set_body(self.line3, extra or time.strftime("%H:%M  %A %d %B", time.localtime(now)))
        # sparkline: output tokens per minute for the last SPARK_BARS minutes
        hist = {m: tk for m, tk, _ in fleet.history}
        cur = int(now // 60) * 60
        vals = [hist.get(cur - 60 * (SPARK_BARS - 1 - i), 0) for i in range(SPARK_BARS)]
        peak = max(max(vals), 1)
        for i, b in enumerate(self.bars):
            h = max(0.02, 0.9 * vals[i] / peak)
            b.scale = (1.0, 1.0, h)
            b.color = hex_to_rgba("#F5C542" if i == SPARK_BARS - 1 else "#5EEAD4")


class LaneSigns:
    """Per-lane decorations beyond the folder name: a branch line, a coin stack for spend, and
    a small live strip of state colours (one dot per session in the lane)."""

    def __init__(self) -> None:
        self.objects: Dict[str, dict] = {}
        self.last_update = 0.0

    def _ensure(self, key: str, i: int, y: float, w: float) -> dict:
        d = self.objects.get(key)
        if d and d["plate"].name in bpy.data.objects:
            return d
        cam = P.camera()
        plate = P.new_object(f"DP_LanePlate_{i}", MS.plate_mesh("LanePlate", 1.9, 0.9, M.board_material()))
        plate.location = (-P.DECK / 2 - 0.1, y, 0.12)
        plate["dp_kind"] = "deck"
        sub = _text(f"DP_LaneSub_{i}", "", 0.16, M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "CENTER")
        sub.location = (-1.3, y, 0.22)
        c = sub.constraints.new("COPY_ROTATION")
        c.target = cam
        sub["dp_kind"] = "deck"
        dots = []
        dot_mat = M.object_color_material("Dot", roughness=0.4, emission=1.5, alpha_from_object=False)
        for j in range(6):
            o = P.new_object(f"DP_LaneDot_{i}_{j}", MS.sphere_mesh("Dot", 0.06, dot_mat))
            o.location = (-1.3 + 0.24 * (j - 2.5), y - 0.36, 0.16)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "deck"
            dots.append(o)
        coins = []
        for j in range(COINS_MAX):
            o = P.new_object(f"DP_Coin_{i}_{j}", MS.coin_mesh(M.coin_material()))
            o.location = (-1.85, y + 0.32 + 0.03 * (j % 2), 0.1 + 0.035 * j)
            o.rotation_euler = (0.0, 0.0, 0.3 * j)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "deck"
            coins.append(o)
        d = {"plate": plate, "sub": sub, "dots": dots, "coins": coins, "y": y}
        self.objects[key] = d
        return d

    def update(self, lanes, fleet, now: float, redact_on: bool) -> None:
        if now - self.last_update < 1.0:
            return
        self.last_update = now
        keys = list(lanes.keys)
        n = max(1, len(keys))
        w = P.POOL_Y / n
        live_keys = set()
        for i, key in enumerate(keys):
            y = i * w + w / 2
            d = self._ensure(key, i, y, w)
            live_keys.add(key)
            if abs(d["y"] - y) > 1e-6:  # lane moved: move the whole sign
                dy = y - d["y"]
                for o in [d["plate"], d["sub"]] + d["dots"] + d["coins"]:
                    o.location.y += dy
                d["y"] = y
            sessions = [s for s in fleet.sessions.values() if (s.cwd or "(no cwd)") == key]
            live = [s for s in sessions if s.state != "ended"]
            branches = sorted({s.branch for s in live if s.branch})
            cost = sum(s.cost_usd for s in sessions)
            sub_txt = (" · ".join(branches[:2]) + (" +" if len(branches) > 2 else "")) if branches else "—"
            sub_txt += f"   {len(live)} session{'s' if len(live) != 1 else ''}   ${cost:.0f}"
            _set_body(d["sub"], redact(sub_txt, redact_on, 40))
            for j, o in enumerate(d["dots"]):
                if j < len(live):
                    o.color = hex_to_rgba(STATE_COLORS.get(live[j].state, "#8A93A6"))
                    o.hide_viewport = False
                    o.hide_render = False
                else:
                    o.hide_viewport = True
                    o.hide_render = True
            ncoins = min(COINS_MAX, int(cost / COIN_USD))
            for j, o in enumerate(d["coins"]):
                show = j < ncoins
                if o.hide_viewport == show:
                    o.hide_viewport = not show
                    o.hide_render = not show
        for key in [k for k in self.objects if k not in live_keys]:
            d = self.objects.pop(key)
            for o in [d["plate"], d["sub"]] + d["dots"] + d["coins"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass

    def clear(self) -> None:
        for key in list(self.objects):
            d = self.objects.pop(key)
            for o in [d["plate"], d["sub"]] + d["dots"] + d["coins"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass
