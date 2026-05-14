from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from nexagent.agents.middlewares.tool_error_handling import ToolErrorHandlingMiddleware


def _request(name: str, args: dict | None = None, tool_call_id: str = "tool-1"):
    return SimpleNamespace(tool_call={"name": name, "id": tool_call_id, "args": args or {}})


@pytest.mark.unit
def test_missing_bash_command_returns_validation_message():
    middleware = ToolErrorHandlingMiddleware()
    called = False

    def _handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="should not run", tool_call_id="tool-1", name="bash")

    result = middleware.wrap_tool_call(_request("bash"), _handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.name == "bash"
    assert "command" in result.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_execute_python_code_returns_validation_message():
    middleware = ToolErrorHandlingMiddleware()
    called = False

    async def _handler(_request):
        nonlocal called
        called = True
        return ToolMessage(content="should not run", tool_call_id="tool-1", name="execute_python")

    result = await middleware.awrap_tool_call(_request("execute_python"), _handler)

    assert called is False
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.name == "execute_python"
    assert "code" in result.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_skill_manage_identity_returns_validation_message():
    middleware = ToolErrorHandlingMiddleware()

    async def _handler(_request):
        raise AssertionError("handler should not be called")

    result = await middleware.awrap_tool_call(_request("skill_manage", {"action": "patch"}), _handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.name == "skill_manage"
    assert "id" in result.text
