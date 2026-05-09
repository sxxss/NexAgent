from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_python_runs_subprocess_without_async_subprocess(monkeypatch):
    from nexagent.tools.builtin.code_exec import get_code_exec_tool

    monkeypatch.setenv("NEXAGENT_SANDBOX_MODE", "local")

    async def _should_not_be_used(*args, **kwargs):
        raise AssertionError("asyncio.create_subprocess_exec should not be used by execute_python")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _should_not_be_used)

    tool = get_code_exec_tool()
    result = await tool.ainvoke({"code": "print(1)"})

    assert result == "1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_python_rejects_empty_code(monkeypatch):
    from nexagent.tools.builtin.code_exec import get_code_exec_tool

    monkeypatch.setenv("NEXAGENT_SANDBOX_MODE", "local")
    tool = get_code_exec_tool()
    result = await tool.ainvoke({"code": ""})

    assert "requires non-empty code" in result


@pytest.mark.unit
def test_default_sandbox_run_root_is_outside_backend_watch_dir(monkeypatch):
    from nexagent.tools.builtin.code_exec import _sandbox_run_root

    monkeypatch.delenv("NEXAGENT_SANDBOX_RUN_DIR", raising=False)

    root = _sandbox_run_root().resolve()
    backend_watch_dir = Path(__file__).resolve().parents[2].resolve() / ".nexagent" / "sandbox-runs"

    assert root != backend_watch_dir
    assert backend_watch_dir not in root.parents
