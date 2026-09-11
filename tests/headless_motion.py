"""Headless motion smoothness test: no duck may turn or move discontinuously, ever.

    blender -b --python tests/headless_motion.py

Drives Motion.step at 30 fps through the situations that used to produce jitter (a duck
grazing a lane rope, a duck heading straight at a rope in a narrow lane, a pool-wall bounce,
lanes re-laid out under swimming and waiting ducks, a duckling flipping state) and asserts,
for every frame of every duck:
  * the heading changes by at most MAX_YAW * dt (no single-frame snaps or flips),
  * the heading never saws (no sign reversal of the turn rate with both legs above 1 deg),
  * the position never jumps (2nd difference below what MAX_YAW turning at top speed allows),
  * displacement matches commanded speed (no sliding without paddling),
  * the duck ends up inside its lane.
"""
import math
import os
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond.runtime import RT  # noqa: E402
from duck_pond.sim import motion as MO  # noqa: E402

duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

RT.start([], gui=False)
T0 = time.time()
RT.last_frame_t = T0
DT = 1.0 / 30.0
MAX_YAW = getattr(MO, "MAX_YAW", math.radians(150))  # rad/s; the fix defines it
MAX_TURN_PER_FRAME = MAX_YAW * DT * 1.05 + 1e-6
TOP_SPEED = max(MO.SPEED_GENERATING, getattr(MO, "SPEED_RELOCATE", 0.0))
# worst-case 2nd difference of position: speed change (accel cap) + direction change at cap
MAX_ACCEL_PER_FRAME = TOP_SPEED * DT * (MAX_YAW * DT) + 0.45 * 2.0 * DT * DT + 1e-4

failures = []
t = T0


def check(cond, msg):
    if not cond:
        failures.append(msg)
        print("FAIL", msg)
    else:
        print("ok  ", msg)


def seen(sid, cwd, at, state="generating"):
    RT.fleet.apply({"type": "SessionSeen", "session_id": sid, "harness": "claude_code",
                    "model": "claude-opus-5", "cwd": cwd, "branch": "main", "at": at})
    RT.fleet.apply({"type": "StateChanged", "session_id": sid, "state": state, "at": at})


def run(frames, label):
    """Advance the sim, recording every session duck; returns {sid: [(heading, x, y, speed)]}."""
    global t
    hist = {}
    for i in range(frames):
        t += DT
        if i % 8 == 0:
            RT.tick(t)
        RT.frame(t, dt=DT)
        for k, st in RT.motion.states.items():
            if not k[1]:
                hist.setdefault(k[0], []).append((st.heading, st.x, st.y, st.speed))
    assert_smooth(hist, label)
    return hist


def assert_smooth(hist, label):
    for sid, rows in hist.items():
        h = [r[0] for r in rows]
        d = [((b - a + math.pi) % (2 * math.pi)) - math.pi for a, b in zip(h, h[1:])]
        worst = max((abs(x) for x in d), default=0.0)
        check(worst <= MAX_TURN_PER_FRAME,
              f"{label}: {sid} max turn/frame {math.degrees(worst):.1f} deg <= {math.degrees(MAX_TURN_PER_FRAME):.1f}")
        saw = sum(1 for a, b in zip(d, d[1:]) if a * b < 0 and abs(a) > math.radians(1) and abs(b) > math.radians(1))
        check(saw == 0, f"{label}: {sid} heading saw-tooth reversals = {saw}")
        xs = [r[1] for r in rows]
        ys = [r[2] for r in rows]
        acc = 0.0
        for i in range(1, len(rows) - 1):
            ax = (xs[i + 1] - xs[i]) - (xs[i] - xs[i - 1])
            ay = (ys[i + 1] - ys[i]) - (ys[i] - ys[i - 1])
            acc = max(acc, math.hypot(ax, ay))
        check(acc <= MAX_ACCEL_PER_FRAME, f"{label}: {sid} max position 2nd-diff {acc:.4f} <= {MAX_ACCEL_PER_FRAME:.4f}")
        slide, worst_i = 0.0, -1
        for i, ((h0, x0, y0, s0), (h1, x1, y1, s1)) in enumerate(zip(rows, rows[1:])):
            v = abs(math.hypot(x1 - x0, y1 - y0) / DT - s1)
            if v > slide:
                slide, worst_i = v, i + 1
        check(slide <= 0.08, f"{label}: {sid} |displacement/dt - speed| max {slide:.3f} <= 0.08 (no sliding)")
        if slide > 0.08:
            h1, x1, y1, s1 = rows[worst_i]
            lane_now = RT.lanes.y_range(RT.fleet.sessions[sid].cwd) if sid in RT.fleet.sessions else None
            print(f"      worst at frame {worst_i}: x={x1:.3f} y={y1:.3f} heading={math.degrees(h1):.1f} speed={s1:.2f} lane={lane_now}")


def place(sid, x, y, heading, speed):
    st = RT.motion.states[(sid, "")]
    st.x, st.y, st.heading, st.speed = x, y, heading, speed
    return st


def inside(sid):
    st = RT.motion.states[(sid, "")]
    y0, y1 = RT.lanes.y_range(RT.fleet.sessions[sid].cwd)
    return y0 - 0.02 <= st.y <= y1 + 0.02


# ---------------------------------------------------------------- 1. grazing the rope
seen("graze", "C:/p/graze", t)
RT.tick(t)
RT.frame(t, dt=DT)
lane = RT.lanes.y_range("C:/p/graze")
place("graze", 5.0, lane[1] - 0.01, math.radians(10), MO.SPEED_GENERATING)
run(450, "grazing rope 15 s")
check(inside("graze"), "grazing duck stays in its lane")

# ---------------------------------------------------------------- 2. narrow lanes, head-on at the rope
seen("n2", "C:/p/two", t)
seen("n3", "C:/p/three", t)
RT.tick(t)
RT.frame(t, dt=DT)
lane = RT.lanes.y_range("C:/p/graze")
check(lane[1] - lane[0] < 1.6, f"three lanes make a narrow lane ({lane[1] - lane[0]:.2f} wide)")
place("graze", 6.0, (lane[0] + lane[1]) / 2, math.radians(90), MO.SPEED_GENERATING)
place("n2", 6.0, sum(RT.lanes.y_range("C:/p/two")) / 2, math.radians(-90), MO.SPEED_GENERATING)
run(450, "head-on at rope, narrow lane, 15 s")
check(inside("graze") and inside("n2"), "head-on ducks stay in their lanes")

# ---------------------------------------------------------------- 3. pool wall, head-on
place("n3", 14.0, sum(RT.lanes.y_range("C:/p/three")) / 2, 0.0, MO.SPEED_GENERATING)
run(300, "pool wall head-on 10 s")

# ---------------------------------------------------------------- 4. lanes re-laid out under a swimmer and a waiter
RT.fleet.apply({"type": "StateChanged", "session_id": "n3", "state": "awaiting_user", "at": t})
run(60, "settle before relayout")
seen("n4", "C:/p/four", t)  # fourth cwd -> every lane moves (the live pond's usual layout)
hist = run(600, "lane relayout 20 s")
for sid in ("graze", "n2", "n3"):
    check(inside(sid), f"{sid} is back inside its new lane 20 s after the relayout")
lane = RT.lanes.y_range("C:/p/graze")
check(lane[1] - lane[0] > 1.0, f"four lanes still leave room to swim ({lane[1] - lane[0]:.2f} wide)")

# ---------------------------------------------------------------- 5. duckling state flip
RT.fleet.apply({"type": "SubAgentSeen", "session_id": "graze", "agent_id": "d1", "agent_type": "general-purpose",
                "description": "test duckling", "model": "claude-sonnet-5", "at": t})
RT.fleet.apply({"type": "StateChanged", "session_id": "graze", "agent_id": "d1", "state": "generating", "at": t})
RT.tick(t)
sub_hist = []
for i in range(240):
    t += DT
    if i == 90:
        RT.fleet.apply({"type": "StateChanged", "session_id": "graze", "agent_id": "d1", "state": "tool_running", "at": t})
    if i == 180:
        RT.fleet.apply({"type": "StateChanged", "session_id": "graze", "agent_id": "d1", "state": "generating", "at": t})
    if i % 8 == 0:
        RT.tick(t)
    RT.frame(t, dt=DT)
    st = RT.motion.states.get(("graze", "d1"))
    if st:
        sub_hist.append((st.heading, st.x, st.y, st.speed))
check(len(sub_hist) > 200, "duckling exists")
h = [r[0] for r in sub_hist]
d = [((b - a + math.pi) % (2 * math.pi)) - math.pi for a, b in zip(h, h[1:])]
worst = max((abs(x) for x in d), default=0.0)
check(worst <= MAX_TURN_PER_FRAME, f"duckling max turn/frame {math.degrees(worst):.1f} deg <= {math.degrees(MAX_TURN_PER_FRAME):.1f}")

print(f"\n{'ALL PASS' if not failures else str(len(failures)) + ' FAILURES'}")
sys.exit(1 if failures else 0)
