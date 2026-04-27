"""Invocation logging middleware — writes one InvocationLog per chat turn."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

logger = logging.getLogger(__name__)


async def logged_stream(
    generator: AsyncGenerator[dict, None],
    agent_id: str,
    agent_name: str,
    thread_id: str,
    model_name: str,
    thinking_enabled: bool = False,
    reasoning_mode: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Wrap an SSE generator and persist an InvocationLog entry when it finishes."""

    start = time.monotonic()
    input_tokens = 0
    output_tokens = 0
    raw_input_tokens = 0
    raw_output_tokens = 0
    token_source = "provider_reported"
    token_estimated = False
    tools_used: list[str] = []
    status = "success"
    error_msg: str | None = None
    cancelled = False

    try:
        async for chunk in generator:
            # Accumulate token usage from 'finished' event
            if chunk.get("status") == "finished":
                from nexagent.token_usage import usage_from_mapping

                usage = chunk.get("usage", {})
                normalized = usage_from_mapping(usage, source="finished_event")
                input_tokens = int(normalized["input_tokens"])
                output_tokens = int(normalized["output_tokens"])
                raw_input_tokens = int(normalized.get("raw_input_tokens") or input_tokens)
                raw_output_tokens = int(normalized.get("raw_output_tokens") or output_tokens)
                token_source = str(normalized.get("token_source") or token_source)
                token_estimated = bool(normalized.get("token_estimated") or normalized.get("estimated") or False)
            elif chunk.get("status") == "tool_call":
                tool_name = chunk.get("tool", "")
                if tool_name and tool_name not in tools_used:
                    tools_used.append(tool_name)
            elif chunk.get("status") == "error":
                status = "error"
                error_msg = chunk.get("error", "")
            elif chunk.get("status") == "interrupted":
                status = "interrupted"
            yield chunk
    except asyncio.CancelledError:
        status = "interrupted"
        cancelled = True
        raise
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        raise
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        payload = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "thread_id": thread_id,
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "raw_input_tokens": raw_input_tokens,
            "raw_output_tokens": raw_output_tokens,
            "token_source": token_source,
            "token_estimated": token_estimated,
            "latency_ms": latency_ms,
            "status": status,
            "error_msg": error_msg,
            "tools_used": tools_used,
            "thinking_enabled": thinking_enabled,
            "reasoning_mode": reasoning_mode,
        }
        current_task = asyncio.current_task()
        if cancelled or (current_task is not None and current_task.cancelling()):
            _schedule_log_write(payload)
        else:
            await _write_log(**payload)


def _schedule_log_write(payload: dict[str, Any]) -> None:
    try:
        task = asyncio.create_task(_write_log(**payload))
        task.add_done_callback(_consume_background_log_error)
    except RuntimeError as exc:
        logger.debug("Could not schedule invocation log write: %s", exc)


def _consume_background_log_error(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Background invocation log write was cancelled")
    except Exception as exc:
        logger.debug("Background invocation log write failed: %s", exc)


async def _write_log(**kwargs: Any) -> None:
    try:
        from nexagent.db.models import InvocationLog
        from nexagent.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            log = InvocationLog(id=str(uuid.uuid4()), **kwargs)
            log.tools_used = kwargs.get("tools_used", [])
            session.add(log)
            await session.commit()
    except Exception as exc:
        logger.debug("Failed to write invocation log: %s", exc)
