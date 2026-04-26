"""KnowledgeMiddleware — injects a ``query_kb`` tool into the agent.

Usage::

    from nexagent.agents.middlewares.knowledge_middleware import KnowledgeMiddleware

    class MyAgent(BaseAgent):
        def _build_graph(self):
            middleware = KnowledgeMiddleware(kb_ids=["kb-uuid-1", "kb-uuid-2"])
            return create_agent(self.model, tools=[*my_tools, *middleware.tools], ...)

The injected tool is a standard LangChain ``StructuredTool`` so the agent can
call it with ``{"kb_id": "...", "query": "..."}`` and receive a plain-text
answer drawn from the knowledge base.
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Tool input schema ─────────────────────────────────────────────────────────

class QueryKBInput(BaseModel):
    kb_id: str = Field(description="The ID of the knowledge base to search.")
    query: str = Field(description="The natural-language question or search query.")
    top_k: int = Field(default=5, description="Number of results to return.")
    mode: str = Field(default="hybrid", description="vector, keyword, hybrid, or a LightRAG mode.")


# ── Tool implementation ───────────────────────────────────────────────────────

async def _query_kb(kb_id: str, query: str, top_k: int = 5, mode: str = "hybrid") -> str:
    """Search a knowledge base and return formatted results."""
    try:
        from nexagent.knowledge.search_service import structured_retrieve
        from nexagent.tools.builtin.knowledge_search import _format_tool_result

        result = await structured_retrieve(query=query, kb_ids=[kb_id], mode=mode, top_k=max(1, min(top_k, 10)))
        return _format_tool_result(query=query, result=result, top_k=max(1, min(top_k, 10)))
    except KeyError:
        return f"Knowledge base '{kb_id}' not found."
    except Exception as exc:
        logger.warning("Knowledge search failed: %s", exc)
        return f"Knowledge base search failed: {exc}"


def make_query_kb_tool(kb_ids: list[str] | None = None) -> StructuredTool:
    """Build the ``query_kb`` LangChain tool.

    Args:
        kb_ids: Optional whitelist of allowed KB IDs. When provided, the tool
                description lists them so the LLM knows which bases exist.
    """
    kb_hint = ""
    if kb_ids:
        kb_hint = f"  Available KB IDs: {', '.join(kb_ids)}."

    async def _scoped_query_kb(kb_id: str, query: str, top_k: int = 5, mode: str = "hybrid") -> str:
        if kb_ids and kb_id not in kb_ids:
            return f"Knowledge base '{kb_id}' is not available to this agent."
        return await _query_kb(kb_id=kb_id, query=query, top_k=top_k, mode=mode)

    return StructuredTool.from_function(
        coroutine=_scoped_query_kb,
        name="query_kb",
        description=(
            "Search a knowledge base for information relevant to a query. "
            "Use this tool when you need domain-specific knowledge from uploaded documents."
            + kb_hint
        ),
        args_schema=QueryKBInput,
    )


# ── Middleware class ──────────────────────────────────────────────────────────

class KnowledgeMiddleware:
    """Provides knowledge-base tools to an agent.

    Example::

        middleware = KnowledgeMiddleware(kb_ids=["kb-abc"])
        agent = create_agent(model, tools=[*base_tools, *middleware.tools], ...)
    """

    def __init__(self, kb_ids: list[str] | None = None) -> None:
        self._kb_ids = kb_ids

    @property
    def tools(self) -> list[StructuredTool]:
        """Return the list of LangChain tools to add to the agent."""
        return [make_query_kb_tool(self._kb_ids)]
