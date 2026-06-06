#!/usr/bin/env python3
"""One-shot data migration: legacy SQLite (.nexagent/nexagent.db) -> PostgreSQL.

NexAgent switched its default relational store from SQLite to PostgreSQL. If you
have an existing local SQLite database you want to keep, run this script once to
copy every row across. Target tables are created if missing; a non-empty target
table is skipped unless ``--truncate`` is passed.

Usage
-----
    # Source defaults to .nexagent/nexagent.db, target to $DATABASE_URL
    uv run python scripts/migrate_sqlite_to_postgres.py

    # Explicit endpoints
    uv run python scripts/migrate_sqlite_to_postgres.py \
        --sqlite .nexagent/nexagent.db \
        --postgres postgresql+asyncpg://nexagent:nexagent@localhost:5432/nexagent \
        --truncate

Uses the same async drivers as the app (asyncpg + aiosqlite), so no extra
dependencies are required.
"""

# ruff: noqa: E402, I001  (imports intentionally follow sys.path setup below)
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make the core package importable when run from the repo root.
_CORE = Path(__file__).resolve().parent.parent / "backend" / "packages" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from sqlalchemy import insert, inspect, select
from sqlalchemy.ext.asyncio import create_async_engine

import nexagent.db.models  # noqa: F401  (populates Base.metadata)
from nexagent.db.base import Base


def _normalize_pg(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    return url


async def _run(sqlite_path: Path, pg_url: str, truncate: bool) -> int:
    src = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path}", future=True)
    dst = create_async_engine(_normalize_pg(pg_url), future=True)

    print(f"→ Source : {sqlite_path}")
    print(f"→ Target : {dst.url.render_as_string(hide_password=True)}")

    # Ensure the schema exists on the target.
    async with dst.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Discover which tables actually exist in the source.
    async with src.connect() as sconn:
        src_tables = set(await sconn.run_sync(lambda c: inspect(c).get_table_names()))

    total = 0
    async with src.connect() as sconn, dst.begin() as dconn:
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                continue
            result = await sconn.execute(select(table))
            rows = [dict(r._mapping) for r in result]
            if not rows:
                continue

            existing = (await dconn.execute(select(table).limit(1))).first()
            if existing is not None:
                if not truncate:
                    print(f"  • {table.name}: target not empty, skipping (use --truncate to overwrite)")
                    continue
                await dconn.execute(table.delete())

            await dconn.execute(insert(table), rows)
            total += len(rows)
            print(f"  ✓ {table.name}: {len(rows)} rows")

    await src.dispose()
    await dst.dispose()
    print(f"\n✅ Migration complete — {total} rows copied.")
    print("   Verify the app, then you may archive the old SQLite file.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default=".nexagent/nexagent.db", help="Path to the source SQLite file")
    parser.add_argument(
        "--postgres",
        default=os.environ.get("DATABASE_URL", "postgresql+asyncpg://nexagent:nexagent@localhost:5432/nexagent"),
        help="Target PostgreSQL URL (defaults to $DATABASE_URL)",
    )
    parser.add_argument("--truncate", action="store_true", help="Empty non-empty target tables before copying")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"✗ Source SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 1

    return asyncio.run(_run(sqlite_path, args.postgres, args.truncate))


if __name__ == "__main__":
    raise SystemExit(main())
