"""API list prices, for estimating what agent usage would cost at API rates. Pure Python.

Source: the Claude API reference, prices cached 2026-06-24, in $ per million tokens. Cache writes
are priced from the input rate by TTL; fast mode doubles input and output. Update the table when
list prices change. A model that is not listed still counts in tokens but is never guessed at in
dollars (the board marks such spend `+?`).
"""
from __future__ import annotations

# (model id prefix, input, output, cache read) in $/MTok. The longest matching prefix wins, so
# dated ids (claude-haiku-4-5-20251001) match their family and claude-fable-5-1 beats claude-fable-5.
PRICES = (
    ("claude-fable-5-1", 10.0, 50.0, 0.25),
    ("claude-fable-5", 10.0, 50.0, 1.00),
    ("claude-opus-5", 5.0, 25.0, 0.50),
    ("claude-opus-4-8", 5.0, 25.0, 0.50),
    ("claude-sonnet-5", 2.0, 10.0, 0.20),
    ("claude-haiku-4-5", 1.0, 5.0, 0.10),
)
CACHE_WRITE_5M = 1.25  # × input
CACHE_WRITE_1H = 2.0   # × input
FAST = 2.0             # × input and output

_BY_LENGTH = sorted(PRICES, key=lambda p: -len(p[0]))


def rates(model: str) -> tuple[float, float, float] | None:
    m = (model or "").lower()
    for prefix, inp, out, read in _BY_LENGTH:
        if m.startswith(prefix):
            return inp, out, read
    return None


def cost(model: str, tokens_in: int = 0, cache_write_5m: int = 0, cache_write_1h: int = 0,
         cache_read: int = 0, tokens_out: int = 0, speed: str = "") -> float | None:
    """Estimated $ for one reply's usage, or None when the model has no list price."""
    r = rates(model)
    if r is None:
        return None
    inp, out, read = r
    if speed == "fast":
        inp, out = inp * FAST, out * FAST
    return (tokens_in * inp + cache_write_5m * inp * CACHE_WRITE_5M + cache_write_1h * inp * CACHE_WRITE_1H
            + cache_read * read + tokens_out * out) / 1_000_000
