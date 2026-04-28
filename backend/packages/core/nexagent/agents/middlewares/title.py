"""Heuristic conversation title helper."""

from __future__ import annotations

from langchain_core.messages import BaseMessage


def generate_title(messages: list[BaseMessage], max_length: int = 48) -> str:
    """Generate a stable short title from the first user message."""
    for message in messages:
        if getattr(message, "type", None) not in {"human", "user"}:
            continue
        content = str(getattr(message, "content", "")).strip().replace("\n", " ")
        if not content:
            continue
        return content[: max_length - 1] + "..." if len(content) > max_length else content
    return "New conversation"
