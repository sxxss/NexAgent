"""Verify Phase 5 advanced backend, docs, SDK, and CI surface."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
CORE_DIR = BACKEND_DIR / "packages" / "core"


def _configure_runtime() -> None:
    for path in (BACKEND_DIR, CORE_DIR):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    os.environ.setdefault("NEXAGENT_CHECKPOINTER", "memory")
    os.environ.setdefault("NEXAGENT_DEFAULT_MODEL", "fake")
    os.environ["NEXAGENT_DATA_DIR"] = str(PROJECT_ROOT / ".nexagent" / "verify_phase5")
    os.environ["NEXAGENT_ALLOW_INPROCESS_CODE_EXEC"] = "1"


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


async def verify_services() -> None:
    from nexagent.client import NexAgentClient
    from nexagent.services.channel_service import handle_inbound_message, list_channels
    from nexagent.services.memory_service import get_user_memory, upsert_memory
    from nexagent.services.subagent_service import SubAgentTask, run_subagents
    from nexagent.tools.builtin.code_exec import get_code_exec_tool
    from nexagent.tools.mcp.client import load_mcp_tools

    if NexAgentClient is None:
        _fail("NexAgentClient import failed")
    for method in (
        "create_knowledge_base",
        "upload_text_file",
        "process_file",
        "search_knowledge_base",
        "channels",
        "send_channel_message",
        "memory",
        "set_memory",
        "run_subagents",
    ):
        if not hasattr(NexAgentClient, method):
            _fail(f"NexAgentClient missing method: {method}")
    _ok("Python SDK exposes Phase 5 helper methods")

    memory = upsert_memory("verify-user", "language", "zh-CN")
    if memory["value"] != "zh-CN" or "language" not in get_user_memory("verify-user"):
        _fail("memory service failed")
    _ok("long-term memory service works")

    result = await run_subagents(
        [SubAgentTask(agent="chatbot", message="hello", model="fake", tools=["none"])],
        max_concurrency=1,
    )
    if result["succeeded"] != 1:
        _fail(f"sub-agent service failed: {result}")
    _ok("sub-agent orchestration works")

    output = await get_code_exec_tool().ainvoke({"code": "print(2 + 3)"})
    if output.strip() != "5":
        _fail(f"sandbox tool failed: {output}")
    _ok("sandbox code execution tool works")

    tools = await load_mcp_tools()
    if not isinstance(tools, list):
        _fail("MCP loader did not return a list")
    _ok("MCP loader is callable")

    channels = list_channels()
    if not {"telegram", "feishu", "wechat", "generic"}.issubset({item["id"] for item in channels}):
        _fail(f"channel registry incomplete: {channels}")
    channel_result = await handle_inbound_message(
        channel="generic",
        text="hello",
        user_id="verify-channel",
        model="fake",
        tools=["none"],
    )
    if channel_result.get("response") != "NexAgent test response.":
        _fail(f"channel webhook dispatch failed: {channel_result}")
    _ok("IM channel webhook dispatch works")


def verify_http_routes() -> None:
    from fastapi.testclient import TestClient

    from app.gateway.app import app

    client = TestClient(app)
    for path in (
        "/api/agents/tools",
        "/api/agents/skills",
        "/api/channels/",
        "/api/memory/verify-user",
        "/api/system/info",
    ):
        response = client.get(path)
        if response.status_code != 200:
            _fail(f"GET {path} returned {response.status_code}: {response.text}")

    response = client.post(
        "/api/agents/subagents/run",
        json={"tasks": [{"agent": "chatbot", "message": "hello", "model": "fake", "tools": ["none"]}]},
    )
    if response.status_code != 200 or response.json().get("succeeded") != 1:
        _fail(f"subagent HTTP route failed: {response.status_code} {response.text}")
    response = client.post(
        "/api/channels/generic/webhook",
        json={"text": "hello", "user_id": "verify-http", "model": "fake", "tools": ["none"]},
    )
    if response.status_code != 200 or response.json().get("response") != "NexAgent test response.":
        _fail(f"channel HTTP route failed: {response.status_code} {response.text}")
    _ok("Phase 5 HTTP routes respond")


def verify_docs_and_ci() -> None:
    for rel in (
        "README.md",
        "README_zh.md",
        "docs/index.md",
        ".github/workflows/ci.yml",
        "backend/packages/core/nexagent/client.py",
    ):
        if not (PROJECT_ROOT / rel).is_file():
            _fail(f"missing Phase 5 artifact: {rel}")
    _ok("README, docs, SDK and CI artifacts are present")


async def main_async() -> int:
    _configure_runtime()
    await verify_services()
    from nexagent.db.init_db import init_db

    await init_db()
    verify_http_routes()
    verify_docs_and_ci()
    print("Phase 5 verification passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
