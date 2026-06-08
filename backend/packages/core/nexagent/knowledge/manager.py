"""KnowledgeBaseManager — unified interface routing to Milvus or LightRAG backends.

Usage::

    from nexagent.knowledge.manager import get_manager

    manager = get_manager()
    kb = await manager.create_kb("my docs", kb_type="milvus")
    file = await manager.add_file(kb.kb_id, "report.pdf", pdf_bytes)
    await manager.parse_file(kb.kb_id, file.file_id)
    await manager.index_file(kb.kb_id, file.file_id)
    results = await manager.search(kb.kb_id, "What is X?")
"""

import logging
import os
from dataclasses import replace
from pathlib import Path

from nexagent.knowledge.models import (
    EmbedInfo,
    FileMeta,
    KBMeta,
    KBType,
    LLMInfo,
    SearchResult,
)

logger = logging.getLogger(__name__)


def _default_work_dir() -> str:
    data_root = Path(os.environ.get("NEXAGENT_DATA_DIR", str(Path.home() / ".nexagent")))
    base = data_root / "knowledge"
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


class KnowledgeBaseManager:
    """Routes KB operations to the appropriate backend (Milvus or LightRAG).

    Each backend persists its own metadata independently under ``work_dir``.
    The manager is intentionally thin — it discovers which backend owns a
    given ``kb_id`` by querying all loaded backends.
    """

    def __init__(self, work_dir: str | None = None) -> None:
        self._work_dir = work_dir or _default_work_dir()
        self._backends: dict[KBType, object] = {}   # KBType → KnowledgeBase

    # ── Backend lifecycle ─────────────────────────────────────────────────────

    def _get_backend(self, kb_type: KBType):
        if kb_type not in self._backends:
            self._backends[kb_type] = self._create_backend(kb_type)
        return self._backends[kb_type]

    def _create_backend(self, kb_type: KBType):
        if kb_type == KBType.MILVUS:
            from nexagent.knowledge.implementations.milvus_kb import MilvusKB
            return MilvusKB(work_dir=str(Path(self._work_dir) / "milvus"))
        elif kb_type == KBType.LIGHTRAG:
            from nexagent.knowledge.implementations.lightrag_kb import LightRagKB
            return LightRagKB(work_dir=str(Path(self._work_dir) / "lightrag"))
        elif kb_type == KBType.WIKI:
            from nexagent.knowledge.implementations.wiki import WikiKB

            return WikiKB(work_dir=str(Path(self._work_dir) / "wiki"))
        else:
            raise ValueError(f"Unknown KB type: {kb_type}")

    def _ensure_all_backends(self) -> None:
        """Load all backend instances so their persisted metadata is visible."""
        for kb_type in KBType:
            if kb_type not in self._backends:
                try:
                    self._backends[kb_type] = self._create_backend(kb_type)
                except Exception as exc:
                    logger.debug("Could not initialise %s backend: %s", kb_type, exc)

    def _find_backend(self, kb_id: str, raise_on_missing: bool = True):
        """Return the backend that owns ``kb_id``, loading all if needed."""
        self._ensure_all_backends()
        for backend in self._backends.values():
            if backend.get_kb(kb_id) is not None:
                return backend
        if raise_on_missing:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        return None

    # ── KB CRUD ───────────────────────────────────────────────────────────────

    async def create_kb(
        self,
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
        kb_type_enum = KBType(kb_type)
        backend = self._get_backend(kb_type_enum)
        effective_embed_info = (
            embed_info
            if embed_info is not None
            else EmbedInfo(model="", base_url="", api_key="", dimension=0)
            if kb_type_enum == KBType.WIKI
            else _default_embed_info()
        )
        return await backend.create_kb(
            name=name,
            description=description,
            embed_info=effective_embed_info,
            llm_info=llm_info or _default_llm_info(),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_preset_id=chunk_preset_id,
            chunk_parser_config=chunk_parser_config or {},
        )

    async def delete_kb(self, kb_id: str) -> None:
        backend = self._find_backend(kb_id)
        await backend.delete_kb(kb_id)

    def get_kb(self, kb_id: str) -> KBMeta | None:
        backend = self._find_backend(kb_id, raise_on_missing=False)
        return backend.get_kb(kb_id) if backend else None

    def list_kbs(self) -> list[KBMeta]:
        self._ensure_all_backends()
        result: list[KBMeta] = []
        for backend in self._backends.values():
            result.extend(backend.list_kbs())
        return result

    # ── File management ───────────────────────────────────────────────────────

    async def add_file(self, kb_id: str, filename: str, content: bytes) -> FileMeta:
        return await self._find_backend(kb_id).add_file(kb_id, filename, content)

    async def parse_file(self, kb_id: str, file_id: str) -> FileMeta:
        return await self._find_backend(kb_id).parse_file(kb_id, file_id)

    async def index_file(self, kb_id: str, file_id: str) -> FileMeta:
        return await self._find_backend(kb_id).index_file(kb_id, file_id)

    async def reparse_file(self, kb_id: str, file_id: str) -> FileMeta:
        backend = self._find_backend(kb_id)
        fn = getattr(backend, "reparse_file", None)
        if not callable(fn):
            raise ValueError(f"Knowledge backend for {kb_id} does not support reparse.")
        return await fn(kb_id, file_id)

    async def reindex_file(self, kb_id: str, file_id: str) -> FileMeta:
        backend = self._find_backend(kb_id)
        fn = getattr(backend, "reindex_file", None)
        if not callable(fn):
            raise ValueError(f"Knowledge backend for {kb_id} does not support reindex.")
        return await fn(kb_id, file_id)

    async def rebuild_graph_file(self, kb_id: str, file_id: str) -> FileMeta:
        backend = self._find_backend(kb_id)
        fn = getattr(backend, "rebuild_graph_file", None)
        if not callable(fn):
            raise ValueError(f"Knowledge backend for {kb_id} does not support graph rebuild.")
        return await fn(kb_id, file_id)

    async def delete_file(self, kb_id: str, file_id: str) -> None:
        await self._find_backend(kb_id).delete_file(kb_id, file_id)

    def get_file(self, kb_id: str, file_id: str) -> FileMeta | None:
        backend = self._find_backend(kb_id, raise_on_missing=False)
        return backend.get_file(kb_id, file_id) if backend else None

    def list_files(self, kb_id: str) -> list[FileMeta]:
        backend = self._find_backend(kb_id, raise_on_missing=False)
        return backend.list_files(kb_id) if backend else []

    def list_indexed_chunks(self, kb_id: str, limit: int = 1000) -> list[dict]:
        backend = self._find_backend(kb_id, raise_on_missing=False)
        if backend is None:
            return []
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            return []
        list_fn = getattr(backend, "list_indexed_chunks", None)
        if callable(list_fn):
            return list_fn(kb_meta, limit=limit)
        return []

    # ── Search ────────────────────────────────────────────────────────────────

    async def search(
        self, kb_id: str, query: str, top_k: int = 5, **kwargs
    ) -> list[SearchResult]:
        return await self._find_backend(kb_id).search(kb_id, query, top_k=top_k, **kwargs)

    def get_query_config(self, kb_id: str) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        return _clean_query_config(
            _default_query_config(kb_meta.kb_type.value) | dict(kb_meta.extra.get("query_config") or {}),
            kb_meta.kb_type.value,
        )

    def get_query_options(self, kb_id: str) -> list[dict]:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        return _query_options(kb_meta.kb_type.value)

    def update_query_config(self, kb_id: str, patch: dict) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        current = self.get_query_config(kb_id)
        cleaned = _clean_query_config({**current, **patch}, kb_meta.kb_type.value)
        kb_meta.extra["query_config"] = cleaned
        save_fn = getattr(backend, "_save_meta", None)
        if callable(save_fn):
            save_fn()
        return cleaned

    def update_model_config(self, kb_id: str, patch: dict) -> dict:
        """Update KB-level embedding, LLM, and rerank metadata without rebuilding indexes."""
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")

        current_embed = kb_meta.embed_info
        next_embed = replace(
            current_embed,
            model=str(patch.get("embed_model", current_embed.model) or current_embed.model),
            base_url=str(patch.get("embed_base_url", current_embed.base_url) or ""),
            api_key=str(patch.get("embed_api_key", current_embed.api_key) or ""),
            dimension=_bounded_int(
                patch.get("embed_dimension", current_embed.dimension),
                current_embed.dimension,
                1,
                8192,
            ),
        )
        embedding_changed = next_embed.to_dict() != current_embed.to_dict()
        if embedding_changed:
            kb_meta.embed_info = next_embed

        current_llm = kb_meta.llm_info
        next_llm = replace(
            current_llm,
            provider=str(patch.get("llm_provider", current_llm.provider) or current_llm.provider),
            model=str(patch.get("llm_model", current_llm.model) or current_llm.model),
            base_url=str(patch.get("llm_base_url", current_llm.base_url) or ""),
            api_key=str(patch.get("llm_api_key", current_llm.api_key) or ""),
        )
        llm_changed = next_llm.to_dict() != current_llm.to_dict()
        if llm_changed:
            kb_meta.llm_info = next_llm
            rag_cache = getattr(backend, "_rag_cache", None)
            if isinstance(rag_cache, dict):
                rag_cache.pop(kb_id, None)
            initialized = getattr(backend, "_rag_initialized", None)
            if isinstance(initialized, set):
                initialized.discard(kb_id)

        query_patch = {}
        if "use_reranker" in patch:
            query_patch["use_reranker"] = bool(patch.get("use_reranker"))
        if "reranker_model" in patch:
            query_patch["reranker_model"] = str(patch.get("reranker_model") or "")
        if query_patch:
            self.update_query_config(kb_id, query_patch)

        indexed_files = [file for file in self.list_files(kb_id) if file.status.value == "indexed"]
        requires_reindex = bool(
            ((embedding_changed or llm_changed) and indexed_files)
            or kb_meta.extra.get("requires_reindex")
        )
        kb_meta.extra["model_config"] = {
            "embedding_model": kb_meta.embed_info.model,
            "embedding_dimension": kb_meta.embed_info.dimension,
            "llm_provider": kb_meta.llm_info.provider,
            "llm_model": kb_meta.llm_info.model,
            "reranker_model": self.get_query_config(kb_id).get("reranker_model", ""),
            "use_reranker": self.get_query_config(kb_id).get("use_reranker", False),
            "requires_reindex": requires_reindex,
        }
        kb_meta.extra["requires_reindex"] = requires_reindex
        save_fn = getattr(backend, "_save_meta", None)
        if callable(save_fn):
            save_fn()
        return {
            "kb": kb_meta.to_dict(),
            "requires_reindex": requires_reindex,
            "indexed_files": len(indexed_files),
            "query_config": self.get_query_config(kb_id),
        }

    def update_chunk_config(self, kb_id: str, patch: dict) -> dict:
        """Update KB-level chunking config and mark indexed files for re-index."""
        from nexagent.knowledge.chunking import normalize_chunk_preset_id, resolve_chunk_processing_params

        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")

        before = {
            "chunk_size": kb_meta.chunk_size,
            "chunk_overlap": kb_meta.chunk_overlap,
            "chunk_preset_id": kb_meta.chunk_preset_id,
            "chunk_parser_config": dict(kb_meta.chunk_parser_config or {}),
        }
        if "chunk_size" in patch:
            kb_meta.chunk_size = _bounded_int(patch.get("chunk_size"), kb_meta.chunk_size, 64, 65535)
        if "chunk_overlap" in patch:
            kb_meta.chunk_overlap = _bounded_int(patch.get("chunk_overlap"), kb_meta.chunk_overlap, 0, 65534)
        if "chunk_preset_id" in patch:
            kb_meta.chunk_preset_id = normalize_chunk_preset_id(patch.get("chunk_preset_id"))
        if isinstance(patch.get("chunk_parser_config"), dict):
            kb_meta.chunk_parser_config = dict(patch["chunk_parser_config"])

        normalized = resolve_chunk_processing_params(
            {
                "chunk_preset_id": kb_meta.chunk_preset_id,
                "chunk_parser_config": kb_meta.chunk_parser_config,
                "chunk_size": kb_meta.chunk_size,
                "chunk_overlap": kb_meta.chunk_overlap,
            }
        )
        kb_meta.chunk_size = int(normalized["chunk_size"])
        kb_meta.chunk_overlap = int(normalized["chunk_overlap"])
        kb_meta.chunk_preset_id = str(normalized["chunk_preset_id"])
        kb_meta.chunk_parser_config = dict(normalized["chunk_parser_config"])

        after = {
            "chunk_size": kb_meta.chunk_size,
            "chunk_overlap": kb_meta.chunk_overlap,
            "chunk_preset_id": kb_meta.chunk_preset_id,
            "chunk_parser_config": dict(kb_meta.chunk_parser_config or {}),
        }
        indexed_files = [file for file in self.list_files(kb_id) if file.status.value == "indexed"]
        requires_reindex = bool(indexed_files and before != after)
        kb_meta.extra["chunk_config"] = {
            **after,
            "requires_reindex": requires_reindex,
        }
        kb_meta.extra["requires_reindex"] = bool(kb_meta.extra.get("requires_reindex") or requires_reindex)
        save_fn = getattr(backend, "_save_meta", None)
        if callable(save_fn):
            save_fn()
        return {
            "kb": kb_meta.to_dict(),
            "requires_reindex": kb_meta.extra["requires_reindex"],
            "indexed_files": len(indexed_files),
            "processing_params": normalized,
        }

    # Backend diagnostics and graph inspection

    def backend_status(self) -> dict:
        """Return local status for configured knowledge backends."""
        backends: dict[str, dict] = {}
        for kb_type in KBType:
            try:
                backend = self._get_backend(kb_type)
                status_fn = getattr(backend, "status", None)
                status = status_fn() if callable(status_fn) else {"status": "configured"}
                status["knowledge_bases"] = len(backend.list_kbs())
                backends[kb_type.value] = status
            except Exception as exc:
                backends[kb_type.value] = {"status": "unavailable", "reason": str(exc)}

        try:
            from nexagent.knowledge.neo4j_store import neo4j_status

            neo4j = neo4j_status()
        except Exception as exc:
            neo4j = {"status": "unavailable", "reason": str(exc)}

        return {
            "status": "ok",
            "work_dir": self._work_dir,
            "backends": backends,
            "neo4j": neo4j,
            "total_knowledge_bases": len(self.list_kbs()),
        }

    def diagnostics(self, kb_id: str) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        if kb_meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        files = self.list_files(kb_id)
        status_counts: dict[str, int] = {}
        for file in files:
            status_counts[file.status.value] = status_counts.get(file.status.value, 0) + 1
        backend_status = {}
        status_fn = getattr(backend, "status", None)
        if callable(status_fn):
            backend_status = status_fn()
        parser_capabilities = _parser_capabilities()
        diagnostics = {
            "kb_id": kb_id,
            "kb_type": kb_meta.kb_type.value,
            "status": "ok",
            "status_counts": status_counts,
            "files": [
                {
                    "file_id": file.file_id,
                    "filename": file.filename,
                    "status": file.status.value,
                    "error": file.error,
                    "chunk_count": file.chunk_count,
                    "parser": (file.parse_metadata or {}).get("parser"),
                    "parser_chain": (file.parse_metadata or {}).get("parser_chain") or [],
                    "processing_params": file.processing_params,
                }
                for file in files
            ],
            "chunk_config": {
                "chunk_size": kb_meta.chunk_size,
                "chunk_overlap": kb_meta.chunk_overlap,
                "chunk_preset_id": kb_meta.chunk_preset_id,
                "chunk_parser_config": kb_meta.chunk_parser_config,
                "requires_reindex": bool(kb_meta.extra.get("requires_reindex")),
            },
            "model_config": {
                "embedding_model": kb_meta.embed_info.model,
                "embedding_dimension": kb_meta.embed_info.dimension,
                "llm_model": kb_meta.llm_info.model,
            },
            "backend": backend_status,
            "graph": kb_meta.extra.get("graph") or {},
            "parser_capabilities": parser_capabilities,
            "actions": [
                "reparse failed or low-quality parsed files",
                "reindex after embedding or chunk config changes",
                "rebuild graph after enabling Neo4j/LightRAG",
            ],
        }
        issues = []
        if any(file.status.value in {"parse_error", "index_error", "error_graphing"} for file in files):
            issues.append("Some files are in an error state; use reparse, reindex, or rebuild-graph.")
        graph_status = (kb_meta.extra.get("graph") or {}).get("lightrag") or {}
        if kb_meta.kb_type == KBType.LIGHTRAG and graph_status.get("status") != "ok":
            issues.append("Native LightRAG semantic graph is unavailable; current graph is degraded.")
        if kb_meta.extra.get("requires_reindex"):
            issues.append("Knowledge base configuration changed after indexing; reindex files.")
        diagnostics["issues"] = issues
        diagnostics["status"] = "warning" if issues else "ok"
        return diagnostics

    def graph_stats(self, kb_id: str) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        stats_fn = getattr(backend, "graph_stats", None)
        if not callable(stats_fn):
            raise ValueError(f"Knowledge base {kb_id} does not expose a graph")
        return stats_fn(kb_meta)

    def graph_summary(self, kb_id: str) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        summary_fn = getattr(backend, "graph_summary", None)
        if callable(summary_fn):
            return summary_fn(kb_meta)
        graph = self.export_graph(kb_id, limit=1000)
        stats = graph.get("stats") or {}
        relations = sorted(
            {str(edge.get("relation") or "related_to") for edge in graph.get("edges", [])}
        )
        return {
            "kb_id": kb_id,
            "kb_type": kb_meta.kb_type.value if kb_meta else "",
            "stats": stats,
            "relations": relations,
            "updated_at": kb_meta.updated_at if kb_meta else "",
        }

    def export_graph(self, kb_id: str, limit: int = 200) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        export_fn = getattr(backend, "export_graph", None)
        if not callable(export_fn):
            raise ValueError(f"Knowledge base {kb_id} does not expose a graph")
        return export_fn(kb_meta, limit=limit)

    def search_graph(self, kb_id: str, query: str, limit: int = 20) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        search_fn = getattr(backend, "search_graph", None)
        if callable(search_fn):
            return search_fn(kb_meta, query=query, limit=limit)
        graph = self.export_graph(kb_id, limit=1000)
        query_l = query.lower().strip()
        nodes = [
            node for node in graph.get("nodes", [])
            if not query_l or query_l in str(node.get("name", "")).lower()
        ][:limit]
        return {"query": query, "nodes": nodes, "total": len(nodes)}

    def graph_subgraph(self, kb_id: str, node_id: str, depth: int = 1, limit: int = 80) -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        subgraph_fn = getattr(backend, "graph_subgraph", None)
        if callable(subgraph_fn):
            return subgraph_fn(kb_meta, node_id=node_id, depth=depth, limit=limit)
        graph = self.export_graph(kb_id, limit=1000)
        selected = {node_id}
        edges = []
        for _ in range(max(1, depth)):
            for edge in graph.get("edges", []):
                if edge.get("source") in selected or edge.get("target") in selected:
                    edges.append(edge)
                    selected.add(str(edge.get("source")))
                    selected.add(str(edge.get("target")))
                if len(edges) >= limit:
                    break
        nodes = [node for node in graph.get("nodes", []) if node.get("name") in selected][:limit]
        return {
            "node_id": node_id,
            "depth": depth,
            "nodes": nodes,
            "edges": edges[:limit],
            "stats": {"nodes": len(nodes), "edges": len(edges[:limit])},
        }

    def import_graph(self, kb_id: str, graph_data: dict, source: str = "manual") -> dict:
        backend = self._find_backend(kb_id)
        kb_meta = backend.get_kb(kb_id)
        import_fn = getattr(backend, "import_graph", None)
        if not callable(import_fn):
            raise ValueError(f"Knowledge base {kb_id} does not support graph import")
        result = import_fn(kb_meta, graph_data, source=source)
        save_fn = getattr(backend, "_save_meta", None)
        if callable(save_fn):
            save_fn()
        return result


# ── Config helpers ────────────────────────────────────────────────────────────

def _default_embed_info() -> EmbedInfo:
    """Build EmbedInfo from the application config (SiliconFlow BAAI/bge)."""
    try:
        from nexagent.config import get_config
        kb_cfg = get_config().knowledge
        return EmbedInfo(
            model=kb_cfg.embed_model,
            base_url=kb_cfg.embed_base_url,
            api_key=kb_cfg.embed_api_key,
            dimension=kb_cfg.embed_dimension,
        )
    except Exception:
        return EmbedInfo()


def _default_llm_info() -> LLMInfo:
    """Build LLMInfo from the first configured model (for LightRAG graph extraction)."""
    try:
        from nexagent.config import get_config
        models = get_config().models
        if models:
            m = models[0]
            api_key = m.api_key  # already resolved by config loader
            return LLMInfo(
                provider=m.provider,
                model=m.model,
                base_url=m.base_url,
                api_key=api_key,
            )
    except Exception:
        pass
    return LLMInfo()


def _parser_capabilities() -> dict:
    optional_modules = {
        "docling": "docling.document_converter",
        "pymupdf": "fitz",
        "pypdf": "pypdf",
        "unstructured": "unstructured",
        "rapidocr": "rapidocr_onnxruntime",
    }
    engines = {}
    for name, module_name in optional_modules.items():
        try:
            __import__(module_name)
            engines[name] = {"available": True}
        except Exception as exc:
            engines[name] = {"available": False, "reason": str(exc)}
    return {
        "engines": engines,
        "preferred_order": ["docling", "pymupdf", "pypdf"],
        "service_adapters": {
            "mineru": {"configured": bool(os.environ.get("MINERU_API_URL") or os.environ.get("MINERU_API_BASE"))},
            "paddlex": {"configured": bool(os.environ.get("PADDLEX_API_URL") or os.environ.get("PADDLEX_API_BASE"))},
        },
    }


def _default_query_config(kb_type: str) -> dict:
    if kb_type == "wiki":
        return {
            "mode": "wiki",
            "search_mode": "wiki",
            "final_top_k": 10,
            "recall_top_k": 10,
            "similarity_threshold": 0.0,
            "use_reranker": False,
            "reranker_model": "",
        }
    if kb_type == "lightrag":
        return {
            "mode": "lightrag_hybrid",
            "search_mode": "lightrag_hybrid",
            "final_top_k": 10,
            "recall_top_k": 30,
            "similarity_threshold": 0.0,
            "use_reranker": False,
            "reranker_model": "",
        }
    return {
        "mode": "hybrid",
        "search_mode": "hybrid",
        "final_top_k": 10,
        "recall_top_k": 30,
        "similarity_threshold": 0.0,
        "vector_weight": 0.7,
        "keyword_weight": 0.3,
        "bm25_weight": 0.3,
        "bm25_top_k": 50,
        "bm25_drop_ratio_search": 0.0,
        "use_reranker": False,
        "reranker_model": "",
    }


def _clean_query_config(value: dict, kb_type: str) -> dict:
    allowed_modes = _available_modes(kb_type)
    mode = str(value.get("search_mode") or value.get("mode") or _default_query_config(kb_type)["mode"])
    if mode == "bm25":
        mode = "keyword"
    if mode not in allowed_modes:
        mode = _default_query_config(kb_type)["mode"]
    cleaned = {
        "mode": mode,
        "search_mode": mode,
        "final_top_k": _bounded_int(value.get("final_top_k"), 10, 1, 100),
        "recall_top_k": _bounded_int(value.get("recall_top_k"), 30, 1, 200),
        "similarity_threshold": _bounded_float(value.get("similarity_threshold"), 0.0, 0.0, 1.0),
        "use_reranker": bool(value.get("use_reranker", False)),
        "reranker_model": str(value.get("reranker_model") or ""),
    }
    if kb_type != "lightrag":
        bm25_weight = _bounded_float(value.get("bm25_weight", value.get("keyword_weight")), 0.3, 0.0, 1.0)
        cleaned.update(
            {
                "vector_weight": _bounded_float(value.get("vector_weight"), 0.7, 0.0, 1.0),
                "keyword_weight": bm25_weight,
                "bm25_weight": bm25_weight,
                "bm25_top_k": _bounded_int(value.get("bm25_top_k"), 50, 1, 200),
                "bm25_drop_ratio_search": _bounded_float(value.get("bm25_drop_ratio_search"), 0.0, 0.0, 1.0),
            }
        )
    return cleaned


def _available_modes(kb_type: str) -> list[str]:
    if kb_type == "wiki":
        return ["wiki"]
    if kb_type == "lightrag":
        return ["lightrag_local", "lightrag_global", "lightrag_hybrid"]
    return ["vector", "keyword", "hybrid"]


def _query_options(kb_type: str) -> list[dict]:
    if kb_type == "wiki":
        return [
            {"key": "final_top_k", "label": "返回数量", "type": "number", "min": 1, "max": 50},
        ]
    if kb_type == "lightrag":
        return [
            {
                "key": "search_mode",
                "label": "检索模式",
                "type": "select",
                "options": [
                    {"value": "lightrag_local", "label": "LightRAG Local"},
                    {"value": "lightrag_global", "label": "LightRAG Global"},
                    {"value": "lightrag_hybrid", "label": "LightRAG Hybrid"},
                ],
            },
            {"key": "final_top_k", "label": "返回数量", "type": "number", "min": 1, "max": 100},
        ]
    return [
        {
            "key": "search_mode",
            "label": "检索模式",
            "type": "select",
            "options": [
                {"value": "vector", "label": "向量检索"},
                {"value": "keyword", "label": "关键词 BM25"},
                {"value": "hybrid", "label": "混合检索"},
            ],
        },
        {"key": "final_top_k", "label": "返回数量", "type": "number", "min": 1, "max": 100},
        {"key": "recall_top_k", "label": "向量召回数量", "type": "number", "min": 1, "max": 200},
        {"key": "bm25_top_k", "label": "BM25 召回数量", "type": "number", "min": 1, "max": 200},
        {"key": "similarity_threshold", "label": "相似度阈值", "type": "number", "min": 0, "max": 1},
        {"key": "vector_weight", "label": "向量权重", "type": "number", "min": 0, "max": 1},
        {"key": "bm25_weight", "label": "BM25 权重", "type": "number", "min": 0, "max": 1},
        {"key": "bm25_drop_ratio_search", "label": "BM25 稀疏项丢弃比例", "type": "number", "min": 0, "max": 1},
        {"key": "use_reranker", "label": "启用 rerank", "type": "boolean"},
        {"key": "reranker_model", "label": "Rerank 模型", "type": "text"},
    ]


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


# ── Module-level singleton ────────────────────────────────────────────────────

_manager: KnowledgeBaseManager | None = None


def get_manager() -> KnowledgeBaseManager:
    """Return the application-level KnowledgeBaseManager singleton."""
    global _manager
    if _manager is None:
        _manager = KnowledgeBaseManager()
    return _manager


def reset_manager(work_dir: str | None = None) -> KnowledgeBaseManager:
    """Reset the module-level manager. Intended for tests and verification scripts."""
    global _manager
    _manager = KnowledgeBaseManager(work_dir=work_dir)
    return _manager
