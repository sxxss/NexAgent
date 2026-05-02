"""JSON-backed API key manager."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.gateway.auth.models import APIKey


def _path() -> Path:
    root = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    path = root / "auth" / "api_keys.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> list[APIKey]:
    path = _path()
    if not path.exists():
        return []
    return [APIKey(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _save(keys: list[APIKey]) -> None:
    _path().write_text(json.dumps([key.__dict__ for key in keys], ensure_ascii=False, indent=2), encoding="utf-8")


def create_api_key(user_id: str, name: str, scopes: list[str], expires_at: str | None = None) -> dict:
    raw_key = "nxg_" + secrets.token_urlsafe(32)
    item = APIKey(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=name,
        key_hash=_hash(raw_key),
        scopes=scopes,
        expires_at=expires_at,
    )
    keys = _load()
    keys.append(item)
    _save(keys)
    return {"api_key": raw_key, **item.public_dict()}


def list_api_keys(user_id: str | None = None) -> list[dict]:
    keys = _load()
    if user_id:
        keys = [key for key in keys if key.user_id == user_id]
    return [key.public_dict() for key in keys]


def revoke_api_key(key_id: str) -> bool:
    keys = _load()
    changed = False
    for key in keys:
        if key.id == key_id:
            key.revoked = True
            changed = True
    if changed:
        _save(keys)
    return changed


def verify_api_key(raw_key: str, required_scope: str | None = None) -> APIKey | None:
    digest = _hash(raw_key)
    keys = _load()
    for key in keys:
        if key.key_hash != digest or key.revoked:
            continue
        if key.expires_at and datetime.fromisoformat(key.expires_at) < datetime.now(UTC):
            continue
        if required_scope and "*" not in key.scopes and required_scope not in key.scopes:
            continue
        key.last_used_at = datetime.now(UTC).isoformat()
        _save(keys)
        return key
    return None


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
