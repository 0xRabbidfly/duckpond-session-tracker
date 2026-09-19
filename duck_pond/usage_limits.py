"""Your Anthropic usage limits, read from the Claude Code CLI.

Nothing on disk records them: `~/.claude/policy-limits.json` is about policy restrictions, and
the transcripts carry no quota at all. `claude -p "/usage"` prints them, so that is what this
runs. It is a real subprocess that spends a few tokens each time, so it runs on its own thread,
on a long interval, and the pool draws the last good answer in between.

Pure parsing lives in `parse_usage`; everything bpy-shaped is somewhere else.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

REFRESH_S = 300.0        # five minutes: the numbers move slowly and each read costs tokens
RETRY_S = 60.0           # after a failure, try again sooner than the full interval
TIMEOUT_S = 120.0        # the CLI starts a session; it is not instant

# "Current session: 24% used · resets Sep 19, 8:30pm (America/Toronto)"
# "Current week (all models): 3% used · resets Sep 26, 4pm (America/Toronto)"
_SESSION = re.compile(r"^\s*current session[^:]*:\s*(\d+(?:\.\d+)?)\s*%\s*used\b(.*)$", re.I | re.M)
_WEEK = re.compile(r"^\s*current week[^:]*:\s*(\d+(?:\.\d+)?)\s*%\s*used\b(.*)$", re.I | re.M)
_RESETS = re.compile(r"resets\s+(.+?)\s*$", re.I)
_TZ_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


@dataclass
class Gauge:
    """One limit window: how full, and when it clears."""
    frac: float = 0.0        # 0..1
    resets: str = ""         # as the CLI worded it, minus the timezone in brackets


@dataclass
class Usage:
    session: Gauge = field(default_factory=Gauge)   # the 5-hour window
    week: Gauge = field(default_factory=Gauge)      # the 7-day window
    at: float = 0.0          # when this was read
    ok: bool = False
    error: str = ""


def _gauge(m) -> Gauge:
    pct = max(0.0, min(100.0, float(m.group(1))))
    tail = m.group(2) or ""
    r = _RESETS.search(tail)
    resets = _TZ_SUFFIX.sub("", r.group(1)).strip() if r else ""
    return Gauge(frac=pct / 100.0, resets=resets)


def parse_usage(text: str) -> Usage:
    """Read `claude -p "/usage"` output. A missing window stays at zero rather than guessing."""
    u = Usage(at=time.time())
    s, w = _SESSION.search(text or ""), _WEEK.search(text or "")
    if s:
        u.session = _gauge(s)
    if w:
        u.week = _gauge(w)
    u.ok = bool(s or w)
    if not u.ok:
        first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
        u.error = f"no limits in the CLI output ({first[:80]})" if first else "the CLI printed nothing"
    return u


def _claude_exe() -> str | None:
    """The CLI, preferring the Windows shim so subprocess can run it without a shell."""
    for name in ("claude.cmd", "claude.exe", "claude"):
        found = shutil.which(name)
        if found:
            return found
    return None


def read_usage(timeout: float = TIMEOUT_S) -> Usage:
    """Run the CLI once and parse it. Never raises."""
    exe = _claude_exe()
    if exe is None:
        return Usage(at=time.time(), error="the claude CLI is not on PATH")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash over a kiosk screen
    # --no-session-persistence keeps this out of ~/.claude/projects. Without it every refresh
    # left a transcript behind and Duck Pond drew its own meter-reading as a duck in the pool.
    cmd = [exe, "-p", "--no-session-persistence", "/usage"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=flags, cwd=os.path.expanduser("~"),
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return Usage(at=time.time(), error=f"the CLI did not answer within {timeout:.0f}s")
    except OSError as exc:
        return Usage(at=time.time(), error=f"could not run the CLI: {exc}")
    u = parse_usage(p.stdout or "")
    if not u.ok and p.returncode != 0:
        u.error = f"the CLI exited {p.returncode}: {(p.stderr or '').strip()[:80]}"
    return u


class UsageLimits:
    """Keeps the last good reading, refreshed on its own thread."""

    def __init__(self, refresh_s: float = REFRESH_S) -> None:
        self.refresh_s = refresh_s
        self.enabled = True
        self._usage = Usage()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def snapshot(self) -> Usage:
        with self._lock:
            return self._usage

    def set_snapshot(self, usage: Usage) -> None:
        """Put a reading in by hand. For screenshots and tests, which must not spend tokens."""
        with self._lock:
            self._usage = usage

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="duck_pond-usage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            u = read_usage()
            with self._lock:
                if u.ok or not self._usage.ok:
                    self._usage = u          # keep the last good numbers through a blip
                else:
                    self._usage.error = u.error
            self._stop.wait(self.refresh_s if u.ok else RETRY_S)
