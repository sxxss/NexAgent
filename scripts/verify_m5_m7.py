"""Verify roadmap M5-M7 product surfaces."""

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
    os.environ["NEXAGENT_DATA_DIR"] = str(PROJECT_ROOT / ".nexagent" / "verify_m5_m7")


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


async def verify_backend() -> None:
    from fastapi.testclient import TestClient

    from app.gateway.app import app
    from nexagent.db.init_db import init_db
    from nexagent.skills.loader import SkillLoader
    from nexagent.tools.builtin.code_exec import get_code_exec_tool
    from nexagent.tools.mcp.registry import list_registry

    await init_db()

    if not list_registry():
        _fail("MCP registry is empty")
    _ok("MCP registry is available")

    loader = SkillLoader()
    for name in ("knowledge-base", "knowledge-graph", "deep-research"):
        skill = loader.load(name)
        if skill is None:
            _fail(f"missing skill: {name}")
        executable = loader.load_executable(name)
        if executable is None:
            _fail(f"skill has no executable layer: {name}")
    _ok("Skills expose executable skill.py layers")

    output = await get_code_exec_tool().ainvoke({"code": "print(40 + 2)"})
    if output.strip() != "42":
        _fail(f"sandbox execution failed: {output}")
    _ok("sandbox code execution works")

    client = TestClient(app)
    for path in ("/api/mcp/registry", "/api/mcp/installed", "/api/skills/registry", "/api/skills/"):
        response = client.get(path)
        if response.status_code != 200:
            _fail(f"GET {path} returned {response.status_code}: {response.text}")

    response = client.post(
        "/api/agents/subagents/stream",
        json={"tasks": [{"agent": "chatbot", "message": "hello", "model": "fake", "tools": ["none"]}]},
    )
    if response.status_code != 200 or "subagent_done" not in response.text:
        _fail(f"sub-agent stream failed: {response.status_code} {response.text}")
    _ok("M5-M7 HTTP routes respond")


def verify_frontend_files() -> None:
    required = [
        "src/app/mcp/page.tsx",
        "src/app/skills/page.tsx",
        "src/app/subagents/page.tsx",
        "src/components/chat/SubAgentTrace.tsx",
        "src/lib/api.ts",
    ]
    for rel in required:
        if not (FRONTEND_DIR / rel).is_file():
            _fail(f"missing frontend artifact: {rel}")
    _ok("M5-M7 frontend artifacts are present")

    api_text = (FRONTEND_DIR / "src/lib/api.ts").read_text(encoding="utf-8")
    for symbol in ("fetchMCPRegistry", "installMCP", "fetchSkillRegistry", "streamSubAgents"):
        if symbol not in api_text:
            _fail(f"frontend API missing {symbol}")
    _ok("frontend API client covers M5-M7")

    if not (PROJECT_ROOT / "docker" / "sandbox" / "Dockerfile").is_file():
        _fail("missing docker/sandbox/Dockerfile")
    _ok("Docker sandbox image file is present")


async def main_async() -> int:
    _configure_runtime()
    await verify_backend()
    verify_frontend_files()
    print("M5-M7 verification passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
