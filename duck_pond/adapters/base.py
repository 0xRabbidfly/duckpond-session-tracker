from __future__ import annotations

import json
import os
from collections.abc import Iterator


class FileTail:
    """Byte-offset tail follower for an append-only JSONL file."""

    def __init__(self, path: str, from_start: bool = True) -> None:
        self.path = path
        self.offset = 0 if from_start else self._size()
        self.partial = b""

    def _size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def mtime(self) -> float:
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def new_lines(self, max_bytes: int = 8 * 1024 * 1024) -> Iterator[dict]:
        size = self._size()
        if size < self.offset:  # truncated / rewritten
            self.offset = 0
            self.partial = b""
        if size == self.offset:
            return
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(min(size - self.offset, max_bytes))
        except OSError:
            return
        self.offset += len(chunk)
        data = self.partial + chunk
        lines = data.split(b"\n")
        self.partial = lines.pop()  # incomplete trailer (or b"")
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue


class Adapter:
    """Protocol: poll(now) returns a list of event dicts (see SPEC §8.4)."""

    name = "base"

    def poll(self, now: float) -> list[dict]:  # pragma: no cover - interface
        return []

    def backfill(self, now: float) -> list[dict]:
        """Past usage for the ledger (UsageBatch events), read once at startup. Creates no ducks."""
        return []

    def describe(self) -> str:
        return self.name


def excerpt(text: object, limit: int = 400) -> str:
    if isinstance(text, list):
        parts = []
        for block in text:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif block.get("type") == "tool_result":
                    parts.append(excerpt(block.get("content", ""), limit))
            else:
                parts.append(str(block))
        text = " ".join(parts)
    s = " ".join(str(text or "").split())
    return s[:limit]


def tool_summary(name: str, inp: dict | None) -> str:
    inp = inp or {}
    for key in ("command", "description", "pattern", "file_path", "query", "prompt", "url", "skill"):
        if key in inp and inp[key]:
            return excerpt(inp[key], 120)
    return excerpt(json.dumps(inp)[:120], 120) if inp else ""
