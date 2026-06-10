"""LightRAG knowledge-graph backend with local and Neo4j graph support."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from nexagent.knowledge.base import KnowledgeBase
from nexagent.knowledge.models import FileMeta, FileStatus, KBMeta, KBType, SearchResult

logger = logging.getLogger(__name__)


def _resolve(val: str) -> str:
    if val.startswith("$"):
        return os.environ.get(val[1:], "")
    if not val:
        return os.environ.get("SILICONFLOW_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    return val


class LightRagKB(KnowledgeBase):
    """Knowledge graph RAG backend.

    The backend writes a local JSON graph for deterministic development and
    verification, then attempts to enhance the index with LightRAG and sync the
    graph to Neo4j when those dependencies/services are available.
    """

    @property
    def kb_type(self) -> KBType:
        return KBType.LIGHTRAG

    def _rag_dir(self, kb_meta: KBMeta) -> str:
        path = Path(self.work_dir) / kb_meta.kb_id / "lightrag"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _graph_path(self, kb_meta: KBMeta) -> Path:
        path = Path(self.work_dir) / kb_meta.kb_id / "graph"
        path.mkdir(parents=True, exist_ok=True)
        return path / "graph.json"

    def _get_local_graph(self, kb_meta: KBMeta):
        from nexagent.knowledge.graph_store import LocalGraphStore

        return LocalGraphStore(self._graph_path(kb_meta))

    def _get_rag(self, kb_meta: KBMeta):
        if not hasattr(self, "_rag_cache"):
            self._rag_cache: dict = {}
        if kb_meta.kb_id not in self._rag_cache:
            self._rag_cache[kb_meta.kb_id] = self._build_rag(kb_meta)
        return self._rag_cache[kb_meta.kb_id]

    async def _ensure_rag_initialized(self, kb_meta: KBMeta, rag) -> None:
        if not hasattr(self, "_rag_initialized"):
            self._rag_initialized: set[str] = set()
        if kb_meta.kb_id in self._rag_initialized:
            return
        if hasattr(rag, "initialize_storages"):
            await rag.initialize_storages()
        try:
            from lightrag.kg.shared_storage import initialize_pipeline_status

            await initialize_pipeline_status()
        except Exception as exc:
            logger.debug("LightRAG pipeline status initialization skipped: %s", exc)
        self._rag_initialized.add(kb_meta.kb_id)

    def _build_rag(self, kb_meta: KBMeta):
        try:
            from lightrag import LightRAG
            from lightrag.llm.openai import openai_complete_if_cache, openai_embed
            from lightrag.utils import EmbeddingFunc
        except ImportError as exc:
            raise ImportError(
                "lightrag-hku is required for native LightRAG indexing. "
                "Local graph fallback remains available."
            ) from exc

        llm = kb_meta.llm_info
        embed = kb_meta.embed_info
        llm_api_key = _resolve(llm.api_key)
        embed_api_key = _resolve(embed.api_key)

        async def _llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
            return await openai_complete_if_cache(
                llm.model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=llm_api_key or None,
                base_url=llm.base_url or None,
                **kwargs,
            )

        async def _embed_func(texts: list[str]) -> list[list[float]]:
            return await openai_embed(
                texts,
                model=embed.model,
                api_key=embed_api_key or None,
                base_url=embed.base_url or None,
            )

        language = str(
            (kb_meta.chunk_parser_config or {}).get("language")
            or os.environ.get("SUMMARY_LANGUAGE")
            or "Chinese"
        )
        kwargs = {
            "working_dir": self._rag_dir(kb_meta),
            "workspace": kb_meta.kb_id,
            "llm_model_func": _llm_func,
            "embedding_func": EmbeddingFunc(
                embedding_dim=embed.dimension,
                max_token_size=8192,
                func=_embed_func,
            ),
            "kv_storage": "JsonKVStorage",
            "doc_status_storage": "JsonDocStatusStorage",
            "log_file_path": str(Path(self._rag_dir(kb_meta)) / "lightrag.log"),
            "addon_params": {"language": language},
        }
        try:
            from nexagent.config import get_config

            cfg = get_config().knowledge
            if (
                os.environ.get("NEXAGENT_LIGHTRAG_GRAPH_STORAGE", "neo4j").lower() == "neo4j"
                and cfg.neo4j_uri
                and cfg.neo4j_password
            ):
                os.environ.setdefault("NEO4J_URI", cfg.neo4j_uri)
                os.environ.setdefault("NEO4J_USERNAME", cfg.neo4j_user)
                os.environ.setdefault("NEO4J_USER", cfg.neo4j_user)
                os.environ.setdefault("NEO4J_PASSWORD", cfg.neo4j_password)
                kwargs["graph_storage"] = "Neo4JStorage"
        except Exception:
            pass
        try:
            return LightRAG(**kwargs)
        except TypeError:
            kwargs.pop("workspace", None)
            kwargs.pop("kv_storage", None)
            kwargs.pop("doc_status_storage", None)
            kwargs.pop("graph_storage", None)
            kwargs.pop("log_file_path", None)
            kwargs.pop("addon_params", None)
            return LightRAG(**kwargs)

    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        from nexagent.knowledge.chunking import split_text

        text = Path(file_meta.parsed_path).read_text(encoding="utf-8")
        if not text.strip():
            return 0

        chunks = split_text(
            text,
            kb_meta.chunk_size,
            kb_meta.chunk_overlap,
            chunk_preset_id=kb_meta.chunk_preset_id,
            chunk_parser_config=kb_meta.chunk_parser_config,
            file_id=file_meta.file_id,
            filename=file_meta.filename,
        )
        local_graph = self._get_local_graph(kb_meta)
        entity_mentions = local_graph.add_document(
            text,
            file_id=file_meta.file_id,
            filename=file_meta.filename,
        )

        await self._update_file_status(file_meta.file_id, FileStatus.GRAPHING)
        lightrag_status = await self._try_lightrag_insert(kb_meta, text, file_meta)
        neo4j_status = {"status": "skipped"}
        if os.environ.get("NEXAGENT_DISABLE_NEO4J_SYNC", "0") != "1":
            from nexagent.knowledge.neo4j_store import try_sync_to_neo4j

            neo4j_status = try_sync_to_neo4j(kb_meta.kb_id, local_graph.export(limit=1000))

        kb_meta.extra["graph"] = {
            "local": local_graph.stats(),
            "lightrag": lightrag_status,
            "neo4j": neo4j_status,
            "entity_mentions": entity_mentions,
        }
        logger.info(
            "Indexed graph file %s: %d chunks, %d entity mentions",
            file_meta.file_id,
            len(chunks),
            entity_mentions,
        )
        return len(chunks)

    async def _try_lightrag_insert(self, kb_meta: KBMeta, text: str, file_meta: FileMeta) -> dict:
        if os.environ.get("NEXAGENT_SKIP_NATIVE_LIGHTRAG") == "1":
            return {"status": "skipped", "reason": "NEXAGENT_SKIP_NATIVE_LIGHTRAG=1"}
        try:
            rag = self._get_rag(kb_meta)
            await self._ensure_rag_initialized(kb_meta, rag)
            try:
                await rag.ainsert(input=text, ids=file_meta.file_id, file_paths=file_meta.file_path)
            except TypeError:
                await rag.ainsert(text)
            return {"status": "ok"}
        except Exception as exc:
            if os.environ.get("NEXAGENT_REQUIRE_LIGHTRAG") == "1":
                raise
            logger.info("Native LightRAG indexing skipped for KB %s: %s", kb_meta.kb_id, exc)
            return {"status": "unavailable", "reason": str(exc)}

    def _index_success_status(self, kb_meta: KBMeta, file_meta: FileMeta) -> FileStatus:
        graph = kb_meta.extra.get("graph") or {}
        lightrag = graph.get("lightrag") or {}
        if lightrag.get("status") == "ok":
            return FileStatus.GRAPH_INDEXED
        return FileStatus.INDEXED_WITH_GRAPH_DEGRADED

    async def _do_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        mode: str = "hybrid",
        **kwargs,
    ) -> list[SearchResult]:
        mode = mode if mode in {"naive", "local", "global", "hybrid"} else "hybrid"
        if os.environ.get("NEXAGENT_SKIP_NATIVE_LIGHTRAG") == "1":
            return self._local_graph_search(query, kb_meta, top_k, mode)
        try:
            from lightrag import QueryParam

            rag = self._get_rag(kb_meta)
            await self._ensure_rag_initialized(kb_meta, rag)
            answer = await rag.aquery(query, param=QueryParam(mode=mode, top_k=top_k))
            if answer:
                return [
                    SearchResult(
                        content=str(answer),
                        score=1.0,
                        source="knowledge_graph",
                        file_id="",
                        metadata={"mode": mode, "kb_id": kb_meta.kb_id, "engine": "lightrag"},
                    )
                ]
        except Exception as exc:
            logger.info("Native LightRAG query fallback for KB %s: %s", kb_meta.kb_id, exc)

        return self._local_graph_search(query, kb_meta, top_k, mode)

    def _local_graph_search(self, query: str, kb_meta: KBMeta, top_k: int, mode: str) -> list[SearchResult]:
        graph = self._get_local_graph(kb_meta)
        return [
            SearchResult(
                content=item["content"],
                score=item["score"],
                source="local_knowledge_graph",
                file_id="",
                metadata={**item["metadata"], "mode": mode, "kb_id": kb_meta.kb_id, "engine": "local_graph"},
            )
            for item in graph.search(query, top_k=top_k)
        ]

    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        import shutil

        for folder in ("lightrag", "graph"):
            path = Path(self.work_dir) / kb_meta.kb_id / folder
            if path.exists():
                await asyncio.get_running_loop().run_in_executor(None, shutil.rmtree, str(path))

        try:
            from nexagent.knowledge.neo4j_store import Neo4jGraphStore

            Neo4jGraphStore().delete_kb(kb_meta.kb_id)
        except Exception:
            pass

        if hasattr(self, "_rag_cache"):
            self._rag_cache.pop(kb_meta.kb_id, None)
        if hasattr(self, "_rag_initialized"):
            self._rag_initialized.discard(kb_meta.kb_id)

    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        graph = self._get_local_graph(kb_meta)
        graph.delete_file(file_meta.file_id)
        logger.warning("Native LightRAG per-file deletion is unavailable; local graph entry removed.")

    def graph_stats(self, kb_meta: KBMeta) -> dict:
        graph = self._get_local_graph(kb_meta)
        return {
            "kb_id": kb_meta.kb_id,
            "kb_type": self.kb_type.value,
            "local": graph.stats(),
            "extra": kb_meta.extra.get("graph", {}),
        }

    def export_graph(self, kb_meta: KBMeta, limit: int = 200) -> dict:
        graph = self._get_local_graph(kb_meta)
        data = self._normalize_graph_export(graph.export(limit=limit), kb_meta)
        data["kb_id"] = kb_meta.kb_id
        data["kb_type"] = self.kb_type.value
        data.update(self._graph_runtime_status(kb_meta))
        return data

    def graph_summary(self, kb_meta: KBMeta) -> dict:
        graph = self._get_local_graph(kb_meta)
        stats = graph.stats()
        runtime = self._graph_runtime_status(kb_meta)
        return {
            "kb_id": kb_meta.kb_id,
            "kb_type": self.kb_type.value,
            "stats": stats,
            "relations": ["co_occurs"],
            "updated_at": kb_meta.updated_at,
            **runtime,
        }

    def search_graph(self, kb_meta: KBMeta, query: str, limit: int = 20) -> dict:
        graph = self._get_local_graph(kb_meta)
        query_l = query.lower().strip()
        exported = self._normalize_graph_export(graph.export(limit=1000), kb_meta)
        nodes = [
            node
            for node in exported.get("nodes", [])
            if not query_l or query_l in str(node.get("name", "")).lower()
        ][:limit]
        return {"query": query, "nodes": nodes, "total": len(nodes), **self._graph_runtime_status(kb_meta)}

    def graph_subgraph(self, kb_meta: KBMeta, node_id: str, depth: int = 1, limit: int = 80) -> dict:
        graph = self.export_graph(kb_meta, limit=1000)
        selected = {node_id}
        edges = []
        for _ in range(max(1, min(depth, 3))):
            for edge in graph.get("edges", []):
                if edge.get("source") in selected or edge.get("target") in selected:
                    edges.append(edge)
                    selected.add(str(edge.get("source")))
                    selected.add(str(edge.get("target")))
                if len(edges) >= limit:
                    break
        nodes = [
            node
            for node in graph.get("nodes", [])
            if node.get("id") in selected or node.get("name") in selected
        ][:limit]
        return {
            "node_id": node_id,
            "depth": depth,
            "nodes": nodes,
            "edges": edges[:limit],
            "stats": {"nodes": len(nodes), "edges": len(edges[:limit])},
            **self._graph_runtime_status(kb_meta),
        }

    def _graph_runtime_status(self, kb_meta: KBMeta) -> dict:
        graph = kb_meta.extra.get("graph") or {}
        lightrag = graph.get("lightrag") or {}
        warnings: list[str] = []
        degraded = True
        error_code = "local_co_occurs_graph"
        graph_source = "local_co_occurs_fallback"
        if lightrag.get("status") == "ok":
            warnings.append(
                "Native LightRAG indexing succeeded, but this API export is still using the local graph "
                "projection until semantic graph export is available."
            )
            error_code = "semantic_graph_export_unavailable"
        else:
            reason = lightrag.get("reason") or lightrag.get("status") or "Native LightRAG graph is unavailable."
            warnings.append(f"Using local co-occurrence graph fallback: {reason}")
        return {
            "graph_source": graph_source,
            "warnings": warnings,
            "degraded": degraded,
            "error_code": error_code,
            "diagnostics": {
                "lightrag": lightrag,
                "neo4j": graph.get("neo4j") or {},
                "local": graph.get("local") or {},
            },
        }

    def _normalize_graph_export(self, data: dict, kb_meta: KBMeta) -> dict:
        nodes = []
        for node in data.get("nodes", []):
            name = str(node.get("name") or node.get("id") or "")
            files = [str(item) for item in node.get("files", [])]
            nodes.append(
                {
                    "id": name,
                    "name": name,
                    "entity_type": node.get("entity_type") or "fallback_entity",
                    "description": node.get("description") or "",
                    "count": int(node.get("count") or 0),
                    "source_chunks": node.get("source_chunks") or [],
                    "source_files": files,
                    "files": files,
                }
            )
        edges = []
        for index, edge in enumerate(data.get("edges", [])):
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            relation = str(edge.get("relation") or "co_occurs")
            files = [str(item) for item in edge.get("files", [])]
            edges.append(
                {
                    "id": edge.get("id") or f"{source}:{relation}:{target}:{index}",
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "keywords": edge.get("keywords") or [relation],
                    "weight": float(edge.get("weight") or edge.get("count") or 1),
                    "count": int(edge.get("count") or 0),
                    "description": edge.get("description") or "",
                    "source_chunks": edge.get("source_chunks") or [],
                    "source_files": files,
                    "files": files,
                }
            )
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": data.get("stats") or {"nodes": len(nodes), "edges": len(edges)},
        }

    def import_graph(self, kb_meta: KBMeta, graph_data: dict, source: str = "manual") -> dict:
        graph = self._get_local_graph(kb_meta)
        result = graph.import_graph(graph_data, source=source)
        kb_meta.extra["graph_upload"] = {"source": source, **result}
        if os.environ.get("NEXAGENT_DISABLE_NEO4J_SYNC", "0") != "1":
            try:
                from nexagent.knowledge.neo4j_store import try_sync_to_neo4j

                result["neo4j"] = try_sync_to_neo4j(kb_meta.kb_id, graph.export(limit=1000))
            except Exception as exc:
                result["neo4j"] = {"status": "skipped", "reason": str(exc)}
        return result

    def status(self) -> dict:
        native = "available"
        try:
            import lightrag  # noqa: F401
        except Exception as exc:
            native = f"unavailable: {exc}"

        return {
            "status": "ok",
            "mode": "local_graph_with_optional_lightrag",
            "native_lightrag": native,
            "work_dir": str(self.work_dir),
        }
