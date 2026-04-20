"""Agent middleware that prepares a per-thread sandbox before execution."""

from __future__ import annotations

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class SandboxMiddleware(AgentMiddleware[AgentState]):
    """Acquire a sandbox at run start and release it at run end."""

    def __init__(self) -> None:
        super().__init__()
        self._sandboxes: dict[str, object] = {}

    @staticmethod
    def _thread_id(runtime: Runtime) -> str:
        return str((runtime.context or {}).get("thread_id") or "default")

    async def _acquire(self, runtime: Runtime) -> None:
        from nexagent.config import get_config
        from nexagent.sandbox.sandbox import get_sandbox_provider

        if not get_config().sandbox.enabled:
            return
        thread_id = self._thread_id(runtime)
        sandbox = await get_sandbox_provider().acquire(thread_id)
        self._sandboxes[thread_id] = sandbox
        logger.debug("Acquired sandbox for thread %s", thread_id)

    async def _release(self, runtime: Runtime) -> None:
        from nexagent.sandbox.sandbox import get_sandbox_provider

        thread_id = self._thread_id(runtime)
        sandbox = self._sandboxes.pop(thread_id, None)
        if sandbox is not None:
            await get_sandbox_provider().release(sandbox)
            logger.debug("Released sandbox for thread %s", thread_id)

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> None:
        await self._acquire(runtime)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> None:
        await self._release(runtime)
