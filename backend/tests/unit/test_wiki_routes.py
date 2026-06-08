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
async def test_create_wiki_kb_uses_selected_llm(monkeypatch):
    calls = {}

    class FakeManager:
        async def create_kb(self, **kwargs):
            calls["create"] = kwargs
            def to_dict(**_kwargs):
                return {
                    "kb_id": "wiki-1",
                    "kb_type": "wiki",
                    "name": kwargs["name"],
                    "llm_info": kwargs["llm_info"].to_dict(),
                }
            return SimpleNamespace(
                to_dict=to_dict
            )

    async def fake_resolve(model_ref, capability):
        calls["resolve"] = (model_ref, capability)
        return {
            "provider_id": "provider-a",
            "model_id": "chat-model",
            "base_url": "https://llm.example/v1",
            "api_key": "secret",
        }

    monkeypatch.setattr(knowledge, "_prod_enabled", lambda: True)
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())
    monkeypatch.setattr(knowledge, "_resolve_provider_model", fake_resolve)

    result = await knowledge.create_kb(
        knowledge.KBCreateRequest(
            name="Wiki",
            description="notes",
            kb_type="wiki",
            llm_model="provider-a::chat-model",
        )
    )

    assert calls["resolve"] == ("provider-a::chat-model", "chat")
    assert calls["create"]["embed_info"] is None
    assert calls["create"]["llm_info"].provider == "provider-a"
    assert calls["create"]["llm_info"].model == "chat-model"
    assert "api_key" not in result["llm_info"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_lightrag_kb_uses_selected_embedding_and_llm(monkeypatch):
    calls = {}

    class FakeManager:
        async def create_kb(self, **kwargs):
            calls["create"] = kwargs
            def to_dict(**_kwargs):
                return {
                    "kb_id": "light-1",
                    "kb_type": "lightrag",
                    "name": kwargs["name"],
                    "embed_info": kwargs["embed_info"].to_dict(),
                    "llm_info": kwargs["llm_info"].to_dict(),
                }
            return SimpleNamespace(
                to_dict=to_dict
            )

    async def fake_resolve(model_ref, capability):
        calls.setdefault("resolve", []).append((model_ref, capability))
        if capability == "embedding":
            return {
                "provider_id": "embed-provider",
                "model_id": "embed-model",
                "base_url": "https://embed.example/v1",
                "api_key": "embed-secret",
                "dimension": 1536,
            }
        return {
            "provider_id": "llm-provider",
            "model_id": "chat-model",
            "base_url": "https://llm.example/v1",
            "api_key": "llm-secret",
        }

    monkeypatch.setattr(knowledge, "_prod_enabled", lambda: False)
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())
    monkeypatch.setattr(knowledge, "_resolve_provider_model", fake_resolve)

    await knowledge.create_kb(
        knowledge.KBCreateRequest(
            name="Graph KB",
            description="graph",
            kb_type="lightrag",
            embed_model="embed-provider::embed-model",
            llm_model="llm-provider::chat-model",
        )
    )

    assert calls["resolve"] == [
        ("llm-provider::chat-model", "chat"),
        ("embed-provider::embed-model", "embedding"),
    ]
    assert calls["create"]["embed_info"].base_url == "https://embed.example/v1"
    assert calls["create"]["embed_info"].dimension == 1536
    assert calls["create"]["llm_info"].provider == "llm-provider"
    assert calls["create"]["llm_info"].model == "chat-model"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_model_config_resolves_selected_llm(monkeypatch):
    calls = {}

    class FakeManager:
        def update_model_config(self, kb_id, patch):
            calls["patch"] = patch
            return {"kb": {"kb_id": kb_id, "llm_info": {"model": patch["llm_model"]}}}

    async def fake_resolve(model_ref, capability):
        calls["resolve"] = (model_ref, capability)
        return {
            "provider_id": "provider-a",
            "model_id": "chat-model",
            "base_url": "https://llm.example/v1",
            "api_key": "secret",
        }

    async def fake_prod_kb(kb_id):
        return None

    async def fake_is_local_wiki_kb(kb_id):
        return True

    monkeypatch.setattr(knowledge, "_prod_kb", fake_prod_kb)
    monkeypatch.setattr(knowledge, "_is_local_wiki_kb", fake_is_local_wiki_kb)
    monkeypatch.setattr(knowledge, "_kb_or_404", lambda kb_id: (FakeManager(), SimpleNamespace()))
    monkeypatch.setattr(knowledge, "_resolve_provider_model", fake_resolve)

    result = await knowledge.update_model_config(
        "wiki-1",
        knowledge.ModelConfigUpdate(llm_model="provider-a::chat-model"),
    )

    assert calls["resolve"] == ("provider-a::chat-model", "chat")
    assert calls["patch"] == {
        "llm_model": "chat-model",
        "llm_provider": "provider-a",
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "secret",
    }
    assert result["kb"]["llm_info"]["model"] == "chat-model"


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
