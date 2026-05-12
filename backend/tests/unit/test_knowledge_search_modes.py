from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


@pytest.mark.unit
def test_search_kwargs_do_not_duplicate_mode():
    from app.gateway.routers.knowledge import SearchRequest, _mode_for_request, _search_kwargs

    req = SearchRequest(query="rag", mode="hybrid", search_mode="keyword", bm25_weight=0.4)
    kwargs = _search_kwargs(req)

    assert "mode" not in kwargs
    assert "search_mode" not in kwargs
    assert kwargs["bm25_weight"] == 0.4
    assert kwargs["keyword_weight"] == 0.4
    assert _mode_for_request(req, "milvus") == "keyword"


@pytest.mark.unit
def test_search_mode_validation_rejects_wrong_backend_mode():
    from app.gateway.routers.knowledge import SearchRequest, _mode_for_request

    with pytest.raises(HTTPException) as exc:
        _mode_for_request(SearchRequest(query="rag", mode="lightrag_local"), "milvus")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        _mode_for_request(SearchRequest(query="rag", mode="keyword"), "lightrag")
    assert exc.value.status_code == 400


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_keyword_uses_degraded_local_fallback():
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB
    from nexagent.knowledge.models import KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    work_dir = Path("test-artifacts") / "milvus-keyword" / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    backend = MilvusKB(work_dir)
    backend._kbs[kb.kb_id] = kb
    backend._save_local_index(
        kb,
        {"chunks": [{"file_id": "f1", "filename": "doc.md", "chunk_index": 0, "content": "RAG retrieval alpha"}]},
    )

    results = await backend.search(kb.kb_id, "alpha", top_k=5, mode="keyword", bm25_top_k=5)

    assert results
    assert results[0].metadata["engine"] == "local_keyword_fallback"
    assert results[0].metadata["degraded"] is True
    assert results[0].metadata["degraded_reason"] in {"native_bm25_unavailable", "milvus_collection_missing"}
    assert results[0].metadata["action"] in {"reindex_recommended", "check_milvus"}
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_vector_missing_dependency_is_clear(monkeypatch):
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB, MilvusUnavailableError
    from nexagent.knowledge.models import KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    work_dir = Path("test-artifacts") / "milvus-missing" / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    backend = MilvusKB(work_dir)
    backend._kbs[kb.kb_id] = kb

    async def fake_milvus_search(*args, **kwargs):
        raise MilvusUnavailableError(
            "Milvus dependency missing: install backend product dependencies including pymilvus."
        )

    monkeypatch.setattr(backend, "_do_milvus_search", fake_milvus_search)

    with pytest.raises(MilvusUnavailableError, match="Milvus dependency missing"):
        await backend.search(kb.kb_id, "alpha", top_k=5, mode="vector")
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_collection_missing_uses_shadow_index(monkeypatch):
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB, MilvusUnavailableError
    from nexagent.knowledge.models import KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    work_dir = Path("test-artifacts") / "milvus-collection-fallback" / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    backend = MilvusKB(work_dir)
    backend._kbs[kb.kb_id] = kb
    backend._save_local_index(
        kb,
        {
            "chunks": [
                {
                    "file_id": "f1",
                    "filename": "doc.md",
                    "chunk_index": 0,
                    "content": "RAG retrieval alpha",
                    "tokens": ["rag", "retrieval", "alpha"],
                }
            ]
        },
    )

    async def fake_milvus_search(*args, **kwargs):
        raise MilvusUnavailableError(f"Milvus collection not found for KB {kb.kb_id}.")

    monkeypatch.setattr(backend, "_do_milvus_search", fake_milvus_search)

    results = await backend.search(kb.kb_id, "alpha", top_k=5, mode="vector")

    assert results
    assert results[0].metadata["engine"] == "local_vector_fallback"
    assert results[0].metadata["degraded"] is True
    assert results[0].metadata["degraded_reason"] == "milvus_collection_missing"
    assert results[0].metadata["action"] == "check_milvus"
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_degraded_index_clears_stale_reindex_flag(monkeypatch):
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB
    from nexagent.knowledge.models import FileMeta, FileStatus, KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    kb.extra["requires_reindex"] = True
    kb.extra["model_config"] = {"requires_reindex": True}
    work_dir = Path("test-artifacts") / "milvus-degraded-index" / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    backend = MilvusKB(work_dir)
    backend._kbs[kb.kb_id] = kb
    parsed_path = work_dir / "parsed.txt"
    parsed_path.write_text("Alpha retrieval uses local shadow when Milvus is down.", encoding="utf-8")
    file_meta = FileMeta(
        file_id="file-1",
        kb_id=kb.kb_id,
        filename="doc.txt",
        file_path=str(parsed_path),
        parsed_path=str(parsed_path),
        status=FileStatus.PARSED,
    )

    async def fail_insert(*args, **kwargs):
        raise RuntimeError("Milvus service unavailable")

    monkeypatch.setattr(backend, "_insert_milvus_chunks", fail_insert)

    count = await backend._do_index(kb, file_meta)

    assert count >= 1
    assert kb.extra["requires_reindex"] is False
    assert kb.extra["model_config"]["requires_reindex"] is False
    assert kb.extra["vector_index"]["status"] == "degraded"
    assert kb.extra["vector_index"]["needs_milvus_reindex"] is True
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_milvus_index_embeds_chunks_one_request_at_a_time(monkeypatch):
    from nexagent.knowledge.implementations import milvus_kb
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB
    from nexagent.knowledge.models import FileMeta, KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    work_dir = Path("test-artifacts") / "milvus-single-embedding" / str(uuid.uuid4())
    work_dir.mkdir(parents=True, exist_ok=True)
    backend = MilvusKB(work_dir)

    class Embed:
        def __init__(self):
            self.calls = []

        def embed_documents(self, texts):
            self.calls.append(list(texts))
            if len(texts) != 1:
                raise RuntimeError("provider batch token limit exceeded")
            return [[0.1] * 1024]

    class Collection:
        def load(self):
            pass

        def delete(self, expr):
            pass

        def insert(self, rows):
            self.rows = rows

        def flush(self):
            pass

    embed = Embed()
    monkeypatch.setattr(milvus_kb, "_build_embeddings", lambda info: embed)
    monkeypatch.setattr(backend, "_get_or_create_collection", lambda meta: Collection())
    chunks = [SimpleNamespace(content="alpha", source="doc.txt", chunk_index=0)]
    file_meta = FileMeta(file_id="file-1", kb_id=kb.kb_id, filename="doc.txt", file_path="doc.txt")

    await backend._insert_milvus_chunks(kb, file_meta, chunks)

    assert embed.calls == [["alpha"]]
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_milvus_schema_requires_native_bm25_support():
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB
    from pymilvus import DataType

    class Field:
        def __init__(self, name, dtype, params=None):
            self.name = name
            self.dtype = dtype
            self.params = params or {}

    class Schema:
        fields = [
            Field("content", DataType.VARCHAR, {"enable_analyzer": True}),
            Field("embedding", DataType.FLOAT_VECTOR, {"dim": 1024}),
        ]
        functions = []

    class Collection:
        schema = Schema()

    backend = MilvusKB(Path("test-artifacts") / "schema-check" / str(uuid.uuid4()))

    assert backend._collection_supports_schema(Collection(), 1024) is False
    shutil.rmtree(backend.work_dir, ignore_errors=True)


@pytest.mark.unit
def test_milvus_version_guard_flags_old_bm25_server():
    from nexagent.knowledge.implementations.milvus_kb import _milvus_version_is_unsupported

    assert _milvus_version_is_unsupported("v2.4.13") is True
    assert _milvus_version_is_unsupported("2.5.0") is False
    assert _milvus_version_is_unsupported("v2.6.12") is False


@pytest.mark.unit
def test_embedding_input_is_token_bounded():
    from nexagent.knowledge.implementations.milvus_kb import (
        EMBEDDING_MAX_CHARS,
        EMBEDDING_MAX_TOKENS,
        _embedding_safe_text,
    )

    text = " ".join(f"token{i}" for i in range(900))
    safe_text = _embedding_safe_text(text)

    import tiktoken

    assert len(safe_text) <= EMBEDDING_MAX_CHARS
    assert len(tiktoken.get_encoding("cl100k_base").encode(safe_text)) <= EMBEDDING_MAX_TOKENS


@pytest.mark.unit
def test_embedding_input_strips_mermaid_markup():
    from nexagent.knowledge.implementations.milvus_kb import _embedding_safe_text

    text = 'D@{ label: "<b>D. 耦合网络构建</b><br><span style=\\"font-size:12px;opacity:0.8\\">关键词</span>" }'
    safe_text = _embedding_safe_text(text)

    assert "<b>" not in safe_text
    assert "style" not in safe_text
    assert "耦合网络构建" in safe_text


@pytest.mark.unit
def test_embedding_token_limit_error_is_classified():
    from nexagent.knowledge.implementations.milvus_kb import _degraded_reason

    assert _degraded_reason(RuntimeError("input must have less than 512 tokens")) == "embedding_failed"


class _RouterFakeManager:
    def __init__(self, chunks: list[dict]):
        self._chunks = chunks

    def list_indexed_chunks(self, kb_id: str, limit: int = 1000) -> list[dict]:
        return self._chunks[:limit]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_search_collection_missing_returns_structured_error(monkeypatch):
    from nexagent.knowledge.retriever import HybridRetriever

    from app.gateway.routers import knowledge

    kb = SimpleNamespace(kb_type=SimpleNamespace(value="milvus"))
    mgr = _RouterFakeManager(
        [{"file_id": "f1", "filename": "doc.md", "chunk_index": 0, "content": "alpha beta retrieval"}]
    )
    monkeypatch.setattr(knowledge, "_kb_or_404", lambda kb_id: (mgr, kb))

    async def fake_retrieve(*args, **kwargs):
        raise RuntimeError("Milvus collection not found for KB kb-1.")

    monkeypatch.setattr(HybridRetriever, "retrieve", fake_retrieve)

    with pytest.raises(HTTPException) as exc:
        await knowledge.search("kb-1", knowledge.SearchRequest(query="alpha", top_k=5))

    assert exc.value.status_code == 409
    assert exc.value.detail["degraded"] is False
    assert exc.value.detail["error_code"] == "milvus_collection_missing"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_router_search_collection_missing_without_chunks_returns_409(monkeypatch):
    from nexagent.knowledge.retriever import HybridRetriever

    from app.gateway.routers import knowledge

    kb = SimpleNamespace(kb_type=SimpleNamespace(value="milvus"))
    mgr = _RouterFakeManager([])
    monkeypatch.setattr(knowledge, "_kb_or_404", lambda kb_id: (mgr, kb))

    async def fake_retrieve(*args, **kwargs):
        raise RuntimeError("Milvus collection not found for KB kb-1.")

    monkeypatch.setattr(HybridRetriever, "retrieve", fake_retrieve)

    with pytest.raises(HTTPException) as exc:
        await knowledge.search("kb-1", knowledge.SearchRequest(query="alpha", top_k=5))

    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "no_indexed_chunks"
