"""Built-in chatbot agent — the default conversational agent in NexAgent."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from langchain.agents import create_agent

from nexagent.agents.base import BaseAgent
from nexagent.agents.context import BaseContext
from nexagent.agents.middlewares import build_agent_middlewares
from nexagent.agents.state import BaseState
from nexagent.models.factory import load_chat_model_async

logger = logging.getLogger(__name__)


class ChatbotAgent(BaseAgent):
    """General-purpose conversational agent.

    Uses ``create_react_agent`` (LangGraph prebuilt) with per-request model,
    tool, and system-prompt overrides from ``BaseContext``.  Selected skills
    are loaded from disk and appended to the system prompt so the LLM is
    aware of its specialised capabilities.  Thread history is persisted via
    the configured checkpointer (SQLite by default).
    """

    name = "chatbot"
    description = "General-purpose conversational AI assistant."
    capabilities = [
        "knowledge_search",
        "list_wiki_pages",
        "read_wiki_page",
        "wiki_lint",
        "get_wiki_graph",
        "compile_wiki",
        "crystallize_wiki",
        "handle_wiki_candidate",
        "web_search",
        "execute_python",
        "skills",
        "subagents",
    ]

    async def get_graph(self, context: BaseContext | None = None, **kwargs):
        context = context or self.context_schema()

        # Per-request model override (falls back to config default)
        model = await load_chat_model_async(
            context.model,
            thinking=context.thinking,
            thinking_budget=context.thinking_budget,
            reasoning_mode=context.reasoning_mode,
            reasoning_effort=context.reasoning_effort,
        )
        checkpointer = await self._get_checkpointer()
        await _prepare_context_skills(context)
        tools = await _load_context_tools(context)
        system_prompt = _build_system_prompt(context)

        graph = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt or None,
            middleware=build_agent_middlewares(),
            state_schema=BaseState,
            checkpointer=checkpointer,
        )
        return graph


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_context_tools(context: BaseContext):
    """Load tools selected in context.

    General chat defaults to read-only tools. Sub-agent delegation is exposed
    whenever the active Agent/profile allows it; reasoning mode controls how
    readily the model chooses to use that capability.
    """
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.validation import ensure_runtime_plan
    from nexagent.tools.registry import load_tools

    loader = SkillLoader()
    selected_skills = loader.load_selected(context.skills) if context.skills else []
    tools_disabled = any(name in {"none", "__none__"} for name in context.tools)
    if tools_disabled:
        plan = await ensure_runtime_plan(
            selected_skills,
            loader=loader,
            selected_tool_names=[],
            selected_mcp_ids=[],
            allow_subagents=context.allow_subagents,
        )
        if plan.required_tools or plan.required_mcp_ids:
            raise ValueError("Selected skills require tools or MCP servers, but this run disabled tools.")
        return []
    default_tools = [
        "knowledge_search",
        "list_wiki_pages",
        "read_wiki_page",
        "wiki_lint",
        "get_wiki_graph",
        "compile_wiki",
        "crystallize_wiki",
        "handle_wiki_candidate",
        "web_search",
        "web_fetch",
        # Basic sandbox workspace tools — let the model inspect and edit files.
        "ls",
        "read_file",
        "glob",
        "grep",
        "write_file",
        "str_replace",
        "bash",
        "present_artifacts",
        "list_skills",
        "read_skill",
        "skill_manage",
    ]
    selected = context.tools if context.tools_explicit else (context.tools or default_tools)
    if not context.tools_explicit and "list_skills" not in selected:
        selected = [*selected, "list_skills"]
    if not context.tools_explicit and "read_skill" not in selected:
        selected = [*selected, "read_skill"]
    if not context.tools_explicit and "skill_manage" not in selected:
        selected = [*selected, "skill_manage"]
    if not context.allow_subagents:
        selected = [name for name in selected if name != "delegate_subagents"]
    if context.allow_subagents and "delegate_subagents" not in selected:
        selected = [*selected, "delegate_subagents"]
    mcp_ids = list(context.mcp_ids or [])
    if selected_skills:
        plan = await ensure_runtime_plan(
            selected_skills,
            loader=loader,
            selected_tool_names=selected,
            selected_mcp_ids=mcp_ids,
            allow_subagents=context.allow_subagents,
        )
        selected = plan.required_tools
        mcp_ids = plan.required_mcp_ids
    tools = load_tools(
        selected,
        kb_ids=context.kb_ids or None,
        allowed_agent_ids=context.allowed_agent_ids or None,
        allowed_tools=[name for name in selected if name != "delegate_subagents"],
        allowed_kb_ids=context.kb_ids or [],
        allowed_mcp_ids=mcp_ids,
        allowed_skill_ids=context.skills or [],
        subagent_model_strategy=context.subagent_model_strategy,
        parent_model=context.model,
        subagent_model=context.subagent_model,
    )
    if mcp_ids:
        from nexagent.tools.mcp.client import load_mcp_tools

        tools.extend(await load_mcp_tools(mcp_ids))
    return tools


async def _prepare_context_skills(context: BaseContext) -> None:
    """Mirror selected Skills into the sandbox runtime before tools execute."""
    try:
        from nexagent.skills.loader import SkillLoader
        from nexagent.skills.runtime import prepare_skill_runtime
        from nexagent.skills.validation import expand_skill_dependencies

        loader = SkillLoader()
        selected_skills = loader.load_selected(context.skills) if context.skills else []
        if not selected_skills:
            prepare_skill_runtime(context.thread_id, [])
            return
        runtime_skills, issues = expand_skill_dependencies(selected_skills, loader=loader)
        for issue in issues:
            logger.warning("Skill runtime dependency issue for thread=%s: %s", context.thread_id, issue.message)
        prepare_skill_runtime(context.thread_id, runtime_skills)
    except Exception as exc:
        logger.warning("Failed to prepare skill runtime for thread=%s: %s", context.thread_id, exc)


def _build_system_prompt(context: BaseContext) -> str:
    """Build the final system prompt, optionally injecting selected skill blocks.

    Selected Skills are appended as a progressive-loading manifest. The model
    reads SKILL.md only when a user request matches a listed Skill.
    """
    base = context.system_prompt or "You are a helpful AI assistant powered by NexAgent."
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    base += (
        f"\n\nCurrent date: {today} (Asia/Shanghai). "
        "Use this date to resolve relative dates such as today, yesterday, and tomorrow."
    )
    runtime_agent = context.agent_name or context.agent_config_id or "chatbot"
    runtime_model = context.model or "system default"
    base += (
        "\n\n## Runtime Metadata"
        f"\n- Current Agent: {runtime_agent}"
        f"\n- Current Model: {runtime_model}"
        "\n\nIf the user asks which model or Agent you are currently using, answer from this Runtime Metadata. "
        "Do not claim that you cannot see the model configuration. "
        "Do not reveal API keys, secrets, or provider credentials."
    )
    base += (
        "\n\n## Wiki Knowledge Policy"
        "\nWhen an enabled knowledge base is an LLM Wiki, prefer Wiki-specific tools for structural questions: "
        "use list_wiki_pages to inspect the page catalog, read_wiki_page to read canonical page content, "
        "wiki_lint to check health issues and repair suggestions, and get_wiki_graph to inspect Wiki page "
        "relationships. Use knowledge_search mode=wiki for semantic retrieval over Wiki content. Treat the Wiki "
        "relationship graph as page-level knowledge links, not as a Neo4j system graph. Wiki write tools "
        "(compile_wiki, crystallize_wiki, handle_wiki_candidate) must only be called with confirmed=true after "
        "the user explicitly confirms the write."
    )
    base += (
        "\n\n## Skill Lifecycle Policy"
        "\nNexAgent Skills are managed resources, not ordinary workspace files. Follow the NexAgent "
        "progressive loading workflow for every Skill task:"
        "\n1. If the user asks to create, add, install, modify, update, improve, refine, complete, replace, review, "
        "or inspect a NexAgent Skill, use list_skills, read_skill, and skill_manage as the authoritative tools."
        "\n2. If the target Skill id is unclear, call list_skills first. Do not search managed Skill folders with "
        "generic filesystem, shell, Python, or MCP filesystem tools."
        "\n3. For an existing Skill, read SKILL.md with read_skill first. Then read referenced support files with "
        "read_skill path='<relative path>' only when the SKILL.md or task makes them relevant."
        "\n4. For Skill changes, use skill_manage. Prefer action=patch over action=edit for narrow updates; use "
        "action=write_file for support files; use action=history when previous edits matter. After important "
        "changes, verify with read_skill."
        "\n4a. Keep each skill_manage call small and incremental. Do not generate a full rewritten Skill package in "
        "one tool call unless the user explicitly asks to replace the whole Skill. For ordinary improvements, patch "
        "one focused section at a time and write one support file at a time. Keep find/replace/content arguments "
        "concise; if a change would require many files, explain the plan first and ask the user before generating "
        "that large payload."
        "\n5. Do not create or modify Skills by guessing absolute paths, manually writing SKILL.md with generic "
        "filesystem tools, running bash/execute_python, or using MCP filesystem tools such as ls, list_directory, "
        "directory_tree, read_file, write_file, or edit_file against managed Skill storage."
        "\n6. Generic file tools are only for user workspace/repository files unrelated to managed Skills, or when "
        "the user explicitly asks you to inspect project files outside the Skill manager."
        "\n7. Runtime Skill usage is progressive: Only Skills configured on the current Agent or run are listed "
        "later in this prompt with `/mnt/skills` locations. Read the matching SKILL.md only when the user's "
        "request matches its description, then read referenced files on demand. Category paths such as "
        "`/mnt/skills/public/<skill-id>` and `/mnt/skills/custom/<skill-id>` are compatibility aliases for "
        "imported Skills."
        "\n8. Bundled scripts are ordinary files under scripts/. When SKILL.md instructs script execution, run them "
        "from bash using absolute paths under `/mnt/skills/<skill-id>/scripts/...`."
        "\n\nSkill evolution policy: After completing a task, consider creating or updating a Skill when the task "
        "required many tool calls, overcame non-obvious pitfalls, the user corrected the approach, or you found a "
        "recurring workflow. If you used a Skill and found a gap in it, patch that Skill when the user asked for "
        "improvement. Skip one-off tasks."
        "\n\nWhen creating or substantially improving a Skill, follow the installed Anthropic skill-creator standard: "
        "capture intent, write a trigger-focused description, keep SKILL.md focused under about 500 lines, use "
        "progressive disclosure, and move bulky references/scripts/examples/evals into bundled files. Include "
        "realistic test prompts for objectively verifiable Skills, preferably in test-cases/ or evals/evals.json. "
        "Use files[] with folders such as references/, scripts/, test-cases/, evals/, examples/, templates/, and "
        "assets/ instead of putting everything in SKILL.md. Put reusable automation in scripts/ as ordinary files "
        "that can be run from the standard `/mnt/skills/<skill-id>/scripts/...` runtime path."
    )
    if context.user_id:
        try:
            from nexagent.agents.memory import top_facts_for_prompt

            memory_block = top_facts_for_prompt(context.user_id)
            if memory_block:
                base += "\n\n## Long-Term Memory\nUse these facts when relevant:\n" + memory_block
        except Exception as exc:
            logger.debug("Failed to inject long-term memory: %s", exc)
    if context.reasoning_mode == "fast":
        base += (
            "\n\nExecution profile: Fast. Prefer direct answers and low latency. "
            "If Sub-Agent delegation is available, use it only when the user explicitly asks for delegation "
            "or the request is clearly impossible to handle well in a single response."
        )
    elif context.reasoning_mode == "balanced":
        base += (
            "\n\nExecution profile: Thinking. Clarify the user's intent internally, do a brief consistency check, "
            "then answer without adding unnecessary process. If Sub-Agent delegation is available, use it for "
            "clearly separable work, but prefer a single-agent answer for ordinary tasks."
        )
    elif context.reasoning_mode == "deep":
        base += (
            "\n\nExecution profile: Pro. For non-trivial tasks, create a concise plan before acting, "
            "choose tools deliberately, and verify important assumptions before finalizing. If Sub-Agent "
            "delegation is available, consider it when parallel subtasks would improve quality."
        )
    elif context.reasoning_mode == "ultra":
        base += (
            "\n\nExecution profile: Ultra. Inherit Pro behavior. Increase the likelihood of decomposing complex work "
            "into independent subtasks, use stronger verification, and consider delegating suitable subtasks "
            "to available Sub-Agents when delegation is enabled."
        )
    if context.planning_enabled:
        base += (
            "\n\nPlanning policy: If the request requires multiple steps, tool use, or trade-off analysis, "
            "make a short internal plan before execution and update it when new information changes the approach."
        )

    try:
        from nexagent.skills.loader import SkillLoader
        from nexagent.skills.validation import expand_skill_dependencies

        loader = SkillLoader()
        if context.skills:
            loaded, _issues = expand_skill_dependencies(loader.load_selected(context.skills), loader=loader)
        else:
            loaded = []
        if not loaded:
            return base
        skill_section = loader.to_system_prompt_blocks(loaded)
        return base + skill_section
    except Exception as exc:
        logger.warning("Failed to inject skills into system prompt: %s", exc)
        return base
