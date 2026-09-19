"""Blender registration: preferences, operators, panel wiring."""
from __future__ import annotations

import os

import bpy

from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.stub import StubAdapter
from .ledger import RANGE_ORDER, RANGES
from .runtime import RT
from .scene import pool as P
from .theme import parse_overrides
from .ui.hover import DUCKPOND_OT_hover
from .ui.panel import VIEW3D_PT_duck_pond

bl_info = {
    "name": "Duck Pond",
    "author": "Nuno Borges",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Duck Pond",
    "description": "Every duck in the pool is a live agent session; ducklings are sub-agents.",
    "category": "3D View",
}

_DEFAULT_FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "demo.json")


def _prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


class DuckPondPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    claude_projects_dir: bpy.props.StringProperty(
        name="Claude Code projects dir", subtype="DIR_PATH",
        default=os.path.join(os.path.expanduser("~"), ".claude", "projects"))
    harness_colors_json: bpy.props.StringProperty(
        name="Harness colours (JSON)", default="", description='{"claude_code": "#D97757", ...}')
    hat_map_json: bpy.props.StringProperty(
        name="Model → hat (JSON)", default="", description='[["astra", "crown"], ...] — first substring match wins')

    def draw(self, context):
        self.layout.prop(self, "claude_projects_dir")
        self.layout.prop(self, "harness_colors_json")
        self.layout.prop(self, "hat_map_json")


def _on_redact(self, context):
    RT.set_redact(self.redact)


def _on_paused(self, context):
    RT.paused = self.paused


def _on_director(self, context):
    RT.director.enabled = self.director
    if self.director:
        RT.motion.follow = None


def _on_tags(self, context):
    RT.tags_for_all = self.tags_for_all


def _on_sound(self, context):
    if self.sound:
        from .sound import Sound
        RT.sound = Sound()
        if not RT.sound.enabled:
            RT.sound = None
            self["sound"] = False
        else:
            RT.sound.mute(3.0)  # do not play the startup replay
    else:
        RT.sound = None


def _on_clock(self, context):
    RT.sky.clock_override = None if self.clock_override < 0 else float(self.clock_override)


def _on_board_range(self, context):
    RT.set_board_range(self.board_range)


def _on_limits(self, context):
    RT.limits.enabled = self.limits
    RT.limits.refresh_s = float(self.limits_every_min) * 60.0
    if self.limits:
        RT.limits.start()
    else:
        RT.limits.stop()


def _on_legend(self, context):
    RT.show_legend = self.legend


class DuckPondSettings(bpy.types.PropertyGroup):
    use_claude: bpy.props.BoolProperty(name="Claude Code (live)", default=True)
    use_stub: bpy.props.BoolProperty(name="Demo fixture", default=False)
    stub_path: bpy.props.StringProperty(name="Fixture", subtype="FILE_PATH", default=_DEFAULT_FIXTURE)
    live_window_min: bpy.props.IntProperty(name="Live window (min)", default=10, min=1, max=240,
                                           description="A transcript touched within this many minutes counts as live")
    redact: bpy.props.BoolProperty(name="Redact text", default=True, update=_on_redact)
    paused: bpy.props.BoolProperty(name="Pause data", default=False, update=_on_paused)
    director: bpy.props.BoolProperty(name="Director", default=False, update=_on_director,
                                     description="Auto camera: frames blocked ducks, questions, spawns and finished reports")
    tags_for_all: bpy.props.BoolProperty(name="Tags on all", default=False, update=_on_tags,
                                         description="Screen-space name + status tag on every duck (kiosk)")
    sound: bpy.props.BoolProperty(name="Sound", default=False, update=_on_sound,
                                  description="Soft synthesised cues: prompt, report, question, error, tests")
    clock_override: bpy.props.FloatProperty(name="Clock (h, -1 = real)", default=-1.0, min=-1.0, max=24.0,
                                            update=_on_clock, description="Force the time of day for the sky and lido lights")
    board_range: bpy.props.EnumProperty(name="Range", items=[(r, r, RANGES[r][1]) for r in RANGE_ORDER], default="hour",
                                        update=_on_board_range,
                                        description="Scoreboard bars and its 'this range' line (T cycles; click a tab on the board)")
    legend: bpy.props.BoolProperty(name="Legend", default=True, update=_on_legend,
                                   description="On-screen key: halo colour = state, body colour = tool, hat = model (H)")
    limits: bpy.props.BoolProperty(name="Sangria (usage limits)", default=True, update=_on_limits,
                                   description="Fill the two jugs from your 5-hour and 7-day limits. "
                                               "Each refresh runs `claude -p /usage`, which spends a few tokens")
    limits_every_min: bpy.props.IntProperty(name="Refresh (min)", default=15, min=2, max=180,
                                            update=_on_limits,
                                            description="How often to ask the CLI. Lower costs more tokens; "
                                                        "the windows move slowly, so 15 minutes is plenty")


def build_adapters(props=None):
    props = props or bpy.context.window_manager.duck_pond
    prefs = _prefs()
    adapters = []
    if props.use_claude:
        d = prefs.claude_projects_dir if prefs else None
        adapters.append(ClaudeCodeAdapter(d or None, live_window_s=props.live_window_min * 60.0))
    if props.use_stub:
        path = bpy.path.abspath(props.stub_path) if props.stub_path else _DEFAULT_FIXTURE
        if os.path.isfile(path):
            adapters.append(StubAdapter(path))
    if prefs:
        RT.color_overrides = parse_overrides(prefs.harness_colors_json, {}) or {}
        RT.hat_overrides = [tuple(x) for x in (parse_overrides(prefs.hat_map_json, []) or []) if len(x) == 2]
    return adapters


class DUCKPOND_OT_start(bpy.types.Operator):
    bl_idname = "duck_pond.start"
    bl_label = "Start"
    bl_description = "Build the pool and start watching sessions"

    def execute(self, context):
        adapters = build_adapters(context.window_manager.duck_pond)
        if not adapters:
            self.report({"WARNING"}, "No source enabled")
            return {"CANCELLED"}
        props = context.window_manager.duck_pond
        RT.set_redact(props.redact)
        RT.start(adapters)
        RT.director.enabled = props.director
        RT.tags_for_all = props.tags_for_all
        RT.set_board_range(props.board_range)
        RT.limits.enabled = props.limits
        RT.limits.refresh_s = float(props.limits_every_min) * 60.0
        _on_sound(props, context)
        _on_clock(props, context)
        return {"FINISHED"}


class DUCKPOND_OT_stop(bpy.types.Operator):
    bl_idname = "duck_pond.stop"
    bl_label = "Stop"

    def execute(self, context):
        RT.stop()
        return {"FINISHED"}


class DUCKPOND_OT_reset(bpy.types.Operator):
    bl_idname = "duck_pond.reset"
    bl_label = "Reset pool"
    bl_description = "Remove everything Duck Pond created"

    def execute(self, context):
        RT.reset()
        return {"FINISHED"}


class DUCKPOND_OT_follow(bpy.types.Operator):
    bl_idname = "duck_pond.follow"
    bl_label = "Follow pinned duck"

    def execute(self, context):
        RT.toggle_follow()
        return {"FINISHED"}


class DUCKPOND_OT_camera_overview(bpy.types.Operator):
    bl_idname = "duck_pond.camera_overview"
    bl_label = "Overview camera"

    def execute(self, context):
        RT.motion.follow = None
        P.camera_overview()
        _look_through_camera(context)
        return {"FINISHED"}


class DUCKPOND_OT_camera_lane(bpy.types.Operator):
    bl_idname = "duck_pond.camera_lane"
    bl_label = "Next lane camera"

    def execute(self, context):
        RT.motion.follow = None
        keys = RT.lanes.keys
        if not keys:
            return {"CANCELLED"}
        idx = (getattr(RT, "_lane_idx", -1) + 1) % len(keys)
        RT._lane_idx = idx
        P.camera_lane(*RT.lanes.bounds[keys[idx]])
        _look_through_camera(context)
        return {"FINISHED"}


class DUCKPOND_OT_open_transcript(bpy.types.Operator):
    bl_idname = "duck_pond.open_transcript"
    bl_label = "Open transcript"

    def execute(self, context):
        if not RT.pinned:
            return {"CANCELLED"}
        s = RT.fleet.sessions.get(RT.pinned[0])
        if not s or not s.transcript_path or not os.path.isfile(s.transcript_path):
            self.report({"WARNING"}, "No transcript file for this session")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=s.transcript_path)
        return {"FINISHED"}


class DUCKPOND_OT_copy_session_id(bpy.types.Operator):
    bl_idname = "duck_pond.copy_session_id"
    bl_label = "Copy session id"

    def execute(self, context):
        if not RT.pinned:
            return {"CANCELLED"}
        context.window_manager.clipboard = RT.pinned[1] or RT.pinned[0]
        return {"FINISHED"}


def _look_through_camera(context):
    for area in context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].region_3d.view_perspective = "CAMERA"


CLASSES = (
    DuckPondPreferences,
    DuckPondSettings,
    DUCKPOND_OT_start,
    DUCKPOND_OT_stop,
    DUCKPOND_OT_reset,
    DUCKPOND_OT_follow,
    DUCKPOND_OT_camera_overview,
    DUCKPOND_OT_camera_lane,
    DUCKPOND_OT_open_transcript,
    DUCKPOND_OT_copy_session_id,
    DUCKPOND_OT_hover,
    VIEW3D_PT_duck_pond,
)


def register() -> None:
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)
    bpy.types.WindowManager.duck_pond = bpy.props.PointerProperty(type=DuckPondSettings)


def unregister() -> None:
    RT.stop()
    if hasattr(bpy.types.WindowManager, "duck_pond"):
        del bpy.types.WindowManager.duck_pond
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
