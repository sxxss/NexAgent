"""Structured knowledge search helpers shared by API routes and eval runs."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from nexagent.knowledge.retriever import HybridRetriever, RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchWarning:
    code: str
    message: str
    action: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "action": self.action}


@dataclass
class StructuredSearchResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    warnings: list[SearchWarning] = field(default_factory=list)
    error_code: str = ""
    error: str = ""
    degraded: bool = False

    def warning_dicts(self) -> list[dict[str, str]]:
        return [warning.to_dict() for warning in self.warnings]


async def structured_retrieve(
    *,
    query: str,
    kb_ids: list[str],
    mode: str = "hybrid",
    top_k: int = 10,
    timeout_s: float | None = 60,
    **kwargs: Any,
) -> StructuredSearchResult:
    """Retrieve per KB and return failures as data instead of exceptions."""

    chunks: list[RetrievedChunk] = []
    warnings: list[SearchWarning] = []
    errors: list[SearchWarning] = []
    prod_handled: set[str] = set()
    prod_ids: list[str] = []
    try:
        from nexagent.knowledge.production_service import get_production_service, production_enabled

        if production_enabled():
            prod = get_production_service()
            if kb_ids:
                for kb_id in kb_ids:
                    if await prod.get_kb(kb_id):
                        prod_ids.append(kb_id)
            else:
                prod_ids = [kb.kb_id for kb in await prod.list_kbs()]
            for kb_id in prod_ids:
                prod_handled.add(kb_id)
                try:
                    kb_results = await asyncio.wait_for(
                        prod.search(kb_id=kb_id, query=query, top_k=top_k, mode=mode, **kwargs),
                        timeout=timeout_s,
                    ) if timeout_s else await prod.search(kb_id=kb_id, query=query, top_k=top_k, mode=mode, **kwargs)
                    kb_chunks = [_search_result_to_chunk(item, kb_id) for item in kb_results]
                    chunks.extend(kb_chunks)
                    warnings.extend(_warnings_from_chunks(kb_chunks))
                except Exception as exc:
                    code = classify_search_error(str(exc))
                    warning = SearchWarning(code=code, message=str(exc), action=action_for_error(code))
                    errors.append(warning)
                    logger.info("Production knowledge search failed for KB %s: %s", kb_id, exc)
    except Exception as exc:
        logger.info("Production knowledge search path unavailable: %s", exc)

    retriever = HybridRetriever()
    legacy_ids = [kb_id for kb_id in kb_ids if kb_id not in prod_handled]
    if not kb_ids and not prod_handled:
        legacy_ids = []
    for kb_id in legacy_ids:
        try:
            call = retriever.retrieve(query=query, kb_ids=[kb_id], mode=mode, top_k=top_k, **kwargs)
            kb_chunks = await asyncio.wait_for(call, timeout=timeout_s) if timeout_s else await call
            chunks.extend(kb_chunks)
            warnings.extend(_warnings_from_chunks(kb_chunks))
        except Exception as exc:  # keep eval/search streams alive
            code = classify_search_error(str(exc))
            warning = SearchWarning(code=code, message=str(exc), action=action_for_error(code))
            errors.append(warning)
            logger.info("Knowledge search failed for KB %s: %s", kb_id, exc)

    chunks = sorted(_dedupe_chunks(chunks), key=lambda item: getattr(item, "score", 0.0), reverse=True)[:top_k]
    all_warnings = _dedupe_warnings([*warnings, *errors])
    hard_error = errors[0] if errors and not chunks else None
    return StructuredSearchResult(
        chunks=chunks,
        warnings=all_warnings,
        error_code=hard_error.code if hard_error else "",
        error=hard_error.message if hard_error else "",
        degraded=bool(all_warnings),
    )


def _search_result_to_chunk(result: Any, kb_id: str) -> RetrievedChunk:
    metadata = dict(getattr(result, "metadata", {}) or {})
    return RetrievedChunk(
        content=str(getattr(result, "content", "") or ""),
        score=float(getattr(result, "score", 0.0) or 0.0),
        kb_id=kb_id,
        source=str(getattr(result, "source", "") or metadata.get("source") or ""),
        file_id=str(getattr(result, "file_id", "") or metadata.get("file_id") or ""),
        metadata=metadata,
    )


def classify_search_error(detail: str) -> str:
    lowered = detail.lower()
    if "unsupported search mode" in lowered:
        return "invalid_search_mode"
    if "collection not found" in lowered:
        return "milvus_collection_missing"
    if "schema" in lowered or "bm25" in lowered or "content_sparse" in lowered:
        return "native_bm25_unavailable"
    if "pymilvus" in lowered or "dependency missing" in lowered:
        return "milvus_dependency_missing"
    if "embedding" in lowered or "api key" in lowered:
        return "embedding_failed"
    if "timeout" in lowered:
        return "search_timeout"
    if "milvus" in lowered or "service unavailable" in lowered:
        return "milvus_service_unavailable"
    return "search_failed"


def action_for_error(code: str) -> str:
    return {
        "milvus_collection_missing": "check_milvus",
        "milvus_dependency_missing": "install_dependency",
        "milvus_service_unavailable": "check_milvus",
        "embedding_failed": "check_embedding",
        "search_timeout": "retry",
        "native_bm25_unavailable": "reindex",
        "invalid_search_mode": "choose_supported_mode",
    }.get(code, "")


def _warnings_from_chunks(chunks: list[RetrievedChunk]) -> list[SearchWarning]:
    warnings: list[SearchWarning] = []
    for chunk in chunks:
        metadata = getattr(chunk, "metadata", {}) or {}
        if not metadata.get("degraded"):
            continue
        reason = str(metadata.get("degraded_reason") or "degraded_search")
        warnings.append(
            SearchWarning(
                code=reason,
                message=str(metadata.get("degraded_message") or "Retrieval used a degraded local fallback."),
                action=str(metadata.get("action") or action_for_error(reason)),
            )
        )
    return warnings


def _dedupe_warnings(warnings: list[SearchWarning]) -> list[SearchWarning]:
    seen: set[tuple[str, str]] = set()
    out: list[SearchWarning] = []
    for warning in warnings:
        key = (warning.code, warning.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(warning)
    return out


def _dedupe_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    seen: dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        metadata = getattr(chunk, "metadata", {}) or {}
        key = str(
            metadata.get("chunk_id")
            or metadata.get("id")
            or (
                f"{getattr(chunk, 'kb_id', '')}:"
                f"{getattr(chunk, 'file_id', '')}:"
                f"{metadata.get('chunk_index')}:"
                f"{getattr(chunk, 'content', '')[:120]}"
            )
        )
        if key not in seen or getattr(chunk, "score", 0.0) > getattr(seen[key], "score", 0.0):
            seen[key] = chunk
    return list(seen.values())
