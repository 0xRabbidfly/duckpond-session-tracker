"""Launch the real Blender GUI on the demo fixture, wait, screenshot the viewport, quit.

    blender --python dev/gui_shot.py -- --out out/gui_tags.png --at 9 --kiosk
    blender --python dev/gui_shot.py -- --out out/gui_card.png --at 9 --pin cc-fable-1
    blender --python dev/gui_shot.py -- --out out/gui_line.png --at 9 --line   # the washing line's card

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
from duck_pond.cli_version import Versions  # noqa: E402
from duck_pond.runtime import RT  # noqa: E402
from duck_pond.usage_limits import Gauge, Usage  # noqa: E402

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
PLANE = arg("--plane", None)   # 0..1: park the banner that far into its crossing
LINE = "--line" in args        # hover the washing line: its card lists every repository

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
    # Sample limits, not the real ones: a screenshot must not spend tokens.
    RT.limits.enabled = False
    RT.limits.set_snapshot(Usage(session=Gauge(0.24, "Sep 19, 8:30pm"),
                                 week=Gauge(0.62, "Sep 26, 4pm"), ok=True))
    # and a sample pair for the banner plane, so a screenshot needs no network
    RT.versions.enabled = False
    RT.versions.set_snapshot(Versions(yours="2.1.273", latest="2.1.278"))
    # and the demo's sample washing line: its folders are made up, so there is no git to ask
    RT.laundry.set_sample(True)
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
    if "__sampled__" not in RT.fleet.ledger._cwd_usd:
        # a day of spend for the mosaic, against the lanes the fixture has made by now
        RT.fleet.ledger.sample_history(time.time(), list(RT.lanes.keys), usd_scale=1.6)
        RT.fleet.ledger._cwd_usd["__sampled__"] = {}
        RT.tick(time.time())
    if PLANE is not None:
        from duck_pond.scene import plane as plane_mod
        cross = (plane_mod.X1 - plane_mod.X0) / plane_mod.SPEED
        RT.plane.phase = cross * float(PLANE) - time.time()
    if PIN:
        RT.pinned = (PIN, "")
        RT.hover = RT.pinned
        RT.hover_kind = "duck"
        for a in bpy.context.screen.areas:
            a.tag_redraw()
        bpy.app.timers.register(_save, first_interval=0.6)
        return None
    if LINE:
        # the real mouse over this window re-casts on every move and would clear it at once
        from duck_pond.ui.hover import DUCKPOND_OT_hover
        DUCKPOND_OT_hover._cast = lambda self, context, event: None
        RT.hover, RT.hover_kind = None, "laundry"
        for a in bpy.context.screen.areas:
            a.tag_redraw()
        bpy.app.timers.register(_save, first_interval=0.6)
        return None
    if PLANE is not None:
        bpy.app.timers.register(_save, first_interval=0.5)  # let a frame fly it there
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
