"""Click a duck, get its terminal.

Herdr (herdr.dev) runs each agent in a pane of its own and exposes a socket API over a CLI.
`herdr agent list` reports, for every pane, the Claude session id running in it -- the same
uuid Duck Pond uses as a duck's identity, because both take it from the transcript name. So
the join is exact: no title matching, no guessing by working directory.

Everything here runs on a worker thread. Focusing takes two subprocess calls of about an eighth
of a second each, and the viewport is not going to wait for that.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading

TIMEOUT_S = 8.0
_have: bool | None = None   # whether the CLI is on PATH; resolved once
_warned: set[str] = set()   # complain about a given failure once, not once per click


def _warn(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        print(f"[duck_pond] herdr: {msg}")


def available() -> bool:
    """Is the CLI on PATH? Cached: the sidebar asks on every redraw, and a PATH scan is not free."""
    global _have
    if _have is None:
        _have = shutil.which("herdr") is not None
    return _have


def _run(*args: str) -> tuple[int, str, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # no console flash over a kiosk screen
    p = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=TIMEOUT_S,
                       encoding="utf-8", errors="replace", creationflags=flags)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def pane_in(payload: str, session_id: str) -> str | None:
    """Pick the pane running `session_id` out of `herdr agent list` output. Pure, so it is
    the part worth testing: the CLI around it is two lines."""
    try:
        agents = json.loads(payload)["result"]["agents"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(agents, list):
        return None
    for a in agents:
        if not isinstance(a, dict):
            continue
        sess = a.get("agent_session") or {}
        if isinstance(sess, dict) and sess.get("value") == session_id:
            pane = a.get("pane_id")
            return pane if isinstance(pane, str) and pane else None
    return None


def pane_for(session_id: str) -> str | None:
    """The Herdr pane running this Claude session, or None."""
    rc, out, err = _run("agent", "list")
    if rc != 0 or not out:
        _warn("list", f"could not list agents: {(err or out)[:120]}")
        return None
    pane = pane_in(out, session_id)
    if pane is None and '"agents"' not in out:
        _warn("parse", f"could not read the agent list: {out[:120]}")
    return pane


def _process_table() -> tuple[dict[int, int], list[int]]:
    """(pid -> parent pid, herdr pids), from one process snapshot."""
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if snap == -1:
        return {}, []
    parent: dict[int, int] = {}
    ours: list[int] = []
    try:
        e = ENTRY()
        e.dwSize = ctypes.sizeof(ENTRY)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            parent[e.th32ProcessID] = e.th32ParentProcessID
            if e.szExeFile.lower() == "herdr.exe":
                ours.append(e.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return parent, ours


def _windows_by_pid() -> dict[int, int]:
    """Visible, titled top-level windows, one per owning process."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    out: dict[int, int] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lp):
        if u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.setdefault(pid.value, hwnd)
        return True

    u32.EnumWindows(each, 0)
    return out


def herdr_window():
    """The handle of the window Herdr is showing in, or None.

    Herdr owns no window of its own: it is a terminal program, so the window belongs to
    whatever is hosting it -- here Windows Terminal, by way of a PowerShell. So find the
    herdr processes and walk up the tree to the first ancestor that has a window. Matching
    on the title would be hopeless: it is whatever the focused pane last printed.
    """
    parent, pids = _process_table()
    if not pids:
        return None
    wins = _windows_by_pid()
    for pid in pids:
        seen = set()
        for _ in range(8):     # a tree that deep is not a terminal hosting a shell
            if pid in wins:
                return wins[pid]
            if pid in seen or pid not in parent:
                break
            seen.add(pid)
            pid = parent[pid]
    return None


def _raise_window() -> None:
    """Bring Herdr's window to the front. Focusing a pane changes which pane is active inside
    Herdr; it does not raise the window, and on a second monitor that is the difference between
    seeing the terminal and not."""
    try:
        import ctypes
        hwnd = herdr_window()
        if hwnd is None:
            return                            # the CLI can reach a server with no GUI attached
        u32 = ctypes.windll.user32
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)           # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
    except Exception as exc:  # noqa: BLE001 - raising a window is a nicety, never a failure
        _warn("raise", f"could not raise the window: {exc}")


def focus_session(session_id: str, raise_window: bool = True) -> None:
    """Focus the pane running `session_id`, on a thread. Never raises, never blocks."""
    if not session_id or not available():
        return

    def work() -> None:
        try:
            pane = pane_for(session_id)
            if pane is None:
                return          # not every duck is a Herdr pane: a session can outlive its tab
            rc, _out, err = _run("agent", "focus", pane)
            if rc != 0:
                _warn("focus", f"could not focus {pane}: {err[:120]}")
                return
            if raise_window:
                _raise_window()
        except (OSError, subprocess.SubprocessError) as exc:
            _warn("run", f"could not run the CLI: {exc}")

    threading.Thread(target=work, name="duck_pond-herdr", daemon=True).start()
