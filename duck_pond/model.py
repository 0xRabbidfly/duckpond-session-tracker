"""Fleet state and the event reducer. Pure Python, no bpy — testable outside Blender."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from .ledger import UsageLedger
from .theme import tool_category

STATES = ("generating", "tool_running", "awaiting_user", "awaiting_permission", "idle", "ended", "error")
# An awaited turn older than this has gone quiet. The screen tag calls it "waiting" from here
# on, where a turn that has just finished says "your turn"; the bather waves at the first and
# not the second, so the rule lives here rather than being spelled twice.
QUIET_AFTER_S = 600.0

DEFAULT_CONTEXT_WINDOW = 200_000
BIG_CONTEXT_WINDOW = 1_000_000
# The version at which a family's window grew to 1M. Fable and Mythos only ever existed at 5+,
# so they are always big; Haiku has no 1M model yet, so it is never big. Matching has to be
# version-aware: "opus" alone is wrong, because Opus 4.5 is a 200K model and Opus 4.6 is not.
BIG_CONTEXT_FROM = {"fable": (0, 0), "mythos": (0, 0), "opus": (4, 6), "sonnet": (4, 6)}
FAMILIES = ("fable", "mythos", "opus", "sonnet", "haiku")


def model_version(model: str) -> tuple[int, int] | None:
    """(major, minor) read from a model id, or None when it does not carry one.

    Ids are read as hyphen-separated tokens so a date stamp is never mistaken for a version:
    `claude-opus-4-8` is 4.8, `claude-haiku-4-5-20251001` is 4.5, and the old-style
    `claude-3-7-sonnet-20250219`, whose digits come before the family, yields None.
    """
    tokens = re.split(r"[^a-z0-9]+", (model or "").lower())
    for i, tok in enumerate(tokens):
        if tok not in FAMILIES:
            continue
        nums = []
        for nxt in tokens[i + 1:i + 3]:
            if not (nxt.isdigit() and len(nxt) <= 2):
                break
            nums.append(int(nxt))
        if not nums:
            return None
        return (nums[0], nums[1] if len(nums) > 1 else 0)
    return None


def context_window_for(model: str) -> int:
    """The model's context window in tokens.

    Wrong values here are not cosmetic: a 1M-context session measured against a 200K window
    pins the context meter at 100 % for most of its life, which reads as "about to run out"
    when it is in fact a quarter full.
    """
    m = (model or "").lower()
    if "[1m]" in m:  # Claude Code marks the 1M-context variant of a model this way
        return BIG_CONTEXT_WINDOW
    family = next((f for f in FAMILIES if f in m), None)
    if family is None:
        return DEFAULT_CONTEXT_WINDOW
    floor = BIG_CONTEXT_FROM.get(family)
    if floor is None:  # a family with no big-context model
        return DEFAULT_CONTEXT_WINDOW
    version = model_version(m)
    if version is None:  # old-style id (claude-3-7-sonnet-...): those predate the 1M window
        return DEFAULT_CONTEXT_WINDOW
    return BIG_CONTEXT_WINDOW if version >= floor else DEFAULT_CONTEXT_WINDOW


@dataclass
class Packet:
    session_id: str
    agent_id: str
    direction: str  # down (parent->sub) | up (sub->parent)
    kind: str  # prompt | response | report | tool_result
    text: str
    at: float
    progress: float = 0.0  # runtime 0..1 along the tether
    label_shown: bool = False


@dataclass
class Agent:
    id: str
    model: str = ""
    state: str = "idle"
    state_confidence: str = "inferred"
    state_since: float = 0.0
    last_event_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    context_used: int = 0
    context_window: int = DEFAULT_CONTEXT_WINDOW
    cost_usd: float = 0.0
    turns: int = 0
    current_tool: str = ""
    current_tool_id: str = ""
    current_tool_category: str = ""
    tool_started_at: float = 0.0
    last_prompt: str = ""
    last_text: str = ""
    error_at: float = 0.0
    error_message: str = ""
    # throughput samples: (at, tokens)
    samples: deque = field(default_factory=lambda: deque(maxlen=200))
    tool_bubble_until: float = 0.0
    # --- reimagined signals
    thinking: bool = False            # the last streamed block was a thinking block
    question: str = ""                # a pending AskUserQuestion, verbatim first question
    effort: str = ""                  # low | medium | high | xhigh | max
    last_done_at: float = 0.0         # last end_turn (a finished report)
    denied_at: float = 0.0            # last tool denial
    denied_kind: str = ""             # user-rejected | permission-rule
    tool_history: deque = field(default_factory=lambda: deque(maxlen=120))  # (at, category, ok)
    tool_calls: int = 0
    tool_errors: int = 0

    @property
    def context_frac(self) -> float:
        if not self.context_window:
            return 0.0
        return max(0.0, min(1.0, self.context_used / self.context_window))

    def blocked_on_you(self) -> bool:
        """Stopped dead until you act: a question put to you, or a permission prompt.

        Not the same as a finished turn, which is merely your turn next and gets answered
        when you feel like it. Both of these have the agent sitting idle at your expense.
        """
        return self.state == "awaiting_permission" or (
            bool(self.question) and self.state == "awaiting_user")

    def waiting_quietly(self, now: float) -> bool:
        """Waiting on you long enough to have been forgotten about.

        Not a pending question (that has its own, louder signal) and not a turn that has just
        ended: those two are answered within a minute or two and are not worth flagging.
        """
        return (self.state == "awaiting_user" and not self.question
                and now - self.state_since > QUIET_AFTER_S)

    def set_state(self, state: str, at: float, confidence: str = "inferred") -> bool:
        if state not in STATES:
            return False
        changed = state != self.state
        if changed:
            self.state = state
            self.state_since = at
        self.state_confidence = confidence
        return changed

    def tokens_per_sec(self, now: float, window: float = 10.0) -> float:
        cutoff = now - window
        return sum(t for at, t in self.samples if at >= cutoff) / window

    def events_per_sec(self, now: float, window: float = 10.0) -> float:
        cutoff = now - window
        return sum(1 for at, _ in self.samples if at >= cutoff) / window

    def tools_per_min(self, now: float) -> float:
        cutoff = now - 60.0
        return float(sum(1 for at, _, _ in self.tool_history if at >= cutoff))

    def recent_tool_mix(self, now: float, window: float = 300.0) -> dict[str, int]:
        cutoff = now - window
        mix: dict[str, int] = {}
        for at, cat, _ in self.tool_history:
            if at >= cutoff:
                mix[cat] = mix.get(cat, 0) + 1
        return mix


@dataclass
class SubAgent(Agent):
    session_id: str = ""
    agent_type: str = ""
    description: str = ""
    started_at: float = 0.0
    done: bool = False
    ok: bool = True
    done_at: float = 0.0
    background: bool = False          # launched with run_in_background: outlives the parent's turn
    parent_agent_id: str = ""         # non-empty for nested sub-agents
    spawn_depth: int = 1
    packets: deque = field(default_factory=lambda: deque(maxlen=60))


TITLE_RANK = {"custom": 4, "agent": 3, "ai": 2, "prompt": 1, "": 0}


@dataclass
class Session(Agent):
    harness: str = "unknown"
    cwd: str = ""
    branch: str = ""
    title: str = ""
    title_source: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    transcript_path: str = ""
    permission_mode: str = ""         # default | acceptEdits | plan | bypassPermissions | ...
    headless: bool = False            # claude -p / Agent SDK run: done when its turn ends, never "waiting"
    queued: int = 0                   # prompts you typed that are waiting for the agent
    lines_added: int = 0
    lines_removed: int = 0
    compactions: int = 0
    last_compaction_at: float = 0.0
    tool_time_ms: int = 0
    api_time_ms: int = 0
    turn_durations: deque = field(default_factory=lambda: deque(maxlen=30))  # ms per finished turn
    model_usage: dict[str, dict] = field(default_factory=dict)
    subagents: dict[str, SubAgent] = field(default_factory=dict)

    def live_subagents(self) -> list[SubAgent]:
        return [s for s in self.subagents.values() if not s.done]

    def set_title(self, title: str, source: str) -> bool:
        title = " ".join((title or "").split())
        if not title or TITLE_RANK.get(source, 0) < TITLE_RANK.get(self.title_source, 0):
            return False
        if source == self.title_source and title == self.title:
            return False
        self.title, self.title_source = title, source
        return True

    @property
    def display_name(self) -> str:
        return self.title or self.id[:8]

    @property
    def bypass(self) -> bool:
        return self.permission_mode == "bypassPermissions"


@dataclass
class Cue:
    """Visual side-effect the scene layer consumes once."""
    kind: str  # ripple | big_ripple | error_ripple | packet | spawn | despawn | flash | prompt_drop | report_up |
    #            tool_chip | tool_done | compaction | done | denied | queued | question | title | hat
    session_id: str
    agent_id: str = ""
    payload: object = None
    at: float = 0.0  # event time; the scene skips effects for cues replayed from old history


class Fleet:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.cues: list[Cue] = []
        self.event_count = 0
        # fleet-wide output tokens per second sample (at, tokens) — drives the weather
        self.samples: deque = deque(maxlen=4000)
        # per-minute history for the scoreboard sparkline: (minute_epoch, tokens_out, tool_calls)
        self.history: deque = deque(maxlen=60)
        # priced usage by minute, fed live and by the startup backfill; outlives the sessions
        self.ledger = UsageLedger()
        # reply keys already counted into agent tokens (a reply is often several transcript lines)
        self._usage_keys: set[str] = set()

    # ------------------------------------------------------------------ queries
    def live_sessions(self) -> list[Session]:
        return [s for s in self.sessions.values() if s.state != "ended"]

    def find_agent(self, session_id: str, agent_id: str = "") -> Agent | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if agent_id:
            return s.subagents.get(agent_id)
        return s

    def tokens_per_sec(self, now: float, window: float = 20.0) -> float:
        cutoff = now - window
        return sum(t for at, t in self.samples if at >= cutoff) / window

    def totals(self, now: float) -> dict:
        live = self.live_sessions()
        subs = [a for s in live for a in s.live_subagents()]
        tpm = sum(a.tokens_per_sec(now, 60.0) for a in live + subs) * 60.0
        return {
            "ducks": len(live),
            "ducklings": len(subs),
            "active": sum(1 for a in live + subs if a.state in ("generating", "tool_running")),
            "waiting": sum(1 for a in live if a.state in ("awaiting_user", "awaiting_permission")),
            "blocked": sum(1 for a in live if a.state == "awaiting_permission"),
            "tokens_per_min": int(tpm),
            "cost_usd": sum(s.cost_usd for s in self.sessions.values()),
            "lines": sum(s.lines_added + s.lines_removed for s in self.sessions.values()),
        }

    def _bucket(self, at: float, tokens: int = 0, tools: int = 0) -> None:
        minute = int(at // 60) * 60
        if self.history and self.history[-1][0] == minute:
            m, tk, tl = self.history[-1]
            self.history[-1] = (m, tk + tokens, tl + tools)
        elif not self.history or minute > self.history[-1][0]:
            self.history.append((minute, tokens, tools))

    # ------------------------------------------------------------------ reducer
    def apply(self, ev: dict) -> None:
        self.event_count += 1
        t = ev.get("type")
        sid = ev.get("session_id", "")
        at = float(ev.get("at") or time.time())
        handler = getattr(self, f"_on_{t}", None)
        if handler is None:
            return
        n0 = len(self.cues)
        handler(ev, sid, at)
        for c in self.cues[n0:]:
            c.at = at

    def _agent(self, ev: dict, sid: str) -> Agent | None:
        return self.find_agent(sid, ev.get("agent_id", "") or "")

    def _on_SessionSeen(self, ev, sid, at):
        s = self.sessions.get(sid)
        if s is None:
            s = Session(id=sid, started_at=float(ev.get("started_at") or at), state_since=at)
            self.sessions[sid] = s
            self.cues.append(Cue("spawn", sid))
        s.harness = ev.get("harness", s.harness) or s.harness
        s.cwd = ev.get("cwd", s.cwd) or s.cwd
        s.branch = ev.get("branch", s.branch) or s.branch
        s.transcript_path = ev.get("transcript_path", s.transcript_path) or s.transcript_path
        if ev.get("model"):
            s.model = ev["model"]
            s.context_window = context_window_for(s.model)
        if ev.get("title"):
            s.set_title(ev["title"], ev.get("title_source", "custom"))
        if ev.get("permission_mode"):
            s.permission_mode = ev["permission_mode"]
        if ev.get("headless"):
            s.headless = True
        s.last_event_at = max(s.last_event_at, at)

    def _on_SessionTitle(self, ev, sid, at):
        s = self.sessions.get(sid)
        if s and s.set_title(ev.get("title", ""), ev.get("source", "ai")):
            self.cues.append(Cue("title", sid))

    def _on_PermissionMode(self, ev, sid, at):
        s = self.sessions.get(sid)
        if s:
            s.permission_mode = ev.get("mode", "") or s.permission_mode

    def _on_Effort(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a and ev.get("effort"):
            a.effort = str(ev["effort"])

    def _on_ModelChanged(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a and ev.get("model") and a.model != ev["model"]:
            a.model = ev["model"]
            a.context_window = context_window_for(a.model)
            self.cues.append(Cue("hat", sid, ev.get("agent_id", "")))

    def _on_StateChanged(self, ev, sid, at):
        a = self._agent(ev, sid)
        if not a:
            return
        prev = a.state
        a.set_state(ev["state"], at, ev.get("confidence", "inferred"))
        a.last_event_at = max(a.last_event_at, at)
        if a.state == "tool_running" and prev != "tool_running":
            self.cues.append(Cue("big_ripple", sid, ev.get("agent_id", "")))
        if prev == "tool_running" and a.state != "tool_running":
            a.current_tool = ""
            a.current_tool_id = ""
            a.current_tool_category = ""
            self.cues.append(Cue("big_ripple", sid, ev.get("agent_id", "")))
        if a.state == "awaiting_user" and prev in ("generating", "tool_running") and isinstance(a, Session):
            # a finished turn: the report goes up to you
            a.last_done_at = at
            a.thinking = False
            self.cues.append(Cue("done", sid, ""))
            self.cues.append(Cue("report_up", sid, "", a.last_text))
            if a.headless:
                self._on_SessionEnded(ev, sid, at)  # nobody is going to answer: fade out and leave
        if a.state != "awaiting_user":
            a.question = "" if a.state in ("generating", "tool_running") else a.question

    def _on_Thinking(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a:
            a.thinking = True
            a.last_event_at = max(a.last_event_at, at)

    def _on_Usage(self, ev, sid, at):
        a = self._agent(ev, sid)
        if not a:
            return
        key = ev.get("key") or ""
        if key:
            if key in self._usage_keys:
                return  # the same reply, written as another transcript line
            self._usage_keys.add(key)
        s = self.sessions.get(sid)
        cw5, cw1 = int(ev.get("cache_write_5m") or 0), int(ev.get("cache_write_1h") or 0)
        # an adapter that reports a running cost is taken at its word; the rest are priced by model
        usd = max(0.0, float(ev["cost_usd"]) - a.cost_usd) if ev.get("cost_usd") is not None else None
        self.ledger.add({
            "at": at, "session_id": sid, "agent_id": ev.get("agent_id", ""), "cwd": s.cwd if s else "",
            "model": ev.get("model") or a.model or (s.model if s else ""), "key": key,
            "tokens_in": max(0, int(ev.get("tokens_in") or 0) - cw5 - cw1), "cache_write_5m": cw5, "cache_write_1h": cw1,
            "cache_read": int(ev.get("cache_read") or 0), "tokens_out": int(ev.get("tokens_out") or 0),
            "speed": ev.get("speed") or "", "usd": usd,
        })
        a.tokens_in += int(ev.get("tokens_in") or 0)
        a.tokens_out += int(ev.get("tokens_out") or 0)
        if ev.get("context_used") is not None:
            a.context_used = int(ev["context_used"])
        if ev.get("context_window"):
            a.context_window = int(ev["context_window"])
        if ev.get("cost_usd") is not None:
            a.cost_usd = float(ev["cost_usd"])
        out = int(ev.get("tokens_out") or 0)
        a.samples.append((at, out))
        if out:
            self.samples.append((at, out))
            self._bucket(at, tokens=out)
        a.last_event_at = max(a.last_event_at, at)

    def _on_UsageBatch(self, ev, sid, at):
        for row in ev.get("rows") or []:
            self.ledger.add(row)

    def _on_BackfillDone(self, ev, sid, at):
        self.ledger.ready = True

    def _on_CostState(self, ev, sid, at):
        s = self.sessions.get(sid)
        if not s:
            return
        if ev.get("cost_usd") is not None:
            s.cost_usd = float(ev["cost_usd"])
        s.lines_added = int(ev.get("lines_added") or s.lines_added)
        s.lines_removed = int(ev.get("lines_removed") or s.lines_removed)
        s.tool_time_ms = int(ev.get("tool_time_ms") or s.tool_time_ms)
        s.api_time_ms = int(ev.get("api_time_ms") or s.api_time_ms)
        if isinstance(ev.get("model_usage"), dict):
            s.model_usage = ev["model_usage"]

    def _on_Prompt(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a:
            a.last_prompt = ev.get("text", "")[:400]
            a.last_event_at = max(a.last_event_at, at)
            a.question = ""
            if isinstance(a, Session):
                a.turns += 1
                a.queued = max(0, a.queued - 1) if a.queued else 0
                if not a.title:
                    a.set_title(a.last_prompt[:48] + ("…" if len(a.last_prompt) > 48 else ""), "prompt")
                    self.cues.append(Cue("title", sid))
                self.cues.append(Cue("prompt_drop", sid, "", a.last_prompt))

    def _on_Queue(self, ev, sid, at):
        s = self.sessions.get(sid)
        if not s:
            return
        op = ev.get("op", "enqueue")
        if op == "enqueue":
            s.queued += 1
            self.cues.append(Cue("queued", sid, "", ev.get("text", "")))
        else:
            s.queued = max(0, s.queued - 1)

    def _on_Text(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a:
            a.last_text = ev.get("text", "")[:400]
            a.thinking = False
            a.last_event_at = max(a.last_event_at, at)

    def _on_Question(self, ev, sid, at):
        a = self._agent(ev, sid)
        if a:
            a.question = ev.get("text", "")[:300]
            a.last_event_at = max(a.last_event_at, at)
            self.cues.append(Cue("question", sid, ev.get("agent_id", ""), a.question))

    def _on_Compaction(self, ev, sid, at):
        s = self.sessions.get(sid)
        if not s:
            return
        s.compactions += 1
        s.last_compaction_at = at
        if ev.get("post_tokens") is not None:
            s.context_used = int(ev["post_tokens"])
        self.cues.append(Cue("compaction", sid, "", (ev.get("pre_tokens"), ev.get("post_tokens"))))

    def _on_TurnDone(self, ev, sid, at):
        s = self.sessions.get(sid)
        if s and ev.get("duration_ms") is not None:
            s.turn_durations.append(int(ev["duration_ms"]))

    def _on_SubAgentSeen(self, ev, sid, at):
        s = self.sessions.get(sid)
        if not s:
            return
        aid = ev["agent_id"]
        sub = s.subagents.get(aid)
        if sub is None:
            sub = SubAgent(id=aid, session_id=sid, started_at=at, state="generating", state_since=at,
                           model=ev.get("model") or s.model)
            sub.context_window = context_window_for(sub.model)
            s.subagents[aid] = sub
            self.cues.append(Cue("spawn_sub", sid, aid))
        sub.agent_type = ev.get("agent_type", sub.agent_type) or sub.agent_type
        sub.description = ev.get("description", sub.description) or sub.description
        if ev.get("model"):
            sub.model = ev["model"]
        if ev.get("background"):
            sub.background = True
        if ev.get("parent_agent_id"):
            sub.parent_agent_id = ev["parent_agent_id"]
        if ev.get("spawn_depth"):
            sub.spawn_depth = int(ev["spawn_depth"])
        sub.last_event_at = max(sub.last_event_at, at)

    def _on_SubAgentDone(self, ev, sid, at):
        s = self.sessions.get(sid)
        if not s:
            return
        sub = s.subagents.get(ev["agent_id"])
        if sub is None:  # finished before we ever saw it start: record it, no spawn cue
            sub = SubAgent(id=ev["agent_id"], session_id=sid, started_at=at, model=s.model)
            s.subagents[sub.id] = sub
        if sub.done:
            return
        sub.done = True
        sub.ok = bool(ev.get("ok", True))
        sub.done_at = at
        sub.set_state("ended", at, "exact")
        if not sub.ok:
            self.cues.append(Cue("error_ripple", sid, sub.id))
        self.cues.append(Cue("despawn_sub", sid, sub.id))

    def _on_Packet(self, ev, sid, at):
        s = self.sessions.get(sid)
        sub = s.subagents.get(ev["agent_id"]) if s else None
        if not sub:
            return
        p = Packet(sid, sub.id, ev.get("direction", "down"), ev.get("kind", "prompt"), ev.get("text", "")[:400], at)
        sub.packets.append(p)
        sub.samples.append((at, max(1, len(p.text) // 4)))
        self.cues.append(Cue("packet", sid, sub.id, p))

    def _on_ToolCall(self, ev, sid, at):
        a = self._agent(ev, sid)
        if not a:
            return
        aid = ev.get("agent_id", "") or ""
        if ev.get("done"):
            cat = a.current_tool_category or tool_category(ev.get("name", ""), "")
            ok = bool(ev.get("ok", True))
            denied = ev.get("denied", "")
            if a.current_tool_id == ev.get("tool_id", a.current_tool_id):
                a.current_tool = ""
                a.current_tool_id = ""
                a.current_tool_category = ""
            a.tool_history.append((at, cat, ok))
            if not ok:
                a.tool_errors += 1
            if denied:
                a.denied_at = at
                a.denied_kind = denied
                self.cues.append(Cue("denied", sid, aid, denied))
                # a rejected tool means the agent stops and waits for you
                a.set_state("awaiting_user", at, "exact")
            else:
                a.set_state("generating", at, ev.get("confidence", "inferred"))
            self.cues.append(Cue("tool_done", sid, aid, (cat, ok)))
            self._bucket(at, tools=1)
        else:
            name = ev.get("name", "?")
            summary = ev.get("summary", "")
            cat = tool_category(name, summary)
            a.current_tool = f"{name} — {summary}"[:200]
            a.current_tool_id = ev.get("tool_id", "")
            a.current_tool_category = cat
            a.tool_started_at = at
            a.tool_bubble_until = at + 1.5
            a.tool_calls += 1
            a.thinking = False
            prev = a.state
            if cat == "ask":
                a.question = summary[:300]
                a.set_state("awaiting_user", at, "exact")
                self.cues.append(Cue("question", sid, aid, a.question))
            else:
                a.set_state("tool_running", at, ev.get("confidence", "inferred"))
                if prev != "tool_running":
                    self.cues.append(Cue("big_ripple", sid, aid))
            self.cues.append(Cue("tool_chip", sid, aid, cat))
        a.last_event_at = max(a.last_event_at, at)

    def _on_Error(self, ev, sid, at):
        a = self._agent(ev, sid)
        if not a:
            return
        a.error_at = at
        a.error_message = ev.get("message", "")[:200]
        self.cues.append(Cue("error_ripple", sid, ev.get("agent_id", "")))

    def _on_SessionEnded(self, ev, sid, at):
        s = self.sessions.get(sid)
        if s and s.state != "ended":
            s.set_state("ended", at, "inferred")
            s.ended_at = at
            for sub in s.subagents.values():
                if not sub.done:
                    sub.done = True
                    sub.done_at = at
                    self.cues.append(Cue("despawn_sub", sid, sub.id))

    # ------------------------------------------------------------------ housekeeping
    def housekeeping(self, now: float, idle_after: float, end_after: float, remove_after: float,
                     permission_after: float = 12.0) -> None:
        """Derive idle/ended/awaiting_permission from silence; drop ducks that finished fading."""
        for sid in list(self.sessions):
            s = self.sessions[sid]
            if s.state == "ended":
                if now - s.ended_at > remove_after:
                    self.cues.append(Cue("despawn", sid))
                    del self.sessions[sid]
                continue
            silence = now - s.last_event_at if s.last_event_at else 0
            if s.last_event_at and silence > end_after:
                self.apply({"type": "SessionEnded", "session_id": sid, "at": now})
                continue
            if s.state in ("generating", "tool_running") and silence > idle_after:
                s.set_state("idle", now, "inferred")
            # A tool call that has produced no result for a while in a session that is NOT in
            # bypass mode is, in practice, a permission prompt you have not answered yet. Long
            # Bash runs and sub-agent spawns are exempt: they legitimately take a while.
            if (s.state == "tool_running" and not s.bypass and s.permission_mode
                    and s.current_tool_category not in ("bash", "test", "agent", "browser", "mcp", "web")
                    and s.tool_started_at and now - s.tool_started_at > permission_after):
                s.set_state("awaiting_permission", now, "inferred")
            for sub in s.subagents.values():
                if not sub.done and sub.state in ("generating", "tool_running") and now - sub.last_event_at > idle_after:
                    sub.set_state("idle", now, "inferred")
        self._bucket(now)

    def drain_cues(self) -> list[Cue]:
        out, self.cues = self.cues, []
        return out
