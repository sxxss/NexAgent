"""Patch incomplete tool-call histories before the next model call."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware[AgentState]):
    """Insert synthetic ToolMessages for AI tool calls that never returned."""

    @staticmethod
    def _tool_calls(message: Any) -> list[dict]:
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            return list(calls)

        raw_calls = (getattr(message, "additional_kwargs", None) or {}).get("tool_calls") or []
        normalized: list[dict] = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
            args: dict = {}
            raw_args = raw.get("args") or function.get("arguments")
            if isinstance(raw_args, dict):
                args = raw_args
            elif isinstance(raw_args, str):
                try:
                    parsed = json.loads(raw_args)
                    args = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    args = {}
            normalized.append({"id": raw.get("id"), "name": raw.get("name") or function.get("name"), "args": args})
        return normalized

    def _patch(self, messages: list) -> list | None:
        existing = {
            msg.tool_call_id
            for msg in messages
            if isinstance(msg, ToolMessage) and getattr(msg, "tool_call_id", None)
        }
        patched: list = []
        inserted = 0
        inserted_ids: set[str] = set()

        for msg in messages:
            patched.append(msg)
            if getattr(msg, "type", None) != "ai":
                continue
            for call in self._tool_calls(msg):
                call_id = call.get("id")
                if not call_id or call_id in existing or call_id in inserted_ids:
                    continue
                patched.append(
                    ToolMessage(
                        content="[Tool call was interrupted before it returned a result.]",
                        tool_call_id=call_id,
                        name=call.get("name") or "unknown",
                        status="error",
                    )
                )
                inserted_ids.add(call_id)
                inserted += 1

        if inserted == 0:
            return None
        logger.warning("Inserted %d placeholder ToolMessage(s) for dangling tool calls", inserted)
        return patched

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._patch(request.messages)
        return handler(request.override(messages=patched)) if patched is not None else handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._patch(request.messages)
        return await handler(request.override(messages=patched)) if patched is not None else await handler(request)
