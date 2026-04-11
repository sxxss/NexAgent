"""SQLAlchemy async engine setup.

Database: SQLite by default (.nexagent/nexagent.db).
Override with DATABASE_URL env var for PostgreSQL in production:
  DATABASE_URL=postgresql+asyncpg://user:pass@localhost/nexagent
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def get_db_path() -> Path:
    data_dir = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "nexagent.db"


def _build_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    db_path = get_db_path()
    return f"sqlite+aiosqlite:///{db_path}"


engine = create_async_engine(
    _build_url(),
    echo=os.environ.get("NEXAGENT_DEBUG") == "1",
    future=True,
    # SQLite-specific: allow multiple concurrent connections
    connect_args={"check_same_thread": False} if "sqlite" in _build_url() else {},
)
