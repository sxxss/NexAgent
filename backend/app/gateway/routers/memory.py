"""Memory router — persistent memory management (DB-backed)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────

class MemoryCreate(BaseModel):
    key: str
    value: str
    agent_id: str | None = None
    memory_type: str = "fact"    # fact / preference / episode
    importance: float = 0.5
    source: str = "user"


class MemoryUpdate(BaseModel):
    key: str | None = None
    value: str | None = None
    memory_type: str | None = None
    importance: float | None = None


class FactCreate(BaseModel):
    content: str
    category: str = "context"
    confidence: float = 0.7
    source: str = "user"


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/{user_id}")
async def list_memories(
    user_id: str,
    agent_id: str | None = Query(None),
    memory_type: str | None = Query(None),
    q: str | None = Query(None, description="Search in key or value"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List memories for a user with optional filters."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stmt = select(MemoryEntry).where(MemoryEntry.user_id == user_id)
        if agent_id:
            stmt = stmt.where(MemoryEntry.agent_id == agent_id)
        if memory_type:
            stmt = stmt.where(MemoryEntry.memory_type == memory_type)
        if q:
            stmt = stmt.where(
                or_(
                    MemoryEntry.key.ilike(f"%{q}%"),
                    MemoryEntry.value.ilike(f"%{q}%"),
                )
            )

        total_result = await session.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = total_result.scalar_one()

        stmt = stmt.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        entries = result.scalars().all()

    return {
        "user_id": user_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "memories": [e.to_dict() for e in entries],
    }


@router.get("/{user_id}/store")
async def get_fact_memory(user_id: str):
    from nexagent.agents.memory import get_memory

    return get_memory(user_id).to_dict()


@router.post("/{user_id}/reload")
async def reload_fact_memory(user_id: str):
    from nexagent.agents.memory import get_memory, reload_memory

    reload_memory()
    return get_memory(user_id).to_dict()


@router.post("/{user_id}/facts", status_code=201)
async def create_fact(user_id: str, body: FactCreate):
    from nexagent.agents.memory import upsert_fact

    fact = upsert_fact(
        user_id=user_id,
        content=body.content,
        category=body.category,  # type: ignore[arg-type]
        confidence=body.confidence,
        source=body.source,
    )
    return fact.__dict__


@router.delete("/{user_id}/facts/{fact_id}", status_code=204)
async def delete_fact(user_id: str, fact_id: str):
    from fastapi import HTTPException
    from nexagent.agents.memory import delete_fact as _delete_fact

    if not _delete_fact(user_id, fact_id):
        raise HTTPException(status_code=404, detail="Fact not found")


@router.post("/{user_id}", status_code=201)
async def create_memory(user_id: str, body: MemoryCreate):
    """Create a new memory entry."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        entry = MemoryEntry(
            user_id=user_id,
            agent_id=body.agent_id,
            memory_type=body.memory_type,
            key=body.key,
            value=body.value,
            source=body.source,
            importance=body.importance,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry.to_dict()


@router.put("/{user_id}/{memory_id}")
async def update_memory(user_id: str, memory_id: str, body: MemoryUpdate):
    """Update a memory entry."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        entry = await session.get(MemoryEntry, memory_id)
        if not entry or entry.user_id != user_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Memory not found")

        if body.key is not None:
            entry.key = body.key
        if body.value is not None:
            entry.value = body.value
        if body.memory_type is not None:
            entry.memory_type = body.memory_type
        if body.importance is not None:
            entry.importance = body.importance

        await session.commit()
        await session.refresh(entry)
        return entry.to_dict()


@router.delete("/{user_id}/{memory_id}", status_code=204)
async def delete_memory(user_id: str, memory_id: str):
    """Delete a specific memory entry."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        entry = await session.get(MemoryEntry, memory_id)
        if not entry or entry.user_id != user_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Memory not found")
        await session.delete(entry)
        await session.commit()


@router.delete("/{user_id}", status_code=204)
async def clear_memories(user_id: str, agent_id: str | None = Query(None)):
    """Delete all memories for a user (optionally scoped to an agent)."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal
    from sqlalchemy import delete

    async with AsyncSessionLocal() as session:
        stmt = delete(MemoryEntry).where(MemoryEntry.user_id == user_id)
        if agent_id:
            stmt = stmt.where(MemoryEntry.agent_id == agent_id)
        await session.execute(stmt)
        await session.commit()


@router.get("/{user_id}/stats")
async def memory_stats(user_id: str):
    """Return memory count breakdown by type."""
    from nexagent.db.models import MemoryEntry
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(MemoryEntry.memory_type, func.count().label("count"))
            .where(MemoryEntry.user_id == user_id)
            .group_by(MemoryEntry.memory_type)
        )).all()

    counts = {row.memory_type: row.count for row in rows}
    total = sum(counts.values())
    return {
        "user_id": user_id,
        "total": total,
        "by_type": {
            "fact": counts.get("fact", 0),
            "preference": counts.get("preference", 0),
            "episode": counts.get("episode", 0),
        },
    }
