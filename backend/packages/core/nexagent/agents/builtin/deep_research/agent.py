"""Deep Research Agent — orchestrates Planner → Researcher(s) → Writer."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from nexagent.agents.base import BaseAgent
from nexagent.agents.builtin.deep_research.nodes import (
    planner_node,
    researcher_node,
    should_continue,
    writer_node,
)
from nexagent.agents.builtin.deep_research.state import DeepResearchState
from nexagent.agents.context import BaseContext

logger = logging.getLogger(__name__)


class DeepResearchAgent(BaseAgent):
    """Multi-step research agent.

    Graph topology:
        START → planner → researcher ─(loop)─ writer → END
                              ↑         ↓ (more steps)
                              └─────────┘
    """

    name = "deep_research"
    description = (
        "Multi-step deep research agent: decomposes complex questions into "
        "a research plan, gathers information with web search + knowledge base, "
        "then synthesises a comprehensive Markdown report."
    )
    capabilities = ["web_search", "knowledge_search", "execute_python", "mcp"]

    async def get_graph(self, context: BaseContext | None = None, **kwargs):
        context = context or self.context_schema()
        checkpointer = await self._get_checkpointer()

        graph = StateGraph(DeepResearchState)

        # Add nodes
        graph.add_node("planner", planner_node)
        graph.add_node("researcher", researcher_node)
        graph.add_node("writer", writer_node)

        # Entry: start with planner
        graph.add_edge(START, "planner")

        # After planning: go to researcher (first step)
        graph.add_edge("planner", "researcher")

        # After each research step: check if more steps remain
        graph.add_conditional_edges(
            "researcher",
            should_continue,
            {"researcher": "researcher", "writer": "writer"},
        )

        # Writer → end
        graph.add_edge("writer", END)

        return graph.compile(checkpointer=checkpointer)

    async def stream_messages(self, messages: list, input_context: dict | None = None, **kwargs):
        """Override to inject `query` into the initial state."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        initial_state = self._build_initial_state(messages)
        run_config = self._build_run_config(context, input_context)

        async for msg, metadata in graph.astream(
            initial_state,
            stream_mode="messages",
            config=run_config,
        ):
            yield msg, metadata

    async def stream_with_state(self, messages: list, input_context: dict | None = None, **kwargs):
        """Override to inject `query` and stream both messages + state."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        initial_state = self._build_initial_state(messages)
        run_config = self._build_run_config(context, input_context)

        async for mode, payload in graph.astream(
            initial_state,
            stream_mode=["messages", "values"],
            config=run_config,
        ):
            yield mode, payload

    async def invoke(self, messages: list, input_context: dict | None = None, **kwargs) -> dict:
        """Run deep research to completion with the full DeepResearchState."""
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        return await graph.ainvoke(
            self._build_initial_state(messages),
            config=self._build_run_config(context, input_context),
        )

    def _build_initial_state(self, messages: list) -> dict:
        query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                query = msg.content if isinstance(msg.content, str) else str(msg.content)
                break

        return {
            "messages": messages,
            "query": query,
            "plan": None,
            "current_step": 0,
            "step_results": [],
            "report": "",
            "artifacts": [],
        }

    def _build_run_config(self, context: BaseContext, input_context: dict | None = None) -> dict:
        model = (input_context or {}).get("model", "")
        return {
            "configurable": {
                "thread_id": context.thread_id,
                "user_id": context.user_id,
                "model": model,
                "mcp_ids": context.mcp_ids,
                "thinking": context.thinking,
                "thinking_budget": context.thinking_budget,
                "reasoning_mode": context.reasoning_mode,
                "reasoning_effort": context.reasoning_effort,
                "planning_enabled": context.planning_enabled,
            },
            "recursion_limit": 50,
        }
