from __future__ import annotations

from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class KnowledgeGraphSkill(BaseSkill):
    metadata = SkillMetadata(
        name="knowledge-graph",
        description="Inspect local knowledge graph nodes and edges.",
        version="0.1.0",
        tags=["knowledge", "graph"],
        required_tools=["knowledge_search"],
    )

    def get_tools(self):
        @tool
        async def skill_knowledge_graph_stats(kb_id: str) -> str:
            """Return local knowledge graph statistics for a knowledge base."""
            from nexagent.knowledge.manager import get_manager

            graph = await get_manager().export_graph(kb_id)
            stats = graph.get("stats", {})
            return f"nodes={stats.get('nodes', 0)}, edges={stats.get('edges', 0)}"

        return [skill_knowledge_graph_stats]
