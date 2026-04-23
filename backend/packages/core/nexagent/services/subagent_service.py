"""Sub-agent orchestration service."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

SubAgentResultStatus = Literal["completed", "failed", "timed_out", "cancelled"]


@dataclass
class SubAgentTask:
    agent: str
    message: str
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    kb_ids: list[str] = field(default_factory=list)
    mcp_ids: list[str] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    allowed_agent_ids: list[str] = field(default_factory=list)


@dataclass
class SubAgentPolicy:
    """Parent-run permissions applied to delegated tasks.

    ``None`` means unrestricted for that dimension. An empty list means no
    values are allowed. This distinction lets normal Agent defaults remain
    flexible while explicit profile selections act as a real whitelist.
    """

    allowed_agent_ids: list[str] | None = None
    allowed_tools: list[str] | None = None
    allowed_kb_ids: list[str] | None = None
    allowed_mcp_ids: list[str] | None = None
    allowed_skill_ids: list[str] | None = None


@dataclass
class TaskEvent:
    type: Literal["task_started", "task_running", "task_completed", "task_failed", "task_timed_out", "task_cancelled"]
    task_id: str
    progress: str | None = None
    result: str | None = None


_TASKS: dict[str, dict[str, Any]] = {}
_TASK_EVENTS: dict[str, list[TaskEvent]] = {}
_TASK_QUEUE: dict[str, asyncio.Queue[TaskEvent]] = {}
_TASK_HANDLES: dict[str, asyncio.Task] = {}


async def run_subagents(
    tasks: list[SubAgentTask],
    max_concurrency: int = 3,
    *,
    timeout_seconds: int = 900,
    policy: SubAgentPolicy | None = None,
) -> dict[str, Any]:
    """Run multiple agent tasks concurrently and aggregate partial failures."""
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    run_id = str(uuid.uuid4())

    async def _run_one(index: int, task: SubAgentTask) -> dict[str, Any]:
        async with semaphore:
            return await _invoke_task(
                run_id=run_id,
                index=index,
                task=task,
                timeout_seconds=timeout_seconds,
                policy=policy,
            )

    results = await asyncio.gather(*[_run_one(index, task) for index, task in enumerate(tasks)])
    return _aggregate_results(run_id, results)


async def stream_subagents(
    tasks: list[SubAgentTask],
    max_concurrency: int = 3,
    *,
    timeout_seconds: int = 900,
    policy: SubAgentPolicy | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run sub-agents concurrently and stream progress events."""
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    run_id = str(uuid.uuid4())
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def _run_one(index: int, task: SubAgentTask) -> dict[str, Any]:
        await queue.put({
            "type": "subagent_started",
            "data": _event_payload(run_id, index, task, status="queued"),
        })
        async with semaphore:
            await queue.put({
                "type": "subagent_progress",
                "data": _event_payload(run_id, index, task, status="running"),
            })
            item = await _invoke_task(
                run_id=run_id,
                index=index,
                task=task,
                timeout_seconds=timeout_seconds,
                policy=policy,
            )
            event_type = {
                "completed": "subagent_completed",
                "failed": "subagent_failed",
                "timed_out": "subagent_failed",
                "cancelled": "subagent_failed",
            }.get(item["status"], "subagent_failed")
            await queue.put({"type": event_type, "data": {**item, "run_id": run_id}})
            return item

    yield {"type": "run_started", "data": {"run_id": run_id, "total": len(tasks), "max_concurrency": max_concurrency}}

    runners = [asyncio.create_task(_run_one(index, task)) for index, task in enumerate(tasks)]
    pending = set(runners)
    results: list[dict[str, Any]] = []

    while pending or not queue.empty():
        while not queue.empty():
            yield await queue.get()
        if pending:
            done, pending = await asyncio.wait(pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED)
            for runner in done:
                results.append(runner.result())

    yield {"type": "run_completed", "data": _aggregate_results(run_id, results)}


async def submit_subagent(task: SubAgentTask, timeout_seconds: int = 900) -> str:
    task_id = str(uuid.uuid4())
    _TASKS[task_id] = {"status": "queued", "task": task, "created_at": time.time(), "result": None}
    _TASK_EVENTS[task_id] = []
    _TASK_QUEUE[task_id] = asyncio.Queue()
    handle = asyncio.create_task(_execute_background(task_id, task, timeout_seconds=timeout_seconds))
    _TASK_HANDLES[task_id] = handle
    return task_id


def get_task_status(task_id: str) -> dict[str, Any]:
    if task_id not in _TASKS:
        raise KeyError(task_id)
    item = _TASKS[task_id]
    return {
        "task_id": task_id,
        "status": item["status"],
        "created_at": item["created_at"],
        "result": item.get("result"),
        "error": item.get("error"),
    }


async def cancel_subagent_task(task_id: str) -> dict[str, Any]:
    if task_id not in _TASKS:
        raise KeyError(task_id)
    item = _TASKS[task_id]
    if item["status"] not in {"queued", "running"}:
        return get_task_status(task_id)
    handle = _TASK_HANDLES.get(task_id)
    if handle and not handle.done():
        handle.cancel()
    item.update({"status": "cancelled", "error": "Cancelled by user"})
    await _emit(TaskEvent(type="task_cancelled", task_id=task_id, progress="Cancelled by user"))
    return get_task_status(task_id)


async def stream_task_events(task_id: str) -> AsyncIterator[TaskEvent]:
    if task_id not in _TASKS:
        raise KeyError(task_id)
    for event in _TASK_EVENTS.get(task_id, []):
        yield event
    queue = _TASK_QUEUE[task_id]
    while _TASKS[task_id]["status"] in {"queued", "running"}:
        try:
            yield await asyncio.wait_for(queue.get(), timeout=5)
        except TimeoutError:
            yield TaskEvent(type="task_running", task_id=task_id, progress="still running")
    while not queue.empty():
        yield queue.get_nowait()


async def _execute_background(task_id: str, task: SubAgentTask, timeout_seconds: int) -> None:
    await _emit(TaskEvent(type="task_started", task_id=task_id, progress=task.message[:200]))
    _TASKS[task_id]["status"] = "running"
    try:
        result = await _invoke_task(
            run_id=task_id,
            index=0,
            task=task,
            timeout_seconds=timeout_seconds,
            policy=None,
        )
        if result["status"] == "completed":
            response = str(result.get("response", ""))
            _TASKS[task_id].update({"status": "completed", "result": response})
            await _emit(TaskEvent(type="task_completed", task_id=task_id, result=response))
        elif result["status"] == "timed_out":
            _TASKS[task_id].update({"status": "timed_out", "error": result.get("error")})
            await _emit(TaskEvent(type="task_timed_out", task_id=task_id, progress=result.get("error")))
        else:
            _TASKS[task_id].update({"status": "failed", "error": result.get("error")})
            await _emit(TaskEvent(type="task_failed", task_id=task_id, progress=result.get("error")))
    except asyncio.CancelledError:
        _TASKS[task_id].update({"status": "cancelled", "error": "Cancelled by user"})
        await _emit(TaskEvent(type="task_cancelled", task_id=task_id, progress="Cancelled by user"))
    finally:
        _TASK_HANDLES.pop(task_id, None)


async def _emit(event: TaskEvent) -> None:
    _TASK_EVENTS.setdefault(event.task_id, []).append(event)
    queue = _TASK_QUEUE.get(event.task_id)
    if queue is not None:
        await queue.put(event)


async def _invoke_task(
    *,
    run_id: str,
    index: int,
    task: SubAgentTask,
    timeout_seconds: int,
    policy: SubAgentPolicy | None,
) -> dict[str, Any]:
    from nexagent.services.chat_service import invoke_chat

    start = time.monotonic()
    try:
        runtime_agent, context_overrides = await _resolve_task_runtime(task, policy=policy)
        result = await asyncio.wait_for(
            invoke_chat(message=task.message, agent_name=runtime_agent, context_overrides=context_overrides),
            timeout=timeout_seconds,
        )
        response = str(result.get("response", ""))
        return {
            "index": index,
            "agent": task.agent,
            "runtime_agent": runtime_agent,
            "task": task.message,
            "status": "completed",
            "response": response,
            "summary": _summarize_text(response),
            "thread_id": result.get("thread_id"),
            "latency_ms": int((time.monotonic() - start) * 1000),
            "context": _public_context(context_overrides),
        }
    except TimeoutError:
        return {
            "index": index,
            "agent": task.agent,
            "task": task.message,
            "status": "timed_out",
            "error": f"Timed out after {timeout_seconds}s",
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return {
            "index": index,
            "agent": task.agent,
            "task": task.message,
            "status": "failed",
            "error": str(exc),
            "latency_ms": int((time.monotonic() - start) * 1000),
        }


async def _resolve_task_runtime(task: SubAgentTask, policy: SubAgentPolicy | None = None) -> tuple[str, dict[str, Any]]:
    """Resolve a task's configured Agent id into runtime agent + bounded context."""
    agent_id = _normalize_agent_id(task.agent)
    _ensure_agent_allowed(agent_id, policy)
    context: dict[str, Any] = {
        "model": task.model,
        "tools": list(task.tools),
        "tools_explicit": bool(task.tools),
        "kb_ids": list(task.kb_ids),
        "mcp_ids": list(task.mcp_ids),
        "skills": list(task.skill_ids),
        "allowed_agent_ids": list(task.allowed_agent_ids),
        "allow_subagents": False,
    }
    runtime_agent = agent_id
    try:
        from nexagent.db.models import AgentConfig
        from nexagent.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentConfig, agent_id)
            if agent:
                runtime_agent = agent.base_type
                context.update(
                    {
                        "agent_config_id": agent.id,
                        "model": task.model or agent.model_name,
                        "system_prompt": agent.system_prompt,
                        "tools": task.tools or agent.tools or [],
                        "tools_explicit": bool(task.tools),
                        "kb_ids": task.kb_ids or agent.kb_ids or [],
                        "mcp_ids": task.mcp_ids or agent.mcp_ids or [],
                        "skills": task.skill_ids or agent.skill_ids or [],
                        "allowed_agent_ids": task.allowed_agent_ids,
                        "memory_enabled": agent.memory_enabled,
                        "thinking": agent.thinking_enabled,
                        "thinking_budget": agent.thinking_budget,
                        "reasoning_mode": agent.reasoning_mode,
                        "allow_subagents": False,
                    }
                )
    except Exception:
        pass
    return runtime_agent, _apply_policy(context, policy)


def _apply_policy(context: dict[str, Any], policy: SubAgentPolicy | None) -> dict[str, Any]:
    if not policy:
        return context
    context = dict(context)
    context["tools"] = _filter_allowed(context.get("tools") or [], policy.allowed_tools)
    if policy.allowed_tools is not None:
        context["tools_explicit"] = True
    context["kb_ids"] = _filter_allowed(context.get("kb_ids") or [], policy.allowed_kb_ids)
    context["mcp_ids"] = _filter_allowed(context.get("mcp_ids") or [], policy.allowed_mcp_ids)
    context["skills"] = _filter_allowed(context.get("skills") or [], policy.allowed_skill_ids)
    context["allowed_agent_ids"] = _filter_allowed(context.get("allowed_agent_ids") or [], policy.allowed_agent_ids)
    context["allow_subagents"] = False
    return context


def _filter_allowed(values: list[str], allowed: list[str] | None) -> list[str]:
    normalized = [str(value) for value in values if str(value)]
    if allowed is None:
        return normalized
    allowed_set = set(allowed)
    return [value for value in normalized if value in allowed_set]


def _ensure_agent_allowed(agent_id: str, policy: SubAgentPolicy | None) -> None:
    if not policy or policy.allowed_agent_ids is None:
        return
    allowed = {_normalize_agent_id(item) for item in policy.allowed_agent_ids}
    if _normalize_agent_id(agent_id) not in allowed:
        raise PermissionError(f"Sub-agent '{agent_id}' is not allowed by the parent Agent policy.")


def _aggregate_results(run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(results, key=lambda item: item["index"])
    succeeded = sum(1 for item in ordered if item["status"] == "completed")
    failed = len(ordered) - succeeded
    return {
        "run_id": run_id,
        "total": len(ordered),
        "succeeded": succeeded,
        "failed": failed,
        "status": "completed" if failed == 0 else "partial_failure",
        "summary": f"{succeeded}/{len(ordered)} sub-agents completed successfully.",
        "results": ordered,
    }


def _event_payload(run_id: str, index: int, task: SubAgentTask, *, status: str) -> dict[str, Any]:
    return {"run_id": run_id, "index": index, "agent": task.agent, "task": task.message, "status": status}


def _public_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": context.get("model"),
        "tools": context.get("tools") or [],
        "kb_ids": context.get("kb_ids") or [],
        "mcp_ids": context.get("mcp_ids") or [],
        "skill_ids": context.get("skills") or [],
    }


def _summarize_text(value: str, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _normalize_agent_id(agent_id: str) -> str:
    aliases = {
        "deep-research": "deep_research",
        "deepresearch": "deep_research",
        "research": "deep_research",
        "chat": "chatbot",
    }
    normalized = str(agent_id or "chatbot").strip()
    return aliases.get(normalized, normalized)
