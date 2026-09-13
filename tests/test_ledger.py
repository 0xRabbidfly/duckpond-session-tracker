"""Pure-Python tests for the usage ledger and the price table (no Blender).

    python tests/test_ledger.py

Covers: list-price estimates (cache write TTLs, Fable 5.1 cache reads, fast mode, unknown
models), de-duplication by message key, windows and distinct sessions, range bars on local
calendar boundaries (midnight, Monday, the 1st), per-session and per-folder spend, and the
Claude Code adapter's startup backfill on a synthetic projects folder.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from duck_pond.adapters.claude_code import ClaudeCodeAdapter  # noqa: E402
from duck_pond.ledger import RANGE_ORDER, RANGES, UsageLedger  # noqa: E402
from duck_pond.model import Fleet  # noqa: E402
from duck_pond.pricing import cost  # noqa: E402

M = 1_000_000
TZ = timezone(timedelta(hours=-4))  # a fixed offset keeps local boundaries deterministic


def _row(at, sid="s1", model="claude-opus-5", key="", cwd="/x", agent="", **tokens):
    return {"at": at, "session_id": sid, "agent_id": agent, "cwd": cwd, "model": model, "key": key, **tokens}


def _ts(*args):
    return datetime(*args, tzinfo=TZ).timestamp()


def close(a, b):
    return abs(a - b) < 1e-9


def test_pricing():
    assert close(cost("claude-opus-5", tokens_in=M), 5.0)
    assert close(cost("claude-opus-5", tokens_out=M), 25.0)
    assert close(cost("claude-opus-5", cache_write_5m=M), 6.25)
    assert close(cost("claude-opus-5", cache_write_1h=M), 10.0)
    assert close(cost("claude-opus-5", cache_read=M), 0.5)
    assert close(cost("claude-fable-5-1", cache_read=M), 0.25), "Fable 5.1 reads cache at $0.25/MTok"
    assert close(cost("claude-fable-5", cache_read=M), 1.0), "the longer prefix must not swallow Fable 5"
    assert close(cost("claude-fable-5-1", tokens_out=M), 50.0)
    assert close(cost("claude-sonnet-5", tokens_in=M, tokens_out=M), 12.0)
    assert close(cost("claude-haiku-4-5-20251001", tokens_in=M), 1.0), "dated ids match their family"
    assert close(cost("claude-opus-4-8", tokens_in=M), 5.0)
    assert close(cost("claude-opus-5", tokens_in=M, tokens_out=M, speed="fast"), 60.0), "fast mode doubles"
    assert cost("gpt-5-codex", tokens_in=M) is None
    assert cost("<synthetic>") is None


def test_dedupe_by_key():
    led = UsageLedger(tz=TZ)
    at = _ts(2026, 9, 13, 12, 0)
    assert led.add(_row(at, key="msg_1:req_1", tokens_out=M))
    assert not led.add(_row(at + 1, key="msg_1:req_1", tokens_out=M)), "a repeated reply line is not counted"
    assert led.add(_row(at + 2, tokens_out=M)) and led.add(_row(at + 3, tokens_out=M)), "keyless rows always count"
    st = led.window(at - 60, at + 60)
    assert close(st.usd, 75.0) and st.tokens_out == 3 * M


def test_window_sessions_and_unpriced():
    led = UsageLedger(tz=TZ)
    at = _ts(2026, 9, 13, 12, 0)
    led.add(_row(at, sid="s1", tokens_in=M))
    led.add(_row(at + 5, sid="s1", agent="sub-a", model="claude-haiku-4-5", tokens_in=M))
    led.add(_row(at + 10, sid="s2", model="gpt-5-codex", tokens_in=M, tokens_out=500))
    st = led.window(at - 1, at + 60)
    assert st.sessions == 2, "a sub-agent counts toward its parent session, not as its own"
    assert close(st.usd, 6.0) and st.unpriced == M + 500 and st.tokens_out == 500
    assert led.window(at + 3600, at + 7200).sessions == 0


def test_ranges_on_local_boundaries():
    led = UsageLedger(tz=TZ)
    now = _ts(2026, 9, 1, 0, 30)          # Tuesday 1 September, 00:30 local
    before_midnight = _ts(2026, 8, 31, 23, 50)  # Monday 31 August
    after_midnight = _ts(2026, 9, 1, 0, 10)
    led.add(_row(before_midnight, sid="old", tokens_in=M))       # $5
    led.add(_row(after_midnight, sid="new", tokens_in=2 * M))    # $10
    for name in RANGE_ORDER:
        bars = led.bars(name, now)
        assert len(bars) == RANGES[name][0], f"{name}: {len(bars)} bars"
    assert close(led.bars("day", now)[-1], 10.0) and close(led.bars("day", now)[-2], 5.0), "midnight splits days"
    assert close(led.bars("hour", now)[-1], 10.0) and close(led.bars("hour", now)[-2], 5.0)
    assert close(led.bars("week", now)[-1], 15.0), "Monday 31 August starts the week holding both"
    assert close(led.bars("month", now)[-1], 10.0) and close(led.bars("month", now)[-2], 5.0), "the 1st splits months"
    assert close(sum(led.bars("min", now)), 15.0), "both are inside the last 60 minutes"
    mtd = led.month_to_date(now)
    assert close(mtd.usd, 10.0) and mtd.sessions == 1
    assert close(led.today(now).usd, 10.0)
    assert close(led.range_stats("day", now).usd, 15.0) and led.range_stats("day", now).sessions == 2
    assert led.month_name(now) == "September"
    # month arithmetic crosses the year boundary
    jan = _ts(2027, 1, 15, 12, 0)
    led.add(_row(_ts(2026, 12, 20, 9, 0), sid="dec", tokens_in=M))
    assert close(led.bars("month", jan)[-2], 5.0)


def test_session_and_cwd_spend():
    led = UsageLedger(tz=TZ)
    now = _ts(2026, 9, 13, 12, 0)
    led.add(_row(now - 60, sid="s1", cwd="/a", tokens_in=M))
    led.add(_row(now - 30, sid="s1", agent="sub", cwd="/a", model="claude-haiku-4-5", tokens_in=M))
    led.add(_row(_ts(2026, 8, 20, 12, 0), sid="s0", cwd="/a", tokens_in=M))  # last month
    led.add(_row(now - 10, sid="s2", cwd="/b", tokens_in=M))
    assert close(led.session_usd("s1"), 6.0), "a session's spend includes its sub-agents"
    assert close(led.cwd_month_usd("/a", now), 6.0) and close(led.cwd_month_usd("/b", now), 5.0)
    assert close(led.cwd_month_usd("/nowhere", now), 0.0)


def test_fleet_usage_dedupe_feeds_ledger():
    f = Fleet()
    f.apply({"type": "SessionSeen", "session_id": "s1", "harness": "claude_code", "cwd": "/x", "at": 1000.0})
    f.apply({"type": "ModelChanged", "session_id": "s1", "model": "claude-opus-5", "at": 1000.0})
    for _ in range(3):  # one reply written as three lines
        f.apply({"type": "Usage", "session_id": "s1", "tokens_in": 10, "tokens_out": M, "key": "m1:r1", "at": 1001.0})
    s = f.sessions["s1"]
    assert s.tokens_out == M and sum(tk for _, tk, _ in f.history) == M, "repeated lines are counted once"
    assert close(f.ledger.session_usd("s1"), 25.0 + 10 * 5 / M), "the ledger prices with the session's model"
    f.apply({"type": "UsageBatch", "rows": [_row(900.0, sid="gone", tokens_in=M), _row(1001.0, key="m1:r1", tokens_out=M)]})
    assert "gone" not in f.sessions, "history rows never create ducks"
    assert close(f.ledger.session_usd("gone"), 5.0) and close(f.ledger.session_usd("s1"), 25.0 + 10 * 5 / M)
    assert not f.ledger.ready
    f.apply({"type": "BackfillDone"})
    assert f.ledger.ready


def test_adapter_backfill_synthetic():
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, "Z--proj")
        os.makedirs(os.path.join(proj, "sess1", "subagents"))
        usage = {"input_tokens": 3, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 1000, "output_tokens": 50,
                 "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200}, "speed": "standard"}
        line = {"type": "assistant", "timestamp": "2026-09-13T12:00:00Z", "cwd": "Z:\\proj", "requestId": "req_1",
                "message": {"id": "msg_1", "model": "claude-opus-5", "usage": usage, "content": []}}
        with open(os.path.join(proj, "sess1.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "cwd": "Z:\\proj", "timestamp": "2026-09-13T11:59:00Z", "message": {"content": "hi"}}) + "\n")
            fh.write(json.dumps(line) + "\n")
            fh.write(json.dumps(line) + "\n")  # the same reply again
            fh.write('{"type": "assistant", "usage": broken\n')
            fh.write(json.dumps({**line, "timestamp": None}) + "\n")  # no timestamp: skipped
        sub = {**line, "requestId": "req_2", "message": {**line["message"], "id": "msg_2", "model": "claude-haiku-4-5"}}
        with open(os.path.join(proj, "sess1", "subagents", "agent-abc.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(sub) + "\n")
        evs = ClaudeCodeAdapter(d).backfill(0.0)
        assert evs and all(e["type"] == "UsageBatch" for e in evs)
        rows = [r for e in evs for r in e["rows"]]
        f = Fleet()
        for e in evs:
            f.apply(e)
        assert not f.sessions, "backfill creates no ducks"
        by_agent = {r["agent_id"]: r for r in rows}
        assert set(by_agent) == {"", "abc"} and all(r["session_id"] == "sess1" for r in rows)
        r = by_agent[""]
        assert (r["tokens_in"], r["cache_write_5m"], r["cache_write_1h"], r["cache_read"], r["tokens_out"]) == (3, 100, 200, 1000, 50)
        assert r["cwd"] == "Z:\\proj" and r["key"] == "msg_1:req_1" and r["model"] == "claude-opus-5"
        want = cost("claude-opus-5", 3, 100, 200, 1000, 50) + cost("claude-haiku-4-5", 3, 100, 200, 1000, 50)
        assert close(f.ledger.session_usd("sess1"), want), "the repeated line is counted once"


def test_adapter_live_usage_event_fields():
    from duck_pond.adapters.claude_code import _TranscriptParser
    p = _TranscriptParser("s1")
    evs = p.parse({"type": "assistant", "timestamp": "2026-09-13T12:00:00Z", "requestId": "req_9",
                   "message": {"id": "msg_9", "model": "claude-fable-5-1", "stop_reason": None, "content": [],
                               "usage": {"input_tokens": 1, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 7,
                                         "output_tokens": 5}}}, 0.0)
    u = [e for e in evs if e["type"] == "Usage"][0]
    assert u["key"] == "msg_9:req_9" and u["model"] == "claude-fable-5-1"
    assert (u["cache_write_5m"], u["cache_write_1h"], u["cache_read"]) == (40, 0, 7), "no TTL split: all 5-minute"
    assert u["tokens_in"] == 41 and u["tokens_out"] == 5 and u["context_used"] == 53


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
