"""Render stills and a short clip of the demo fixture into out/ (headless).

    blender -b --python dev/render_showcase.py            # stills + clip
    blender -b --python dev/render_showcase.py -- --no-clip

Stills: busy fan-out (t≈9.5 s), compaction geyser (t≈32.4 s), blocked duck close-up (t≈40 s),
night lido (t≈41 s, clock forced to 22:30). Clip: 6 s from t=4 s at 24 fps, H.264.
"""
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
from duck_pond.scene import plane as plane_mod  # noqa: E402
from duck_pond.scene import pool as P  # noqa: E402
from duck_pond.usage_limits import Gauge, Usage  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.join(ROOT, "out")
os.makedirs(OUT, exist_ok=True)

duck_pond.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

stub = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
# Sample limits, not the real ones: a docs render must not spend tokens.
RT.limits.enabled = False
RT.limits.set_snapshot(Usage(session=Gauge(0.31, "8:30pm"),
                             week=Gauge(0.58, "Sep 26, 4pm"), ok=True))
# and a sample pair for the banner plane, so a screenshot needs no network
RT.versions.enabled = False
RT.versions.set_snapshot(Versions(yours="2.1.273", latest="2.1.278"))
RT.start([stub], gui=False)
RT.sky.clock_override = 16.5  # late afternoon for the day shots
t0 = time.time()
stub.started = t0
RT.last_frame_t = t0
_t = 0.0
STEP = 1.0 / 30.0


def simulate_until(t_rel: float):
    global _t
    i = 0
    while _t < t_rel:
        _t += STEP
        i += 1
        now = t0 + _t
        if i % 8 == 0:
            RT.tick(now)
        RT.frame(now, dt=STEP)
    RT.tick(t0 + _t)


def render(name: str, w=1600, h=900, samples=32):
    scene = bpy.context.scene
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = os.path.join(OUT, name)
    try:
        scene.eevee.taa_render_samples = samples
    except AttributeError:
        pass
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"[showcase] {name} in {time.time() - t:.1f}s")


def fly_the_plane(frac: float = 0.42):
    """Park the banner mid-crossing. A flypast every 150 s is otherwise pot luck, and a
    screenshot of the pool should show the thing the screenshot is meant to show."""
    RT.plane.update((plane_mod.X1 - plane_mod.X0) / plane_mod.SPEED * frac, 1 / 30.0,
                    RT.versions.snapshot())

def frame_camera_on(key, back=None):
    back = back if back is not None else Vector((-2.6, -4.4, 2.6))
    d = RT.ducks.get(key)
    cam = P.camera()
    if d is None:
        return
    t = Vector(d.obj.location)
    cam.location = t + back
    P.look_at(cam, t + Vector((0.0, 0.0, 0.25)))


# 1. the busy moment: chips, nested duckling, packets, the codex test just failed
simulate_until(9.7)
P.camera_overview()
# a day of spend for the deck mosaic, against the pool's own lanes: the fixture replays in
# under a minute, so on its own the mosaic is one bright column and twenty-three empty ones
RT.fleet.ledger.sample_history(time.time(), list(RT.lanes.keys), usd_scale=1.6)
RT.tick(t0 + _t)
fly_the_plane(0.3)
render("showcase_busy.png")

# 2. compaction geyser on the opus duck (t=32) — close in
simulate_until(32.35)
frame_camera_on(("cc-opus-2", ""), Vector((-2.2, -3.6, 2.2)))
render("showcase_compaction.png")

# 3. codex blocked on a permission (housekeeping flips it ~12 s after the Write at 27 s)
simulate_until(40.0)
frame_camera_on(("codex-3", ""), Vector((-2.4, -3.8, 2.0)))
render("showcase_blocked.png")

# 4. overview with a waiting duck, a background duckling on its long leash, mail, coins, the board
P.camera_overview()
fly_the_plane(0.42)
render("showcase_overview.png")

# 5. night lido
RT.sky.clock_override = 22.5
simulate_until(43.5)
fly_the_plane(0.55)
render("showcase_night.png")

if "--no-clip" not in ARGS:
    # 6. clip: re-run the fixture from t=4 for 6 s at 24 fps, rendered as an animation so the
    #    water shader's frame driver scrolls and the ducks paddle continuously
    RT.reset()
    stub = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
    RT.start([stub], gui=False)
    RT.sky.clock_override = 16.5
    t0 = time.time()
    stub.started = t0
    RT.last_frame_t = t0
    _t = 0.0
    simulate_until(4.0)
    P.camera_overview()
    scene = bpy.context.scene
    FPS = 24
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = FPS * 6
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    # this Blender build has no FFMPEG output: render a PNG sequence, then encode with ffmpeg if present
    scene.render.image_settings.file_format = "PNG"
    clip_dir = os.path.join(OUT, "clip")
    os.makedirs(clip_dir, exist_ok=True)
    for old in os.listdir(clip_dir):
        os.remove(os.path.join(clip_dir, old))
    scene.render.filepath = os.path.join(clip_dir, "frame_")
    try:
        scene.eevee.taa_render_samples = 12
    except AttributeError:
        pass

    def _advance(scene_, *args):
        global _t
        _t += 1.0 / FPS
        now = t0 + _t
        if scene_.frame_current % 6 == 0:
            RT.tick(now)
        RT.frame(now, dt=1.0 / FPS)

    bpy.app.handlers.frame_change_pre.append(_advance)
    t = time.time()
    bpy.ops.render.render(animation=True)
    print(f"[showcase] {scene.frame_end} frames in {time.time() - t:.1f}s -> {clip_dir}")
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        mp4 = os.path.join(OUT, "showcase_clip.mp4")
        cmd = [ffmpeg, "-y", "-framerate", str(FPS), "-i", os.path.join(clip_dir, "frame_%04d.png"),
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", mp4]
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(f"[showcase] ffmpeg exit {r.returncode} -> {mp4}" if r.returncode == 0 else f"[showcase] ffmpeg failed: {r.stderr[-400:]}")
    else:
        print("[showcase] ffmpeg not on PATH; PNG sequence left in", clip_dir)

print("[showcase] done")
