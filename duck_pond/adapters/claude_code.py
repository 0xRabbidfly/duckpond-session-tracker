"""Claude Code adapter — tails ~/.claude/projects/<slug>/<session>.jsonl and its subagents/ folder.

Verified against the on-disk layout on 2026-09-10 (SPEC §8.1):
  * session lines carry cwd, gitBranch, sessionId, timestamp, message.model, message.usage
  * <session>/subagents/agent-<id>.jsonl (+ .meta.json {agentType, description, toolUseId})
  * sub-agent lines are isSidechain: true with agentId
  * the parent's tool_result for the Agent call has toolUseResult {agentId, status, resolvedModel, ...}
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime

from .base import Adapter, FileTail, excerpt, tool_summary

HARNESS = "claude_code"
SEEN_REFRESH_S = 60.0  # re-emit SessionSeen so a session that went quiet and was dropped comes back
_TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
_TASK_STATUS = re.compile(r"<status>([^<]+)</status>")
_TASK_SUMMARY = re.compile(r"<summary>([^<]*)</summary>", re.S)
_NON_PROMPT_PREFIXES = ("<task-notification>", "<system-reminder>", "<local-command", "<command-name>")


def _ts(o: dict, fallback: float) -> float:
    ts = o.get("timestamp")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def _first_line_ts(path: str) -> float:
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    return _ts(json.loads(raw.decode("utf-8", "replace")), 0.0)
    except (OSError, ValueError):
        pass
    return 0.0


def _usage_event(sid: str, aid: str, usage: dict, at: float) -> dict:
    inp = int(usage.get("input_tokens") or 0)
    cc = int(usage.get("cache_creation_input_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    return {
        "type": "Usage", "session_id": sid, "agent_id": aid, "at": at,
        "tokens_in": inp + cc, "tokens_out": out, "context_used": inp + cc + cr + out,
    }


class _TranscriptParser:
    """Turns one JSONL stream (session or sub-agent) into events. Stateful per file."""

    def __init__(self, session_id: str, agent_id: str = "") -> None:
        self.sid = session_id
        self.aid = agent_id
        self.model = ""
        self.open_tools: dict[str, dict] = {}  # tool_use_id -> {name, input}
        self.agent_tool_uses: dict[str, dict] = {}  # tool_use_id -> Agent input
        self.last_at = 0.0
        self.effort = ""

    def parse(self, o: dict, now: float) -> list[dict]:
        ev: list[dict] = []
        t = o.get("type")
        at = _ts(o, now)
        self.last_at = max(self.last_at, at)
        base = {"session_id": self.sid, "agent_id": self.aid, "at": at}
        msg = o.get("message")

        if t == "assistant" and isinstance(msg, dict):
            model = msg.get("model") or ""
            if model and not model.startswith("<") and model != self.model:
                self.model = model
                ev.append({"type": "ModelChanged", "model": model, **base})
            if isinstance(msg.get("usage"), dict):
                ev.append(_usage_event(self.sid, self.aid, msg["usage"], at))
            if o.get("effort") and o.get("effort") != self.effort:
                self.effort = str(o["effort"])
                ev.append({"type": "Effort", "effort": self.effort, **base})
            if o.get("isApiErrorMessage"):
                ev.append({"type": "Error", "message": excerpt(msg.get("content"), 200), **base})
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type")
                    if bt == "thinking":
                        ev.append({"type": "Thinking", **base})
                    elif bt == "tool_use":
                        name = block.get("name", "?")
                        tid = block.get("id", "")
                        inp = block.get("input") or {}
                        self.open_tools[tid] = {"name": name, "input": inp}
                        if name == "Agent":
                            self.agent_tool_uses[tid] = inp
                        summary = tool_summary(name, inp)
                        if name == "AskUserQuestion":
                            qs = inp.get("questions") or []
                            if qs and isinstance(qs[0], dict):
                                summary = excerpt(qs[0].get("question", ""), 200)
                        ev.append({"type": "ToolCall", "name": name, "tool_id": tid,
                                   "summary": summary, "done": False, **base})
                    elif bt == "text" and block.get("text"):
                        ev.append({"type": "Text", "text": excerpt(block["text"]), **base})
                        if self.aid:  # sub-agent talking -> packet up to the parent
                            ev.append({"type": "Packet", "direction": "up", "kind": "response",
                                       "text": excerpt(block["text"]), **base})
            stop = msg.get("stop_reason")
            if stop == "end_turn" and self.aid:
                # a sub-agent's final answer is its completion (background agents never get a
                # parent tool_result; sync ones get it in the same instant, and Done is idempotent)
                ev.append({"type": "SubAgentDone", "ok": True, **base})
            elif stop == "end_turn":
                ev.append({"type": "StateChanged", "state": "awaiting_user", **base})
            elif stop == "tool_use" or any(b.get("type") == "tool_use" for b in (content or []) if isinstance(b, dict)):
                ev.append({"type": "StateChanged", "state": "tool_running", **base})
            elif stop is None:
                ev.append({"type": "StateChanged", "state": "generating", **base})

        elif t == "permission-mode" and not self.aid:
            ev.append({"type": "PermissionMode", "mode": str(o.get("permissionMode") or ""), **base})

        elif t == "queue-operation" and not self.aid:
            op = o.get("operation", "")
            if op in ("enqueue", "dequeue", "remove"):
                ev.append({"type": "Queue", "op": op, "text": excerpt(o.get("content", ""), 120), **base})

        elif t == "cost-state" and not self.aid:
            ev.append({"type": "CostState", "cost_usd": o.get("totalCostUSD"),
                       "lines_added": o.get("totalLinesAdded"), "lines_removed": o.get("totalLinesRemoved"),
                       "tool_time_ms": o.get("totalToolDuration"), "api_time_ms": o.get("totalAPIDuration"),
                       "model_usage": o.get("modelUsage"), **base})

        elif t == "system":
            sub = o.get("subtype")
            if sub == "compact_boundary":
                cm = o.get("compactMetadata") or {}
                ev.append({"type": "Compaction", "pre_tokens": cm.get("preTokens"), "post_tokens": cm.get("postTokens"),
                           "trigger": cm.get("trigger", ""), **base})
            elif sub == "turn_duration" and not self.aid:
                ev.append({"type": "TurnDone", "duration_ms": o.get("durationMs"), **base})

        elif t in ("custom-title", "agent-name", "ai-title") and not self.aid:
            title = o.get("customTitle") or o.get("agentName") or o.get("aiTitle") or ""
            source = {"custom-title": "custom", "agent-name": "agent", "ai-title": "ai"}[t]
            if title:
                ev.append({"type": "SessionTitle", "title": str(title), "source": source, **base})

        elif t == "user" and isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                ev.extend(self._user_text(content, o, base))
            elif isinstance(content, list):
                had_result = False
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        had_result = True
                        tid = block.get("tool_use_id", "")
                        info = self.open_tools.pop(tid, {"name": "?"})
                        denied = str(o.get("toolDenialKind") or "")
                        ok = not bool(block.get("is_error")) and not denied
                        ev.append({"type": "ToolCall", "name": info["name"], "tool_id": tid, "done": True,
                                   "ok": ok, "denied": denied, **base})
                        tur = o.get("toolUseResult")
                        if isinstance(tur, dict) and tur.get("agentId"):
                            aid = tur["agentId"]
                            if tur.get("isAsync") or tur.get("status") == "async_launched":
                                # background agent: this is only the launch acknowledgement
                                inp = self.agent_tool_uses.get(tid, {})
                                ev.append({"type": "SubAgentSeen", "session_id": self.sid, "agent_id": aid, "at": at,
                                           "agent_type": tur.get("agentType") or inp.get("subagent_type", ""),
                                           "description": tur.get("description") or inp.get("description", ""),
                                           "model": tur.get("resolvedModel") or inp.get("model", "") or "",
                                           "background": True})
                            else:
                                ok = tur.get("status") in (None, "completed", "success", "ok")
                                ev.append({"type": "Packet", "direction": "up", "kind": "report",
                                           "text": excerpt(tur.get("content") or block.get("content")),
                                           "session_id": self.sid, "agent_id": aid, "at": at})
                                ev.append({"type": "SubAgentDone", "ok": ok, "session_id": self.sid,
                                           "agent_id": aid, "at": at})
                    elif block.get("type") == "text" and block.get("text"):
                        ev.extend(self._user_text(block["text"], o, base, state=False))
                if had_result or not o.get("isMeta"):
                    ev.append({"type": "StateChanged", "state": "generating", **base})
        return ev


    def _user_text(self, text: str, o: dict, base: dict, state: bool = True) -> list[dict]:
        ev: list[dict] = []
        stripped = text.strip()
        if not stripped:
            return ev
        if stripped.startswith("<task-notification>"):
            m = _TASK_ID.search(stripped)
            if m and not self.aid:
                aid = m.group(1).strip()
                st = _TASK_STATUS.search(stripped)
                status = st.group(1) if st else "completed"
                summ = _TASK_SUMMARY.search(stripped)
                ev.append({"type": "Packet", "direction": "up", "kind": "report",
                           "text": excerpt(summ.group(1) if summ else stripped),
                           "session_id": self.sid, "agent_id": aid, "at": base["at"]})
                ev.append({"type": "SubAgentDone", "ok": status.strip().lower() in ("completed", "ok", "success"),
                           "session_id": self.sid, "agent_id": aid, "at": base["at"]})
            if state:
                ev.append({"type": "StateChanged", "state": "generating", **base})
            return ev
        if not o.get("isMeta") and not stripped.startswith(_NON_PROMPT_PREFIXES):
            ev.append({"type": "Prompt", "text": excerpt(stripped), **base})
        if state:
            ev.append({"type": "StateChanged", "state": "generating", **base})
        return ev


class ClaudeCodeAdapter(Adapter):
    name = "claude_code"

    def __init__(self, projects_dir: str | None = None, live_window_s: float = 600.0,
                 replay_all: bool = False) -> None:
        self.projects_dir = projects_dir or os.path.join(os.path.expanduser("~"), ".claude", "projects")
        self.live_window_s = live_window_s
        self.replay_all = replay_all  # test mode: read every transcript regardless of age
        self.tails: dict[str, FileTail] = {}
        self.parsers: dict[str, _TranscriptParser] = {}
        self.seen_sessions: set = set()
        self.seen_emit_at: dict[str, float] = {}
        self.seen_subagents: set = set()
        self.session_meta: dict[str, dict] = {}
        self.sub_tool_use: dict[str, str] = {}  # toolUseId -> agentId
        self.last_scan = 0.0

    def describe(self) -> str:
        return f"claude_code ({self.projects_dir})"

    # ------------------------------------------------------------ discovery
    def _discover(self, now: float) -> list[str]:
        pattern = os.path.join(self.projects_dir, "*", "*.jsonl")
        out = []
        for path in glob.glob(pattern):
            try:
                mt = os.path.getmtime(path)
            except OSError:
                continue
            if self.replay_all or now - mt <= self.live_window_s:
                out.append(path)
        return out

    def _subagent_files(self, session_path: str) -> list[str]:
        d = os.path.join(os.path.splitext(session_path)[0], "subagents")
        if not os.path.isdir(d):
            return []
        return sorted(glob.glob(os.path.join(d, "agent-*.jsonl")))

    # ------------------------------------------------------------ polling
    def poll(self, now: float) -> list[dict]:
        events: list[dict] = []
        if now - self.last_scan >= 2.0 or not self.tails:
            self.last_scan = now
            for path in self._discover(now):
                if path not in self.tails:
                    sid = os.path.splitext(os.path.basename(path))[0]
                    self.tails[path] = FileTail(path)
                    self.parsers[path] = _TranscriptParser(sid)
                    self.session_meta[path] = {"sid": sid}
        for path, tail in list(self.tails.items()):
            parser = self.parsers[path]
            meta = self.session_meta[path]
            sid = meta["sid"]
            for o in tail.new_lines():
                if o.get("cwd") and (sid not in self.seen_sessions or now - self.seen_emit_at.get(sid, 0.0) > SEEN_REFRESH_S):
                    self.seen_sessions.add(sid)
                    self.seen_emit_at[sid] = now
                    events.append({
                        "type": "SessionSeen", "session_id": sid, "harness": HARNESS,
                        "cwd": o.get("cwd", ""), "branch": o.get("gitBranch", ""),
                        "started_at": _ts(o, now), "at": _ts(o, now), "transcript_path": path,
                    })
                if sid in self.seen_sessions:
                    events.extend(parser.parse(o, now))
            if sid not in self.seen_sessions:
                continue
            # sub-agents
            for spath in self._subagent_files(path):
                if spath not in self.tails:
                    aid = os.path.basename(spath)[len("agent-"):-len(".jsonl")]
                    self.tails[spath] = FileTail(spath)
                    self.parsers[spath] = _TranscriptParser(sid, aid)
                    self.session_meta[spath] = {"sid": sid, "aid": aid, "sub": True}
                    agent_type, description, prompt, model = "", "", "", ""
                    parent_agent, depth, background = "", 1, False
                    try:
                        with open(spath[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as fh:
                            m = json.load(fh)
                        agent_type = m.get("agentType", "")
                        description = m.get("description", "")
                        parent_agent = m.get("parentAgentId", "") or ""
                        depth = int(m.get("spawnDepth") or 1)
                        inp = parser.agent_tool_uses.get(m.get("toolUseId", ""), {})
                        prompt = excerpt(inp.get("prompt", ""))
                        model = inp.get("model", "") or ""
                        background = bool(inp.get("run_in_background"))
                    except (OSError, ValueError):
                        pass
                    started = _first_line_ts(spath) or self.tails[spath].mtime() or now
                    events.append({"type": "SubAgentSeen", "session_id": sid, "agent_id": aid, "at": started,
                                   "agent_type": agent_type, "description": description, "model": model,
                                   "parent_agent_id": parent_agent, "spawn_depth": depth, "background": background})
                    if prompt:
                        events.append({"type": "Packet", "session_id": sid, "agent_id": aid, "at": started,
                                       "direction": "down", "kind": "prompt", "text": prompt})
        # drain sub-agent tails (they were added to self.tails above; second pass keeps ordering simple)
        for spath, meta in list(self.session_meta.items()):
            if not meta.get("sub"):
                continue
            for o in self.tails[spath].new_lines():
                events.extend(self.parsers[spath].parse(o, now))
        events.sort(key=lambda e: e.get("at", 0.0))
        return events
