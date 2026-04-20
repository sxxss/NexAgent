"""MCP (Model Context Protocol) client integration for NexAgent.

Connects to external MCP servers and registers their tools into the ToolRegistry.
Configure servers in config.yaml under `mcp_servers`.
"""

from nexagent.tools.mcp.client import MCPClient, load_mcp_tools

__all__ = ["MCPClient", "load_mcp_tools"]
