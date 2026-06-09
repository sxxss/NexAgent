"""Conversation-to-Wiki router."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CrystallizeRequest(BaseModel):
    thread_id: str
    kb_id: str | None = None
    model: str | None = None
    page_type: str = "note"


@router.post("/crystallize", summary="Distill a conversation thread into a selected Wiki knowledge base")
async def crystallize(req: CrystallizeRequest):
    from nexagent.services.wiki_service import crystallize_thread

    if not req.kb_id:
        raise HTTPException(status_code=400, detail="请选择目标 Wiki 知识库后再沉淀。")
    try:
        return await crystallize_thread(req.thread_id, kb_id=req.kb_id, model=req.model, page_type=req.page_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"沉淀失败：{exc}") from exc
