"""Chat router — Agent conversation endpoints with invocation logging."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    agent: str = "chatbot"
    thread_id: str | None = None
    user_id: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    kb_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    allow_subagents: bool | None = None
    allowed_agent_ids: list[str] | None = None
    subagent_model_strategy: str | None = Field(default=None, pattern="^(main_agent|agent_default|custom)$")
    subagent_model: str | None = None
    # Thinking Mode (Claude Extended Thinking / Gemini Thinking)
    thinking: bool = False
    thinking_budget: int = Field(default=8000, ge=1024, le=32000)
    reasoning_mode: str = Field(default="balanced", pattern="^(fast|balanced|deep|ultra)$")
    reasoning_effort: str | None = Field(default=None, pattern="^(minimal|low|medium|high)$")
    reasoning_budget: int | None = Field(default=None, ge=1024, le=32000)
    planning_enabled: bool | None = None


class ChatSyncResponse(BaseModel):
    response: str
    thread_id: str
    agent: str
    model: str | None = None
    artifacts: list[str] = []


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """Stream an agent response as JSON-Lines (NDJSON).

    Extra event types beyond the base protocol:
      - ``thinking``   — incremental thinking content (when thinking=True)
      - ``usage``      — token usage summary (at stream end)
    """
    from nexagent.agents.middlewares.log_middleware import logged_stream
    from nexagent.services.chat_service import stream_chat
    from nexagent.services.conversation_service import append_message, ensure_conversation, list_messages

    thread_id = request.thread_id or str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    runtime = await resolve_agent_runtime(request.agent)
    context_overrides = build_context_overrides(request, runtime, thread_id)
    context_overrides["checkpoint_thread_id"] = f"{thread_id}:run:{request_id}"
    await ensure_conversation(
        conversation_id=thread_id,
        user_id=request.user_id,
        agent_id=runtime["agent_config_id"],
        agent_name=runtime["agent_name"],
        model_name=context_overrides.get("model"),
        first_message=request.message,
    )
    history_messages = await list_messages(thread_id)
    await append_message(conversation_id=thread_id, role="user", content=request.message)

    raw_stream = stream_chat(
        message=request.message,
        agent_name=runtime["runtime_agent"],
        thread_id=thread_id,
        context_overrides=context_overrides,
        request_id=request_id,
        history_messages=history_messages,
    )

    logged = logged_stream(
        raw_stream,
        agent_id=runtime["agent_config_id"],
        agent_name=runtime["agent_name"],
        thread_id=thread_id,
        model_name=context_overrides.get("model", ""),
        thinking_enabled=bool(context_overrides.get("thinking")),
        reasoning_mode=context_overrides.get("reasoning_mode"),
    )

    import json

    async def _ndjson():
        assistant_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            async for chunk in logged:
                if chunk.get("status") == "loading" and chunk.get("content"):
                    assistant_parts.append(str(chunk["content"]))
                elif chunk.get("status") == "thinking" and chunk.get("content"):
                    reasoning_parts.append(str(chunk["content"]))
                elif chunk.get("status") == "tool_call":
                    await append_message(
                        conversation_id=thread_id,
                        role="tool",
                        content=json.dumps(chunk.get("input") or {}, ensure_ascii=False),
                        tool_name=str(chunk.get("tool") or ""),
                    )
                elif chunk.get("status") == "finished":
                    content = (
                        "".join(assistant_parts).strip()
                        or "模型没有返回可显示内容。本次调用已结束，请重试或切换模型。"
                    )
                    await append_message(
                        conversation_id=thread_id,
                        role="assistant",
                        content=content,
                        reasoning_content="".join(reasoning_parts) or None,
                    )
                elif chunk.get("status") == "error":
                    await append_message(
                        conversation_id=thread_id,
                        role="assistant",
                        content=f"错误：{chunk.get('error')}",
                        reasoning_content="".join(reasoning_parts) or None,
                    )
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except Exception as exc:
            error_chunk = {
                "request_id": str(uuid.uuid4()),
                "event_id": str(uuid.uuid4()),
                "seq": 0,
                "status": "error",
                "thread_id": thread_id,
                "phase": "error",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
            await append_message(
                conversation_id=thread_id,
                role="assistant",
                content=f"错误：{exc}",
                reasoning_content="".join(reasoning_parts) or None,
            )
            yield json.dumps(error_chunk, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _ndjson(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/", response_model=ChatSyncResponse)
async def chat_sync(request: ChatRequest):
    """Run an agent to completion and return the full response (non-streaming)."""
    from nexagent.services.chat_service import invoke_chat
    from nexagent.services.conversation_service import append_message, ensure_conversation, list_messages

    thread_id = request.thread_id or str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    runtime = await resolve_agent_runtime(request.agent)
    context_overrides = build_context_overrides(request, runtime, thread_id)
    context_overrides["checkpoint_thread_id"] = f"{thread_id}:run:{request_id}"
    await ensure_conversation(
        conversation_id=thread_id,
        user_id=request.user_id,
        agent_id=runtime["agent_config_id"],
        agent_name=runtime["agent_name"],
        model_name=context_overrides.get("model"),
        first_message=request.message,
    )
    history_messages = await list_messages(thread_id)
    await append_message(conversation_id=thread_id, role="user", content=request.message)
    start = time.monotonic()
    status = "success"
    error_msg = None

    try:
        result = await invoke_chat(
            message=request.message,
            agent_name=runtime["runtime_agent"],
            thread_id=thread_id,
            context_overrides=context_overrides,
            history_messages=history_messages,
        )
    except ValueError as e:
        status = "error"
        error_msg = str(e)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        status = "error"
        error_msg = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await _write_sync_log(
            agent_id=runtime["agent_config_id"],
            agent_name=runtime["agent_name"],
            thread_id=thread_id,
            model_name=context_overrides.get("model", ""),
            latency_ms=int((time.monotonic() - start) * 1000),
            status=status,
            error_msg=error_msg,
            thinking_enabled=bool(context_overrides.get("thinking")),
            reasoning_mode=context_overrides.get("reasoning_mode"),
        )

    await append_message(conversation_id=thread_id, role="assistant", content=str(result["response"]))

    return ChatSyncResponse(
        response=result["response"],
        thread_id=result["thread_id"],
        agent=runtime["agent_config_id"],
        model=result.get("model"),
        artifacts=result.get("artifacts", []),
    )


@router.get("/history/{thread_id}")
async def get_history(thread_id: str, agent: str = "chatbot"):
    """Return message history for a conversation thread."""
    from nexagent.services.conversation_service import list_messages

    messages = await list_messages(thread_id)
    if messages:
        return {"thread_id": thread_id, "messages": messages}

    from nexagent.services.chat_service import _get_agent
    try:
        ag = _get_agent(agent)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    history = await ag.get_history(thread_id)
    return {"thread_id": thread_id, "messages": history}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def resolve_agent_runtime(agent_id: str) -> dict[str, Any]:
    """Resolve a configured Agent into runtime defaults used by chat endpoints."""
    try:
        from nexagent.db.models import AgentConfig
        from nexagent.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            agent = await session.get(AgentConfig, agent_id)
            if agent:
                return {
                    "agent_config_id": agent.id,
                    "runtime_agent": agent.base_type,
                    "agent_name": agent.name,
                    "model": agent.model_name or None,
                    "system_prompt": agent.system_prompt or None,
                    "tools": agent.tools or [],
                    "kb_ids": agent.kb_ids or [],
                    "skill_ids": agent.skill_ids or [],
                    "mcp_ids": agent.mcp_ids or [],
                    "allow_subagents": agent.allow_subagents,
                    "memory_enabled": agent.memory_enabled,
                    "thinking_enabled": agent.thinking_enabled,
                    "thinking_budget": agent.thinking_budget,
                    "reasoning_mode": agent.reasoning_mode or "balanced",
                }
    except Exception:
        pass
    return {
        "agent_config_id": agent_id,
        "runtime_agent": agent_id,
        "agent_name": agent_id,
        "model": None,
        "system_prompt": None,
        "tools": [],
        "kb_ids": [],
        "skill_ids": [],
        "mcp_ids": [],
        "allow_subagents": False,
        "memory_enabled": False,
        "thinking_enabled": False,
        "thinking_budget": 8000,
        "reasoning_mode": "balanced",
    }


def build_context_overrides(request: ChatRequest, runtime: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """Merge request-level overrides with persisted AgentConfig defaults."""
    context: dict[str, Any] = {"thread_id": thread_id, "agent_config_id": runtime["agent_config_id"]}
    context["agent_name"] = runtime.get("agent_name")
    context["model"] = request.model or runtime.get("model")
    if request.user_id:
        context["user_id"] = request.user_id
    elif runtime.get("memory_enabled"):
        context["user_id"] = "default"

    context["system_prompt"] = request.system_prompt or runtime.get("system_prompt")
    context["tools"] = request.tools if request.tools is not None else runtime.get("tools", [])
    context["tools_explicit"] = request.tools is not None
    context["kb_ids"] = request.kb_ids if request.kb_ids is not None else runtime.get("kb_ids", [])
    context["skills"] = request.skill_ids if request.skill_ids is not None else runtime.get("skill_ids", [])
    context["mcp_ids"] = request.mcp_ids if request.mcp_ids is not None else runtime.get("mcp_ids", [])
    context["allow_subagents"] = (
        request.allow_subagents if request.allow_subagents is not None else bool(runtime.get("allow_subagents"))
    )
    if request.allowed_agent_ids is not None:
        context["allowed_agent_ids"] = request.allowed_agent_ids
    if request.subagent_model_strategy is not None:
        context["subagent_model_strategy"] = request.subagent_model_strategy
    if request.subagent_model is not None:
        context["subagent_model"] = request.subagent_model
    context["memory_enabled"] = bool(runtime.get("memory_enabled"))
    requested_mode = request.reasoning_mode or runtime.get("reasoning_mode", "balanced")
    context["reasoning_mode"] = _effective_reasoning_mode(requested_mode)
    reasoning_profile = _reasoning_profile(context["reasoning_mode"], request.reasoning_effort)
    context["reasoning_effort"] = reasoning_profile["effort"]
    context["planning_enabled"] = (
        request.planning_enabled if request.planning_enabled is not None else reasoning_profile["planning_enabled"]
    )
    context["thinking"] = bool(
        request.thinking
        or runtime.get("thinking_enabled")
        or reasoning_profile["thinking_enabled"]
    )
    context["thinking_budget"] = (
        request.reasoning_budget
        or request.thinking_budget
        or reasoning_profile["budget"]
        or runtime.get("thinking_budget", 8000)
    )
    return {key: value for key, value in context.items() if value is not None}


def _effective_reasoning_mode(requested: str) -> str:
    return requested if requested in {"fast", "balanced", "deep", "ultra"} else "balanced"


def _reasoning_profile(mode: str, requested_effort: str | None = None) -> dict[str, Any]:
    defaults = {
        "fast": {"thinking_enabled": False, "planning_enabled": False, "effort": "minimal", "budget": 1024},
        "balanced": {"thinking_enabled": True, "planning_enabled": False, "effort": "low", "budget": 4096},
        "deep": {"thinking_enabled": True, "planning_enabled": True, "effort": "medium", "budget": 12000},
        "ultra": {"thinking_enabled": True, "planning_enabled": True, "effort": "high", "budget": 32000},
    }
    profile = defaults.get(mode, defaults["balanced"]).copy()
    if requested_effort in {"minimal", "low", "medium", "high"}:
        profile["effort"] = requested_effort
    return profile


async def _write_sync_log(**kwargs: Any) -> None:
    try:
        from nexagent.agents.middlewares.log_middleware import _write_log

        await _write_log(
            input_tokens=0,
            output_tokens=0,
            tools_used=[],
            **kwargs,
        )
    except Exception:
        pass
