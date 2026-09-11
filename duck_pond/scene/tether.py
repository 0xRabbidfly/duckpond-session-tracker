"""Tethers (vibrating ropes) and the packets that travel along them."""
from __future__ import annotations

import math
from typing import List, Optional

import bpy
from mathutils import Vector, noise

from . import materials as M
from . import meshes as MS
from . import pool as P
from ..theme import hex_to_rgba, redact

SEGMENTS = 24
TRAVERSE_S = 1.5
MAX_LABELS_PER_TETHER = 3
LABEL_POOL = 50
PACKET_POOL = 200
COLOR_DOWN = hex_to_rgba("#FFB347")
COLOR_UP = hex_to_rgba("#5EEAD4")


class Tether:
    def __init__(self, session_id: str, agent_id: str, color) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        cu = bpy.data.curves.new(f"DP_Tether_{agent_id}", "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = 0.012
        cu.bevel_resolution = 3
        cu.fill_mode = "FULL"
        cu.materials.append(M.tether_material())
        sp = cu.splines.new("POLY")
        sp.points.add(SEGMENTS - 1)
        self.obj = P.new_object(f"DP_Tether_{agent_id}", cu)
        self.obj["dp_kind"] = "tether"
        self.obj["dp_session_id"] = session_id
        self.obj["dp_agent_id"] = agent_id
        self.obj["dp_pulse"] = 0.0
        c = color
        self.obj.color = (c[0] * 0.6, c[1] * 0.6, c[2] * 0.6, 1.0)
        self.points: List[Vector] = [Vector((0, 0, 0)) for _ in range(SEGMENTS)]
        self.pulse = 0.0
        self.retract = 1.0  # 1 = full length, shrinks while a duckling merges back
        self.base_color = (c[0] * 0.6, c[1] * 0.6, c[2] * 0.6)
        self.style = (None, None)

    def set_style(self, background: bool, active: bool) -> None:
        """Background agents hang on a thin, faded leash (they outlive the turn); an active link
        is thick and lit; a finished or idle one is thin and dull."""
        if (background, active) == self.style:
            return
        self.style = (background, active)
        cu = self.obj.data
        cu.bevel_depth = 0.006 if background else (0.016 if active else 0.010)
        r, g, b = self.base_color
        k = 0.55 if background else (1.4 if active else 0.8)
        self.obj.color = (min(1.0, r * k), min(1.0, g * k), min(1.0, b * k), 1.0)
        self.obj["dp_pulse"] = max(float(self.obj.get("dp_pulse", 0.0)), 0.15 if active else 0.0)

    def update(self, p0: Vector, p1: Vector, amp: float, freq: float, t: float, dt: float) -> None:
        """p0 = parent tail, p1 = duckling chest. amp in metres, freq in Hz."""
        sp = self.obj.data.splines[0]
        end = p0.lerp(p1, self.retract)
        d = end - p0
        length = max(d.length, 1e-4)
        side = Vector((-d.y, d.x, 0.0)).normalized() if length > 1e-3 else Vector((0, 1, 0))
        seed = hash(self.agent_id) % 97
        for i in range(SEGMENTS):
            s = i / (SEGMENTS - 1)
            base = p0 + d * s
            env = math.sin(math.pi * s)
            sag = -0.06 * env * min(1.0, length / 1.5)
            vib = 0.0
            lat = 0.0
            if amp > 0.0:
                phase = 2 * math.pi * (freq * t + s * 3.0) + seed
                n = noise.noise(Vector((s * 6.0 + seed, t * freq * 0.7, 0.0)))
                vib = amp * env * (math.sin(phase) + 0.5 * n)
                lat = amp * env * 0.6 * math.cos(phase * 0.8 + 1.3)
            pt = base + Vector((0.0, 0.0, sag + vib)) + side * lat
            self.points[i] = pt
            sp.points[i].co = (pt.x, pt.y, pt.z, 1.0)
        self.pulse = max(0.0, self.pulse - dt * 2.5)
        self.obj["dp_pulse"] = max(self.pulse, 0.15 if self.style[1] else 0.0)

    def flash(self) -> None:
        self.pulse = 1.0

    def sample(self, s: float) -> Vector:
        s = max(0.0, min(1.0, s)) * (SEGMENTS - 1)
        i = int(s)
        if i >= SEGMENTS - 1:
            return self.points[-1].copy()
        return self.points[i].lerp(self.points[i + 1], s - i)

    def remove(self) -> None:
        try:
            bpy.data.objects.remove(self.obj, do_unlink=True)
        except ReferenceError:
            pass


class _PacketVisual:
    __slots__ = ("packet", "sphere", "label", "tether", "progress", "color")

    def __init__(self, packet, sphere, label, tether, color):
        self.packet = packet
        self.sphere = sphere
        self.label = label
        self.tether = tether
        self.progress = 0.0
        self.color = color


class PacketSystem:
    """Object pools for packet spheres and their labels."""

    def __init__(self) -> None:
        self.spheres: List[bpy.types.Object] = []
        self.labels: List[bpy.types.Object] = []
        self.free_spheres: List[bpy.types.Object] = []
        self.free_labels: List[bpy.types.Object] = []
        self.active: List[_PacketVisual] = []
        self.redact_enabled = True
        # packet text deserves a hover, not a glance: labels ride only on the tethers of this
        # session (the hovered or pinned one). None = no labels anywhere.
        self.label_session: Optional[str] = None

    def ensure_pools(self) -> None:
        if self.spheres:
            return
        mesh = MS.sphere_mesh("Packet", 0.05, M.packet_material())
        for i in range(PACKET_POOL):
            o = P.new_object(f"DP_Packet_{i:03d}", mesh)
            o.hide_viewport = True
            o.hide_render = True
            o["dp_kind"] = "packet"
            self.spheres.append(o)
        self.free_spheres = list(self.spheres)
        cam = P.camera()
        for i in range(LABEL_POOL):
            cu = bpy.data.curves.new(f"DP_PacketLabel_{i:02d}", "FONT")
            cu.body = ""
            cu.size = 0.13
            cu.align_x = "CENTER"
            cu.materials.append(M.text_material())
            o = P.new_object(f"DP_PacketLabel_{i:02d}", cu)
            c = o.constraints.new("TRACK_TO")
            c.target = cam
            c.track_axis = "TRACK_Z"
            c.up_axis = "UP_Y"
            o.hide_viewport = True
            o.hide_render = True
            self.labels.append(o)
        self.free_labels = list(self.labels)

    def spawn(self, packet, tether: Tether) -> Optional[_PacketVisual]:
        self.ensure_pools()
        if not self.free_spheres:
            return None
        sphere = self.free_spheres.pop()
        sphere.hide_viewport = False
        sphere.hide_render = False
        color = COLOR_DOWN if packet.direction == "down" else COLOR_UP
        sphere.color = color
        label = None
        labels_on_tether = sum(1 for v in self.active if v.tether is tether and v.label is not None)
        if self.free_labels and labels_on_tether < MAX_LABELS_PER_TETHER and self.label_session == packet.session_id:
            label = self.free_labels.pop()
            label.data.body = redact(packet.text, self.redact_enabled, 80)
            label.hide_viewport = False
            label.hide_render = False
        vis = _PacketVisual(packet, sphere, label, tether, color)
        self.active.append(vis)
        tether.flash()
        return vis

    def update(self, dt: float) -> List[_PacketVisual]:
        """Advance packets; return the ones that arrived this step."""
        arrived = []
        for vis in list(self.active):
            vis.progress += dt / TRAVERSE_S
            s = vis.progress if vis.packet.direction == "down" else 1.0 - vis.progress
            pos = vis.tether.sample(s)
            vis.sphere.location = pos
            fade = 1.0 if vis.progress < 0.85 else max(0.0, (1.0 - vis.progress) / 0.15)
            c = vis.color
            vis.sphere.color = (c[0], c[1], c[2], fade)
            if vis.label:
                vis.label.location = pos + Vector((0.0, 0.0, 0.13))
            if vis.progress >= 1.0:
                self._release(vis)
                arrived.append(vis)
        return arrived

    def _release(self, vis: _PacketVisual) -> None:
        self.active.remove(vis)
        vis.sphere.hide_viewport = True
        vis.sphere.hide_render = True
        self.free_spheres.append(vis.sphere)
        if vis.label:
            vis.label.hide_viewport = True
            vis.label.hide_render = True
            vis.label.data.body = ""
            self.free_labels.append(vis.label)

    def release_tether(self, tether: Tether) -> None:
        for vis in [v for v in self.active if v.tether is tether]:
            self._release(vis)

    def clear(self) -> None:
        for vis in list(self.active):
            self._release(vis)
