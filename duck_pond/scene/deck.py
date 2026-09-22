"""The deck is the dashboard: a scoreboard on the far side, lane signs that tell a story.

Numbers live here, on purpose. The water is for feeling; the deck is for reading.
"""
from __future__ import annotations

import bpy
from mathutils import Vector

from ..theme import STATE_COLORS, folder_name, hex_to_rgba, redact
from . import materials as M
from . import meshes as MS
from . import pool as P

SIGN_W = 2.2  # lane sign plate, screen-aligned
SIGN_H = 0.80
SIGN_X = -1.05  # centre on the west deck (the deck runs from -2.0 to the pool lip at 0)
# Signs are scaled by their distance to the camera so every lane's sign is the same size on
# screen. Without it the far lane renders about a third smaller than the near one, which is
# the difference between reading its branch and spend line and not.
# The distance to the *nearest* sign, not the middle of the row: the near sign keeps the size
# it always had -- it is the one with a frame edge and a coin stack to run into -- and the far
# ones grow up to meet it. Scaling the whole row up instead pushed the near sign off-frame.
SIGN_REF_DIST = 15.2
SIGN_SCALE_RANGE = (0.6, 2.5)
SIGN_NAME_CHARS = 17
SIGN_SUB_CHARS = 25  # fewer than before: the detail line is much bigger now


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


class LaneSigns:
    """Per-lane decorations beyond the folder name: a branch line, the month's spend, and a
    small live strip of state colours (one dot per session in the lane)."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.last_update = 0.0

    def _ensure(self, key: str, i: int, y: float, w: float) -> dict:
        """One sign per lane, screen-aligned as a whole: the folder name on top, branch · sessions ·
        spend under it, one dot per live session at the bottom, all on one dark plate, so nothing
        covers anything whichever way the camera looks."""
        d = self.objects.get(key)
        if d and d["root"].name in bpy.data.objects:
            return d
        root = P.new_object(f"DP_LaneSign_{i}")
        root.location = (SIGN_X, y, 0.06)
        c = root.constraints.new("COPY_ROTATION")
        c.target = P.camera()
        plate = P.new_object(f"DP_LanePlate_{i}", MS.plate_mesh("LaneSignPlate", SIGN_W, SIGN_H, M.board_material()))
        plate.location = (0.0, SIGN_H / 2, -0.02)
        name = _text(f"DP_LaneName_{i}", "", 0.27, M.text_material(), "CENTER")
        name.location = (0.0, SIGN_H - 0.33, 0.0)
        sub = _text(f"DP_LaneSub_{i}", "", 0.185, M.flat_material("TextDim", "#B8C2D6", roughness=0.8, emission=0.8), "CENTER")
        sub.location = (0.0, SIGN_H - 0.59, 0.0)
        dots = []
        dot_mat = M.object_color_material("Dot", roughness=0.4, emission=1.5, alpha_from_object=False)
        for j in range(6):
            o = P.new_object(f"DP_LaneDot_{i}_{j}", MS.sphere_mesh("Dot", 0.06, dot_mat))
            o.location = (0.20 * (j - 2.5), 0.12, 0.0)
            o.scale = (0.75, 0.75, 0.75)
            o.hide_viewport = True
            o.hide_render = True
            dots.append(o)
        for o in [root, plate, name, sub] + dots:
            o["dp_kind"] = "deck"
            if o is not root:
                o.parent = root
        d = {"root": root, "plate": plate, "name": name, "sub": sub, "dots": dots, "y": y}
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
            if abs(d["y"] - y) > 1e-6:  # lane moved: the sign moves and its parts follow
                d["root"].location.y = y
                d["y"] = y
            sessions = [s for s in fleet.sessions.values() if (s.cwd or "(no cwd)") == key]
            live = [s for s in sessions if s.state != "ended"]
            branches = sorted({s.branch for s in live if s.branch})
            cost = fleet.ledger.cwd_month_usd(key, now)  # month to date, including ducks that left
            _set_body(d["name"], folder_name(key, SIGN_NAME_CHARS))
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
        for key in [k for k in self.objects if k not in live_keys]:
            d = self.objects.pop(key)
            for o in [d["root"], d["plate"], d["name"], d["sub"]] + d["dots"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass

    def clear(self) -> None:
        for key in list(self.objects):
            d = self.objects.pop(key)
            for o in [d["root"], d["plate"], d["name"], d["sub"]] + d["dots"]:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass
