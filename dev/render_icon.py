"""Render a clean app icon: one Claude-clay duck in a top hat on transparent background.

    blender -b --python dev/render_icon.py      -> launcher/duck_icon.png (512x512, RGBA)

dev/build_exe.py turns it into launcher/duck.ico.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond.scene import pool as P  # noqa: E402
from duck_pond.scene.duck import DuckObj  # noqa: E402

duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

scene = bpy.context.scene
P.ensure_pool()
# hide everything but the duck: the pool objects are still needed for materials, so just move the camera in
d = DuckObj("icon", "", "claude_code", "claude-opus-5", "", False)
d.place(P.POOL_X / 2, P.POOL_Y / 2, 0.02, math.radians(200), 0.0, math.radians(-6))
d.set_label("")
d.set_flag("")
for o in bpy.data.objects:
    if o.get("dp_kind") in ("water", "deck", "fx") or o.name.startswith(("DP_Floor", "DP_Wall", "DP_Deck", "DP_Ladder", "DP_Block", "DP_Lido")):
        o.hide_render = True
cam = P.camera()
target = Vector(d.obj.location) + Vector((0.0, 0.0, 0.32))
cam.location = target + Vector((-1.35, -1.55, 1.0))
P.look_at(cam, target)
cam.data.lens = 60
sun = bpy.data.objects.get("DP_Sun")
if sun:
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(-60))
    sun.data.energy = 4.5
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
try:
    scene.eevee.taa_render_samples = 48
except AttributeError:
    pass
out = os.path.join(ROOT, "launcher", "duck_icon.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("[icon] wrote", out)
