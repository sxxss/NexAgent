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
        knowledge.KBCreateRequest(name="Wiki", description="notes", kb_type="wiki", llm_model="chat-model")
    )

    assert result == {"kb_id": "wiki-1", "kb_type": "wiki", "name": "Wiki"}
    assert calls["kb_type"] == "wiki"
    assert calls["embed_info"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_wiki_kb_requires_llm():
    with pytest.raises(HTTPException) as exc:
        await knowledge.create_kb(
            knowledge.KBCreateRequest(name="Wiki", description="notes", kb_type="wiki")
        )

    assert exc.value.status_code == 400
    assert "Wiki 知识库需要配置 LLM" in str(exc.value.detail)


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
async def test_list_kbs_clears_stale_wiki_reindex_flag_when_compile_completed(monkeypatch):
    wiki_kb = SimpleNamespace(
        kb_id="wiki-1",
        kb_type="wiki",
        to_dict=lambda **_kwargs: {
            "kb_id": "wiki-1",
            "kb_type": "wiki",
            "extra": {
                "requires_reindex": True,
                "model_config": {"requires_reindex": True},
            },
        },
    )

    class FakeProdService:
        async def list_kbs(self):
            return []

    class FakeBackend:
        def _load_state(self, kb_id):
            return {"compile_status": {"status": "completed"}, "needs_recompile": False}

    class FakeManager:
        def list_kbs(self):
            return [wiki_kb]

        def _find_backend(self, kb_id):
            return FakeBackend()

    monkeypatch.setattr(knowledge, "_prod_enabled", lambda: True)
    monkeypatch.setattr(knowledge, "_prod_service", lambda: FakeProdService())
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    result = await knowledge.list_kbs()

    extra = result["knowledge_bases"][0]["extra"]
    assert extra["requires_reindex"] is False
    assert extra["model_config"]["requires_reindex"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_lightrag_kb_requires_llm_and_embedding():
    with pytest.raises(HTTPException) as exc:
        await knowledge.create_kb(
            knowledge.KBCreateRequest(
                name="Graph KB",
                description="graph",
                kb_type="lightrag",
                embed_model="embed-model",
            )
        )

    assert exc.value.status_code == 400
    assert "LightRAG 知识库需要配置 LLM" in str(exc.value.detail)

    with pytest.raises(HTTPException) as embed_exc:
        await knowledge.create_kb(
            knowledge.KBCreateRequest(
                name="Graph KB",
                description="graph",
                kb_type="lightrag",
                llm_model="chat-model",
            )
        )

    assert embed_exc.value.status_code == 400
    assert "LightRAG 知识库需要配置 Embedding" in str(embed_exc.value.detail)


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_route_enqueues_task(monkeypatch, tmp_path):
    from nexagent.services import task_service

    calls = {}
    scheduled = []

    class FakeBackend:
        def list_files(self, kb_id):
            assert kb_id == "wiki-1"
            return [SimpleNamespace(file_id="file-1", status=SimpleNamespace(value="uploaded"))]

        async def compile_wiki(self, kb_id, file_ids=None, force=False, retry_failed=False):
            calls.update(
                {
                    "kb_id": kb_id,
                    "file_ids": file_ids,
                    "force": force,
                    "retry_failed": retry_failed,
                }
            )
            return {"processed": 1, "failed": 0, "items": [{"file_id": "file-1", "status": "indexed"}]}

    class FakeManager:
        backend = FakeBackend()

        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return self.backend

    def fake_create_task(coro):
        scheduled.append(coro)
        return SimpleNamespace()

    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(tmp_path))
    task_service.reset_task_registry_for_tests()
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())
    monkeypatch.setattr(knowledge.asyncio, "create_task", fake_create_task)

    try:
        result = await knowledge.compile_wiki(
            "wiki-1",
            {
                "file_ids": ["file-1"],
                "force": True,
                "retry_failed": True,
            },
        )
        await scheduled.pop(0)
    finally:
        task_service.reset_task_registry_for_tests()

    assert result["status"] == "queued"
    assert result["task"]["kind"] == "wiki_compile"
    assert result["task"]["metadata"] == {
        "kb_id": "wiki-1",
        "file_ids": ["file-1"],
        "force": True,
        "retry_failed": True,
    }
    assert calls == {
        "kb_id": "wiki-1",
        "file_ids": ["file-1"],
        "force": True,
        "retry_failed": True,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_repair_route_enqueues_task(monkeypatch, tmp_path):
    from nexagent.services import task_service

    calls = {}
    scheduled = []

    class FakeBackend:
        def lint_wiki(self, kb_id):
            assert kb_id == "wiki-1"
            return {
                "issues": [
                    {
                        "id": "issue-a",
                        "type": "needs_review",
                        "page_id": "topic:alpha",
                        "repair_action": "ai_candidate",
                    }
                ]
            }

        async def repair_wiki(self, kb_id, issue_ids=None, issue_types=None, page_ids=None, force=False, context=None):
            await context.set_progress(20, "fake repair")
            calls.update(
                {
                    "kb_id": kb_id,
                    "issue_ids": issue_ids,
                    "issue_types": issue_types,
                    "page_ids": page_ids,
                    "force": force,
                    "context": context,
                }
            )
            return {"repaired_count": 1, "candidate_count": 1, "skipped_issues": [], "failed_issues": []}

    class FakeManager:
        backend = FakeBackend()

        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return self.backend

    def fake_create_task(coro):
        scheduled.append(coro)
        return SimpleNamespace()

    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(tmp_path))
    task_service.reset_task_registry_for_tests()
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())
    monkeypatch.setattr(knowledge.asyncio, "create_task", fake_create_task)

    try:
        result = await knowledge.repair_wiki(
            "wiki-1",
            {
                "issue_ids": ["issue-a"],
                "issue_types": ["needs_review"],
                "page_ids": ["topic:alpha"],
                "force": True,
            },
        )
        await scheduled.pop(0)
    finally:
        task_service.reset_task_registry_for_tests()

    assert result["status"] == "queued"
    assert result["task"]["kind"] == "wiki_repair"
    assert result["task"]["metadata"] == {
        "kb_id": "wiki-1",
        "issue_ids": ["issue-a"],
        "issue_types": ["needs_review"],
        "page_ids": ["topic:alpha"],
        "force": True,
    }
    assert calls["kb_id"] == "wiki-1"
    assert calls["issue_ids"] == ["issue-a"]
    assert calls["issue_types"] == ["needs_review"]
    assert calls["page_ids"] == ["topic:alpha"]
    assert calls["force"] is True
    assert calls["context"] is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_repair_route_returns_completed_when_no_ai_issues(monkeypatch, tmp_path):
    from nexagent.services import task_service

    class FakeBackend:
        def lint_wiki(self, kb_id):
            assert kb_id == "wiki-1"
            return {"issues": []}

    class FakeManager:
        backend = FakeBackend()

        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return self.backend

    monkeypatch.setenv("NEXAGENT_DATA_DIR", str(tmp_path))
    task_service.reset_task_registry_for_tests()
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    try:
        result = await knowledge.repair_wiki(
            "wiki-1",
            {
                "issue_ids": ["issue-a"],
                "issue_types": ["needs_review"],
                "page_ids": ["topic:alpha"],
                "force": True,
            },
        )
    finally:
        task_service.reset_task_registry_for_tests()

    assert result == {
        "status": "completed",
        "task_id": "",
        "task": None,
        "job": None,
        "queued": 0,
        "repaired_count": 0,
        "candidate_count": 0,
        "skipped_issues": [],
        "failed_issues": [],
        "completed": 0,
        "failed": 0,
        "items": [],
    }
