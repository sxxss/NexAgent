from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crystallize_thread_into_wiki_kb_registers_source_and_page(monkeypatch):
    from nexagent.services import wiki_service

    calls = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="# Decision Log\n\n## Summary\n\nUse Wiki KB.\n\n标签: wiki, decision")

    class FakeBackend:
        async def add_file(self, kb_id, filename, content):
            calls["add_file"] = {
                "kb_id": kb_id,
                "filename": filename,
                "content": content.decode("utf-8"),
            }
            return SimpleNamespace(file_id="file-1")

        async def parse_file(self, kb_id, file_id):
            calls["parse_file"] = (kb_id, file_id)

        async def index_file(self, kb_id, file_id):
            calls["index_file"] = (kb_id, file_id)

        async def crystallize_wiki_text(
            self,
            kb_id,
            title,
            content,
            page_type="note",
            sources=None,
            confidence="UNVERIFIED",
        ):
            calls["crystallize"] = {
                "kb_id": kb_id,
                "title": title,
                "content": content,
                "sources": sources,
                "confidence": confidence,
            }
            return {"id": "note:decision-log", "title": title, "type": page_type, "sources": sources}

    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return FakeBackend()

    async def fake_list_messages(thread_id):
        return [
            {"role": "user", "content": "Should we use Wiki KB?"},
            {"role": "assistant", "content": "Yes."},
        ]

    monkeypatch.setattr("nexagent.services.conversation_service.list_messages", fake_list_messages)
    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", lambda model=None: FakeLLM())
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())

    result = await wiki_service.crystallize_thread("thread-1", kb_id="wiki-1", model="test/model")

    assert result["id"] == "note:decision-log"
    assert result["file_id"] == "file-1"
    assert calls["add_file"]["filename"] == "Decision Log.md"
    assert calls["crystallize"]["sources"] == ["file-1"]
    assert calls["crystallize"]["confidence"] == "UNVERIFIED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_global_wiki_crystallize_requires_target_kb(monkeypatch):
    from app.gateway.routers import wiki

    called = False

    async def fake_crystallize_thread(thread_id, kb_id=None, model=None):
        nonlocal called
        called = True
        return {"id": "note:hidden"}

    monkeypatch.setattr("nexagent.services.wiki_service.crystallize_thread", fake_crystallize_thread)

    with pytest.raises(HTTPException) as exc:
        await wiki.crystallize(wiki.CrystallizeRequest(thread_id="thread-1"))

    assert exc.value.status_code == 400
    assert "Wiki 知识库" in str(exc.value.detail)
    assert called is False
