from __future__ import annotations

from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class KnowledgeBaseSkill(BaseSkill):
    metadata = SkillMetadata(
        name="knowledge-base",
        description="Search configured NexAgent knowledge bases.",
        version="0.1.0",
        tags=["knowledge", "rag"],
        required_tools=["knowledge_search"],
    )

    def get_tools(self):
        @tool
        async def skill_search_knowledge(kb_id: str, query: str, top_k: int = 5) -> str:
            """Search a NexAgent knowledge base by id."""
            from nexagent.knowledge.manager import get_manager

            results = await get_manager().search(kb_id, query, top_k=top_k)
            if not results:
                return "No matching knowledge base results."
            return "\n\n".join(f"[{i + 1}] {item.content}" for i, item in enumerate(results))

        return [skill_search_knowledge]
