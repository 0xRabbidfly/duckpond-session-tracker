"""The world reacts. Time of day comes from the PC clock: the sun wheels over the pool, and
after dark the lido lights come on (underwater lane lights, glowing ducks). Weather comes
from the fleet: glassy water when nobody is generating, chop that grows with tokens per
second, and rain when errors pile up. All values are low-pass filtered per frame so the
water never jumps.
"""
from __future__ import annotations

import math
import time
from typing import List, Optional

import bpy
from mathutils import Vector

from . import materials as M
from . import meshes as MS
from . import pool as P
from ..theme import hex_to_rgba

CHOP_FULL_TPS = 400.0     # fleet output tokens/sec that reads as "storm"
RAIN_FULL_ERR = 4.0       # errors in the last 2 min that reads as a downpour
N_LIGHTS = 6


def daylight(hour: float) -> float:
    """0 at night, 1 at noon, smooth: a raised cosine between 05:30 and 20:30."""
    if hour < 5.5 or hour > 20.5:
        return 0.0
    return math.sin(math.pi * (hour - 5.5) / 15.0)


class Sky:
    def __init__(self) -> None:
        self.clock_override: Optional[float] = None  # hour of day, e.g. 22.5; None = wall clock
        self.chop = 0.0
        self.chop_target = 0.0
        self.night = 0.0
        self.rain = 0.0
        self.rain_target = 0.0
        self.lights: List[bpy.types.Object] = []
        self.last_tick = 0.0
        self._primed = False

    def hour(self, now: float) -> float:
        if self.clock_override is not None:
            return self.clock_override % 24.0
        lt = time.localtime(now)
        return lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0

    # ------------------------------------------------------------ build
    def ensure(self) -> None:
        if self.lights and self.lights[0].name in bpy.data.objects:
            return
        mat = M.object_color_material("LidoLight", roughness=0.3, emission=4.0, alpha_from_object=False)
        post_mat = M.flat_material("Pole", "#C8CCD2", roughness=0.4)
        for i in range(N_LIGHTS):
            for side, y in (("S", -0.55), ("N", P.POOL_Y + 0.55)):
                x = P.POOL_X * (i + 0.5) / N_LIGHTS
                post = P.new_object(f"DP_LidoPost{side}_{i}", MS.pole_mesh(post_mat))
                post.location = (x, y, 0.1)
                post.scale = (1.6, 1.6, 0.6)
                post["dp_kind"] = "deck"
                o = P.new_object(f"DP_LidoLight{side}_{i}", MS.sphere_mesh("LidoLamp", 0.09, mat))
                o.location = (x, y, 0.1 + 0.66 + 0.08)
                o.color = (1.0, 0.72, 0.35, 1.0)
                o.hide_viewport = True
                o.hide_render = True
                o["dp_kind"] = "deck"
                self.lights.append(o)

    # ------------------------------------------------------------ data tick (4 Hz)
    def tick(self, fleet, now: float) -> None:
        tps = fleet.tokens_per_sec(now, 20.0)
        self.chop_target = max(0.0, min(1.0, tps / CHOP_FULL_TPS))
        errs = sum(1 for s in fleet.sessions.values() if s.error_at and now - s.error_at < 120.0)
        errs += sum(1 for s in fleet.sessions.values() for at, _, ok in s.tool_history if not ok and now - at < 120.0) * 0.25
        self.rain_target = max(0.0, min(1.0, errs / RAIN_FULL_ERR))

    # ------------------------------------------------------------ frame
    def update(self, now: float, dt: float) -> None:
        self.ensure()
        k = min(1.0, dt * 0.8)
        self.chop += (self.chop_target - self.chop) * k
        self.rain += (self.rain_target - self.rain) * k
        h = self.hour(now)
        day = daylight(h)
        night = 1.0 - day
        if not self._primed:  # a fresh pool starts at the right time of day, no ramp
            self.night, self.chop, self.rain = night, self.chop_target, self.rain_target
            self._primed = True
        self.night += (night - self.night) * min(1.0, dt * 2.0)
        water = bpy.data.materials.get("DP_Water")
        if water is not None:
            M.water_set_chop(water, self.chop)
            M.water_set_night(water, self.night)
        self._sun(h, day)
        self._world(day)
        on = self.night > 0.5
        for o in self.lights:
            if o.hide_viewport == on:
                o.hide_viewport = not on
                o.hide_render = not on

    def _sun(self, hour: float, day: float) -> None:
        sun = bpy.data.objects.get("DP_Sun")
        if sun is None:
            return
        # azimuth sweeps east -> west across the pool's long axis over the day; elevation follows daylight
        frac = max(0.0, min(1.0, (hour - 5.5) / 15.0))
        elev = math.radians(8 + 62 * day)
        azim = math.radians(-100 + 200 * frac)
        sun.rotation_euler = (math.pi / 2 - elev, 0.0, azim)
        light = sun.data
        light.energy = 0.6 + 3.6 * day  # moonlight floor so the pool never goes black
        warm = 1.0 - day  # low sun is warm
        light.color = (1.0, 0.93 - 0.25 * warm, 0.82 - 0.45 * warm)

    def _world(self, day: float) -> None:
        world = bpy.data.worlds.get("DP_World")
        if world is None or not world.use_nodes:
            return
        nt = world.node_tree
        ramp = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeValToRGB"), None)
        bg = nt.nodes.get("Background")
        if ramp is not None:
            horizon_day = (0.75, 0.85, 0.95)
            horizon_night = (0.10, 0.12, 0.20)
            zenith_day = (0.30, 0.52, 0.85)
            zenith_night = (0.02, 0.03, 0.07)
            dusk = math.sin(math.pi * day) ** 2 * (1.0 - day)  # a warm band around sunrise/sunset
            e0, e1 = ramp.color_ramp.elements[0], ramp.color_ramp.elements[1]
            e0.color = tuple(horizon_day[i] * day + horizon_night[i] * (1 - day) + (0.5, 0.2, 0.0)[i] * dusk for i in range(3)) + (1.0,)
            e1.color = tuple(zenith_day[i] * day + zenith_night[i] * (1 - day) for i in range(3)) + (1.0,)
        if bg is not None:
            bg.inputs["Strength"].default_value = 0.45 + 0.55 * day
