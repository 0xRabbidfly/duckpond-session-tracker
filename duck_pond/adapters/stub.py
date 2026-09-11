"""Stub adapter — replays a JSON fixture of events with relative timestamps, looping.

Fixture format:
{
  "loop_seconds": 60,
  "events": [ {"t": 0.0, "type": "SessionSeen", "session_id": "...", ...}, ... ]
}
Each event's "t" is seconds after the adapter started (per loop). Sessions are re-created
each loop with a suffix so ducks come and go.
"""
from __future__ import annotations

import copy
import json
import time

from .base import Adapter


class StubAdapter(Adapter):
    name = "stub"

    def __init__(self, fixture_path: str, loop: bool = True, speed: float = 1.0) -> None:
        with open(fixture_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.events = sorted(data.get("events", []), key=lambda e: e.get("t", 0.0))
        self.loop_seconds = float(data.get("loop_seconds", 60.0))
        self.loop = loop
        self.speed = speed
        self.started = time.time()
        self.cursor = 0
        self.iteration = 0
        self.fixture_path = fixture_path

    def describe(self) -> str:
        return f"stub ({self.fixture_path})"

    def _suffix(self, sid: str) -> str:
        return sid if self.iteration == 0 else f"{sid}-{self.iteration}"

    def poll(self, now: float) -> list[dict]:
        out: list[dict] = []
        elapsed = (now - self.started) * self.speed
        while self.cursor < len(self.events) and self.events[self.cursor].get("t", 0.0) <= elapsed:
            ev = copy.deepcopy(self.events[self.cursor])
            t = ev.pop("t", 0.0)
            ev["at"] = self.started + t / self.speed
            if "session_id" in ev:
                ev["session_id"] = self._suffix(ev["session_id"])
            out.append(ev)
            self.cursor += 1
        if self.cursor >= len(self.events) and self.loop and elapsed >= self.loop_seconds:
            self.started = now
            self.cursor = 0
            self.iteration += 1
        return out
