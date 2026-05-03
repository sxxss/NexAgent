"""Agents router — Agent CRUD + built-in agent info + sub-agent execution."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str
    description: str = ""
    base_type: str = "chatbot"          # chatbot / deep_research
    model_name: str = ""
    system_prompt: str = ""
    tools: list[str] = []
    kb_ids: list[str] = []
    skill_ids: list[str] = []
    mcp_ids: list[str] = []
    memory_enabled: bool = False
    thinking_enabled: bool = False
    thinking_budget: int = 8000
    reasoning_mode: str = "balanced"
    allow_subagents: bool = True
    avatar_color: str = "indigo"


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_type: str | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    tools: list[str] | None = None
    kb_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    memory_enabled: bool | None = None
    thinking_enabled: bool | None = None
    thinking_budget: int | None = None
    reasoning_mode: str | None = None
    allow_subagents: bool | None = None
    avatar_color: str | None = None


class SubAgentTaskRequest(BaseModel):
    agent: str = "chatbot"
    message: str
    model: str | None = None
    tools: list[str] = []
    kb_ids: list[str] = []
    mcp_ids: list[str] = []
    skill_ids: list[str] = []
    allowed_agent_ids: list[str] = []


class SubAgentRunRequest(BaseModel):
    tasks: list[SubAgentTaskRequest]
    max_concurrency: int = 3
    timeout_seconds: int = 900


class SubAgentSubmitRequest(SubAgentTaskRequest):
    timeout_seconds: int = 900


class AgentChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    user_id: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    kb_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    allow_subagents: bool | None = None
    allowed_agent_ids: list[str] | None = None
    subagent_model_strategy: str | None = None
    subagent_model: str | None = None
    thinking: bool = False
    thinking_budget: int = 8000
    reasoning_mode: str = "balanced"
    reasoning_budget: int | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/")
async def list_agents():
    """List all agents (built-in + user-created) from the database."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentConfig).order_by(AgentConfig.is_builtin.desc(), AgentConfig.created_at)
        )
        agents = result.scalars().all()

    return {"agents": [a.to_dict() for a in agents]}


@router.post("/", status_code=201)
async def create_agent(body: AgentCreate):
    """Create a new user-defined agent."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        agent = AgentConfig(
            name=body.name,
            description=body.description,
            base_type=body.base_type,
            model_name=body.model_name or None,
            system_prompt=body.system_prompt,
            tools=body.tools,
            memory_enabled=body.memory_enabled,
            thinking_enabled=body.thinking_enabled,
            thinking_budget=body.thinking_budget,
            reasoning_mode=body.reasoning_mode,
            allow_subagents=body.allow_subagents,
            is_builtin=False,
            avatar_color=body.avatar_color,
        )
        agent.kb_ids = body.kb_ids
        agent.skill_ids = body.skill_ids
        agent.mcp_ids = body.mcp_ids
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return agent.to_dict()


@router.get("/skills")
async def list_skills():
    """List available skills with full metadata."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    skills = loader.load_all()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "content_preview": (s.content[:300] + "…" if len(s.content) > 300 else s.content),
            }
            for s in skills
        ],
        "total": len(skills),
    }


@router.get("/tools")
async def list_tools():
    """List available built-in and configured MCP tools."""
    from nexagent.tools.registry import list_tool_specs

    tools = [
        {"name": spec.name, "description": spec.description, "category": spec.category, "available": True}
        for spec in list_tool_specs()
        if spec.configurable
    ]

    try:
        from nexagent.tools.mcp.client import load_mcp_tools
        mcp_tools = await load_mcp_tools()
        for tool in mcp_tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "category": "mcp",
                "available": True,
            })
    except Exception:
        pass

    return {"tools": tools}


@router.post("/subagents/run")
async def run_subagents(req: SubAgentRunRequest):
    """Run multiple agent tasks concurrently and return their responses."""
    from nexagent.services.subagent_service import SubAgentTask
    from nexagent.services.subagent_service import run_subagents as _run

    tasks = [
        SubAgentTask(
            agent=item.agent,
            message=item.message,
            model=item.model,
            tools=item.tools,
            kb_ids=item.kb_ids,
            mcp_ids=item.mcp_ids,
            skill_ids=item.skill_ids,
            allowed_agent_ids=item.allowed_agent_ids,
        )
        for item in req.tasks
    ]
    return await _run(tasks, max_concurrency=req.max_concurrency, timeout_seconds=req.timeout_seconds)


@router.post("/subagents/stream")
async def stream_subagents(req: SubAgentRunRequest):
    """Run sub-agents and stream progress events as NDJSON."""
    import json

    from nexagent.services.subagent_service import SubAgentTask
    from nexagent.services.subagent_service import stream_subagents as _stream

    tasks = [
        SubAgentTask(
            agent=item.agent,
            message=item.message,
            model=item.model,
            tools=item.tools,
            kb_ids=item.kb_ids,
            mcp_ids=item.mcp_ids,
            skill_ids=item.skill_ids,
            allowed_agent_ids=item.allowed_agent_ids,
        )
        for item in req.tasks
    ]

    async def _ndjson():
        async for event in _stream(tasks, max_concurrency=req.max_concurrency, timeout_seconds=req.timeout_seconds):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _ndjson(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/subagents/submit")
async def submit_subagent(req: SubAgentSubmitRequest):
    from nexagent.services.subagent_service import SubAgentTask, submit_subagent

    task_id = await submit_subagent(
        SubAgentTask(
            agent=req.agent,
            message=req.message,
            model=req.model,
            tools=req.tools,
            kb_ids=req.kb_ids,
            mcp_ids=req.mcp_ids,
            skill_ids=req.skill_ids,
            allowed_agent_ids=req.allowed_agent_ids,
        ),
        timeout_seconds=req.timeout_seconds,
    )
    return {"task_id": task_id, "status": "queued"}


@router.get("/subagents/{task_id}")
async def get_subagent_task(task_id: str):
    from nexagent.services.subagent_service import get_task_status

    try:
        return get_task_status(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@router.post("/subagents/{task_id}/cancel")
async def cancel_subagent_task(task_id: str):
    from nexagent.services.subagent_service import cancel_subagent_task

    try:
        return await cancel_subagent_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc


@router.get("/subagents/{task_id}/events")
async def stream_subagent_task_events(task_id: str):
    import json

    from nexagent.services.subagent_service import stream_task_events

    async def _sse():
        try:
            async for event in stream_task_events(task_id):
                yield f"event: {event.type}\ndata: {json.dumps(event.__dict__, ensure_ascii=False)}\n\n"
        except KeyError:
            yield f"event: task_failed\ndata: {json.dumps({'task_id': task_id, 'error': 'Task not found'})}\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get a single agent's full configuration."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        agent = await session.get(AgentConfig, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        return agent.to_dict()


@router.post("/{agent_id}/chat")
async def chat_with_agent(agent_id: str, body: AgentChatRequest):
    """Run a configured Agent with its persisted defaults."""
    from app.gateway.routers.chat import ChatRequest, chat_sync

    request = ChatRequest(
        message=body.message,
        agent=agent_id,
        thread_id=body.thread_id,
        user_id=body.user_id,
        model=body.model,
        tools=body.tools,
        kb_ids=body.kb_ids,
        mcp_ids=body.mcp_ids,
        skill_ids=body.skill_ids,
        allow_subagents=body.allow_subagents,
        allowed_agent_ids=body.allowed_agent_ids,
        subagent_model_strategy=body.subagent_model_strategy,
        subagent_model=body.subagent_model,
        thinking=body.thinking,
        thinking_budget=body.thinking_budget,
        reasoning_mode=body.reasoning_mode,
        reasoning_budget=body.reasoning_budget,
    )
    return await chat_sync(request)


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate):
    """Update an agent's configuration."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        agent = await session.get(AgentConfig, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        if body.name is not None:
            agent.name = body.name
        if body.description is not None:
            agent.description = body.description
        if body.base_type is not None:
            agent.base_type = body.base_type
        if body.model_name is not None:
            agent.model_name = body.model_name or None
        if body.system_prompt is not None:
            agent.system_prompt = body.system_prompt
        if hasattr(body, "tools") and body.tools is not None:
            agent.tools = body.tools
        if body.kb_ids is not None:
            agent.kb_ids = body.kb_ids
        if body.skill_ids is not None:
            agent.skill_ids = body.skill_ids
        if body.mcp_ids is not None:
            agent.mcp_ids = body.mcp_ids
        if body.memory_enabled is not None:
            agent.memory_enabled = body.memory_enabled
        if body.thinking_enabled is not None:
            agent.thinking_enabled = body.thinking_enabled
        if body.thinking_budget is not None:
            agent.thinking_budget = body.thinking_budget
        if body.reasoning_mode is not None:
            agent.reasoning_mode = body.reasoning_mode
        if body.allow_subagents is not None:
            agent.allow_subagents = body.allow_subagents
        if body.avatar_color is not None:
            agent.avatar_color = body.avatar_color

        await session.commit()
        await session.refresh(agent)
        return agent.to_dict()


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str):
    """Delete a user-created agent. Built-in agents cannot be deleted."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        agent = await session.get(AgentConfig, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
        if agent.is_builtin:
            raise HTTPException(status_code=403, detail="Cannot delete built-in agents")
        await session.delete(agent)
        await session.commit()


@router.post("/{agent_id}/clone")
async def clone_agent(agent_id: str):
    """Clone an existing agent into a new user-created agent."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        source = await session.get(AgentConfig, agent_id)
        if not source:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        clone = AgentConfig(
            name=f"{source.name} (副本)",
            description=source.description,
            base_type=source.base_type,
            model_name=source.model_name,
            system_prompt=source.system_prompt,
            memory_enabled=source.memory_enabled,
            thinking_enabled=source.thinking_enabled,
            thinking_budget=source.thinking_budget,
            reasoning_mode=source.reasoning_mode,
            allow_subagents=source.allow_subagents,
            is_builtin=False,
            avatar_color=source.avatar_color,
        )
        clone.kb_ids = source.kb_ids or []
        clone.skill_ids = source.skill_ids or []
        clone.mcp_ids = source.mcp_ids or []
        session.add(clone)
        await session.commit()
        await session.refresh(clone)
        return clone.to_dict()
