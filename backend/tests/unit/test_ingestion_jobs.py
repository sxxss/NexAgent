from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path

import pytest


def _work_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / ".test-artifacts" / name / uuid.uuid4().hex


@pytest.mark.unit
def test_task_registry_loads_active_tasks_as_interrupted(monkeypatch):
    from nexagent.services import task_service

    work_dir = _work_dir("task-registry-restart")
    work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(work_dir))
    task_service.reset_task_registry_for_tests()

    tasks_path = work_dir / "tasks" / "tasks.json"
    tasks_path.parent.mkdir(parents=True)
    now = time.time()
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-running",
                        "kind": "unit",
                        "status": "running",
                        "progress": 40,
                        "current_step": "working",
                        "completed_steps": 2,
                        "total_steps": 5,
                        "result": {},
                        "error": "",
                        "metadata": {"kb_id": "kb-a"},
                        "cancel_requested": False,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "task_id": "task-completed",
                        "kind": "unit",
                        "status": "completed",
                        "progress": 100,
                        "current_step": "done",
                        "completed_steps": 1,
                        "total_steps": 1,
                        "result": {},
                        "error": "",
                        "metadata": {"kb_id": "kb-a"},
                        "cancel_requested": False,
                        "created_at": now - 1,
                        "updated_at": now - 1,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        running = task_service.require_task("task-running")
        completed = task_service.require_task("task-completed")

        assert running.status == "interrupted"
        assert running.current_step == ""
        assert "Server restarted" in running.error
        assert completed.status == "completed"
    finally:
        task_service.reset_task_registry_for_tests()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_task_registry_filters_cancels_and_retries(monkeypatch):
    from nexagent.services import task_service

    work_dir = _work_dir("task-registry-actions")
    work_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(work_dir))
    task_service.reset_task_registry_for_tests()

    kind = f"unit-{uuid.uuid4().hex}"

    def retry_handler(task: task_service.TaskRecord) -> task_service.TaskRecord:
        return task_service.create_task(
            kind=kind,
            metadata={"kb_id": task.metadata["kb_id"], "retried_from": task.task_id},
            total_steps=1,
            current_step="queued",
        )

    try:
        task_service.register_retry_handler(kind, retry_handler)
        task = task_service.create_task(
            kind=kind,
            metadata={"kb_id": "kb-a", "file_ids": ["file-a"]},
            total_steps=1,
        )
        task_service.update_progress(task.task_id, completed_steps=0, status="failed", error="boom")
        cancelled = task_service.create_task(kind=kind, metadata={"kb_id": "kb-b"}, total_steps=2)

        filtered = task_service.list_tasks(kind=kind, metadata={"kb_id": "kb-a"})
        assert [item.task_id for item in filtered] == [task.task_id]
        assert task_service.request_cancel(cancelled.task_id).status == "cancelled"

        retried = asyncio.run(task_service.retry_task(task.task_id))
        assert retried.task_id != task.task_id
        assert retried.metadata["retried_from"] == task.task_id
        assert retried.metadata["kb_id"] == "kb-a"
    finally:
        task_service.reset_task_registry_for_tests()
        shutil.rmtree(work_dir, ignore_errors=True)
