"""Headless Blender smoke test: builds the pool from the demo fixture, simulates time, renders a still.

    blender -b --python tests/headless_smoke.py
"""
import math
import os
import sys
import time

import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond.adapters.stub import StubAdapter  # noqa: E402
from duck_pond.cli_version import Versions  # noqa: E402
from duck_pond.runtime import RT  # noqa: E402
from duck_pond.scene import bather as bather_mod  # noqa: E402
from duck_pond.scene import pitchers as pitchers_mod  # noqa: E402
from duck_pond.scene import plane as plane_mod  # noqa: E402
from duck_pond.scene import props as props_mod  # noqa: E402
from duck_pond.scene.pitchers import JUG_H, WALL  # noqa: E402
from duck_pond.ui import cards  # noqa: E402
from duck_pond.usage_limits import Gauge, Usage  # noqa: E402

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
# the context ring is worn over the head and must not cut across the face
_ring = obj("DP_Duck_cc-opus-2_ring")
_R, _TUBE, _BILL = 0.224, 0.045, Vector((0.36, 0.0, 0.21))
_c, _th = Vector(_ring.location), _ring.rotation_euler.y
_pts = [_c + Vector((_R * math.cos(a) * math.cos(_th), _R * math.sin(a), -_R * math.cos(a) * math.sin(_th)))
        for a in (2 * math.pi * i / 144 for i in range(144))]
_near_bill = min((p - _BILL).length for p in _pts)
check(not _ring.hide_viewport, "the context ring is always worn")
check(_near_bill > 0.15, f"the ring clears the bill by {_near_bill:.3f} (level at the neck it was 0.04)")
check(min(p.z for p in _pts) < 0.0 < max(p.z for p in _pts),
      f"it slopes from above the neck into the water (z {min(p.z for p in _pts):+.3f}..{max(p.z for p in _pts):+.3f})")
check(_th > 0.3, f"and it is tilted, not level ({math.degrees(_th):.0f} deg)")
# the bather waves when a duck has put a question to you, not when a turn merely ended
_asking = [s for s in RT.fleet.live_sessions() if s.blocked_on_you()]
check(bool(_asking) == RT.blocked_on_you,
      f"blocked_on_you tracks the fleet ({RT.blocked_on_you}, {[s.id for s in _asking]})")
_turn_only = [s for s in RT.fleet.live_sessions() if s.state == "awaiting_user" and not s.question]
check(not any(s.blocked_on_you() for s in _turn_only),
      f"a finished turn does not block you, so it does not wave ({[s.id for s in _turn_only]})")
_q = RT.fleet.sessions["cc-opus-2"]
_saved_q, _q.question = _q.question, "Which one?"
check(_q.blocked_on_you(), "a pending question counts as blocked on you")
_q.question = _saved_q
# how high her hand is, which is the thing that matters -- the euler angle it comes from
# runs the other way now that the arm starts on the deck, and a test should not care
def _hand_z():
    bpy.context.view_layer.update()   # matrix_world is stale until the depsgraph catches up
    return (obj("DP_BatherArm").matrix_world @ Vector(bather_mod.ARM_TIP)).z


# settle her arm down first: the fixture may already have her hand up
for _i in range(150):
    RT.bather.update(t0 + _t + _i / 30.0, 1 / 30.0, None, False)
_rest, _rest_x = _hand_z(), obj("DP_BatherArm").rotation_euler.x
check(_rest < 0.35, f"at rest her hand is down on the deck (z {_rest:+.3f}, deck top 0.10)")
for _i in range(150):
    RT.bather.update(t0 + _t + 5 + _i / 30.0, 1 / 30.0, None, True)
_up = _hand_z()
check(_up > _rest + 1.0,
      f"her arm comes up when someone asks you something (z {_rest:+.3f} to {_up:+.3f})")
for _i in range(200):
    RT.bather.update(t0 + _t + 10 + _i / 30.0, 1 / 30.0, None, False)
check(abs(obj("DP_BatherArm").rotation_euler.x - _rest_x) < 0.02,
      "and goes back down once you have answered")
# both hands rest on the deck, out beside her where you can see them: they used to fold in
# behind her back, which from the front left her with no arms at all
# park her out of the sunbathe first: leaning back lifts her hands off the deck, and which
# moment this lands on is otherwise down to the wall clock. The envelope is flat from
# LEAN_HOLD + 2 * LEAN_RISE (13.4 s) to LEAN_EVERY (34 s), so 20 s in is safely still.
_calm = (math.floor(t0 / bather_mod.LEAN_EVERY) + 1) * bather_mod.LEAN_EVERY + 20.0
RT.bather.update(_calm, 1 / 30.0, None, False)
bpy.context.view_layer.update()
_bx = RT.bather.body.matrix_world
_lh = _bx @ Vector((-bather_mod.HAND[0], bather_mod.HAND[1], bather_mod.HAND[2]))
_rh = obj("DP_BatherArm").matrix_world @ Vector(bather_mod.ARM_TIP)
_hip = _bx @ Vector((0.205, 0.02, 0.28))          # the edge of her hip shell
check(abs(_lh.x - _rh.x) > 2 * abs(_hip.x - _bx.translation.x),
      f"her hands are outboard of her hips ({abs(_lh.x - _rh.x):.2f} m apart)")
_palm = 0.048 * 0.70 * bather_mod.SCALE           # half the thickness of a palm
check(max(abs(_lh.z - _palm - 0.10), abs(_rh.z - _palm - 0.10)) < 0.05,
      f"and both are down on the deck (undersides {_lh.z - _palm:+.3f} and "
      f"{_rh.z - _palm:+.3f}, deck top 0.10)")
# the noodles roam the pool and push out of whatever they meet
_nd = RT.props.noodles
check(len(_nd) >= 2, f"there are noodles to collide ({len(_nd)})")
class _D:
    def __init__(self, x, y):
        self.x, self.y = x, y
_nd[0].update(x=4.0, y=4.0, heading=0.0, vx=0.0, vy=0.0, spin=0.0)
_nd[1].update(x=4.05, y=4.03, heading=1.4, vx=0.0, vy=0.0, spin=0.0)   # crossed, the usual case
for _i in range(90):
    RT.props.update(t0 + _t + _i / 30.0, 1 / 30.0, {})
_a1, _b1 = props_mod._seg(_nd[0])
_a2, _b2 = props_mod._seg(_nd[1])
_gap = props_mod._closest_between(_a1, _b1, _a2, _b2)[0]
check(_gap > 2 * props_mod.NOODLE_R - 0.02, f"two noodles laid on top of each other push apart ({_gap:.2f} m)")
_nd[0].update(x=8.0, y=4.0, heading=0.0, vx=0.0, vy=0.0, spin=0.0)
for _i in range(40):
    RT.props.update(t0 + _t + 2 + _i / 30.0, 1 / 30.0, {"d": _D(8.0, 4.0)})
_c, _ = props_mod._closest_on_seg(*props_mod._seg(_nd[0]), (8.0, 4.0))
_dd = math.dist(_c, (8.0, 4.0))
check(_dd > props_mod.NOODLE_R + props_mod.DUCK_R - 0.02, f"a noodle dropped on a duck is pushed off it ({_dd:.2f} m)")
for _n in _nd:
    for _e in props_mod._seg(_n):
        check(0 <= _e[0] <= 16.0 and 0 <= _e[1] <= 8.0, f"a noodle end stays in the pool ({_e[0]:.1f},{_e[1]:.1f})")
# the sangria jugs: filled from the usage limits, which a test must never go and fetch
check(not RT.limits._thread, "a headless run never starts the usage-limit reader")
RT.limits.set_snapshot(Usage(session=Gauge(0.25, "8:30pm"), week=Gauge(1.0, "Sep 26, 4pm"), ok=True))
RT.pitchers.update(RT.limits.snapshot())
_inner = JUG_H - 2 * WALL
_fs = obj("DP_JugFill_session").scale.z
_fw = obj("DP_JugFill_week").scale.z
check(abs(_fs - _inner * 0.25) < 1e-6 and abs(_fw - _inner) < 1e-6,
      f"each jug is poured to its window ({_fs:.3f} and {_fw:.3f} of {_inner:.3f})")
_week_label = obj("DP_JugSub_week").data.body
check(_week_label == "Sep 26, 4pm", f"the reset time is written under the jug ({_week_label!r})")
RT.pitchers.update(Usage(ok=False, error="no CLI"))
check(obj("DP_JugSub_session").data.body == "no reading", "a failed read says so rather than showing zero")
# the mark above the jugs reaches its arms out and draws them back, rather than turning
RT.pitchers.pulse(0.0)
_arm0 = [obj(f"DP_UsageRay{i}").scale.x for i in range(3)]
RT.pitchers.pulse(1.0 / (4 * pitchers_mod.LOGO_PULSE_HZ))     # a quarter of the way round
_arm1 = [obj(f"DP_UsageRay{i}").scale.x for i in range(3)]
check(any(abs(a - b) > 0.05 for a, b in zip(_arm0, _arm1)),
      f"the burst's arms change length over time ({_arm0[0]:.2f} -> {_arm1[0]:.2f})")
check(len({round(s, 3) for s in _arm0}) > 1, "and they are not all the same length at once")
check(all(pitchers_mod.LOGO_MIN - 1e-6 <= s <= pitchers_mod.LOGO_MAX + 1e-6 for s in _arm0),
      "no arm reaches past the disc behind it")
check(abs(obj("DP_UsageRay0").rotation_euler.z) < 1e-9, "and nothing spins any more")
# the banner plane: it tows the two version rows across the sky, and the plate it writes
# them on is sized to the text rather than hoping the text fits
RT.plane.update(0.0, 1 / 30.0, Versions())      # nothing known yet
check(obj("DP_PlaneBannerPlate").hide_render, "no version reading, no banner")
_mid = (plane_mod.X1 - plane_mod.X0) / plane_mod.SPEED * 0.5
RT.plane.update(_mid, 1 / 30.0, Versions(yours="2.1.9", latest="2.1.278"))
check(not obj("DP_PlaneBannerPlate").hide_render, "with a reading, it flies")
_top, _bot = obj("DP_PlaneRowTop").data.body, obj("DP_PlaneRowBottom").data.body
check(_top == "LATEST  v2.1.278", f"the published version is the top row ({_top!r})")
check(_bot.startswith("YOURS  v2.1.9"), f"and yours is underneath ({_bot!r})")
check("UPDATE" in _bot, "2.1.9 is behind 2.1.278, and the banner says so")
bpy.context.view_layer.update()
_plate_w = obj("DP_PlaneBannerPlate").dimensions.x
_text_w = max(obj("DP_PlaneRowTop").dimensions.x, obj("DP_PlaneRowBottom").dimensions.x)
check(_plate_w > _text_w, f"the banner is wider than what is written on it ({_plate_w:.2f} vs {_text_w:.2f})")
check(_plate_w - _text_w < 2.0, f"but not by a mile ({_plate_w - _text_w:.2f})")
_px = obj("DP_PlaneRoot").location.x
check(plane_mod.X0 < _px < plane_mod.X1, f"and it is somewhere over the pool ({_px:.1f})")
check(obj("DP_PlaneRoot").location.y > 16.5, "beyond the lawn's edge, so nothing hides it")
check(len(RT.ripples.active_rings) > 0, "water has active ripple rings")
check(obj("DP_Duck_cc-opus-2").location.z < -0.08, "opus at 91 % of its 1M context sits low in the water")
check(obj("DP_Duck_vscode-4").rotation_euler.y > 0.1, "tool-running duck dips its head")
# --- reimagined: glance-level state, the deck dashboard, the world
check(not obj("DP_Duck_cc-opus-2_beacon").hide_viewport and obj("DP_Duck_cc-opus-2_beacon").color[0] > 0.8 and obj("DP_Duck_cc-opus-2_beacon").color[2] < 0.2,
      "waiting duck's lamp is yellow")
check(RT.fleet.sessions["cc-fable-1"].effort == "max", "effort is read from the fixture")
# the board is a screen overlay now, so it is asserted through its model, not its objects
check(obj("DP_Board") is None and obj("DP_Board_L1") is None, "no scoreboard geometry is left in the scene")
check(RT.fleet.ledger.ready, "the ledger backfill finished")
_b = cards.board_model(RT.fleet, t0 + _t, RT.board_range)
check(any("WORKING" in t for t, _s in _b.status), f"board reads: {_b.status}")
check([n for n, _sel in _b.tabs] == ["min", "hour", "day", "week", "month"], "board has the five range tabs")
check([n for n, sel in _b.tabs if sel] == ["hour"], f"the picked range is the selected tab ({_b.tabs})")
check(len(_b.bars) == 24 and _b.peak > 0, f"hour range: 24 bars with a live one (peak {_b.peak:.2f})")
check(_b.range_line.startswith("last 24 h") and "≈$" in _b.range_line, f"range line: {_b.range_line}")
check("≈$" in _b.month_line, f"month line: {_b.month_line}")
RT.set_board_range("min")
_b = cards.board_model(RT.fleet, t0 + _t, RT.board_range)
check(len(_b.bars) == 60 and _b.range_line.startswith("last 60 min"), f"min range: 60 bars ({_b.range_line})")
check([n for n, sel in _b.tabs if sel] == ["min"], "switching the range moves the selected tab")
RT.set_board_range("hour")
check(any(not o.hide_viewport for o in RT.fx.chips), "a tool chip is on screen (bash / edit / read…)")
check(RT.fx.active_orbs or any(not o.hide_viewport for o in RT.fx.orbs), "thought bubbles / drops / risers are pooled and visible")
check(len(RT.signs.objects) == 3, f"every lane has a sign plate ({len(RT.signs.objects)})")
RT.signs.last_update = 0.0
RT.signs.update(RT.lanes, RT.fleet, t0 + _t, RT.redact)
_portal = [(k, d) for k, d in RT.signs.objects.items() if "storefront" in k]
_usd = RT.fleet.ledger.cwd_month_usd(_portal[0][0], t0 + _t) if _portal else 0.0
check(bool(_portal) and _usd > 0 and f"${_usd:.0f}" in _portal[0][1]["sub"].data.body,
      f"storefront lane sign shows its month spend ({_portal[0][1]['sub'].data.body if _portal else None})")
check(RT.sky.chop >= 0.0 and RT.sky.night < 0.5 or RT.sky.clock_override is None, "sky is in a valid day state")

# lane re-layout must not make ducks shake: headings may flip at most a couple of times
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
