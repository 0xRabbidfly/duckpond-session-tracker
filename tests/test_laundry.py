"""Tests for the washing line's data (no Blender).

    python tests/test_laundry.py

The parser is tested against output captured from git 2.51 itself, not written from memory.
The last few tests build real repositories in a temporary folder and run the real reader
against them, when git is on PATH; one of them proves the reader never writes to a repository,
which is the promise that makes it safe to point at folders agents are committing in.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond import laundry as L  # noqa: E402
from duck_pond.laundry import (  # noqa: E402
    GitLaundry,
    Laundry,
    Wash,
    all_clear,
    allot,
    caption,
    inside,
    left_out,
    parse_status,
    pick,
    sample,
    towels,
)
from duck_pond.ledger import UsageLedger  # noqa: E402

# ---------------------------------------------------------------- captured from git 2.51
CLEAN = """# branch.oid 5749cf660ba8ac6d7e899a8c6aafc5c60313f550
# branch.head main
# branch.upstream origin/main
# branch.ab +0 -0
"""
DIRTY_AHEAD = """# branch.oid 354596c9d43a1eb4b6cff48631fafc85f10bd302
# branch.head main
# branch.upstream origin/main
# branch.ab +1 -0
1 MM N... 100644 100644 100644 78981922613b2afb6025042ff6bd878ac1994e85 9ad2ebbaff6f3397bb65002dcf4294d8d6243982 a.txt
1 .D N... 100644 100644 000000 f2ad6c76f0115a6ba5b00456a849810e7ec0af20 f2ad6c76f0115a6ba5b00456a849810e7ec0af20 c.txt
? d/
? new.txt
"""
RENAME = ("# branch.head main\n# branch.upstream origin/main\n# branch.ab +1 -0\n"
          "2 R. N... 100644 100644 100644 587be6b4c3f93f93c489c0111bba5596147a26cb "
          "587be6b4c3f93f93c489c0111bba5596147a26cb R100 sp ace2.txt\tsp ace.txt\n")
CONFLICT = """# branch.oid e0632bb6f37afafd26d49706e718816fc7bc8a6d
# branch.head main
# branch.upstream origin/main
# branch.ab +3 -0
u UU N... 100644 100644 100644 100644 78981922613b2afb6025042ff6bd878ac1994e85 ba2906d0666cf726c7eaadd2cd3db615dedfdf3a 2299c37978265a95cbe835a4b0f0bbf15aad5549 a.txt
"""
NO_UPSTREAM = "# branch.oid 681d58429d9368397c3b45d7cb6688903c0b27ef\n# branch.head side\n"
DETACHED = "# branch.oid 67b8de25527eb255383bcaed8bee2efedf5981da\n# branch.head (detached)\n"
FRESH = "# branch.oid (initial)\n# branch.head main\n? z.txt\n"


def test_a_clean_tracking_branch_has_nothing_on_the_line():
    w = parse_status(CLEAN)
    assert (w.changed, w.new, w.conflicts, w.ahead, w.behind) == (0, 0, 0, 0, 0)
    assert w.compared and w.branch == "main" and w.upstream == "origin/main"
    assert w.items == 0


def test_changed_deleted_and_untracked_are_counted_apart():
    w = parse_status(DIRTY_AHEAD)
    assert (w.changed, w.new, w.ahead) == (2, 2, 1), w   # MM and .D are changes; a new folder is one entry
    assert w.dirty == 4 and w.items == 5


def test_a_rename_is_one_change_whatever_is_in_its_paths():
    assert parse_status(RENAME).changed == 1


def test_a_path_with_a_newline_in_it_is_still_one_entry():
    # git quotes such a path onto one line; that is why the parser reads lines, not -z records
    text = '1 .M N... 100644 100644 100644 aaaa bbbb "we\\nird.txt"\n? "? not an entry"\n'
    w = parse_status(text)
    assert (w.changed, w.new) == (1, 1), w


def test_a_conflict_is_its_own_kind():
    w = parse_status(CONFLICT)
    assert (w.conflicts, w.changed, w.ahead) == (1, 0, 3), w


def test_without_an_upstream_git_has_not_compared_anything():
    for text, branch in ((NO_UPSTREAM, "side"), (DETACHED, "(detached)")):
        w = parse_status(text)
        assert not w.compared and w.ahead == 0 and w.upstream == "" and w.branch == branch, w


def test_a_repo_with_no_commits_yet():
    w = parse_status(FRESH)
    assert w.new == 1 and not w.compared, w


def test_behind_is_read_and_is_not_laundry():
    w = parse_status("# branch.ab +0 -4\n")
    assert (w.ahead, w.behind, w.compared) == (0, 4, True), w
    assert w.items == 0


def test_junk_is_nothing():
    for bad in ("", "fatal: not a git repository (or any of the parent directories): .git", None):
        assert parse_status(bad).items == 0, bad


# ---------------------------------------------------------------- what goes on the line
def test_pegs_go_to_whoever_has_fewest():
    # the small repository is shown exactly; the big one gets what is left
    assert allot([40, 3], 10) == [7, 3]
    assert allot([2, 2, 2], 10) == [2, 2, 2]
    assert allot([5, 5], 0) == [0, 0]
    assert allot([0, 4], 3) == [0, 3]


def test_allot_never_overspends_or_overfills():
    rnd = random.Random(1234)   # seeded: an unseeded test is a flaky test
    for _ in range(500):
        wants = [rnd.randint(0, 30) for _ in range(rnd.randint(1, 4))]
        slots = rnd.randint(0, 40)
        got = allot(wants, slots)
        assert sum(got) == min(slots, sum(wants)), (wants, slots, got)
        assert all(0 <= g <= w for g, w in zip(got, wants)), (wants, slots, got)
        # nobody left short while someone with more pegs could have given one up
        assert all(not (got[i] < wants[i] and got[j] > got[i] + 1)
                   for i in range(len(got)) for j in range(len(got))), (wants, slots, got)


def test_towels_hang_in_order_of_urgency():
    w = Wash(root="r", changed=2, new=1, conflicts=1, ahead=2)
    assert towels(w, 10) == ["conflict", "changed", "changed", "new", "folded", "folded"]


def test_when_it_does_not_fit_files_first_but_a_push_still_shows():
    w = Wash(root="r", changed=9, ahead=4)
    got = towels(w, 5)
    assert got == ["changed"] * 4 + ["folded"], got
    assert towels(w, 1) == ["changed"], "one peg: the uncommitted work, which is the kind that gets lost"
    assert towels(Wash(root="r", ahead=3), 2) == ["folded", "folded"]
    assert towels(w, 0) == []


def test_every_kind_there_is_gets_a_towel():
    # changed files do not crowd the new ones off: a glance can tell there is a mix
    assert towels(Wash(root="r", changed=4, new=2), 3) == ["changed", "changed", "new"]
    assert towels(Wash(root="r", changed=30, new=1, conflicts=1), 3) == ["conflict", "changed", "new"]


def test_a_huge_count_does_not_build_a_huge_list():
    t = time.perf_counter()
    got = towels(Wash(root="r", new=10 ** 7), 5)
    assert got == ["new"] * 5 and time.perf_counter() - t < 0.05


def test_caption_says_what_to_do_in_two_lines_at_most():
    assert caption(Wash(conflicts=2, changed=4, new=1, ahead=3)) == ("2 conflicts", "5 to commit")
    assert caption(Wash(conflicts=1)) == ("1 conflict",)
    assert caption(Wash(changed=3, ahead=2)) == ("3 to commit", "2 to push")
    assert caption(Wash(ahead=1)) == ("1 to push",)
    assert caption(Wash()) == ()


def test_inside_is_by_path_not_by_prefix():
    assert inside("C:\\Users\\dev\\proj\\sub", "C:/Users/dev/proj")    # git's slashes vs a transcript's
    assert inside("c:/users/dev/PROJ", "C:/Users/dev/proj/")
    assert not inside("C:/Users/dev/project2", "C:/Users/dev/proj"), "a longer name is not a subfolder"
    assert not inside("C:/Users/dev/proj", "")


def test_laundry_nobody_is_with_is_picked_first_and_hung_by_name():
    a = Wash(root="C:/p/alpha", changed=9)
    b = Wash(root="C:/p/bravo", changed=8)
    c = Wash(root="C:/p/charlie", changed=1)   # the least of it, but no duck is with it
    d = Wash(root="C:/p/delta", changed=5)
    clean = Wash(root="C:/p/echo")
    live = ["C:\\p\\alpha", "C:\\p\\bravo\\src", "C:\\p\\delta"]
    got = pick([d, clean, c, b, a], live, n=3)
    assert [w.name for w in got] == ["alpha", "bravo", "charlie"], [w.name for w in got]
    assert left_out(c, live) and not left_out(b, live)
    assert pick([clean], live) == [], "a clean repository has no place on the line"


SIX = [Wash(root="C:/p/alpha", changed=9), Wash(root="C:/p/bravo", changed=8, ahead=1),
       Wash(root="C:/p/charlie", changed=1), Wash(root="C:/p/delta", changed=5),
       Wash(root="C:/p/echo", new=2, ahead=3), Wash(root="C:/p/foxtrot", conflicts=1, changed=1),
       Wash(root="C:/p/golf")]                                   # and one clean
SIX_LIVE = ["C:/p/alpha", "C:/p/bravo", "C:/p/delta", "C:/p/echo", "C:/p/foxtrot"]   # charlie is left out


def test_six_repos_three_on_the_line_and_the_rest_on_a_more_card():
    shown = pick(SIX, SIX_LIVE)
    assert [w.name for w in shown] == ["alpha", "bravo", "charlie"], [w.name for w in shown]
    name, lines, gold = L.more(SIX, SIX_LIVE)
    assert name == "+3 more", name
    assert lines == ("1 conflict", "8 to commit"), lines   # delta 5 + echo 2 + foxtrot 1, the conflict first
    assert not gold, "everything left out made the line itself"
    # with nobody live at all, the hidden ones are left out too, and the card says so
    assert L.more(SIX, [])[2] is True
    assert L.more(SIX[:3], SIX_LIVE) is None, "three fit: no card, nothing hidden"


def test_nothing_with_laundry_is_ever_missing_from_line_and_card_together():
    rnd = random.Random(99)
    for _ in range(200):
        washes = [Wash(root=f"C:/r/{i}", changed=rnd.randint(0, 3), ahead=rnd.randint(0, 2))
                  for i in range(rnd.randint(0, 9))]
        live = [w.root for w in washes if rnd.random() < 0.5]
        extra = L.more(washes, live)
        hidden = int(extra[0].split()[0][1:]) if extra else 0
        assert len(pick(washes, live)) + hidden == sum(1 for w in washes if w.items), (washes, live)


def test_the_hover_card_lists_every_repo_most_in_need_first():
    from duck_pond.ui import cards
    c = cards.laundry_card(Laundry(tuple(SIX), ok=True), SIX_LIVE)
    names = [ln.split()[0] for ln in c.lines[:6]]
    assert names == ["charlie", "alpha", "bravo", "delta", "echo", "foxtrot"], c.lines
    assert c.lines[-1] == "1 other repo all put away", c.lines
    assert c.state_text == "1 left out" and "charlie" in c.highlight and c.color == cards.LEFT_OUT_GOLD
    many = Laundry(tuple(Wash(root=f"C:/r/{i:02d}", changed=1) for i in range(14)), ok=True)
    c = cards.laundry_card(many, [w.root for w in many.washes])
    assert len(c.lines) == cards.LAUNDRY_LINES + 1 and c.lines[-1] == "… and 4 more", c.lines
    assert not c.highlight and c.color != cards.LEFT_OUT_GOLD, "nothing left out: no gold"
    assert "all put away" in cards.laundry_card(Laundry((Wash(root="a"),), ok=True)).subtitle
    assert "no reading" in cards.laundry_card(Laundry()).subtitle


def test_all_put_away_only_when_git_has_actually_looked():
    assert all_clear(Laundry()) == (), "git has not answered: say nothing"
    assert all_clear(Laundry((), ok=True)) == (), "no repositories at all is not 'all put away'"
    two = Laundry((Wash(root="a"), Wash(root="b")), ok=True)
    assert all_clear(two) == ("all put away", "2 repos clean")
    assert all_clear(Laundry((Wash(root="a", ahead=1),), ok=True)) == ()


def test_the_sample_is_the_demo_plus_one_left_out():
    folders = ["C:\\Users\\dev\\Projects\\storefront", "C:\\Users\\dev\\Projects\\docs-site", "(no cwd)"]
    snap = sample(folders)
    names = [w.name for w in snap.washes]
    assert names == ["docs-site", "storefront", "billing"], names
    assert snap.washes[-1].root == "C:\\Users\\dev\\Projects\\billing"
    assert left_out(snap.washes[-1], folders) and not left_out(snap.washes[0], folders)
    assert sample(folders) == snap, "hand-written, not random: every render is the same"
    assert sample([]) == Laundry((), ok=True)


def test_the_ledger_names_folders_that_spent_since_a_time():
    led = UsageLedger()
    for at, cwd in ((1000.0, "C:/old"), (90_000.0, "C:/new"), (90_100.0, "(no cwd)")):
        led.add({"at": at, "session_id": "s", "cwd": cwd, "usd": 1.0, "key": f"{at}{cwd}"})
    assert led.cwds_since(80_000.0) == ["C:/new"]
    assert sorted(led.cwds_since(0.0)) == ["C:/new", "C:/old"]


def test_the_reader_is_told_folders_and_samples_them_in_demo_mode():
    g = GitLaundry()
    g.set_folders(["C:/a", "", "(no cwd)", "C:/a"])
    assert g._folders == ("C:/a",)
    g.set_sample(True)
    assert [w.name for w in g.snapshot().washes] == ["a", "billing"]
    g.set_folders(["C:/a", "C:/b"])
    assert [w.name for w in g.snapshot().washes] == ["a", "b", "billing"], "new demo folders re-sample"
    g.set_sample(False)
    assert g.snapshot() == Laundry(), "leaving demo mode takes the sample down"
    g.enabled = False
    g.set_sample(True)
    assert g.snapshot() == Laundry(), "switched off, even the demo hangs nothing"


# ---------------------------------------------------------------- the real thing, when git is here
def _run(cwd, *args):
    subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "user.email=t@example.invalid",
                    "-c", "user.name=T", *args], cwd=cwd, check=True, capture_output=True,
                   stdin=subprocess.DEVNULL)


def _repo(parent, name, remote=None):
    path = os.path.join(parent, name)
    os.makedirs(path)
    _run(path, "init", "-q", "-b", "main")
    with open(os.path.join(path, "a.txt"), "w") as f:
        f.write("a\n")
    _run(path, "add", "a.txt")
    _run(path, "commit", "-q", "--no-verify", "-m", "one")
    if remote:
        _run(parent, "init", "-q", "--bare", remote)
        _run(path, "remote", "add", "origin", os.path.join(parent, remote))
        _run(path, "push", "-q", "-u", "origin", "main")
    return path


def _with_git(fn):
    if not shutil.which("git"):
        print(f"SKIP {fn.__name__}: git is not on PATH")
        return
    tmp = tempfile.mkdtemp(prefix="duckpond-laundry-")
    try:
        fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reads_a_real_repository():
    def body(tmp):
        path = _repo(tmp, "work", remote="origin.git")
        with open(os.path.join(path, "a.txt"), "a") as f:
            f.write("more\n")
        with open(os.path.join(path, "new.txt"), "w") as f:
            f.write("n\n")
        _run(path, "commit", "-q", "--no-verify", "--allow-empty", "-m", "local")
        w = L.read_wash(L.repo_root(path))
        assert w is not None and (w.changed, w.new, w.ahead, w.compared) == (1, 1, 1, True), w
    _with_git(body)


def test_a_branch_never_pushed_still_counts_its_commits():
    def body(tmp):
        path = _repo(tmp, "work", remote="origin.git")
        _run(path, "checkout", "-q", "-b", "agent/feature")
        for i in range(2):
            _run(path, "commit", "-q", "--no-verify", "--allow-empty", "-m", f"c{i}")
        w = L.read_wash(L.repo_root(path))
        assert w is not None and not w.compared and w.ahead == 2, w
        local = _repo(tmp, "local-only")   # no remote anywhere: nothing to push to, not everything
        w = L.read_wash(L.repo_root(local))
        assert w is not None and w.ahead == 0, w
    _with_git(body)


def test_folders_are_grouped_by_repository_and_strangers_skipped():
    def body(tmp):
        path = _repo(tmp, "work")
        os.makedirs(os.path.join(path, "src", "deep"))
        g = GitLaundry()
        g.set_folders([path, os.path.join(path, "src", "deep"), tmp, os.path.join(tmp, "gone")])
        snap = g.read()
        assert snap.ok and len(snap.washes) == 1, snap
        assert len(snap.washes[0].folders) == 2 and snap.washes[0].name == "work", snap.washes[0]
    _with_git(body)


def test_reading_never_writes_to_the_repository():
    """Same content, new timestamp: a plain `git status` rewrites the index to refresh it.
    The reader must not -- an agent committing at that moment would find `index.lock` taken."""
    def body(tmp):
        path = _repo(tmp, "work")
        os.utime(os.path.join(path, "a.txt"), (1_577_836_800, 1_577_836_800))
        index = os.path.join(path, ".git", "index")

        def snap():
            with open(index, "rb") as f:
                return f.read()
        before = snap()
        for _ in range(3):
            L.read_wash(L.repo_root(path))
        assert snap() == before, "the reader rewrote .git/index"
        subprocess.run(["git", "status", "--porcelain=v2"], cwd=path, capture_output=True, check=True,
                       stdin=subprocess.DEVNULL)
        assert snap() != before, "control: a plain status should have refreshed it, or this test proves nothing"
    _with_git(body)


def test_a_repos_own_untracked_setting_stands():
    """A dotfiles repository at the home folder says showUntrackedFiles=no so git does not walk
    the whole disk. The reader must not override that."""
    def body(tmp):
        path = _repo(tmp, "home")
        with open(os.path.join(path, "stray.txt"), "w") as f:
            f.write("x\n")
        assert L.read_wash(path).new == 1, "control: an untracked file is seen by default"
        _run(path, "config", "status.showUntrackedFiles", "no")
        assert L.read_wash(path).new == 0, "the repository asked for no untracked scan"
    _with_git(body)


def test_a_repository_that_times_out_is_left_alone_for_a_while():
    calls = []
    saved = (L.TIMEOUT_S, L.read_wash, L.repo_root)
    try:
        L.TIMEOUT_S = 0.05

        def slow(root):
            calls.append(root)
            time.sleep(0.06)
            return None
        L.read_wash, L.repo_root = slow, (lambda cwd: cwd)
        g = GitLaundry()
        g.set_folders(["C:/huge"])
        g.read(now=1000.0)
        g.read(now=1000.0 + 60)
        assert calls == ["C:/huge"], f"timed out once, then skipped ({calls})"
        g.read(now=1000.0 + L.SLOW_S + 1)
        assert len(calls) == 2, "and tried again once the back-off is over"
    finally:
        L.TIMEOUT_S, L.read_wash, L.repo_root = saved


def test_a_reader_stopped_mid_read_never_writes_over_what_replaced_it():
    if not L.git_exe():
        print("SKIP: git is not on PATH (start() needs it)")
        return
    entered, release = threading.Event(), threading.Event()
    g = GitLaundry()

    def slow_read(now=None):
        entered.set()
        release.wait(5)
        return Laundry((Wash(root="C:/late", changed=1),), ok=True)
    g.read = slow_read
    g.start()
    assert entered.wait(5), "the reader started"
    g.stop()                        # switched off in the middle of a read ...
    g.set_snapshot(Laundry())       # ... and the washing taken in
    entered.clear()
    g.start()                       # and straight back on, while the old one is still reading
    assert entered.wait(5)
    g.stop()
    release.set()
    time.sleep(0.3)
    assert g.snapshot() == Laundry(), "a stopped reader wrote its late answer over the line"
    alive = [t for t in threading.enumerate() if t.name == "duck_pond-laundry"]
    assert not alive, f"every stopped reader is gone ({len(alive)} left)"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {exc!r}")
    sys.exit(1 if failures else 0)
