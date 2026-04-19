"""Built-in MCP server registry and DB-backed MCP configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MCPRegistryItem:
    id: str
    name: str
    description: str
    transport: str = "stdio"
    command: list[str] = field(default_factory=list)
    url: str = ""
    env_schema: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "command": self.command,
            "url": self.url,
            "env_schema": self.env_schema,
            "tags": self.tags,
        }


BUILTIN_MCP_REGISTRY: list[MCPRegistryItem] = [
    MCPRegistryItem(
        id="filesystem",
        name="Filesystem",
        description="Expose a bounded filesystem directory to agents through MCP tools.",
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
        env_schema=[],
        tags=["local", "files"],
    ),
    MCPRegistryItem(
        id="fetch",
        name="Fetch",
        description="Fetch and convert web pages for agent use.",
        command=["uvx", "mcp-server-fetch"],
        tags=["web"],
    ),
    MCPRegistryItem(
        id="github",
        name="GitHub",
        description="Read and manage GitHub repositories using a personal access token.",
        command=["npx", "-y", "@modelcontextprotocol/server-github"],
        env_schema=[{"name": "GITHUB_PERSONAL_ACCESS_TOKEN", "description": "GitHub access token"}],
        tags=["code", "github"],
    ),
    MCPRegistryItem(
        id="postgres",
        name="PostgreSQL",
        description="Query a PostgreSQL database through MCP.",
        command=["npx", "-y", "@modelcontextprotocol/server-postgres"],
        env_schema=[{"name": "POSTGRES_CONNECTION_STRING", "description": "PostgreSQL connection string"}],
        tags=["database"],
    ),
]


def list_registry() -> list[dict[str, Any]]:
    return [item.to_dict() for item in BUILTIN_MCP_REGISTRY]


def get_registry_item(server_id: str) -> MCPRegistryItem | None:
    return next((item for item in BUILTIN_MCP_REGISTRY if item.id == server_id), None)


async def list_installed_mcp_servers() -> list[dict[str, Any]]:
    """Return DB-installed MCP server configs."""
    from sqlalchemy import select

    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(MCPServer).order_by(MCPServer.created_at.desc()))
        return [server.to_dict() for server in result.scalars().all()]


async def list_enabled_mcp_server_configs(server_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Return enabled MCP server configs suitable for MCPClient."""
    return await list_mcp_server_configs(server_ids=server_ids, enabled_only=True)


async def get_mcp_server_config(server_id: str, *, include_disabled: bool = False) -> dict[str, Any] | None:
    """Return one installed MCP server config suitable for MCPClient."""
    configs = await list_mcp_server_configs(
        server_ids=[server_id],
        enabled_only=not include_disabled,
    )
    return configs[0] if configs else None


async def list_mcp_server_configs(
    server_ids: list[str] | None = None,
    *,
    enabled_only: bool = False,
) -> list[dict[str, Any]]:
    """Return DB MCP server configs suitable for MCPClient."""
    from sqlalchemy import select

    from nexagent.db.models import MCPServer
    from nexagent.db.session import AsyncSessionLocal

    wanted = set(server_ids or [])
    async with AsyncSessionLocal() as session:
        stmt = select(MCPServer)
        if enabled_only:
            stmt = stmt.where(MCPServer.is_enabled == True)  # noqa: E712
        if wanted:
            stmt = stmt.where(MCPServer.id.in_(wanted))
        result = await session.execute(stmt)
        servers = result.scalars().all()

    return [
        {
            "id": server.id,
            "name": server.id,
            "transport": server.transport,
            "command": server.command or [],
            "url": server.url or "",
            "env": server.env or {},
            "is_enabled": bool(server.is_enabled),
            "disabled_tools": server.disabled_tools or [],
        }
        for server in servers
    ]
