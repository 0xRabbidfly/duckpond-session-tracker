"""Pure-Python tests (no Blender): reducer, redaction, Claude Code adapter on real logs.

    python tests/test_core.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from duck_pond.adapters.stub import StubAdapter  # noqa: E402
from duck_pond.model import Fleet, context_window_for, model_version  # noqa: E402
from duck_pond.theme import (  # noqa: E402
    CONTEXT_BANDS,
    CONTEXT_LEGEND,
    context_band,
    context_ring_color,
    context_ring_holed,
    hat_for_model,
    hex_to_rgba,
    redact,
)


def test_redact():
    r = redact("key sk-abcdefghijklmnop please")
    assert "••••" in r and "abcdefghijklmnop" not in r
    assert "••••" in redact("Authorization: Bearer abcdefgh.ijklmnop")
    assert redact("x" * 200).endswith("…") and len(redact("x" * 200)) == 80
    assert redact("plain words", enabled=False) == "plain words"


def test_hats():
    assert hat_for_model("claude-fable-5-1") == "wizard"
    assert hat_for_model("claude-opus-5") == "top_hat"
    assert hat_for_model("claude-haiku-4-5-20251001") == "kasa"
    assert hat_for_model("gpt-5-codex") == "cap"
    assert hat_for_model("mystery-9") == "newspaper"
    assert hat_for_model("astra-1", [("astra", "crown")]) == "crown"


def test_stub_fixture():
    st = StubAdapter(os.path.join(ROOT, "fixtures", "demo.json"), loop=False)
    st.started -= 49  # everything up to the codex denial at 48 s, before any SessionEnded
    f = Fleet()
    for ev in st.poll(time.time()):
        f.apply(ev)
    assert len(f.sessions) == 4
    fable = f.sessions["cc-fable-1"]
    assert fable.harness == "claude_code" and fable.model == "claude-fable-5-1"
    assert len(fable.subagents) == 4  # explore-a, gp-b, nested-f (depth 2), bg-e (background)
    assert all(sub.done for sub in fable.subagents.values())
    assert sum(len(sub.packets) for sub in fable.subagents.values()) >= 6
    assert f.sessions["cc-opus-2"].state == "awaiting_user"
    assert f.sessions["codex-3"].error_message


def test_claude_adapter_real_logs():
    d = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(d):
        print("  (skipped: no ~/.claude/projects)")
        return
    a = ClaudeCodeAdapter(d, replay_all=True)
    t0 = time.time()
    evs = a.poll(time.time())
    f = Fleet()
    for ev in evs:
        f.apply(ev)
    dt = time.time() - t0
    subs = [sub for s in f.sessions.values() for sub in s.subagents.values()]
    down = sum(1 for sub in subs for p in sub.packets if p.direction == "down")
    print(f"  sessions={len(f.sessions)} subagents={len(subs)} done={sum(s.done for s in subs)} "
          f"down_packets={down} events={len(evs)} in {dt:.2f}s")
    assert f.sessions, "expected at least one session"
    assert all(s.harness == "claude_code" for s in f.sessions.values())
    if subs:
        assert any(s.done for s in subs), "sub-agent completions should be linked via toolUseResult.agentId"
        assert down > 0, "sub-agent prompts should become down packets"
        assert any(s.agent_type for s in subs), "meta.json agentType should be read"
    # a second poll only sees lines appended since (this very session may be writing its own log)
    # (transcripts > 8 MB are read in 8 MB chunks per poll; drain, then expect quiet)
    for _ in range(50):
        again = a.poll(time.time())
        if not again:
            break
    assert len(again) < 50, f"poll keeps emitting: {len(again)} events"


def test_backfill_real_logs():
    d = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(d):
        print("  (skipped: no ~/.claude/projects)")
        return
    t0 = time.time()
    evs = ClaudeCodeAdapter(d).backfill(t0)
    f = Fleet()
    for ev in evs:
        f.apply(ev)
    f.apply({"type": "BackfillDone"})
    dt = time.time() - t0
    now = time.time()
    rows = sum(len(e["rows"]) for e in evs)
    day, mtd = f.ledger.range_stats("day", now), f.ledger.month_to_date(now)
    print(f"  files={len(evs)} rows={rows} last 30 days ≈${day.usd:,.2f} ({day.sessions} sessions, +? {day.unpriced}) "
          f"month-to-date ≈${mtd.usd:,.2f} in {dt:.2f}s")
    assert all(e["type"] == "UsageBatch" for e in evs)
    assert not f.sessions, "backfill creates no ducks"
    assert f.ledger.ready
    if rows:
        assert day.usd > 0 and day.sessions > 0


def test_housekeeping():
    f = Fleet()
    now = 1000.0
    f.apply({"type": "SessionSeen", "session_id": "s1", "harness": "claude_code", "cwd": "/x", "at": now})
    f.apply({"type": "StateChanged", "session_id": "s1", "state": "generating", "at": now})
    f.housekeeping(now + 200, idle_after=180, end_after=600, remove_after=120)
    assert f.sessions["s1"].state == "idle"
    f.housekeeping(now + 700, idle_after=180, end_after=600, remove_after=120)
    assert f.sessions["s1"].state == "ended"
    f.housekeeping(now + 900, idle_after=180, end_after=600, remove_after=120)
    assert "s1" not in f.sessions
    assert any(c.kind == "despawn" for c in f.cues)


def test_background_subagent_lifecycle():
    """run_in_background agents: async_launched ack = spawn; task-notification / end_turn = done."""
    from duck_pond.adapters.claude_code import _TranscriptParser
    now = 1000.0
    parent = _TranscriptParser("s1")
    f = Fleet()
    f.apply({"type": "SessionSeen", "session_id": "s1", "harness": "claude_code", "cwd": "/x", "at": now})
    evs = []
    evs += parent.parse({"type": "assistant", "timestamp": "2026-09-10T21:41:00Z", "message": {"model": "claude-fable-5-1", "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "t1", "name": "Agent", "input": {"subagent_type": "general-purpose", "description": "review", "prompt": "review the reducer", "run_in_background": True}}]}}, now)
    evs += parent.parse({"type": "user", "timestamp": "2026-09-10T21:41:01Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Async agent launched successfully."}]},
        "toolUseResult": {"isAsync": True, "status": "async_launched", "agentId": "abc123", "description": "review", "resolvedModel": "claude-sonnet-5"}}, now)
    for e in evs:
        f.apply(e)
    sub = f.sessions["s1"].subagents["abc123"]
    assert not sub.done, "async launch must not complete the sub-agent"
    assert sub.model == "claude-sonnet-5" and sub.description == "review"
    assert not f.sessions["s1"].last_prompt, "launch ack is not a user prompt"
    evs = parent.parse({"type": "user", "timestamp": "2026-09-10T21:42:00Z", "message": {"content": "<task-notification>\n<task-id>abc123</task-id>\n<status>completed</status>\n<summary>Agent review finished</summary>\n</task-notification>"}}, now)
    for e in evs:
        f.apply(e)
    assert sub.done and sub.ok
    assert sub.packets and sub.packets[-1].kind == "report" and "finished" in sub.packets[-1].text
    assert not f.sessions["s1"].last_prompt, "task notification is not a user prompt"
    child = _TranscriptParser("s1", "def456")
    f.apply({"type": "SubAgentSeen", "session_id": "s1", "agent_id": "def456", "at": now})
    for e in child.parse({"type": "assistant", "isSidechain": True, "agentId": "def456", "timestamp": "2026-09-10T21:43:00Z",
                          "message": {"model": "claude-haiku-4-5", "stop_reason": "end_turn", "content": [{"type": "text", "text": "All done."}]}}, now):
        f.apply(e)
    sub2 = f.sessions["s1"].subagents["def456"]
    assert sub2.done and sub2.model == "claude-haiku-4-5"
    assert any(p.direction == "up" for p in sub2.packets)


def test_session_title_precedence():
    from duck_pond.adapters.claude_code import _TranscriptParser
    f = Fleet()
    now = 1000.0
    f.apply({"type": "SessionSeen", "session_id": "s1", "harness": "claude_code", "cwd": "/x", "at": now})
    p = _TranscriptParser("s1")
    for e in p.parse({"type": "user", "timestamp": "2026-09-10T21:00:00Z", "message": {"content": "download blender please"}}, now):
        f.apply(e)
    s = f.sessions["s1"]
    assert s.title == "download blender please" and s.title_source == "prompt"
    for e in p.parse({"type": "ai-title", "aiTitle": "Install Blender", "sessionId": "s1"}, now):
        f.apply(e)
    assert s.title == "Install Blender"
    for e in p.parse({"type": "custom-title", "customTitle": "forgeai", "sessionId": "s1"}, now):
        f.apply(e)
    assert s.title == "forgeai"
    for e in p.parse({"type": "ai-title", "aiTitle": "Something else", "sessionId": "s1"}, now):
        f.apply(e)
    assert s.title == "forgeai", "a custom title is never overridden by an AI title"
    assert s.display_name == "forgeai"


def test_context_ring_bands():
    """The ring is the only thing showing context, and it is banded: a duck is in one band or
    the next, with nothing in between, so the key can put a number on each change."""
    tops = [hi for hi, _c, _l in CONTEXT_BANDS]
    assert tops == sorted(tops) and tops[-1] == 1.0, tops
    assert context_ring_color(0.0) == context_ring_color(-5.0), "clamps below zero"
    assert context_ring_color(1.0) == context_ring_color(9.9), "clamps above one"
    # the bands the user reads off the key: empty to 20, half to 50, red to 80, full to 100
    assert [context_band(f) for f in (0.0, 0.2, 0.21, 0.5, 0.51, 0.8, 0.81, 1.0)] == [0, 0, 1, 1, 2, 2, 3, 3]
    for f in (0.0, 0.1, 0.45, 0.6, 0.75, 0.9, 1.0):
        rgba = context_ring_color(f)
        assert len(rgba) == 4 and all(0.0 <= c <= 1.0 for c in rgba), (f, rgba)
    # no blending inside a band, and a step at every boundary
    assert context_ring_color(0.01) == context_ring_color(0.2)
    for hi in tops[:-1]:
        assert context_ring_color(hi) != context_ring_color(hi + 0.01), hi
    # the top band is the punctured ring, and it is the only one
    assert [context_ring_holed(f) for f in (0.0, 0.5, 0.8, 0.81, 1.0)] == [False, False, False, True, True]
    assert context_ring_color(1.0)[:3] == hex_to_rgba("#0D0D0D")[:3], "full is black, not a colour"
    # every legend swatch names a real band
    for f, label in CONTEXT_LEGEND:
        assert 0.0 <= f <= 1.0 and label, (f, label)
    assert [label for _f, label in CONTEXT_LEGEND] == [lb for _hi, _c, lb in CONTEXT_BANDS]


def test_context_window_per_model():
    """A 1M-context session measured against a 200K window sits at 100 % for most of its life,
    which reads as 'about to run out' when it is a quarter full. Version matters: Opus 4.5 is a
    200K model and Opus 4.6 is not, so a bare family substring gets this wrong."""
    big = [
        "claude-opus-5", "claude-opus-5[1m]", "claude-opus-4-8", "claude-opus-4-7",
        "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6",
        "claude-fable-5", "claude-fable-5-1", "claude-mythos-5-1",
    ]
    small = [
        "claude-opus-4-5", "claude-opus-4-5-20251101", "claude-sonnet-4-5",
        "claude-haiku-4-5", "claude-haiku-4-5-20251001",
        "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022",
        "<synthetic>", "", None,
    ]
    for m in big:
        assert context_window_for(m) == 1_000_000, f"{m} should be a 1M-context model"
    for m in small:
        assert context_window_for(m) == 200_000, f"{m} should be a 200K-context model"

    assert model_version("claude-opus-4-8") == (4, 8)
    assert model_version("claude-opus-5") == (5, 0)
    assert model_version("claude-haiku-4-5-20251001") == (4, 5), "a date stamp is not a version"
    assert model_version("claude-3-7-sonnet-20250219") is None, "old-style ids carry no readable version"

    # and the meter that reads it
    f = Fleet()
    now = time.time()
    f.apply({"type": "SessionSeen", "session_id": "s", "harness": "claude_code", "cwd": "C:/p", "at": now})
    f.apply({"type": "ModelChanged", "session_id": "s", "model": "claude-opus-5", "at": now})
    f.apply({"type": "Usage", "session_id": "s", "tokens_in": 1000, "tokens_out": 10,
             "context_used": 250_000, "key": "k1", "at": now})
    s = f.sessions["s"]
    assert s.context_window == 1_000_000, s.context_window
    assert 0.24 < s.context_frac < 0.26, f"250k of 1M should read a quarter full, not {s.context_frac}"


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
