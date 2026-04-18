"""Sub-agent delegation tool."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field


class SubAgentToolTask(BaseModel):
    """A single delegated task."""

    agent: str = Field(default="chatbot", description="Agent id or runtime agent name to execute.")
    message: str = Field(..., description="Task instruction for the delegated agent.")
    model: str | None = Field(default=None, description="Optional model override.")
    tools: list[str] = Field(default_factory=list, description="Optional built-in tools for this task.")
    kb_ids: list[str] = Field(default_factory=list, description="Optional knowledge base ids.")
    mcp_ids: list[str] = Field(default_factory=list, description="Optional MCP server ids.")
    skill_ids: list[str] = Field(default_factory=list, description="Optional skill ids.")


class DelegateSubAgentsInput(BaseModel):
    """Input schema for delegate_subagents."""

    tasks: list[SubAgentToolTask] = Field(..., min_length=1, max_length=8)
    max_concurrency: int = Field(default=3, ge=1, le=5)
    timeout_seconds: int = Field(default=900, ge=5, le=3600)


def get_subagent_tool(
    allowed_agent_ids: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    allowed_kb_ids: list[str] | None = None,
    allowed_mcp_ids: list[str] | None = None,
    allowed_skill_ids: list[str] | None = None,
    model_strategy: str = "agent_default",
    parent_model: str | None = None,
    custom_model: str | None = None,
):
    """Return a tool that runs multiple sub-agents concurrently."""

    allowed = set(allowed_agent_ids or [])
    resolved_model_strategy = _normalize_model_strategy(model_strategy)

    @tool("delegate_subagents", args_schema=DelegateSubAgentsInput)
    async def delegate_subagents(
        tasks: list[SubAgentToolTask],
        max_concurrency: int = 3,
        timeout_seconds: int = 900,
    ) -> str:
        """Delegate independent subtasks to other agents and aggregate their answers.

        Use this when a task can be split into independent research, analysis, or
        implementation subtasks. Each task should include an agent and a message.
        """
        from nexagent.services.subagent_service import SubAgentPolicy, SubAgentTask, run_subagents

        normalized: list[SubAgentTask] = []
        for item in tasks:
            data: dict[str, Any] = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            agent_id = str(data.get("agent") or "chatbot")
            if allowed and agent_id not in allowed:
                continue
            message = str(data.get("message") or "").strip()
            if not message:
                continue
            normalized.append(
                SubAgentTask(
                    agent=agent_id,
                    message=message,
                    model=_resolve_task_model(
                        requested=data.get("model"),
                        strategy=resolved_model_strategy,
                        parent_model=parent_model,
                        custom_model=custom_model,
                    ),
                    tools=list(data.get("tools") or []),
                    kb_ids=list(data.get("kb_ids") or []),
                    mcp_ids=list(data.get("mcp_ids") or []),
                    skill_ids=list(data.get("skill_ids") or []),
                )
            )

        if not normalized:
            return "No valid sub-agent tasks were provided."

        policy = SubAgentPolicy(
            allowed_agent_ids=allowed_agent_ids,
            allowed_tools=allowed_tools,
            allowed_kb_ids=allowed_kb_ids,
            allowed_mcp_ids=allowed_mcp_ids,
            allowed_skill_ids=allowed_skill_ids,
        )
        result = await run_subagents(
            normalized,
            max_concurrency=max_concurrency,
            timeout_seconds=timeout_seconds,
            policy=policy,
        )
        lines = [
            f"Sub-agent run {result['run_id']} completed: "
            f"{result['succeeded']} succeeded, {result['failed']} failed."
        ]
        for item in result["results"]:
            label = f"[{item['index'] + 1}] {item['agent']}"
            if item["status"] == "completed":
                lines.append(f"{label}: {item['response']}")
            else:
                lines.append(f"{label}: ERROR - {item.get('error', 'unknown error')}")
        lines.append("")
        lines.append("```nexagent-subagents")
        lines.append(_json_dumps(result))
        lines.append("```")
        return "\n\n".join(lines)

    return delegate_subagents


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def _normalize_model_strategy(value: str | None) -> str:
    if value in {"main_agent", "agent_default", "custom"}:
        return value
    return "agent_default"


def _resolve_task_model(
    *,
    requested: str | None,
    strategy: str,
    parent_model: str | None,
    custom_model: str | None,
) -> str | None:
    if strategy == "main_agent":
        return parent_model or requested
    if strategy == "custom":
        return custom_model or requested
    return None
