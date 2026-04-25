"""Token usage accounting middleware."""

from __future__ import annotations

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TokenUsageMiddleware(AgentMiddleware[AgentState]):
    """Accumulate token usage from model response metadata."""

    @staticmethod
    def _usage_from_state(state: AgentState) -> dict[str, int]:
        messages = state.get("messages") or []
        if not messages:
            return {}
        usage = getattr(messages[-1], "usage_metadata", None) or {}
        if not usage:
            metadata = getattr(messages[-1], "response_metadata", None) or {}
            usage = metadata.get("token_usage") or {}
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    def _log(self, state: AgentState, runtime: Runtime) -> None:
        usage = self._usage_from_state(state)
        if any(usage.values()):
            logger.debug("Token usage thread=%s usage=%s", (runtime.context or {}).get("thread_id"), usage)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> None:
        self._log(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> None:
        self._log(state, runtime)
