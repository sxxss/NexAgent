from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.routers import knowledge


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_kb_accepts_wiki_without_embedding(monkeypatch):
    calls = {}

    class FakeManager:
        async def create_kb(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                to_dict=lambda: {"kb_id": "wiki-1", "kb_type": "wiki", "name": kwargs["name"]}
            )

    monkeypatch.setattr(knowledge, "_prod_enabled", lambda: True)
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    result = await knowledge.create_kb(
        knowledge.KBCreateRequest(name="Wiki", description="notes", kb_type="wiki")
    )

    assert result == {"kb_id": "wiki-1", "kb_type": "wiki", "name": "Wiki"}
    assert calls["kb_type"] == "wiki"
    assert calls["embed_info"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_pages_route_rejects_non_wiki(monkeypatch):
    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="milvus"))

    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    with pytest.raises(HTTPException) as exc:
        await knowledge.list_wiki_pages("kb-1")

    assert exc.value.status_code == 400
    assert "Wiki" in str(exc.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_pages_route_delegates_to_backend(monkeypatch):
    calls = {}

    class FakeBackend:
        def list_wiki_pages(self, kb_id, page_type=None, q=None, status=None, source_file_id=None):
            calls.update(
                {
                    "kb_id": kb_id,
                    "page_type": page_type,
                    "q": q,
                    "status": status,
                    "source_file_id": source_file_id,
                }
            )
            return {"pages": [{"id": "topic:alpha"}]}

    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return FakeBackend()

    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    result = await knowledge.list_wiki_pages(
        "wiki-1",
        type="topic",
        q="alpha",
        status="generated",
        source_file_id="file-1",
    )

    assert result == {"pages": [{"id": "topic:alpha"}]}
    assert calls == {
        "kb_id": "wiki-1",
        "page_type": "topic",
        "q": "alpha",
        "status": "generated",
        "source_file_id": "file-1",
    }
