"""Executable Skill protocol for NexAgent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool


@dataclass
class SkillMetadata:
    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    required_mcp_ids: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)


class BaseSkill:
    """Base class for executable skills.

    A skill folder may contain both ``SKILL.md`` and ``skill.py``.  The
    Markdown file is used for prompt injection, while ``skill.py`` can expose
    LangChain tools by subclassing this class and returning them from
    ``get_tools``.
    """

    metadata = SkillMetadata(name="base")

    def get_tools(self) -> list[BaseTool]:
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.metadata.name,
            "description": self.metadata.description,
            "version": self.metadata.version,
            "tags": self.metadata.tags,
            "required_mcp_ids": self.metadata.required_mcp_ids,
            "required_tools": self.metadata.required_tools,
            "tools": [tool.name for tool in self.get_tools()],
        }
