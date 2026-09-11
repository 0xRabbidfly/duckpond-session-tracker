"""Launch the real Blender GUI on the demo fixture, wait, screenshot the viewport, quit.

    blender --python dev/gui_shot.py -- --out out/gui_tags.png --at 9 --kiosk
    blender --python dev/gui_shot.py -- --out out/gui_card.png --at 9 --pin cc-fable-1

Used to verify the screen-space overlay (hover card, name tags), which headless renders
cannot show. The stub fixture is run at 1x; `--at` is the fixture second to shoot at.
"""
import os
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond.adapters.stub import StubAdapter  # noqa: E402
from duck_pond.runtime import RT  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else default
    return default


OUT = os.path.abspath(arg("--out", os.path.join(ROOT, "out", "gui_shot.png")))
AT = float(arg("--at", "9"))
PIN = arg("--pin", None)
KIOSK = "--kiosk" in args
CLOCK = arg("--clock", None)

duck_pond.register()
props = bpy.context.window_manager.duck_pond
props.use_stub = True
props.use_claude = False
props.tags_for_all = KIOSK
props.director = False
try:
    bpy.context.preferences.view.show_splash = False
except AttributeError:
    pass
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

stub = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
T_START = time.time()


def _style(space):
    space.shading.type = "RENDERED"
    ov = space.overlay
    for a in ("show_floor", "show_axis_x", "show_axis_y", "show_relationship_lines", "show_extras", "show_cursor",
              "show_object_origins", "show_outline_selected", "show_text", "show_stats"):
        try:
            setattr(ov, a, False)
        except AttributeError:
            pass
    space.show_gizmo = False
    space.show_region_ui = not KIOSK
    space.region_3d.view_perspective = "CAMERA"


def _go():
    RT.start([stub])
    RT.tags_for_all = KIOSK
    if CLOCK is not None:
        RT.sky.clock_override = float(CLOCK)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                _style(area.spaces[0])
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                    bpy.ops.screen.screen_full_area(use_hide_panels=KIOSK)
                bpy.app.timers.register(_fit, first_interval=0.5)
                break
    return None


def _fit():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                    bpy.ops.view3d.view_center_camera()
                return None
    return None


def _shoot():
    if time.time() - T_START < AT + 1.0:
        return 0.25
    if PIN:
        RT.pinned = (PIN, "")
        RT.hover = RT.pinned
        RT.hover_kind = "duck"
        for a in bpy.context.screen.areas:
            a.tag_redraw()
        bpy.app.timers.register(_save, first_interval=0.6)
        return None
    return _save()


def _save():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=OUT)
                print("[gui_shot] saved", OUT)
                bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.5)
                return None
    return None


bpy.app.timers.register(_go, first_interval=0.3)
bpy.app.timers.register(_shoot, first_interval=1.0)
