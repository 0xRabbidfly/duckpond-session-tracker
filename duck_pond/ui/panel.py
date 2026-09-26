"""N-panel: controls, totals, pinned session details (the click level of attention)."""
from __future__ import annotations

import time

import bpy

from .. import herdr
from ..runtime import RT
from ..theme import redact
from . import cards


class VIEW3D_PT_duck_pond(bpy.types.Panel):
    bl_label = "Duck Pond"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Duck Pond"

    def draw(self, context):
        layout = self.layout
        props = context.window_manager.duck_pond
        now = time.time()

        row = layout.row(align=True)
        if RT.running:
            row.operator("duck_pond.stop", icon="PAUSE")
        else:
            row.operator("duck_pond.start", icon="PLAY")
        row.operator("duck_pond.reset", icon="TRASH", text="")
        layout.label(text=RT.status, icon="INFO")
        if RT.last_error:
            layout.label(text="last error in console", icon="ERROR")
        if RT.revivals:
            layout.label(text=f"watchdog revived {RT.revivals}x", icon="RECOVER_LAST")

        box = layout.box()
        box.label(text="Sources")
        box.prop(props, "use_claude")
        box.prop(props, "use_stub")
        if props.use_stub:
            box.prop(props, "stub_path", text="")
        box.prop(props, "live_window_min")
        row = box.row(align=True)
        row.prop(props, "limits", toggle=True)
        sub = row.row(align=True)
        sub.enabled = props.limits
        sub.prop(props, "limits_every_min", text="every")
        box.prop(props, "laundry", toggle=True)

        box = layout.box()
        box.label(text="View")
        row = box.row()
        row.prop(props, "redact", toggle=True, icon="HIDE_OFF" if props.redact else "HIDE_ON")
        row.prop(props, "paused", toggle=True, icon="PAUSE")
        row = box.row()
        row.prop(props, "tags_for_all", toggle=True, icon="FONTPREVIEW")
        row.prop(props, "director", toggle=True, icon="CAMERA_DATA")
        row.prop(props, "sound", toggle=True, icon="SPEAKER")
        row.prop(props, "legend", toggle=True, icon="HELP")
        if herdr.available():
            box.prop(props, "herdr_focus", toggle=True, icon="CONSOLE")
        row = box.row(align=True)
        row.operator("duck_pond.camera_overview", text="Overview", icon="VIEW_CAMERA")
        row.operator("duck_pond.camera_lane", text="Next lane", icon="TRACKING_FORWARDS")
        row.operator("duck_pond.follow", text="Unfollow" if RT.motion.follow else "Follow", icon="OUTLINER_OB_CAMERA")
        box.prop(props, "board_range", expand=True)
        box.prop(props, "clock_override")

        layout.separator()
        layout.label(text=cards.totals_line(RT.fleet, now))

        key = RT.pinned
        if key:
            s = RT.fleet.sessions.get(key[0])
            if s:
                box = layout.box()
                kind = "duckling" if key[1] else "duck"
                box.label(text="Pinned", icon="PINNED")
                card = cards.card_for(RT.fleet, kind, key, now, RT.redact)
                if card:
                    box.label(text=f"{card.title} — {card.state_text}")
                    box.label(text=card.subtitle)
                    if card.context_text:
                        box.label(text=card.context_text)
                    if card.highlight:
                        box.label(text=card.highlight, icon="QUESTION")
                    for ln in card.lines:
                        box.label(text=ln)
                    if card.tool_mix:
                        box.label(text="tools (10 min): " + "  ".join(f"{t} ×{n}" for t, n, _ in card.tool_mix))
                row = box.row(align=True)
                row.operator("duck_pond.open_transcript", icon="FILE_TEXT")
                row.operator("duck_pond.copy_session_id", icon="COPYDOWN")
                if s.model_usage:
                    mu = box.box()
                    mu.label(text="Spend by model")
                    for model, u in s.model_usage.items():
                        if isinstance(u, dict):
                            mu.label(text=f"{model}: ${float(u.get('costUSD', 0)):.2f} · out {cards.fmt_tokens(int(u.get('outputTokens', 0)))} · "
                                          f"think {cards.fmt_tokens(int(u.get('thinkingTokens', 0)))}")
                if s.subagents:
                    sub_box = box.box()
                    sub_box.label(text="Sub-agents")
                    for sub in sorted(s.subagents.values(), key=lambda a: a.started_at):
                        icon = "CHECKMARK" if sub.done and sub.ok else "ERROR" if sub.done else "PLAY"
                        tag = " (bg)" if sub.background else ""
                        nest = f" ↳{sub.parent_agent_id[:6]}" if sub.parent_agent_id else ""
                        sub_box.label(text=f"{sub.agent_type or sub.id[:8]}{tag}{nest} · {sub.state} · {redact(sub.description, RT.redact, 40)}", icon=icon)
                packets = [p for sub in s.subagents.values() for p in sub.packets]
                if packets:
                    pk_box = box.box()
                    pk_box.label(text="Recent packets")
                    for p in sorted(packets, key=lambda p: p.at)[-8:]:
                        arrow = "↓" if p.direction == "down" else "↑"
                        pk_box.label(text=f"{arrow} {p.kind}: {redact(p.text, RT.redact, 60)}")
                if s.tool_history:
                    th = box.box()
                    th.label(text="Last tools")
                    for at, cat, ok in list(s.tool_history)[-6:]:
                        th.label(text=f"{time.strftime('%H:%M:%S', time.localtime(at))} {cat}{'' if ok else '  FAILED'}",
                                 icon="CHECKMARK" if ok else "ERROR")
        else:
            layout.label(text="Hover a duck for its card; click to pin it here.")
        layout.label(text="Keys: R redact · F follow · Home overview · L lanes · P pause")
        layout.label(text="      K tags on all · C director camera · S sound · T board range · H legend")
