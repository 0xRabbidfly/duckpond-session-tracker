"""DuckPond.exe — one double-click to the pool.

Finds Blender 5.x, unpacks the add-on (bundled inside the exe) to %LOCALAPPDATA%\\DuckPond,
and starts Blender in app mode on your live Claude Code sessions. Blender is the app; this is
just the key that starts it.

    DuckPond.exe                 the pool in a maximised window, live sessions
    DuckPond.exe --fullscreen    borderless fullscreen instead (Alt+F11 toggles back)
    DuckPond.exe --kiosk --sound second-monitor mode: auto camera, tags on every duck, cues
    DuckPond.exe --dev           normal Blender UI + sidebar (no fullscreen)
    DuckPond.exe --stub          demo fixture instead of live sessions (--both for both)
    DuckPond.exe --blender "C:\\path\\to\\blender.exe"

Also runs unfrozen from the repo:  python launcher\\duckpond_launcher.py --stub
"""
from __future__ import annotations

import ctypes
import glob
import os
import shutil
import subprocess
import sys
import winreg

VERSION = "0.2.0"
DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"


def _msg(text: str, title: str = "Duck Pond") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)


def find_blender(explicit: str | None) -> str | None:
    """Explicit flag, then the known install, then the newest 'Blender Foundation' install,
    then PATH, then the registry's .blend association."""
    if explicit and os.path.isfile(explicit):
        return explicit
    env = os.environ.get("DUCKPOND_BLENDER")
    if env and os.path.isfile(env):
        return env
    if os.path.isfile(DEFAULT_BLENDER):
        return DEFAULT_BLENDER
    candidates = []
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")):
        if base:
            candidates += glob.glob(os.path.join(base, "Blender Foundation", "Blender *", "blender.exe"))
    steam = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam", "steamapps", "common", "Blender", "blender.exe")
    if os.path.isfile(steam):
        candidates.append(steam)
    if candidates:
        # newest version number wins
        def ver(p):
            import re
            m = re.search(r"Blender (\d+)\.(\d+)", p)
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        candidates.sort(key=ver, reverse=True)
        return candidates[0]
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"blendfile\shell\open\command") as k:
            cmd, _ = winreg.QueryValueEx(k, "")
        exe = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
        if os.path.isfile(exe):
            return exe
    except OSError:
        pass
    return None


def app_root() -> str:
    """Where duck_pond/, dev/launch.py and fixtures/ live for this run."""
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    # The onefile temp dir disappears when this process exits, but Blender keeps running and
    # imports lazily (sound, fixtures), so copy the app to a stable, version-stamped folder.
    base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DuckPond")
    dest = os.path.join(base, f"app-{VERSION}")
    stamp = os.path.join(dest, ".complete")
    if not os.path.isfile(stamp):
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest, exist_ok=True)
        for name in ("duck_pond", "dev", "fixtures"):
            src = os.path.join(bundle, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dest, name), dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        open(stamp, "w").close()
        # prune older versions
        for old in glob.glob(os.path.join(base, "app-*")):
            if os.path.abspath(old) != os.path.abspath(dest):
                shutil.rmtree(old, ignore_errors=True)
    return dest


def main() -> int:
    args = list(sys.argv[1:])
    explicit = None
    if "--blender" in args:
        i = args.index("--blender")
        explicit = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    blender = find_blender(explicit)
    if not blender:
        _msg("Duck Pond needs Blender 5.x.\n\nInstall it from blender.org (or: winget install BlenderFoundation.Blender), "
             "or start with\n  DuckPond.exe --blender \"C:\\path\\to\\blender.exe\"")
        return 2
    root = app_root()
    launch = os.path.join(root, "dev", "launch.py")
    if not os.path.isfile(launch):
        _msg(f"Duck Pond is missing its files:\n{launch}")
        return 3
    dev = "--dev" in args
    args = [a for a in args if a != "--dev"]
    if not dev and "--app" not in args and "--kiosk" not in args:
        args.insert(0, "--app")
    # a normal, maximised OS window by default (movable, minimisable); --fullscreen goes borderless
    win = [] if "--fullscreen" in args or dev else ["--window-maximized"]
    cmd = [blender, *win, "--python", launch, "--", *args]
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DuckPond")
    os.makedirs(log_dir, exist_ok=True)
    log = open(os.path.join(log_dir, "last-run.log"), "w", encoding="utf-8", errors="replace")
    flags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags = subprocess.DETACHED_PROCESS | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # Unbuffered: a detached Blender writing to a file otherwise flushes only when it exits, so
    # the log of a run that is still going -- the one you actually want to read -- stays empty.
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    try:
        subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=root, creationflags=flags,
                         close_fds=True, env=env)
    except OSError as exc:
        _msg(f"Could not start Blender:\n{blender}\n\n{exc}")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
