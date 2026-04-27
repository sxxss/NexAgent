"""Detect repeated tool-call loops and force the agent to wrap up."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime


class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    """Inject a warning when the same tool call repeats too many times."""

    def __init__(self, warn_threshold: int = 3, hard_limit: int = 5, window_size: int = 20) -> None:
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self._history: dict[str, deque[str]] = defaultdict(lambda: deque(maxlen=self.window_size))
        self._warned: set[tuple[str, str]] = set()

    @staticmethod
    def _hash_tool_calls(tool_calls: list[dict]) -> str:
        normalized = []
        for call in tool_calls:
            args = call.get("args") or {}
            if not isinstance(args, dict):
                args = {"raw": str(args)}
            normalized.append({"name": call.get("name"), "args": args})
        blob = json.dumps(sorted(normalized, key=lambda item: str(item)), sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _thread_id(runtime: Runtime) -> str:
        return str((runtime.context or {}).get("thread_id") or "default")

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        calls = getattr(last, "tool_calls", None) or []
        if not calls:
            return None

        thread_id = self._thread_id(runtime)
        call_hash = self._hash_tool_calls(list(calls))
        history = self._history[thread_id]
        history.append(call_hash)
        count = sum(1 for item in history if item == call_hash)

        if count >= self.hard_limit:
            stripped = last.model_copy(
                update={
                    "tool_calls": [],
                    "content": str(getattr(last, "content", "") or "")
                    + "\n\n[FORCED STOP] Repeated tool calls exceeded the safety limit. Produce a final answer now.",
                }
            )
            return {"messages": [stripped]}

        warning_key = (thread_id, call_hash)
        if count >= self.warn_threshold and warning_key not in self._warned:
            self._warned.add(warning_key)
            return {
                "messages": [
                    HumanMessage(
                        content=(
                            "[LOOP DETECTED] You are repeating the same tool call. "
                            "Stop looping and produce a final answer."
                        )
                    )
                ]
            }
        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)
