"""Agent registry for NexAgent built-in and runtime agents."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from nexagent.agents.base import BaseAgent


@dataclass(frozen=True)
class AgentSpec:
    """Metadata and import path for an agent."""

    id: str
    name: str
    description: str
    capabilities: list[str]
    module: str
    class_name: str
    default: bool = False


_SPECS: dict[str, AgentSpec] = {
    "chatbot": AgentSpec(
        id="chatbot",
        name="智能对话",
        description="通用对话助手，支持模型切换、流式输出、知识库检索和工具调用。",
        capabilities=["chat", "streaming", "checkpoint", "knowledge_search", "web_search", "execute_python"],
        module="nexagent.agents.builtin.chatbot.agent",
        class_name="ChatbotAgent",
        default=True,
    ),
    "deep_research": AgentSpec(
        id="deep_research",
        name="深度研究",
        description="多阶段研究 Agent：规划、检索、分析并生成结构化报告。",
        capabilities=["planning", "web_search", "knowledge_search", "execute_python", "mcp", "report"],
        module="nexagent.agents.builtin.deep_research.agent",
        class_name="DeepResearchAgent",
    ),
}

_INSTANCES: dict[str, BaseAgent] = {}


def list_agent_specs() -> list[AgentSpec]:
    """Return registered agent specs in stable order."""
    return list(_SPECS.values())


def get_agent_spec(agent_id: str) -> AgentSpec:
    try:
        return _SPECS[agent_id]
    except KeyError as exc:
        available = ", ".join(_SPECS)
        raise ValueError(f"Unknown agent: '{agent_id}'. Available: {available}") from exc


def get_default_agent_id() -> str:
    for spec in _SPECS.values():
        if spec.default:
            return spec.id
    return next(iter(_SPECS))


def get_agent_class(agent_id: str) -> type[BaseAgent]:
    spec = get_agent_spec(agent_id)
    module = import_module(spec.module)
    cls = getattr(module, spec.class_name)
    if not issubclass(cls, BaseAgent):
        raise TypeError(f"Agent class {spec.class_name} must inherit BaseAgent")
    return cls


def get_agent(agent_id: str) -> BaseAgent:
    """Return or lazily instantiate an agent by ID."""
    if agent_id not in _INSTANCES:
        _INSTANCES[agent_id] = get_agent_class(agent_id)()
    return _INSTANCES[agent_id]


def reset_agent_cache() -> None:
    """Clear cached agent instances. Intended for tests and dev reloads."""
    _INSTANCES.clear()
