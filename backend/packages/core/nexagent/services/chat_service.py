"""Chat service - streaming and non-streaming agent invocation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS = 30 * 60
DEFAULT_STREAM_HEARTBEAT_SECONDS = 15


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


STREAM_IDLE_TIMEOUT_SECONDS = _env_int(
    "NEXAGENT_CHAT_STREAM_IDLE_TIMEOUT_S",
    DEFAULT_STREAM_IDLE_TIMEOUT_SECONDS,
    minimum=60,
    maximum=6 * 60 * 60,
)
STREAM_HEARTBEAT_SECONDS = _env_int(
    "NEXAGENT_CHAT_STREAM_HEARTBEAT_S",
    DEFAULT_STREAM_HEARTBEAT_SECONDS,
    minimum=5,
    maximum=60,
)


def _get_agent(agent_name: str):
    """Return or lazily create an agent instance by name."""
    from nexagent.agents.registry import get_agent

    return get_agent(agent_name)


@dataclass
class StreamRun:
    """Small helper that stamps every stream event consistently."""

    request_id: str
    thread_id: str
    started_at: float = field(default_factory=time.monotonic)
    seq: int = 0

    def event(self, status: str, **kwargs: Any) -> dict[str, Any]:
        self.seq += 1
        return {
            "request_id": self.request_id,
            "event_id": f"{self.request_id}:{self.seq}",
            "seq": self.seq,
            "status": status,
            "thread_id": self.thread_id,
            "elapsed_ms": int((time.monotonic() - self.started_at) * 1000),
            **kwargs,
        }


def _normalize_context(thread_id: str, context_overrides: dict | None = None) -> dict:
    context = {"thread_id": thread_id, **(context_overrides or {})}
    context.setdefault("tools", [])
    context.setdefault("kb_ids", [])
    context.setdefault("allowed_agent_ids", [])
    return context


def _history_to_messages(history_messages: list[dict[str, Any]] | None) -> list:
    """Convert persisted conversation rows into model-safe chat history.

    Tool rows are intentionally skipped because the database stores UI tool
    call metadata, not LangChain ToolMessages with valid tool_call_id pairs.
    """
    messages: list = []
    for item in (history_messages or [])[-30:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content") or block.get("delta")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content or "")


def _clean_model_text(value: str) -> str:
    """Remove common transport/mojibake artifacts without changing normal text."""
    if not value:
        return ""
    return (
        value
        .replace("\ufeff", "")
        .replace("\ufffd", "")
        .replace("锟斤拷", "")
        .replace("锟", "")
        .replace("\x00", "")
    )


def _last_ai_text(state: dict[str, Any]) -> str:
    messages = state.get("messages", []) or []
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
        if msg_type in {"ai", "assistant"} or isinstance(msg, AIMessage):
            text = _clean_model_text(_message_text(getattr(msg, "content", "")))
            if text:
                return text
    return ""


def _message_events(msg: AIMessageChunk) -> list[dict[str, str]]:
    """Convert provider-specific streaming chunks into NexAgent stream events."""
    events: list[dict[str, str]] = []
    content = msg.content

    if isinstance(content, str) and content:
        text = _clean_model_text(content)
        if text:
            events.append({"status": "loading", "content": text})
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str) and block:
                text = _clean_model_text(block)
                if text:
                    events.append({"status": "loading", "content": text})
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "")).lower()
            text = str(block.get("text") or block.get("content") or block.get("delta") or "")
            text = _clean_model_text(text)
            if not text:
                continue
            if "thinking" in block_type or "reasoning" in block_type:
                events.append({"status": "thinking", "content": text})
            else:
                events.append({"status": "loading", "content": text})

    for key in ("thinking", "reasoning", "reasoning_content"):
        value = msg.additional_kwargs.get(key) if hasattr(msg, "additional_kwargs") else None
        if isinstance(value, str) and value:
            text = _clean_model_text(value)
            if text:
                events.append({"status": "thinking", "content": text})

    return events


def _usage_from_chunk(msg: AIMessageChunk) -> dict[str, int | bool]:
    from nexagent.token_usage import usage_from_mapping

    usage = getattr(msg, "usage_metadata", None) or {}
    return usage_from_mapping(usage, source="stream_chunk")


def _usage_from_state(state: dict[str, Any]) -> dict[str, int | bool]:
    from nexagent.token_usage import usage_from_mapping

    input_tokens = 0
    output_tokens = 0
    anomalous = False
    for msg in state.get("messages", []) or []:
        usage = getattr(msg, "usage_metadata", None) or {}
        if not usage:
            metadata = getattr(msg, "response_metadata", None) or {}
            usage = metadata.get("token_usage") or {}
        normalized = usage_from_mapping(usage, source="state_message")
        input_tokens = max(input_tokens, int(normalized["input_tokens"]))
        output_tokens = max(output_tokens, int(normalized["output_tokens"]))
        anomalous = anomalous or bool(normalized["token_usage_anomalous"])
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "token_usage_anomalous": anomalous}


def _tool_message_content(value: Any, *, max_chars: int = 6000) -> str:
    text = _clean_model_text(_message_text(value))
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n\n[Tool result truncated for UI.]"
    return text


def _tool_dedupe_key(tool_name: str, tool_call_id: str, args: Any) -> str:
    if tool_call_id:
        return tool_call_id
    return f"{tool_name}:{json.dumps(args or {}, sort_keys=True, default=str)}"


def _tool_stream_key(tool_name: str, tool_call_id: str, args: Any, *, ready: bool) -> str:
    if tool_call_id:
        return tool_call_id
    if ready:
        return _tool_dedupe_key(tool_name, tool_call_id, args)
    return f"{tool_name}:preparing"


def _tool_args_ready(tool_name: str, args: Any) -> bool:
    """Return whether streamed tool-call args are complete enough for execution UI."""
    if not isinstance(args, dict):
        return args is not None
    if tool_name == "skill_manage":
        return bool(str(args.get("action") or "").strip() and str(args.get("id") or "").strip())
    if tool_name == "read_skill":
        return bool(str(args.get("id") or "").strip())
    if tool_name == "execute_python":
        return bool(str(args.get("code") or "").strip())
    if tool_name == "bash":
        return bool(str(args.get("command") or "").strip())
    return True


def _heartbeat_message(active_tools: dict[str, str]) -> str:
    if not active_tools:
        return "模型仍在处理，继续等待中。"
    names = ", ".join(sorted(set(active_tools.values()))[:3])
    suffix = " 等工具" if len(set(active_tools.values())) > 3 else ""
    return f"正在等待工具 {names}{suffix} 返回结果。"


def _extract_subagent_runs(value: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if "```nexagent-subagents" not in value:
        return runs
    for match in re.finditer(r"```nexagent-subagents\s*([\s\S]*?)```", value):
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict) and parsed.get("run_id"):
                runs.append(parsed)
        except Exception:
            continue
    return runs


def _subagent_runs_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for msg in state.get("messages", []) or []:
        content = _message_text(getattr(msg, "content", ""))
        if content:
            runs.extend(_extract_subagent_runs(content))
    return runs


async def _sandbox_artifacts(thread_id: str) -> list[str]:
    try:
        from nexagent.sandbox import get_sandbox_provider

        sandbox = await get_sandbox_provider().acquire(thread_id)
        return await sandbox.present_artifacts()
    except Exception as exc:
        logger.debug("Artifact discovery skipped for thread=%s: %s", thread_id, exc)
        return []


async def stream_chat(
    message: str,
    agent_name: str = "chatbot",
    thread_id: str | None = None,
    context_overrides: dict | None = None,
    request_id: str | None = None,
    history_messages: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream agent response as JSON-Lines bytes.

    Event protocol:
    - started: request accepted and agent/model resolved
    - loading: incremental model text
    - tool_call: tool invocation metadata
    - plan/research_step/writing: structured research progress
    - state: state snapshot such as artifacts
    - finished: run completed
    - error/interrupted: terminal failure states
    """
    from nexagent.models.factory import validate_model_name_async

    request_id = request_id or str(uuid.uuid4())
    thread_id = thread_id or str(uuid.uuid4())
    run = StreamRun(request_id=request_id, thread_id=thread_id)
    input_context = _normalize_context(thread_id, context_overrides)
    messages = [*_history_to_messages(history_messages), HumanMessage(content=message)]

    try:
        agent = _get_agent(agent_name)
        input_context["model"] = await validate_model_name_async(input_context.get("model"))
    except ValueError as exc:
        yield run.event("error", error=str(exc), error_type=exc.__class__.__name__, phase="startup")
        return

    yield run.event(
        "started",
        agent=agent.name,
        model=input_context.get("model"),
        tools=input_context.get("tools", []),
        kb_ids=input_context.get("kb_ids", []),
        mcp_ids=input_context.get("mcp_ids", []),
        skill_ids=input_context.get("skills", []),
        reasoning_mode=input_context.get("reasoning_mode"),
        phase="startup",
    )

    emitted_plan = False
    last_step = -1
    emitted_writing = False
    emitted_artifacts: set[str] = set()
    emitted_subagent_runs: set[str] = set()
    emitted_tool_calls: set[str] = set()
    completed_tool_calls: set[str] = set()
    tool_started_at: dict[str, float] = {}
    active_tools: dict[str, str] = {}
    response_parts: list[str] = []
    last_state: dict[str, Any] = {}
    input_tokens = 0
    output_tokens = 0
    token_usage_anomalous = False

    try:
        stream = agent.stream_with_state(messages, input_context=input_context)
        iterator = stream.__aiter__()
        while True:
            pending = asyncio.create_task(iterator.__anext__())
            pending_started_at = time.monotonic()
            while True:
                done, _pending = await asyncio.wait({pending}, timeout=STREAM_HEARTBEAT_SECONDS)
                if pending in done:
                    try:
                        mode, payload = pending.result()
                    except StopAsyncIteration:
                        pending = None
                    break

                elapsed = int(time.monotonic() - pending_started_at)
                if elapsed >= STREAM_IDLE_TIMEOUT_SECONDS:
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending
                    yield run.event(
                        "error",
                        error=(
                            f"模型在 {STREAM_IDLE_TIMEOUT_SECONDS} 秒内没有返回新内容，"
                            "本次响应已中断。可以重试，或切换模型、降低推理模式。"
                        ),
                        error_type="StreamIdleTimeout",
                        phase="error",
                    )
                    return
                yield run.event(
                    "heartbeat",
                    phase="tool" if active_tools else "model",
                    message=_heartbeat_message(active_tools),
                    idle_seconds=elapsed,
                    active_tools=sorted(set(active_tools.values())),
                )
            if pending is None:
                break
            if mode == "messages":
                msg, _metadata = payload
                if isinstance(msg, AIMessageChunk):
                    if getattr(msg, "tool_calls", None):
                        for tool_call in msg.tool_calls:
                            tool_name = str(tool_call.get("name", "") or "").strip()
                            if not tool_name:
                                continue
                            tool_call_id = str(tool_call.get("id", "") or "")
                            tool_args = tool_call.get("args", {})
                            args_ready = _tool_args_ready(tool_name, tool_args)
                            dedupe_key = _tool_stream_key(tool_name, tool_call_id, tool_args, ready=args_ready)
                            already_emitted = (
                                (args_ready and dedupe_key in tool_started_at)
                                or (not args_ready and dedupe_key in emitted_tool_calls)
                            )
                            if already_emitted:
                                continue
                            emitted_tool_calls.add(dedupe_key)
                            if args_ready:
                                tool_started_at[dedupe_key] = time.monotonic()
                                active_tools[dedupe_key] = tool_name
                            yield run.event(
                                "tool_call",
                                phase="tool",
                                tool_call_id=tool_call_id,
                                tool=tool_name,
                                input=tool_args,
                                tool_status="started" if args_ready else "preparing",
                            )
                    chunk_usage = _usage_from_chunk(msg)
                    input_tokens = max(input_tokens, int(chunk_usage["input_tokens"]))
                    output_tokens = max(output_tokens, int(chunk_usage["output_tokens"]))
                    token_usage_anomalous = token_usage_anomalous or bool(chunk_usage["token_usage_anomalous"])
                    for event in _message_events(msg):
                        if event["status"] == "loading":
                            response_parts.append(event["content"])
                            yield run.event("loading", content=event["content"], phase="model")
                        elif event["status"] == "thinking":
                            yield run.event("thinking", content=event["content"], phase="reasoning")
                        else:
                            yield run.event(event["status"], content=event.get("content", ""), phase="model")
                elif isinstance(msg, AIMessage) and getattr(msg, "content", None):
                    text = _clean_model_text(_message_text(msg.content))
                    if text:
                        response_parts.append(text)
                        yield run.event("loading", content=text, phase="model")
                elif hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tool_name = str(tool_call.get("name", "") or "").strip()
                        if not tool_name:
                            continue
                        tool_call_id = str(tool_call.get("id", "") or "")
                        tool_args = tool_call.get("args", {})
                        args_ready = _tool_args_ready(tool_name, tool_args)
                        dedupe_key = _tool_stream_key(tool_name, tool_call_id, tool_args, ready=args_ready)
                        already_emitted = (
                            (args_ready and dedupe_key in tool_started_at)
                            or (not args_ready and dedupe_key in emitted_tool_calls)
                        )
                        if already_emitted:
                            continue
                        emitted_tool_calls.add(dedupe_key)
                        if args_ready:
                            tool_started_at[dedupe_key] = time.monotonic()
                            active_tools[dedupe_key] = tool_name
                        yield run.event(
                            "tool_call",
                            phase="tool",
                            tool_call_id=tool_call_id,
                            tool=tool_name,
                            input=tool_args,
                            tool_status="started" if args_ready else "preparing",
                        )
                elif isinstance(msg, ToolMessage) or getattr(msg, "type", None) == "tool":
                    tool_call_id = str(getattr(msg, "tool_call_id", "") or "")
                    tool_name = str(getattr(msg, "name", "") or "")
                    tool_success = str(getattr(msg, "status", "") or "").lower() != "error"
                    dedupe_key = tool_call_id or str(getattr(msg, "id", "") or "")
                    if dedupe_key and dedupe_key in completed_tool_calls:
                        continue
                    if dedupe_key:
                        completed_tool_calls.add(dedupe_key)
                        active_tools.pop(tool_call_id or dedupe_key, None)
                    started_at = tool_started_at.get(tool_call_id or dedupe_key)
                    tool_elapsed_ms = int((time.monotonic() - started_at) * 1000) if started_at else None
                    yield run.event(
                        "tool_result",
                        phase="tool",
                        tool_call_id=tool_call_id,
                        tool=tool_name,
                        output=_tool_message_content(getattr(msg, "content", "")),
                        success=tool_success,
                        tool_status="completed",
                        tool_elapsed_ms=tool_elapsed_ms,
                    )

            elif mode == "values":
                state = payload
                last_state = state if isinstance(state, dict) else {}
                state_usage = _usage_from_state(state)
                input_tokens = max(input_tokens, int(state_usage["input_tokens"]))
                output_tokens = max(output_tokens, int(state_usage["output_tokens"]))
                token_usage_anomalous = token_usage_anomalous or bool(state_usage["token_usage_anomalous"])
                plan = state.get("plan")
                current_step = state.get("current_step", 0)

                if plan and not emitted_plan:
                    yield run.event(
                        "plan",
                        phase="planning",
                        steps=[
                            {"id": step["id"], "title": step["title"], "description": step["description"]}
                            for step in plan
                        ],
                        total=len(plan),
                    )
                    emitted_plan = True

                if plan and emitted_plan and current_step > last_step:
                    if current_step <= len(plan):
                        step_started = current_step
                        if step_started < len(plan):
                            yield run.event(
                                "research_step",
                                phase="research",
                                step=step_started + 1,
                                total=len(plan),
                                title=plan[step_started]["title"],
                            )
                    last_step = current_step

                if plan and emitted_plan and current_step >= len(plan) and not emitted_writing:
                    yield run.event("writing", phase="writing")
                    emitted_writing = True

                artifacts = state.get("artifacts", [])
                if artifacts:
                    artifacts = [str(artifact) for artifact in artifacts]
                    new_artifacts = [artifact for artifact in artifacts if artifact not in emitted_artifacts]
                    emitted_artifacts.update(str(artifact) for artifact in artifacts)
                    yield run.event(
                        "state",
                        phase="artifact",
                        artifacts=artifacts,
                        new_artifacts=new_artifacts,
                    )

                for subagent_run in _subagent_runs_from_state(state):
                    subagent_run_id = str(subagent_run.get("run_id") or "")
                    if not subagent_run_id or subagent_run_id in emitted_subagent_runs:
                        continue
                    emitted_subagent_runs.add(subagent_run_id)
                    failed = int(subagent_run.get("failed") or 0)
                    yield run.event(
                        "subagent_failed" if failed else "subagent_completed",
                        phase="subagent",
                        run_id=subagent_run_id,
                        total=subagent_run.get("total"),
                        succeeded=subagent_run.get("succeeded"),
                        failed=failed,
                        summary=subagent_run.get("summary"),
                        subagents=subagent_run.get("results") or [],
                    )

        final_text = _last_ai_text(last_state)
        if final_text and "".join(response_parts).strip() != final_text.strip():
            if not response_parts or final_text.strip() not in "".join(response_parts).strip():
                response_parts = [final_text]
                yield run.event("loading", content=final_text, phase="model")

        if not "".join(response_parts).strip():
            fallback = "模型没有返回可显示内容。本次调用已结束，请重试或切换模型。"
            response_parts = [fallback]
            yield run.event("loading", content=fallback, phase="model", warning="empty_model_response")

        final_artifacts = await _sandbox_artifacts(thread_id)
        new_artifacts = [artifact for artifact in final_artifacts if artifact not in emitted_artifacts]
        if new_artifacts:
            emitted_artifacts.update(new_artifacts)
            yield run.event(
                "state",
                phase="artifact",
                artifacts=sorted(emitted_artifacts),
                new_artifacts=new_artifacts,
            )

        if input_context.get("memory_enabled") and input_context.get("user_id"):
            await _save_memory_from_turn(
                user_id=input_context["user_id"],
                agent_id=input_context.get("agent_config_id") or agent.name,
                model_name=input_context.get("model") or "",
                user_message=message,
                assistant_message="".join(response_parts),
            )

        from nexagent.token_usage import usage_with_estimate

        usage = usage_with_estimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_text=message,
            response_text="".join(response_parts),
            model=input_context.get("model"),
            provider_anomalous=token_usage_anomalous,
        )
        yield run.event(
            "finished",
            agent=agent.name,
            model=input_context.get("model"),
            content="".join(response_parts),
            usage=usage,
            response_chars=sum(len(part) for part in response_parts),
            phase="done",
        )

    except asyncio.CancelledError:
        yield run.event("interrupted", phase="done")
    except Exception as exc:
        logger.exception("stream_chat error (request_id=%s)", request_id)
        yield run.event("error", error=str(exc), error_type=exc.__class__.__name__, phase="error")


async def invoke_chat(
    message: str,
    agent_name: str = "chatbot",
    thread_id: str | None = None,
    context_overrides: dict | None = None,
    history_messages: list[dict[str, Any]] | None = None,
) -> dict:
    """Run the agent to completion and return the final response."""
    from nexagent.models.factory import validate_model_name_async

    thread_id = thread_id or str(uuid.uuid4())
    input_context = _normalize_context(thread_id, context_overrides)
    input_context["model"] = await validate_model_name_async(input_context.get("model"))

    messages = [*_history_to_messages(history_messages), HumanMessage(content=message)]
    agent = _get_agent(agent_name)
    state = await agent.invoke(messages, input_context=input_context)
    ai_messages = [msg for msg in state.get("messages", []) if hasattr(msg, "content") and msg.type == "ai"]
    response_text = ai_messages[-1].content if ai_messages else ""
    artifacts = list(dict.fromkeys([*state.get("artifacts", []), *await _sandbox_artifacts(thread_id)]))
    if input_context.get("memory_enabled") and input_context.get("user_id"):
        await _save_memory_from_turn(
            user_id=input_context["user_id"],
            agent_id=input_context.get("agent_config_id") or agent.name,
            model_name=input_context.get("model") or "",
            user_message=message,
            assistant_message=str(response_text),
        )
    return {
        "response": response_text,
        "thread_id": thread_id,
        "agent": agent.name,
        "model": input_context.get("model"),
        "artifacts": artifacts,
    }


async def _save_memory_from_turn(
    *,
    user_id: str,
    agent_id: str,
    model_name: str,
    user_message: str,
    assistant_message: str,
) -> None:
    try:
        from nexagent.agents.memory import extraction_enabled
        from nexagent.agents.middlewares.memory_extractor import extract_and_save

        # Master switch (config.memory.enabled + extraction_enabled) gates writes.
        if not extraction_enabled():
            return
        conversation = f"User: {user_message}\nAssistant: {assistant_message}"
        await extract_and_save(user_id, agent_id, model_name, conversation)
    except Exception as exc:
        logger.debug("Memory extraction skipped: %s", exc)
