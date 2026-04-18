"""MCP client — wraps langchain-mcp-adapters MultiServerMCPClient.

Usage
-----
Tools are loaded from all configured MCP servers at startup and registered
into the global ToolRegistry. Per-agent tool scoping is applied by the agent.

Config (config.yaml):
  mcp_servers:
    - name: filesystem
      transport: stdio
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    - name: my-api
      transport: sse
      url: http://localhost:3001/sse
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)
MCP_TOOL_CACHE_TTL_SECONDS = 300


@dataclass
class MCPToolCacheEntry:
    server_id: str
    config_hash: str
    tools: list[BaseTool] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        return self.created_at + MCP_TOOL_CACHE_TTL_SECONDS

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class MCPClient:
    """Thin wrapper around MultiServerMCPClient for NexAgent."""

    def __init__(self, server_configs: list[dict[str, Any]], *, raise_errors: bool = False) -> None:
        self._server_configs = server_configs
        self._raise_errors = raise_errors
        self._tools: list[BaseTool] = []
        self._loaded = False

    async def load_tools(self) -> list[BaseTool]:
        """Connect to all configured MCP servers and return their tools."""
        if self._loaded:
            return self._tools

        if not self._server_configs:
            logger.debug("No MCP servers configured — skipping MCP tool loading")
            self._loaded = True
            return []

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore
        except ImportError:
            message = "langchain-mcp-adapters not installed. Run: pip install langchain-mcp-adapters"
            logger.warning(message)
            if self._raise_errors:
                raise RuntimeError(message)
            self._loaded = True
            return []

        # Build the config dict expected by MultiServerMCPClient
        client_config: dict[str, dict] = {}
        for srv in self._server_configs:
            name = srv.get("name", "")
            transport = srv.get("transport", "stdio")
            if transport == "stdio":
                client_config[name] = {
                    "transport": "stdio",
                    "command": srv["command"][0],
                    "args": srv["command"][1:],
                    "env": srv.get("env", {}),
                }
            elif transport in ("sse", "http", "streamable_http"):
                client_config[name] = {
                    "transport": transport,
                    "url": srv["url"],
                }

        try:
            client = MultiServerMCPClient(client_config)
            tools = await client.get_tools()
            self._tools = list(tools)
            logger.info(
                f"MCP: loaded {len(self._tools)} tool(s) from "
                f"{len(client_config)} server(s): "
                f"{[t.name for t in self._tools]}"
            )
        except Exception as e:
            logger.error("MCP tool loading failed: %s", e)
            if self._raise_errors:
                raise

        self._loaded = True
        return self._tools

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools


_client: MCPClient | None = None
_TOOL_CACHE: dict[str, MCPToolCacheEntry] = {}
_LAST_INVALIDATED_AT = time.time()


def reset_mcp_client() -> None:
    """Clear the cached MCP client after server configuration changes."""
    invalidate_mcp_caches()


def invalidate_mcp_caches(server_id: str | None = None) -> None:
    """Clear MCP clients and per-server tool caches after config changes."""
    global _client
    global _LAST_INVALIDATED_AT
    _client = None
    _LAST_INVALIDATED_AT = time.time()
    if server_id is None:
        _TOOL_CACHE.clear()
        return
    for key, entry in list(_TOOL_CACHE.items()):
        if entry.server_id == server_id:
            _TOOL_CACHE.pop(key, None)


def _get_client() -> MCPClient:
    global _client
    if _client is None:
        from nexagent.config import get_config
        cfgs = [
            {
                "name": s.name,
                "transport": s.transport,
                "command": s.command,
                "url": s.url,
                "env": s.env,
            }
            for s in get_config().mcp_servers
        ]
        _client = MCPClient(cfgs)
    return _client


async def load_mcp_tools(server_ids: list[str] | None = None) -> list[BaseTool]:
    """Load and return all MCP tools from configured servers."""
    global _client
    if server_ids:
        try:
            from nexagent.tools.mcp.registry import list_enabled_mcp_server_configs

            configs = await list_enabled_mcp_server_configs(server_ids)
            tools: list[BaseTool] = []
            for config in configs:
                tools.extend(await load_mcp_server_tools(config))
            return tools
        except Exception as exc:
            logger.debug("Could not load scoped DB MCP configs: %s", exc)
            return []

    if _client is None:
        try:
            from nexagent.tools.mcp.registry import list_mcp_server_configs

            all_db_configs = await list_mcp_server_configs()
            if all_db_configs:
                tools: list[BaseTool] = []
                for config in all_db_configs:
                    if config.get("is_enabled"):
                        tools.extend(await load_mcp_server_tools(config))
                _client = MCPClient([])
                _client._tools = tools
                _client._loaded = True
        except Exception as exc:
            logger.debug("Could not load DB MCP configs: %s", exc)
    return await _get_client().load_tools()


async def load_mcp_server_tools(
    config: dict[str, Any],
    *,
    use_cache: bool = True,
    respect_enabled: bool = True,
    raise_errors: bool = False,
) -> list[BaseTool]:
    """Load one server's tools with TTL cache and tool-level filtering."""
    if respect_enabled and config.get("is_enabled") is False:
        return []
    server_id = str(config.get("id") or config.get("name") or "")
    config_hash = _config_hash(config)
    cache_key = f"{server_id}:{config_hash}"
    entry = _TOOL_CACHE.get(cache_key)
    if use_cache and entry and not entry.expired:
        return _filter_disabled_tools(entry.tools, config.get("disabled_tools") or [])

    tools = await MCPClient([config], raise_errors=raise_errors).load_tools()
    _TOOL_CACHE[cache_key] = MCPToolCacheEntry(server_id=server_id, config_hash=config_hash, tools=list(tools))
    return _filter_disabled_tools(tools, config.get("disabled_tools") or [])


async def test_mcp_server(server_id: str) -> dict[str, Any]:
    """Run an uncached connection test for one installed MCP server."""
    from nexagent.tools.mcp.registry import get_mcp_server_config

    config = await get_mcp_server_config(server_id, include_disabled=True)
    if config is None:
        raise KeyError(f"MCP server not found: {server_id}")

    start = time.perf_counter()
    try:
        tools = await MCPClient([config], raise_errors=True).load_tools()
        config_hash = _config_hash(config)
        _TOOL_CACHE[f"{server_id}:{config_hash}"] = MCPToolCacheEntry(
            server_id=server_id,
            config_hash=config_hash,
            tools=list(tools),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": len(tools) > 0,
            "server_id": server_id,
            "latency_ms": latency_ms,
            "tool_count": len(tools),
            "error_type": "" if tools else "schema_error",
            "tools": [_tool_payload(tool, config.get("disabled_tools") or []) for tool in tools],
            "message": f"Loaded {len(tools)} tool(s)" if tools else "No tools were loaded from this MCP server",
            "cache_ttl_seconds": MCP_TOOL_CACHE_TTL_SECONDS,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "server_id": server_id,
            "latency_ms": latency_ms,
            "tool_count": 0,
            "error_type": classify_mcp_error(exc),
            "tools": [],
            "message": str(exc),
            "cache_ttl_seconds": MCP_TOOL_CACHE_TTL_SECONDS,
        }


def mcp_tool_cache_snapshot() -> dict[str, Any]:
    """Return UI-facing MCP tool cache state."""
    now = time.time()
    entries = []
    for entry in _TOOL_CACHE.values():
        entries.append(
            {
                "server_id": entry.server_id,
                "tool_count": len(entry.tools),
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
                "ttl_remaining_seconds": max(0, int(entry.expires_at - now)),
                "expired": entry.expired,
            }
        )
    return {
        "ttl_seconds": MCP_TOOL_CACHE_TTL_SECONDS,
        "last_invalidated_at": _LAST_INVALIDATED_AT,
        "entries": entries,
    }


def classify_mcp_error(error: BaseException | str) -> str:
    """Classify MCP failures into stable UI/API categories."""
    text = str(error).lower()
    if isinstance(error, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if any(marker in text for marker in ("unauthorized", "forbidden", "401", "403", "auth", "token")):
        return "auth_error"
    if any(marker in text for marker in ("schema", "validation", "invalid request", "invalid schema")):
        return "schema_error"
    if any(
        marker in text
        for marker in (
            "connect",
            "connection",
            "refused",
            "econn",
            "enoent",
            "not found",
            "no such file",
            "dns",
            "name resolution",
            "spawn",
            "could not start",
        )
    ):
        return "connection_error"
    return "tool_runtime_error"


def _filter_disabled_tools(tools: list[BaseTool], disabled_tools: list[str]) -> list[BaseTool]:
    disabled = set(disabled_tools or [])
    return [tool for tool in tools if tool.name not in disabled]


def _tool_payload(tool: BaseTool, disabled_tools: list[str]) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "category": "mcp",
        "enabled": tool.name not in set(disabled_tools or []),
    }


def _config_hash(config: dict[str, Any]) -> str:
    relevant = {
        "id": config.get("id") or config.get("name"),
        "transport": config.get("transport") or "",
        "command": config.get("command") or [],
        "url": config.get("url") or "",
        "env": config.get("env") or {},
    }
    raw = json.dumps(relevant, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
