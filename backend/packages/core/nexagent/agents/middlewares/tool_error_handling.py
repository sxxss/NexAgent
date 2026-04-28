"""Convert tool exceptions into ToolMessages so agent runs can continue."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Wrap tool calls and return a structured error message on failure."""

    def __init__(self, max_retries: int = 1, backoff_seconds: float = 0.25) -> None:
        super().__init__()
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)

    @staticmethod
    def _message(request: ToolCallRequest, exc: Exception, *, attempts: int, elapsed_ms: int) -> ToolMessage:
        name = str(request.tool_call.get("name") or "unknown_tool")
        call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."
        return ToolMessage(
            content=(
                f"Error: Tool '{name}' failed after {attempts} attempt(s) in {elapsed_ms} ms "
                f"with {exc.__class__.__name__}: {detail}. "
                f"{_recovery_hint(name, detail)}"
            ),
            tool_call_id=call_id,
            name=name,
            status="error",
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        validation_error = _validate_required_args(request)
        if validation_error:
            return _validation_message(request, validation_error)

        started_at = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                logger.warning(
                    "Tool failed; retrying name=%s id=%s attempt=%s",
                    request.tool_call.get("name"),
                    request.tool_call.get("id"),
                    attempt + 1,
                    exc_info=True,
                )
                if self.backoff_seconds:
                    time.sleep(self.backoff_seconds)
        assert last_exc is not None
        logger.error(
            "Tool failed: name=%s id=%s error=%s",
            request.tool_call.get("name"),
            request.tool_call.get("id"),
            last_exc,
        )
        return self._message(
            request,
            last_exc,
            attempts=self.max_retries + 1,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        validation_error = _validate_required_args(request)
        if validation_error:
            return _validation_message(request, validation_error)

        started_at = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                logger.warning(
                    "Async tool failed; retrying name=%s id=%s attempt=%s",
                    request.tool_call.get("name"),
                    request.tool_call.get("id"),
                    attempt + 1,
                    exc_info=True,
                )
                if self.backoff_seconds:
                    await asyncio.sleep(self.backoff_seconds)
        assert last_exc is not None
        logger.error(
            "Async tool failed: name=%s id=%s error=%s",
            request.tool_call.get("name"),
            request.tool_call.get("id"),
            last_exc,
        )
        return self._message(
            request,
            last_exc,
            attempts=self.max_retries + 1,
            elapsed_ms=int((time.monotonic() - started_at) * 1000),
        )


def _recovery_hint(tool_name: str, detail: str) -> str:
    lowered = f"{tool_name} {detail}".lower()
    if "access denied" in lowered and "outside allowed directories" in lowered:
        return (
            "The requested path is outside this tool's allowed filesystem roots. "
            "Use a path inside the allowed roots, or continue with available context "
            "and return the result inline."
        )
    return "Continue with available context or choose another tool."


def _validate_required_args(request: ToolCallRequest) -> str | None:
    name = str(request.tool_call.get("name") or "").strip()
    args = request.tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    def missing(field: str) -> str | None:
        value = args.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"Missing required tool argument: {field}."
        return None

    if name == "bash":
        return missing("command")
    if name == "execute_python":
        return missing("code")
    if name == "read_skill":
        return missing("id")
    if name == "skill_manage":
        return missing("action") or missing("id")
    return None


def _validation_message(request: ToolCallRequest, detail: str) -> ToolMessage:
    name = str(request.tool_call.get("name") or "unknown_tool")
    call_id = str(request.tool_call.get("id") or "missing_tool_call_id")
    return ToolMessage(
        content=(
            f"Error: Tool '{name}' was not executed because its input is incomplete. "
            f"{detail} Provide the required argument and call the tool again."
        ),
        tool_call_id=call_id,
        name=name,
        status="error",
    )
