"""Headless Blender smoke test: builds the pool from the demo fixture, simulates time, renders a still.

    blender -b --python tests/headless_smoke.py
"""
import os
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond.adapters.stub import StubAdapter  # noqa: E402
from duck_pond.runtime import RT  # noqa: E402

OUT = os.path.join(ROOT, "out")
os.makedirs(OUT, exist_ok=True)

duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

stub = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
RT.start([stub], gui=False)
RT.remove_after = 20.0  # shorten fade for the test

t0 = time.time()
stub.started = t0
RT.last_frame_t = t0


def simulate_until(t_rel: float, step: float = 0.1):
    global _t
    while _t < t_rel:
        _t += step
        now = t0 + _t
        if int(_t / step) % int(0.25 / step) == 0:
            RT.tick(now)
        RT.frame(now, dt=step)


_t = 0.0
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL", msg)
    else:
        print("ok  ", msg)


def obj(name):
    return bpy.data.objects.get(name)


simulate_until(3.5)
check(len([o for o in bpy.data.objects if o.get("dp_kind") == "duck"]) == 4, "4 session ducks after 3.5 s")
fable = obj("DP_Duck_cc-fable-1")
check(fable is not None and fable.color[0] > 0.5 and fable.color[2] < 0.2, "Claude Code duck is clay coloured")
check(obj("DP_Duck_cc-fable-1_hat") is not None and obj("DP_Duck_cc-fable-1_hat").data.name == "DP_Hat_wizard", "Fable wears the wizard hat")
check(obj("DP_Duck_cc-opus-2_hat").data.name == "DP_Hat_top_hat", "Opus wears the top hat")
check(obj("DP_Duck_codex-3_hat").data.name == "DP_Hat_cap", "Codex wears the cap")
check(obj("DP_Duck_vscode-4_hat").data.name == "DP_Hat_beret", "Sonnet wears the beret")
check(len(RT.lanes.keys) == 3, f"3 lanes for 3 working directories (got {RT.lanes.keys})")
check(obj("DP_LaneRope_1") is not None and obj("DP_LaneSign_0") is not None, "lane ropes and signs exist")
check(obj("DP_Duck_cc-fable-1_flag").data.body == "master", "tail flag shows the branch")
check(obj("DP_Duck_cc-fable-1_label").data.body == "duck pond spec", "name label shows the session title")
_badge = obj("DP_Duck_cc-fable-1_label_badge")
check(_badge is not None and not _badge.hide_viewport and _badge.scale.x > 0.5 and _badge.scale.y > 0.1 and _badge.location.z < 0,
      f"name sits on a dark badge sized to it ({tuple(round(v, 2) for v in _badge.scale) if _badge else None})")
_ln, _ls = obj("DP_LaneName_0"), obj("DP_LaneSub_0")
check(_ln is not None and _ln.data.body and _ls is not None and "session" in _ls.data.body and _ln.parent == obj("DP_LaneSign_0")
      and _ls.parent == obj("DP_LaneSign_0") and obj("DP_LanePlate_0").parent == obj("DP_LaneSign_0"),
      f"lane sign: name over details on one plate ({_ln.data.body if _ln else None} / {_ls.data.body if _ls else None})")
_h = obj("DP_Duck_cc-opus-2_halo").color
check(_h[3] > 0.5 and _h[0] > 0.8 and _h[2] < 0.2, f"waiting duck has a yellow halo {tuple(round(c, 2) for c in _h)}")
_h = obj("DP_Duck_cc-fable-1_halo").color
check(_h[3] > 0.5 and _h[1] > 0.6 and _h[0] < 0.3, f"working duck has a teal halo {tuple(round(c, 2) for c in _h)}")
check(not obj("DP_Duck_cc-fable-1_beacon").hide_viewport and obj("DP_Duck_cc-fable-1_beacon").color[1] > 0.6, "working duck's lamp is teal")
check(obj("DP_Duck_cc-opus-2_halo").location.z < 0.05 and abs(obj("DP_Duck_cc-opus-2_halo").location.x - obj("DP_Duck_cc-opus-2").location.x) < 1e-6,
      "halo lies flat on the water under its duck")
check(RT.motion.states[("cc-fable-1", "")].speed > 0.3, "generating duck paddles")
_opus = RT.motion.states[("cc-opus-2", "")]
check(_opus.speed < 0.05 or _opus.relocating, "waiting duck floats still (unless paddling to a re-laid lane)")
check(len(RT.ripples.active_rings) > 0, "water has active ripple rings")
check(obj("DP_Duck_cc-opus-2").location.z < -0.08, "opus at 91 % context sits low in the water")
check(obj("DP_Duck_vscode-4").rotation_euler.y > 0.1, "tool-running duck dips its head")
# --- reimagined: glance-level state, the deck dashboard, the world
check(not obj("DP_Duck_cc-opus-2_beacon").hide_viewport and obj("DP_Duck_cc-opus-2_beacon").color[0] > 0.8 and obj("DP_Duck_cc-opus-2_beacon").color[2] < 0.2,
      "waiting duck's lamp is yellow")
check(RT.fleet.sessions["cc-fable-1"].effort == "max", "effort is read from the fixture")
check(obj("DP_Board") is not None and "WORKING" in obj("DP_Board_L1").data.body, f"scoreboard reads: {obj('DP_Board_L1').data.body}")
check(RT.fleet.ledger.ready, "the ledger backfill finished")
check(all(obj(f"DP_Board_Tab_{r}") is not None for r in ("min", "hour", "day", "week", "month")), "scoreboard has the five range tabs")
check(sum(1 for b in RT.board.bars if not b.hide_viewport) == 24 and any(b.scale.z > 0.05 for b in RT.board.bars),
      "hour range: 24 bars with a live one")
check(obj("DP_Board_L2").data.body.startswith("last 24 h") and "≈$" in obj("DP_Board_L2").data.body, f"range line: {obj('DP_Board_L2').data.body}")
check("≈$" in obj("DP_Board_L3").data.body, f"month line: {obj('DP_Board_L3').data.body}")
RT.set_board_range("min")
RT.board.update(RT.fleet, t0 + _t, RT.board_range)
check(sum(1 for b in RT.board.bars if not b.hide_viewport) == 60 and obj("DP_Board_L2").data.body.startswith("last 60 min"),
      f"min range: 60 bars ({obj('DP_Board_L2').data.body})")
check(obj("DP_Board_TabLine_min") is not None and not obj("DP_Board_TabLine_min").hide_viewport and obj("DP_Board_TabLine_hour").hide_viewport,
      "the selected tab is underlined")
RT.set_board_range("hour")
check(any(not o.hide_viewport for o in RT.fx.chips), "a tool chip is on screen (bash / edit / read…)")
check(RT.fx.active_orbs or any(not o.hide_viewport for o in RT.fx.orbs), "thought bubbles / drops / risers are pooled and visible")
check(len(RT.signs.objects) == 3, f"every lane has a sign plate ({len(RT.signs.objects)})")
RT.signs.last_update = 0.0
RT.signs.update(RT.lanes, RT.fleet, t0 + _t, RT.redact)
_portal = [(k, d) for k, d in RT.signs.objects.items() if "AI-HUB-Portal" in k]
_usd = RT.fleet.ledger.cwd_month_usd(_portal[0][0], t0 + _t) if _portal else 0.0
check(bool(_portal) and _usd > 0 and sum(1 for o in _portal[0][1]["coins"] if not o.hide_viewport) == min(24, int(_usd)),
      f"AI-HUB-Portal lane shows its month spend as a coin stack (≈${_usd:.2f})")
check(RT.sky.chop >= 0.0 and RT.sky.night < 0.5 or RT.sky.clock_override is None, "sky is in a valid day state")

# lane re-layout must not make ducks shake: headings may flip at most a couple of times
import math
import math as _m

_hist = {k: [] for k in RT.motion.states if not k[1]}
_t_end = 5.0
_i = 0
while _t < _t_end:
    _t += 0.033
    _i += 1
    if _i % 8 == 0:
        RT.tick(t0 + _t)
    RT.frame(t0 + _t, dt=0.033)
    for k in _hist:
        _hist[k].append(RT.motion.states[k].heading)
_flips = {k[0]: sum(1 for a, b in zip(h, h[1:]) if abs(((b - a + _m.pi) % (2 * _m.pi)) - _m.pi) > 1.0) for k, h in _hist.items()}
check(max(_flips.values()) <= 2, f"no heading jitter after lanes changed (flips per duck: {_flips})")
RT.tick(t0 + _t)

RT.pinned = ("cc-fable-1", "")  # packet text is hover/pin-level detail: pin the duck to see it
simulate_until(6.0)
check(obj("DP_Duckling_explore-a") is not None, "explore duckling spawned")
check(obj("DP_Duckling_explore-a_hat").data.name == "DP_Hat_kasa", "haiku duckling wears the kasa")
check(obj("DP_Duckling_explore-a_label").data.body == "find where sessions are logged", "duckling label shows its description")
check(obj("DP_Tether_explore-a") is not None, "tether exists")
check(any(not o.hide_viewport for o in RT.packets.spheres), "a packet is travelling")
check(any(o.data.body for o in RT.packets.labels if not o.hide_viewport), "packet label carries text")
tether = RT.tethers[("cc-fable-1", "explore-a")]
pts_before = [p.copy() for p in tether.points]
simulate_until(6.5)
moved = max((a - b).length for a, b in zip(pts_before, tether.points))
check(moved > 0.002, f"tether vibrates while the sub-agent streams (moved {moved:.4f} m)")
check(obj("DP_Duckling_gp-b") is not None, "second duckling spawned")

# render a still at the busiest moment
simulate_until(9.0)
scene = bpy.context.scene
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.join(OUT, "smoke_eevee.png")
try:
    scene.eevee.taa_render_samples = 16
except AttributeError:
    pass
rendered = False
try:
    bpy.ops.render.render(write_still=True)
    rendered = os.path.isfile(scene.render.filepath)
except Exception as exc:  # noqa: BLE001
    print("EEVEE render failed:", exc)
if not rendered:
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.filepath = os.path.join(OUT, "smoke_workbench.png")
    bpy.ops.render.render(write_still=True)
    rendered = os.path.isfile(scene.render.filepath)
check(rendered, f"rendered still -> {scene.render.filepath}")

simulate_until(10.2)
check(obj("DP_Duckling_nested-f") is not None, "nested (depth 2) duckling exists")
_nf, _gp = RT.motion.states.get(("cc-fable-1", "nested-f")), RT.motion.states.get(("cc-fable-1", "gp-b"))
check(_nf is not None and _gp is not None and math.hypot(_nf.x - _gp.x, _nf.y - _gp.y) < 1.3,
      "nested duckling orbits its parent duckling, not the session duck")
check(any(c.obj.data.body == "tests FAIL" for c in RT.fx.active_chips), "codex's failed npm test shows a red 'tests FAIL' chip")
check(RT.sky.rain_target > 0.0, "a failing test seeds the error rain")
simulate_until(14.0)
check(obj("DP_Duckling_explore-a") is None, "finished duckling merged back and was removed")
check(obj("DP_Tether_explore-a") is None, "its tether is gone")
check(obj("DP_Duckling_gp-b") is not None, "second duckling still working")
simulate_until(20.0)
check(obj("DP_Duckling_gp-b") is None, "second duckling finished")
check(RT.fleet.sessions["codex-3"].error_message == "rate limited, retrying", "codex error recorded")

simulate_until(31.0)
_op = RT.fleet.sessions["cc-opus-2"]
check(_op.queued == 0 and obj("DP_Duck_cc-opus-2_tray0").hide_viewport, "queued prompt was consumed by the prompt at 30 s")
_z_before = obj("DP_Duck_cc-opus-2").location.z
simulate_until(32.6)
check(_op.compactions == 1 and _op.context_frac < 0.2, "compaction recorded, context drops")
check(obj("DP_Duck_cc-opus-2").location.z > _z_before + 0.05, "duck pops up out of the water after compaction")
check(any(c.obj.data.body == "compacted" for c in RT.fx.active_chips), "'compacted' chip after the geyser")
simulate_until(40.0)
_cx = RT.fleet.sessions["codex-3"]
check(_cx.state == "awaiting_permission", f"codex Write unanswered in default mode is inferred blocked ({_cx.state})")
check(not obj("DP_Duck_codex-3_beacon").hide_viewport and obj("DP_Duck_codex-3_beacon").color[0] > 0.8 and obj("DP_Duck_codex-3_beacon").color[1] < 0.3,
      "blocked duck's beacon is red")
_h = obj("DP_Duck_codex-3_halo").color
check(_h[0] > 0.8 and _h[1] < 0.3 and _h[3] > 0.5, "blocked duck's halo is red")
check(obj("DP_Duckling_bg-e") is not None and RT.fleet.sessions["cc-fable-1"].state == "awaiting_user",
      "background duckling keeps working after its parent finished the turn")
check(RT.tethers[("cc-fable-1", "bg-e")].obj.data.bevel_depth < 0.01, "background tether is a thin leash")
simulate_until(48.5)
check(_cx.state == "awaiting_user" and _cx.denied_kind == "user-rejected", "denied Write leaves codex waiting for you")
check(any(c.obj.data.body == "denied" for c in RT.fx.active_chips), "'denied' chip")
simulate_until(56.0)
vs = RT.fleet.sessions.get("vscode-4")
check(vs is not None and vs.state == "ended", "vscode session ended")
check(obj("DP_Duck_vscode-4").color[3] < 1.0, "ended duck is fading")
simulate_until(75.0)
check("vscode-4" not in RT.fleet.sessions and obj("DP_Duck_vscode-4") is None, "ended duck removed after fade")

# idle reads at a glance: no lamp, no halo, the body drained of colour and see-through
_idle_at = t0 + _t
RT.fleet.sessions["cc-opus-2"].set_state("idle", _idle_at)
RT.tick(_idle_at)
RT.frame(_idle_at, dt=0.1)
_od = obj("DP_Duck_cc-opus-2")
_rgb = _od.color[:3]
check(obj("DP_Duck_cc-opus-2_halo").color[3] == 0.0 and obj("DP_Duck_cc-opus-2_beacon").hide_viewport, "idle duck has no halo and no lamp")
check(max(_rgb) - min(_rgb) < 0.2 and _od.color[3] < 0.6, f"idle duck is greyed out and see-through ({tuple(round(c, 2) for c in _od.color)})")

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "smoke.blend"))
print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILURES'} — objects in scene: {len(bpy.data.objects)}")
sys.exit(1 if failures else 0)
