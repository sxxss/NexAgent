"""Deep Research Agent - multi-agent research pipeline.

Architecture (Supervisor pattern):
  Planner  →  Researcher (×N steps)  →  Writer

The Planner decomposes the query into structured research steps.
Each Researcher step executes tools (web search, knowledge base, code).
The Writer synthesizes all findings into a formatted Markdown report.
"""

from nexagent.agents.builtin.deep_research.agent import DeepResearchAgent

__all__ = ["DeepResearchAgent"]
