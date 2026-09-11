"""Optional sound cues, synthesised with Blender's `aud` module (no files to ship).

Off by default. Every cue is a short sine with a soft envelope, so the pool sounds like a
quiet lido rather than a pager: prompt = low bloop, done = two-note chime, question = ding,
error = short buzz, geyser = a rising whoosh, tests pass/fail = up / down pair.
"""
from __future__ import annotations

import time

try:
    import aud
except ImportError:  # pragma: no cover - headless builds may lack audio
    aud = None

MIN_GAP_S = 0.12  # never stack cues closer than this


def _tone(freq: float, dur: float, vol: float = 0.25):
    s = aud.Sound.sine(freq, 44100).limit(0, dur).fadein(0, 0.01).fadeout(max(0.0, dur - 0.08), 0.08)
    return s.volume(vol)


def _seq(*parts):
    out = parts[0]
    for p in parts[1:]:
        out = out.join(p)
    return out


class Sound:
    def __init__(self) -> None:
        self.enabled = aud is not None
        self.device = None
        self.cache: dict[str, object] = {}
        self.last_at: dict[str, float] = {}
        self.muted_until = 0.0
        if self.enabled:
            try:
                self.device = aud.Device()
            except Exception:  # noqa: BLE001
                self.enabled = False

    def _build(self, name: str):
        if name == "prompt":
            return _tone(220, 0.14, 0.3)
        if name == "done":
            return _seq(_tone(660, 0.09, 0.22), _tone(990, 0.16, 0.22))
        if name == "question":
            return _seq(_tone(880, 0.08, 0.22), _tone(1320, 0.12, 0.2))
        if name == "error":
            return _seq(_tone(140, 0.07, 0.3), _tone(110, 0.16, 0.3))
        if name == "geyser":
            return _seq(*[_tone(300 + 60 * i, 0.05, 0.18) for i in range(8)])
        if name == "pass":
            return _seq(_tone(523, 0.08, 0.22), _tone(784, 0.14, 0.22))
        if name == "fail":
            return _seq(_tone(392, 0.09, 0.24), _tone(262, 0.18, 0.24))
        if name == "spawn":
            return _tone(1568, 0.06, 0.15)
        return None

    def play(self, name: str) -> bool:
        if not self.enabled or self.device is None:
            return False
        now = time.time()
        if now < self.muted_until or now - self.last_at.get(name, 0.0) < MIN_GAP_S:
            return False
        snd = self.cache.get(name)
        if snd is None:
            snd = self._build(name)
            if snd is None:
                return False
            self.cache[name] = snd
        try:
            self.device.play(snd)
        except Exception:  # noqa: BLE001
            return False
        self.last_at[name] = now
        return True

    def mute(self, seconds: float) -> None:
        """Silence for a while (startup replay, a burst of history)."""
        self.muted_until = time.time() + seconds
