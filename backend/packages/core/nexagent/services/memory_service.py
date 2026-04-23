"""Lightweight long-term memory store for user preferences."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


def _memory_path() -> Path:
    root = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    path = root / "memory" / "user_memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> dict:
    path = _memory_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    _memory_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_memory(user_id: str) -> dict:
    return _load().get(user_id, {})


def upsert_memory(user_id: str, key: str, value: str) -> dict:
    data = _load()
    user_memory = data.setdefault(user_id, {})
    user_memory[key] = {
        "value": value,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _save(data)
    return {"user_id": user_id, "key": key, **user_memory[key]}


def delete_memory(user_id: str, key: str) -> None:
    data = _load()
    if user_id in data:
        data[user_id].pop(key, None)
        _save(data)
