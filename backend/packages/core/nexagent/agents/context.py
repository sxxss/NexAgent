"""Agent runtime context — configurable parameters passed to each agent invocation."""

from __future__ import annotations

import uuid
from dataclasses import MISSING, dataclass, field, fields
from typing import Annotated, get_args, get_origin, get_type_hints


def _default_model() -> str:
    """Read default model name from config.yaml, then env, then hard default."""
    import os
    try:
        from nexagent.config import get_config
        cfg = get_config()
        if cfg.default_model:
            return cfg.default_model
    except Exception:
        pass
    return os.environ.get("NEXAGENT_DEFAULT_MODEL", "openai/gpt-4o-mini")


def _model_options() -> list[dict]:
    try:
        from nexagent.config import get_config
        return [
            {
                "label": model.display_name or model.name,
                "value": model.name,
                "provider": model.provider,
            }
            for model in get_config().models
        ]
    except Exception:
        return []


def _skill_options() -> list[dict]:
    """Return available skill names for the UI skill selector."""
    try:
        from nexagent.skills.loader import SkillLoader
        loader = SkillLoader()
        skills = loader.load_all()
        return [{"label": s.name, "value": s.name, "description": s.description} for s in skills]
    except Exception:
        return []


def _mcp_options() -> list[dict]:
    """Return installed MCP server ids for runtime configuration UIs."""
    return []


@dataclass(kw_only=True)
class BaseContext:
    """Runtime configuration for a single agent invocation.

    Fields annotated with ``__template_metadata__`` are exposed to the
    frontend for dynamic UI generation (model picker, tool selector, etc.).
    Fields with ``configurable: False`` in metadata are hidden from the UI.
    """

    thread_id: str = field(
        default_factory=lambda: str(uuid.uuid4()),
        metadata={"name": "Thread ID", "configurable": False,
                  "description": "Unique conversation thread identifier"},
    )

    checkpoint_thread_id: str = field(
        default="",
        metadata={"hide": True, "description": "Internal LangGraph checkpoint thread id for this run."},
    )

    user_id: str = field(
        default_factory=lambda: str(uuid.uuid4()),
        metadata={"name": "User ID", "configurable": False,
                  "description": "Unique user identifier"},
    )

    agent_config_id: str = field(
        default="",
        metadata={"hide": True, "description": "Resolved Agent configuration id for this run."},
    )

    agent_name: str = field(
        default="",
        metadata={"hide": True, "description": "Resolved Agent display name for this run."},
    )

    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default="You are a helpful AI assistant powered by NexAgent.",
        metadata={"name": "System Prompt", "description": "Defines the agent's role and behavior"},
    )

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default_factory=_default_model,
        metadata={
            "name": "Model",
            "options": _model_options,
            "description": "LLM driving this agent. Use provider/model format, e.g. openai/gpt-4o.",
        },
    )

    tools: Annotated[list[str], {"__template_metadata__": {"kind": "tools"}}] = field(
        default_factory=list,
        metadata={"name": "Tools", "description": "Built-in tools enabled for this agent."},
    )

    tools_explicit: bool = field(
        default=False,
        metadata={"hide": True, "description": "Whether tools were explicitly supplied by the request."},
    )

    kb_ids: Annotated[list[str], {"__template_metadata__": {"kind": "knowledge_bases"}}] = field(
        default_factory=list,
        metadata={"name": "Knowledge Bases",
                  "description": "Knowledge base IDs available to this run."},
    )

    skills: Annotated[list[str], {"__template_metadata__": {"kind": "skills"}}] = field(
        default_factory=list,
        metadata={
            "name": "Skills",
            "options": _skill_options,
            "description": "Skills to inject into the agent system prompt.",
        },
    )

    mcp_ids: Annotated[list[str], {"__template_metadata__": {"kind": "mcp_servers"}}] = field(
        default_factory=list,
        metadata={
            "name": "MCP Servers",
            "options": _mcp_options,
            "description": "Installed MCP server IDs available to this run.",
        },
    )

    allow_subagents: bool = field(
        default=False,
        metadata={
            "name": "Allow Sub-Agents",
            "description": "Allow this run to delegate independent tasks to other agents.",
        },
    )

    allowed_agent_ids: list[str] = field(
        default_factory=list,
        metadata={
            "name": "Allowed Sub-Agent IDs",
            "description": "Optional whitelist of agents this run may delegate to. Empty means all agents.",
        },
    )

    subagent_model_strategy: str = field(
        default="agent_default",
        metadata={
            "name": "Sub-Agent Model Strategy",
            "description": "How delegated sub-agents choose models: main_agent, agent_default, or custom.",
        },
    )

    subagent_model: str | None = field(
        default=None,
        metadata={
            "name": "Sub-Agent Model",
            "description": "Model used when subagent_model_strategy is custom.",
        },
    )

    thinking: bool = field(
        default=False,
        metadata={
            "name": "Thinking Mode",
            "description": "Enable provider-specific extended thinking when supported.",
        },
    )

    thinking_budget: int = field(
        default=8000,
        metadata={
            "name": "Thinking Budget",
            "description": "Maximum thinking tokens for providers that support it.",
        },
    )

    reasoning_mode: str = field(
        default="balanced",
        metadata={
            "name": "Reasoning Mode",
            "description": "Reasoning profile: fast, balanced, deep, or ultra.",
            "options": [
                {"label": "Fast", "value": "fast"},
                {"label": "Balanced", "value": "balanced"},
                {"label": "Deep", "value": "deep"},
                {"label": "Ultra", "value": "ultra"},
            ],
        },
    )

    reasoning_effort: str | None = field(
        default=None,
        metadata={
            "name": "Reasoning Effort",
            "description": "Provider reasoning effort: minimal, low, medium, or high.",
        },
    )

    planning_enabled: bool = field(
        default=False,
        metadata={
            "name": "Planning Mode",
            "description": "Ask the agent to plan before executing when the task is non-trivial.",
        },
    )

    def update_from_dict(self, data: dict) -> None:
        """Apply a dict of values onto this context (ignores unknown keys)."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @classmethod
    def get_configurable_items(cls) -> dict:
        """Return UI-renderable schema for all configurable fields."""
        # get_type_hints with include_extras=True preserves Annotated metadata.
        # This is necessary when `from __future__ import annotations` is active,
        # which causes dataclass f.type to be a plain string rather than a type object.
        try:
            hints = get_type_hints(cls, include_extras=True)
        except Exception:
            hints = {}

        result = {}
        for f in fields(cls):
            if not f.init:
                continue
            if f.metadata.get("configurable", True) is False:
                continue
            if f.metadata.get("hide", False):
                continue

            # Use resolved hint when available, fall back to string f.type
            resolved_type = hints.get(f.name, f.type)
            type_name = cls._get_type_name(resolved_type)
            template_metadata = cls._extract_template_metadata(resolved_type)
            options = f.metadata.get("options", [])
            if callable(options):
                options = options()

            default = (
                f.default
                if f.default is not MISSING
                else (f.default_factory() if f.default_factory is not MISSING else None)
            )

            result[f.name] = {
                "type": f.metadata.get("type", type_name),
                "name": f.metadata.get("name", f.name),
                "options": options,
                "default": default,
                "description": f.metadata.get("description", ""),
                "template_metadata": template_metadata,
            }
        return result

    # ── internal helpers ────────────────────────────────────────────────────

    @classmethod
    def _get_type_name(cls, field_type) -> str:
        """Return a human-readable type name, unwrapping Annotated wrappers."""
        # Unwrap Annotated[X, ...] → recurse on X
        if get_origin(field_type) is Annotated:
            args = get_args(field_type)
            return cls._get_type_name(args[0]) if args else "unknown"

        origin = get_origin(field_type)
        if origin is not None:
            if hasattr(origin, "__name__"):
                return origin.__name__
            return str(origin)
        if hasattr(field_type, "__name__"):
            return field_type.__name__
        return str(field_type)

    @classmethod
    def _extract_template_metadata(cls, field_type) -> dict:
        """Extract ``__template_metadata__`` dict from an Annotated type hint."""
        if get_origin(field_type) is Annotated:
            for meta in get_args(field_type)[1:]:
                if isinstance(meta, dict) and "__template_metadata__" in meta:
                    return meta["__template_metadata__"]
        return {}
