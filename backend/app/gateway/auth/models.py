"""API key models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class APIKey:
    id: str
    user_id: str
    name: str
    key_hash: str
    scopes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked: bool = False

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("key_hash", None)
        return data
