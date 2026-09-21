"""Two jugs of sangria on a table: your Anthropic limits, as drinks.

The 5-hour window and the 7-day window each get a jug. How full it is, is how much of that
window you have spent; the label under it says when it clears. Numbers for both come from the
Claude Code CLI (see `usage_limits`), so an empty jug means a fresh window and a full one
means you are about to be cut off.

It reads at a glance from across a room, which a percentage on a board does not.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Vector

from ..theme import hex_to_rgba
from . import materials as M
from . import meshes as MS
from . import pool as P
from .deck import _text

# The outer corner of the north-east deck, well back from the water. A capture of the window
# on this machine's primary screen showed the right label clipped and I moved the table in;
# that was wrong. The kiosk runs on a much wider second monitor where it always fitted, and
# moving it in pushed the jugs over the board in the middle. Left where it belongs.
TABLE_AT = (15.15, 9.35)
TABLE_R = 1.15
TABLE_TOP_Z = 0.92
JUG_DX = 0.58              # the two jugs either side of the table's centre
JUG_R, JUG_H = 0.26, 0.72
WALL = 0.016               # glass thickness, so the sangria sits inside the jug
# The labels float above the jugs, not under them: below, they sat over the busy end of the
# pool. They are wider apart than the jugs and overhang the table, because they are signage
# rather than furniture -- and they are scaled to the camera at the lane signs' own reference
# distance, so a jug label and a lane sign are exactly the same size on screen.
LABEL_DX = 0.95
LABEL_DY = -0.22
LABEL_Z = 1.95
LABEL_REF_DIST = 15.2
PLATE_W, PLATE_H = 1.78, 1.00
PLATE_SCALE = 0.70         # the pair reads from across a room at a third off; they were shouting
LOGO_R = 0.42              # the mark above and between the two labels
LOGO_RAYS = 11             # a radiating burst
# It used to turn, which is not what the Claude mark does when it is thinking: the rays
# reach out and draw back in, in a wave round the burst. A pulse also survives being small,
# where a slow rotation just looks like a wobble.
LOGO_PULSE_HZ = 0.42       # one wave round the burst every two and a half seconds
LOGO_MIN, LOGO_MAX = 0.42, 1.12   # how far in and out a ray travels, as a fraction of LOGO_R
# The mark floats against the sky, which is pale at noon and near black at midnight, so no
# one appearance can carry both. A deep clay reads as a dark shape against a bright sky; the
# same clay lit from within reads as a glowing one against a dark sky. So the colour stays
# put and the emission follows the hour: nothing by day, plenty by night.
LOGO_COLOR = "#9E3B1B"
LOGO_EMIT_DAY = 0.0
LOGO_EMIT_NIGHT = 2.6
SANGRIA = "#E00010"        # a saturated red, lit from within so it carries through the glass.
# Tuned by measuring the rendered pixels, not by eye. The scene renders through AgX, which
# desaturates bright emission: at 1.6 the fill came out (209,95,93), a coral. This, with a
# thinner glass in front and a matte fill that throws no white specular, measures (214,80,73).
# Biasing the red toward magenta to fight AgX's orange shift made it worse, not better.
SANGRIA_LOW = "#FF2A08"    # barely touched: a shade warmer, like a jug just poured
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


def _ray_mesh(mat):
    """One arm of the burst, lying along +X from the origin.

    Its own object, so its length is its `scale.x` and each arm can reach and draw back on
    its own phase. Scaling X alone leaves the cross-section be, so an arm gets longer without
    getting fatter.

    Drawn from primitives as a nod to the Claude starburst, not the official asset: Duck Pond
    ships no brand files and cannot fetch one offline. Put a real image on a plane here if you
    want the exact mark.
    """
    me = MS._existing("UsageRay")
    if me:
        return me
    b = MS._Builder()
    b.cone(0.036, 0.004, LOGO_R, at=(LOGO_R / 2, 0.0, 0.0),
           rot=Matrix.Rotation(math.radians(90), 4, "Y"), segments=10)
    return b.finish("UsageRay", [mat])


def _hub_mesh(mat):
    me = MS._existing("UsageHub")
    if me:
        return me
    b = MS._Builder()
    b.sphere(0.055, scale=(1.0, 1.0, 0.45))
    return b.finish("UsageHub", [mat])



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
                M.object_color_material("Sangria", roughness=0.45, emission=1.0, alpha_from_object=False)))
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
            head = _text(f"DP_JugTitle_{key}", title, 0.20, M.text_material(), "CENTER")
            head.location = (0.0, PLATE_H - 0.29, 0.0)
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
        # the mark sits between the two labels and above them, on its own screen-aligned root
        logo_root = P.new_object("DP_UsageLogoRoot")
        logo_root.location = (x, y + LABEL_DY, LABEL_Z + 1.62)  # clear of the plates below it
        lc = logo_root.constraints.new("COPY_ROTATION")
        lc.target = P.camera()
        # created with an emission so the node exists; `pulse` sets the strength each frame
        ray_mat = M.flat_material("UsageLogo", LOGO_COLOR, roughness=0.45, emission=1.0)
        hub = P.new_object("DP_UsageHub", _hub_mesh(ray_mat))
        hub.parent = logo_root
        rays = []
        for i in range(LOGO_RAYS):
            a = 2 * math.pi * i / LOGO_RAYS
            ray = P.new_object(f"DP_UsageRay{i}", _ray_mesh(ray_mat))
            ray.parent = logo_root
            ray.rotation_euler = (0.0, 0.0, a)
            ray.scale = (LOGO_MIN, 1.0, 1.0)
            rays.append(ray)
        for o in (logo_root, hub, *rays):
            o["dp_kind"] = "deck"
        self.objects["logo_root"] = logo_root
        self.objects["rays"] = rays
        self.objects["logo_mat"] = ray_mat

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
            sub = (g.resets or "") if usage.ok else "no reading"
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
        # one distance for both, measured at the table: scaling each label by its own distance
        # left the nearer plate visibly larger than the far one
        table = self.objects.get("table")
        if table is None:
            return
        k = max(0.6, min(2.5, (Vector(table.location) - eye).length / LABEL_REF_DIST))
        # the plates and their text ride one root, so a single scale shrinks the container
        # and everything written on it together
        sized = [(self.objects[key]["root"], k * PLATE_SCALE) for _t, key in WINDOWS
                 if key in self.objects]
        if "logo_root" in self.objects:
            # the mark shrinks with the plates it belongs to, or it towers over them
            sized.append((self.objects["logo_root"], k * PLATE_SCALE))
        for root, s in sized:
            try:
                if abs(root.scale.x - s) > 1e-4:
                    root.scale = (s, s, s)
            except ReferenceError:
                return

    def pulse(self, now: float, night: float = 0.0) -> None:
        """Reach the arms out and draw them back, one wave running round the burst.

        Each arm is a quarter-turn behind the one before it, so the burst breathes in a
        rotating wave rather than all at once -- which is what the Claude mark does while it
        is thinking. The arms' own root copies the camera's rotation, so the whole thing
        stays face-on however the camera moves.

        `night` is the sky's own 0-to-1, and it decides how much the mark is lit from within.
        By day it is unlit, and the deep clay reads as a dark shape against a bright sky; by
        night it glows, and reads as a bright one against a dark sky. One colour, both skies.
        """
        rays = self.objects.get("rays")
        if not rays:
            return
        mid = (LOGO_MAX + LOGO_MIN) / 2
        half = (LOGO_MAX - LOGO_MIN) / 2
        try:
            for i, ray in enumerate(rays):
                phase = 2 * math.pi * i / LOGO_RAYS
                s = mid + half * math.sin(now * 2 * math.pi * LOGO_PULSE_HZ - phase)
                ray.scale = (s, 1.0, 1.0)
            mat = self.objects.get("logo_mat")
            if mat is not None:
                want = LOGO_EMIT_DAY + (LOGO_EMIT_NIGHT - LOGO_EMIT_DAY) * max(0.0, min(1.0, night))
                inp = mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
                if abs(inp.default_value - want) > 1e-3:
                    inp.default_value = want
        except (ReferenceError, KeyError, AttributeError):
            self.objects = {}
