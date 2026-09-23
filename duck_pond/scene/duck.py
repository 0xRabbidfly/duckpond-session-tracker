"""Duck / duckling objects with hats, tail flags, status bubbles and context rings."""
from __future__ import annotations

import math

import bpy
from mathutils import Vector

from ..theme import HAT_COLORS, context_ring_color, context_ring_holed, harness_color, hat_for_model
from . import materials as M
from . import meshes as MS
from . import pool as P

SESSION_SCALE = 1.35
DUCKLING_SCALE = SESSION_SCALE * 0.45
# Text is sized in WORLD metres (the objects are parented to a scaled duck, so the curve size
# is divided by that scale): glyph heights readable from the overview camera without names from
# neighbouring ducks running into each other (ducks in a lane sit ~1.6 m apart).
LABEL_H_DUCK = 0.2
LABEL_H_DUCKLING = 0.13
FLAG_H = 0.15
BUBBLE_H = 0.45


def _hat_mats(kind: str):
    main = M.flat_material(f"Hat_{kind}", HAT_COLORS.get(kind, "#888888"), roughness=0.45)
    accent = M.flat_material("HatAccent", "#F4C542", roughness=0.35, emission=0.3)
    return main, accent


def _billboard(obj: bpy.types.Object) -> None:
    """Screen-align a text object: copying the camera's rotation keeps the glyph plane parallel
    to the view everywhere in frame, so a name reads left to right whichever way its duck is
    heading (a TRACK_TO aimed at the camera skewed labels away from the view centre)."""
    c = obj.constraints.new("COPY_ROTATION")
    c.target = P.camera()


def _text_object(name: str, body: str, size: float, billboard: bool = True, outline: bool = False) -> bpy.types.Object:
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = "CENTER"
    cu.materials.append(M.text_material())
    obj = P.new_object(name, cu)
    if billboard:
        _billboard(obj)
    if outline:
        # a fattened black copy just behind the glyphs: legible over water, deck and ducks alike
        oc = bpy.data.curves.new(name + "_outline", "FONT")
        oc.body = body
        oc.size = size
        oc.align_x = "CENTER"
        oc.offset = size * 0.05
        oc.materials.append(M.flat_material("TextOutline", "#0B0F14", roughness=1.0))
        out = P.new_object(name + "_outline", oc)
        out.parent = obj
        out.location = (0.0, 0.0, -0.004)
        obj["dp_outline"] = out.name
    return obj


def _set_body(obj: bpy.types.Object, text: str) -> None:
    if obj.data.body != text:
        obj.data.body = text
    out = bpy.data.objects.get(obj.get("dp_outline", "")) if "dp_outline" in obj else None
    if out is not None and out.data.body != text:
        out.data.body = text


class DuckObj:
    """Wraps one duck (session) or duckling (sub-agent) object plus its children."""

    def __init__(self, session_id: str, agent_id: str, harness: str, model: str, branch: str,
                 duckling: bool, color_overrides=None, hat_overrides=None) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        self.duckling = duckling
        self.color_overrides = color_overrides
        self.hat_overrides = hat_overrides
        short = session_id if len(session_id) <= 12 else session_id[:8]
        name = f"DP_Duckling_{agent_id}" if duckling else f"DP_Duck_{short}"
        mesh = MS.duck_mesh(M.duck_body_material(),
                            M.flat_material("Bill", "#F28C28", roughness=0.35),
                            M.flat_material("Eye", "#111111", roughness=0.2))
        self.obj = P.new_object(name, mesh)
        self.obj["dp_kind"] = "duckling" if duckling else "duck"
        self.obj["dp_session_id"] = session_id
        self.obj["dp_agent_id"] = agent_id
        s = DUCKLING_SCALE if duckling else SESSION_SCALE
        self.obj.scale = (s, s, s)
        self.set_color(harness_color(harness, color_overrides))
        self.hat = None
        self.hat_kind = ""
        self.set_hat(model)
        self.flag = None
        if not duckling:
            # the branch flag flies over the tail, screen-aligned like the name so it reads
            # left to right whichever way the duck is heading
            self.flag = _text_object(f"{name}_flag", branch or "", FLAG_H / s, billboard=True)
            self.flag.parent = self.obj
            self.flag.location = MS.TAIL_TIP + Vector((0.0, 0.0, 0.16))
            P.add_badge(self.flag)
        self.label = _text_object(f"{name}_label", "", (LABEL_H_DUCKLING if duckling else LABEL_H_DUCK) / s,
                                  billboard=True)
        self.label.parent = self.obj
        self.label.location = MS.HEAD_TOP + Vector((0.0, 0.0, 0.62 if duckling else 0.74))
        self.label["dp_kind"] = "label"
        self.label["dp_session_id"] = session_id
        self.label["dp_agent_id"] = agent_id
        P.add_badge(self.label)  # white on a dark badge: legible over water, deck and ducks
        self.label_text = ""
        self.badges_dirty = True
        # the state halo: a ring on the water in the state colour (teal working, yellow waiting,
        # red blocked, grey idle). Replaces the "?" / "!" glyphs, which read the same in every state.
        self.halo = P.new_object(f"{name}_halo", MS.halo_mesh(M.halo_material()))
        self.halo.scale = (s, s, 1.0)
        self.halo.color = (0.5, 0.5, 0.5, 0.0)
        self.halo["dp_kind"] = "hat"
        self.halo["dp_session_id"] = session_id
        self.halo["dp_agent_id"] = agent_id
        self.halo_color = (0.5, 0.5, 0.5, 0.0)
        # The ring is the context gauge: always worn, and its colour is how full the context is.
        # A ring that only appeared at 95 % told you nothing for the first 94 %.
        # Both rings are built up front (the mesh is cached per name, so only the first duck
        # pays for them): swapping the data is then the whole of going full, and no mesh is
        # created from the frame handler.
        ring_mat = M.object_color_material("ContextRing", roughness=0.3, emission=0.25, alpha_from_object=False)
        self.ring_meshes = (MS.lifering_mesh(ring_mat), MS.lifering_holed_mesh(ring_mat))
        self.lifering = P.new_object(f"{name}_ring", self.ring_meshes[0])
        self.lifering.parent = self.obj
        # Worn the way a person wears one: high at the back of the neck, sloping down over the
        # chest and dipping into the water at the front. Level at the neck it cut straight
        # across the bill; this way the nearest point to the bill is 0.23 rather than 0.04.
        self.lifering.location = (0.125, 0.0, 0.13)
        self.lifering.rotation_euler = (0.0, math.radians(38.7), 0.0)
        self.lifering["dp_kind"] = "hat"  # hovering the ring hovers the duck
        self.lifering["dp_session_id"] = session_id
        self.lifering["dp_agent_id"] = agent_id
        self.ring_color = None
        self.ring_holed = False
        self.obj["dp_glow"] = 0.0
        # beacon: a pole with a light on top that comes on when the duck needs you. Legible
        # from across the room, which the "?" glyph alone was not.
        self.pole = P.new_object(f"{name}_pole", MS.pole_mesh(M.flat_material("Pole", "#C8CCD2", roughness=0.4)))
        self.pole.parent = self.obj
        self.pole.location = MS.TAIL_TIP + Vector((0.05, 0.0, -0.05))
        self.pole.scale = (1.0 / s, 1.0 / s, (0.55 if duckling else 0.75) / s)
        self.beacon = P.new_object(f"{name}_beacon", MS.sphere_mesh("Beacon", 0.11, M.beacon_material()))
        self.beacon.parent = self.obj
        self.beacon.location = self.pole.location + Vector((0.0, 0.0, (0.55 if duckling else 0.75) * 1.1 / s))
        self.beacon.scale = (1.0 / s, 1.0 / s, 1.0 / s)
        for o in (self.pole, self.beacon):
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "hat"  # hovering the beacon hovers the duck
            o["dp_session_id"] = session_id
            o["dp_agent_id"] = agent_id
        self.beacon_on = False
        self.beacon_color = (1.0, 1.0, 1.0, 1.0)
        # mail tray: one amber letter per prompt you typed while the duck was still working
        self.trays = []
        if not duckling:
            tray_mesh = MS.tray_mesh(M.flat_material("Tray", "#FFB347", roughness=0.5, emission=0.6))
            for i in range(3):
                t = P.new_object(f"{name}_tray{i}", tray_mesh)
                t.parent = self.obj
                t.location = Vector((-0.42, 0.0, 0.06 + 0.03 * i))
                t.rotation_euler = (0.0, 0.0, 0.25 * (i - 1))
                t.hide_viewport = True
                t.hide_render = True
                t["dp_kind"] = "hat"
                t["dp_session_id"] = session_id
                t["dp_agent_id"] = agent_id
                self.trays.append(t)
        self.mail = 0

    # ------------------------------------------------------------ appearance
    def set_beacon(self, color, pulse: float = 1.0) -> None:
        """color = RGBA or None (off). pulse in 0..1 scales the light."""
        on = color is not None
        if on != self.beacon_on:
            self.beacon_on = on
            for o in (self.pole, self.beacon):
                o.hide_viewport = not on
                o.hide_render = not on
        if on:
            s = self.obj.scale.x or 1.0
            k = (0.7 + 0.6 * pulse) / s
            self.beacon.scale = (k, k, k)
            if color != self.beacon_color:
                self.beacon_color = color
                self.beacon.color = color

    def set_mail(self, n: int) -> None:
        n = max(0, min(3, int(n)))
        if n == self.mail:
            return
        self.mail = n
        for i, t in enumerate(self.trays):
            show = i < n
            t.hide_viewport = not show
            t.hide_render = not show

    def set_glow(self, k: float) -> None:
        if abs(self.obj.get("dp_glow", 0.0) - k) > 0.01:
            self.obj["dp_glow"] = k

    def set_color(self, rgba) -> None:
        self.obj.color = rgba

    def set_alpha(self, a: float) -> None:
        c = self.obj.color
        self.obj.color = (c[0], c[1], c[2], max(0.0, min(1.0, a)))

    def set_hat(self, model: str) -> None:
        kind = hat_for_model(model, self.hat_overrides)
        if kind == self.hat_kind and self.hat:
            return
        if self.hat:
            P.remove_object(self.hat)
        main, accent = _hat_mats(kind)
        self.hat = P.new_object(f"{self.obj.name}_hat", MS.hat_mesh(kind, main, accent))
        self.hat.parent = self.obj
        self.hat.location = MS.HEAD_TOP
        self.hat["dp_kind"] = "hat"
        self.hat["dp_session_id"] = self.session_id
        self.hat["dp_agent_id"] = self.agent_id
        self.hat_kind = kind

    def set_label(self, text: str) -> None:
        if text != self.label_text:
            self.label_text = text
            _set_body(self.label, text)
            self.badges_dirty = True

    def set_world_label_visible(self, show: bool) -> None:
        """Hidden while a screen-space tag names this duck (kiosk tags, hover, pin)."""
        if self.label.hide_viewport != (not show):
            self.label.hide_viewport = not show
            badge = bpy.data.objects.get(self.label.get("dp_badge", ""))
            if badge is not None:
                badge.hide_viewport = not show or not self.label_text.strip()
                badge.hide_render = badge.hide_viewport
            self.badges_dirty = True

    def set_flag(self, text: str) -> None:
        if self.flag and self.flag.data.body != text:
            _set_body(self.flag, text)
            self.badges_dirty = True

    def fit_badges(self) -> None:
        """Resize the name and branch badges after their text changed. Runs from the data timer:
        fitting evaluates the depsgraph, which a frame-change handler must not do."""
        if not self.badges_dirty:
            return
        self.badges_dirty = False
        for o in (self.label, self.flag):
            if o is not None:
                P.fit_badge(o)

    def set_halo(self, color) -> None:
        """RGBA; alpha 0 hides it."""
        if color != self.halo_color:
            self.halo_color = color
            self.halo.color = color

    def set_context(self, frac: float) -> None:
        """Dress the ring for a context fill of `frac` (0..1): its band's colour, and in the
        top band the punctured ring instead of the whole one."""
        col = context_ring_color(frac)
        if col != self.ring_color:
            self.ring_color = col
            self.lifering.color = col
        holed = context_ring_holed(frac)
        if holed != self.ring_holed:
            self.ring_holed = holed
            self.lifering.data = self.ring_meshes[1 if holed else 0]

    # ------------------------------------------------------------ transform
    def place(self, x: float, y: float, z: float, heading: float, pitch: float, roll: float, scale_mul: float = 1.0) -> None:
        self.obj.location = (x, y, z)
        self.obj.rotation_euler = (roll, pitch, heading)
        s = (DUCKLING_SCALE if self.duckling else SESSION_SCALE) * scale_mul
        self.obj.scale = (s, s, s)
        self.halo.location = (x, y, P.WATER_Z + 0.012)
        self.halo.scale = (s, s, 1.0)

    @property
    def position(self) -> Vector:
        return Vector(self.obj.location)

    def world_point(self, local: Vector) -> Vector:
        return self.obj.matrix_world @ local

    def remove(self) -> None:
        texts = [o for o in (self.flag, self.label) if o is not None]
        extras = [bpy.data.objects.get(o.get(k, "")) for o in texts for k in ("dp_outline", "dp_badge")]
        for o in extras + texts + [self.hat, self.lifering, self.pole, self.beacon, self.halo] + self.trays + [self.obj]:
            if o is not None:
                P.remove_object(o)  # takes the duck's own text curves with it
