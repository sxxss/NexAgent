"""LangGraph node implementations for the Deep Research Agent.

Nodes
-----
planner_node    — decomposes query → structured ResearchPlan
researcher_node — executes one step using selected tools
writer_node     — synthesises all results → final Markdown report
should_continue — routing function: more steps? → researcher, else → writer
"""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from nexagent.agents.builtin.deep_research.state import (
    DeepResearchState,
    ResearchStep,
    StepResult,
)
from nexagent.models.factory import load_chat_model

logger = logging.getLogger(__name__)

# ── Pydantic schemas for structured LLM output ───────────────────────────────

class PlanStep(BaseModel):
    id: int = Field(description="Step number, starting from 1")
    title: str = Field(description="Short title for this research step (max 10 words)")
    description: str = Field(description="What to find or analyse in this step")
    tools: list[str] = Field(
        description="Tools to use: web_search, web_fetch, knowledge_search, execute_python"
    )
    queries: list[str] = Field(
        description="2-3 specific search queries or sub-questions for this step"
    )

class ResearchPlan(BaseModel):
    steps: list[PlanStep] = Field(
        description="Ordered list of research steps, max 5 steps"
    )
    expected_output: str = Field(
        description="One sentence describing the expected final report"
    )


# ── System prompts ────────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """You are an expert research planner. Given a user's question or task,
create a structured research plan with clear, actionable steps.

Rules:
- Break the task into 2-5 focused steps (no more)
- Each step should use appropriate tools (web_search, web_fetch, knowledge_search, execute_python)
- For each step, provide 2-3 specific search queries or sub-questions
- Steps should build on each other logically
- Keep step titles concise (under 10 words)
- Respond ONLY with the structured plan, no preamble"""

_RESEARCHER_SYSTEM = """You are a diligent research assistant executing one step of a research plan.
Your job is to gather comprehensive, accurate information using the available tools.

Rules:
- Use the provided tools to gather relevant information
- Search with multiple queries to get diverse perspectives
- Synthesise findings clearly with key facts highlighted
- Cite sources when available
- Be thorough but concise — aim for depth over breadth
"""

_WRITER_SYSTEM = """You are an expert technical writer who synthesises research findings into
clear, well-structured Markdown reports.

Report format:
# [Title]

## Overview
[1-2 paragraph executive summary]

## [Section per research step]
[Detailed findings with inline citations]

## Conclusion
[Key takeaways and recommendations]

---
*Research conducted by NexAgent Deep Research*

Rules:
- Write in clear, professional Chinese if the query was in Chinese
- Use proper Markdown formatting (headers, bold, lists, code blocks)
- Include specific facts, numbers, and citations from the research
- Conclude with actionable insights or recommendations
- Do NOT invent facts not present in the research results"""


def _with_reasoning_profile(system_prompt: str, mode: str | None) -> str:
    if mode == "fast":
        profile = "Execution profile: Fast. Keep planning compact and prefer low-latency answers."
    elif mode == "balanced":
        profile = "Execution profile: Thinking. Do a concise consistency check before acting."
    elif mode == "deep":
        profile = (
            "Execution profile: Pro. Plan before acting, analyze carefully, "
            "and cross-check findings before writing."
        )
    elif mode == "ultra":
        profile = (
            "Execution profile: Ultra. Treat this as a high-complexity research task. "
            "Increase the likelihood of decomposing independent work, verify evidence, and surface uncertainty."
        )
    else:
        profile = "Execution profile: balance depth and speed."
    return f"{system_prompt}\n\n{profile}"


# ── Node implementations ──────────────────────────────────────────────────────

async def planner_node(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Decompose the user query into a structured research plan."""
    query = state["query"]
    configurable = config.get("configurable") or {}
    model_name = configurable.get("model")
    model = load_chat_model(
        model_name,
        thinking=bool(configurable.get("thinking")),
        thinking_budget=int(configurable.get("thinking_budget") or 8000),
        reasoning_mode=configurable.get("reasoning_mode"),
        reasoning_effort=configurable.get("reasoning_effort"),
    ).with_structured_output(ResearchPlan)

    logger.info(f"Planner: decomposing query '{query[:80]}...'")

    try:
        plan_obj: ResearchPlan = await model.ainvoke([
            SystemMessage(
                content=_with_reasoning_profile(_PLANNER_SYSTEM, configurable.get("reasoning_mode"))
            ),
            HumanMessage(content=f"Research task: {query}"),
        ])

        plan: list[ResearchStep] = [
            ResearchStep(
                id=s.id,
                title=s.title,
                description=s.description,
                tools=s.tools,
                queries=s.queries,
            )
            for s in plan_obj.steps
        ]

        logger.info(f"Planner: created {len(plan)} step(s)")
        return {
            "plan": plan,
            "current_step": 0,
        }

    except Exception as e:
        logger.error(f"Planner failed: {e}, falling back to single-step plan")
        fallback: list[ResearchStep] = [ResearchStep(
            id=1,
            title="General Research",
            description=query,
            tools=["web_search", "knowledge_search"],
            queries=[query],
        )]
        return {"plan": fallback, "current_step": 0}


async def researcher_node(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Execute one research step using the configured tools."""
    from langgraph.prebuilt import create_react_agent

    from nexagent.tools.builtin.code_exec import get_code_exec_tool
    from nexagent.tools.builtin.knowledge_search import get_knowledge_search_tool
    from nexagent.tools.builtin.web_fetch import get_web_fetch_tool
    from nexagent.tools.builtin.web_search import get_web_search_tool
    from nexagent.tools.mcp.client import load_mcp_tools

    plan = state["plan"] or []
    step_idx = state["current_step"]

    if step_idx >= len(plan):
        return {}

    step = plan[step_idx]
    configurable = config.get("configurable") or {}
    logger.info(f"Researcher: executing step {step_idx + 1}/{len(plan)}: '{step['title']}'")

    # Build tool set for this step
    tool_map = {
        "web_search": get_web_search_tool,
        "web_fetch": get_web_fetch_tool,
        "knowledge_search": get_knowledge_search_tool,
        "execute_python": get_code_exec_tool,
    }
    step_tools = []
    for tool_name in step.get("tools", ["web_search"]):
        factory = tool_map.get(tool_name)
        if factory:
            try:
                step_tools.append(factory())
            except Exception as e:
                logger.warning(f"Could not load tool '{tool_name}': {e}")

    # Also add any MCP tools
    try:
        mcp_ids = configurable.get("mcp_ids") or []
        if mcp_ids:
            mcp_tools = await load_mcp_tools(mcp_ids)
            step_tools.extend(mcp_tools)
    except Exception as e:
        logger.warning(f"MCP tool loading skipped: {e}")

    if not step_tools:
        logger.warning("No tools available for this step; using LLM knowledge only")

    model_name = configurable.get("model")
    model = load_chat_model(
        model_name,
        thinking=bool(configurable.get("thinking")),
        thinking_budget=int(configurable.get("thinking_budget") or 8000),
        reasoning_mode=configurable.get("reasoning_mode"),
        reasoning_effort=configurable.get("reasoning_effort"),
    )

    # Build research prompt
    queries_text = "\n".join(f"- {q}" for q in step.get("queries", [step["description"]]))
    research_prompt = (
        f"Research step: {step['title']}\n\n"
        f"Task: {step['description']}\n\n"
        f"Suggested queries to investigate:\n{queries_text}\n\n"
        "Use the available tools to thoroughly research this topic. "
        "Collect specific facts, data points, and cite your sources."
    )

    try:
        if step_tools:
            agent = create_react_agent(model, step_tools)
            result = await agent.ainvoke({
                "messages": [
                    SystemMessage(
                        content=_with_reasoning_profile(_RESEARCHER_SYSTEM, configurable.get("reasoning_mode"))
                    ),
                    HumanMessage(content=research_prompt),
                ]
            })
            content = result["messages"][-1].content
        else:
            # Fallback: direct LLM without tools
            response = await model.ainvoke([
                SystemMessage(
                    content=_with_reasoning_profile(_RESEARCHER_SYSTEM, configurable.get("reasoning_mode"))
                ),
                HumanMessage(content=research_prompt),
            ])
            content = response.content

    except Exception as e:
        logger.error(f"Researcher step {step_idx + 1} failed: {e}")
        content = f"Research step failed: {e}"

    step_result = StepResult(
        step_id=step["id"],
        title=step["title"],
        content=content,
        sources=[],
    )

    return {
        "step_results": [step_result],
        "current_step": step_idx + 1,
    }


async def writer_node(state: DeepResearchState, config: RunnableConfig) -> dict:
    """Synthesise all research results into a final Markdown report."""
    query = state["query"]
    step_results = state.get("step_results", [])

    logger.info(f"Writer: synthesising {len(step_results)} research result(s)")

    configurable = config.get("configurable") or {}
    model_name = configurable.get("model")
    model = load_chat_model(
        model_name,
        thinking=bool(configurable.get("thinking")),
        thinking_budget=int(configurable.get("thinking_budget") or 8000),
        reasoning_mode=configurable.get("reasoning_mode"),
        reasoning_effort=configurable.get("reasoning_effort"),
    )

    # Build synthesis context
    research_sections = []
    for i, result in enumerate(step_results):
        research_sections.append(
            f"### Step {result['step_id']}: {result['title']}\n\n"
            f"{result['content']}"
        )

    synthesis_prompt = (
        f"Original research question: {query}\n\n"
        f"Research findings ({len(step_results)} steps completed):\n\n"
        + "\n\n---\n\n".join(research_sections)
        + "\n\n"
        "Now write a comprehensive, well-structured Markdown report that synthesises "
        "all the above findings to answer the original question completely."
    )

    try:
        response = await model.ainvoke([
            SystemMessage(
                content=_with_reasoning_profile(_WRITER_SYSTEM, configurable.get("reasoning_mode"))
            ),
            HumanMessage(content=synthesis_prompt),
        ])
        report = response.content
    except Exception as e:
        logger.error(f"Writer failed: {e}")
        report = (
            f"# Research Report\n\n"
            f"**Query:** {query}\n\n"
            f"*Report generation failed: {e}*\n\n"
            + "\n\n".join(
                f"## {r['title']}\n\n{r['content']}" for r in step_results
            )
        )

    return {
        "report": report,
        "messages": [AIMessage(content=report)],
    }


def should_continue(state: DeepResearchState) -> Literal["researcher", "writer"]:
    """Route: if more steps remain, continue research; otherwise write report."""
    plan = state.get("plan") or []
    current = state.get("current_step", 0)
    if current < len(plan):
        return "researcher"
    return "writer"
