"""SQLAlchemy async engine setup.

Database: PostgreSQL by default (production-grade).

Resolution order for the connection URL:
  1. ``DATABASE_URL`` env var (used by docker-compose and deployments).
  2. Fallback to a local PostgreSQL instance on ``localhost:5432`` — bring it up
     with ``docker compose up -d postgres`` (port 5432 is published).

SQLite is still supported for throwaway/offline use, but only when explicitly
requested via ``DATABASE_URL=sqlite+aiosqlite:///...`` or by setting
``NEXAGENT_DB_BACKEND=sqlite``.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase

DEFAULT_POSTGRES_URL = "postgresql+asyncpg://nexagent:nexagent@localhost:5432/nexagent"


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db_path() -> Path:
    data_dir = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "nexagent.db"


def _normalize_url(url: str) -> str:
    """Ensure async drivers are used for common DSN shapes.

    Accepts the bare ``postgresql://`` / ``postgres://`` forms (as written in
    .env.example and most tooling) and upgrades them to the asyncpg driver that
    the async engine requires.
    """
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return "sqlite+aiosqlite://" + url[len("sqlite://"):]
    return url


def _build_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return _normalize_url(url)
    if os.environ.get("NEXAGENT_DB_BACKEND", "").lower() == "sqlite":
        return f"sqlite+aiosqlite:///{get_db_path()}"
    return DEFAULT_POSTGRES_URL


_DB_URL = _build_url()
_IS_SQLITE = _DB_URL.startswith("sqlite")

engine = create_async_engine(
    _DB_URL,
    echo=os.environ.get("NEXAGENT_DEBUG") == "1",
    future=True,
    # SQLite-specific: allow multiple concurrent connections.
    connect_args={"check_same_thread": False} if _IS_SQLITE else {},
    # Pooling tuned for PostgreSQL under concurrent gateway + worker load.
    **({} if _IS_SQLITE else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True, "pool_recycle": 1800}),
)
