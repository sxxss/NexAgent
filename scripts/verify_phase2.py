"""Verify Phase 2 agent engine, model config, tools, and chat route."""

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


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


def verify_registry() -> None:
    from nexagent.agents.base import BaseAgent
    from nexagent.agents.registry import get_agent, get_agent_spec, list_agent_specs

    specs = {spec.id: spec for spec in list_agent_specs()}
    if "chatbot" not in specs:
        _fail("chatbot agent is not registered")
    spec = get_agent_spec("chatbot")
    agent = get_agent("chatbot")
    if not isinstance(agent, BaseAgent):
        _fail("chatbot agent does not inherit BaseAgent")
    if "streaming" not in spec.capabilities:
        _fail("chatbot spec must advertise streaming capability")
    _ok("agent registry exposes chatbot")


def verify_context_and_models() -> None:
    from nexagent.agents.context import BaseContext
    from nexagent.models.factory import load_chat_model, validate_model_name

    items = BaseContext.get_configurable_items()
    for key in ("system_prompt", "model", "tools", "kb_ids", "skills"):
        if key not in items:
            _fail(f"BaseContext missing configurable field: {key}")

    if validate_model_name("fake") != "fake":
        _fail("fake model validation failed")
    model = load_chat_model("fake")
    if model is None:
        _fail("fake model failed to load")
    _ok("context schema and fake model are available")


def verify_tools_and_skills() -> None:
    from nexagent.skills.loader import SkillLoader
    from nexagent.tools.registry import list_tool_specs, load_tools

    tools = {spec.name for spec in list_tool_specs()}
    required_tools = {"knowledge_search", "web_search", "execute_python"}
    missing = required_tools - tools
    if missing:
        _fail(f"missing built-in tools: {sorted(missing)}")
    if load_tools(["knowledge_search"], kb_ids=[]) == []:
        _fail("knowledge_search tool failed to load")

    skills = set(SkillLoader().discover())
    if "knowledge-base" not in skills:
        _fail("knowledge-base skill is missing")
    _ok("tool registry and skill loader are available")


async def verify_chat_service() -> None:
    from nexagent.services.chat_service import invoke_chat, stream_chat

    result = await invoke_chat(
        "hello",
        agent_name="chatbot",
        context_overrides={"model": "fake", "tools": ["none"]},
    )
    if result.get("response") != "NexAgent test response.":
        _fail(f"unexpected fake chat response: {result}")
    _ok("non-streaming chat invocation works")

    statuses: list[str] = []
    async for chunk in stream_chat(
        "hello",
        agent_name="chatbot",
        context_overrides={"model": "fake", "tools": ["none"]},
    ):
        status = chunk.get("status") if isinstance(chunk, dict) else chunk.decode("utf-8")
        if status == "started" or '"status": "started"' in status:
            statuses.append("started")
        if status == "finished" or '"status": "finished"' in status:
            statuses.append("finished")
    if statuses != ["started", "finished"]:
        _fail(f"stream_chat did not emit expected terminal statuses: {statuses}")
    _ok("streaming chat invocation works")


def verify_http_routes() -> None:
    from fastapi.testclient import TestClient

    from app.gateway.app import app
    from nexagent.db.init_db import init_db

    asyncio.run(init_db())

    client = TestClient(app)
    for path in ("/api/agents/", "/api/agents/tools", "/api/agents/skills", "/api/models"):
        response = client.get(path)
        if response.status_code != 200:
            _fail(f"GET {path} returned {response.status_code}: {response.text}")
    _ok("agent/model HTTP routes respond")


def main() -> int:
    _configure_runtime()
    verify_dir = PROJECT_ROOT / ".nexagent" / "verify_phase2"
    verify_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NEXAGENT_DATA_DIR"] = str(verify_dir)

    verify_registry()
    verify_context_and_models()
    verify_tools_and_skills()
    asyncio.run(verify_chat_service())
    verify_http_routes()
    print("Phase 2 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
