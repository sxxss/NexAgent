from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_fact_memory_store_dedupes(monkeypatch):
    from nexagent.agents.memory import get_memory, reload_memory, upsert_fact

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / "memory-store"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXAGENT_MEMORY_PATH", str(base / "memory.json"))
    reload_memory()

    first = upsert_fact("u1", "Likes concise answers", category="preference", confidence=0.6)
    second = upsert_fact("u1", "Likes concise answers", category="preference", confidence=0.9)

    assert first.id == second.id
    assert get_memory("u1").facts[0].confidence == 0.9


@pytest.mark.unit
def test_api_key_create_verify_and_revoke(monkeypatch):
    from app.gateway.auth.manager import create_api_key, revoke_api_key, verify_api_key

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / "auth"
    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(base))

    created = create_api_key("u1", "test", ["knowledge:read"])
    raw = created["api_key"]

    assert verify_api_key(raw, "knowledge:read") is not None
    assert verify_api_key(raw, "sandbox:execute") is None
    assert revoke_api_key(created["id"]) is True
    assert verify_api_key(raw, "knowledge:read") is None


@pytest.mark.unit
def test_channel_bus_formats_outbound():
    from nexagent.services.channel_service import format_outbound, list_channels

    assert any(item["id"] == "wecom" for item in list_channels())
    assert format_outbound("telegram", "hello")["method"] == "sendMessage"


@pytest.mark.unit
async def test_subagent_submit_status(monkeypatch):
    from nexagent.services import subagent_service
    from nexagent.services.subagent_service import SubAgentTask, get_task_status, submit_subagent

    async def fake_invoke_chat(*args, **kwargs):
        return {"response": "done", "thread_id": "t1"}

    async def fake_resolve(task, **kwargs):
        return "chatbot", {"tools": ["none"], "model": "fake"}

    monkeypatch.setattr("nexagent.services.chat_service.invoke_chat", fake_invoke_chat)
    monkeypatch.setattr(subagent_service, "_resolve_task_runtime", fake_resolve)

    task_id = await submit_subagent(SubAgentTask(agent="chatbot", message="work"), timeout_seconds=5)
    for _ in range(20):
        status = get_task_status(task_id)
        if status["status"] == "completed":
            break
        import asyncio

        await asyncio.sleep(0.01)

    assert get_task_status(task_id)["result"] == "done"
