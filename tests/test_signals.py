"""Pure-Python tests for the reimagined signals (no Blender).

    python tests/test_signals.py

Covers: tool categories, the question / denial / compaction / queue / cost-state reducers,
permission-wait inference, the fleet's per-minute history, the adapter's parsing of thinking
blocks, AskUserQuestion, denials, permission-mode, compaction and nested / background agents.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.adapters.claude_code import _TranscriptParser  # noqa: E402
from duck_pond.model import Fleet  # noqa: E402
from duck_pond.theme import STATE_COLORS, tool_category, tool_chip  # noqa: E402
from duck_pond.ui import cards  # noqa: E402

T = 1_000_000.0


def _fleet(sid="s1", mode=""):
    f = Fleet()
    f.apply({"type": "SessionSeen", "session_id": sid, "harness": "claude_code", "model": "claude-opus-5",
             "cwd": "/x", "branch": "main", "at": T, "permission_mode": mode})
    f.apply({"type": "StateChanged", "session_id": sid, "state": "generating", "at": T})
    return f


def _cues(f, kind):
    return [c for c in f.cues if c.kind == kind]


def test_tool_categories():
    assert tool_category("Bash", "python tests/headless_motion.py") == "test"
    assert tool_category("Bash", "pytest -q") == "test"
    assert tool_category("Bash", "git status") == "bash"
    assert tool_category("Bash", "digest the log") == "bash"  # no \\bjest\\b match
    assert tool_category("shell", "npm test") == "test"
    assert tool_category("runTests", "") == "test"
    assert tool_category("Edit") == "edit" and tool_category("Write") == "edit"
    assert tool_category("Read") == "read" and tool_category("Grep") == "read" and tool_category("Glob") == "read"
    assert tool_category("WebFetch") == "web" and tool_category("WebSearch") == "web"
    assert tool_category("Agent") == "agent"
    assert tool_category("AskUserQuestion") == "ask"
    assert tool_category("mcp__playwright__browser_click") == "browser"
    assert tool_category("mcp__github__list_issues") == "mcp"
    assert tool_category("Frobnicate") == "other"
    text, hexc = tool_chip("test")
    assert text == "test" and hexc.startswith("#")
    for st in ("generating", "tool_running", "awaiting_user", "awaiting_permission", "idle", "ended", "error"):
        assert st in STATE_COLORS


def test_question_flow():
    f = _fleet()
    f.apply({"type": "ToolCall", "session_id": "s1", "name": "AskUserQuestion", "tool_id": "q1",
             "summary": "Which database?", "done": False, "at": T + 1})
    s = f.sessions["s1"]
    assert s.state == "awaiting_user" and s.state_confidence == "exact"
    assert s.question == "Which database?"
    assert _cues(f, "question") and not _cues(f, "big_ripple")[1:], "a question is not a tool dip"
    card = cards.session_card(s, T + 2, True)
    assert "Which database?" in card.highlight
    name, status, state = cards.tag_for(f, ("s1", ""), T + 2, True)
    assert status == "asking you"
    f.apply({"type": "Prompt", "session_id": "s1", "text": "postgres", "at": T + 5})
    assert s.question == "" and _cues(f, "prompt_drop")


def test_denial_flow():
    f = _fleet(mode="default")
    f.apply({"type": "ToolCall", "session_id": "s1", "name": "Write", "tool_id": "w1", "summary": "x.py", "done": False, "at": T + 1})
    s = f.sessions["s1"]
    assert s.state == "tool_running" and s.current_tool_category == "edit"
    # unanswered for 12 s in a mode that asks -> blocked on permission (inferred)
    f.housekeeping(T + 14, idle_after=180, end_after=1800, remove_after=60)
    assert s.state == "awaiting_permission" and s.state_confidence == "inferred"
    f.apply({"type": "ToolCall", "session_id": "s1", "name": "Write", "tool_id": "w1", "done": True, "ok": False,
             "denied": "user-rejected", "at": T + 20})
    assert s.state == "awaiting_user" and s.denied_kind == "user-rejected"
    assert _cues(f, "denied") and s.tool_errors == 1
    assert s.tool_history[-1][1] == "edit" and s.tool_history[-1][2] is False
    # bypass mode never infers a permission wait, and long-running kinds are exempt
    g = _fleet(mode="bypassPermissions")
    g.apply({"type": "ToolCall", "session_id": "s1", "name": "Write", "tool_id": "w1", "summary": "x", "done": False, "at": T + 1})
    g.housekeeping(T + 60, idle_after=180, end_after=1800, remove_after=60)
    assert g.sessions["s1"].state == "tool_running"
    h = _fleet(mode="default")
    h.apply({"type": "ToolCall", "session_id": "s1", "name": "Bash", "tool_id": "b", "summary": "npm run build", "done": False, "at": T + 1})
    h.housekeeping(T + 60, idle_after=180, end_after=1800, remove_after=60)
    assert h.sessions["s1"].state == "tool_running", "a long Bash run is not a permission prompt"


def test_compaction_queue_cost():
    f = _fleet()
    s = f.sessions["s1"]
    f.apply({"type": "Usage", "session_id": "s1", "tokens_in": 100, "tokens_out": 50, "context_used": 190000, "at": T + 1})
    assert s.context_frac > 0.9
    f.apply({"type": "Compaction", "session_id": "s1", "pre_tokens": 190000, "post_tokens": 20000, "at": T + 2})
    assert s.compactions == 1 and s.context_frac < 0.2 and s.last_compaction_at == T + 2
    assert _cues(f, "compaction")[0].at == T + 2
    f.apply({"type": "Queue", "session_id": "s1", "op": "enqueue", "text": "and then…", "at": T + 3})
    f.apply({"type": "Queue", "session_id": "s1", "op": "enqueue", "text": "also…", "at": T + 4})
    assert s.queued == 2 and len(_cues(f, "queued")) == 2
    f.apply({"type": "Queue", "session_id": "s1", "op": "dequeue", "at": T + 5})
    assert s.queued == 1
    f.apply({"type": "Prompt", "session_id": "s1", "text": "also…", "at": T + 6})
    assert s.queued == 0
    f.apply({"type": "CostState", "session_id": "s1", "cost_usd": 12.5, "lines_added": 300, "lines_removed": 20,
             "tool_time_ms": 5000, "api_time_ms": 90000, "model_usage": {"claude-opus-5": {"costUSD": 12.5}}, "at": T + 7})
    assert s.cost_usd == 12.5 and s.lines_added == 300 and s.lines_removed == 20 and "claude-opus-5" in s.model_usage
    t = f.totals(T + 8)
    assert t["cost_usd"] == 12.5 and t["lines"] == 320


def test_done_and_thinking():
    f = _fleet()
    s = f.sessions["s1"]
    f.apply({"type": "Thinking", "session_id": "s1", "at": T + 1})
    assert s.thinking
    assert cards.tag_for(f, ("s1", ""), T + 1, True)[1] == "thinking"
    f.apply({"type": "Text", "session_id": "s1", "text": "Here is the plan.", "at": T + 2})
    assert not s.thinking
    f.apply({"type": "StateChanged", "session_id": "s1", "state": "awaiting_user", "at": T + 3})
    assert s.last_done_at == T + 3
    assert _cues(f, "done") and _cues(f, "report_up")
    assert cards.tag_for(f, ("s1", ""), T + 4, True)[1] == "your turn"


def test_history_buckets_and_throughput():
    f = _fleet()
    for i in range(10):
        f.apply({"type": "Usage", "session_id": "s1", "tokens_out": 100, "at": T + i * 30})
    minutes = {m for m, _, _ in f.history}
    assert len(minutes) in (5, 6), f"10 samples over 4.5 min fill 5 or 6 minute buckets (T is not minute-aligned), got {len(minutes)}"
    assert sum(tk for _, tk, _ in f.history) == 1000
    assert f.tokens_per_sec(T + 275, 20.0) == 100 / 20.0  # only the T+270 sample is inside the 20 s window


def test_adapter_new_signals():
    p = _TranscriptParser("s1")
    ts = "2026-09-10T21:41:00Z"
    evs = p.parse({"type": "permission-mode", "permissionMode": "default", "sessionId": "s1"}, T)
    assert evs[0]["type"] == "PermissionMode" and evs[0]["mode"] == "default"
    evs = p.parse({"type": "assistant", "timestamp": ts, "effort": "max", "message": {"model": "claude-opus-5", "stop_reason": None,
                   "content": [{"type": "thinking", "thinking": "", "signature": "x"}]}}, T)
    kinds = [e["type"] for e in evs]
    assert "Thinking" in kinds and "Effort" in kinds and "ModelChanged" in kinds
    evs = p.parse({"type": "assistant", "timestamp": ts, "message": {"model": "claude-opus-5", "stop_reason": "tool_use",
                   "content": [{"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
                                "input": {"questions": [{"question": "Tabs or spaces?", "header": "Style", "options": []}]}}]}}, T)
    tc = [e for e in evs if e["type"] == "ToolCall"][0]
    assert tc["summary"] == "Tabs or spaces?"
    evs = p.parse({"type": "user", "timestamp": ts, "toolDenialKind": "user-rejected",
                   "message": {"content": [{"type": "tool_result", "tool_use_id": "q1", "is_error": True, "content": "rejected"}]}}, T)
    tc = [e for e in evs if e["type"] == "ToolCall"][0]
    assert tc["done"] and tc["denied"] == "user-rejected" and tc["ok"] is False
    evs = p.parse({"type": "queue-operation", "operation": "enqueue", "timestamp": ts, "sessionId": "s1", "content": "next please"}, T)
    assert evs[0]["type"] == "Queue" and evs[0]["op"] == "enqueue"
    evs = p.parse({"type": "system", "subtype": "compact_boundary", "timestamp": ts,
                   "compactMetadata": {"trigger": "auto", "preTokens": 413819, "postTokens": 12694}}, T)
    assert evs[0]["type"] == "Compaction" and evs[0]["post_tokens"] == 12694
    evs = p.parse({"type": "system", "subtype": "turn_duration", "timestamp": ts, "durationMs": 25000}, T)
    assert evs[0]["type"] == "TurnDone" and evs[0]["duration_ms"] == 25000
    evs = p.parse({"type": "cost-state", "sessionId": "s1", "totalCostUSD": 4.2, "totalLinesAdded": 10, "totalLinesRemoved": 2,
                   "totalToolDuration": 100, "totalAPIDuration": 200, "modelUsage": {}}, T)
    assert evs[0]["type"] == "CostState" and evs[0]["cost_usd"] == 4.2 and evs[0]["lines_added"] == 10
    # feed it all into a fleet: the reducer must accept every event the adapter emits
    f = Fleet()
    f.apply({"type": "SessionSeen", "session_id": "s1", "harness": "claude_code", "cwd": "/x", "at": T})
    for e in evs:
        f.apply(e)
    assert f.sessions["s1"].cost_usd == 4.2


def test_nested_and_background_subagents():
    f = _fleet()
    s = f.sessions["s1"]
    f.apply({"type": "SubAgentSeen", "session_id": "s1", "agent_id": "p", "agent_type": "general-purpose", "at": T + 1})
    f.apply({"type": "SubAgentSeen", "session_id": "s1", "agent_id": "n", "agent_type": "Explore", "parent_agent_id": "p",
             "spawn_depth": 2, "at": T + 2})
    f.apply({"type": "SubAgentSeen", "session_id": "s1", "agent_id": "bg", "agent_type": "general-purpose", "background": True, "at": T + 3})
    assert s.subagents["n"].parent_agent_id == "p" and s.subagents["n"].spawn_depth == 2
    assert s.subagents["bg"].background and not s.subagents["p"].background
    card = cards.subagent_card(s, s.subagents["n"], T + 4, True)
    assert "nested under" in card.subtitle
    card = cards.subagent_card(s, s.subagents["bg"], T + 4, True)
    assert card.subtitle.startswith("background ")
    f.apply({"type": "StateChanged", "session_id": "s1", "state": "awaiting_user", "at": T + 5})
    assert not s.subagents["bg"].done, "a background agent outlives the parent's turn"
    line = cards.session_card(s, T + 6, True).lines
    assert any("in background" in ln for ln in line)


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
