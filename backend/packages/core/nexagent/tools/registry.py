"""Tool registry - register, discover, and instantiate tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: str
    module: str
    factory: str
    configurable: bool = True


_BUILTIN_SPECS: dict[str, ToolSpec] = {
    "knowledge_search": ToolSpec(
        name="knowledge_search",
        description="Search uploaded knowledge bases across RAG or graph backends.",
        category="knowledge",
        module="nexagent.tools.builtin.knowledge_search",
        factory="get_knowledge_search_tool",
    ),
    "list_wiki_pages": ToolSpec(
        name="list_wiki_pages",
        description="List pages in an enabled LLM Wiki knowledge base with filters.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_list_wiki_pages_tool",
    ),
    "read_wiki_page": ToolSpec(
        name="read_wiki_page",
        description="Read a page body and metadata from an enabled LLM Wiki knowledge base.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_read_wiki_page_tool",
    ),
    "wiki_lint": ToolSpec(
        name="wiki_lint",
        description="Inspect health issues for an enabled LLM Wiki knowledge base.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_wiki_lint_tool",
    ),
    "get_wiki_graph": ToolSpec(
        name="get_wiki_graph",
        description="Summarize the relationship graph of an enabled LLM Wiki knowledge base.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_wiki_graph_tool",
    ),
    "compile_wiki": ToolSpec(
        name="compile_wiki",
        description="Compile uploaded source files into an enabled LLM Wiki after explicit confirmation.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_compile_wiki_tool",
    ),
    "crystallize_wiki": ToolSpec(
        name="crystallize_wiki",
        description="Create or update a Wiki page from explicit markdown text after confirmation.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_crystallize_wiki_tool",
    ),
    "handle_wiki_candidate": ToolSpec(
        name="handle_wiki_candidate",
        description="Accept or discard a generated Wiki candidate after explicit confirmation.",
        category="knowledge",
        module="nexagent.tools.builtin.wiki",
        factory="get_handle_wiki_candidate_tool",
    ),
    "web_search": ToolSpec(
        name="web_search",
        description="Search the web for current information via Tavily or DuckDuckGo/DDGS.",
        category="search",
        module="nexagent.tools.builtin.web_search",
        factory="get_web_search_tool",
    ),
    "web_fetch": ToolSpec(
        name="web_fetch",
        description="Fetch readable page content from an exact URL returned by search or provided by the user.",
        category="search",
        module="nexagent.tools.builtin.web_fetch",
        factory="get_web_fetch_tool",
    ),
    "execute_python": ToolSpec(
        name="execute_python",
        description="Execute Python snippets in the configured local sandbox.",
        category="compute",
        module="nexagent.tools.builtin.code_exec",
        factory="get_code_exec_tool",
    ),
    "list_skills": ToolSpec(
        name="list_skills",
        description="List installed managed NexAgent Skills so the agent can choose one before reading or updating it.",
        category="skills",
        module="nexagent.tools.builtin.skill_manager",
        factory="get_list_skills_tool",
    ),
    "read_skill": ToolSpec(
        name="read_skill",
        description="Inspect a managed NexAgent Skill's file tree and read its text files without filesystem MCP.",
        category="skills",
        module="nexagent.tools.builtin.skill_manager",
        factory="get_read_skill_tool",
    ),
    "skill_manage": ToolSpec(
        name="skill_manage",
        description=(
            "Create, edit, patch, delete, or update bundled files for managed NexAgent Skills with validation, "
            "history, and per-skill write locking."
        ),
        category="skills",
        module="nexagent.tools.builtin.skill_manager",
        factory="get_skill_manage_tool",
    ),
    "bash": ToolSpec(
        name="bash",
        description="Execute shell commands inside the configured sandbox workspace.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_bash_tool",
    ),
    "ls": ToolSpec(
        name="ls",
        description="List files inside the sandbox workspace.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_ls_tool",
    ),
    "read_file": ToolSpec(
        name="read_file",
        description="Read a text file inside the sandbox workspace.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_read_file_tool",
    ),
    "glob": ToolSpec(
        name="glob",
        description="Find files or directories inside the sandbox workspace using a glob pattern.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_glob_tool",
    ),
    "grep": ToolSpec(
        name="grep",
        description="Search UTF-8 text files inside the sandbox workspace with a regex pattern.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_grep_tool",
    ),
    "write_file": ToolSpec(
        name="write_file",
        description="Write a text file inside the sandbox workspace.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_write_file_tool",
    ),
    "str_replace": ToolSpec(
        name="str_replace",
        description="Replace one exact text fragment inside a sandbox file.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_str_replace_tool",
    ),
    "present_artifacts": ToolSpec(
        name="present_artifacts",
        description="Expose generated files from /mnt/user-data/outputs to the UI.",
        category="sandbox",
        module="nexagent.sandbox.tools",
        factory="get_present_artifacts_tool",
    ),
    "delegate_subagents": ToolSpec(
        name="delegate_subagents",
        description="Delegate independent subtasks to configured agents and aggregate their answers.",
        category="orchestration",
        module="nexagent.tools.builtin.subagent",
        factory="get_subagent_tool",
        configurable=False,
    ),
}


class ToolRegistry:
    """Central registry for built-in and runtime tools."""

    def __init__(self) -> None:
        self._runtime_tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register an already-instantiated runtime tool."""
        self._runtime_tools[tool.name] = tool

    def list_specs(self) -> list[ToolSpec]:
        return list(_BUILTIN_SPECS.values())

    def get_spec(self, name: str) -> ToolSpec | None:
        return _BUILTIN_SPECS.get(name)

    def list_all(self) -> list[BaseTool]:
        tools = []
        for spec in self.list_specs():
            tool = self.create(spec.name)
            if tool is not None:
                tools.append(tool)
        tools.extend(self._runtime_tools.values())
        return tools

    def get(self, name: str) -> BaseTool | None:
        return self.create(name)

    def get_by_names(self, names: list[str], **kwargs) -> list[BaseTool]:
        tools = []
        for name in names:
            tool = self.create(name, **kwargs)
            if tool is not None:
                tools.append(tool)
        return tools

    def create(self, name: str, **kwargs) -> BaseTool | None:
        if name in self._runtime_tools:
            return self._runtime_tools[name]

        spec = _BUILTIN_SPECS.get(name)
        if spec is None:
            return None

        try:
            module = import_module(spec.module)
            factory: Callable = getattr(module, spec.factory)
            if name in {
                "knowledge_search",
                "list_wiki_pages",
                "read_wiki_page",
                "wiki_lint",
                "get_wiki_graph",
                "compile_wiki",
                "crystallize_wiki",
                "handle_wiki_candidate",
            }:
                return factory(kb_ids=kwargs.get("kb_ids") or None)
            if name == "delegate_subagents":
                return factory(
                    allowed_agent_ids=kwargs.get("allowed_agent_ids"),
                    allowed_tools=kwargs.get("allowed_tools"),
                    allowed_kb_ids=kwargs.get("allowed_kb_ids"),
                    allowed_mcp_ids=kwargs.get("allowed_mcp_ids"),
                    allowed_skill_ids=kwargs.get("allowed_skill_ids"),
                    model_strategy=kwargs.get("subagent_model_strategy") or "agent_default",
                    parent_model=kwargs.get("parent_model"),
                    custom_model=kwargs.get("subagent_model"),
                )
            return factory()
        except Exception as exc:
            logger.warning("Could not load tool '%s': %s", name, exc)
            return None


_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _registry


def list_tool_specs() -> list[ToolSpec]:
    return _registry.list_specs()


def load_tools(
    names: list[str] | None = None,
    *,
    kb_ids: list[str] | None = None,
    allowed_agent_ids: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    allowed_kb_ids: list[str] | None = None,
    allowed_mcp_ids: list[str] | None = None,
    allowed_skill_ids: list[str] | None = None,
    subagent_model_strategy: str = "agent_default",
    parent_model: str | None = None,
    subagent_model: str | None = None,
) -> list[BaseTool]:
    """Load tools by name, or all built-ins when names is empty."""
    selected = names or [spec.name for spec in _registry.list_specs()]
    return _registry.get_by_names(
        selected,
        kb_ids=kb_ids,
        allowed_agent_ids=allowed_agent_ids,
        allowed_tools=allowed_tools,
        allowed_kb_ids=allowed_kb_ids,
        allowed_mcp_ids=allowed_mcp_ids,
        allowed_skill_ids=allowed_skill_ids,
        subagent_model_strategy=subagent_model_strategy,
        parent_model=parent_model,
        subagent_model=subagent_model,
    )
