from __future__ import annotations

from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class DeepResearchSkill(BaseSkill):
    metadata = SkillMetadata(
        name="deep-research",
        description="Delegate a focused research task to the built-in deep_research agent.",
        version="0.1.0",
        tags=["research", "delegation"],
        required_tools=["web_search", "web_fetch", "delegate_subagents"],
    )

    def get_tools(self):
        @tool
        async def skill_run_deep_research(query: str, model: str = "fake") -> str:
            """Run the deep_research agent for a focused query and return its response."""
            from nexagent.services.chat_service import invoke_chat

            result = await invoke_chat(
                query,
                agent_name="deep_research",
                context_overrides={"model": model, "tools": ["none"]},
            )
            return str(result.get("response", ""))

        return [skill_run_deep_research]
