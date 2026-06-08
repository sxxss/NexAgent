"""LLM Wiki router — crystallize conversations into reusable knowledge pages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class CrystallizeRequest(BaseModel):
    thread_id: str
    kb_id: str | None = None
    model: str | None = None


@router.post("/crystallize", summary="Distill a conversation thread into a wiki page")
async def crystallize(req: CrystallizeRequest):
    from nexagent.services.wiki_service import crystallize_thread

    if not req.kb_id:
        raise HTTPException(status_code=400, detail="请选择目标 Wiki 知识库后再沉淀。")
    try:
        return await crystallize_thread(req.thread_id, kb_id=req.kb_id, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"沉淀失败：{exc}") from exc


@router.get("/pages", summary="List saved wiki pages")
async def list_wiki_pages():
    from nexagent.services.wiki_service import list_pages

    return {"pages": list_pages()}


@router.get("/pages/{page_id}", summary="Get a wiki page with content")
async def get_wiki_page(page_id: str):
    from nexagent.services.wiki_service import get_page

    page = get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return page


@router.delete("/pages/{page_id}", status_code=204, summary="Delete a wiki page")
async def delete_wiki_page(page_id: str):
    from nexagent.services.wiki_service import delete_page

    if not delete_page(page_id):
        raise HTTPException(status_code=404, detail="Wiki page not found")
