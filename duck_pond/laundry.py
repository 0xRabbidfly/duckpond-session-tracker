"""The washing line: the work your agents did that nobody has committed yet.

An agent edits eleven files, says it is done, and the duck swims off. Whether anyone then
committed that work is a question the pool never asked, and the answer is often no -- found
out a week later, when a branch switch or a stash eats it. So every folder a session worked in
gets a `git status` here, and whatever is not committed hangs on a washing line on the far
deck: one towel per changed file, and one towel folded over the line per commit the remote
does not have yet. The line outlives the ducks on purpose. Laundry still out after everyone
has gone home is exactly the case worth seeing, and its card says so in gold.

Read-only, and careful about it. `git --no-optional-locks status` never refreshes the index,
so it never takes `index.lock`, so an agent's own `git commit` can never fail because the pool
happened to be looking at the same repository at the same moment.

Parsing (`parse_status`) and every decision about what goes on the line (`pick`, `allot`,
`towels`, `caption`) are pure and live here. The subprocesses run on their own thread. The
geometry is `scene/laundry.py`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, replace

from .theme import folder_name

REFRESH_S = 20.0          # a file an agent just wrote is on the line within one of these
RESOLVE_S = 300.0         # how long "this folder belongs to that repository" is trusted
TIMEOUT_S = 10.0          # a status that takes longer than this is a repository to skip, not wait on
SLOW_S = 600.0            # and it is left alone this long, rather than timed out every pass
LOOKBACK_S = 24 * 3600.0  # folders that spent in the last day are checked even after their ducks leave
MAX_GROUPS = 3            # repositories on the line at once; more and the cards eat every peg
NO_CWD = "(no cwd)"       # the ledger's name for usage without a folder

KINDS = ("conflict", "changed", "new", "folded")


@dataclass(frozen=True)
class Wash:
    """One repository's laundry. A pure value: the thread builds them, the scene hangs them."""
    root: str = ""            # the repository's top level, as git prints it
    changed: int = 0          # tracked files with changes, staged or not; renames and deletions count
    new: int = 0              # untracked entries, as git lists them: a new folder is one entry
    conflicts: int = 0        # paths stopped in a merge
    ahead: int = 0            # commits the remote does not have
    behind: int = 0
    branch: str = ""
    upstream: str = ""
    compared: bool = False    # ahead / behind came from git's own comparison with the upstream
    folders: tuple[str, ...] = ()   # the session folders that live in this repository

    @property
    def name(self) -> str:
        return folder_name(self.root)

    @property
    def dirty(self) -> int:
        """Files not committed: each one a towel on the line."""
        return self.changed + self.new + self.conflicts

    @property
    def items(self) -> int:
        """Everything that wants a peg: the files, and the commits not pushed."""
        return self.dirty + self.ahead


@dataclass(frozen=True)
class Laundry:
    """Every repository read on the last pass, clean ones included."""
    washes: tuple[Wash, ...] = ()
    ok: bool = False          # git has answered at least once; before that the line says nothing


# ---------------------------------------------------------------- pure
def parse_status(text: str) -> Wash:
    """Count what `git status --porcelain=v2 --branch` lists. Pure.

    Only the first field of an entry is read, never its path, so a file name with spaces or
    tabs in it cannot throw the count off; one with a newline in it is quoted onto a single
    line by git, which is why this reads lines rather than `-z` records.
    """
    changed = new = conflicts = ahead = behind = 0
    branch = upstream = ""
    compared = False
    for line in (text or "").splitlines():
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head "):].strip()
        elif line.startswith("# branch.upstream "):
            upstream = line[len("# branch.upstream "):].strip()
        elif line.startswith("# branch.ab "):
            for tok in line[len("# branch.ab "):].split():
                if tok[:1] == "+" and tok[1:].isdigit():
                    ahead, compared = int(tok[1:]), True
                elif tok[:1] == "-" and tok[1:].isdigit():
                    behind = int(tok[1:])
        elif line.startswith(("1 ", "2 ")):   # ordinary change / rename or copy
            changed += 1
        elif line.startswith("u "):
            conflicts += 1
        elif line.startswith("? "):
            new += 1
    return Wash(changed=changed, new=new, conflicts=conflicts, ahead=ahead, behind=behind,
                branch=branch, upstream=upstream, compared=compared)


def _norm(path: str) -> str:
    # Lower-cased everywhere: git prints C:/Users/... and a transcript says C:\Users\..., and
    # two folders that differ only in case are not a thing anyone keeps side by side.
    return (path or "").replace("\\", "/").rstrip("/").lower()


def inside(cwd: str, root: str) -> bool:
    """True when `cwd` is `root` or somewhere under it. Pure."""
    c, r = _norm(cwd), _norm(root)
    return bool(r) and (c == r or c.startswith(r + "/"))


def left_out(w: Wash, live_cwds) -> bool:
    """Nobody is with this laundry: no live session is working anywhere in the repository."""
    return not any(inside(c, w.root) for c in live_cwds or ())


def pick(washes, live_cwds=(), n: int = MAX_GROUPS) -> list[Wash]:
    """The repositories that go on the line, in the order they hang. Pure.

    Laundry nobody is with is picked first, then whoever has the most of it; the rest go on
    the "+N more" card (`more`). The order along the line is by name, not by how much, so a
    count going up or down moves towels and never swaps whole groups about.
    """
    return sorted(ranked(washes, live_cwds)[:max(0, n)], key=lambda w: (w.name.lower(), w.root))


def ranked(washes, live_cwds=()) -> list[Wash]:
    """Every repository with laundry, most in need of you first: left out, then the most of it."""
    dirty = [w for w in washes if w.items > 0]
    return sorted(dirty, key=lambda w: (not left_out(w, live_cwds), -w.items, w.name.lower(), w.root))


def more(washes, live_cwds=(), n: int = MAX_GROUPS):
    """The card for the repositories that do not fit on the line: (name, lines, gold), or None.

    Nothing is dropped without a word: a line that shows three repositories when six have
    work outstanding would be hiding exactly the laundry most likely to be forgotten. The
    card adds the rest up, and is gold if any of them has been left out.
    """
    rest = ranked(washes, live_cwds)[max(0, n):]
    if not rest:
        return None
    total = Wash(changed=sum(w.changed for w in rest), new=sum(w.new for w in rest),
                 conflicts=sum(w.conflicts for w in rest), ahead=sum(w.ahead for w in rest))
    return (f"+{len(rest)} more", caption(total), any(left_out(w, live_cwds) for w in rest))


def allot(wants, slots: int) -> list[int]:
    """Share `slots` pegs between groups that want `wants` of them. Pure.

    Nobody gets more than they asked for. Pegs go one at a time to whoever has fewest so far,
    so every group whose count fits is shown exactly, and a repository with forty changes
    cannot crowd one with three off the line: it gets what is left once the small ones are
    whole, and its card carries the real number.
    """
    wants = [max(0, int(w)) for w in wants]
    got = [0] * len(wants)
    left = max(0, int(slots))
    while left > 0:
        hungry = [i for i, w in enumerate(wants) if got[i] < w]
        if not hungry:
            break
        i = min(hungry, key=lambda j: (got[j], j))
        got[i] += 1
        left -= 1
    return got


def towels(w: Wash, k: int) -> list[str]:
    """What hangs in a group's `k` slots, left to right. Pure.

    Conflicts, then changed files, then new ones, then a towel folded over the line for each
    commit the remote lacks. When it does not all fit, files come first -- uncommitted work is
    the kind that gets lost -- but a group with commits to push keeps one folded towel as long
    as it has two slots, because pushing is a different job and should show. The hanging kinds
    share their pegs the way groups do, so every kind there is gets a towel and the smaller
    counts are exact: the line says "a conflict, some changes, a few new files" at a glance
    even when the numbers are only on the card.
    """
    k = max(0, int(k))
    hang = min(w.dirty, k)
    fold = min(w.ahead, k - hang)
    if w.ahead and not fold and hang >= 2:
        hang, fold = hang - 1, 1
    out: list[str] = []
    for kind, n in zip(("conflict", "changed", "new"), allot([w.conflicts, w.changed, w.new], hang)):
        out += [kind] * n
    return out + ["folded"] * fold


def caption(w: Wash) -> tuple[str, ...]:
    """The lines under the card's name: what there is to do, most urgent first, two at most.

    Lines, not one string joined with dots: the card is read from the far side of the pool,
    where a line long enough to say both things is a line too small to read.
    """
    parts = []
    if w.conflicts:
        parts.append(f"{w.conflicts} conflict" + ("" if w.conflicts == 1 else "s"))
    if w.changed + w.new:
        parts.append(f"{w.changed + w.new} to commit")
    if w.ahead:
        parts.append(f"{w.ahead} to push")
    return tuple(parts[:2])


def all_clear(snap: Laundry) -> tuple[str, ...]:
    """The card for an empty line, or () when there is nothing honest to say.

    Only when git has actually looked at something: an empty line because git is missing, or
    because no session has a folder yet, is not the same as everything being put away.
    """
    if not snap.ok or not snap.washes or any(w.items for w in snap.washes):
        return ()
    n = len(snap.washes)
    return ("all put away", f"{n} repo{'' if n == 1 else 's'} clean")


# (changed, new, conflicts, ahead): hand-written rather than random, like the ledger's sample
# day -- a feature half done with commits not pushed, work committed and not pushed, and a
# merge that stopped on a conflict.
_SAMPLE = ((4, 2, 0, 3), (0, 0, 0, 2), (6, 1, 1, 0))
_SAMPLE_LEFT_OUT = ("billing", (3, 0, 0, 1))


def sample(folders) -> Laundry:
    """A plausible line for the demo's made-up folders. For screenshots, tests and `--stub`,
    which must show the line without there being a real repository behind any of it.

    One extra repository sits beside the demo's folders with no duck in it, because laundry
    left out is the point of the line and a demo that never shows it hides the point.
    """
    folders = sorted({f for f in folders or () if f and f != NO_CWD})
    washes = []
    for i, f in enumerate(folders):
        c, n, u, a = _SAMPLE[i % len(_SAMPLE)]
        washes.append(Wash(root=f, changed=c, new=n, conflicts=u, ahead=a, compared=True,
                           branch="main", folders=(f,)))
    if folders:
        sep = "\\" if "\\" in folders[0] else "/"
        parent = folders[0].rstrip(sep).rsplit(sep, 1)[0]
        name, (c, n, u, a) = _SAMPLE_LEFT_OUT
        washes.append(Wash(root=parent + sep + name, changed=c, new=n, conflicts=u, ahead=a,
                           compared=True, branch="main"))
    return Laundry(tuple(washes), ok=True)


# ---------------------------------------------------------------- git
_GIT: list[str | None] = []


def git_exe() -> str | None:
    if not _GIT:
        _GIT.append(shutil.which("git"))
    return _GIT[0]


def _git(cwd: str, *args: str) -> str | None:
    """stdout of one git command in `cwd`, or None when it failed for any reason at all."""
    exe = git_exe()
    if not exe:
        return None
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run([exe, "--no-optional-locks", "-C", cwd, *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return p.stdout if p.returncode == 0 else None


def repo_root(cwd: str) -> str:
    """The top level of the repository `cwd` is in, or "" when it is in none."""
    if not cwd or not os.path.isdir(cwd):   # a folder deleted since: no need to ask git
        return ""
    out = _git(cwd, "rev-parse", "--show-toplevel")
    return out.strip() if out else ""


def _unpushed(root: str) -> int:
    """Commits on HEAD that no remote-tracking branch has.

    For the branch an agent made and never pushed, which `branch.ab` cannot see because it
    has no upstream to compare with. A repository with no remote at all has nowhere to push
    to, so it reads as nothing rather than as every commit it has ever had.
    """
    if not (_git(root, "for-each-ref", "--count=1", "--format=x", "refs/remotes") or "").strip():
        return 0
    n = (_git(root, "rev-list", "--count", "HEAD", "--not", "--remotes") or "").strip()
    return int(n) if n.isdigit() else 0


def read_wash(root: str) -> Wash | None:
    # No --untracked-files: the repository's own status.showUntrackedFiles stands. A dotfiles
    # repository at the home folder sets it to "no" so that git does not walk the whole disk,
    # and a flag here would override that on every pass.
    out = _git(root, "status", "--porcelain=v2", "--branch")
    if out is None:
        return None
    w = replace(parse_status(out), root=root)
    return w if w.compared else replace(w, ahead=_unpushed(root))


class GitLaundry:
    """Keeps the last good reading of every repository the sessions worked in, refreshed on
    its own thread. The main thread says which folders matter (`set_folders`) and draws
    whatever `snapshot` last returned."""

    def __init__(self, refresh_s: float = REFRESH_S) -> None:
        self.refresh_s = refresh_s
        self.enabled = True
        self.sample = False       # demo mode: hang `sample(folders)` instead of asking git
        self._folders: tuple[str, ...] = ()
        self._roots: dict[str, tuple[str, float]] = {}   # folder -> (repository or "", when asked)
        self._slow: dict[str, float] = {}                # repository -> when to try it again
        self._snap = Laundry()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    def snapshot(self) -> Laundry:
        with self._lock:
            return self._snap

    def set_snapshot(self, snap: Laundry) -> None:
        """Put a reading in by hand. For screenshots and tests, which must not run git."""
        with self._lock:
            self._snap = snap

    def set_sample(self, on: bool) -> None:
        """Demo mode: hang `sample(folders)` for whatever folders the demo has, and never run git."""
        with self._lock:
            if self.sample and not on:
                self._snap = Laundry()      # a sample is not a reading: do not leave it up
            self.sample = on
            if on and self.enabled:
                self._snap = sample(self._folders)

    def set_folders(self, folders) -> None:
        f = tuple(sorted({x for x in folders or () if x and x != NO_CWD}))
        with self._lock:
            if f == self._folders:
                return
            fresh = bool(set(f) - set(self._folders))
            self._folders = f
            if self.sample and self.enabled:
                self._snap = sample(f)
        if fresh:
            self._wake.set()      # a new folder: look now, not up to twenty seconds from now

    def start(self) -> None:
        if not self.enabled or self.sample or not git_exe():
            return
        if self._thread and self._thread.is_alive():
            return
        # A fresh stop flag for every thread. A reader still inside its last `git status` when
        # it was stopped keeps the flag that was set, so it can never carry on beside the reader
        # that replaced it.
        self._stop = stop = threading.Event()
        self._wake.set()          # the first reading straight away
        self._thread = threading.Thread(target=self._loop, args=(stop,), name="duck_pond-laundry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self._wake.wait(self.refresh_s)
            self._wake.clear()
            if stop.is_set():
                break
            try:
                snap = self.read()
            except Exception:  # noqa: BLE001 - a bad repository must not take the line down
                print("[duck_pond] laundry error:", traceback.format_exc(limit=3))
                continue
            with self._lock:
                if stop.is_set():
                    break     # stopped mid-read -- switched off, say: whatever replaced this reading stands
                self._snap = snap

    def read(self, now: float | None = None) -> Laundry:
        """One pass over every folder: which repository each is in, then one status per repository."""
        now = time.time() if now is None else now
        with self._lock:
            folders = self._folders
        by_root: dict[str, list[str]] = {}
        for cwd in folders:
            root, at = self._roots.get(cwd, ("", -1e18))
            if now - at > RESOLVE_S:
                root = repo_root(cwd)
                self._roots[cwd] = (root, now)
            if root:
                by_root.setdefault(root, []).append(cwd)
        for cwd in [c for c in list(self._roots) if c not in folders]:
            self._roots.pop(cwd, None)
        washes = []
        for root, cwds in sorted(by_root.items()):
            if self._slow.get(root, 0.0) > now:
                continue          # timed out lately: left alone for a while, not timed out again
            t = time.monotonic()
            w = read_wash(root)
            if w is None and time.monotonic() - t >= TIMEOUT_S * 0.9:
                self._slow[root] = now + SLOW_S
                print(f"[duck_pond] laundry: git status in {root} took over {TIMEOUT_S:.0f} s; "
                      f"leaving it alone for {SLOW_S / 60:.0f} min")
            if w is not None:
                washes.append(replace(w, folders=tuple(cwds)))
        return Laundry(tuple(washes), ok=True)
