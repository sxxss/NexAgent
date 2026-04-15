"""Milvus vector/BM25 knowledge base backend with local shadow search."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from nexagent.knowledge.base import KnowledgeBase
from nexagent.knowledge.models import EmbedInfo, FileMeta, KBMeta, KBType, SearchResult

logger = logging.getLogger(__name__)

_COLL_PREFIX = "nexagent_"
CONTENT_SPARSE_FIELD = "content_sparse"
CONTENT_ANALYZER_PARAMS = {"type": "chinese"}
CONTENT_MAX_LENGTH = 65535
EMBEDDING_MAX_TOKENS = 256
EMBEDDING_MAX_CHARS = 180
MIN_BM25_SERVER_VERSION = (2, 5)


class MilvusUnavailableError(RuntimeError):
    """Raised when the product Milvus backend cannot be used."""


def _collection_name(kb_id: str) -> str:
    return _COLL_PREFIX + kb_id.replace("-", "_")


def _resolve_api_key(raw: str) -> str:
    if raw.startswith("$"):
        return os.environ.get(raw[1:], "")
    if not raw:
        return os.environ.get("SILICONFLOW_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    return raw


def _degraded_reason(exc: Exception) -> str:
    detail = str(exc).lower()
    if "server version" in detail or "does not support" in detail:
        return "native_bm25_unavailable"
    if "collection not found" in detail:
        return "milvus_collection_missing"
    if "schema" in detail or "bm25" in detail or CONTENT_SPARSE_FIELD in detail:
        return "native_bm25_unavailable"
    if "dependency missing" in detail or "pymilvus" in detail:
        return "milvus_dependency_missing"
    if (
        "embedding" in detail
        or "api key" in detail
        or "less than 512 tokens" in detail
        or "too many tokens" in detail
        or "maximum context length" in detail
    ):
        return "embedding_failed"
    if "service unavailable" in detail or "milvus" in detail:
        return "milvus_service_unavailable"
    return "milvus_unavailable"


def _parse_milvus_version(raw: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", raw or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _milvus_version_is_unsupported(raw: str) -> bool:
    version = _parse_milvus_version(raw)
    if version is None:
        return False
    return version[:2] < MIN_BM25_SERVER_VERSION


async def _in_executor(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


def _build_embeddings(embed_info: EmbedInfo):
    """Return an OpenAI-compatible LangChain embeddings client."""

    from langchain_openai import OpenAIEmbeddings

    api_key = _resolve_api_key(embed_info.api_key) or "sk-placeholder"
    model = embed_info.model.split("::", 1)[1] if "::" in embed_info.model else embed_info.model
    kwargs: dict[str, Any] = {"model": model, "api_key": api_key}
    if embed_info.base_url:
        kwargs["openai_api_base"] = embed_info.base_url
    return OpenAIEmbeddings(**kwargs)


def _embedding_safe_text(text: str, max_tokens: int = EMBEDDING_MAX_TOKENS) -> str:
    """Keep provider embedding input under common 512-token model limits."""

    raw = str(text or "")
    value = html.unescape(raw)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"style\\?=\\?\"[^\"\n]*\\?\"", " ", value)
    value = re.sub(r"[@#`*_~|{}\[\]()<>=:;\"'\\/]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        value = raw.strip()
    if not value:
        return " "
    value = value[:EMBEDDING_MAX_CHARS]
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        token_ids = encoding.encode(value)
        if len(token_ids) <= max_tokens:
            return value
        return encoding.decode(token_ids[:max_tokens]).strip() or value[:2048]
    except Exception:
        return value[: min(len(value), max_tokens * 4)]


class MilvusKB(KnowledgeBase):
    """Vector RAG using Milvus dense vectors plus native BM25 sparse vectors."""

    @property
    def kb_type(self) -> KBType:
        return KBType.MILVUS

    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        chunks = self._chunks_for_file(kb_meta, file_meta)
        self._save_shadow_chunks(kb_meta, file_meta, chunks)
        if os.environ.get("NEXAGENT_FORCE_LOCAL_KB_FALLBACK") == "1":
            kb_meta.extra["requires_reindex"] = False
            kb_meta.extra["vector_index"] = {
                "mode": "local_shadow",
                "status": "forced_local",
                "reason": "forced_local_fallback",
                "chunks": len(chunks),
                "path": str(self._local_index_path(kb_meta)),
                "needs_milvus_reindex": False,
            }
            _clear_reindex_flags(kb_meta)
            self._mark_local_index(kb_meta, chunks=len(chunks), status="forced_local")
            return len(chunks)
        try:
            await self._insert_milvus_chunks(kb_meta, file_meta, chunks)
            kb_meta.extra["requires_reindex"] = False
            kb_meta.extra["vector_index"] = {
                "mode": "milvus_dense_bm25",
                "status": "ok",
                "collection": _collection_name(kb_meta.kb_id),
                "chunks": len(chunks),
                "dimension": kb_meta.embed_info.dimension,
                "shadow_index": str(self._local_index_path(kb_meta)),
                "needs_milvus_reindex": False,
            }
            _clear_reindex_flags(kb_meta)
        except Exception as exc:
            if os.environ.get("NEXAGENT_REQUIRE_MILVUS_INDEX") == "1":
                raise
            reason = _degraded_reason(exc)
            logger.warning("Milvus index unavailable for KB %s; local shadow index is usable: %s", kb_meta.kb_id, exc)
            kb_meta.extra["requires_reindex"] = False
            kb_meta.extra["vector_index"] = {
                "mode": "local_shadow",
                "status": "degraded",
                "reason": reason,
                "detail": str(exc),
                "chunks": len(chunks),
                "path": str(self._local_index_path(kb_meta)),
                "needs_milvus_reindex": True,
            }
            _clear_reindex_flags(kb_meta)
        return len(chunks)

    async def _do_local_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        chunks = self._chunks_for_file(kb_meta, file_meta)
        self._save_shadow_chunks(kb_meta, file_meta, chunks)
        self._mark_local_index(kb_meta, chunks=len(chunks), status="local_only")
        return len(chunks)

    def _chunks_for_file(self, kb_meta: KBMeta, file_meta: FileMeta):
        from nexagent.knowledge.chunking import resolve_chunk_processing_params, split_text

        text = Path(file_meta.parsed_path).read_text(encoding="utf-8", errors="replace")
        params = file_meta.processing_params or resolve_chunk_processing_params(
            {
                "chunk_preset_id": kb_meta.chunk_preset_id,
                "chunk_parser_config": kb_meta.chunk_parser_config,
                "chunk_size": kb_meta.chunk_size,
                "chunk_overlap": kb_meta.chunk_overlap,
            }
        )
        chunks = split_text(
            text,
            chunk_size=_bounded_int(params.get("chunk_size"), kb_meta.chunk_size, 64, CONTENT_MAX_LENGTH),
            chunk_overlap=_bounded_int(params.get("chunk_overlap"), kb_meta.chunk_overlap, 0, CONTENT_MAX_LENGTH - 1),
            chunk_preset_id=str(params.get("chunk_preset_id") or kb_meta.chunk_preset_id),
            chunk_parser_config=dict(params.get("chunk_parser_config") or kb_meta.chunk_parser_config or {}),
            file_id=file_meta.file_id,
            filename=file_meta.filename,
        )
        logger.info(
            "Split file %s into %d chunks with preset=%s",
            file_meta.file_id,
            len(chunks),
            params.get("chunk_preset_id") or kb_meta.chunk_preset_id,
        )
        return chunks

    async def _insert_milvus_chunks(self, kb_meta: KBMeta, file_meta: FileMeta, chunks: list) -> None:
        if not chunks:
            return
        embed_fn = _build_embeddings(kb_meta.embed_info)
        texts = [_embedding_safe_text(chunk.content) for chunk in chunks]
        vectors: list[list[float]] = []
        for text in texts:
            vector = await _in_executor(embed_fn.embed_documents, [text])
            vectors.append(vector[0])
        collection = await _in_executor(self._get_or_create_collection, kb_meta)
        rows = [
            {
                "id": _chunk_id(chunk, file_meta.file_id, index),
                "content": chunk.content[:CONTENT_MAX_LENGTH],
                "source": chunk.source or file_meta.filename,
                "chunk_id": _chunk_id(chunk, file_meta.file_id, index),
                "file_id": file_meta.file_id,
                "filename": file_meta.filename,
                "chunk_index": int(chunk.chunk_index),
                "embedding": vectors[index],
            }
            for index, chunk in enumerate(chunks)
        ]

        def _insert() -> None:
            collection.load()
            self._delete_file_chunks_sync(collection, file_meta.file_id)
            collection.insert(rows)
            collection.flush()

        await _in_executor(_insert)

    async def _do_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        **kwargs,
    ) -> list[SearchResult]:
        mode = str(kwargs.get("search_mode") or kwargs.get("mode") or "vector").lower()
        if mode == "bm25":
            mode = "keyword"
        if mode not in {"vector", "keyword", "hybrid"}:
            raise ValueError(f"Unsupported Milvus search mode: {mode}")

        final_top_k = _bounded_int(kwargs.get("final_top_k"), top_k, 1, 100)
        recall_top_k = _bounded_int(kwargs.get("recall_top_k"), max(final_top_k, top_k), final_top_k, 200)
        bm25_top_k = _bounded_int(kwargs.get("bm25_top_k"), recall_top_k, 1, 200)
        threshold = _bounded_float(kwargs.get("similarity_threshold"), 0.0, 0.0, 1.0)

        if os.environ.get("NEXAGENT_FORCE_LOCAL_KB_FALLBACK") == "1":
            return self._require_local_fallback(
                query,
                kb_meta,
                top_k=final_top_k,
                reason="forced_local_fallback",
                engine=f"local_{mode}_fallback",
                similarity_threshold=threshold,
            )
        index_state = kb_meta.extra.get("vector_index") or {}
        if (
            isinstance(index_state, dict)
            and index_state.get("status") in {"degraded", "forced_local"}
            and self._load_local_index(kb_meta).get("chunks")
        ):
            return self._require_local_fallback(
                query,
                kb_meta,
                top_k=final_top_k,
                reason=str(index_state.get("reason") or "milvus_unavailable"),
                engine=f"local_{mode}_fallback",
                similarity_threshold=threshold,
            )

        try:
            if mode == "keyword":
                return await self._do_milvus_keyword_search(
                    query,
                    kb_meta,
                    top_k=min(final_top_k, bm25_top_k),
                    similarity_threshold=threshold,
                    bm25_drop_ratio_search=_bounded_float(
                        kwargs.get("bm25_drop_ratio_search"), 0.0, 0.0, 1.0
                    ),
                )
            if mode == "hybrid":
                return await self._do_milvus_hybrid_search(
                    query,
                    kb_meta,
                    top_k=final_top_k,
                    recall_top_k=recall_top_k,
                    bm25_top_k=bm25_top_k,
                    similarity_threshold=threshold,
                    vector_weight=_bounded_float(kwargs.get("vector_weight"), 0.7, 0.0, 1.0),
                    bm25_weight=_bounded_float(
                        kwargs.get("bm25_weight", kwargs.get("keyword_weight")), 0.3, 0.0, 1.0
                    ),
                    bm25_drop_ratio_search=_bounded_float(
                        kwargs.get("bm25_drop_ratio_search"), 0.0, 0.0, 1.0
                    ),
                )
            return (
                await self._do_milvus_search(
                    query,
                    kb_meta,
                    top_k=recall_top_k,
                    similarity_threshold=threshold,
                )
            )[:final_top_k]
        except Exception as exc:
            reason = _degraded_reason(exc)
            fallback = self._fallback_local_search(
                query,
                kb_meta,
                top_k=final_top_k,
                reason=reason,
                engine=f"local_{mode}_fallback",
                similarity_threshold=threshold,
            )
            if fallback is None:
                if isinstance(exc, MilvusUnavailableError):
                    raise
                raise MilvusUnavailableError(f"Milvus service unavailable: {exc}") from exc
            return fallback

    async def _do_milvus_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        **kwargs,
    ) -> list[SearchResult]:
        return await self._do_milvus_vector_search(query, kb_meta, top_k=top_k, **kwargs)

    async def _do_milvus_vector_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        *,
        similarity_threshold: float = 0.0,
        **_: Any,
    ) -> list[SearchResult]:
        embed_fn = _build_embeddings(kb_meta.embed_info)
        query_vector: list[float] = await _in_executor(embed_fn.embed_query, query)
        collection = await _in_executor(self._get_collection, kb_meta)
        if collection is None:
            raise MilvusUnavailableError(
                f"Milvus collection not found for KB {kb_meta.kb_id}. Re-index before vector search."
            )

        def _search():
            collection.load()
            return collection.search(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"nprobe": 16}},
                limit=top_k,
                output_fields=_output_fields(),
            )

        results = await _in_executor(_search)
        return self._hits_to_results(results, engine="milvus_vector", threshold=similarity_threshold)

    async def _do_milvus_keyword_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int,
        *,
        similarity_threshold: float,
        bm25_drop_ratio_search: float,
    ) -> list[SearchResult]:
        collection = await _in_executor(self._get_collection, kb_meta)
        if collection is None:
            raise MilvusUnavailableError(
                f"Milvus collection not found for KB {kb_meta.kb_id}. Re-index before BM25 search."
            )

        def _search():
            collection.load()
            return collection.search(
                data=[query],
                anns_field=CONTENT_SPARSE_FIELD,
                param={"metric_type": "BM25", "params": {"drop_ratio_search": bm25_drop_ratio_search}},
                limit=top_k,
                output_fields=_output_fields(),
            )

        results = await _in_executor(_search)
        return self._hits_to_results(
            results,
            engine="milvus_bm25",
            threshold=similarity_threshold,
            score_field="bm25_score",
        )

    async def _do_milvus_hybrid_search(
        self,
        query: str,
        kb_meta: KBMeta,
        *,
        top_k: int,
        recall_top_k: int,
        bm25_top_k: int,
        similarity_threshold: float,
        vector_weight: float,
        bm25_weight: float,
        bm25_drop_ratio_search: float,
    ) -> list[SearchResult]:
        try:
            from pymilvus import AnnSearchRequest, WeightedRanker
        except ImportError as exc:
            raise MilvusUnavailableError("Milvus dependency missing: pymilvus hybrid search is unavailable.") from exc

        embed_fn = _build_embeddings(kb_meta.embed_info)
        query_vector: list[float] = await _in_executor(embed_fn.embed_query, query)
        collection = await _in_executor(self._get_collection, kb_meta)
        if collection is None:
            raise MilvusUnavailableError(
                f"Milvus collection not found for KB {kb_meta.kb_id}. Re-index before hybrid search."
            )

        def _search():
            collection.load()
            vector_request = AnnSearchRequest(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"nprobe": 16}},
                limit=recall_top_k,
            )
            bm25_request = AnnSearchRequest(
                data=[query],
                anns_field=CONTENT_SPARSE_FIELD,
                param={"metric_type": "BM25", "params": {"drop_ratio_search": bm25_drop_ratio_search}},
                limit=bm25_top_k,
            )
            return collection.hybrid_search(
                reqs=[vector_request, bm25_request],
                rerank=WeightedRanker(vector_weight, bm25_weight),
                limit=top_k,
                output_fields=_output_fields(),
            )

        results = await _in_executor(_search)
        out = self._hits_to_results(
            results,
            engine="milvus_hybrid",
            threshold=similarity_threshold,
            score_field="hybrid_score",
        )
        for result in out:
            result.metadata["vector_weight"] = vector_weight
            result.metadata["bm25_weight"] = bm25_weight
            result.metadata["keyword_weight"] = bm25_weight
        return out

    def _hits_to_results(
        self,
        results,
        *,
        engine: str,
        threshold: float,
        score_field: str = "",
    ) -> list[SearchResult]:
        if not results or not results[0]:
            return []
        out: list[SearchResult] = []
        for hit in results[0]:
            entity = hit.entity
            score = float(getattr(hit, "score", getattr(hit, "distance", 0.0)) or 0.0)
            if score < threshold:
                continue
            metadata = {
                "chunk_id": _entity_get(entity, "chunk_id") or _entity_get(entity, "id"),
                "chunk_index": _entity_get(entity, "chunk_index") or 0,
                "source": _entity_get(entity, "source") or _entity_get(entity, "filename"),
                "engine": engine,
            }
            if score_field:
                metadata[score_field] = score
            out.append(
                SearchResult(
                    content=str(_entity_get(entity, "content") or ""),
                    score=score,
                    source=str(_entity_get(entity, "source") or _entity_get(entity, "filename") or ""),
                    file_id=str(_entity_get(entity, "file_id") or ""),
                    metadata=metadata,
                )
            )
        return out

    def _do_local_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        *,
        engine: str = "local_vector_fallback",
        degraded: bool = False,
        degraded_reason: str = "",
        similarity_threshold: float = 0.0,
    ) -> list[SearchResult]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        index = self._load_local_index(kb_meta)
        scored: list[tuple[float, dict]] = []
        for chunk in index.get("chunks", []):
            chunk_tokens = set(chunk.get("tokens", [])) or _tokenize(chunk.get("content", ""))
            score = _token_overlap_score(query_tokens, chunk_tokens, chunk.get("content", ""))
            if score > 0 and score >= similarity_threshold:
                scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchResult(
                content=str(chunk.get("content") or ""),
                score=round(score, 4),
                source=str(chunk.get("source") or chunk.get("filename") or ""),
                file_id=str(chunk.get("file_id") or ""),
                metadata={
                    "id": chunk.get("id") or chunk.get("chunk_id"),
                    "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "source": chunk.get("source") or chunk.get("filename") or "",
                    "engine": engine,
                    "degraded": degraded,
                    "degraded_reason": degraded_reason,
                    "degraded_message": _degraded_message(degraded_reason),
                    "action": _fallback_action(degraded_reason),
                },
            )
            for score, chunk in scored[:top_k]
        ]

    def _require_local_fallback(
        self,
        query: str,
        kb_meta: KBMeta,
        *,
        top_k: int,
        reason: str,
        engine: str,
        similarity_threshold: float,
    ) -> list[SearchResult]:
        fallback = self._fallback_local_search(
            query,
            kb_meta,
            top_k=top_k,
            reason=reason,
            engine=engine,
            similarity_threshold=similarity_threshold,
        )
        return fallback or []

    def _fallback_local_search(
        self,
        query: str,
        kb_meta: KBMeta,
        *,
        top_k: int,
        reason: str,
        engine: str,
        similarity_threshold: float = 0.0,
    ) -> list[SearchResult] | None:
        if not self._load_local_index(kb_meta).get("chunks"):
            self._rebuild_local_index_from_parsed(kb_meta)
        if not self._load_local_index(kb_meta).get("chunks"):
            return None
        logger.info("Using local shadow search for KB %s: %s", kb_meta.kb_id, reason)
        return self._do_local_search(
            query,
            kb_meta,
            top_k=top_k,
            engine=engine,
            degraded=True,
            degraded_reason=reason,
            similarity_threshold=similarity_threshold,
        )

    def _rebuild_local_index_from_parsed(self, kb_meta: KBMeta) -> int:
        from nexagent.knowledge.chunking import resolve_chunk_processing_params, split_text

        chunks: list[dict] = []
        for file_meta in self.list_files(kb_meta.kb_id):
            if not file_meta.parsed_path:
                continue
            parsed_path = Path(file_meta.parsed_path)
            if not parsed_path.exists():
                continue
            params = file_meta.processing_params or resolve_chunk_processing_params(
                {
                    "chunk_preset_id": kb_meta.chunk_preset_id,
                    "chunk_parser_config": kb_meta.chunk_parser_config,
                    "chunk_size": kb_meta.chunk_size,
                    "chunk_overlap": kb_meta.chunk_overlap,
                }
            )
            text = parsed_path.read_text(encoding="utf-8", errors="replace")
            parsed_chunks = split_text(
                text,
                chunk_size=int(params.get("chunk_size") or kb_meta.chunk_size),
                chunk_overlap=int(params.get("chunk_overlap") or kb_meta.chunk_overlap),
                chunk_preset_id=str(params.get("chunk_preset_id") or kb_meta.chunk_preset_id),
                chunk_parser_config=dict(params.get("chunk_parser_config") or kb_meta.chunk_parser_config or {}),
                file_id=file_meta.file_id,
                filename=file_meta.filename,
            )
            chunks.extend(self._shadow_rows(file_meta, parsed_chunks))
        if chunks:
            self._save_local_index(kb_meta, {"chunks": chunks})
            self._mark_local_index(kb_meta, chunks=len(chunks), status="rebuilt_from_parsed")
        return len(chunks)

    def list_indexed_chunks(self, kb_meta: KBMeta, limit: int = 1000) -> list[dict]:
        local_chunks = self._load_local_index(kb_meta).get("chunks", [])
        if not local_chunks:
            self._rebuild_local_index_from_parsed(kb_meta)
            local_chunks = self._load_local_index(kb_meta).get("chunks", [])
        if local_chunks:
            return [
                {
                    "id": _stored_chunk_id(chunk),
                    "chunk_id": _stored_chunk_id(chunk),
                    "content": chunk.get("content", ""),
                    "file_id": chunk.get("file_id", ""),
                    "filename": chunk.get("filename", ""),
                    "source": "local_index",
                    "chunk_index": chunk.get("chunk_index", 0),
                    "metadata": {"source": chunk.get("source") or chunk.get("filename") or ""},
                }
                for chunk in local_chunks[:limit]
                if chunk.get("content")
            ]
        collection = self._get_collection(kb_meta)
        if collection is None:
            return []
        try:
            collection.load()
            rows = collection.query(expr="", output_fields=_output_fields(), limit=limit)
        except Exception as exc:
            logger.info("Could not load indexed chunks from Milvus for %s: %s", kb_meta.kb_id, exc)
            return []
        return [
            {
                "id": row.get("chunk_id") or row.get("id") or f"{row.get('file_id')}:{row.get('chunk_index')}",
                "chunk_id": row.get("chunk_id") or row.get("id") or f"{row.get('file_id')}:{row.get('chunk_index')}",
                "content": row.get("content", ""),
                "file_id": row.get("file_id", ""),
                "filename": row.get("filename", ""),
                "source": "milvus",
                "chunk_index": row.get("chunk_index", 0),
                "metadata": {"source": row.get("source") or row.get("filename") or ""},
            }
            for row in rows[:limit]
            if row.get("content")
        ]

    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        def _drop():
            from pymilvus import utility

            self._connect()
            col_name = _collection_name(kb_meta.kb_id)
            if utility.has_collection(col_name):
                utility.drop_collection(col_name)
                logger.info("Dropped Milvus collection %s", col_name)

        await _in_executor(_drop)
        local_index = self._local_index_path(kb_meta)
        if local_index.exists():
            local_index.unlink()

    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        def _delete():
            col = self._get_collection(kb_meta)
            if col is None:
                return
            self._delete_file_chunks_sync(col, file_meta.file_id)
            col.flush()

        try:
            await _in_executor(_delete)
        except Exception as exc:
            logger.info("Milvus file delete skipped for %s: %s", file_meta.file_id, exc)
        index = self._load_local_index(kb_meta)
        index["chunks"] = [chunk for chunk in index.get("chunks", []) if chunk.get("file_id") != file_meta.file_id]
        self._save_local_index(kb_meta, index)

    def _connect(self) -> None:
        try:
            from pymilvus import connections
        except ImportError as exc:
            raise MilvusUnavailableError(
                "Milvus dependency missing: install backend product dependencies including pymilvus."
            ) from exc
        try:
            from nexagent.config import get_config

            kb_cfg = get_config().knowledge
            host = kb_cfg.milvus_host
            port = kb_cfg.milvus_port
        except Exception:
            host, port = "localhost", 19530
        try:
            connections.connect("default", host=host, port=port)
        except Exception as exc:
            raise MilvusUnavailableError(f"Milvus service unavailable: {exc}") from exc

    def _server_version(self, utility_module=None) -> str:
        try:
            if utility_module is None:
                from pymilvus import utility as utility_module

            return str(utility_module.get_server_version())
        except Exception:
            return ""

    def _assert_server_supports_bm25(self, utility_module=None) -> None:
        version = self._server_version(utility_module)
        if _milvus_version_is_unsupported(version):
            raise MilvusUnavailableError(
                f"Milvus server version {version} does not support NexAgent dense+BM25 schema; "
                "use Milvus >=2.5 or the docker-compose default milvusdb/milvus:v2.6.12."
            )

    def _get_or_create_collection(self, kb_meta: KBMeta):
        try:
            from pymilvus import Collection, utility
        except ImportError as exc:
            raise MilvusUnavailableError(
                "Milvus dependency missing: install backend product dependencies including pymilvus."
            ) from exc

        self._connect()
        self._assert_server_supports_bm25(utility)
        col_name = _collection_name(kb_meta.kb_id)
        if utility.has_collection(col_name):
            collection = Collection(col_name)
            if self._collection_supports_schema(collection, kb_meta.embed_info.dimension):
                return collection
            if os.environ.get("NEXAGENT_RECREATE_MILVUS_ON_SCHEMA_MISMATCH") == "1":
                utility.drop_collection(col_name)
                return self._create_collection(col_name, kb_meta)
            raise MilvusUnavailableError(
                f"Milvus collection schema mismatch for KB {kb_meta.kb_id}; re-index with BM25 schema."
            )
        return self._create_collection(col_name, kb_meta)

    def _create_collection(self, collection_name: str, kb_meta: KBMeta):
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, Function, FunctionType

        fields = [
            FieldSchema("id", DataType.VARCHAR, max_length=128, is_primary=True),
            FieldSchema(
                "content",
                DataType.VARCHAR,
                max_length=CONTENT_MAX_LENGTH,
                enable_analyzer=True,
                analyzer_params=CONTENT_ANALYZER_PARAMS,
            ),
            FieldSchema("source", DataType.VARCHAR, max_length=512),
            FieldSchema("chunk_id", DataType.VARCHAR, max_length=128),
            FieldSchema("file_id", DataType.VARCHAR, max_length=128),
            FieldSchema("filename", DataType.VARCHAR, max_length=512),
            FieldSchema("chunk_index", DataType.INT64),
            FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=kb_meta.embed_info.dimension),
            FieldSchema(CONTENT_SPARSE_FIELD, DataType.SPARSE_FLOAT_VECTOR),
        ]
        bm25_function = Function(
            name="content_bm25",
            input_field_names=["content"],
            output_field_names=[CONTENT_SPARSE_FIELD],
            function_type=FunctionType.BM25,
        )
        schema = CollectionSchema(
            fields,
            description=f"Knowledge base collection for {kb_meta.kb_id} using {kb_meta.embed_info.model}",
            functions=[bm25_function],
        )
        collection = Collection(collection_name, schema)
        collection.create_index(
            "embedding",
            {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
        )
        collection.create_index(
            CONTENT_SPARSE_FIELD,
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE"},
            },
        )
        logger.info("Created Milvus dense+BM25 collection %s", collection_name)
        return collection

    def _collection_supports_schema(self, collection, dim: int) -> bool:
        try:
            from pymilvus import DataType, FunctionType
        except ImportError:
            return False
        fields = {field.name: field for field in collection.schema.fields}
        content_field = fields.get("content")
        sparse_field = fields.get(CONTENT_SPARSE_FIELD)
        embedding_field = fields.get("embedding")
        if not content_field or content_field.dtype != DataType.VARCHAR:
            return False
        if not sparse_field or sparse_field.dtype != DataType.SPARSE_FLOAT_VECTOR:
            return False
        if not embedding_field or embedding_field.dtype != DataType.FLOAT_VECTOR:
            return False
        if int((getattr(embedding_field, "params", {}) or {}).get("dim") or dim) != int(dim):
            return False
        if (getattr(content_field, "params", {}) or {}).get("enable_analyzer") is not True:
            return False
        for function in getattr(collection.schema, "functions", []) or []:
            function_type = getattr(function, "type", None) or getattr(function, "function_type", None)
            if (
                function_type == FunctionType.BM25
                and list(getattr(function, "input_field_names", [])) == ["content"]
                and list(getattr(function, "output_field_names", [])) == [CONTENT_SPARSE_FIELD]
            ):
                return True
        return False

    def _get_collection(self, kb_meta: KBMeta):
        try:
            from pymilvus import Collection, utility
        except ImportError as exc:
            raise MilvusUnavailableError(
                "Milvus dependency missing: install backend product dependencies including pymilvus."
            ) from exc
        self._connect()
        col_name = _collection_name(kb_meta.kb_id)
        if utility.has_collection(col_name):
            return Collection(col_name)
        return None

    def _delete_file_chunks_sync(self, collection, file_id: str) -> None:
        safe_file_id = file_id.replace("\\", "\\\\").replace('"', '\\"')
        try:
            collection.delete(expr=f'file_id == "{safe_file_id}"')
        except Exception as exc:
            logger.debug("Ignoring Milvus chunk delete failure for %s: %s", file_id, exc)

    def status(self) -> dict:
        try:
            from pymilvus import utility

            self._connect()
            server_version = self._server_version(utility)
            collections = utility.list_collections()
            if _milvus_version_is_unsupported(server_version):
                return {
                    "status": "degraded",
                    "mode": "local_shadow",
                    "error_code": "milvus_version_unsupported",
                    "server_version": server_version,
                    "reason": (
                        f"Milvus server version {server_version} is too old for dense+BM25 schema; "
                        "use Milvus >=2.5 or the docker-compose default milvusdb/milvus:v2.6.12."
                    ),
                    "work_dir": str(self.work_dir),
                }
            return {
                "status": "ok",
                "mode": "milvus_dense_bm25_with_local_shadow",
                "server_version": server_version,
                "collections": len(collections),
                "work_dir": str(self.work_dir),
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "mode": "local_shadow",
                "reason": str(exc),
                "work_dir": str(self.work_dir),
            }

    def _local_index_path(self, kb_meta: KBMeta) -> Path:
        path = Path(self.work_dir) / kb_meta.kb_id / "local_vector"
        path.mkdir(parents=True, exist_ok=True)
        return path / "index.json"

    def _load_local_index(self, kb_meta: KBMeta) -> dict:
        path = self._local_index_path(kb_meta)
        if not path.exists():
            return {"chunks": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"chunks": []}

    def _save_local_index(self, kb_meta: KBMeta, index: dict) -> None:
        path = self._local_index_path(kb_meta)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _save_shadow_chunks(self, kb_meta: KBMeta, file_meta: FileMeta, chunks: list) -> None:
        index = self._load_local_index(kb_meta)
        index["chunks"] = [chunk for chunk in index.get("chunks", []) if chunk.get("file_id") != file_meta.file_id]
        index["chunks"].extend(self._shadow_rows(file_meta, chunks))
        self._save_local_index(kb_meta, index)
        self._mark_local_index(kb_meta, chunks=len(index["chunks"]), status="shadow_ready")

    def _shadow_rows(self, file_meta: FileMeta, chunks: list) -> list[dict]:
        return [
            {
                "id": _chunk_id(chunk, file_meta.file_id, index),
                "chunk_id": _chunk_id(chunk, file_meta.file_id, index),
                "file_id": file_meta.file_id,
                "filename": file_meta.filename,
                "source": chunk.source or file_meta.filename,
                "chunk_index": int(chunk.chunk_index),
                "content": chunk.content,
                "tokens": sorted(_tokenize(chunk.content)),
            }
            for index, chunk in enumerate(chunks)
        ]

    def _mark_local_index(self, kb_meta: KBMeta, *, chunks: int, status: str) -> None:
        kb_meta.extra["local_shadow_index"] = {
            "status": status,
            "chunks": chunks,
            "path": str(self._local_index_path(kb_meta)),
        }

    def _normalize_kb_runtime_flags(self, kb_meta: KBMeta) -> bool:
        vector_index = kb_meta.extra.get("vector_index") or {}
        if not isinstance(vector_index, dict):
            return False
        if vector_index.get("status") not in {"degraded", "forced_local"}:
            return False
        if not self._load_local_index(kb_meta).get("chunks"):
            return False
        changed = False
        if kb_meta.extra.get("requires_reindex"):
            kb_meta.extra["requires_reindex"] = False
            changed = True
        if vector_index.get("needs_milvus_reindex") is not True and vector_index.get("status") == "degraded":
            vector_index["needs_milvus_reindex"] = True
            kb_meta.extra["vector_index"] = vector_index
            changed = True
        return changed


def _output_fields() -> list[str]:
    return ["id", "content", "source", "chunk_id", "file_id", "filename", "chunk_index"]


def _entity_get(entity, key: str):
    try:
        return entity.get(key)
    except Exception:
        try:
            return getattr(entity, key)
        except Exception:
            return None


def _chunk_id(chunk, file_id: str, index: int) -> str:
    return str(
        getattr(chunk, "chunk_id", "")
        or (getattr(chunk, "metadata", {}) or {}).get("chunk_id")
        or f"{file_id}_chunk_{index}"
    )


def _stored_chunk_id(record: dict) -> str:
    return str(
        record.get("chunk_id")
        or record.get("id")
        or f"{record.get('file_id')}:{record.get('chunk_index')}"
    )


def _clear_reindex_flags(kb_meta: KBMeta) -> None:
    for key in ("model_config", "chunk_config"):
        value = kb_meta.extra.get(key)
        if isinstance(value, dict):
            value["requires_reindex"] = False


def _fallback_action(reason: str) -> str:
    if reason == "native_bm25_unavailable":
        return "reindex_recommended"
    if reason == "embedding_failed":
        return "check_embedding"
    if reason in {
        "milvus_collection_missing",
        "milvus_dependency_missing",
        "milvus_service_unavailable",
        "milvus_unavailable",
    }:
        return "check_milvus"
    return ""


def _degraded_message(reason: str) -> str:
    return {
        "forced_local_fallback": "Retrieval is using the configured local shadow index.",
        "milvus_collection_missing": (
            "Milvus has no collection for this knowledge base; the local shadow index is being used."
        ),
        "milvus_dependency_missing": "Milvus dependencies are missing; the local shadow index is being used.",
        "milvus_service_unavailable": "Milvus is unavailable; the local shadow index is being used.",
        "milvus_unavailable": "Milvus is unavailable; the local shadow index is being used.",
        "embedding_failed": "Embedding failed during indexing; lexical local retrieval is being used.",
        "native_bm25_unavailable": "Native BM25 is unavailable; lexical local retrieval is being used.",
    }.get(reason, "Retrieval used a degraded local fallback.")


def _tokenize(text: str) -> set[str]:
    tokens = {
        token.lower()
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,}", text or "")
        if len(token.strip("_-")) >= 2
    }
    if tokens:
        return tokens
    return {char for char in text.lower() if char.strip()}


def _token_overlap_score(query_tokens: set[str], chunk_tokens: set[str], content: str) -> float:
    overlap = query_tokens & chunk_tokens
    score = len(overlap) / max(len(query_tokens), 1)
    lowered = (content or "").lower()
    for token in query_tokens:
        if token in lowered:
            score += 0.15
    return min(score, 1.0)


def _bounded_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))


def _bounded_float(value, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(parsed, max_value))
