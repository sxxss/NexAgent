"""State schema for the Deep Research Agent graph."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from nexagent.agents.state import merge_artifacts


class ResearchStep(TypedDict):
    """A single step in the research plan."""
    id: int
    title: str
    description: str
    tools: list[str]          # e.g. ["web_search", "knowledge_search"]
    queries: list[str]        # suggested search queries


class StepResult(TypedDict):
    """Result produced by executing one research step."""
    step_id: int
    title: str
    content: str              # raw findings (may be long)
    sources: list[str]        # URLs or filenames cited


class DeepResearchState(TypedDict):
    """Full state for the Deep Research LangGraph."""

    # Conversation messages (user query + assistant responses)
    messages: Annotated[list[BaseMessage], add_messages]

    # Original user query (set once at entry)
    query: str

    # Structured plan produced by the Planner node
    plan: list[ResearchStep] | None

    # Index of the next step to execute (0-based)
    current_step: int

    # Accumulated step results (append-only)
    step_results: Annotated[list[StepResult], operator.add]

    # Final synthesized report (set by Writer)
    report: str

    # File artifacts produced during research
    artifacts: Annotated[list[str], merge_artifacts]
