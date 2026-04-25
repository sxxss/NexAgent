"""Simple scope-based guardrail middleware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str = ""


class GuardrailMiddleware(AgentMiddleware[AgentState]):
    """Checks runtime context for tool and KB restrictions."""

    def _check(self, runtime: Runtime) -> GuardrailResult:
        context = runtime.context or {}
        scopes = set(context.get("scopes") or ["*"])
        if "*" in scopes:
            return GuardrailResult(True)

        tools = set(context.get("tools") or [])
        if tools and "tools:use" not in scopes:
            return GuardrailResult(False, "Missing scope: tools:use")
        if any(tool in tools for tool in {"bash", "write_file", "str_replace", "execute_python"}):
            if "sandbox:execute" not in scopes:
                return GuardrailResult(False, "Missing scope: sandbox:execute")
        if context.get("kb_ids") and "knowledge:read" not in scopes:
            return GuardrailResult(False, "Missing scope: knowledge:read")
        return GuardrailResult(True)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        result = self._check(runtime)
        if result.allowed:
            return None
        return {"messages": [HumanMessage(content=f"[GUARDRAIL BLOCKED] {result.reason}")]}

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self.before_agent(state, runtime)
