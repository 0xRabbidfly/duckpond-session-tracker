"""Pure tests for the Herdr pane lookup (no Blender, no CLI).

    python tests/test_herdr.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.herdr import pane_in  # noqa: E402

SESS = "e7602728-1111-4222-8333-444455556666"
OTHER = "aaaaaaaa-1111-4222-8333-444455556666"


def _agent(pane: str, value: str | None, **extra):
    a = {"pane_id": pane, "tab_id": pane.split(":")[0] + ":t1", "workspace_id": pane.split(":")[0],
         "cwd": "C:\\Users\\dev\\Projects\\storefront", "focused": False,
         "terminal_title_stripped": "claude", **extra}
    if value is not None:
        a["agent_session"] = {"agent": "claude", "kind": "id", "source": "herdr:claude", "value": value}
    return a


def _list(*agents) -> str:
    return json.dumps({"id": "cli:agent:list", "result": {"agents": list(agents)}})


def test_finds_the_pane_running_this_session():
    out = _list(_agent("w4:p1", OTHER), _agent("w1:p1", SESS))
    assert pane_in(out, SESS) == "w1:p1"


def test_unknown_session_is_not_a_guess():
    # A duck can outlive the tab that ran it. Better no focus than the wrong terminal.
    assert pane_in(_list(_agent("w4:p1", OTHER)), SESS) is None


def test_empty_pond():
    assert pane_in(_list(), SESS) is None


def test_a_pane_with_no_agent_is_skipped():
    out = _list(_agent("w2:p3", None), _agent("w1:p1", SESS))
    assert pane_in(out, SESS) == "w1:p1"


def test_the_title_is_never_matched_on():
    # Titles carry the working directory and spinner glyphs, and two agents can share one.
    out = _list(_agent("w4:p1", OTHER, terminal_title_stripped=SESS))
    assert pane_in(out, SESS) is None


def test_junk_does_not_raise():
    for bad in ("", "not json", "{}", '{"result": {}}', '{"result": {"agents": "nope"}}',
                '{"result": {"agents": [null, 7]}}', _list(_agent("", SESS))):
        assert pane_in(bad, SESS) is None, bad


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
