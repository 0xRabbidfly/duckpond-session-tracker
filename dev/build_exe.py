"""Build dist/DuckPond.exe with PyInstaller (one file, no console, duck icon).

    python dev/build_exe.py

Bundles duck_pond/, dev/launch.py and fixtures/ inside the exe; the launcher unpacks them
to %LOCALAPPDATA%/DuckPond/app-<version>/ on first run. Blender itself is not bundled
(it is a 300 MB install the launcher locates). The icon is drawn from a showcase render if
one exists, otherwise a flat rubber-duck glyph is drawn with PIL.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
ICON = os.path.join(ROOT, "launcher", "duck.ico")


def make_icon() -> str:
    from PIL import Image, ImageDraw
    src = os.path.join(ROOT, "launcher", "duck_icon.png")  # from: blender -b --python dev/render_icon.py
    img = None
    if os.path.isfile(src):
        im = Image.open(src).convert("RGBA")
        bbox = im.getbbox()
        if bbox:
            im = im.crop(bbox)
        side = max(im.size) + 24
        img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        img.paste(im, ((side - im.size[0]) // 2, (side - im.size[1]) // 2), im)
        return _save_icon(img)
    if img is None:
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((20, 110, 200, 230), fill=(217, 119, 87, 255))     # body
        d.ellipse((120, 40, 220, 140), fill=(217, 119, 87, 255))     # head
        d.polygon([(215, 95), (252, 105), (215, 118)], fill=(242, 140, 40, 255))  # bill
        d.ellipse((178, 70, 192, 84), fill=(17, 17, 17, 255))        # eye
    return _save_icon(img)


def _save_icon(img) -> str:
    img = img.resize((256, 256))
    os.makedirs(os.path.dirname(ICON), exist_ok=True)
    img.save(ICON, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    return ICON


def main() -> int:
    icon = make_icon()
    for d in (DIST, BUILD):
        shutil.rmtree(d, ignore_errors=True)
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "DuckPond",
        "--icon", icon,
        "--distpath", DIST, "--workpath", BUILD, "--specpath", BUILD,
        "--add-data", os.path.join(ROOT, "duck_pond") + sep + "duck_pond",
        "--add-data", os.path.join(ROOT, "dev", "launch.py") + sep + "dev",
        "--add-data", os.path.join(ROOT, "fixtures") + sep + "fixtures",
        "--exclude-module", "bpy",
        os.path.join(ROOT, "launcher", "duckpond_launcher.py"),
    ]
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        return r.returncode
    exe = os.path.join(DIST, "DuckPond.exe")
    print(f"built {exe} ({os.path.getsize(exe) / 1e6:.1f} MB)")
    if "--launch" in sys.argv:
        ship_and_launch(exe)
    return 0


def ship_and_launch(exe: str) -> None:
    """Refresh every copy of the exe, close a running Duck Pond, start it in kiosk mode with sound.

    Standing request: a rebuilt DuckPond.exe always comes back up as `--kiosk --sound`."""
    local = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    targets = [os.path.join(ROOT, "DuckPond.exe"), os.path.join(local, "Microsoft", "WindowsApps", "DuckPond.exe")]
    for t in targets:
        if os.path.isdir(os.path.dirname(t)):
            shutil.copy2(exe, t)
            print("copied ->", t)
    # force the launcher to re-unpack the bundled add-on
    import glob
    for d in glob.glob(os.path.join(local, "DuckPond", "app-*")):
        shutil.rmtree(d, ignore_errors=True)
    # close only Blender processes that are running Duck Pond (their command line names launch.py)
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='blender.exe'\" | "
          "Where-Object { $_.CommandLine -like '*launch.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    launcher = targets[1] if os.path.isfile(targets[1]) else exe
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([launcher, "--kiosk", "--sound"], creationflags=flags, close_fds=True)
    print("launched:", launcher, "--kiosk --sound")


if __name__ == "__main__":
    sys.exit(main())
