"""Agent state schema for LangGraph graphs."""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import MessagesState


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Merge artifact file paths — preserve order, remove duplicates."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    return list(dict.fromkeys(existing + new))


class BaseState(MessagesState):
    """Shared state for all NexAgent agents.

    Extends LangGraph's MessagesState (which provides the ``messages`` field with
    the ``add_messages`` reducer) with NexAgent-specific fields.
    """

    # Paths to output artifacts produced during this conversation
    artifacts: Annotated[list[str], merge_artifacts]
    # Required by LangGraph's prebuilt create_react_agent executor.
    remaining_steps: int


class AgentStatePayload(TypedDict):
    """Serialized state snapshot sent to the frontend over SSE."""

    artifacts: list[str]
