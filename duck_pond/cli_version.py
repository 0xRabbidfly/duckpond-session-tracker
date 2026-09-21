"""Which Claude Code you are running, and which one is out.

Two readings, from two places. Yours comes from `claude --version`, which prints something
like `2.1.273 (Claude Code)`. The published one comes from the npm registry over plain HTTP
rather than from `npm view`, because npm is a second install that a Blender add-on has no
business requiring, and the registry answers a one-line JSON GET perfectly well.

Neither call is cheap enough to do on a frame, and neither answer changes within an hour, so
this runs on its own thread and the banner draws whatever was last known.

Pure parsing lives in `parse_local`; everything bpy-shaped is somewhere else.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

REFRESH_S = 3 * 3600.0   # three hours: a release lands every few days, not every few minutes
RETRY_S = 600.0
TIMEOUT_S = 20.0
REGISTRY = "https://registry.npmjs.org/@anthropic-ai%2Fclaude-code/latest"
USER_AGENT = "duck-pond (+https://github.com/0xRabbidfly/duckpond-session-tracker)"

_VERSION = re.compile(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")


@dataclass
class Versions:
    yours: str = ""
    latest: str = ""

    @property
    def known(self) -> bool:
        """Worth flying a banner for. One of the two is enough to be worth saying."""
        return bool(self.yours or self.latest)

    @property
    def behind(self) -> bool:
        return bool(self.yours and self.latest and _key(self.yours) < _key(self.latest))


def _key(v: str) -> tuple:
    """Compare releases numerically, so 2.1.9 sorts below 2.1.10 as it should. A pre-release
    suffix sorts below the plain release of the same numbers, as semver says."""
    core, _, pre = v.partition("-")
    nums = tuple(int(p) if p.isdigit() else 0 for p in core.split("."))
    return nums, (0, pre) if pre else (1, "")


def parse_local(text: str) -> str:
    """The version out of `claude --version` output. Pure."""
    m = _VERSION.search(text or "")
    return m.group(1) if m else ""


def parse_latest(payload: str) -> str:
    """The version out of a registry document. Pure."""
    try:
        v = json.loads(payload).get("version")
    except (ValueError, AttributeError):
        return ""
    return v if isinstance(v, str) and _VERSION.fullmatch(v) else ""


def read_local() -> str:
    exe = shutil.which("claude")
    if not exe:
        return ""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                           creationflags=flags)
        return parse_local(p.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def read_latest() -> str:
    try:
        req = urllib.request.Request(REGISTRY, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return parse_latest(r.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return ""    # offline, or behind a filter that eats the registry: fly no banner


class CliVersions:
    """Keeps the last good pair, refreshed on its own thread."""

    def __init__(self, refresh_s: float = REFRESH_S) -> None:
        self.refresh_s = refresh_s
        self.enabled = True
        self._v = Versions()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def snapshot(self) -> Versions:
        with self._lock:
            return self._v

    def set_snapshot(self, v: Versions) -> None:
        """Put an answer in by hand. For screenshots and tests, which must not hit the network."""
        with self._lock:
            self._v = v

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="duck_pond-version", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            v = Versions(yours=read_local(), latest=read_latest())
            with self._lock:
                # keep whichever half still answered, rather than blanking the banner on a blip
                self._v = Versions(yours=v.yours or self._v.yours,
                                   latest=v.latest or self._v.latest)
            self._stop.wait(self.refresh_s if v.known else RETRY_S)
