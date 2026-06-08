"""LangChain tools backed by the configured sandbox provider."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _thread_id(config: RunnableConfig | None = None) -> str:
    configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
    return str(configurable.get("sandbox_thread_id") or configurable.get("thread_id") or "default")


async def _sandbox(config: RunnableConfig | None = None):
    from nexagent.sandbox import get_sandbox_provider
    from nexagent.sandbox.context import get_current_sandbox

    current = get_current_sandbox()
    if current is not None:
        return current
    return await get_sandbox_provider().acquire(_thread_id(config))


def get_bash_tool():
    @tool
    async def bash(command: str, timeout: int = 60, config: RunnableConfig | None = None) -> str:
        """Execute a shell command inside the configured sandbox workspace."""
        sb = await _sandbox(config)
        return await sb.execute_command(command, timeout=timeout)

    return bash


def get_ls_tool():
    @tool
    async def ls(path: str = ".", max_depth: int = 2, config: RunnableConfig | None = None) -> str:
        """List sandbox directory contents up to max_depth."""
        sb = await _sandbox(config)
        return await sb.list_dir(path, max_depth=max_depth)

    return ls


def get_read_file_tool():
    @tool
    async def read_file(
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        config: RunnableConfig | None = None,
    ) -> str:
        """Read a UTF-8 text file from the sandbox, optionally by line range."""
        sb = await _sandbox(config)
        return await sb.read_file(path, start_line=start_line, end_line=end_line)

    return read_file


def get_glob_tool():
    @tool
    async def glob(pattern: str, path: str = ".", config: RunnableConfig | None = None) -> str:
        """Find files or directories in the sandbox using a glob pattern."""
        sb = await _sandbox(config)
        return await sb.glob(pattern, path=path)

    return glob


def get_grep_tool():
    @tool
    async def grep(
        pattern: str,
        path: str = ".",
        glob: str = "",
        config: RunnableConfig | None = None,
    ) -> str:
        """Search UTF-8 text files in the sandbox with a regex pattern."""
        sb = await _sandbox(config)
        return await sb.grep(pattern, path=path, glob=glob)

    return grep


def get_write_file_tool():
    @tool
    async def write_file(path: str, content: str, append: bool = False, config: RunnableConfig | None = None) -> str:
        """Write UTF-8 text into a sandbox file."""
        sb = await _sandbox(config)
        return await sb.write_file(path, content, append=append)

    return write_file


def get_str_replace_tool():
    @tool
    async def str_replace(path: str, old_str: str, new_str: str, config: RunnableConfig | None = None) -> str:
        """Replace exactly one text fragment in a sandbox file."""
        sb = await _sandbox(config)
        return await sb.str_replace(path, old_str, new_str)

    return str_replace


def get_present_artifacts_tool():
    @tool
    async def present_artifacts(config: RunnableConfig | None = None) -> str:
        """List final files under /mnt/user-data/outputs for UI presentation."""
        sb = await _sandbox(config)
        artifacts = await sb.present_artifacts()
        if not artifacts:
            return "No artifacts found in /mnt/user-data/outputs."
        return "\n".join(artifacts)

    return present_artifacts


def get_sandbox_tools():
    return [
        get_bash_tool(),
        get_ls_tool(),
        get_read_file_tool(),
        get_glob_tool(),
        get_grep_tool(),
        get_write_file_tool(),
        get_str_replace_tool(),
        get_present_artifacts_tool(),
    ]
