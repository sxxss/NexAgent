"""Abstract base class for all NexAgent agents."""

from __future__ import annotations

import logging
import os
from abc import abstractmethod
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver, aiosqlite
from langgraph.graph.state import CompiledStateGraph

from nexagent.agents.context import BaseContext

logger = logging.getLogger(__name__)


class BaseAgent:
    """Foundation for LangGraph-based agents in NexAgent.

    Subclasses implement ``get_graph()`` to return a compiled LangGraph graph.
    This class provides:
    - Thread-safe SQLite checkpointing (with InMemory fallback)
    - Async streaming in both "messages" and "values" modes
    - Per-agent isolated working directories
    """

    name: str = "base_agent"
    description: str = "Base agent"
    capabilities: list[str] = []
    context_schema: type[BaseContext] = BaseContext

    def __init__(self, **kwargs) -> None:
        self._checkpointer = None
        self._async_conn = None
        self.workdir = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent")) / "agents" / self._agent_id
        self.workdir.mkdir(parents=True, exist_ok=True)

    @property
    def _agent_id(self) -> str:
        return self.__class__.__name__.lower()

    @abstractmethod
    async def get_graph(self, context: BaseContext | None = None, **kwargs) -> CompiledStateGraph:
        """Build and return the compiled LangGraph graph.

        Must call ``await self._get_checkpointer()`` and pass the result to
        ``graph.compile(checkpointer=...)``.
        """

    async def stream_messages(self, messages: list, input_context: dict | None = None, **kwargs):
        """Stream (msg, metadata) tuples from the agent graph."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)

        checkpoint_thread_id = context.checkpoint_thread_id or context.thread_id
        run_config = {
            "configurable": {
                "thread_id": checkpoint_thread_id,
                "sandbox_thread_id": context.thread_id,
                "user_id": context.user_id,
            },
            "recursion_limit": 100,
        }

        async for msg, metadata in graph.astream(
            {"messages": messages},
            stream_mode="messages",
            config=run_config,
        ):
            yield msg, metadata

    async def stream_with_state(self, messages: list, input_context: dict | None = None, **kwargs):
        """Stream (mode, payload) tuples — both message chunks and state snapshots."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)

        checkpoint_thread_id = context.checkpoint_thread_id or context.thread_id
        run_config = {
            "configurable": {
                "thread_id": checkpoint_thread_id,
                "sandbox_thread_id": context.thread_id,
                "user_id": context.user_id,
            },
            "recursion_limit": 100,
        }

        async for mode, payload in graph.astream(
            {"messages": messages},
            stream_mode=["messages", "values"],
            config=run_config,
        ):
            yield mode, payload

    async def invoke(self, messages: list, input_context: dict | None = None, **kwargs) -> dict:
        """Run the agent to completion and return the final state."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)

        checkpoint_thread_id = context.checkpoint_thread_id or context.thread_id
        run_config = {
            "configurable": {
                "thread_id": checkpoint_thread_id,
                "sandbox_thread_id": context.thread_id,
                "user_id": context.user_id,
            },
            "recursion_limit": 100,
        }
        return await graph.ainvoke({"messages": messages}, config=run_config)

    async def get_history(self, thread_id: str, user_id: str = "") -> list[dict]:
        """Return the serialized message history for a thread."""
        try:
            graph = await self.get_graph()
            config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
            state = await graph.aget_state(config)
            if not state:
                return []
            result = []
            for msg in state.values.get("messages", []):
                if hasattr(msg, "model_dump"):
                    result.append(msg.model_dump())
                else:
                    result.append({"content": str(msg)})
            return result
        except Exception as e:
            logger.error(f"get_history failed for {self.name}: {e}")
            return []

    async def get_info(self) -> dict:
        return {
            "id": self.__class__.__name__,
            "name": self.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "configurable_items": self.context_schema.get_configurable_items(),
        }

    # ── checkpointer management ─────────────────────────────────────────────

    async def _get_checkpointer(self):
        if self._checkpointer is not None:
            return self._checkpointer

        backend = os.environ.get("NEXAGENT_CHECKPOINTER", "sqlite").lower()

        if backend == "memory":
            self._checkpointer = InMemorySaver()
            return self._checkpointer

        if backend == "postgres":
            cp = await self._try_postgres_checkpointer()
            if cp:
                self._checkpointer = cp
                return self._checkpointer

        try:
            conn = await self._get_async_conn()
            self._checkpointer = AsyncSqliteSaver(conn)
            logger.debug(f"{self.name}: using SQLite checkpointer at {self.workdir}")
        except Exception as e:
            logger.warning(f"{self.name}: SQLite checkpointer failed ({e}), falling back to in-memory")
            self._checkpointer = InMemorySaver()

        return self._checkpointer

    async def _get_async_conn(self) -> aiosqlite.Connection:
        if self._async_conn is not None:
            return self._async_conn
        db_path = self.workdir / "history.db"
        conn = await aiosqlite.connect(str(db_path))
        # langgraph's AsyncSqliteSaver needs is_alive()
        if not hasattr(conn, "is_alive"):
            conn.is_alive = lambda: True
        self._async_conn = conn
        return conn

    async def _try_postgres_checkpointer(self):
        postgres_url = os.environ.get("POSTGRES_URL")
        if not postgres_url:
            return None
        try:
            import psycopg_pool  # type: ignore
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore
            pool = psycopg_pool.AsyncConnectionPool(postgres_url, open=False)
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            logger.info(f"{self.name}: using Postgres checkpointer")
            return saver
        except Exception as e:
            logger.warning(f"{self.name}: Postgres checkpointer unavailable ({e}), falling back")
            return None
