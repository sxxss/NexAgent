"""MCP marketplace and installed-server management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class MCPInstallRequest(BaseModel):
    id: str
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPCustomRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    transport: str = "stdio"
    command: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    transport: str | None = None
    command: list[str] | None = None
    url: str | None = None
    is_enabled: bool | None = None
    env: dict[str, str] | None = None
    disabled_tools: list[str] | None = None


class MCPToolUpdateRequest(BaseModel):
    is_enabled: bool


SUPPORTED_TRANSPORTS = {"stdio", "sse", "http", "streamable_http"}


@router.get("/registry")
async def registry():
    """Return built-in MCP marketplace entries with installed state."""
    from nexagent.tools.mcp.registry import list_installed_mcp_servers, list_registry

    installed = {item["id"]: item for item in await list_installed_mcp_servers()}
    entries = []
    for item in list_registry():
        entries.append({
            **item,
            "installed": item["id"] in installed,
            "is_enabled": installed.get(item["id"], {}).get("is_enabled", False),
        })
    return {"registry": entries}


@router.get("/installed")
async def installed():
    """List installed MCP servers."""
    from nexagent.tools.mcp.client import mcp_tool_cache_snapshot
    from nexagent.tools.mcp.registry import list_installed_mcp_servers

    servers = await list_installed_mcp_servers()
    cache = mcp_tool_cache_snapshot()
    by_server = {entry["server_id"]: entry for entry in cache["entries"]}
    return {
        "servers": [
            {
                **server,
                "cache": by_server.get(server["id"]),
                "disabled_tool_count": len(server.get("disabled_tools") or []),
            }
            for server in servers
        ],
        "cache": cache,
    }


@router.post("/install", status_code=201)
async def install(body: MCPInstallRequest):
    """Install a built-in MCP server entry into the local DB config."""
    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.tools.mcp.client import invalidate_mcp_caches
    from nexagent.tools.mcp.registry import get_registry_item

    item = get_registry_item(body.id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"MCP registry item '{body.id}' not found")

    async with AsyncSessionLocal() as session:
        exists = await session.get(MCPServer, item.id)
        if exists:
            raise HTTPException(status_code=409, detail=f"MCP server '{item.id}' is already installed")
        server = MCPServer(
            id=item.id,
            name=item.name,
            description=item.description,
            transport=item.transport,
            url=item.url or None,
            is_enabled=body.enabled,
            source="registry",
        )
        server.command = item.command
        server.env = body.env
        server.disabled_tools = []
        session.add(server)
        await session.commit()
        await session.refresh(server)

    invalidate_mcp_caches(item.id)
    return server.to_dict()


@router.post("/{server_id}/test")
async def test_server(server_id: str):
    """Try to load tools from one installed MCP server."""
    from nexagent.tools.mcp.client import test_mcp_server

    try:
        return await test_mcp_server(server_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/custom", status_code=201)
async def custom(body: MCPCustomRequest):
    """Install a custom MCP server."""
    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.tools.mcp.client import invalidate_mcp_caches

    if body.transport not in SUPPORTED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"unsupported MCP transport: {body.transport}")
    if body.transport == "stdio" and not body.command:
        raise HTTPException(status_code=400, detail="stdio MCP servers require a command")
    if body.transport != "stdio" and not body.url:
        raise HTTPException(status_code=400, detail="remote MCP servers require a url")

    async with AsyncSessionLocal() as session:
        exists = await session.get(MCPServer, body.id)
        if exists:
            raise HTTPException(status_code=409, detail=f"MCP server '{body.id}' already exists")
        server = MCPServer(
            id=body.id,
            name=body.name,
            description=body.description,
            transport=body.transport,
            url=body.url or None,
            is_enabled=body.enabled,
            source="custom",
        )
        server.command = body.command
        server.env = body.env
        server.disabled_tools = []
        session.add(server)
        await session.commit()
        await session.refresh(server)

    invalidate_mcp_caches(body.id)
    return server.to_dict()


@router.put("/{server_id}")
async def update(server_id: str, body: MCPUpdateRequest):
    """Enable/disable an MCP server or update its environment."""
    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.tools.mcp.client import invalidate_mcp_caches

    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
        if body.name is not None:
            server.name = body.name
        if body.description is not None:
            server.description = body.description
        if body.transport is not None:
            if body.transport not in SUPPORTED_TRANSPORTS:
                raise HTTPException(status_code=400, detail=f"unsupported MCP transport: {body.transport}")
            server.transport = body.transport
        if body.command is not None:
            server.command = body.command
        if body.url is not None:
            server.url = body.url or None
        if body.is_enabled is not None:
            server.is_enabled = body.is_enabled
        if body.env is not None:
            server.env = body.env
        if body.disabled_tools is not None:
            server.disabled_tools = sorted({name for name in body.disabled_tools if name})
        await session.commit()
        await session.refresh(server)

    invalidate_mcp_caches(server_id)
    return server.to_dict()


@router.put("/{server_id}/tools/{tool_name:path}")
async def update_tool(server_id: str, tool_name: str, body: MCPToolUpdateRequest):
    """Enable or disable a single discovered tool on an installed MCP server."""
    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.tools.mcp.client import invalidate_mcp_caches

    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
        disabled = set(server.disabled_tools or [])
        if body.is_enabled:
            disabled.discard(tool_name)
        else:
            disabled.add(tool_name)
        server.disabled_tools = sorted(disabled)
        await session.commit()
        await session.refresh(server)

    invalidate_mcp_caches(server_id)
    return server.to_dict()


@router.delete("/{server_id}", status_code=204)
async def uninstall(server_id: str):
    """Uninstall an MCP server."""
    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.tools.mcp.client import invalidate_mcp_caches

    async with AsyncSessionLocal() as session:
        server = await session.get(MCPServer, server_id)
        if not server:
            raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found")
        await session.delete(server)
        await session.commit()

    invalidate_mcp_caches(server_id)
