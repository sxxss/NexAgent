"""AI-assisted creator routes for Agents, Skills, and MCP configs."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class DraftRequest(BaseModel):
    goal: str
    details: dict[str, str] = Field(default_factory=dict)


class SaveRequest(BaseModel):
    draft: dict


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.lower()).strip("-")
    return slug[:48] or fallback


def _summary(kind: str, draft: dict) -> str:
    name = draft.get("name") or draft.get("id") or kind
    return f"已生成 {kind} 草稿：{name}。请检查配置，确认后保存。"


@router.post("/agent/draft")
async def draft_agent(body: DraftRequest):
    goal = body.goal.strip()
    name = body.details.get("name") or goal[:18] or "自定义 Agent"
    draft = {
        "name": name,
        "description": body.details.get("description") or goal,
        "base_type": body.details.get("base_type") or "chatbot",
        "model_name": body.details.get("model_name") or "",
        "system_prompt": (
            "你是一个专门处理以下目标的 NexAgent Agent。\n"
            f"目标：{goal}\n"
            "请先澄清不确定需求，再调用合适的知识库、Skills、MCP 或工具完成任务。"
        ),
        "kb_ids": [],
        "skill_ids": [],
        "mcp_ids": [],
        "memory_enabled": False,
        "thinking_enabled": False,
        "thinking_budget": 8000,
        "reasoning_mode": body.details.get("reasoning_mode") or "balanced",
        "allow_subagents": True,
        "avatar_color": "emerald",
    }
    return {"kind": "agent", "summary": _summary("Agent", draft), "draft": draft}


@router.post("/skill/draft")
async def draft_skill(body: DraftRequest):
    goal = body.goal.strip()
    skill_id = _slug(body.details.get("id") or goal, "custom-skill")
    name = body.details.get("name") or skill_id
    content = "\n".join(
        [
            f"# {name}",
            "",
            "## 适用场景",
            goal or "用户请求与该能力描述匹配时使用。",
            "",
            "## 工作流程",
            "1. 先确认输入、输出和约束。",
            "2. 分解任务并选择可用工具。",
            "3. 输出可验证、可复用的结果。",
            "",
            "## 输出要求",
            "- 说明关键假设。",
            "- 给出下一步建议。",
        ]
    )
    draft = {
        "id": skill_id,
        "name": name,
        "description": body.details.get("description") or goal,
        "content": content,
    }
    return {"kind": "skill", "summary": _summary("Skill", draft), "draft": draft}


@router.post("/mcp/draft")
async def draft_mcp(body: DraftRequest):
    goal = body.goal.strip()
    server_id = _slug(body.details.get("id") or goal, "custom-mcp")
    draft = {
        "id": server_id,
        "name": body.details.get("name") or server_id,
        "description": body.details.get("description") or goal,
        "transport": body.details.get("transport") or "stdio",
        "command": body.details.get("command", "").split() if body.details.get("command") else [],
        "url": body.details.get("url") or "",
        "env": {},
        "enabled": True,
    }
    return {"kind": "mcp", "summary": _summary("MCP", draft), "draft": draft}


@router.post("/agent/save", status_code=201)
async def save_agent(body: SaveRequest):
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    draft = body.draft
    if not str(draft.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="Agent name is required")

    async with AsyncSessionLocal() as session:
        agent = AgentConfig(
            name=str(draft["name"]).strip(),
            description=str(draft.get("description") or ""),
            base_type=str(draft.get("base_type") or "chatbot"),
            model_name=str(draft.get("model_name") or "") or None,
            system_prompt=str(draft.get("system_prompt") or ""),
            memory_enabled=bool(draft.get("memory_enabled", False)),
            thinking_enabled=bool(draft.get("thinking_enabled", False)),
            thinking_budget=int(draft.get("thinking_budget") or 8000),
            reasoning_mode=str(draft.get("reasoning_mode") or "balanced"),
            allow_subagents=bool(draft.get("allow_subagents", True)),
            is_builtin=False,
            avatar_color=str(draft.get("avatar_color") or "emerald"),
        )
        agent.kb_ids = list(draft.get("kb_ids") or [])
        agent.skill_ids = list(draft.get("skill_ids") or [])
        agent.mcp_ids = list(draft.get("mcp_ids") or [])
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return {"saved": agent.to_dict(), "message": "Agent 已保存，可在 Agent 管理页面继续配置。"}


@router.post("/skill/save", status_code=201)
async def save_skill(body: SaveRequest):
    from app.gateway.routers.skills import SkillCustomRequest, custom

    draft = body.draft
    request = SkillCustomRequest(
        id=str(draft.get("id") or ""),
        name=str(draft.get("name") or draft.get("id") or ""),
        description=str(draft.get("description") or ""),
        content=str(draft.get("content") or ""),
    )
    saved = await custom(request)
    return {"saved": saved, "message": "Skill 已保存，可在 Skills 页面绑定给 Agent。"}


@router.post("/mcp/save", status_code=201)
async def save_mcp(body: SaveRequest):
    from app.gateway.routers.mcp import MCPCustomRequest, custom

    draft = body.draft
    request = MCPCustomRequest(
        id=str(draft.get("id") or ""),
        name=str(draft.get("name") or draft.get("id") or ""),
        description=str(draft.get("description") or ""),
        transport=str(draft.get("transport") or "stdio"),
        command=list(draft.get("command") or []),
        url=str(draft.get("url") or ""),
        env=dict(draft.get("env") or {}),
        enabled=bool(draft.get("enabled", True)),
    )
    saved = await custom(request)
    return {"saved": saved, "message": "MCP 已保存，可在 MCP 页面测试并绑定给 Agent。"}
