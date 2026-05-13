from __future__ import annotations

import sys
import types

import pytest
from langchain_core.tools import StructuredTool


def _tool(name: str):
    def handler() -> str:
        return name

    return StructuredTool.from_function(handler, name=name, description=f"{name} tool")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_streamable_http_transport_is_forwarded(monkeypatch):
    from nexagent.tools.mcp import client as mcp_client

    captured_config = {}

    class FakeMultiServerMCPClient:
        def __init__(self, config):
            captured_config.update(config)

        async def get_tools(self):
            return [_tool("remote_tool")]

    package = types.ModuleType("langchain_mcp_adapters")
    module = types.ModuleType("langchain_mcp_adapters.client")
    module.MultiServerMCPClient = FakeMultiServerMCPClient
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters", package)
    monkeypatch.setitem(sys.modules, "langchain_mcp_adapters.client", module)

    tools = await mcp_client.MCPClient(
        [
            {
                "id": "streamable",
                "name": "streamable",
                "transport": "streamable_http",
                "url": "https://example.test/mcp",
                "env": {"API_KEY": "secret"},
            }
        ],
        raise_errors=True,
    ).load_tools()

    assert [tool.name for tool in tools] == ["remote_tool"]
    assert captured_config == {
        "streamable": {
            "transport": "streamable_http",
            "url": "https://example.test/mcp",
        }
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_tool_cache_filters_disabled_tools(monkeypatch):
    from nexagent.tools.mcp import client as mcp_client

    calls = 0

    async def fake_load_tools(self):
        nonlocal calls
        calls += 1
        return [_tool("alpha"), _tool("beta")]

    monkeypatch.setattr(mcp_client.MCPClient, "load_tools", fake_load_tools)
    mcp_client.invalidate_mcp_caches()

    config = {
        "id": "unit-mcp",
        "name": "unit-mcp",
        "transport": "stdio",
        "command": ["unit"],
        "env": {},
        "is_enabled": True,
        "disabled_tools": ["beta"],
    }

    first = await mcp_client.load_mcp_server_tools(config)
    second = await mcp_client.load_mcp_server_tools(config)

    assert [tool.name for tool in first] == ["alpha"]
    assert [tool.name for tool in second] == ["alpha"]
    assert calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_tool_cache_invalidates_by_server(monkeypatch):
    from nexagent.tools.mcp import client as mcp_client

    calls = 0

    async def fake_load_tools(self):
        nonlocal calls
        calls += 1
        return [_tool(f"tool_{calls}")]

    monkeypatch.setattr(mcp_client.MCPClient, "load_tools", fake_load_tools)
    mcp_client.invalidate_mcp_caches()

    config = {
        "id": "unit-mcp",
        "name": "unit-mcp",
        "transport": "stdio",
        "command": ["unit"],
        "env": {},
        "is_enabled": True,
        "disabled_tools": [],
    }

    assert [tool.name for tool in await mcp_client.load_mcp_server_tools(config)] == ["tool_1"]
    assert [tool.name for tool in await mcp_client.load_mcp_server_tools(config)] == ["tool_1"]
    mcp_client.invalidate_mcp_caches("unit-mcp")
    assert [tool.name for tool in await mcp_client.load_mcp_server_tools(config)] == ["tool_2"]


@pytest.mark.unit
def test_mcp_error_classification_is_stable():
    from nexagent.tools.mcp.client import classify_mcp_error

    assert classify_mcp_error(TimeoutError("timed out")) == "timeout"
    assert classify_mcp_error("401 unauthorized token") == "auth_error"
    assert classify_mcp_error("invalid schema from server") == "schema_error"
    assert classify_mcp_error("connection refused") == "connection_error"
    assert classify_mcp_error("tool crashed") == "tool_runtime_error"
