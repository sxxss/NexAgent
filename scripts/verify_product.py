"""Verify product-level integration contracts across backend, frontend, and deploy config."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
CORE_DIR = BACKEND_DIR / "packages" / "core"
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def _configure_runtime() -> None:
    for path in (BACKEND_DIR, CORE_DIR):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    os.environ.setdefault("NEXAGENT_CHECKPOINTER", "memory")
    os.environ.setdefault("NEXAGENT_DEFAULT_MODEL", "fake")
    os.environ.setdefault("NEXAGENT_ALLOW_INPROCESS_CODE_EXEC", "1")
    os.environ.setdefault("NEXAGENT_SECRET_KEY", "verify-product-secret-key-000000")
    os.environ["NEXAGENT_DATA_DIR"] = str(PROJECT_ROOT / ".nexagent" / "verify_product")


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


async def verify_backend_contracts() -> None:
    from fastapi.testclient import TestClient

    from app.gateway.app import app
    from app.gateway.routers.chat import ChatRequest, build_context_overrides, resolve_agent_runtime
    from nexagent.agents.context import BaseContext
    from nexagent.db.init_db import init_db
    from nexagent.services.subagent_service import SubAgentTask, run_subagents
    from nexagent.tools.mcp.client import load_mcp_tools
    from nexagent.tools.registry import list_tool_specs

    await init_db()

    context_fields = BaseContext.get_configurable_items()
    for field in ("mcp_ids", "allow_subagents"):
        if field not in context_fields:
            _fail(f"BaseContext missing configurable field: {field}")
    _ok("Agent runtime context exposes MCP and Sub-Agent controls")

    if "mcp_ids" not in ChatRequest.model_fields:
        _fail("ChatRequest missing mcp_ids")
    runtime = await resolve_agent_runtime("chatbot")
    context = build_context_overrides(ChatRequest(message="hello"), runtime, "verify-thread")
    if "mcp_ids" not in context or "allow_subagents" not in context:
        _fail(f"Chat context missing product fields: {context}")
    _ok("Chat runtime merges persisted Agent product settings")

    tool_names = {spec.name for spec in list_tool_specs()}
    if "delegate_subagents" not in tool_names:
        _fail("delegate_subagents tool is not registered")
    _ok("Sub-Agent delegation tool is registered")

    scoped_mcp_tools = await load_mcp_tools(["missing-server-id"])
    if scoped_mcp_tools != []:
        _fail("Scoped MCP loader should return no tools for an unknown server id")
    _ok("MCP loader supports Agent-scoped server ids")

    result = await run_subagents(
        [SubAgentTask(agent="chatbot", message="hello", model="fake", tools=["none"])],
        max_concurrency=1,
    )
    if result["succeeded"] != 1:
        _fail(f"Sub-Agent service failed: {result}")
    _ok("Sub-Agent service can execute configured tasks")

    client = TestClient(app)
    ready = client.get("/health/ready")
    if ready.status_code != 200:
        _fail(f"/health/ready returned {ready.status_code}: {ready.text}")
    checks = ready.json().get("checks", {})
    for check_name in ("config", "database", "data_dir"):
        if checks.get(check_name, {}).get("status") != "ok":
            _fail(f"/health/ready check failed for {check_name}: {checks}")
    _ok("Readiness probe validates config, database, and data dir")


def verify_frontend_contracts() -> None:
    home = (FRONTEND_DIR / "src/app/page.tsx").read_text(encoding="utf-8")
    agents = (FRONTEND_DIR / "src/app/agents/page.tsx").read_text(encoding="utf-8")
    api = (FRONTEND_DIR / "src/lib/api.ts").read_text(encoding="utf-8")

    for symbol in ("fetchAgents", "selectedAgent", "agent: selectedAgent"):
        if symbol not in home:
            _fail(f"Chat page missing Agent selector contract: {symbol}")
    _ok("Chat page can send messages through selected Agents")

    for symbol in ("fetchInstalledMCP", "mcpServers", "mcp_ids", "allow_subagents"):
        if symbol not in agents:
            _fail(f"Agent page missing product configuration contract: {symbol}")
    _ok("Agent editor exposes MCP and Sub-Agent configuration")

    for symbol in ("mcp_ids?: string[]", "allow_subagents?: boolean"):
        if symbol not in api:
            _fail(f"Frontend API types missing {symbol}")
    _ok("Frontend API types include product settings")


def verify_deploy_contracts() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
    core_pyproject = (CORE_DIR / "pyproject.toml").read_text(encoding="utf-8")

    if "postgresql+asyncpg://" not in compose:
        _fail("docker-compose DATABASE_URL must use the asyncpg SQLAlchemy driver")
    if "asyncpg>=0.30.0" not in core_pyproject or "asyncpg>=0.30.0" not in dockerfile:
        _fail("asyncpg dependency is missing from backend packaging")
    if "/health/ready" not in dockerfile:
        _fail("Docker healthcheck should use /health/ready")
    _ok("Docker deployment config is aligned with async DB readiness")


async def main_async() -> int:
    _configure_runtime()
    await verify_backend_contracts()
    verify_frontend_contracts()
    verify_deploy_contracts()
    print("Product verification passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
