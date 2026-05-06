"""Generic task registry API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/", summary="List long-running tasks")
async def list_tasks(
    kind: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    from nexagent.services.task_service import list_tasks as list_task_records

    tasks = list_task_records(kind=kind, status=status, limit=limit)
    return {"tasks": [task.to_dict() for task in tasks], "total": len(tasks)}


@router.get("/{task_id}", summary="Get task status")
async def get_task(task_id: str):
    from nexagent.services.task_service import get_task as get_task_record

    task = get_task_record(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task.to_dict()


@router.post("/{task_id}/cancel", summary="Cancel or request cancellation for a task")
async def cancel_task(task_id: str):
    from nexagent.services.task_service import request_cancel

    try:
        task = request_cancel(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task": task.to_dict()}


@router.post("/{task_id}/retry", summary="Retry a failed or interrupted task")
async def retry_task(task_id: str):
    from nexagent.services.task_service import retry_task as retry_task_record

    try:
        task = await retry_task_record(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task": task.to_dict(), "retried_from": task_id}
