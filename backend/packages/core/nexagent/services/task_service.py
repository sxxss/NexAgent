"""Generic persistent task registry for long-running NexAgent work."""

from __future__ import annotations

import inspect
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "interrupted", "cancelled"}
ACTIVE_STATUSES = {"queued", "running"}


@dataclass
class TaskRecord:
    """Persistent state for a long-running task."""

    task_id: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    current_step: str = ""
    completed_steps: int = 0
    total_steps: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskRecord:
        payload = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "progress": round(float(self.progress), 1),
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "total_steps": self.total_steps,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


RetryHandler = Callable[[TaskRecord], TaskRecord | Awaitable[TaskRecord]]

_TASKS: dict[str, TaskRecord] = {}
_LOADED = False
_RETRY_HANDLERS: dict[str, RetryHandler] = {}


def register_retry_handler(kind: str, handler: RetryHandler) -> None:
    """Register an in-process retry handler for a task kind."""
    _RETRY_HANDLERS[kind] = handler


def create_task(
    *,
    kind: str,
    metadata: dict[str, Any] | None = None,
    total_steps: int = 0,
    current_step: str = "",
    task_id: str | None = None,
) -> TaskRecord:
    ensure_loaded()
    task = TaskRecord(
        task_id=task_id or str(uuid.uuid4()),
        kind=kind,
        metadata=metadata or {},
        total_steps=total_steps,
        current_step=current_step,
    )
    _TASKS[task.task_id] = task
    persist_tasks()
    return task


def get_task(task_id: str) -> TaskRecord | None:
    ensure_loaded()
    return _TASKS.get(task_id)


def require_task(task_id: str) -> TaskRecord:
    task = get_task(task_id)
    if task is None:
        raise KeyError(f"Task not found: {task_id}")
    return task


def list_tasks(
    *,
    kind: str | None = None,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
    limit: int = 100,
) -> list[TaskRecord]:
    ensure_loaded()
    tasks = sorted(_TASKS.values(), key=lambda item: item.created_at, reverse=True)
    if kind:
        tasks = [task for task in tasks if task.kind == kind]
    if status:
        allowed = {item.strip() for item in status.split(",") if item.strip()}
        tasks = [task for task in tasks if task.status in allowed]
    if metadata:
        tasks = [
            task
            for task in tasks
            if all(task.metadata.get(key) == value for key, value in metadata.items())
        ]
    return tasks[:limit]


def update_task(task_id: str, **updates: Any) -> TaskRecord:
    ensure_loaded()
    task = require_task(task_id)
    for key, value in updates.items():
        if key not in TaskRecord.__dataclass_fields__:
            raise KeyError(f"Unknown task field: {key}")
        setattr(task, key, value)
    task.updated_at = time.time()
    _TASKS[task.task_id] = task
    persist_tasks()
    return task


def update_progress(
    task_id: str,
    *,
    completed_steps: int | None = None,
    total_steps: int | None = None,
    current_step: str | None = None,
    result: dict[str, Any] | None = None,
    status: str | None = None,
    error: str | None = None,
) -> TaskRecord:
    task = require_task(task_id)
    next_completed = task.completed_steps if completed_steps is None else completed_steps
    next_total = task.total_steps if total_steps is None else total_steps
    progress = round((next_completed / next_total) * 100, 1) if next_total else task.progress
    updates: dict[str, Any] = {
        "completed_steps": next_completed,
        "total_steps": next_total,
        "progress": min(100.0, max(0.0, progress)),
    }
    if current_step is not None:
        updates["current_step"] = current_step
    if result is not None:
        updates["result"] = result
    if status is not None:
        updates["status"] = status
    if error is not None:
        updates["error"] = error
    return update_task(task_id, **updates)


def request_cancel(task_id: str) -> TaskRecord:
    task = require_task(task_id)
    if task.status == "queued":
        return update_task(
            task_id,
            status="cancelled",
            cancel_requested=True,
            error="Task was cancelled before it started.",
        )
    if task.status == "running":
        return update_task(task_id, cancel_requested=True)
    return task


def is_cancel_requested(task_id: str) -> bool:
    task = get_task(task_id)
    return bool(task and task.cancel_requested)


async def retry_task(task_id: str) -> TaskRecord:
    task = require_task(task_id)
    if task.status in ACTIVE_STATUSES:
        return task
    handler = _RETRY_HANDLERS.get(task.kind)
    if handler is None:
        raise ValueError(f"No retry handler registered for task kind: {task.kind}")
    result = handler(task)
    if inspect.isawaitable(result):
        return await result
    return result


def ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    path = _tasks_path()
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw.get("tasks", []):
            task = TaskRecord.from_dict(item)
            if task.status in ACTIVE_STATUSES:
                task.status = "interrupted"
                task.current_step = ""
                task.cancel_requested = False
                task.error = "Server restarted before this task completed."
                task.updated_at = time.time()
            _TASKS[task.task_id] = task
        persist_tasks()
    except Exception as exc:
        logger.warning("Failed to load task registry from %s: %s", path, exc)


def persist_tasks() -> None:
    try:
        tasks = sorted(_TASKS.values(), key=lambda item: item.created_at, reverse=True)[:500]
        _tasks_path().write_text(
            json.dumps({"tasks": [task.to_dict() for task in tasks]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to persist task registry: %s", exc)


def _tasks_path() -> Path:
    data_root = Path(os.environ.get("NEXAGENT_DATA_DIR", str(Path.home() / ".nexagent")))
    path = data_root / "tasks" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_task_registry_for_tests() -> None:
    """Reset in-memory registry state. Intended for unit tests only."""
    global _LOADED
    _TASKS.clear()
    _LOADED = False
