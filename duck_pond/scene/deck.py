"""The deck is the dashboard: a scoreboard on the far side, lane signs that tell a story.

Numbers live here, on purpose. The water is for feeling; the deck is for reading.
"""
from __future__ import annotations

import time

import bpy
from mathutils import Vector

from ..ledger import RANGE_ORDER, RANGES
from ..theme import STATE_COLORS, hex_to_rgba, redact
from . import materials as M
from . import meshes as MS
from . import pool as P

BOARD_W = 9.0
BOARD_H = 2.3   # the live status row moved to the screen overlay; the board lost a row
BOARD_Z = 1.35  # centre height; the bottom edge stays just above the deck
SPARK_BARS = 60  # bars built; a range shows the first RANGES[name][0] of them
BAR_MAX_H = 0.62  # bars stand in front of the text: keep the tallest clear of the footer from a raised camera
TAB_W = 1.1
TAB_GAP = 1.3
COINS_MAX = 24
SIGN_W = 1.7  # lane sign plate, screen-aligned
SIGN_H = 0.62
SIGN_X = -1.15  # centre on the west deck, clear of the coin stack at the pool edge
# Signs are scaled by their distance to the camera so every lane's sign is the same size on
# screen. Without it the far lane renders about a third smaller than the near one, which is
# the difference between reading its branch and spend line and not.
SIGN_REF_DIST = 17.4  # metres: the overview camera's distance to the middle of the sign row
SIGN_SCALE_RANGE = (0.6, 2.5)
COIN_X = -0.12  # the coin stack stands at the pool edge, beside the sign
SIGN_NAME_CHARS = 17
SIGN_SUB_CHARS = 30
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


def fmt_usd(v: float) -> str:
    return f"≈${v:,.0f}" if v >= 1000 else f"≈${v:.2f}"


def fmt_stats(st) -> str:
    """One ledger Stats as a board line. `+?` = tokens from models with no list price."""
    return (f"{fmt_usd(st.usd)}{' +?' if st.unpriced else ''}  ·  {fmt_tokens(st.tokens_out)} out tok  ·  "
            f"{st.sessions} session{'' if st.sessions == 1 else 's'}")


class Scoreboard:
    """A dark board standing on the north deck, read from across the room.

    Row 1: range tabs (click one, or press T). Row 2: estimated spend for the picked range.
    Row 3: the month so far, whatever the range. Below: ≈$ per bucket for the picked range as
    real geometry, the current bucket in gold. Spend comes from the usage ledger, so it does not
    drop when ducks leave the pool.

    Who is doing what is *not* here: it is drawn in screen space at the top-left, because a
    duck's name tag would park on top of this board and hide it for minutes at a time."""

    def __init__(self) -> None:
        self.board: bpy.types.Object | None = None
        self.line2 = None
        self.line3 = None
        self.line4 = None
        self.tabs: dict[str, dict] = {}
        self.gold = None
        self.dim = None
        self.bars: list[bpy.types.Object] = []
        self.bars_laid_out = 0
        self.last_update = 0.0

    def ensure(self) -> None:
        if self.board is not None and self.board.name in bpy.data.objects:
            return
        x0 = P.POOL_X / 2
        y = P.POOL_Y + P.DECK + 0.05
        z = BOARD_Z
        self.board = P.new_object("DP_Board", MS.plate_mesh("Board", BOARD_W, BOARD_H, M.board_material()))
        self.board.location = (x0, y, z)
        self.board.rotation_euler = (1.5708, 0.0, 0.0)  # stand it up, facing the pool (-Y)
        self.board["dp_kind"] = "deck"
        white = M.text_material()
        self.gold = M.flat_material("TextGold", "#F5C542", roughness=0.8, emission=1.4)
        self.dim = M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8)
        teal = M.flat_material("TextTeal", "#5EEAD4", roughness=0.8, emission=1.4)
        self.line2 = _text("DP_Board_L2", "", 0.24, self.gold, "CENTER")
        self.line3 = _text("DP_Board_L3", "", 0.24, white, "CENTER")
        self.line4 = _text("DP_Board_L4", "", 0.17, teal, "CENTER")
        for o, dz in ((self.line2, 0.34), (self.line3, 0.04), (self.line4, -0.24)):
            o.location = (x0, y - 0.03, z + dz)
            o.rotation_euler = (1.5708, 0.0, 0.0)
            o["dp_kind"] = "deck"
        # range tabs: a plate to click, the name, and an underline under the selected one
        plate_mat = M.flat_material("TabPlate", "#1F2738", roughness=0.8)
        for i, name in enumerate(RANGE_ORDER):
            tx = x0 + TAB_GAP * (i - (len(RANGE_ORDER) - 1) / 2)
            tz = z + 0.78
            plate = P.new_object(f"DP_Board_Tab_{name}", MS.box_mesh("BoardTab", TAB_W, 0.01, 0.36, plate_mat))
            plate.location = (tx, y - 0.015, tz)
            text = _text(f"DP_Board_TabText_{name}", name, 0.22, self.dim, "CENTER")
            text.location = (tx, y - 0.03, tz - 0.08)
            text.rotation_euler = (1.5708, 0.0, 0.0)
            line = P.new_object(f"DP_Board_TabLine_{name}", MS.box_mesh("BoardTabLine", TAB_W * 0.8, 0.01, 0.035, self.gold))
            line.location = (tx, y - 0.035, tz - 0.15)
            line.hide_viewport = True
            line.hide_render = True
            for o in (plate, text, line):
                o["dp_kind"] = "range_tab"
                o["dp_range"] = name
            self.tabs[name] = {"plate": plate, "text": text, "line": line}
        bar_mat = M.object_color_material("Bar", roughness=0.6, emission=0.8, alpha_from_object=False)
        slot = (BOARD_W - 0.8) / SPARK_BARS
        for i in range(SPARK_BARS):
            b = P.new_object(f"DP_Bar_{i:02d}", MS.box_mesh("Bar60", slot * 0.7, 0.05, 1.0, bar_mat, at=(0, 0, 0.5)))
            b.location = (x0, y - 0.05, z - BOARD_H / 2 + 0.1)
            b.scale = (1.0, 1.0, 0.02)
            b.color = hex_to_rgba("#5EEAD4")
            b["dp_kind"] = "deck"
            self.bars.append(b)
        self.bars_laid_out = 0

    def _layout_bars(self, n: int) -> None:
        """Spread the first n bars across the board; hide the rest."""
        if n == self.bars_laid_out:
            return
        self.bars_laid_out = n
        x0 = P.POOL_X / 2
        slot = (BOARD_W - 0.8) / n
        for i, b in enumerate(self.bars):
            show = i < n
            b.hide_viewport = not show
            b.hide_render = not show
            if show:
                b.location.x = x0 - (BOARD_W - 0.8) / 2 + slot * (i + 0.5)
                b.scale.x = SPARK_BARS / n

    def _select_tab(self, name: str) -> None:
        for r, t in self.tabs.items():
            on = r == name
            mat = self.gold if on else self.dim
            if t["text"].data.materials[0] != mat:
                t["text"].data.materials[0] = mat
            if t["line"].hide_viewport == on:
                t["line"].hide_viewport = not on
                t["line"].hide_render = not on

    def update(self, fleet, now: float, board_range: str = "hour", extra: str = "") -> None:
        if now - self.last_update < 1.0:
            return
        self.last_update = now
        self.ensure()
        led = fleet.ledger
        n, label, unit = RANGES[board_range]
        self._select_tab(board_range)
        if led.ready:
            _set_body(self.line2, f"{label}   {fmt_stats(led.range_stats(board_range, now))}")
            _set_body(self.line3, f"{led.month_name(now)}   {fmt_stats(led.month_to_date(now))}")
        else:
            _set_body(self.line2, "scanning logs…")
            _set_body(self.line3, "")
        vals = led.bars(board_range, now)
        peak = max(vals)
        foot = [time.strftime("%H:%M  %A %d %B", time.localtime(now))]
        if peak > 0:
            foot.insert(0, f"peak {fmt_usd(peak)}/{unit}")
        if board_range in ("week", "month"):
            foot.append("logs keep ~30 days")
        _set_body(self.line4, extra or "  ·  ".join(foot))
        self._layout_bars(n)
        for i in range(n):
            b = self.bars[i]
            b.scale.z = max(0.02, BAR_MAX_H * vals[i] / peak) if peak > 0 else 0.02
            b.color = hex_to_rgba("#F5C542" if i == n - 1 else "#5EEAD4")


class LaneSigns:
    """Per-lane decorations beyond the folder name: a branch line, a coin stack for spend, and
    a small live strip of state colours (one dot per session in the lane)."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.last_update = 0.0

    def _ensure(self, key: str, i: int, y: float, w: float) -> dict:
        """One sign per lane, screen-aligned as a whole: the folder name on top, branch · sessions ·
        spend under it, one dot per live session at the bottom, all on one dark plate, so nothing
        covers anything whichever way the camera looks. The coin stack stands on the deck beside it."""
        d = self.objects.get(key)
        if d and d["root"].name in bpy.data.objects:
            return d
        root = P.new_object(f"DP_LaneSign_{i}")
        root.location = (SIGN_X, y, 0.06)
        c = root.constraints.new("COPY_ROTATION")
        c.target = P.camera()
        plate = P.new_object(f"DP_LanePlate_{i}", MS.plate_mesh("LaneSignPlate", SIGN_W, SIGN_H, M.board_material()))
        plate.location = (0.0, SIGN_H / 2, -0.02)
        name = _text(f"DP_LaneName_{i}", "", 0.2, M.text_material(), "CENTER")
        name.location = (0.0, SIGN_H - 0.25, 0.0)
        sub = _text(f"DP_LaneSub_{i}", "", 0.12, M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "CENTER")
        sub.location = (0.0, SIGN_H - 0.43, 0.0)
        dots = []
        dot_mat = M.object_color_material("Dot", roughness=0.4, emission=1.5, alpha_from_object=False)
        for j in range(6):
            o = P.new_object(f"DP_LaneDot_{i}_{j}", MS.sphere_mesh("Dot", 0.06, dot_mat))
            o.location = (0.17 * (j - 2.5), 0.1, 0.0)
            o.scale = (0.75, 0.75, 0.75)
            o.hide_viewport = True
            o.hide_render = True
            dots.append(o)
        for o in [root, plate, name, sub] + dots:
            o["dp_kind"] = "deck"
            if o is not root:
                o.parent = root
        coins = []
        for j in range(COINS_MAX):
            o = P.new_object(f"DP_Coin_{i}_{j}", MS.coin_mesh(M.coin_material()))
            o.location = (COIN_X, y + 0.03 * (j % 2), 0.1 + 0.035 * j)
            o.rotation_euler = (0.0, 0.0, 0.3 * j)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "deck"
            coins.append(o)
        d = {"root": root, "plate": plate, "name": name, "sub": sub, "dots": dots, "coins": coins, "y": y}
        self.objects[key] = d
        return d

    def scale_to_camera(self, cam) -> None:
        """Keep every lane sign the same size on screen, whatever its distance.

        Apparent size goes as scale / distance under perspective, so scaling each sign by its
        own distance cancels the falloff exactly. Called per frame: the camera moves.
        """
        if cam is None:
            return
        try:
            eye = Vector(cam.location)
        except (AttributeError, ReferenceError):
            return
        lo, hi = SIGN_SCALE_RANGE
        for d in self.objects.values():
            root = d.get("root")
            if root is None:
                continue
            try:
                k = (Vector(root.location) - eye).length / SIGN_REF_DIST
            except ReferenceError:
                continue
            k = max(lo, min(hi, k))
            if abs(root.scale.x - k) > 1e-4:
                root.scale = (k, k, k)

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
            if abs(d["y"] - y) > 1e-6:  # lane moved: move the sign (its parts follow) and the coins
                dy = y - d["y"]
                for o in [d["root"]] + d["coins"]:
                    o.location.y += dy
                d["y"] = y
            sessions = [s for s in fleet.sessions.values() if (s.cwd or "(no cwd)") == key]
            live = [s for s in sessions if s.state != "ended"]
            branches = sorted({s.branch for s in live if s.branch})
            cost = fleet.ledger.cwd_month_usd(key, now)  # month to date, including ducks that left
            folder = key.replace("\\", "/").rstrip("/").split("/")[-1] or key
            _set_body(d["name"], folder if len(folder) <= SIGN_NAME_CHARS else folder[:SIGN_NAME_CHARS - 1] + "…")
            detail = f"{len(live)} session{'s' if len(live) != 1 else ''} · ≈${cost:.0f}"
            branch = (" · ".join(branches[:2]) + (" +" if len(branches) > 2 else "")) if branches else ""
            room = SIGN_SUB_CHARS - len(detail) - 3  # sessions and spend first; the branch gets what is left
            if branch and room >= 4:
                detail = f"{redact(branch, redact_on, room)} · {detail}"
            _set_body(d["sub"], detail)
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
            for o in [d["root"], d["plate"], d["name"], d["sub"]] + d["dots"] + d["coins"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass

    def clear(self) -> None:
        for key in list(self.objects):
            d = self.objects.pop(key)
            for o in [d["root"], d["plate"], d["name"], d["sub"]] + d["dots"] + d["coins"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass
