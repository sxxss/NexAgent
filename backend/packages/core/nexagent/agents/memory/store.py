"""Atomic JSON fact memory store."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

FactCategory = Literal["preference", "knowledge", "context", "behavior", "goal"]


@dataclass
class Fact:
    id: str
    content: str
    category: FactCategory = "context"
    confidence: float = 0.7
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source: str = ""


@dataclass
class UserContext:
    work_context: str = ""
    personal_context: str = ""
    top_of_mind: str = ""


@dataclass
class MemoryHistory:
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    update_count: int = 0


@dataclass
class MemoryStore:
    user_context: UserContext = field(default_factory=UserContext)
    history: MemoryHistory = field(default_factory=MemoryHistory)
    facts: list[Fact] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> MemoryStore:
        return cls(
            user_context=UserContext(**data.get("user_context", {})),
            history=MemoryHistory(**data.get("history", {})),
            facts=[Fact(**item) for item in data.get("facts", [])],
        )

    def to_dict(self) -> dict:
        return asdict(self)


_cache: dict[str, MemoryStore] | None = None


def memory_enabled() -> bool:
    """Master switch — whether long-term memory is active at all."""
    try:
        from nexagent.config import get_config

        return bool(get_config().memory.enabled)
    except Exception:
        return True


def injection_enabled() -> bool:
    """Whether saved facts may be injected into the system prompt."""
    try:
        from nexagent.config import get_config

        cfg = get_config().memory
        return bool(cfg.enabled and cfg.injection_enabled)
    except Exception:
        return True


def extraction_enabled() -> bool:
    """Whether new facts may be extracted from conversations."""
    try:
        from nexagent.config import get_config

        cfg = get_config().memory
        return bool(cfg.enabled and cfg.extraction_enabled)
    except Exception:
        return True


def _max_facts() -> int:
    try:
        from nexagent.config import get_config

        return max(1, int(get_config().memory.max_facts))
    except Exception:
        return 100


def _path() -> Path:
    from nexagent.config import get_config

    configured = os.environ.get("NEXAGENT_MEMORY_PATH")
    if configured:
        return Path(configured)
    root = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    storage = getattr(get_config().memory, "storage_path", "")
    return Path(storage) if storage else root / "memory.json"


def _load_all() -> dict[str, MemoryStore]:
    global _cache
    if _cache is not None:
        return _cache
    path = _path()
    if not path.exists():
        _cache = {}
        return _cache
    raw = json.loads(path.read_text(encoding="utf-8"))
    _cache = {user_id: MemoryStore.from_dict(value) for user_id, value in raw.items()}
    return _cache


def reload_memory() -> dict[str, MemoryStore]:
    global _cache
    _cache = None
    return _load_all()


def save_memory() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {user_id: store.to_dict() for user_id, store in _load_all().items()}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    Path(temp_name).replace(path)


def get_memory(user_id: str) -> MemoryStore:
    data = _load_all()
    return data.setdefault(user_id, MemoryStore())


def upsert_fact(
    user_id: str,
    content: str,
    category: FactCategory = "context",
    confidence: float = 0.7,
    source: str = "",
) -> Fact:
    store = get_memory(user_id)
    normalized = _normalize(content)
    for fact in store.facts:
        if _normalize(fact.content) == normalized:
            fact.confidence = max(fact.confidence, confidence)
            fact.source = source or fact.source
            _touch(store)
            save_memory()
            return fact
    fact = Fact(
        id=str(uuid.uuid4()),
        content=content.strip(),
        category=category,
        confidence=max(0.0, min(1.0, confidence)),
        source=source,
    )
    store.facts.append(fact)
    _trim(store)
    _touch(store)
    save_memory()
    return fact


def delete_fact(user_id: str, fact_id: str) -> bool:
    store = get_memory(user_id)
    before = len(store.facts)
    store.facts = [fact for fact in store.facts if fact.id != fact_id]
    if len(store.facts) == before:
        return False
    _touch(store)
    save_memory()
    return True


def top_facts_for_prompt(user_id: str, limit: int | None = None) -> str:
    if not injection_enabled():
        return ""
    if limit is None:
        try:
            from nexagent.config import get_config

            limit = max(1, int(get_config().memory.max_injection_facts))
        except Exception:
            limit = 15
    store = get_memory(user_id)
    facts = sorted(store.facts, key=lambda fact: (fact.confidence, fact.created_at), reverse=True)[:limit]
    parts = []
    if store.user_context.work_context:
        parts.append(f"Work context: {store.user_context.work_context}")
    if store.user_context.personal_context:
        parts.append(f"Personal context: {store.user_context.personal_context}")
    if store.user_context.top_of_mind:
        parts.append(f"Top of mind: {store.user_context.top_of_mind}")
    parts.extend(f"- [{fact.category}] {fact.content}" for fact in facts)
    return "\n".join(parts)


def _touch(store: MemoryStore) -> None:
    store.history.updated_at = datetime.now(UTC).isoformat()
    store.history.update_count += 1


def _trim(store: MemoryStore, max_facts: int | None = None) -> None:
    limit = max_facts if max_facts is not None else _max_facts()
    store.facts = sorted(store.facts, key=lambda fact: (fact.confidence, fact.created_at), reverse=True)[:limit]


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())
