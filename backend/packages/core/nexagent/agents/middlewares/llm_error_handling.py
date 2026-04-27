"""LLM error handling middleware with one retry for transient failures."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


def _is_transient_error(exc: Exception) -> bool:
    """Best-effort retry classification across provider SDKs."""
    if _is_stream_chunk_timeout(exc):
        return False
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    retryable_names = ("timeout", "ratelimit", "rate_limit", "connection", "temporar", "server")
    non_retryable_names = ("authentication", "permission", "unauthorized", "invalidrequest", "badrequest")
    if any(token in name for token in non_retryable_names) or any(token in text for token in non_retryable_names):
        return False
    return any(token in name for token in retryable_names) or any(token in text for token in retryable_names)


def _is_stream_chunk_timeout(exc: Exception) -> bool:
    """A streamed response already started and then stalled; retrying can duplicate or hang a turn."""
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    return "streamchunktimeout" in name or "no streaming chunk received" in text


class LLMErrorHandlingMiddleware(AgentMiddleware[AgentState]):
    """Retry transient model errors once before surfacing the failure."""

    def __init__(self, max_retries: int = 1, backoff_seconds: float = 0.5) -> None:
        super().__init__()
        self.max_retries = max(0, max_retries)
        self.backoff_seconds = max(0.0, backoff_seconds)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        for attempt in range(self.max_retries + 1):
            try:
                return handler(request)
            except Exception as exc:
                if attempt >= self.max_retries or not _is_transient_error(exc):
                    raise
                logger.warning("Transient model call failed; retrying attempt=%s", attempt + 1, exc_info=True)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        for attempt in range(self.max_retries + 1):
            try:
                return await handler(request)
            except Exception as exc:
                if attempt >= self.max_retries or not _is_transient_error(exc):
                    raise
                logger.warning("Transient async model call failed; retrying attempt=%s", attempt + 1, exc_info=True)
                if self.backoff_seconds:
                    await asyncio.sleep(self.backoff_seconds)
        return await handler(request)
