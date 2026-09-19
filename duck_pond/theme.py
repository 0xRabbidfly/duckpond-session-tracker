"""Harness colours, model → hat mapping, redaction. Pure Python."""
from __future__ import annotations

import json
import re

RGBA = tuple[float, float, float, float]

HARNESS_COLORS = {
    "claude_code": "#D97757",
    "codex": "#F5F5F5",
    "vscode": "#F2C230",  # was VS Code blue, which disappeared into the water
    "gemini": "#5FCF80",  # was Gemini blue, same problem
    "unknown": "#9E9E9E",
}

HARNESS_LABELS = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "vscode": "VS Code",
    "gemini": "Gemini CLI",
    "unknown": "Unknown",
}

# ordered: first substring match wins
HAT_MAP = [
    ("fable", "wizard"),
    ("opus", "top_hat"),
    ("sonnet", "beret"),
    ("haiku", "kasa"),
    ("astra", "crown"),
    ("gpt", "cap"),
    ("o1", "cap"),
    ("o3", "cap"),
    ("o4", "cap"),
    ("codex", "cap"),
    ("gemini", "propeller"),
]
DEFAULT_HAT = "newspaper"

HAT_COLORS = {
    "wizard": "#4B2A7B",
    "top_hat": "#111111",
    "beret": "#C0392B",
    "kasa": "#D9B26F",
    "crown": "#C9CED6",
    "cap": "#10A37F",
    "propeller": "#3B6FE0",
    "newspaper": "#E8E4D8",
}

# The ring around a duck's neck is its context gauge: always on, colour only. Green -> yellow
# -> magenta, picked to clear two things it sits next to: the duck's own salmon body (so the
# ring never blends into it) and the state halo's teal/amber/red (so a full duck and a blocked
# duck can never be confused at a glance).
CONTEXT_RAMP = [
    (0.00, "#22C55E"),
    (0.45, "#FFE14D"),
    (0.75, "#FF7A1A"),
    (1.00, "#FF2FD0"),
]
# (fraction, label) for the on-screen key
CONTEXT_LEGEND = [(0.0, "empty"), (0.45, "half"), (0.75, "filling"), (1.0, "full")]


def context_ring_color(frac: float) -> tuple[float, float, float, float]:
    """Colour for a context fill of `frac`, interpolated along CONTEXT_RAMP."""
    f = max(0.0, min(1.0, frac))
    lo = CONTEXT_RAMP[0]
    for hi in CONTEXT_RAMP[1:]:
        if f <= hi[0]:
            span = hi[0] - lo[0]
            k = 0.0 if span <= 0 else (f - lo[0]) / span
            a, b = hex_to_rgba(lo[1]), hex_to_rgba(hi[1])
            return tuple(a[i] + (b[i] - a[i]) * k for i in range(4))
        lo = hi
    return hex_to_rgba(CONTEXT_RAMP[-1][1])


# hat -> who wears it, for the on-screen key (HAT_MAP maps several patterns to one hat)
HAT_LEGEND = [
    ("wizard", "Fable"),
    ("top_hat", "Opus"),
    ("beret", "Sonnet"),
    ("kasa", "Haiku"),
    ("cap", "GPT / Codex"),
    ("propeller", "Gemini"),
    ("newspaper", "any other model"),
]

MODEL_LABELS = [
    ("claude-fable-5-1", "Fable 5.1"),
    ("fable", "Fable"),
    ("claude-opus-5", "Opus 5"),
    ("opus", "Opus"),
    ("claude-sonnet-5", "Sonnet 5"),
    ("sonnet", "Sonnet"),
    ("haiku", "Haiku"),
    ("astra", "Astra"),
]

_unknown_models_logged = set()

# ---------------------------------------------------------------- states (glance colours)
# One colour per state, used by the beacon, the card's state bar and the name plate tint.
STATE_COLORS = {
    "generating": "#5EEAD4",          # teal: working (thinking / streaming)
    "tool_running": "#5EEAD4",        # teal too: working; the tool chip says which tool (amber read as yellow)
    "awaiting_user": "#FFC400",       # saturated yellow: your turn (pale yellow washed out on the water)
    "awaiting_permission": "#FF3B30", # red: blocked on you
    "idle": "#8A93A6",                # grey
    "ended": "#5B6270",
    "error": "#FF3B30",
}

# ---------------------------------------------------------------- tool categories
# A Bash call, a file edit, a web fetch and a test run each look different in the pool.
# (category, chip text, colour). Order matters: first match wins.
TOOL_CATEGORIES = {
    "bash":   ("bash",  "#1B1F2A"),
    "test":   ("test",  "#FF8F3F"),
    "edit":   ("edit",  "#4CD964"),
    "read":   ("read",  "#4FA3FF"),
    "web":    ("web",   "#B67CFF"),
    "browser": ("browser", "#B67CFF"),
    "agent":  ("spawn", "#F5D76E"),
    "ask":    ("ask",   "#FFD54F"),
    "plan":   ("plan",  "#9AD1D4"),
    "mcp":    ("mcp",   "#C9A0DC"),
    "other":  ("tool",  "#C8CCD2"),
}
_TEST_RE = re.compile(r"(?i)\b(pytest|vitest|jest|mocha|npm test|pnpm test|yarn test|dotnet test|go test|cargo test|"
                      r"headless_\w+\.py|test_\w+\.py|unittest|playwright test|ctest)\b")


def tool_category(name: str, summary: str = "") -> str:
    n = (name or "").lower()
    if n in ("bash", "shell", "run_command", "exec"):
        return "test" if _TEST_RE.search(summary or "") else "bash"
    if "test" in n:
        return "test"
    if n in ("edit", "write", "multiedit", "notebookedit"):
        return "edit"
    if n in ("read", "grep", "glob", "ls"):
        return "read"
    if n in ("webfetch", "websearch"):
        return "web"
    if n == "agent" or n == "workflow" or n == "sendmessage":
        return "agent"
    if n == "askuserquestion":
        return "ask"
    if n in ("enterplanmode", "exitplanmode", "taskcreate", "taskupdate", "todowrite"):
        return "plan"
    if n.startswith("mcp__"):
        return "browser" if any(k in n for k in ("chrome", "playwright", "browser", "devtools")) else "mcp"
    return "other"


def tool_chip(category: str):
    """(chip text, hex colour) for a tool category."""
    return TOOL_CATEGORIES.get(category, TOOL_CATEGORIES["other"])



def hex_to_rgba(h: str, alpha: float = 1.0) -> RGBA:
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    # sRGB -> linear so viewport colours match the hex
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (lin(r), lin(g), lin(b), alpha)


def harness_color(harness: str, overrides: dict | None = None) -> RGBA:
    table = dict(HARNESS_COLORS)
    if overrides:
        table.update(overrides)
    return hex_to_rgba(table.get(harness, table["unknown"]))


def hat_for_model(model: str, overrides: list | None = None) -> str:
    m = (model or "").lower()
    for needle, hat in (overrides or []) + HAT_MAP:
        if needle in m:
            return hat
    if m and m not in _unknown_models_logged:
        _unknown_models_logged.add(m)
        print(f"[duck_pond] no hat for model '{model}', using {DEFAULT_HAT}")
    return DEFAULT_HAT


def model_label(model: str) -> str:
    m = (model or "").lower()
    for needle, label in MODEL_LABELS:
        if needle in m:
            return label
    return model or "unknown model"


def parse_overrides(json_text: str, default):
    try:
        v = json.loads(json_text) if json_text.strip() else default
        return v
    except Exception:
        return default


# ---------------------------------------------------------------- redaction
_SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-z0-9\-_\.=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9\-_]{8,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"(?i)(AccountKey|SharedAccessSignature|sig|client_secret|api[_-]?key|password|pwd|token)\s*[=:]\s*[^;\s\"']{6,}"),
    re.compile(r"(?i)postgres(ql)?://[^\s\"']+"),
]


def redact(text: str, enabled: bool = True, limit: int = 80) -> str:
    t = " ".join((text or "").split())
    if enabled:
        for pat in _SECRET_PATTERNS:
            t = pat.sub(lambda m: m.group(0)[:4] + "••••", t)
    if limit and len(t) > limit:
        t = t[: limit - 1] + "…"
    return t
