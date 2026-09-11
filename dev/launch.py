"""Launch Blender with Duck Pond registered and running.

    blender --python dev/launch.py            # live Claude Code sessions
    blender --python dev/launch.py -- --stub  # demo fixture only
    blender --python dev/launch.py -- --both  # live + demo
    blender --python dev/launch.py -- --app   # pool only (no Blender UI) in a normal maximised window
    add --fullscreen for borderless fullscreen (Alt+F11 toggles back)
    blender --python dev/launch.py -- --kiosk # --app + auto camera director + name tags on every duck
    add --sound for the soft cues (prompt bloop, report chime, error buzz)
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402

duck_pond.register()

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
props = bpy.context.window_manager.duck_pond
props.use_stub = "--stub" in args or "--both" in args
props.use_claude = "--stub" not in args
KIOSK = "--kiosk" in args
APP_MODE = "--app" in args or KIOSK
# app/kiosk mode maximises the pool INSIDE a normal OS window (title bar: minimise, move,
# maximise, snap). Borderless fullscreen is opt-in with --fullscreen (Alt+F11 toggles it back).
FULLSCREEN = "--fullscreen" in args
props.director = KIOSK
props.tags_for_all = KIOSK
props.sound = "--sound" in args
try:
    bpy.context.preferences.view.show_splash = False
except AttributeError:
    pass

# fresh scene: drop the default cube/light/camera
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)


def _style_viewport(space, kiosk: bool):
    space.shading.type = "RENDERED"
    ov = space.overlay
    for attr in ("show_floor", "show_axis_x", "show_axis_y", "show_relationship_lines", "show_extras",
                 "show_cursor", "show_object_origins", "show_outline_selected", "show_bones",
                 "show_motion_paths", "show_annotation", "show_light_colors"):
        try:
            setattr(ov, attr, False)
        except AttributeError:
            pass
    if kiosk:
        for attr in ("show_text", "show_stats", "show_fade_inactive"):
            try:
                setattr(ov, attr, False)
            except AttributeError:
                pass
        space.show_gizmo = False
        space.show_region_header = False
        space.show_region_toolbar = False
        space.show_region_ui = False
        try:
            space.show_region_tool_header = False
        except AttributeError:
            pass
    else:
        space.show_region_ui = True
    space.region_3d.view_perspective = "CAMERA"


def _fit_camera():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                try:
                    with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                        bpy.ops.view3d.view_center_camera()
                except Exception as exc:  # noqa: BLE001
                    print("[duck_pond] fit camera:", exc)
                return None
    return None


def _go():
    adapters = duck_pond.build_adapters(props)
    duck_pond.RT.start(adapters)
    duck_pond.RT.director.enabled = props.director
    duck_pond.RT.tags_for_all = props.tags_for_all
    if props.sound:
        from duck_pond.sound import Sound
        duck_pond.RT.sound = Sound()
        duck_pond.RT.sound.mute(3.0)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                _style_viewport(area.spaces[0], APP_MODE)
                if APP_MODE:
                    try:
                        with bpy.context.temp_override(window=window, screen=window.screen, area=area):
                            bpy.ops.screen.screen_full_area(use_hide_panels=True)
                            if FULLSCREEN:
                                bpy.ops.wm.window_fullscreen_toggle()
                            bpy.app.timers.register(_fit_camera, first_interval=0.5)
                    except Exception as exc:  # noqa: BLE001
                        print("[duck_pond] app mode layout:", exc)
                break
    return None


bpy.app.timers.register(_go, first_interval=0.3)

# --quit-after N: exit after N seconds (used to smoke-test DuckPond.exe end to end)
if "--quit-after" in args:
    _secs = float(args[args.index("--quit-after") + 1])

    def _quit():
        print(f"[duck_pond] quit-after {_secs}s: status={duck_pond.RT.status} ducks={len(duck_pond.RT.ducks)}")
        bpy.ops.wm.quit_blender()
        return None

    bpy.app.timers.register(_quit, first_interval=_secs)
