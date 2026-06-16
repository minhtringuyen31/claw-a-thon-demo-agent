"""File-backed session/memory store.

Fixes config-agent's in-memory-only loss: state survives process restarts by
persisting JSON under `sessions/`. Keys map to one JSON file each.
"""
from __future__ import annotations

import json
import pathlib

_DIR = pathlib.Path("sessions")


def _path(key: str) -> pathlib.Path:
    safe = key.replace("/", "__").replace(":", "_")
    return _DIR / f"{safe}.json"


class FileMemoryService:
    def __init__(self, base_dir: str | pathlib.Path = "sessions"):
        self._dir = pathlib.Path(base_dir)
        self._dir.mkdir(exist_ok=True)

    def _p(self, key: str) -> pathlib.Path:
        safe = key.replace("/", "__").replace(":", "_")
        return self._dir / f"{safe}.json"

    def get(self, key: str):
        p = self._p(key)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def set(self, key: str, value) -> None:
        self._p(key).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def append(self, key: str, item: dict) -> None:
        existing = self.get(key)
        if isinstance(existing, list):
            existing.append(item)
        else:
            existing = [item]
        self.set(key, existing)
