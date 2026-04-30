"""Agent middleware assembly."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware

from nexagent.agents.middlewares.dangling_tool_call import DanglingToolCallMiddleware
from nexagent.agents.middlewares.llm_error_handling import LLMErrorHandlingMiddleware
from nexagent.agents.middlewares.loop_detection import LoopDetectionMiddleware
from nexagent.agents.middlewares.summarization import SummarizationMiddleware
from nexagent.agents.middlewares.token_usage import TokenUsageMiddleware
from nexagent.agents.middlewares.tool_error_handling import ToolErrorHandlingMiddleware
from nexagent.guardrails import GuardrailMiddleware
from nexagent.sandbox.middleware import SandboxMiddleware


def build_agent_middlewares() -> list[AgentMiddleware]:
    """Build the default DeerFlow-inspired runtime middleware chain."""
    return [
        GuardrailMiddleware(),
        SandboxMiddleware(),
        SummarizationMiddleware(),
        DanglingToolCallMiddleware(),
        LLMErrorHandlingMiddleware(),
        LoopDetectionMiddleware(),
        TokenUsageMiddleware(),
        ToolErrorHandlingMiddleware(),
    ]


__all__ = [
    "DanglingToolCallMiddleware",
    "LLMErrorHandlingMiddleware",
    "LoopDetectionMiddleware",
    "SummarizationMiddleware",
    "TokenUsageMiddleware",
    "ToolErrorHandlingMiddleware",
    "SandboxMiddleware",
    "build_agent_middlewares",
]
