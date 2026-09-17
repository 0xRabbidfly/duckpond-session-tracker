"""The watchdog revives the moving parts: playback heartbeat, data timer, frame handler, worker.

    blender -b --python tests/headless_watchdog.py

Regression for the silent freeze of 2026-09-16: animation playback stopped (a laptop waking from
Modern Standby), so `frame_change_post` never fired again. The data timer kept running and the
sound cues kept playing, but the pond sat on a stale frame for 26 minutes -- no new ducks, no
moving numbers, no error anywhere. Nothing noticed, because a frozen pond looks like an empty one.
"""
import os
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import duck_pond  # noqa: E402
from duck_pond import runtime  # noqa: E402
from duck_pond.adapters.stub import StubAdapter  # noqa: E402
from duck_pond.runtime import RT, _frame, _timer, _watchdog  # noqa: E402

failures = []


def check(label, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
    if not cond:
        failures.append(label)


duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

stub = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
RT.threaded = False
RT.start([stub], gui=True)  # gui=True in background: registers the timers without a window

print("after start")
check("data timer registered", bpy.app.timers.is_registered(_timer))
check("watchdog registered", bpy.app.timers.is_registered(_watchdog))
check("frame handler attached", _frame in bpy.app.handlers.frame_change_post)

# The one-shot bootstrap timer never runs in a scripted test, so playback is still stopped here
# and the first watchdog call is the one that starts it -- which is the whole point of the thing.
_watchdog()
check("the watchdog starts playback nobody else started", RT.revivals == 1)
base = RT.revivals

print("watchdog is a no-op while everything is alive")
_watchdog()
check("no further revivals", RT.revivals == base)
check("timer still registered once", bpy.app.timers.is_registered(_timer))

print("kill the data timer -> watchdog brings it back")
bpy.app.timers.unregister(_timer)
check("timer really gone", not bpy.app.timers.is_registered(_timer))
_watchdog()
check("timer revived", bpy.app.timers.is_registered(_timer))
check("revival counted", RT.revivals == base + 1)

print("detach the frame handler -> watchdog re-attaches it")
bpy.app.handlers.frame_change_post.remove(_frame)
_watchdog()
check("handler revived", _frame in bpy.app.handlers.frame_change_post)
check("handler attached exactly once", bpy.app.handlers.frame_change_post.count(_frame) == 1)
check("second revival counted", RT.revivals == base + 2)

print("stopping playback is noticed and undone")
for _w, screen, _a, _r in runtime._viewports():
    if screen.is_animation_playing:
        with bpy.context.temp_override(window=_w, screen=screen, area=_a, region=_r):
            bpy.ops.screen.animation_cancel()
check("playback really stopped", not any(s.is_animation_playing for _w, s, _a, _r in runtime._viewports()))
_watchdog()
check("playback restarted", any(s.is_animation_playing for _w, s, _a, _r in runtime._viewports()))
check("third revival counted", RT.revivals == base + 3)

print("a dead worker thread is restarted")
RT.threaded = True
RT._worker = None
_watchdog()
check("worker running", RT._worker is not None and RT._worker.is_alive())
check("fourth revival counted", RT.revivals == base + 4)
RT.threaded = False
RT._stop_worker()

print("a stalled scene is detected from the frame clock alone")
RT.last_frame_t = time.time() - (runtime.STALL_AFTER_S + 5.0)
before = RT.revivals
_watchdog()
check("no window, so nothing to revive and no false count", RT.revivals == before)
RT.frame()
check("frame() advances the frame counter", RT.frames > 0)
check("frame() refreshes the stall clock", time.time() - RT.last_frame_t < 1.0)

print("the watchdog survives a broken viewport scan")
runtime._viewports = lambda: (_ for _ in ()).throw(RuntimeError("no context"))
check("returns its interval instead of dying", _watchdog() == runtime.WATCHDOG_S)
check("the failure is recorded", "no context" in RT.last_error)

print("stop() takes the watchdog down with everything else")
RT.stop()
check("watchdog unregistered", not bpy.app.timers.is_registered(_watchdog))
check("data timer unregistered", not bpy.app.timers.is_registered(_timer))
check("frame handler detached", _frame not in bpy.app.handlers.frame_change_post)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): " + "; ".join(failures))
    sys.exit(1)
print("watchdog: all checks passed")
