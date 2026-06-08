from __future__ import annotations

import pytest


@pytest.mark.unit
def test_file_meta_progress_is_exposed_in_dict():
    from nexagent.knowledge.models import FileMeta, FileStatus

    meta = FileMeta(
        file_id="file-a",
        kb_id="kb-a",
        filename="doc.md",
        file_path="/tmp/doc.md",
        status=FileStatus.PARSED,
        parse_metadata={"parser": "fallback", "content_chars": 128},
    )

    payload = meta.to_dict()

    assert payload["parse_metadata"]["parser"] == "fallback"
    assert payload["progress"]["percent"] == 60
    assert payload["progress"]["can_index"] is True
    assert payload["progress"]["can_process"] is False


@pytest.mark.unit
def test_kb_meta_public_dict_redacts_api_keys():
    from nexagent.knowledge.models import EmbedInfo, KBMeta, KBType, LLMInfo

    meta = KBMeta(
        kb_id="kb-a",
        name="kb",
        kb_type=KBType.WIKI,
        embed_info=EmbedInfo(api_key="secret-embed"),
        llm_info=LLMInfo(api_key="secret-llm"),
    )

    payload = meta.to_dict(include_secrets=False)

    assert "api_key" not in payload["embed_info"]
    assert "api_key" not in payload["llm_info"]
    assert meta.to_dict()["embed_info"]["api_key"] == "secret-embed"


@pytest.mark.unit
def test_search_result_payload_includes_evidence():
    from app.gateway.routers.knowledge import _search_result_payload

    class Result:
        content = "hello world"
        score = 0.91
        source = "doc.md"
        file_id = "file-a"
        metadata = {"source": "doc.md"}

        def evidence(self, index: int) -> dict:
            return {"id": f"E{index}", "source": self.source, "score": self.score, "metadata": self.metadata}

        def to_dict(self) -> dict:
            return {
                "content": self.content,
                "score": self.score,
                "source": self.source,
                "file_id": self.file_id,
                "metadata": self.metadata,
            }

    payload = _search_result_payload(Result(), 2)

    assert payload["evidence"]["id"] == "E2"
    assert payload["source"] == "doc.md"


@pytest.mark.unit
def test_production_service_uses_singleton_and_lazy_object_store(monkeypatch):
    from nexagent.knowledge import production_service

    calls = {"count": 0}

    class FakeObjectStore:
        pass

    def fake_get_object_store():
        calls["count"] += 1
        return FakeObjectStore()

    monkeypatch.setattr(production_service, "_PRODUCTION_SERVICE", None, raising=False)
    monkeypatch.setattr(production_service, "get_object_store", fake_get_object_store)

    service_a = production_service.get_production_service()
    service_b = production_service.get_production_service()

    assert service_a is service_b
    assert calls["count"] == 0
    assert service_a.object_store is service_a.object_store
    assert calls["count"] == 1
