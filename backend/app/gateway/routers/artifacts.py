"""Thread artifact listing, preview, and download routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/threads/{thread_id}")
async def list_artifacts(thread_id: str):
    from nexagent.artifacts import list_thread_artifacts

    return {"thread_id": thread_id, "artifacts": [item.to_dict() for item in list_thread_artifacts(thread_id)]}


@router.get("/threads/{thread_id}/preview")
async def preview_artifact(thread_id: str, path: str = Query(..., description="Virtual artifact path")):
    from nexagent.artifacts import read_artifact_preview

    try:
        return read_artifact_preview(thread_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/threads/{thread_id}/download")
async def download_artifact(thread_id: str, path: str = Query(..., description="Virtual artifact path")):
    from nexagent.artifacts import resolve_artifact

    try:
        target = resolve_artifact(thread_id, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(target, filename=target.name)
