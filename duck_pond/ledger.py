"""Usage ledger: every reply's tokens, priced, in per-minute buckets. Pure Python, no bpy.

The scoreboard, the lane signs and the cards read spend from here, not from the sessions still in
the pool, so a duck that leaves takes nothing with it. Rows come from live Usage events and from
the adapter's startup backfill of every transcript on disk. A reply written as several transcript
lines carries one key and is counted once.

Ranges are cut on local calendar boundaries (midnight, Monday, the 1st), computed at query time
from UTC minute buckets.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from .pricing import cost

# name -> (bars, stats label, bar unit)
RANGES = {
    "min": (60, "last 60 min", "min"),
    "hour": (24, "last 24 h", "h"),
    "day": (30, "last 30 days", "day"),
    "week": (8, "last 8 weeks", "wk"),
    "month": (6, "last 6 months", "mo"),
}
RANGE_ORDER = ("min", "hour", "day", "week", "month")

def fmt_usd(v: float) -> str:
    return f"≈${v:,.0f}" if v >= 1000 else f"≈${v:.2f}"


def fmt_tokens(n: int) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def fmt_stats(st) -> str:
    """One ledger Stats as a board line. `+?` = tokens from models with no list price."""
    return (f"{fmt_usd(st.usd)}{' +?' if st.unpriced else ''}  ·  {fmt_tokens(st.tokens_out)} out tok  ·  "
            f"{st.sessions} session{'' if st.sessions == 1 else 's'}")


_TOKEN_FIELDS = ("tokens_in", "cache_write_5m", "cache_write_1h", "cache_read", "tokens_out")


@dataclass
class Stats:
    usd: float = 0.0
    unpriced: int = 0  # tokens from models with no list price
    tokens_out: int = 0
    sessions: int = 0  # distinct session ids; sub-agent rows carry their parent's id


class UsageLedger:
    def __init__(self, tz=None) -> None:
        self.tz = tz  # None = this machine's local time; tests pass a fixed offset
        self.ready = False  # set once the startup backfill has been applied
        self.version = 0
        self._keys: set[str] = set()
        self._minutes: list[int] = []  # sorted minute epochs that hold usage
        self._buckets: dict[int, list] = {}  # minute -> [usd, unpriced, tokens_out, {session ids}]
        self._session_usd: dict[str, float] = {}
        self._cwd_usd: dict[str, dict[int, float]] = {}  # cwd -> minute -> usd
        self._memo: dict[tuple, Stats] = {}
        self._memo_version = -1

    # ------------------------------------------------------------------ writes
    def add(self, row: dict) -> bool:
        """Add one reply's usage. False when its key was already counted.

        `usd` in the row, when present, is used as is (an adapter that reports cost itself);
        otherwise the tokens are priced by model."""
        key = row.get("key") or ""
        if key:
            if key in self._keys:
                return False
            self._keys.add(key)
        tokens = [int(row.get(f) or 0) for f in _TOKEN_FIELDS]
        usd = row.get("usd")
        if usd is None:
            usd = cost(row.get("model") or "", *tokens, speed=row.get("speed") or "")
        unpriced = sum(tokens) if usd is None else 0
        usd = float(usd or 0.0)
        minute = int(float(row.get("at") or 0.0) // 60) * 60
        b = self._buckets.get(minute)
        if b is None:
            b = self._buckets[minute] = [0.0, 0, 0, set()]
            bisect.insort(self._minutes, minute)
        sid = row.get("session_id") or ""
        b[0] += usd
        b[1] += unpriced
        b[2] += tokens[4]
        b[3].add(sid)
        self._session_usd[sid] = self._session_usd.get(sid, 0.0) + usd
        per = self._cwd_usd.setdefault(row.get("cwd") or "(no cwd)", {})
        per[minute] = per.get(minute, 0.0) + usd
        self.version += 1
        return True

    # ------------------------------------------------------------------ queries
    def window(self, start: float, end: float) -> Stats:
        """Usage in minute buckets starting in [start, end)."""
        if self._memo_version != self.version:
            self._memo.clear()
            self._memo_version = self.version
        memo_key = (start, end)
        if memo_key in self._memo:
            return self._memo[memo_key]
        st = Stats()
        sessions: set[str] = set()
        lo = bisect.bisect_left(self._minutes, start)
        hi = bisect.bisect_left(self._minutes, end)
        for m in self._minutes[lo:hi]:
            usd, unpriced, out, sids = self._buckets[m]
            st.usd += usd
            st.unpriced += unpriced
            st.tokens_out += out
            sessions |= sids
        st.sessions = len(sessions)
        self._memo[memo_key] = st
        return st

    def boundaries(self, name: str, now: float) -> list[float]:
        """bars + 1 epochs, oldest first; the last one ends the bucket that holds `now`."""
        n = RANGES[name][0]
        steps = range(-(n - 1), 2)
        if name == "min":
            cur = int(now // 60) * 60
            return [float(cur + 60 * k) for k in steps]
        local = self._local(now)
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if name == "hour":
            top = local.replace(minute=0, second=0, microsecond=0)
            return [(top + timedelta(hours=k)).timestamp() for k in steps]
        if name == "day":
            return [(midnight + timedelta(days=k)).timestamp() for k in steps]
        if name == "week":
            monday = midnight - timedelta(days=local.weekday())
            return [(monday + timedelta(weeks=k)).timestamp() for k in steps]
        out = []
        for k in steps:  # calendar months
            idx = local.year * 12 + local.month - 1 + k
            out.append(midnight.replace(year=idx // 12, month=idx % 12 + 1, day=1).timestamp())
        return out

    def bars(self, name: str, now: float) -> list[float]:
        """Estimated $ per bucket for a range, oldest first."""
        bounds = self.boundaries(name, now)
        vals = [0.0] * (len(bounds) - 1)
        lo = bisect.bisect_left(self._minutes, bounds[0])
        hi = bisect.bisect_left(self._minutes, bounds[-1])
        for m in self._minutes[lo:hi]:
            vals[bisect.bisect_right(bounds, m) - 1] += self._buckets[m][0]
        return vals

    def range_stats(self, name: str, now: float) -> Stats:
        bounds = self.boundaries(name, now)
        return self.window(bounds[0], bounds[-1])

    def month_to_date(self, now: float) -> Stats:
        return self.window(self._month_start(now), int(now // 60) * 60 + 60)

    def today(self, now: float) -> Stats:
        midnight = self._local(now).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.window(midnight.timestamp(), int(now // 60) * 60 + 60)

    def month_name(self, now: float) -> str:
        return self._local(now).strftime("%B")

    def session_usd(self, session_id: str) -> float:
        return self._session_usd.get(session_id, 0.0)

    def cwd_month_usd(self, cwd: str, now: float) -> float:
        start = self._month_start(now)
        return sum(usd for m, usd in self._cwd_usd.get(cwd or "(no cwd)", {}).items() if m >= start)

    def cwd_bars(self, cwd: str, name: str, now: float) -> list[float]:
        """Estimated $ per bucket for one working directory, oldest first.

        The same cut as `bars`, one folder at a time: the fleet total is one line on the
        board, and which folder spent it when is a different question.
        """
        bounds = self.boundaries(name, now)
        vals = [0.0] * (len(bounds) - 1)
        per = self._cwd_usd.get(cwd or "(no cwd)")
        if not per:
            return vals
        for m, usd in per.items():
            if bounds[0] <= m < bounds[-1]:
                vals[bisect.bisect_right(bounds, m) - 1] += usd
        return vals

    def cwds(self) -> list[str]:
        """Every working directory the ledger has ever seen, busiest first."""
        return sorted(self._cwd_usd, key=lambda c: -sum(self._cwd_usd[c].values()))

    def sample_history(self, now: float, cwds: list[str], usd_scale: float = 1.0) -> None:
        """Fill in a plausible day of spend, one row per hour per folder.

        For screenshots and tests, which must not depend on what this machine actually did --
        the same reason `UsageLimits.set_snapshot` exists. A replayed fixture is under a minute
        long, so the mosaic it produces is one bright column and twenty-three empty ones, which
        shows the grid without showing the point of it.
        """
        # hand-written rather than random: an overnight run, a working day, and a folder that
        # barely gets touched. Indexed oldest hour first, to match `bars`.
        shapes = (
            (0, 0, 0, 0, 1.9, 2.4, 1.1, 0, 0, 0, 0, .3, .6, .2, 0, 0, 0, 0, 0, .4, 1.2, .8, .1, .5),
            (0, 0, 0, 0, 0, 0, 0, 0, .2, .9, 1.4, 1.1, .7, 1.6, 2.1, 1.3, .4, 0, 0, 0, 0, 0, 0, .2),
            (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, .1, 0, 0, 0, .3, 0, 0, 0, 0, 0, 0, .2, 0, 0),
        )
        bounds = self.boundaries("hour", now)
        for i, cwd in enumerate(cwds):
            shape = shapes[i % len(shapes)]
            for h, mult in enumerate(shape):
                if mult <= 0 or h >= len(bounds) - 1:
                    continue
                self.add({"at": bounds[h] + 90, "session_id": f"sample-{i}", "cwd": cwd,
                          "usd": mult * usd_scale, "key": f"sample-{i}-{h}"})

    # ------------------------------------------------------------------ time
    def _local(self, ts: float) -> datetime:
        return datetime.fromtimestamp(ts, self.tz)

    def _month_start(self, now: float) -> float:
        return self._local(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
