"""Headless camera test: the camera moves only when you focus a duck, and never snaps.

    blender -b --python tests/headless_director.py

Drives the runtime at 30 fps while sessions appear, get blocked, ask questions, spawn
ducklings and finish — everything that used to make the camera go hunting — and asserts:
  * with nothing focused the camera never leaves the overview, however loud the pool gets,
  * focusing a duck frames it, and dropping the focus returns to the overview,
  * camera position 2nd difference stays under a bound (no cuts, no overshoot spikes),
  * the camera's forward vector never turns more than MAX_CAM_TURN per frame,
  * the sky's chop, night and rain values are continuous (no jumps > 0.05 per frame).
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
from duck_pond.runtime import RT  # noqa: E402
from duck_pond.scene import pool as P  # noqa: E402

duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

RT.start([], gui=False)
RT.director.enabled = True
RT.sky.clock_override = 20.2  # dusk: the night blend is moving during the test
T0 = time.time()
RT.last_frame_t = T0
DT = 1.0 / 30.0
MAX_CAM_ACC = 0.03          # m per frame^2: omega^2 * 16 m * dt^2 for the 1.3 rad/s spring; a cut is metres
MAX_CAM_TURN = math.radians(2.5)  # per frame
failures = []
t = T0


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL", msg)
    else:
        print("ok  ", msg)


def ev(**kw):
    kw.setdefault("at", t)
    RT.fleet.apply(kw)


cam = P.camera()
pos_hist, fwd_hist, targets = [], [], set()
sky_hist = []
OVERVIEW = Vector(P.CAM_OVERVIEW[0])


def run(frames):
    global t
    for i in range(frames):
        t += DT
        if i % 8 == 0:
            RT.tick(t)
        RT.frame(t, dt=DT)
        pos_hist.append(Vector(cam.location))
        fwd_hist.append(cam.rotation_euler.to_matrix() @ Vector((0.0, 0.0, -1.0)))  # matrix_world is stale headless
        targets.add(RT.director.target)
        sky_hist.append((RT.sky.chop, RT.sky.night, RT.sky.rain))


# a fleet that keeps giving the director reasons to move
for i, (sid, cwd) in enumerate((("a", "C:/p/one"), ("b", "C:/p/two"), ("c", "C:/p/one"))):
    ev(type="SessionSeen", session_id=sid, harness="claude_code", model="claude-opus-5", cwd=cwd, branch="main")
    ev(type="StateChanged", session_id=sid, state="generating")
    ev(type="PermissionMode", session_id=sid, mode="default")
run(60)
ev(type="Prompt", session_id="a", text="do the thing")
ev(type="Usage", session_id="a", tokens_in=1000, tokens_out=4000, context_used=50000)
run(90)
ev(type="ToolCall", session_id="b", name="AskUserQuestion", tool_id="q", summary="Which one?", done=False)
run(120)
ev(type="ToolCall", session_id="c", name="Write", tool_id="w", summary="x.py", done=False)
run(30)
ev(type="SubAgentSeen", session_id="a", agent_id="s1", agent_type="Explore", description="look", model="claude-haiku-4-5")
ev(type="ToolCall", session_id="a", name="Agent", tool_id="ag", summary="look", done=False)
run(420)  # 14 s: past the 12 s permission_after window
# c has been in tool_running with a Write for > 12 s in default permission mode: blocked (inferred)
check(RT.fleet.sessions["c"].state == "awaiting_permission", "long unanswered Write in default mode reads as awaiting_permission")
ev(type="ToolCall", session_id="c", name="Write", tool_id="w", done=True, ok=False, denied="user-rejected")
run(120)
ev(type="Error", session_id="b", message="boom")
ev(type="Error", session_id="a", message="boom")
run(150)
ev(type="StateChanged", session_id="a", state="awaiting_user")
ev(type="Compaction", session_id="a", pre_tokens=180000, post_tokens=20000)
run(400)
check(RT.fleet.sessions["c"].state == "awaiting_user", "a denied tool leaves the duck waiting for you")

# --- unattended: every one of those events happened with nothing focused
drift = max((p - OVERVIEW).length for p in pos_hist)
check(drift < 1e-6, f"camera never left the overview unattended (max drift {drift:.6f} m)")
check(targets == {None}, f"the camera picked no target of its own: {sorted(t for t in targets if t)}")
unattended_frames = len(pos_hist)

# --- focus a duck: now, and only now, the camera goes in
RT.pinned = ("a", "")
run(150)
framed = pos_hist[-1]
d = RT.ducks[("a", "")]
check((framed - OVERVIEW).length > 1.0, f"focusing a duck moves the camera in ({(framed - OVERVIEW).length:.2f} m)")
check(RT.director.target == ("a", ""), f"the focused duck is the target ({RT.director.target})")
check((framed - Vector(d.obj.location)).length < 8.0, "the camera ends up near the duck it framed")

# --- drop the focus: back out to the overview
RT.pinned = None
run(300)
check((pos_hist[-1] - OVERVIEW).length < 0.35,
      f"dropping the focus returns to the overview ({(pos_hist[-1] - OVERVIEW).length:.2f} m out)")
check(RT.director.target is None, "no target once the focus is dropped")
check(len(pos_hist) > unattended_frames, "the focus phases actually ran")

# --- camera continuity
acc = 0.0
for i in range(1, len(pos_hist) - 1):
    a = (pos_hist[i + 1] - pos_hist[i]) - (pos_hist[i] - pos_hist[i - 1])
    acc = max(acc, a.length)
check(acc <= MAX_CAM_ACC, f"camera position 2nd difference {acc:.4f} <= {MAX_CAM_ACC}")
turn = 0.0
for a, b in zip(fwd_hist, fwd_hist[1:]):
    turn = max(turn, a.angle(b, 0.0))
check(turn <= MAX_CAM_TURN, f"camera max turn per frame {math.degrees(turn):.2f} deg <= {math.degrees(MAX_CAM_TURN):.2f}")
# --- world continuity
jump = 0.0
for a, b in zip(sky_hist, sky_hist[1:]):
    jump = max(jump, max(abs(x - y) for x, y in zip(a, b)))
check(jump <= 0.05, f"sky chop/night/rain move continuously (max step {jump:.4f})")
check(RT.sky.rain > 0.05, f"two errors in two minutes bring rain ({RT.sky.rain:.2f})")
check(RT.sky.night > 0.0, f"20:12 is dusk ({RT.sky.night:.2f} night)")

print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILURES'}")
sys.exit(1 if failures else 0)
