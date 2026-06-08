"""Knowledge base REST API — full CRUD + file upload + search.

Endpoints
---------
GET    /api/knowledge/                              list all KBs
POST   /api/knowledge/                              create KB
GET    /api/knowledge/{kb_id}                       get KB metadata
DELETE /api/knowledge/{kb_id}                       delete KB

POST   /api/knowledge/{kb_id}/files                 upload file (multipart)
GET    /api/knowledge/{kb_id}/files                 list files
GET    /api/knowledge/{kb_id}/files/{file_id}       get file metadata
DELETE /api/knowledge/{kb_id}/files/{file_id}       delete file
POST   /api/knowledge/{kb_id}/files/{file_id}/parse  parse (extract text)
POST   /api/knowledge/{kb_id}/files/{file_id}/index  index (embed + store)

POST   /api/knowledge/{kb_id}/search               semantic search
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from nexagent.knowledge.base import KnowledgeFileError, max_upload_bytes
from nexagent.knowledge.models import EmbedInfo, KBType
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()
KNOWLEDGE_INGESTION_TASK_KIND = "knowledge_ingestion"
SEARCH_TIMEOUT_SECONDS = 60
_ACTIVE_INGESTION_FILES: set[str] = set()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class KBCreateRequest(BaseModel):
    name: str
    description: str = ""
    kb_type: str = Field(default="milvus", pattern="^(milvus|lightrag|wiki)$")
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=512)
    chunk_preset_id: str = Field(default="general", pattern="^(general|qa|book|laws|paper)$")
    chunk_parser_config: dict[str, Any] = Field(default_factory=dict)
    embed_model: str = ""
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_dimension: int | None = Field(default=None, ge=1, le=8192)


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    mode: str = Field(
        default="hybrid",
        description="vector | keyword | hybrid | lightrag_local | lightrag_global | lightrag_hybrid | wiki",
    )
    search_mode: str | None = None
    recall_top_k: int | None = Field(default=None, ge=1, le=200)
    final_top_k: int | None = Field(default=None, ge=1, le=100)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    keyword_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    bm25_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    bm25_top_k: int | None = Field(default=None, ge=1, le=200)
    bm25_drop_ratio_search: float | None = Field(default=None, ge=0.0, le=1.0)
    use_reranker: bool | None = None
    reranker_model: str = ""


class HybridSearchRequest(SearchRequest):
    kb_ids: list[str] = Field(default_factory=list, description="Empty means search all knowledge bases")


class GraphUploadRequest(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=128)


class ProcessAllRequest(BaseModel):
    retry_errors: bool = True


class QueryConfigUpdate(BaseModel):
    mode: str | None = None
    search_mode: str | None = None
    recall_top_k: int | None = Field(default=None, ge=1, le=200)
    final_top_k: int | None = Field(default=None, ge=1, le=100)
    similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    vector_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    keyword_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    bm25_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    bm25_top_k: int | None = Field(default=None, ge=1, le=200)
    bm25_drop_ratio_search: float | None = Field(default=None, ge=0.0, le=1.0)
    use_reranker: bool | None = None
    reranker_model: str | None = None


class ModelConfigUpdate(BaseModel):
    embed_model: str | None = None
    embed_base_url: str | None = None
    embed_api_key: str | None = None
    embed_dimension: int | None = Field(default=None, ge=1, le=8192)
    use_reranker: bool | None = None
    reranker_model: str | None = None


class ChunkConfigUpdate(BaseModel):
    chunk_size: int | None = Field(default=None, ge=64, le=65535)
    chunk_overlap: int | None = Field(default=None, ge=0, le=65534)
    chunk_preset_id: str | None = Field(default=None, pattern="^(general|qa|book|laws|paper)$")
    chunk_parser_config: dict[str, Any] | None = None


# ── Manager accessor ──────────────────────────────────────────────────────────

def _mgr():
    """Lazy-import the manager so import errors are surfaced at request time."""
    try:
        from nexagent.knowledge.manager import get_manager
        return get_manager()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Knowledge service unavailable: {exc}. "
                   "Make sure Phase 3 services are running: "
                   "docker compose --profile kb up -d",
        ) from exc


def _prod_enabled() -> bool:
    try:
        from nexagent.knowledge.production_service import production_enabled

        return production_enabled()
    except Exception:
        return False


def _prod_service():
    from nexagent.knowledge.production_service import get_production_service

    return get_production_service()


async def _prod_kb(kb_id: str):
    if not _prod_enabled():
        return None
    return await _prod_service().get_kb(kb_id)


def _legacy_read_only_error(kb_id: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error_code": "legacy_kb_read_only",
            "message": "This is a legacy local knowledge base. Create a new production KB and upload the files again.",
            "details": {"kb_id": kb_id},
            "action": "create_production_kb",
        },
    )


def _kb_or_404(kb_id: str):
    mgr = _mgr()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base not found: {kb_id}")
    return mgr, kb


def _kb_type_value(kb) -> str:
    return str(getattr(getattr(kb, "kb_type", ""), "value", getattr(kb, "kb_type", "")))


def _kb_public_dict(kb) -> dict:
    if hasattr(kb, "to_dict"):
        try:
            payload = kb.to_dict(include_secrets=False)
        except TypeError:
            payload = kb.to_dict()
    else:
        payload = dict(kb)
    for key in ("embed_info", "llm_info"):
        if isinstance(payload.get(key), dict):
            payload[key].pop("api_key", None)
    return payload


def _redact_kb_secrets(payload: dict) -> dict:
    out = dict(payload)
    for key in ("embed_info", "llm_info"):
        if isinstance(out.get(key), dict):
            out[key] = dict(out[key])
            out[key].pop("api_key", None)
    if isinstance(out.get("kb"), dict):
        out["kb"] = _redact_kb_secrets(out["kb"])
    return out


def _local_wiki_kb_or_404(kb_id: str):
    mgr = _mgr()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base not found: {kb_id}")
    if _kb_type_value(kb) != "wiki":
        raise HTTPException(status_code=400, detail="This endpoint only supports Wiki knowledge bases.")
    return mgr, kb, mgr._find_backend(kb_id)


async def _is_local_wiki_kb(kb_id: str) -> bool:
    try:
        kb = _mgr().get_kb(kb_id)
        return bool(kb and _kb_type_value(kb) == "wiki")
    except Exception:
        return False


def _raise_knowledge_file_error(exc: KnowledgeFileError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.to_detail()) from exc


def _state_error_detail(exc: Exception) -> dict:
    if isinstance(exc, KnowledgeFileError):
        return exc.to_detail()
    return {
        "error_code": "file_operation_failed",
        "message": str(exc),
        "details": {},
    }


async def _read_upload_content(file: UploadFile) -> bytes:
    limit = max_upload_bytes()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise KnowledgeFileError(
                "file_too_large",
                f"Uploaded file exceeds the maximum size of {limit} bytes.",
                status_code=413,
                details={
                    "filename": file.filename or "",
                    "size": total,
                    "max_size": limit,
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _resolve_provider_model(model_ref: str, capability: str) -> dict | None:
    """Resolve provider_id::model_id into endpoint credentials and model metadata."""
    if "::" not in model_ref:
        return None
    import os

    from nexagent.db.crypto import decrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    provider_id, model_id = model_ref.split("::", 1)
    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider not found: {provider_id}")
        configs = provider.model_configs or []
        config = next((item for item in configs if item.get("id") == model_id), None)
        if config and config.get("type") not in {capability, None, ""}:
            raise HTTPException(status_code=400, detail=f"Model '{model_id}' is not a {capability} model")
        if not config and model_id not in (provider.models or []):
            raise HTTPException(
                status_code=404,
                detail=f"Model '{model_id}' is not configured on provider '{provider_id}'",
            )
        env_name = provider.api_key_env or ""
        api_key = os.environ.get(env_name, "") if env_name else ""
        if not api_key:
            api_key = decrypt_key(provider.api_key_enc or "")
        return {
            "model_ref": model_ref,
            "provider_id": provider_id,
            "model_id": model_id,
            "base_url": (config or {}).get("base_url_override") or provider.base_url or "",
            "api_key": api_key,
            "dimension": (config or {}).get("dimension"),
        }


def _search_result_payload(result, index: int) -> dict:
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    else:
        payload = dict(getattr(result, "__dict__", {}))
    if hasattr(result, "evidence"):
        payload["evidence"] = result.evidence(index)
    else:
        payload["evidence"] = {
            "id": f"E{index}",
            "source": payload.get("source") or "unknown",
            "file_id": payload.get("file_id") or "",
            "score": payload.get("score", 0.0),
            "metadata": payload.get("metadata") or {},
            "preview": str(payload.get("content") or "")[:240],
        }
    metadata = payload.get("metadata") or {}
    if isinstance(metadata, dict):
        payload.setdefault("chunk_id", metadata.get("chunk_id") or metadata.get("id") or "")
        payload.setdefault("chunk_index", metadata.get("chunk_index"))
        payload.setdefault("source", metadata.get("source") or payload.get("source") or "")
        payload.setdefault("file_id", metadata.get("file_id") or payload.get("file_id") or "")
    return payload


def _structured_search_payload(
    *,
    req: SearchRequest,
    mode: str,
    search_result,
    kb_ids: list[str],
    kb_id: str = "",
    kb_type: str = "",
) -> dict:
    payload = {
        "query": req.query,
        "mode": mode,
        "retrieval_config": _search_kwargs(req),
        "results": [_search_result_payload(result, index) for index, result in enumerate(search_result.chunks, 1)],
        "total": len(search_result.chunks),
        "degraded": bool(search_result.degraded),
        "warnings": search_result.warning_dicts(),
        "error_code": search_result.error_code,
        "fallback_source": _fallback_source(search_result.chunks),
    }
    if kb_id:
        payload["kb_id"] = kb_id
        payload["kb_type"] = kb_type
    else:
        payload["kb_ids"] = kb_ids
    return payload


def _search_warnings(results: list) -> list[dict]:
    warnings: dict[str, dict] = {}
    for result in results:
        metadata = getattr(result, "metadata", None) or {}
        if not metadata.get("degraded"):
            continue
        reason = str(metadata.get("degraded_reason") or "degraded_search")
        message = {
            "milvus_collection_missing": (
                "Milvus collection is missing; local indexed/parsed chunks were used for degraded search."
            ),
            "milvus_dependency_missing": (
                "Milvus dependency is missing; local indexed/parsed chunks were used for degraded search."
            ),
            "milvus_service_unavailable": (
                "Milvus service is unavailable; local indexed/parsed chunks were used for degraded search."
            ),
            "native_bm25_unavailable": "Native BM25 is unavailable; lexical fallback was used.",
        }.get(reason, "Search used a degraded local fallback.")
        warnings[reason] = {
            "code": reason,
            "message": message,
            "action": metadata.get("action") or ("reindex_recommended" if reason.startswith("milvus_") else ""),
        }
    return list(warnings.values())


def _fallback_source(results: list) -> str:
    for result in results:
        metadata = getattr(result, "metadata", None) or {}
        if not metadata.get("degraded"):
            continue
        reason = str(metadata.get("degraded_reason") or "")
        if reason in {
            "milvus_collection_missing",
            "milvus_dependency_missing",
            "milvus_service_unavailable",
            "milvus_unavailable",
        }:
            return "parsed_chunks" if metadata.get("source") == "parsed_fallback" else "local_index"
        if reason == "native_bm25_unavailable":
            return "parsed_chunks" if metadata.get("source") == "parsed_fallback" else "local_index"
    return "none"


def _search_error_code(detail: str) -> str:
    lowered = detail.lower()
    if "collection not found" in lowered:
        return "milvus_collection_missing"
    if "dependency missing" in lowered or "pymilvus" in lowered:
        return "milvus_dependency_missing"
    if "timeout" in lowered:
        return "search_timeout"
    if "embedding" in lowered or "api key" in lowered:
        return "embedding_failed"
    if "service unavailable" in lowered or "milvus" in lowered:
        return "milvus_service_unavailable"
    return "search_failed"


def _search_error_detail(code: str, detail: str, *, fallback_source: str = "none") -> dict:
    message = {
        "milvus_collection_missing": "Milvus collection 不存在，请重新入库后再进行向量检索。",
        "milvus_dependency_missing": "Milvus 依赖缺失，请安装 pymilvus 或使用本地降级索引。",
        "milvus_service_unavailable": "Milvus 服务不可用，请检查知识库服务或重新入库。",
        "embedding_failed": "Embedding 模型调用失败，请检查知识库的嵌入模型和 API Key。",
        "search_timeout": "检索超时，请缩小 Top K 或检查 Milvus / Embedding 服务。",
        "no_indexed_chunks": "该知识库没有可用于检索的 indexed chunks，请先完成入库。",
    }.get(code, "知识库检索失败，请检查索引和模型配置。")
    return {
        "error_code": code,
        "message": message,
        "detail": detail,
        "degraded": False,
        "fallback_source": fallback_source,
        "warnings": [],
    }


def _search_status_code(code: str) -> int:
    if code in {"invalid_search_mode"}:
        return 400
    if code in {"milvus_collection_missing", "no_indexed_chunks"}:
        return 409
    if code in {"milvus_dependency_missing", "milvus_service_unavailable", "embedding_failed", "search_timeout"}:
        return 503
    return 500


def _local_fallback_results(mgr, kb_id: str, query: str, top_k: int, reason: str) -> list:
    from nexagent.knowledge.models import SearchResult

    tokens = {token.lower() for token in query.split() if token.strip()}
    chunks = mgr.list_indexed_chunks(kb_id, limit=1000)
    if not chunks:
        try:
            for file in mgr.list_files(kb_id):
                parsed_path = Path(str(getattr(file, "parsed_path", "") or ""))
                if not parsed_path.exists() or not parsed_path.is_file():
                    continue
                content = parsed_path.read_text(encoding="utf-8", errors="ignore")
                for index in range(0, len(content), 1200):
                    chunks.append(
                        {
                            "file_id": getattr(file, "file_id", ""),
                            "filename": getattr(file, "filename", ""),
                            "chunk_index": index // 1200,
                            "content": content[index : index + 1200],
                            "metadata": {"source": "parsed_fallback"},
                        }
                    )
        except Exception:
            chunks = []
    results = []
    for chunk in chunks:
        content = str(chunk.get("content") or chunk.get("text") or "")
        if not content:
            continue
        lowered = content.lower()
        overlap = sum(1 for token in tokens if token in lowered)
        score = overlap / max(len(tokens), 1) if tokens else 0.1
        if overlap or not tokens:
            results.append(
                SearchResult(
                    content=content,
                    score=max(score, 0.05),
                    source=str(chunk.get("filename") or chunk.get("source") or chunk.get("file_id") or ""),
                    file_id=str(chunk.get("file_id") or ""),
                    metadata={
                        **dict(chunk.get("metadata") or {}),
                        "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
                        "chunk_index": chunk.get("chunk_index"),
                        "degraded": True,
                        "degraded_reason": reason,
                        "engine": "router_local_fallback",
                      "source": "parsed_fallback"
                      if (chunk.get("metadata") or {}).get("source") == "parsed_fallback"
                      else "local_index",
                    },
                )
            )
    if not results and chunks:
        chunk = chunks[0]
        results.append(
            SearchResult(
                content=str(chunk.get("content") or chunk.get("text") or ""),
                score=0.01,
                source=str(chunk.get("filename") or chunk.get("source") or chunk.get("file_id") or ""),
                file_id=str(chunk.get("file_id") or ""),
                metadata={
                    **dict(chunk.get("metadata") or {}),
                    "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
                    "chunk_index": chunk.get("chunk_index"),
                    "degraded": True,
                    "degraded_reason": reason,
                    "engine": "router_local_fallback",
                    "source": "parsed_fallback"
                    if (chunk.get("metadata") or {}).get("source") == "parsed_fallback"
                    else "local_index",
                },
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]


def _fallback_or_raise_search_response(mgr, kb, kb_id: str, req: SearchRequest, mode: str, detail: str) -> dict:
    code = _search_error_code(detail)
    allow_local_fallback = os.environ.get("NEXAGENT_FORCE_LOCAL_KB_FALLBACK") == "1"
    results = _local_fallback_results(mgr, kb_id, req.query, req.top_k, code) if allow_local_fallback else []
    if results:
        fallback_source = _fallback_source(results)
        warnings = _search_warnings(results)
        warnings.append({"code": code, "message": detail, "action": "reindex_recommended"})
        return {
            "query": req.query,
            "kb_id": kb_id,
            "kb_type": kb.kb_type.value,
            "mode": mode,
            "retrieval_config": _search_kwargs(req),
            "results": [_search_result_payload(result, index) for index, result in enumerate(results, 1)],
            "total": len(results),
            "degraded": True,
            "warnings": warnings,
            "error_code": code,
            "fallback_source": fallback_source,
        }
    if code in {
        "milvus_collection_missing",
        "milvus_dependency_missing",
        "milvus_service_unavailable",
        "embedding_failed",
    }:
        status = 503 if code in {"milvus_dependency_missing", "milvus_service_unavailable", "embedding_failed"} else 409
        raise HTTPException(status_code=status, detail=_search_error_detail(code, detail))
    status = 503 if code == "search_timeout" else 500
    raise HTTPException(status_code=status, detail=_search_error_detail(code, detail))


def _raise_structured_search_error(mgr, kb_id: str, detail: str) -> None:
    code = _search_error_code(detail)
    chunks = []
    try:
        chunks = mgr.list_indexed_chunks(kb_id, limit=1)
    except Exception:
        chunks = []
    if code == "milvus_collection_missing" and not chunks:
        raise HTTPException(
            status_code=409,
            detail=_search_error_detail("no_indexed_chunks", detail),
        )
    status = (
        _search_status_code(code)
    )
    raise HTTPException(status_code=status, detail=_search_error_detail(code, detail))


def _search_kwargs(req: SearchRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    payload.pop("query", None)
    payload.pop("top_k", None)
    payload.pop("mode", None)
    payload.pop("search_mode", None)
    if "bm25_weight" in payload and "keyword_weight" not in payload:
        payload["keyword_weight"] = payload["bm25_weight"]
    return payload


def _mode_for_request(req: SearchRequest, kb_type: str) -> str:
    raw = str(req.search_mode or req.mode or "").strip().lower()
    if raw == "bm25":
        raw = "keyword"
    allowed = _available_modes(kb_type)
    default = "wiki" if kb_type == KBType.WIKI.value else "lightrag_hybrid" if kb_type == KBType.LIGHTRAG.value else "hybrid"
    mode = raw or default
    if mode not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Search mode '{mode}' is not supported for {kb_type} knowledge bases. "
            f"Available modes: {', '.join(allowed)}",
        )
    return mode


def _available_modes(kb_type: str) -> list[str]:
    if kb_type == KBType.WIKI.value:
        return ["wiki"]
    if kb_type == KBType.LIGHTRAG.value:
        return ["lightrag_local", "lightrag_global", "lightrag_hybrid"]
    return ["vector", "keyword", "hybrid"]


def _query_config_response(mgr, kb_id: str, kb_type: str) -> dict:
    return {
        "kb_id": kb_id,
        "kb_type": kb_type,
        "available_modes": _available_modes(kb_type),
        "options": mgr.get_query_options(kb_id),
        "query_config": mgr.get_query_config(kb_id),
        "effective_config": mgr.get_query_config(kb_id),
    }


def _task_or_404(task_id: str):
    from nexagent.services.task_service import get_task

    task = get_task(task_id)
    if task is None or task.kind != KNOWLEDGE_INGESTION_TASK_KIND:
        raise HTTPException(status_code=404, detail=f"Ingestion task not found: {task_id}")
    return task


async def _run_ingestion_task(task_id: str) -> None:
    from nexagent.services.task_service import is_cancel_requested, update_progress, update_task

    task = _task_or_404(task_id)
    kb_id = str(task.metadata.get("kb_id") or "")
    file_ids = [str(file_id) for file_id in task.metadata.get("file_ids", [])]
    if task.cancel_requested or task.status == "cancelled":
        update_task(
            task_id,
            status="cancelled",
            progress=0.0,
            current_step="cancelled",
            total_steps=len(file_ids),
            error="Task was cancelled before it started.",
        )
        return
    result = {
        "completed": 0,
        "failed": 0,
        "items": [],
        "current_file_id": "",
    }
    update_task(task_id, status="running", progress=0.0, result=result, total_steps=len(file_ids))
    mgr = _mgr()
    try:
        for index, file_id in enumerate(file_ids, 1):
            if is_cancel_requested(task_id):
                result["current_file_id"] = ""
                update_progress(
                    task_id,
                    completed_steps=index - 1,
                    total_steps=len(file_ids),
                    current_step="cancelled",
                    result=result,
                    status="cancelled",
                    error="Task was cancelled.",
                )
                return

            result["current_file_id"] = file_id
            update_progress(
                task_id,
                completed_steps=index - 1,
                total_steps=len(file_ids),
                current_step=f"Processing file {index}/{len(file_ids)}",
                result=result,
            )
            active_key = f"{kb_id}:{file_id}"
            if active_key in _ACTIVE_INGESTION_FILES:
                result["failed"] = int(result["failed"]) + 1
                result["items"].append(
                    {"file_id": file_id, "status": "skipped", "error": "File is already being processed."}
                )
                update_progress(
                    task_id,
                    completed_steps=index,
                    total_steps=len(file_ids),
                    result=result,
                )
                continue
            _ACTIVE_INGESTION_FILES.add(active_key)
            try:
                f = mgr.get_file(kb_id, file_id)
                if f is None:
                    raise ValueError(f"File not found: {file_id}")
                if f.status.value in {"uploaded", "parse_error"}:
                    await mgr.parse_file(kb_id, file_id)
                    f = mgr.get_file(kb_id, file_id)
                if f and f.status.value in {
                    "parsed",
                    "index_error",
                    "error_graphing",
                    "indexed_with_graph_degraded",
                }:
                    await mgr.index_file(kb_id, file_id)
                updated = mgr.get_file(kb_id, file_id)
                result["completed"] = int(result["completed"]) + 1
                result["items"].append({"file_id": file_id, "status": updated.status.value if updated else "unknown"})
            except KnowledgeFileError as exc:
                logger.info("Ingestion task %s rejected file %s: %s", task_id, file_id, exc)
                result["failed"] = int(result["failed"]) + 1
                result["items"].append(
                    {
                        "file_id": file_id,
                        "status": "error",
                        "error": exc.message,
                        "error_code": exc.code,
                    }
                )
            except Exception as exc:
                logger.exception("Ingestion task %s failed for file %s", task_id, file_id)
                result["failed"] = int(result["failed"]) + 1
                result["items"].append({"file_id": file_id, "status": "error", "error": str(exc)})
            finally:
                _ACTIVE_INGESTION_FILES.discard(active_key)
                update_progress(
                    task_id,
                    completed_steps=index,
                    total_steps=len(file_ids),
                    result=result,
                )
        result["current_file_id"] = ""
        failed = int(result["failed"])
        completed = int(result["completed"])
        status = "failed" if failed and completed == 0 else "completed"
        update_progress(
            task_id,
            completed_steps=len(file_ids),
            total_steps=len(file_ids),
            current_step="done",
            result=result,
            status=status,
        )
    except Exception as exc:
        logger.exception("Ingestion task %s failed", task_id)
        update_task(task_id, status="failed", error=str(exc), result=result)


def _queue_ingestion(kb_id: str, file_ids: list[str]):
    from nexagent.services.task_service import create_task

    task = create_task(
        kind=KNOWLEDGE_INGESTION_TASK_KIND,
        metadata={"kb_id": kb_id, "file_ids": file_ids},
        total_steps=len(file_ids),
        current_step="queued",
    )
    asyncio.create_task(_run_ingestion_task(task.task_id))
    return task


def _retry_ingestion_task(task):
    result = task.result or {}
    failed_ids = [
        str(item["file_id"])
        for item in result.get("items", [])
        if item.get("file_id")
        and str(item.get("status")) in {"error", "parse_error", "index_error", "error_graphing", "indexed_with_graph_degraded"}
    ]
    file_ids = failed_ids or [str(file_id) for file_id in task.metadata.get("file_ids", [])]
    if not file_ids:
        raise ValueError("Task has no files to retry.")
    return _queue_ingestion(str(task.metadata.get("kb_id") or ""), file_ids)


try:
    from nexagent.services.task_service import register_retry_handler

    register_retry_handler(KNOWLEDGE_INGESTION_TASK_KIND, _retry_ingestion_task)
except Exception as exc:
    logger.debug("Knowledge ingestion retry handler registration skipped: %s", exc)


# ── Knowledge base CRUD ───────────────────────────────────────────────────────

@router.get("/", summary="List all knowledge bases")
async def list_kbs():
    if _prod_enabled():
        prod = _prod_service()
        prod_kbs = [_kb_public_dict(kb) for kb in await prod.list_kbs()]
        local_wiki = []
        legacy = []
        try:
            for kb in _mgr().list_kbs():
                item = _kb_public_dict(kb)
                if _kb_type_value(kb) == "wiki":
                    item["extra"] = {**item.get("extra", {}), "storage": "local_wiki"}
                    local_wiki.append(item)
                    continue
                item.setdefault("extra", {})
                item["extra"] = {**item.get("extra", {}), "legacy": True, "read_only": True}
                item["status"] = "legacy"
                legacy.append(item)
        except Exception:
            local_wiki = []
            legacy = []
        items = prod_kbs + local_wiki + legacy
        return {"knowledge_bases": items, "total": len(items), "mode": "production"}
    mgr = _mgr()
    kbs = mgr.list_kbs()
    return {"knowledge_bases": [_kb_public_dict(kb) for kb in kbs], "total": len(kbs)}


@router.post("/", summary="Create a knowledge base", status_code=201)
async def create_kb(req: KBCreateRequest):
    if req.kb_type == "wiki":
        mgr = _mgr()
        try:
            kb = await mgr.create_kb(
                name=req.name,
                description=req.description,
                kb_type="wiki",
                embed_info=None,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
                chunk_preset_id=req.chunk_preset_id,
                chunk_parser_config=req.chunk_parser_config,
            )
            return _kb_public_dict(kb)
        except Exception as exc:
            logger.exception("Failed to create Wiki KB")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if _prod_enabled():
        try:
            embed_info = None
            if req.embed_model or req.embed_base_url or req.embed_api_key or req.embed_dimension:
                provider_model = await _resolve_provider_model(req.embed_model, "embedding") if req.embed_model else None
                embed_info = EmbedInfo(
                    model=req.embed_model or "BAAI/bge-large-zh-v1.5",
                    base_url=req.embed_base_url or (provider_model or {}).get("base_url", ""),
                    api_key=req.embed_api_key or (provider_model or {}).get("api_key", ""),
                    dimension=req.embed_dimension or (provider_model or {}).get("dimension") or 1024,
                )
            kb = await _prod_service().create_kb(
                name=req.name,
                description=req.description,
                kb_type=req.kb_type,
                embed_info=embed_info,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
                chunk_preset_id=req.chunk_preset_id,
                chunk_parser_config=req.chunk_parser_config,
            )
            return _kb_public_dict(kb)
        except Exception as exc:
            logger.exception("Failed to create production KB")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    mgr = _mgr()
    try:
        embed_info = None
        if req.embed_model or req.embed_base_url or req.embed_api_key or req.embed_dimension:
            provider_model = await _resolve_provider_model(req.embed_model, "embedding") if req.embed_model else None
            embed_info = EmbedInfo(
                model=req.embed_model or "BAAI/bge-large-zh-v1.5",
                base_url=req.embed_base_url or (provider_model or {}).get("base_url", ""),
                api_key=req.embed_api_key or (provider_model or {}).get("api_key", ""),
                dimension=req.embed_dimension or (provider_model or {}).get("dimension") or 1024,
            )
        kb = await mgr.create_kb(
            name=req.name,
            description=req.description,
            kb_type=req.kb_type,
            embed_info=embed_info,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            chunk_preset_id=req.chunk_preset_id,
            chunk_parser_config=req.chunk_parser_config,
        )
    except Exception as exc:
        logger.exception("Failed to create KB")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _kb_public_dict(kb)


@router.get("/status", summary="Knowledge backend status")
async def knowledge_status():
    if _prod_enabled():
        return await _prod_service().backend_status()
    mgr = _mgr()
    return mgr.backend_status()


@router.post("/search", summary="Hybrid search across knowledge bases")
async def hybrid_search(req: HybridSearchRequest):
    mgr = None if _prod_enabled() else _mgr()
    kb_ids = req.kb_ids or (
        [kb.kb_id for kb in await _prod_service().list_kbs()] if _prod_enabled() else [kb.kb_id for kb in mgr.list_kbs()]
    )
    mode = str(req.search_mode or req.mode or "hybrid").lower()
    if mode == "bm25":
        mode = "keyword"
    allowed = {"vector", "keyword", "hybrid", "lightrag_local", "lightrag_global", "lightrag_hybrid", "wiki"}
    if mode not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported search mode: {mode}")
    try:
        from nexagent.knowledge.search_service import structured_retrieve

        search_result = await structured_retrieve(
            query=req.query,
            kb_ids=kb_ids,
            mode=mode,
            top_k=req.top_k,
            timeout_s=SEARCH_TIMEOUT_SECONDS,
            **_search_kwargs(req),
        )
    except Exception as exc:
        logger.exception("Hybrid search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if search_result.error_code and not search_result.chunks:
        raise HTTPException(
            status_code=_search_status_code(search_result.error_code),
            detail=_search_error_detail(search_result.error_code, search_result.error),
        )
    return _structured_search_payload(req=req, mode=mode, search_result=search_result, kb_ids=kb_ids)


@router.get("/jobs/{job_id}", summary="Get knowledge ingestion job status")
async def get_ingestion_job(job_id: str):
    if _prod_enabled():
        job = await _prod_service().get_job(job_id)
        if job:
            return job
    return _task_or_404(job_id).to_dict()


@router.get("/jobs/{job_id}/logs", summary="Get knowledge ingestion job logs")
async def get_ingestion_job_logs(job_id: str):
    if _prod_enabled():
        job = await _prod_service().get_job(job_id)
        if job:
            return {"job_id": job_id, "task": job, "logs": job.get("logs", [])}
    task = _task_or_404(job_id)
    items = task.result.get("items", []) if isinstance(task.result, dict) else []
    return {
        "job_id": job_id,
        "task": task.to_dict(),
        "logs": [
            {
                "file_id": item.get("file_id"),
                "status": item.get("status"),
                "error_code": item.get("error_code", ""),
                "message": item.get("error", item.get("status", "")),
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


@router.post("/{kb_id}/wiki/compile", summary="Compile Wiki pages")
async def compile_wiki(kb_id: str, body: dict[str, Any] | None = None):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    file_ids = (body or {}).get("file_ids")
    if file_ids is not None and not isinstance(file_ids, list):
        raise HTTPException(status_code=400, detail="file_ids must be a list")
    force = bool((body or {}).get("force"))
    retry_failed = bool((body or {}).get("retry_failed"))
    return await backend.compile_wiki(kb_id, file_ids=file_ids, force=force, retry_failed=retry_failed)


@router.get("/{kb_id}/wiki/pages", summary="List Wiki pages")
async def list_wiki_pages(
    kb_id: str,
    type: str | None = None,
    q: str | None = None,
    status: str | None = None,
    source_file_id: str | None = None,
):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.list_wiki_pages(kb_id, page_type=type, q=q, status=status, source_file_id=source_file_id)


@router.get("/{kb_id}/wiki/pages/{page_id}", summary="Get Wiki page")
async def get_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return backend.get_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{kb_id}/wiki/pages/{page_id}", summary="Update Wiki page")
async def update_wiki_page(kb_id: str, page_id: str, body: dict[str, Any]):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    frontmatter = body.get("frontmatter") if isinstance(body.get("frontmatter"), dict) else None
    try:
        return await backend.update_wiki_page(kb_id, page_id, str(body.get("content") or ""), frontmatter=frontmatter)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{kb_id}/wiki/pages/{page_id}", summary="Delete Wiki page")
async def delete_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return await backend.delete_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{kb_id}/wiki/pages/{page_id}/accept-generated", summary="Accept Wiki candidate")
async def accept_generated_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return await backend.accept_generated_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{kb_id}/wiki/pages/{page_id}/discard-generated", summary="Discard Wiki candidate")
async def discard_generated_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return await backend.discard_generated_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{kb_id}/wiki/graph", summary="Get Wiki graph")
async def get_wiki_graph(
    kb_id: str,
    max_edges: int = Query(80),
    include_weak: bool = Query(False),
    q: str | None = Query(None),
):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.get_wiki_graph(kb_id, max_edges=max_edges, include_weak=include_weak, q=q)


@router.get("/{kb_id}/wiki/lint", summary="Lint Wiki")
async def lint_wiki(kb_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.lint_wiki(kb_id)


@router.post("/{kb_id}/wiki/crystallize", summary="Crystallize Markdown into Wiki")
async def crystallize_wiki(kb_id: str, body: dict[str, Any]):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    page_type = str(body.get("type") or "note").strip()
    confidence = str(body.get("confidence") or "UNVERIFIED").strip().upper()
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")
    try:
        return await backend.crystallize_wiki_text(
            kb_id,
            title,
            content,
            page_type=page_type,
            sources=sources,
            confidence=confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/retry", summary="Retry a failed or interrupted ingestion job")
async def retry_ingestion_job(job_id: str):
    if _prod_enabled():
        job = await _prod_service().get_job(job_id)
        if job:
            file_ids = (job.get("metadata") or {}).get("file_ids") or []
            file_id = file_ids[0] if file_ids else job.get("file_id")
            new_job = await _prod_service().create_job(str(job.get("kb_id") or ""), file_id, str(job.get("job_type") or "ingest"))
            return {"task": new_job, "job": new_job, "retried_from": job_id, "queued": 1}
    from nexagent.services.task_service import retry_task

    try:
        task = await retry_task(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "task": task.to_dict(),
        "job": task.to_dict(),
        "retried_from": job_id,
        "queued": int(task.total_steps),
    }


@router.get("/{kb_id}", summary="Get knowledge base metadata")
async def get_kb(kb_id: str):
    prod_kb = await _prod_kb(kb_id)
    if prod_kb:
        return _kb_public_dict(prod_kb)
    if await _is_local_wiki_kb(kb_id):
        _, kb = _kb_or_404(kb_id)
        item = _kb_public_dict(kb)
        item["extra"] = {**item.get("extra", {}), "storage": "local_wiki"}
        return item
    if _prod_enabled():
        _, kb = _kb_or_404(kb_id)
        item = _kb_public_dict(kb)
        item["extra"] = {**item.get("extra", {}), "legacy": True, "read_only": True}
        item["status"] = "legacy"
        return item
    _, kb = _kb_or_404(kb_id)
    return _kb_public_dict(kb)


@router.get("/{kb_id}/query-config", summary="Get knowledge base query config")
async def get_query_config(kb_id: str):
    prod_kb = await _prod_kb(kb_id)
    if prod_kb:
        return {
            "kb_id": kb_id,
            "kb_type": prod_kb.kb_type.value,
            "mode": "lightrag_hybrid" if prod_kb.kb_type.value == "lightrag" else "hybrid",
            "final_top_k": 10,
            "recall_top_k": 30,
            "similarity_threshold": 0,
            "vector_weight": 0.7,
            "bm25_weight": 0.3,
            "keyword_weight": 0.3,
            "bm25_top_k": 50,
            "bm25_drop_ratio_search": 0,
            "use_reranker": bool(prod_kb.extra.get("use_reranker")),
            "reranker_model": str(prod_kb.extra.get("reranker_model") or ""),
            "requires_reindex": bool(prod_kb.extra.get("requires_reindex")),
        }
    if await _is_local_wiki_kb(kb_id):
        mgr, kb = _kb_or_404(kb_id)
        return _query_config_response(mgr, kb_id, kb.kb_type.value)
    mgr, kb = _kb_or_404(kb_id)
    return _query_config_response(mgr, kb_id, kb.kb_type.value)


@router.patch("/{kb_id}/query-config", summary="Update knowledge base query config")
async def update_query_config(kb_id: str, req: QueryConfigUpdate):
    if await _prod_kb(kb_id):
        return {"kb_id": kb_id, **req.model_dump(exclude_none=True), "status": "saved"}
    if await _is_local_wiki_kb(kb_id):
        mgr, kb = _kb_or_404(kb_id)
        patch = req.model_dump(exclude_none=True)
        mgr.update_query_config(kb_id, patch)
        return _query_config_response(mgr, kb_id, kb.kb_type.value)
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, kb = _kb_or_404(kb_id)
    patch = req.model_dump(exclude_none=True)
    mgr.update_query_config(kb_id, patch)
    return _query_config_response(mgr, kb_id, kb.kb_type.value)


@router.patch("/{kb_id}/model-config", summary="Update knowledge base model config")
async def update_model_config(kb_id: str, req: ModelConfigUpdate):
    if await _prod_kb(kb_id):
        try:
            patch = req.model_dump(exclude_none=True)
            provider_model = (
                await _resolve_provider_model(str(patch.get("embed_model") or ""), "embedding")
                if patch.get("embed_model")
                else None
            )
            if provider_model:
                patch.setdefault("embed_base_url", provider_model.get("base_url", ""))
                patch.setdefault("embed_api_key", provider_model.get("api_key", ""))
                if provider_model.get("dimension") and "embed_dimension" not in patch:
                    patch["embed_dimension"] = provider_model["dimension"]
            return _redact_kb_secrets(await _prod_service().update_model_config(kb_id, patch))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        try:
            return _redact_kb_secrets(mgr.update_model_config(kb_id, req.model_dump(exclude_none=True)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    try:
        patch = req.model_dump(exclude_none=True)
        provider_model = (
            await _resolve_provider_model(str(patch.get("embed_model") or ""), "embedding")
            if patch.get("embed_model")
            else None
        )
        if provider_model:
            patch.setdefault("embed_base_url", provider_model.get("base_url", ""))
            patch.setdefault("embed_api_key", provider_model.get("api_key", ""))
            if provider_model.get("dimension") and "embed_dimension" not in patch:
                patch["embed_dimension"] = provider_model["dimension"]
        return _redact_kb_secrets(mgr.update_model_config(kb_id, patch))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/chunk-config", summary="Get knowledge base chunk config")
async def get_chunk_config(kb_id: str):
    prod_kb = await _prod_kb(kb_id)
    if prod_kb:
        return {
            "kb_id": kb_id,
            "chunk_size": prod_kb.chunk_size,
            "chunk_overlap": prod_kb.chunk_overlap,
            "chunk_preset_id": prod_kb.chunk_preset_id,
            "chunk_parser_config": prod_kb.chunk_parser_config,
            "requires_reindex": bool(prod_kb.extra.get("requires_reindex")),
        }
    _, kb = _kb_or_404(kb_id)
    return {
        "kb_id": kb_id,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "chunk_preset_id": kb.chunk_preset_id,
        "chunk_parser_config": kb.chunk_parser_config,
        "requires_reindex": bool(kb.extra.get("requires_reindex")),
    }


@router.patch("/{kb_id}/chunk-config", summary="Update knowledge base chunk config")
async def update_chunk_config(kb_id: str, req: ChunkConfigUpdate):
    if await _prod_kb(kb_id):
        try:
            return await _prod_service().update_chunk_config(kb_id, req.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        try:
            return mgr.update_chunk_config(kb_id, req.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.update_chunk_config(kb_id, req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/diagnostics", summary="Knowledge base diagnostics")
async def knowledge_diagnostics(kb_id: str):
    if await _prod_kb(kb_id):
        return await _prod_service().diagnostics(kb_id)
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        payload = mgr.diagnostics(kb_id)
        payload["storage"] = "local_wiki"
        return payload
    if _prod_enabled():
        return {
            "kb_id": kb_id,
            "status": "legacy",
            "issues": ["Legacy local knowledge base is read-only in production mode."],
            "action": "create_production_kb",
        }
    mgr, _ = _kb_or_404(kb_id)
    return mgr.diagnostics(kb_id)


@router.delete("/{kb_id}", summary="Delete a knowledge base", status_code=204)
async def delete_kb(kb_id: str):
    if await _prod_kb(kb_id):
        try:
            await _prod_service().delete_kb(kb_id)
            return None
        except Exception as exc:
            logger.exception("Failed to delete production KB %s", kb_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        try:
            await mgr.delete_kb(kb_id)
            return None
        except Exception as exc:
            logger.exception("Failed to delete local Wiki KB %s", kb_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    try:
        await mgr.delete_kb(kb_id)
    except Exception as exc:
        logger.exception("Failed to delete KB %s", kb_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── File management ───────────────────────────────────────────────────────────

@router.get("/{kb_id}/files", summary="List files in a knowledge base")
async def list_files(kb_id: str):
    if await _prod_kb(kb_id):
        files = await _prod_service().list_files(kb_id)
        return {"files": [f.to_dict() for f in files], "total": len(files)}
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        files = mgr.list_files(kb_id)
        return {"files": [f.to_dict() for f in files], "total": len(files)}
    if _prod_enabled():
        _, _ = _kb_or_404(kb_id)
        return {"files": [], "total": 0, "legacy": True, "read_only": True}
    mgr, _ = _kb_or_404(kb_id)
    files = mgr.list_files(kb_id)
    return {"files": [f.to_dict() for f in files], "total": len(files)}


@router.get("/{kb_id}/jobs", summary="List recent ingestion jobs for a knowledge base")
async def list_ingestion_jobs(kb_id: str):
    if await _prod_kb(kb_id):
        payload = await _prod_service().list_jobs(kb_id)
        return {"tasks": payload, "jobs": payload, "total": len(payload)}
    if await _is_local_wiki_kb(kb_id):
        _, _ = _kb_or_404(kb_id)
        from nexagent.services.task_service import list_tasks

        tasks = list_tasks(kind=KNOWLEDGE_INGESTION_TASK_KIND, metadata={"kb_id": kb_id}, limit=50)
        payload = [task.to_dict() for task in tasks]
        return {"tasks": payload, "jobs": payload, "total": len(payload)}
    if _prod_enabled():
        _, _ = _kb_or_404(kb_id)
        return {"tasks": [], "jobs": [], "total": 0, "legacy": True}
    _, _ = _kb_or_404(kb_id)
    from nexagent.services.task_service import list_tasks

    tasks = list_tasks(kind=KNOWLEDGE_INGESTION_TASK_KIND, metadata={"kb_id": kb_id}, limit=50)
    payload = [task.to_dict() for task in tasks]
    return {"tasks": payload, "jobs": payload, "total": len(payload)}


@router.post("/{kb_id}/files/process-all", summary="Queue parse and index for all pending files")
async def process_all_files(kb_id: str, req: ProcessAllRequest | None = None):
    if await _prod_kb(kb_id):
        retry_errors = True if req is None else req.retry_errors
        retryable = {"uploaded", "parsed"}
        if retry_errors:
            retryable.update({"parse_error", "index_error", "error_parsing", "error_indexing", "error_graphing", "indexed_with_graph_degraded"})
        files = await _prod_service().list_files(kb_id)
        jobs = [
            await _prod_service().create_job(kb_id, f.file_id, "ingest")
            for f in files
            if f.status.value in retryable
        ]
        return {"task": jobs[0] if len(jobs) == 1 else None, "job": jobs[0] if len(jobs) == 1 else None, "jobs": jobs, "queued": len(jobs)}
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        retry_errors = True if req is None else req.retry_errors
        retryable = {"uploaded", "parsed"}
        if retry_errors:
            retryable.update({"parse_error", "index_error", "error_graphing", "indexed_with_graph_degraded"})
        file_ids = [f.file_id for f in mgr.list_files(kb_id) if f.status.value in retryable]
        if not file_ids:
            return {"task": None, "job": None, "queued": 0, "message": "No pending files to process."}
        task = _queue_ingestion(kb_id, file_ids)
        return {"task": task.to_dict(), "job": task.to_dict(), "queued": len(file_ids)}
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    retry_errors = True if req is None else req.retry_errors
    retryable = {"uploaded", "parsed"}
    if retry_errors:
        retryable.update({"parse_error", "index_error", "error_graphing", "indexed_with_graph_degraded"})
    file_ids = [f.file_id for f in mgr.list_files(kb_id) if f.status.value in retryable]
    if not file_ids:
        return {"task": None, "job": None, "queued": 0, "message": "No pending files to process."}
    task = _queue_ingestion(kb_id, file_ids)
    return {"task": task.to_dict(), "job": task.to_dict(), "queued": len(file_ids)}


@router.post("/{kb_id}/files", summary="Upload a file", status_code=201)
async def upload_file(kb_id: str, file: UploadFile = File(...)):
    if await _prod_kb(kb_id):
        try:
            content = await _read_upload_content(file)
            meta = await _prod_service().add_file(kb_id, file.filename or "unknown", content)
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Failed to upload production file to KB %s", kb_id)
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "upload_failed",
                    "message": str(exc),
                    "details": {"filename": file.filename or ""},
                    "action": "check_minio_postgres",
                },
            ) from exc
        return meta.to_dict()
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        try:
            content = await _read_upload_content(file)
            meta = await mgr.add_file(kb_id, file.filename or "unknown", content)
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Failed to upload file to local Wiki KB %s", kb_id)
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "upload_failed",
                    "message": str(exc),
                    "details": {"filename": file.filename or ""},
                },
            ) from exc
        return meta.to_dict()
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    try:
        content = await _read_upload_content(file)
        meta = await mgr.add_file(kb_id, file.filename or "unknown", content)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Failed to upload file to KB %s", kb_id)
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "upload_failed",
                "message": str(exc),
                "details": {"filename": file.filename or ""},
            },
        ) from exc
    return meta.to_dict()


@router.get("/{kb_id}/files/{file_id}", summary="Get file metadata")
async def get_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        f = await _prod_service().get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        return f.to_dict()
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    return f.to_dict()


@router.get("/{kb_id}/files/{file_id}/preview", summary="Preview parsed file text")
async def preview_file(kb_id: str, file_id: str, max_chars: int = Query(default=12000, ge=100, le=50000)):
    if await _prod_kb(kb_id):
        f = await _prod_service().get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            content = await _prod_service().parsed_content(kb_id, file_id)
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        return {
            "file": f.to_dict(),
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "chars": len(content),
        }
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    if not f.parsed_path:
        raise HTTPException(status_code=409, detail="File has not been parsed yet.")
    parsed_path = Path(f.parsed_path).resolve()
    if not parsed_path.exists():
        raise HTTPException(status_code=404, detail="Parsed file is missing on disk.")
    content = parsed_path.read_text(encoding="utf-8", errors="replace")
    return {
        "file": f.to_dict(),
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
        "chars": len(content),
    }


@router.delete("/{kb_id}/files/{file_id}", summary="Delete a file", status_code=204)
async def delete_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            await _prod_service().delete_file(kb_id, file_id)
            return None
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
        except Exception as exc:
            logger.exception("Failed to delete production file %s", file_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        f = mgr.get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            await mgr.delete_file(kb_id, file_id)
            return None
        except Exception as exc:
            logger.exception("Failed to delete local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        await mgr.delete_file(kb_id, file_id)
    except Exception as exc:
        logger.exception("Failed to delete file %s", file_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{kb_id}/files/{file_id}/parse", summary="Extract text from uploaded file")
async def parse_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            return (await _prod_service().parse_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        f = mgr.get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            return (await mgr.parse_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Parse failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    """Parse the raw document and extract plain text (PDF → text, DOCX → text…)."""
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        updated = await mgr.parse_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Parse failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return updated.to_dict()


@router.post("/{kb_id}/files/{file_id}/reparse", summary="Re-parse a file from its original upload")
async def reparse_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            return (await _prod_service().reparse_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        if mgr.get_file(kb_id, file_id) is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            return (await mgr.reparse_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Reparse failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    if mgr.get_file(kb_id, file_id) is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        updated = await mgr.reparse_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Reparse failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return updated.to_dict()


@router.post("/{kb_id}/files/{file_id}/index", summary="Chunk, embed and index a parsed file")
async def index_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            return (await _prod_service().index_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        if mgr.get_file(kb_id, file_id) is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            return (await mgr.index_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Index failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    """Chunk the parsed text, generate embeddings, and store in the vector/graph backend."""
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        updated = await mgr.index_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Index failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return updated.to_dict()


# ── Search ────────────────────────────────────────────────────────────────────

@router.post("/{kb_id}/files/{file_id}/reindex", summary="Rebuild vector or graph index for a parsed file")
async def reindex_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            return (await _prod_service().reindex_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        if mgr.get_file(kb_id, file_id) is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            return (await mgr.reindex_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Reindex failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    if mgr.get_file(kb_id, file_id) is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        updated = await mgr.reindex_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Reindex failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return updated.to_dict()


@router.post("/{kb_id}/files/{file_id}/rebuild-graph", summary="Rebuild semantic graph for a file")
async def rebuild_graph_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            return (await _prod_service().rebuild_graph_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from None
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        if mgr.get_file(kb_id, file_id) is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            return (await mgr.rebuild_graph_file(kb_id, file_id)).to_dict()
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Graph rebuild failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    if mgr.get_file(kb_id, file_id) is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        updated = await mgr.rebuild_graph_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Graph rebuild failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return updated.to_dict()


@router.post("/{kb_id}/files/{file_id}/process", summary="Parse and index an uploaded file")
async def process_file(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        try:
            f = await _prod_service().get_file(kb_id, file_id)
            if f is None:
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
            parsed = f if f.status.value not in {"uploaded", "parse_error"} else await _prod_service().parse_file(kb_id, file_id)
            indexed = await _prod_service().index_file(kb_id, file_id)
            return {"parsed": parsed.to_dict(), "indexed": indexed.to_dict()}
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        f = mgr.get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        try:
            parsed = f
            if f.status.value in {"uploaded", "parse_error"}:
                parsed = await mgr.parse_file(kb_id, file_id)
                f = mgr.get_file(kb_id, file_id) or parsed
            indexed = await mgr.index_file(kb_id, file_id)
            return {"parsed": parsed.to_dict(), "indexed": indexed.to_dict()}
        except KnowledgeFileError as exc:
            _raise_knowledge_file_error(exc)
        except Exception as exc:
            logger.exception("Process failed for local Wiki file %s", file_id)
            raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    """Run full ingestion for clients that do not need parse/index step control."""
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    try:
        parsed = f
        if f.status.value in {"uploaded", "parse_error"}:
            parsed = await mgr.parse_file(kb_id, file_id)
            f = mgr.get_file(kb_id, file_id) or parsed
        if f.status.value not in {
            "parsed",
            "index_error",
            "indexed",
            "error_graphing",
            "graph_indexed",
            "indexed_with_graph_degraded",
        }:
            raise KnowledgeFileError(
                "invalid_file_state",
                f"File {file_id} cannot be processed from status {f.status.value}.",
                status_code=409,
                details={"file_id": file_id, "status": f.status.value},
            )
        indexed = await mgr.index_file(kb_id, file_id)
    except KnowledgeFileError as exc:
        _raise_knowledge_file_error(exc)
    except Exception as exc:
        logger.exception("Process failed for file %s", file_id)
        raise HTTPException(status_code=500, detail=_state_error_detail(exc)) from exc
    return {"parsed": parsed.to_dict(), "indexed": indexed.to_dict()}


@router.post("/{kb_id}/files/{file_id}/process-async", summary="Queue parse and index for one file")
async def process_file_async(kb_id: str, file_id: str):
    if await _prod_kb(kb_id):
        f = await _prod_service().get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        if f.status.value in {"parsing", "indexing", "graphing", "indexed", "graph_indexed"}:
            return {"job": None, "file": f.to_dict(), "message": f"File is already {f.status.value}."}
        job = await _prod_service().create_job(kb_id, file_id, "ingest")
        return {"task": job, "job": job, "file": f.to_dict()}
    if await _is_local_wiki_kb(kb_id):
        mgr, _ = _kb_or_404(kb_id)
        f = mgr.get_file(kb_id, file_id)
        if f is None:
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
        if f"{kb_id}:{file_id}" in _ACTIVE_INGESTION_FILES:
            return {"job": None, "file": f.to_dict(), "message": "File is already being processed."}
        if f.status.value in {"parsing", "indexing", "graphing", "indexed", "graph_indexed"}:
            return {"job": None, "file": f.to_dict(), "message": f"File is already {f.status.value}."}
        task = _queue_ingestion(kb_id, [file_id])
        return {"task": task.to_dict(), "job": task.to_dict(), "file": f.to_dict()}
    if _prod_enabled():
        raise _legacy_read_only_error(kb_id)
    mgr, _ = _kb_or_404(kb_id)
    f = mgr.get_file(kb_id, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail=f"File not found: {file_id}")
    if f"{kb_id}:{file_id}" in _ACTIVE_INGESTION_FILES:
        return {"job": None, "file": f.to_dict(), "message": "File is already being processed."}
    if f.status.value in {"parsing", "indexing", "graphing", "indexed", "graph_indexed"}:
        return {"job": None, "file": f.to_dict(), "message": f"File is already {f.status.value}."}
    task = _queue_ingestion(kb_id, [file_id])
    return {"task": task.to_dict(), "job": task.to_dict(), "file": f.to_dict()}


@router.post("/{kb_id}/search", summary="Semantic search in a knowledge base")
async def search(kb_id: str, req: SearchRequest):
    prod_kb = await _prod_kb(kb_id)
    if prod_kb:
        mgr = None
        kb = prod_kb
    else:
        if _prod_enabled() and not await _is_local_wiki_kb(kb_id):
            raise _legacy_read_only_error(kb_id)
        mgr, kb = _kb_or_404(kb_id)
    mode = _mode_for_request(req, kb.kb_type.value)
    try:
        from nexagent.knowledge.search_service import structured_retrieve

        search_result = await structured_retrieve(
            query=req.query,
            kb_ids=[kb_id],
            mode=mode,
            top_k=req.top_k,
            timeout_s=SEARCH_TIMEOUT_SECONDS,
            **_search_kwargs(req),
        )
    except HTTPException:
        raise
    except TimeoutError:
        if mgr is None:
            raise HTTPException(
                status_code=503,
                detail=_search_error_detail("search_timeout", f"Search timeout after {SEARCH_TIMEOUT_SECONDS}s"),
            )
        return _fallback_or_raise_search_response(
            mgr,
            kb,
            kb_id,
            req,
            mode,
            f"Search timeout after {SEARCH_TIMEOUT_SECONDS}s",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        if mgr is None:
            code = _search_error_code(str(exc))
            raise HTTPException(status_code=_search_status_code(code), detail=_search_error_detail(code, str(exc)))
        return _fallback_or_raise_search_response(mgr, kb, kb_id, req, mode, str(exc))
    except Exception as exc:
        logger.exception("Search failed in KB %s", kb_id)
        if mgr is None:
            code = _search_error_code(str(exc))
            raise HTTPException(status_code=_search_status_code(code), detail=_search_error_detail(code, str(exc)))
        return _fallback_or_raise_search_response(mgr, kb, kb_id, req, mode, str(exc))
    if search_result.error_code and not search_result.chunks:
        if mgr is None:
            raise HTTPException(
                status_code=_search_status_code(search_result.error_code),
                detail=_search_error_detail(search_result.error_code, search_result.error),
            )
        _raise_structured_search_error(mgr, kb_id, search_result.error)
    return _structured_search_payload(
        req=req,
        mode=mode,
        search_result=search_result,
        kb_ids=[kb_id],
        kb_id=kb_id,
        kb_type=kb.kb_type.value,
    )


@router.get("/{kb_id}/graph/stats", summary="Knowledge graph statistics")
async def graph_stats(kb_id: str):
    if await _prod_kb(kb_id):
        return await _prod_service().graph_stats(kb_id)
    if _prod_enabled():
        return {"nodes": 0, "edges": 0, "degraded": True, "error_code": "legacy_graph_unavailable"}
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.graph_stats(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/graph/summary", summary="Knowledge graph summary")
async def graph_summary(kb_id: str):
    if await _prod_kb(kb_id):
        return await _prod_service().graph_summary(kb_id)
    if _prod_enabled():
        return {
            "kb_id": kb_id,
            "status": "legacy",
            "entity_count": 0,
            "relation_count": 0,
            "degraded": True,
            "warnings": [{"code": "legacy_graph_unavailable", "message": "Legacy local KB does not expose production semantic graph.", "action": "create_production_kb"}],
        }
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.graph_summary(kb_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/graph/search", summary="Search graph entities")
async def graph_search(kb_id: str, q: str = Query(default=""), limit: int = Query(default=20, ge=1, le=100)):
    if await _prod_kb(kb_id):
        return await _prod_service().search_graph(kb_id, query=q, limit=limit)
    if _prod_enabled():
        return {"nodes": [], "edges": [], "total": 0, "degraded": True, "error_code": "legacy_graph_unavailable"}
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.search_graph(kb_id, query=q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/graph/subgraph", summary="Graph subgraph around an entity")
async def graph_subgraph(
    kb_id: str,
    node_id: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=3),
    limit: int = Query(default=80, ge=1, le=300),
):
    if await _prod_kb(kb_id):
        return await _prod_service().graph_subgraph(kb_id, node_id=node_id, depth=depth, limit=limit)
    if _prod_enabled():
        return {"nodes": [], "edges": [], "center": node_id, "degraded": True, "error_code": "legacy_graph_unavailable"}
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.graph_subgraph(kb_id, node_id=node_id, depth=depth, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{kb_id}/graph", summary="Export knowledge graph")
async def export_graph(kb_id: str, limit: int = Query(default=200, ge=1, le=1000)):
    if await _prod_kb(kb_id):
        return await _prod_service().export_graph(kb_id, limit=limit)
    if _prod_enabled():
        return {
            "kb_id": kb_id,
            "nodes": [],
            "edges": [],
            "stats": {"nodes": 0, "edges": 0},
            "degraded": True,
            "warnings": [{"code": "legacy_graph_unavailable", "message": "Legacy local KB is read-only and has no production semantic graph.", "action": "create_production_kb"}],
            "error_code": "legacy_graph_unavailable",
        }
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.export_graph(kb_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{kb_id}/graph/upload", summary="Import existing graph data")
async def upload_graph(kb_id: str, req: GraphUploadRequest):
    if _prod_enabled():
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "manual_graph_import_disabled",
                "message": "Production graph data is built by LightRAG/Neo4j jobs, not manual fallback imports.",
                "action": "rebuild_graph",
            },
        )
    mgr, _ = _kb_or_404(kb_id)
    try:
        return mgr.import_graph(
            kb_id,
            {"nodes": req.nodes, "edges": req.edges},
            source=req.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
