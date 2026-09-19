"""Text and structure for hover cards, name tags and the panel. Pure formatting, no drawing.

Three levels of attention, decided here once so every surface agrees:
  glance  — the duck itself: motion, beacon colour, chips, the big name tag
  hover   — the card: who, state, what it is doing right now, how full, how much
  click   — the pinned panel: history, sub-agents, packets, per-model spend
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..model import Fleet, Session, SubAgent
from ..theme import HARNESS_LABELS, STATE_COLORS, hex_to_rgba, model_label, redact, tool_chip

STATE_LABELS = {
    "generating": "generating",
    "tool_running": "running a tool",
    "awaiting_user": "waiting for you",
    "awaiting_permission": "BLOCKED: needs permission",
    "idle": "idle",
    "ended": "ended",
    "error": "error",
}


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def fmt_elapsed(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} m"
    if m:
        return f"{m} m {s:02d} s"
    return f"{s} s"


def state_rgba(state: str) -> tuple[float, float, float, float]:
    return hex_to_rgba(STATE_COLORS.get(state, "#8A93A6"))


@dataclass
class Card:
    title: str
    state: str
    state_text: str
    subtitle: str = ""
    lines: list[str] = field(default_factory=list)
    context_frac: float = 0.0
    context_text: str = ""
    highlight: str = ""            # a question or a denial, drawn in the state colour
    tool_mix: list[tuple[str, int, str]] = field(default_factory=list)  # (chip text, count, hex)
    inferred: bool = False


def _state_text(agent, now: float) -> str:
    conf = "" if agent.state_confidence == "exact" else " (inferred)"
    label = STATE_LABELS.get(agent.state, agent.state)
    if agent.state == "awaiting_user" and now - agent.state_since > 600 and not agent.question:
        label = "waiting for you (quiet)"
    return f"{label}{conf} · {fmt_elapsed(now - agent.state_since)}"


def _mix(agent, now: float) -> list[tuple[str, int, str]]:
    mix = agent.recent_tool_mix(now, 600.0)
    out = []
    for cat, n in sorted(mix.items(), key=lambda kv: -kv[1])[:6]:
        text, hexc = tool_chip(cat)
        out.append((text, n, hexc))
    return out


def session_card(s: Session, now: float, redact_on: bool, usd: float | None = None) -> Card:
    """`usd` is the ledger's estimate for the session (sub-agents included); the recorded
    cost-state total, when Claude Code wrote one, is shown beside it."""
    folder = (s.cwd or "").replace(chr(92), "/").rstrip("/").split("/")[-1] or "(no cwd)"
    card = Card(
        title=redact(s.display_name, redact_on, 60),
        state=s.state,
        state_text=_state_text(s, now),
        subtitle=f"{HARNESS_LABELS.get(s.harness, s.harness)} · {model_label(s.model)}"
                 f"{' · effort ' + s.effort if s.effort else ''} · {folder} · {s.branch or '-'}",
        context_frac=s.context_frac,
        context_text=f"context {int(s.context_frac * 100)} % of {fmt_tokens(s.context_window)}"
                     f"{' · compacted ×' + str(s.compactions) if s.compactions else ''}",
        inferred=s.state_confidence != "exact",
    )
    lines = card.lines
    if usd is None:
        spend = f"${s.cost_usd:.2f}"
    else:
        spend = f"≈${usd:.2f}" + (f" · recorded ${s.cost_usd:.2f}" if s.cost_usd else "")
    lines.append(f"turns {s.turns} · tokens {fmt_tokens(s.tokens_in)} in / {fmt_tokens(s.tokens_out)} out · "
                 f"{spend}" + (f" · +{s.lines_added} −{s.lines_removed} lines" if s.lines_added or s.lines_removed else ""))
    if s.current_tool:
        lines.append("now: " + redact(s.current_tool, redact_on, 90))
    elif s.thinking and s.state == "generating":
        lines.append("now: thinking…")
    if s.question:
        card.highlight = "asks: “" + redact(s.question, redact_on, 110) + "”"
    elif s.denied_at and now - s.denied_at < 300:
        card.highlight = "you " + ("rejected" if s.denied_kind == "user-rejected" else "have a rule that blocked") + " its last tool call"
    if s.last_prompt:
        lines.append("you said: “" + redact(s.last_prompt, redact_on, 90) + "”")
    if s.last_text and s.state in ("awaiting_user", "idle"):
        lines.append("it said: “" + redact(s.last_text, redact_on, 90) + "”")
    running = len(s.live_subagents())
    done = len(s.subagents) - running
    if s.subagents:
        bg = sum(1 for a in s.subagents.values() if a.background and not a.done)
        lines.append(f"sub-agents: {running} running{f' ({bg} in background)' if bg else ''} · {done} done")
    if s.queued:
        lines.append(f"{s.queued} prompt{'s' if s.queued > 1 else ''} queued behind this turn")
    if s.error_message and now - s.error_at < 120:
        lines.append("error: " + redact(s.error_message, redact_on, 80))
    extras = []
    if s.permission_mode:
        extras.append({"bypassPermissions": "bypass permissions", "acceptEdits": "accept edits", "plan": "plan mode",
                       "default": "asks before tools"}.get(s.permission_mode, s.permission_mode))
    if s.started_at:
        extras.append(f"started {fmt_elapsed(now - s.started_at)} ago")
    if s.turn_durations:
        extras.append(f"last turn {fmt_elapsed(s.turn_durations[-1] / 1000.0)}")
    if extras:
        lines.append(" · ".join(extras))
    card.tool_mix = _mix(s, now)
    return card


def subagent_card(s: Session, sub: SubAgent, now: float, redact_on: bool) -> Card:
    label = sub.agent_type or "sub-agent"
    kind = "background " if sub.background else ""
    nest = f" · nested under {sub.parent_agent_id[:8]} (depth {sub.spawn_depth})" if sub.parent_agent_id else ""
    card = Card(
        title=redact(sub.description or label, redact_on, 60),
        state=sub.state if not sub.done else "ended",
        state_text=_state_text(sub, now) if not sub.done else f"finished {'ok' if sub.ok else 'with error'} {fmt_elapsed(now - sub.done_at)} ago",
        subtitle=f"{kind}{label} · {model_label(sub.model or s.model)} · under {redact(s.display_name, redact_on, 30)}{nest}",
        context_frac=sub.context_frac,
        context_text=f"context {int(sub.context_frac * 100)} %",
        inferred=sub.state_confidence != "exact",
    )
    card.lines.append(f"tokens {fmt_tokens(sub.tokens_in)} in / {fmt_tokens(sub.tokens_out)} out · {len(sub.packets)} packets · "
                      f"{sub.tokens_per_sec(now):.0f} tok/s")
    if sub.current_tool:
        card.lines.append("now: " + redact(sub.current_tool, redact_on, 90))
    if sub.last_text:
        card.lines.append("it said: “" + redact(sub.last_text, redact_on, 90) + "”")
    card.tool_mix = _mix(sub, now)
    return card


def tether_card(s: Session, sub: SubAgent, now: float, redact_on: bool) -> Card:
    card = Card(
        title=f"{redact(s.display_name, redact_on, 24)} ⇄ {redact(sub.description or sub.agent_type or sub.id[:8], redact_on, 24)}",
        state=sub.state if not sub.done else "ended",
        state_text=f"{sub.tokens_per_sec(now):.0f} tok/s on the link",
        subtitle="last packets, newest last",
    )
    for p in list(sub.packets)[-5:]:
        arrow = "↓" if p.direction == "down" else "↑"
        card.lines.append(f"{arrow} {time.strftime('%H:%M:%S', time.localtime(p.at))} {p.kind}: {redact(p.text, redact_on, 70)}")
    return card


def card_for(fleet: Fleet, kind: str, key: tuple[str, str] | None, now: float, redact_on: bool) -> Card | None:
    if not key:
        return None
    sid, aid = key
    s = fleet.sessions.get(sid)
    if not s:
        return None
    if kind in ("duck", "hat", "label") and not aid:
        return session_card(s, now, redact_on, fleet.ledger.session_usd(sid))
    sub = s.subagents.get(aid)
    if not sub:
        return session_card(s, now, redact_on, fleet.ledger.session_usd(sid))
    if kind == "tether":
        return tether_card(s, sub, now, redact_on)
    return subagent_card(s, sub, now, redact_on)


# ---------------------------------------------------------------- compatibility helpers
def lines_for(fleet: Fleet, kind: str, key, now: float, redact_on: bool) -> list[str]:
    c = card_for(fleet, kind, key, now, redact_on)
    if c is None:
        return []
    out = [f"{c.title}    {c.state_text}", c.subtitle, c.context_text] if c.context_text else [f"{c.title}    {c.state_text}", c.subtitle]
    if c.highlight:
        out.append(c.highlight)
    return out + c.lines


def name_for(fleet: Fleet, key: tuple[str, str] | None, redact_on: bool) -> str:
    """The display name alone, for the big floating tag over a duck."""
    if not key:
        return ""
    sid, aid = key
    s = fleet.sessions.get(sid)
    if not s:
        return ""
    if aid:
        sub = s.subagents.get(aid)
        if sub:
            return redact(sub.description or sub.agent_type or sub.id[:8], redact_on, 48)
    return redact(s.display_name, redact_on, 48)


def tag_for(fleet: Fleet, key: tuple[str, str], now: float, redact_on: bool) -> tuple[str, str, str]:
    """(name, one-word status, state) for the always-on screen tags in kiosk mode."""
    sid, aid = key
    s = fleet.sessions.get(sid)
    if not s:
        return "", "", "idle"
    a = s.subagents.get(aid) if aid else s
    if a is None:
        return "", "", "idle"
    if a.state == "tool_running" and a.current_tool_category:
        status = tool_chip(a.current_tool_category)[0]
    elif a.state == "generating":
        status = "thinking" if a.thinking else "writing"
    elif a.state == "awaiting_user":
        status = "asking you" if a.question else ("waiting" if now - a.state_since > 600 else "your turn")
    elif a.state == "awaiting_permission":
        status = "needs permission"
    else:
        status = STATE_LABELS.get(a.state, a.state)
    return name_for(fleet, key, redact_on), status, a.state


def status_segments(fleet: Fleet, now: float) -> list[tuple[str, str]]:
    """(text, state) for the live pool status, one segment per state so each can be drawn in
    its own colour. Lives here, not on the board, because it is now drawn in screen space:
    a duck's name tag used to sit on top of it for minutes at a time."""
    t = fleet.totals(now)
    if not t["ducks"]:
        return [("POOL IS EMPTY", "idle")]
    # totals() counts a blocked duck under "waiting" as well, so take it out of that bucket:
    # these segments are read as a breakdown and should add up to the number of ducks.
    waiting = max(0, t["waiting"] - t["blocked"])
    idle = t["ducks"] - t["active"] - t["waiting"]
    out = [(f"{t['active']} WORKING", "generating"), (f"{waiting} WAITING", "awaiting_user")]
    if t["blocked"]:
        out.append((f"{t['blocked']} BLOCKED", "awaiting_permission"))
    if idle > 0:
        out.append((f"{idle} IDLE", "idle"))
    return out


TOTALS_SCOPE = "WHOLE POOL"  # the footer sits under a card about one duck; say what it counts


def totals_line(fleet: Fleet, now: float) -> str:
    """The pond-wide tally drawn under the card. It is deliberately labelled and worded so it
    cannot be read as belonging to the duck above it: every count names what it counts."""
    t = fleet.totals(now)
    blocked = f" · {t['blocked']} blocked" if t["blocked"] else ""
    return (f"{TOTALS_SCOPE}  ·  {plural(t['ducks'], 'duck')} · {plural(t['ducklings'], 'duckling')} · "
            f"{t['active']} of them active · {t['waiting']} waiting{blocked} · "
            f"{fmt_tokens(t['tokens_per_min'])} tok/min · ≈${fleet.ledger.today(now).usd:.2f} today")
