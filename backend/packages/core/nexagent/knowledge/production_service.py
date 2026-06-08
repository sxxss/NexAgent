"""Postgres/MinIO backed production knowledge service.

This service is the production path behind ``NEXAGENT_KB_STORAGE=postgres``.
It intentionally reuses the existing parser, chunking, Milvus and LightRAG
adapters, but moves lifecycle metadata and artifacts out of local JSON files.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from nexagent.config import get_config
from nexagent.db.models import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeFileRecord,
    KnowledgeGraphManifest,
    KnowledgeIndexManifest,
    KnowledgeJobRecord,
)
from nexagent.db.session import AsyncSessionLocal
from nexagent.knowledge.base import (
    KnowledgeFileError,
    _sanitize_upload_filename,
    _validate_upload_content,
)
from nexagent.knowledge.chunking import Chunk, chunk_markdown, resolve_chunk_processing_params
from nexagent.knowledge.models import EmbedInfo, FileMeta, FileStatus, KBMeta, KBType, LLMInfo, SearchResult
from nexagent.storage.object_store import get_object_store

PRODUCTION_JOB_QUEUE = "nexagent:knowledge:jobs"
MILVUS_SCHEMA_VERSION = "dense_bm25_v1"


def production_enabled() -> bool:
    return os.environ.get("NEXAGENT_KB_STORAGE", get_config().knowledge.storage_backend).lower() in {
        "postgres",
        "production",
        "prod",
    }


class ProductionKnowledgeService:
    def __init__(self) -> None:
        self._object_store = None

    @property
    def object_store(self):
        if self._object_store is None:
            self._object_store = get_object_store()
        return self._object_store

    async def list_kbs(self) -> list[KBMeta]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.created_at.desc()))
            return [_record_to_kb_meta(record) for record in result.scalars().all()]

    async def get_kb(self, kb_id: str) -> KBMeta | None:
        async with AsyncSessionLocal() as session:
            record = await session.get(KnowledgeBaseRecord, kb_id)
            return _record_to_kb_meta(record) if record else None

    async def create_kb(
        self,
        *,
        name: str,
        description: str = "",
        kb_type: str = "milvus",
        embed_info: EmbedInfo | None = None,
        llm_info: LLMInfo | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        chunk_preset_id: str = "general",
        chunk_parser_config: dict | None = None,
    ) -> KBMeta:
        from nexagent.knowledge.chunking import normalize_chunk_preset_id
        from nexagent.knowledge.manager import _default_embed_info, _default_llm_info

        kb_id = str(uuid.uuid4())
        record = KnowledgeBaseRecord(
            id=kb_id,
            name=name,
            description=description,
            kb_type=KBType(kb_type).value,
            status="ready",
            chunk_size=max(64, int(chunk_size)),
            chunk_overlap=max(0, int(chunk_overlap)),
            chunk_preset_id=normalize_chunk_preset_id(chunk_preset_id),
        )
        record.chunk_parser_config = chunk_parser_config or {}
        record.embed_info = (embed_info or _default_embed_info()).to_dict()
        record.llm_info = (llm_info or _default_llm_info()).to_dict()
        record.extra = {"storage": "postgres_minio", "legacy": False}
        async with AsyncSessionLocal() as session:
            session.add(record)
            await session.commit()
        return _record_to_kb_meta(record)

    async def delete_kb(self, kb_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.kb_id == kb_id))
            await session.execute(delete(KnowledgeFileRecord).where(KnowledgeFileRecord.kb_id == kb_id))
            await session.execute(delete(KnowledgeJobRecord).where(KnowledgeJobRecord.kb_id == kb_id))
            await session.execute(delete(KnowledgeIndexManifest).where(KnowledgeIndexManifest.kb_id == kb_id))
            await session.execute(delete(KnowledgeGraphManifest).where(KnowledgeGraphManifest.kb_id == kb_id))
            record = await session.get(KnowledgeBaseRecord, kb_id)
            if record:
                await session.delete(record)
            await session.commit()

    async def update_model_config(self, kb_id: str, patch: dict) -> dict:
        async with AsyncSessionLocal() as session:
            kb = await _require_kb_record(session, kb_id)
            embed = dict(kb.embed_info or {})
            for src, dst in {
                "embed_model": "model",
                "embed_base_url": "base_url",
                "embed_api_key": "api_key",
                "embed_dimension": "dimension",
            }.items():
                if src in patch and patch[src] is not None:
                    embed[dst] = patch[src]
            kb.embed_info = embed
            extra = dict(kb.extra or {})
            extra["requires_reindex"] = True
            if "use_reranker" in patch:
                extra["use_reranker"] = patch["use_reranker"]
            if "reranker_model" in patch:
                extra["reranker_model"] = patch["reranker_model"]
            kb.extra = extra
            await session.commit()
            return _record_to_kb_meta(kb).to_dict()

    async def update_chunk_config(self, kb_id: str, patch: dict) -> dict:
        from nexagent.knowledge.chunking import normalize_chunk_preset_id

        async with AsyncSessionLocal() as session:
            kb = await _require_kb_record(session, kb_id)
            if "chunk_size" in patch and patch["chunk_size"] is not None:
                kb.chunk_size = int(patch["chunk_size"])
            if "chunk_overlap" in patch and patch["chunk_overlap"] is not None:
                kb.chunk_overlap = int(patch["chunk_overlap"])
            if "chunk_preset_id" in patch and patch["chunk_preset_id"]:
                kb.chunk_preset_id = normalize_chunk_preset_id(str(patch["chunk_preset_id"]))
            if "chunk_parser_config" in patch and patch["chunk_parser_config"] is not None:
                kb.chunk_parser_config = dict(patch["chunk_parser_config"])
            extra = dict(kb.extra or {})
            extra["requires_reindex"] = True
            kb.extra = extra
            await session.commit()
            return {
                "kb_id": kb_id,
                "chunk_size": kb.chunk_size,
                "chunk_overlap": kb.chunk_overlap,
                "chunk_preset_id": kb.chunk_preset_id,
                "chunk_parser_config": kb.chunk_parser_config or {},
                "requires_reindex": True,
            }

    async def add_file(self, kb_id: str, filename: str, content: bytes) -> FileMeta:
        safe_name = _sanitize_upload_filename(filename)
        _validate_upload_content(content, safe_name)
        checksum = hashlib.sha256(content).hexdigest()
        mime_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        now = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        object_name = f"{kb_id}/raw/{now}-{uuid.uuid4().hex}-{safe_name}"
        cfg = get_config().knowledge
        write = self.object_store.put_bytes(cfg.raw_bucket, object_name, content, content_type=mime_type)

        file_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as session:
            kb = await session.get(KnowledgeBaseRecord, kb_id)
            if kb is None:
                raise KeyError(f"Knowledge base not found: {kb_id}")
            record = KnowledgeFileRecord(
                id=file_id,
                kb_id=kb_id,
                filename=safe_name,
                mime_type=mime_type,
                checksum=checksum,
                file_size=len(content),
                raw_uri=write.uri,
                status=FileStatus.UPLOADED.value,
            )
            record.processing_params = resolve_chunk_processing_params(
                {
                    "chunk_preset_id": kb.chunk_preset_id,
                    "chunk_parser_config": kb.chunk_parser_config or {},
                    "chunk_size": kb.chunk_size,
                    "chunk_overlap": kb.chunk_overlap,
                }
            )
            record.parse_metadata = {"object_store_degraded": write.degraded}
            session.add(record)
            await session.commit()
        return _record_to_file_meta(record)

    async def list_files(self, kb_id: str) -> list[FileMeta]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KnowledgeFileRecord)
                .where(KnowledgeFileRecord.kb_id == kb_id)
                .order_by(KnowledgeFileRecord.created_at.desc())
            )
            return [_record_to_file_meta(record) for record in result.scalars().all()]

    async def get_file(self, kb_id: str, file_id: str) -> FileMeta | None:
        async with AsyncSessionLocal() as session:
            record = await session.get(KnowledgeFileRecord, file_id)
            if not record or record.kb_id != kb_id:
                return None
            return _record_to_file_meta(record)

    async def delete_file(self, kb_id: str, file_id: str) -> None:
        async with AsyncSessionLocal() as session:
            record = await _require_file_record(session, kb_id, file_id)
            await session.execute(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.file_id == file_id))
            await session.delete(record)
            await session.commit()

    async def parsed_content(self, kb_id: str, file_id: str) -> str:
        async with AsyncSessionLocal() as session:
            record = await _require_file_record(session, kb_id, file_id)
            if not record.parsed_uri:
                raise KnowledgeFileError(
                    "file_not_parsed",
                    "File has not been parsed yet.",
                    status_code=409,
                    details={"file_id": file_id},
                )
            uri = record.parsed_uri
        return self.object_store.get_bytes(uri).decode("utf-8", errors="replace")

    async def parse_file(self, kb_id: str, file_id: str) -> FileMeta:
        from nexagent.knowledge.parser import parse_document_structured

        async with AsyncSessionLocal() as session:
            record = await _require_file_record(session, kb_id, file_id)
            if record.status not in {FileStatus.UPLOADED.value, FileStatus.PARSE_ERROR.value, "error_parsing"}:
                raise _invalid_state(file_id, record.status, ["uploaded", "parse_error", "error_parsing"])
            record.status = FileStatus.PARSING.value
            record.error_code = ""
            record.error_message = ""
            await session.commit()

        raw = self.object_store.get_bytes(record.raw_uri)
        suffix = Path(record.filename).suffix or ".bin"
        try:
            with tempfile.TemporaryDirectory(prefix="nexagent-parse-") as tmp:
                path = Path(tmp) / record.filename
                path.write_bytes(raw)
                parsed = await parse_document_structured(str(path))
            markdown = parsed.content or ""
            parsed_object = f"{kb_id}/parsed/{file_id}.md"
            cfg = get_config().knowledge
            write = self.object_store.put_bytes(cfg.parsed_bucket, parsed_object, markdown.encode("utf-8"), "text/markdown")
            async with AsyncSessionLocal() as session:
                updated = await _require_file_record(session, kb_id, file_id)
                updated.parsed_uri = write.uri
                updated.parse_metadata = {
                    **(parsed.metadata or {}),
                    "table_count": len(parsed.tables),
                    "image_count": len(parsed.images),
                    "object_store_degraded": write.degraded,
                    "source_suffix": suffix,
                }
                updated.status = FileStatus.PARSED.value
                updated.error_code = ""
                updated.error_message = ""
                await session.commit()
                return _record_to_file_meta(updated)
        except Exception as exc:
            async with AsyncSessionLocal() as session:
                failed = await _require_file_record(session, kb_id, file_id)
                failed.status = FileStatus.PARSE_ERROR.value
                failed.error_code = "error_parsing"
                failed.error_message = str(exc)
                await session.commit()
                return _record_to_file_meta(failed)

    async def index_file(self, kb_id: str, file_id: str) -> FileMeta:
        async with AsyncSessionLocal() as session:
            kb = await _require_kb_record(session, kb_id)
            record = await _require_file_record(session, kb_id, file_id)
            allowed = {
                FileStatus.PARSED.value,
                FileStatus.INDEX_ERROR.value,
                "error_indexing",
                FileStatus.INDEXED.value,
                FileStatus.GRAPH_ERROR.value,
                FileStatus.INDEXED_WITH_GRAPH_DEGRADED.value,
                FileStatus.GRAPH_INDEXED.value,
            }
            if record.status not in allowed:
                raise _invalid_state(file_id, record.status, sorted(allowed))
            record.status = FileStatus.INDEXING.value
            record.error_code = ""
            record.error_message = ""
            await session.commit()

        try:
            markdown = self.object_store.get_bytes(record.parsed_uri).decode("utf-8", errors="replace")
            params = resolve_chunk_processing_params(
                {
                    "chunk_preset_id": kb.chunk_preset_id,
                    "chunk_parser_config": kb.chunk_parser_config or {},
                    "chunk_size": kb.chunk_size,
                    "chunk_overlap": kb.chunk_overlap,
                },
                record.processing_params or {},
            )
            raw_chunks = chunk_markdown(markdown, file_id=file_id, filename=record.filename, processing_params=params)
            chunks = [_stable_chunk(kb_id, file_id, record.filename, raw, index) for index, raw in enumerate(raw_chunks)]
            manifest = {
                "kb_id": kb_id,
                "file_id": file_id,
                "chunk_count": len(chunks),
                "processing_params": params,
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": chunk.chunk_index,
                        "source": chunk.source,
                        "metadata": chunk.metadata,
                    }
                    for chunk in chunks
                ],
            }
            cfg = get_config().knowledge
            manifest_uri = self.object_store.put_bytes(
                cfg.chunks_bucket,
                f"{kb_id}/chunks/{file_id}.json",
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json",
            ).uri
            await self._replace_db_chunks(kb_id, file_id, chunks, manifest_uri)

            kb_meta = _record_to_kb_meta(kb)
            tmp_file = _record_to_file_meta(record)
            status = FileStatus.INDEXED.value
            index_manifest = {"status": "unavailable", "error_code": "", "error_message": ""}
            graph_manifest = {"status": "unavailable", "error_code": "", "error_message": ""}
            if kb.kb_type == KBType.MILVUS.value:
                index_manifest = await self._index_milvus(kb_meta, tmp_file, chunks)
                status = FileStatus.INDEXED.value if index_manifest["status"] == "ready" else FileStatus.INDEXED_WITH_GRAPH_DEGRADED.value
            else:
                graph_manifest = await self._index_lightrag(kb_meta, tmp_file, markdown)
                status = FileStatus.GRAPH_INDEXED.value if graph_manifest["status"] == "ready" else FileStatus.INDEXED_WITH_GRAPH_DEGRADED.value

            async with AsyncSessionLocal() as session:
                updated = await _require_file_record(session, kb_id, file_id)
                updated.status = status
                updated.chunk_count = len(chunks)
                updated.chunk_manifest_uri = manifest_uri
                updated.processing_params = params
                updated.error_code = "" if status in {FileStatus.INDEXED.value, FileStatus.GRAPH_INDEXED.value} else "degraded_index"
                updated.error_message = "" if not updated.error_code else "Index completed with degraded production backend."
                await _upsert_index_manifest(session, kb_meta, index_manifest)
                await _upsert_graph_manifest(session, kb_meta, graph_manifest)
                await session.commit()
                return _record_to_file_meta(updated)
        except Exception as exc:
            async with AsyncSessionLocal() as session:
                failed = await _require_file_record(session, kb_id, file_id)
                failed.status = FileStatus.INDEX_ERROR.value
                failed.error_code = "error_indexing"
                failed.error_message = str(exc)
                await session.commit()
                return _record_to_file_meta(failed)

    async def reparse_file(self, kb_id: str, file_id: str) -> FileMeta:
        async with AsyncSessionLocal() as session:
            record = await _require_file_record(session, kb_id, file_id)
            record.status = FileStatus.PARSE_ERROR.value
            record.parsed_uri = ""
            record.chunk_manifest_uri = ""
            record.chunk_count = 0
            await session.execute(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.file_id == file_id))
            await session.commit()
        return await self.parse_file(kb_id, file_id)

    async def reindex_file(self, kb_id: str, file_id: str) -> FileMeta:
        async with AsyncSessionLocal() as session:
            record = await _require_file_record(session, kb_id, file_id)
            record.status = FileStatus.INDEX_ERROR.value
            await session.commit()
        return await self.index_file(kb_id, file_id)

    async def rebuild_graph_file(self, kb_id: str, file_id: str) -> FileMeta:
        return await self.reindex_file(kb_id, file_id)

    async def create_job(self, kb_id: str, file_id: str | None, job_type: str = "ingest") -> dict:
        job = KnowledgeJobRecord(kb_id=kb_id, file_id=file_id, job_type=job_type, status="queued", current_step="queued")
        job.input_snapshot = {"kb_id": kb_id, "file_id": file_id, "job_type": job_type}
        job.logs = []
        async with AsyncSessionLocal() as session:
            session.add(job)
            await session.commit()
        await _push_redis_job(job.id)
        return _job_to_dict(job)

    async def run_job(self, job_id: str) -> dict:
        async with AsyncSessionLocal() as session:
            job = await session.get(KnowledgeJobRecord, job_id)
            if not job:
                raise KeyError(f"Knowledge job not found: {job_id}")
            job.status = "running"
            job.progress = 5
            job.current_step = "starting"
            job.logs = [*_list(job.logs), _job_log("starting", "Job started.")]
            await session.commit()

        try:
            if job.job_type in {"ingest", "process"} and job.file_id:
                file_meta = await self.get_file(job.kb_id, job.file_id)
                if file_meta and file_meta.status in {FileStatus.UPLOADED, FileStatus.PARSE_ERROR}:
                    await self._job_progress(job.id, 25, "parsing", "Parsing file.")
                    await self.parse_file(job.kb_id, job.file_id)
                await self._job_progress(job.id, 65, "indexing", "Indexing file.")
                updated = await self.index_file(job.kb_id, job.file_id)
                await self._job_done(job.id, {"file": updated.to_dict()})
            elif job.job_type == "reparse" and job.file_id:
                updated = await self.reparse_file(job.kb_id, job.file_id)
                await self._job_done(job.id, {"file": updated.to_dict()})
            elif job.job_type in {"reindex", "rebuild_graph"} and job.file_id:
                updated = await self.reindex_file(job.kb_id, job.file_id)
                await self._job_done(job.id, {"file": updated.to_dict()})
            else:
                raise ValueError(f"Unsupported knowledge job: {job.job_type}")
        except Exception as exc:
            await self._job_failed(job.id, "job_failed", str(exc))
        return await self.get_job(job_id) or {}

    async def get_job(self, job_id: str) -> dict | None:
        async with AsyncSessionLocal() as session:
            job = await session.get(KnowledgeJobRecord, job_id)
            return _job_to_dict(job) if job else None

    async def list_jobs(self, kb_id: str, limit: int = 50) -> list[dict]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KnowledgeJobRecord)
                .where(KnowledgeJobRecord.kb_id == kb_id)
                .order_by(KnowledgeJobRecord.created_at.desc())
                .limit(limit)
            )
            return [_job_to_dict(job) for job in result.scalars().all()]

    async def search(self, kb_id: str, query: str, top_k: int = 10, **kwargs) -> list[SearchResult]:
        kb_meta = await self.get_kb(kb_id)
        if not kb_meta:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        try:
            if kb_meta.kb_type == KBType.MILVUS:
                from nexagent.knowledge.implementations.milvus_kb import MilvusKB

                return await MilvusKB(work_dir=str(_prod_work_dir() / "milvus"))._do_search(
                    query, kb_meta, top_k=top_k, **kwargs
                )
            from nexagent.knowledge.implementations.lightrag_kb import LightRagKB

            return await LightRagKB(work_dir=str(_prod_work_dir() / "lightrag"))._do_search(
                query, kb_meta, top_k=top_k, **kwargs
            )
        except Exception as exc:
            return await self._db_lexical_search(kb_id, query, top_k, str(exc))

    async def list_indexed_chunks(self, kb_id: str, limit: int = 1000) -> list[dict]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KnowledgeChunkRecord)
                .where(KnowledgeChunkRecord.kb_id == kb_id)
                .order_by(KnowledgeChunkRecord.updated_at.desc())
                .limit(limit)
            )
            return [_chunk_to_dict(row) for row in result.scalars().all()]

    async def diagnostics(self, kb_id: str) -> dict:
        async with AsyncSessionLocal() as session:
            kb = await _require_kb_record(session, kb_id)
            files = (
                await session.execute(select(KnowledgeFileRecord).where(KnowledgeFileRecord.kb_id == kb_id))
            ).scalars().all()
            index = (
                await session.execute(select(KnowledgeIndexManifest).where(KnowledgeIndexManifest.kb_id == kb_id))
            ).scalars().first()
            graph = (
                await session.execute(select(KnowledgeGraphManifest).where(KnowledgeGraphManifest.kb_id == kb_id))
            ).scalars().first()
        status_counts: dict[str, int] = {}
        for file in files:
            status_counts[file.status] = status_counts.get(file.status, 0) + 1
        issues = []
        if index and index.status != "ready":
            issues.append(f"Vector index is {index.status}: {index.error_message or index.error_code}")
        if kb.kb_type == KBType.LIGHTRAG.value and graph and graph.status != "ready":
            issues.append(f"Semantic graph is {graph.status}: {graph.error_message or graph.error_code}")
        return {
            "kb_id": kb_id,
            "kb_type": kb.kb_type,
            "status": "warning" if issues else "ok",
            "storage": "postgres_minio",
            "object_store": self.object_store.status(),
            "status_counts": status_counts,
            "index_manifest": _manifest_to_dict(index),
            "graph_manifest": _manifest_to_dict(graph),
            "files": [_record_to_file_meta(file).to_dict() for file in files],
            "issues": issues,
        }

    async def backend_status(self) -> dict:
        return {
            "mode": "production",
            "storage": "postgres_minio",
            "object_store": self.object_store.status(),
            "queue": {"backend": "redis", "url": os.environ.get("REDIS_URL", "redis://localhost:6379/0")},
        }

    async def graph_stats(self, kb_id: str) -> dict:
        data = await self.export_graph(kb_id, limit=1000)
        return data.get("stats") or {"nodes": len(data.get("nodes", [])), "edges": len(data.get("edges", []))}

    async def graph_summary(self, kb_id: str) -> dict:
        async with AsyncSessionLocal() as session:
            graph = (
                await session.execute(select(KnowledgeGraphManifest).where(KnowledgeGraphManifest.kb_id == kb_id))
            ).scalars().first()
            files = (
                await session.execute(select(KnowledgeFileRecord).where(KnowledgeFileRecord.kb_id == kb_id))
            ).scalars().all()
        return {
            "kb_id": kb_id,
            "status": graph.status if graph else "unavailable",
            "entity_count": int(getattr(graph, "node_count", 0) or 0) if graph else 0,
            "relation_count": int(getattr(graph, "edge_count", 0) or 0) if graph else 0,
            "file_count": len(files),
            "degraded": bool(graph and graph.status != "ready"),
            "warnings": []
            if graph and graph.status == "ready"
            else [{"code": "semantic_graph_unavailable", "message": "Neo4j/LightRAG semantic graph is not ready.", "action": "rebuild_graph"}],
        }

    async def search_graph(self, kb_id: str, query: str, limit: int = 20) -> dict:
        data = await self.export_graph(kb_id, limit=1000)
        q = query.lower().strip()
        nodes = [
            node
            for node in data.get("nodes", [])
            if not q or q in str(node.get("name", "")).lower() or q in str(node.get("description", "")).lower()
        ][:limit]
        return {**data, "nodes": nodes, "edges": [], "total": len(nodes), "query": query}

    async def graph_subgraph(self, kb_id: str, node_id: str, depth: int = 1, limit: int = 120) -> dict:
        data = await self.export_graph(kb_id, limit=1000)
        node_ids = {node_id}
        edges = []
        for _ in range(max(depth, 1)):
            for edge in data.get("edges", []):
                if edge.get("source") in node_ids or edge.get("target") in node_ids:
                    edges.append(edge)
                    node_ids.add(str(edge.get("source")))
                    node_ids.add(str(edge.get("target")))
                if len(node_ids) >= limit:
                    break
        nodes = [node for node in data.get("nodes", []) if node.get("id") in node_ids][:limit]
        edge_ids = {edge.get("id") for edge in edges}
        return {**data, "nodes": nodes, "edges": [edge for edge in edges if edge.get("id") in edge_ids], "center": node_id}

    async def export_graph(self, kb_id: str, limit: int = 200) -> dict:
        from nexagent.knowledge.neo4j_store import Neo4jGraphStore

        try:
            data = Neo4jGraphStore().export_kb(kb_id, limit=limit)
            data.update({"kb_id": kb_id, "kb_type": "lightrag", "degraded": False, "warnings": [], "error_code": ""})
            return data
        except Exception as exc:
            return {
                "kb_id": kb_id,
                "kb_type": "lightrag",
                "nodes": [],
                "edges": [],
                "stats": {"nodes": 0, "edges": 0, "files": []},
                "degraded": True,
                "warnings": [{"code": "semantic_graph_unavailable", "message": str(exc), "action": "start_neo4j_rebuild_graph"}],
                "error_code": "semantic_graph_unavailable",
            }

    async def _replace_db_chunks(self, kb_id: str, file_id: str, chunks: list[Chunk], manifest_uri: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(KnowledgeChunkRecord).where(KnowledgeChunkRecord.file_id == file_id))
            for chunk in chunks:
                record = KnowledgeChunkRecord(
                    chunk_id=chunk.chunk_id,
                    kb_id=kb_id,
                    file_id=file_id,
                    chunk_index=chunk.chunk_index,
                    source=chunk.source,
                    content=chunk.content,
                    content_hash=chunk.metadata.get("content_hash", ""),
                    manifest_uri=manifest_uri,
                )
                record.chunk_metadata = chunk.metadata
                session.add(record)
            await session.commit()

    async def _index_milvus(self, kb_meta: KBMeta, file_meta: FileMeta, chunks: list[Chunk]) -> dict:
        try:
            from nexagent.knowledge.implementations.milvus_kb import MilvusKB, _collection_name

            await MilvusKB(work_dir=str(_prod_work_dir() / "milvus"))._insert_milvus_chunks(kb_meta, file_meta, chunks)
            return {
                "status": "ready",
                "collection_name": _collection_name(kb_meta.kb_id),
                "schema_version": MILVUS_SCHEMA_VERSION,
                "error_code": "",
                "error_message": "",
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "collection_name": "",
                "schema_version": MILVUS_SCHEMA_VERSION,
                "error_code": "milvus_unavailable",
                "error_message": str(exc),
            }

    async def _index_lightrag(self, kb_meta: KBMeta, file_meta: FileMeta, markdown: str) -> dict:
        try:
            from nexagent.knowledge.implementations.lightrag_kb import LightRagKB

            backend = LightRagKB(work_dir=str(_prod_work_dir() / "lightrag"))
            status = await backend._try_lightrag_insert(kb_meta, markdown, file_meta)
            if status.get("status") != "ok":
                raise RuntimeError(status.get("reason") or status.get("status") or "LightRAG unavailable")
            return {"status": "ready", "error_code": "", "error_message": "", "node_count": 0, "edge_count": 0}
        except Exception as exc:
            return {
                "status": "degraded",
                "error_code": "semantic_graph_unavailable",
                "error_message": str(exc),
                "node_count": 0,
                "edge_count": 0,
            }

    async def _db_lexical_search(self, kb_id: str, query: str, top_k: int, reason: str) -> list[SearchResult]:
        terms = [item.lower() for item in query.split() if item.strip()]
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(KnowledgeChunkRecord).where(KnowledgeChunkRecord.kb_id == kb_id))
            rows = result.scalars().all()
        scored = []
        for row in rows:
            content = row.content or ""
            lowered = content.lower()
            score = sum(lowered.count(term) for term in terms) if terms else 0
            if score or not terms:
                scored.append((score or 0.01, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchResult(
                content=row.content,
                score=float(score),
                source=row.source,
                file_id=row.file_id,
                metadata={
                    "chunk_id": row.chunk_id,
                    "chunk_index": row.chunk_index,
                    "degraded": True,
                    "degraded_reason": "production_db_lexical_fallback",
                    "degraded_message": f"Production index fallback used: {reason}",
                    "action": "check_milvus_or_graph_backend",
                },
            )
            for score, row in scored[:top_k]
        ]

    async def _job_progress(self, job_id: str, progress: float, step: str, message: str) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(KnowledgeJobRecord, job_id)
            if not job:
                return
            job.progress = progress
            job.current_step = step
            job.logs = [*_list(job.logs), _job_log(step, message)]
            await session.commit()

    async def _job_done(self, job_id: str, result: dict) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(KnowledgeJobRecord, job_id)
            if not job:
                return
            job.status = "succeeded"
            job.progress = 100
            job.current_step = "done"
            job.result = result
            job.logs = [*_list(job.logs), _job_log("done", "Job completed.")]
            await session.commit()

    async def _job_failed(self, job_id: str, code: str, message: str) -> None:
        async with AsyncSessionLocal() as session:
            job = await session.get(KnowledgeJobRecord, job_id)
            if not job:
                return
            job.status = "failed"
            job.error_code = code
            job.error_message = message
            job.current_step = "failed"
            job.logs = [*_list(job.logs), _job_log("failed", message, code)]
            await session.commit()


_PRODUCTION_SERVICE: ProductionKnowledgeService | None = None


def get_production_service() -> ProductionKnowledgeService:
    global _PRODUCTION_SERVICE
    if _PRODUCTION_SERVICE is None:
        _PRODUCTION_SERVICE = ProductionKnowledgeService()
    return _PRODUCTION_SERVICE


def _prod_work_dir() -> Path:
    root = Path(os.environ.get("NEXAGENT_DATA_DIR", str(Path.home() / ".nexagent"))) / "knowledge-production"
    root.mkdir(parents=True, exist_ok=True)
    return root


async def _push_redis_job(job_id: str) -> None:
    try:
        import redis.asyncio as redis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        client = redis.from_url(url, decode_responses=True)
        await client.rpush(PRODUCTION_JOB_QUEUE, job_id)
        await client.aclose()
    except Exception:
        return


def _stable_chunk(kb_id: str, file_id: str, filename: str, raw: dict, index: int) -> Chunk:
    content = str(raw.get("content") or "")
    digest = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
    chunk_id = f"{kb_id}:{file_id}:{index}:{digest[:12]}"
    metadata = dict(raw.get("metadata") or {})
    metadata.update(
        {
            "chunk_id": chunk_id,
            "file_id": file_id,
            "filename": filename,
            "content_hash": digest,
            "chunk_index": index,
        }
    )
    return Chunk(content=content, chunk_index=index, metadata=metadata, chunk_id=chunk_id, source=filename)


async def _require_kb_record(session, kb_id: str) -> KnowledgeBaseRecord:
    record = await session.get(KnowledgeBaseRecord, kb_id)
    if record is None:
        raise KeyError(f"Knowledge base not found: {kb_id}")
    return record


async def _require_file_record(session, kb_id: str, file_id: str) -> KnowledgeFileRecord:
    record = await session.get(KnowledgeFileRecord, file_id)
    if record is None or record.kb_id != kb_id:
        raise KeyError(f"File not found: {file_id}")
    return record


def _record_to_kb_meta(record: KnowledgeBaseRecord) -> KBMeta:
    return KBMeta(
        kb_id=record.id,
        name=record.name,
        description=record.description or "",
        kb_type=KBType(record.kb_type),
        embed_info=EmbedInfo.from_dict(record.embed_info or {}),
        llm_info=LLMInfo.from_dict(record.llm_info or {}),
        chunk_size=record.chunk_size,
        chunk_overlap=record.chunk_overlap,
        chunk_preset_id=record.chunk_preset_id,
        chunk_parser_config=record.chunk_parser_config or {},
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
        extra={**(record.extra or {}), "storage": "postgres_minio", "legacy": bool(record.legacy)},
    )


def _record_to_file_meta(record: KnowledgeFileRecord) -> FileMeta:
    status_aliases = {
        "error_parsing": FileStatus.PARSE_ERROR,
        "error_indexing": FileStatus.INDEX_ERROR,
    }
    status = status_aliases.get(record.status) or FileStatus(record.status)
    return FileMeta(
        file_id=record.id,
        kb_id=record.kb_id,
        filename=record.filename,
        file_path=record.raw_uri,
        file_size=record.file_size,
        status=status,
        parsed_path=record.parsed_uri,
        chunk_count=record.chunk_count,
        error=record.error_message or "",
        parse_metadata=record.parse_metadata or {},
        processing_params=record.processing_params or {},
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


def _chunk_to_dict(row: KnowledgeChunkRecord) -> dict:
    return {
        "chunk_id": row.chunk_id,
        "id": row.chunk_id,
        "kb_id": row.kb_id,
        "file_id": row.file_id,
        "chunk_index": row.chunk_index,
        "source": row.source,
        "content": row.content,
        "metadata": row.chunk_metadata or {},
    }


def _job_to_dict(job: KnowledgeJobRecord | None) -> dict:
    if job is None:
        return {}
    return {
        "task_id": job.id,
        "job_id": job.id,
        "kind": "knowledge_ingestion",
        "kb_id": job.kb_id,
        "file_id": job.file_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": round(float(job.progress or 0), 1),
        "current_step": job.current_step,
        "error_code": job.error_code,
        "error": job.error_message,
        "logs": job.logs or [],
        "result": job.result or {},
        "metadata": {"kb_id": job.kb_id, "file_ids": [job.file_id] if job.file_id else []},
        "created_at": job.created_at.timestamp() if job.created_at else 0,
        "updated_at": job.updated_at.timestamp() if job.updated_at else 0,
    }


def _invalid_state(file_id: str, status: str, allowed: list[str]) -> KnowledgeFileError:
    return KnowledgeFileError(
        "invalid_file_state",
        f"File {file_id} cannot be processed from status {status}.",
        status_code=409,
        details={"file_id": file_id, "status": status, "allowed_statuses": allowed},
    )


async def _upsert_index_manifest(session, kb_meta: KBMeta, data: dict) -> None:
    existing = (
        await session.execute(select(KnowledgeIndexManifest).where(KnowledgeIndexManifest.kb_id == kb_meta.kb_id))
    ).scalars().first()
    record = existing or KnowledgeIndexManifest(kb_id=kb_meta.kb_id)
    record.status = data.get("status", "unavailable")
    record.collection_name = data.get("collection_name", "")
    record.schema_version = data.get("schema_version", MILVUS_SCHEMA_VERSION)
    record.embedding_model = kb_meta.embed_info.model
    record.embedding_dimension = kb_meta.embed_info.dimension
    record.requires_reindex = record.status != "ready"
    record.error_code = data.get("error_code", "")
    record.error_message = data.get("error_message", "")
    record.config_snapshot = {
        "embedding": kb_meta.embed_info.to_dict(),
        "chunk_preset_id": kb_meta.chunk_preset_id,
        "chunk_size": kb_meta.chunk_size,
        "chunk_overlap": kb_meta.chunk_overlap,
    }
    if existing is None:
        session.add(record)


async def _upsert_graph_manifest(session, kb_meta: KBMeta, data: dict) -> None:
    existing = (
        await session.execute(select(KnowledgeGraphManifest).where(KnowledgeGraphManifest.kb_id == kb_meta.kb_id))
    ).scalars().first()
    record = existing or KnowledgeGraphManifest(kb_id=kb_meta.kb_id)
    record.status = data.get("status", "unavailable")
    record.node_count = int(data.get("node_count", 0) or 0)
    record.edge_count = int(data.get("edge_count", 0) or 0)
    record.requires_rebuild = record.status != "ready"
    record.error_code = data.get("error_code", "")
    record.error_message = data.get("error_message", "")
    record.config_snapshot = {"llm": kb_meta.llm_info.to_dict(), "embedding": kb_meta.embed_info.to_dict()}
    if existing is None:
        session.add(record)


def _manifest_to_dict(record) -> dict:
    if record is None:
        return {"status": "unavailable"}
    return {
        "status": record.status,
        "backend": record.backend,
        "requires_reindex": getattr(record, "requires_reindex", False),
        "requires_rebuild": getattr(record, "requires_rebuild", False),
        "error_code": record.error_code,
        "error_message": record.error_message,
        "updated_at": record.updated_at.isoformat() if record.updated_at else "",
    }


def _job_log(step: str, message: str, error_code: str = "") -> dict:
    return {
        "time": datetime.now(UTC).isoformat(),
        "step": step,
        "message": message,
        "error_code": error_code,
    }


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []
