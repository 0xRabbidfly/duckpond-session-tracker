"""A banner plane, towing your Claude Code version past the pool.

Every couple of minutes a little propeller plane crosses the sky dragging a banner: the
published version of the CLI on the top row, the one you are running underneath. It is the
one piece of news in the pool that is not about a session, and a plane is the right carrier
for it -- you look up, read it, and it leaves.

Where the sky is, measured rather than guessed. The lawn is a disc whose far edge is the
horizon, and from the overview camera that edge sits at 0.81 of the frame height, so the sky
is the top fifth and nothing else. A plane at y 20, z 0.62 sits in the middle of that
band: low in world terms, but beyond the lawn's edge, so nothing occludes it and it
reads as being up in the air.
"""
from __future__ import annotations

import math

import bpy
from mathutils import Matrix

from . import materials as M
from . import meshes as MS
from . import pool as P
from .deck import _set_body, _text

LANE_Y = 20.0
LANE_Z = 0.62            # centred in the sky band; at 1.05 it grazed the top edge
X0, X1 = -13.0, 40.0     # off the left edge to off the right; the rig is 11 units long
SPEED = 3.2              # units per second: about fifteen seconds to cross
EVERY_S = 150.0          # one flypast every two and a half minutes
BOB = 0.11               # a little air under it, so it is not on rails
BOB_HZ = 0.35
PROP_SPIN = 22.0         # radians per second; fast enough to blur into a disc

BODY = "#E8E4DC"         # cream, so it holds up against both a pale sky and a black one
TRIM = "#C2462F"
DARK = "#252A33"
# A long tow line, so the plane and its banner are rarely behind the board at the top
# of the screen at the same moment: while one is covered the other is usually clear.
ROPE_LEN = 3.30
# The plate is built one unit wide and stretched to whatever the rows turn out to be. A
# version string is not a fixed width -- 2.1.9 and 2.1.278 differ, and the second row grows
# a whole word when you are behind -- and a banner whose text runs off the end of it is worse
# than no banner. Measured once per text change, which is once every few hours.
BANNER_UNIT = 1.0
BANNER_H = 2.0
BANNER_SCALE = 0.75      # a quarter off: less of the thin sky band, less to clip
BANNER_PAD = 0.45
ROW_SIZE = 0.60
BA, BB = 0, 1            # material slots: body, trim


def _plane_mesh(body, trim, dark):
    """Nose along +X, which is the way it flies."""
    me = MS._existing("Plane")
    if me:
        return me
    b = MS._Builder()
    ry = Matrix.Rotation(math.radians(90), 4, "Y")
    b.cone(0.07, 0.20, 1.30, at=(-0.35, 0, 0), rot=ry, slot=BA, segments=16)    # tail boom
    b.cone(0.20, 0.27, 0.55, at=(0.575, 0, 0), rot=ry, slot=BA, segments=16)    # body
    b.cone(0.27, 0.05, 0.40, at=(1.05, 0, 0), rot=ry, slot=BB, segments=16)     # nose cone
    b.sphere(0.16, at=(0.42, 0, 0.17), scale=(1.5, 0.85, 0.80), slot=2)         # cockpit
    b.box(0.62, 3.10, 0.06, at=(0.38, 0, 0.02), slot=BA)                        # wing
    b.box(0.10, 3.10, 0.03, at=(0.66, 0, 0.05), slot=BB)                        # wing stripe
    b.box(0.38, 1.20, 0.05, at=(-0.86, 0, 0.05), slot=BA)                       # tailplane
    b.box(0.40, 0.05, 0.50, at=(-0.90, 0, 0.30), slot=BB)                       # fin
    for sy in (-1, 1):                                                          # undercarriage
        b.cone(0.028, 0.028, 0.30, at=(0.36, sy * 0.30, -0.14), slot=2, segments=8)
        b.sphere(0.095, at=(0.36, sy * 0.30, -0.30), scale=(1.0, 0.55, 1.0), slot=2)
    return b.finish("Plane", [body, trim, dark])


def _prop_mesh(dark):
    """Two blades in the YZ plane, so the object spins about its own X."""
    me = MS._existing("PlaneProp")
    if me:
        return me
    b = MS._Builder()
    b.sphere(0.075, scale=(1.4, 1.0, 1.0))
    b.box(0.03, 0.10, 0.98)
    b.box(0.03, 0.98, 0.10)
    return b.finish("PlaneProp", [dark])


def _rope_mesh(dark):
    me = MS._existing("PlaneRope")
    if me:
        return me
    b = MS._Builder()
    b.cone(0.018, 0.018, ROPE_LEN, at=(0, 0, 0),
           rot=Matrix.Rotation(math.radians(90), 4, "Y"), segments=6)
    return b.finish("PlaneRope", [dark])


class BannerPlane:
    """The plane, its propeller, and the banner it tows."""

    def __init__(self) -> None:
        self.objects: dict = {}
        self.last_text: dict[str, str] = {}
        # None, not False: the first _show must actually run. Left at False it no-ops,
        # and the plane sits parked and visible at the start of the runway.
        self._flying: bool | None = None
        # shifts the flypast clock. A screenshot wants the plane in shot, not wherever
        # the two-and-a-half-minute cycle happens to have left it.
        self.phase = 0.0

    def ensure(self) -> None:
        if self.objects and self.objects["root"].name in bpy.data.objects:
            return
        self.objects = {}
        self._flying = None
        body = M.flat_material("PlaneBody", BODY, roughness=0.42)
        trim = M.flat_material("PlaneTrim", TRIM, roughness=0.40)
        dark = M.flat_material("PlaneDark", DARK, roughness=0.55)

        root = P.new_object("DP_PlaneRoot")
        root.location = (X0, LANE_Y, LANE_Z)
        plane = P.new_object("DP_Plane", _plane_mesh(body, trim, dark))
        plane.parent = root
        prop = P.new_object("DP_PlaneProp", _prop_mesh(dark))
        prop.parent = root
        prop.location = (1.27, 0.0, 0.0)
        rope = P.new_object("DP_PlaneRope", _rope_mesh(dark))
        rope.parent = root
        rope.location = (-1.0 - ROPE_LEN / 2, 0.0, 0.0)

        # the banner stands up and faces the camera: the plate and the text are built lying in
        # XY, so one quarter-turn about X puts them in XZ with their faces toward -Y
        banner = P.new_object("DP_PlaneBanner")
        banner.parent = root
        banner.rotation_euler = (math.radians(90), 0.0, 0.0)
        banner.scale = (BANNER_SCALE, BANNER_SCALE, BANNER_SCALE)
        plate = P.new_object("DP_PlaneBannerPlate",
                             MS.plate_mesh("BannerPlate", BANNER_UNIT, BANNER_H, M.board_material()))
        plate.parent = banner
        top = _text("DP_PlaneRowTop", "", ROW_SIZE, M.text_material(), "CENTER")
        top.parent = banner
        top.location = (0.0, 0.30, 0.02)
        bot = _text("DP_PlaneRowBottom", "", ROW_SIZE,
                    M.flat_material("TextGold", "#F5C542", roughness=0.8, emission=1.4), "CENTER")
        bot.parent = banner
        bot.location = (0.0, -0.72, 0.02)

        for o in (root, plane, prop, rope, banner, plate, top, bot):
            o["dp_kind"] = "deck"
        self.objects = {"root": root, "prop": prop, "top": top, "bottom": bot,
                        "banner": banner, "plate": plate,
                        "all": [plane, prop, rope, plate, top, bot]}
        self._fit()
        self._show(False)

    def _fit(self) -> None:
        """Stretch the plate to the wider of the two rows and hang it off the rope.

        `dimensions` is only right once the depsgraph has caught up with the new text, so this
        asks for an update -- affordable because it runs when the version changes, not on a frame.
        """
        try:
            bpy.context.view_layer.update()
            # `dimensions` is in world units -- it carries the parent's scale -- while the
            # plate's scale is in the banner's own space. Divide back out, or the banner
            # shrinks by BANNER_SCALE twice and comes out narrower than its own text.
            rows = max(self.objects["top"].dimensions.x, self.objects["bottom"].dimensions.x)
            w = max(rows / BANNER_SCALE + 2 * BANNER_PAD, 3.0)
            self.objects["plate"].scale = (w / BANNER_UNIT, 1.0, 1.0)
            # the front edge stays on the rope; the banner grows backwards from there.
            # `w` is in the banner's own space, which the scale shrinks before it lands.
            self.objects["banner"].location = (-1.0 - ROPE_LEN - w * BANNER_SCALE / 2, 0.0, 0.0)
        except (ReferenceError, KeyError, AttributeError):
            pass

    def _show(self, on: bool) -> None:
        if self._flying == on and self.objects:
            return
        self._flying = on
        for o in self.objects.get("all", []):
            o.hide_viewport = not on
            o.hide_render = not on

    def update(self, now: float, dt: float, versions) -> None:
        """Fly it across, once every EVERY_S, if there is anything to say."""
        self.ensure()
        if versions is None or not versions.known:
            self._show(False)      # no reading: no banner. Two question marks help nobody
            return
        cross = (X1 - X0) / SPEED
        t = (now + self.phase) % EVERY_S
        if t > cross:
            self._show(False)
            return
        latest = versions.latest or "?"
        yours = versions.yours or "?"
        rows = (f"LATEST  v{latest}",
                f"YOURS  v{yours}" + ("  ·  UPDATE" if versions.behind else ""))
        try:
            changed = False
            for slot, text in zip(("top", "bottom"), rows):
                if self.last_text.get(slot) != text:
                    self.last_text[slot] = text
                    _set_body(self.objects[slot], text)
                    changed = True
            if changed:
                self._fit()
            self._show(True)
            root = self.objects["root"]
            root.location = (X0 + SPEED * t, LANE_Y,
                             LANE_Z + BOB * math.sin(now * 2 * math.pi * BOB_HZ))
            # a gentle pitch only: more than this and the banner reads as skewed rather
            # than flying, because it is a flat sign seen at an angle already
            root.rotation_euler = (math.radians(1.5) * math.sin(now * 2 * math.pi * BOB_HZ),
                                   0.0, 0.0)
            self.objects["prop"].rotation_euler = (now * PROP_SPIN % (2 * math.pi), 0.0, 0.0)
        except ReferenceError:
            self.objects = {}
