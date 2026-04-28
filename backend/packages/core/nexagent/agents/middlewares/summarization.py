"""Lightweight conversation trimming middleware."""

from __future__ import annotations

from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime


class SummarizationMiddleware(AgentMiddleware[AgentState]):
    """Keep long histories bounded with a deterministic summary placeholder.

    This is intentionally conservative: it avoids an extra model call and only
    trims when message count is large. A future version can replace the
    placeholder with an LLM-generated summary.
    """

    def __init__(self, max_messages: int = 80, keep_messages: int = 40) -> None:
        super().__init__()
        self.max_messages = max_messages
        self.keep_messages = keep_messages

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages") or []
        if len(messages) <= self.max_messages:
            return None
        omitted = len(messages) - self.keep_messages
        return {
            "messages": [
                SystemMessage(content=f"Earlier conversation was compacted. {omitted} messages were omitted."),
                *messages[-self.keep_messages :],
            ]
        }

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)
