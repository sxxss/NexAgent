"""Reusable Skill validation and runtime dependency checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexagent.skills.loader import Skill, SkillIssue, SkillLoader


@dataclass
class SkillRuntimePlan:
    """Resolved runtime requirements for selected skills."""

    skills: list[Skill]
    required_tools: list[str] = field(default_factory=list)
    required_mcp_ids: list[str] = field(default_factory=list)
    issues: list[SkillIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


class SkillRuntimeError(RuntimeError):
    """Raised when selected skills cannot run safely."""

    def __init__(self, issues: list[SkillIssue]) -> None:
        self.issues = issues
        message = "; ".join(f"{issue.code}: {issue.message}" for issue in issues if issue.severity == "error")
        super().__init__(message or "Selected skills failed runtime validation.")


def builtin_tool_names() -> set[str]:
    from nexagent.tools.registry import list_tool_specs

    return {spec.name for spec in list_tool_specs()}


def skill_tool_names(loader: SkillLoader | None = None) -> set[str]:
    return set()


def tool_conflicts(loader: SkillLoader | None = None) -> dict[str, list[str]]:
    """Executable skill tools are no longer loaded, so conflicts cannot occur."""
    return {}


async def dependency_issues(skill: Skill, *, loader: SkillLoader | None = None) -> list[SkillIssue]:
    mcp_issues = await missing_mcp_issues(skill.required_mcp_ids)
    mcp_tool_names = await available_mcp_tool_names()
    return [
        *mcp_issues,
        *missing_tool_issues(skill.required_tools, loader=loader, extra_available_tools=mcp_tool_names),
    ]


async def missing_mcp_issues(required_mcp_ids: list[str]) -> list[SkillIssue]:
    if not required_mcp_ids:
        return []
    try:
        from nexagent.tools.mcp.registry import list_installed_mcp_servers

        installed = await list_installed_mcp_servers()
        enabled = {item["id"] for item in installed if item.get("is_enabled")}
    except Exception:
        enabled = set()
    return [
        SkillIssue(
            "error",
            "missing_mcp_dependency",
            f"Required MCP server '{server_id}' is not installed or enabled.",
            "Install and enable the MCP server before using this skill.",
        )
        for server_id in required_mcp_ids
        if server_id not in enabled
    ]


async def available_mcp_tool_names() -> set[str]:
    """Return tool names currently exposed by enabled MCP servers.

    This is intentionally best-effort: dependency validation should not fail
    the whole Skills page just because an optional MCP server is offline.
    """
    try:
        from nexagent.tools.mcp.client import load_mcp_tools

        return {tool.name for tool in await load_mcp_tools()}
    except Exception:
        return set()


def missing_tool_issues(
    required_tools: list[str],
    *,
    loader: SkillLoader | None = None,
    extra_available_tools: set[str] | None = None,
) -> list[SkillIssue]:
    if not required_tools:
        return []
    available = builtin_tool_names() | skill_tool_names(loader) | (extra_available_tools or set())
    return [
        SkillIssue(
            "error",
            "missing_tool_dependency",
            f"Required tool '{tool_name}' is not available.",
            "Enable a skill/MCP that provides this tool or update the skill metadata.",
        )
        for tool_name in required_tools
        if tool_name not in available
    ]


async def resolve_runtime_plan(
    skills: list[Skill],
    *,
    loader: SkillLoader | None = None,
    selected_tool_names: list[str] | None = None,
    selected_mcp_ids: list[str] | None = None,
    allow_subagents: bool = True,
) -> SkillRuntimePlan:
    """Validate selected skills and compute additional runtime dependencies."""
    loader = loader or SkillLoader()
    selected_tools = set(selected_tool_names or [])
    selected_mcp = set(selected_mcp_ids or [])
    required_tools = sorted({name for skill in skills for name in skill.required_tools})
    required_mcp_ids = sorted({mcp_id for skill in skills for mcp_id in skill.required_mcp_ids})

    issues: list[SkillIssue] = []
    for skill in skills:
        issues.extend(skill.validation_issues)
        issues.extend(await dependency_issues(skill, loader=loader))
    if "delegate_subagents" in required_tools and not allow_subagents:
        issues.append(
            SkillIssue(
                "error",
                "subagent_dependency_disabled",
                "Selected skill requires delegate_subagents but this agent has sub-agents disabled.",
                "Enable sub-agents on the Agent profile or remove this skill.",
            )
        )

    for mcp_id in required_mcp_ids:
        if selected_mcp_ids is not None and mcp_id not in selected_mcp:
            selected_mcp.add(mcp_id)

    for tool_name in required_tools:
        if selected_tool_names is not None and tool_name not in selected_tools:
            selected_tools.add(tool_name)

    return SkillRuntimePlan(
        skills=skills,
        required_tools=sorted(selected_tools),
        required_mcp_ids=sorted(selected_mcp),
        issues=issues,
    )


async def ensure_runtime_plan(*args: Any, **kwargs: Any) -> SkillRuntimePlan:
    plan = await resolve_runtime_plan(*args, **kwargs)
    if plan.has_errors:
        raise SkillRuntimeError(plan.issues)
    return plan
