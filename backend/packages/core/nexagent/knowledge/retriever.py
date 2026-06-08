"""Hybrid retrieval facade over vector and graph knowledge bases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from nexagent.knowledge.graph_store import extract_entities
from nexagent.knowledge.models import SearchResult

RetrievalMode = Literal[
    "vector",
    "keyword",
    "hybrid",
    "lightrag_local",
    "lightrag_global",
    "lightrag_hybrid",
    "wiki",
]


@dataclass
class RetrievedChunk:
    content: str
    score: float
    kb_id: str
    source: str = ""
    file_id: str = ""
    metadata: dict = field(default_factory=dict)

    def evidence(self, index: int) -> dict:
        return {
            "id": f"E{index}",
            "kb_id": self.kb_id,
            "file_id": self.file_id,
            "source": self.source,
            "score": round(self.score, 6),
            "metadata": self.metadata,
            "preview": self.content[:240],
        }


class HybridRetriever:
    """Retrieve from one or more KBs and merge results with deduplication."""

    async def retrieve(
        self,
        query: str,
        kb_ids: list[str],
        mode: RetrievalMode = "hybrid",
        top_k: int = 10,
        **kwargs: Any,
    ) -> list[RetrievedChunk]:
        from nexagent.knowledge.manager import get_manager

        manager = get_manager()
        from nexagent.config import get_config

        cfg = get_config().knowledge
        candidates: list[RetrievedChunk] = []
        final_top_k = _positive_int(kwargs.get("final_top_k"), top_k)
        recall_top_k = _positive_int(kwargs.get("recall_top_k"), final_top_k * max(cfg.rerank_top_k_multiplier, 1))
        per_k = max(recall_top_k, final_top_k)
        mode = _normalize_mode(mode)
        search_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key
            in {
                "final_top_k",
                "recall_top_k",
                "similarity_threshold",
                "vector_weight",
                "keyword_weight",
                "bm25_weight",
                "bm25_top_k",
                "bm25_drop_ratio_search",
                "use_reranker",
                "reranker_model",
            }
        }

        for kb_id in kb_ids:
            try:
                get_kb = getattr(manager, "get_kb", None)
                kb = get_kb(kb_id) if callable(get_kb) else None
                kb_type = kb.kb_type.value if kb else "milvus"
                mode_for_kb = _mode_for_kb(mode, kb_type)
                results = await manager.search(
                    kb_id,
                    query,
                    top_k=per_k,
                    mode=_backend_mode(mode_for_kb),
                    **search_kwargs,
                )
            except TypeError:
                results = await manager.search(kb_id, query, top_k=per_k)
            candidates.extend(_convert(kb_id, results))

        if mode in {"lightrag_local", "lightrag_global", "lightrag_hybrid"}:
            candidates.extend(await self._expand_graph_context(query, kb_ids, top_k=per_k))

        deduped = _dedupe(candidates)
        should_rerank = bool(kwargs.get("use_reranker", True))
        model_name = str(kwargs.get("reranker_model") or cfg.rerank_model or "")
        reranked = _rerank(query, deduped, model_name=model_name) if should_rerank else deduped
        return reranked[:final_top_k]

    async def _expand_graph_context(self, query: str, kb_ids: list[str], top_k: int) -> list[RetrievedChunk]:
        from nexagent.knowledge.manager import get_manager
        from nexagent.knowledge.models import KBType

        manager = get_manager()
        entities = extract_entities(query)
        graph_queries = [query, *entities[:5]]
        chunks: list[RetrievedChunk] = []
        for kb_id in kb_ids:
            get_kb = getattr(manager, "get_kb", None)
            if not callable(get_kb):
                continue
            kb = get_kb(kb_id)
            if kb is None or kb.kb_type != KBType.LIGHTRAG:
                continue
            for graph_query in dict.fromkeys(graph_queries):
                try:
                    results = await manager.search(kb_id, graph_query, top_k=max(1, top_k // 2), mode="hybrid")
                except Exception:
                    continue
                for chunk in _convert(kb_id, results):
                    chunk.metadata = {**chunk.metadata, "graph_expansion_query": graph_query}
                    chunks.append(chunk)
        return chunks


def _convert(kb_id: str, results: list[SearchResult]) -> list[RetrievedChunk]:
    converted: list[RetrievedChunk] = []
    for index, result in enumerate(results, 1):
        metadata = dict(result.metadata or {})
        metadata.setdefault("retrieval_rank", index)
        metadata.setdefault("file_id", result.file_id)
        if result.source:
            metadata.setdefault("source", result.source)
        if "chunk_id" not in metadata:
            metadata["chunk_id"] = metadata.get("id") or ""
        converted.append(
            RetrievedChunk(
                content=result.content,
                score=result.score,
                kb_id=kb_id,
                source=result.source,
                file_id=result.file_id,
                metadata=metadata,
            )
        )
    return converted


def _dedupe(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        key = " ".join(chunk.content.lower().split())[:500]
        if key not in seen or chunk.score > seen[key].score:
            seen[key] = chunk
    return list(seen.values())


def _rerank(query: str, chunks: list[RetrievedChunk], model_name: str = "") -> list[RetrievedChunk]:
    """Cheap lexical rerank layer used when no cross-encoder is configured."""
    cross_scores = _cross_encoder_scores(model_name, query, chunks) if model_name else None
    query_terms = _terms(query)
    for index, chunk in enumerate(chunks):
        content_terms = _terms(chunk.content)
        lexical = len(query_terms & content_terms) / max(len(query_terms), 1)
        exact = 0.2 if query.strip().lower() and query.strip().lower() in chunk.content.lower() else 0.0
        cross = cross_scores[index] if cross_scores is not None and index < len(cross_scores) else None
        if cross is None:
            chunk.score = round((chunk.score * 0.75) + (lexical * 0.2) + exact, 6)
        else:
            chunk.score = round((chunk.score * 0.35) + (cross * 0.55) + (lexical * 0.1), 6)
        chunk.metadata = {
            **chunk.metadata,
            "rerank": {"lexical_overlap": lexical, "exact_query_bonus": exact, "cross_encoder_score": cross},
        }
    return sorted(chunks, key=lambda item: item.score, reverse=True)


def _cross_encoder_scores(model_name: str, query: str, chunks: list[RetrievedChunk]) -> list[float] | None:
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except ImportError:
        return None
    try:
        model = CrossEncoder(model_name)
        raw = model.predict([(query, chunk.content) for chunk in chunks])
        values = [float(item) for item in raw]
        if not values:
            return []
        min_v, max_v = min(values), max(values)
        if max_v == min_v:
            return [0.5 for _ in values]
        return [(value - min_v) / (max_v - min_v) for value in values]
    except Exception:
        return None


def _terms(text: str) -> set[str]:
    import re

    return {
        token.lower()
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,}", text)
        if len(token.strip("_-")) >= 2
    }


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1)


def _normalize_mode(mode: str) -> RetrievalMode:
    normalized = str(mode or "hybrid").lower()
    if normalized == "bm25":
        normalized = "keyword"
    if normalized in {
        "vector",
        "keyword",
        "hybrid",
        "lightrag_local",
        "lightrag_global",
        "lightrag_hybrid",
        "wiki",
    }:
        return normalized  # type: ignore[return-value]
    raise ValueError(
        "Unsupported search mode "
        f"'{mode}'. Available modes: vector, keyword, hybrid, "
        "lightrag_local, lightrag_global, lightrag_hybrid, wiki."
    )


def _mode_for_kb(mode: RetrievalMode, kb_type: str) -> RetrievalMode:
    if kb_type == "wiki":
        return "wiki"
    if kb_type == "lightrag":
        if mode in {"lightrag_local", "lightrag_global", "lightrag_hybrid"}:
            return mode
        return "lightrag_hybrid"
    if mode in {"vector", "keyword", "hybrid"}:
        return mode
    return "hybrid"


def _backend_mode(mode: RetrievalMode) -> str:
    if mode == "wiki":
        return "wiki"
    if mode == "lightrag_local":
        return "local"
    if mode == "lightrag_global":
        return "global"
    if mode == "lightrag_hybrid":
        return "hybrid"
    return mode
