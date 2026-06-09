"""Abstract base class for all NexAgent knowledge base backends."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from nexagent.knowledge.models import (
    EmbedInfo,
    FileMeta,
    FileStatus,
    KBMeta,
    KBType,
    LLMInfo,
    SearchResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_ALLOWED_UPLOAD_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".htm",
    ".html",
    ".json",
    ".markdown",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rst",
    ".txt",
    ".xlsx",
    ".yaml",
    ".yml",
}
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class KnowledgeFileError(ValueError):
    """Structured validation error for file lifecycle operations."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_detail(self) -> dict:
        return {
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


def max_upload_bytes() -> int:
    try:
        return max(1, int(os.environ.get("NEXAGENT_KB_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_UPLOAD_BYTES


def _sanitize_upload_filename(filename: str) -> str:
    raw = str(filename or "").replace("\x00", "").strip()
    if not raw:
        raise KnowledgeFileError("invalid_filename", "Uploaded file must have a filename.")

    normalized = raw.replace("\\", "/")
    path_parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if any(part == ".." for part in path_parts):
        raise KnowledgeFileError(
            "invalid_filename",
            "Uploaded filename must not contain parent path segments.",
            details={"filename": raw},
        )

    basename = path_parts[-1] if path_parts else normalized
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", basename).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise KnowledgeFileError(
            "invalid_filename",
            "Uploaded filename becomes empty after sanitization.",
            details={"filename": raw},
        )

    if Path(cleaned).stem.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"file_{cleaned}"

    suffix = Path(cleaned).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise KnowledgeFileError(
            "unsupported_file_type",
            f"Unsupported knowledge file type: {suffix or 'none'}.",
            details={
                "filename": raw,
                "allowed_extensions": sorted(_ALLOWED_UPLOAD_EXTENSIONS),
            },
        )
    return cleaned


def _validate_upload_content(content: bytes, filename: str) -> None:
    size = len(content)
    limit = max_upload_bytes()
    if size <= 0:
        raise KnowledgeFileError(
            "empty_file",
            "Uploaded file is empty.",
            details={"filename": filename, "size": size},
        )
    if size > limit:
        raise KnowledgeFileError(
            "file_too_large",
            f"Uploaded file exceeds the maximum size of {limit} bytes.",
            status_code=413,
            details={"filename": filename, "size": size, "max_size": limit},
        )


class KnowledgeBase(ABC):
    """Pluggable knowledge base backend.

    Each implementation (Milvus, LightRAG) manages its own vector / graph
    storage while this base class owns the on-disk metadata (JSON) and the
    local copy of uploaded files.

    Directory layout under ``work_dir``::

        work_dir/
        ├── meta.json           ← all KBMeta + FileMeta for this backend type
        ├── <kb_id>/
        │   ├── files/          ← raw uploaded documents
        │   └── parsed/         ← extracted plain-text / markdown
        └── ...
    """

    def __init__(self, work_dir: str) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self._meta_path = self.work_dir / "meta.json"
        self._kbs: dict[str, KBMeta] = {}       # kb_id → KBMeta
        self._files: dict[str, FileMeta] = {}    # file_id → FileMeta
        self._meta_lock = asyncio.Lock()
        self._processing_files: set[str] = set()
        self._load_meta()

    # ── abstract interface ───────────────────────────────────────────────────

    @property
    @abstractmethod
    def kb_type(self) -> KBType:
        """Return the backend type enum value."""

    @abstractmethod
    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        """Index the parsed text file into the backend.

        Returns the number of chunks indexed.
        Must raise on failure.
        """

    @abstractmethod
    async def _do_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        **kwargs,
    ) -> list[SearchResult]:
        """Run a query against the backend and return ranked results."""

    @abstractmethod
    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        """Remove all backend data for this KB (collections, graph, etc.)."""

    @abstractmethod
    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        """Remove indexed data for a single file from the backend."""

    # ── public CRUD ──────────────────────────────────────────────────────────

    async def create_kb(
        self,
        name: str,
        description: str = "",
        embed_info: EmbedInfo | None = None,
        llm_info: LLMInfo | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        chunk_preset_id: str = "general",
        chunk_parser_config: dict | None = None,
    ) -> KBMeta:
        from nexagent.knowledge.chunking import normalize_chunk_preset_id

        kb_id = str(uuid.uuid4())
        meta = KBMeta(
            kb_id=kb_id,
            name=name,
            kb_type=self.kb_type,
            description=description,
            embed_info=embed_info or EmbedInfo(),
            llm_info=llm_info or LLMInfo(),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_preset_id=normalize_chunk_preset_id(chunk_preset_id),
            chunk_parser_config=dict(chunk_parser_config or {}),
        )
        (self.work_dir / kb_id / "files").mkdir(parents=True, exist_ok=True)
        (self.work_dir / kb_id / "parsed").mkdir(parents=True, exist_ok=True)
        async with self._meta_lock:
            self._kbs[kb_id] = meta
            self._save_meta()
        logger.info(f"Created KB '{name}' ({kb_id}) type={self.kb_type.value}")
        return meta

    async def delete_kb(self, kb_id: str) -> None:
        meta = self._require_kb(kb_id)
        # Remove from backend
        try:
            await self._do_delete_kb(meta)
        except Exception as e:
            logger.warning(f"Backend cleanup failed for {kb_id}: {e}")
        # Remove local files
        import shutil
        kb_dir = self.work_dir / kb_id
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
        # Remove metadata
        async with self._meta_lock:
            self._kbs.pop(kb_id, None)
            for fid in [fid for fid, f in self._files.items() if f.kb_id == kb_id]:
                self._files.pop(fid)
            self._save_meta()

    def get_kb(self, kb_id: str) -> KBMeta | None:
        meta = self._kbs.get(kb_id)
        if meta is not None and self._normalize_kb_runtime_flags(meta):
            self._save_meta()
        return meta

    def list_kbs(self) -> list[KBMeta]:
        changed = False
        for meta in self._kbs.values():
            changed = self._normalize_kb_runtime_flags(meta) or changed
        if changed:
            self._save_meta()
        return list(self._kbs.values())

    # ── file management ──────────────────────────────────────────────────────

    async def add_file(
        self,
        kb_id: str,
        filename: str,
        content: bytes,
        processing_params: dict | None = None,
    ) -> FileMeta:
        """Save an uploaded file and return its metadata (not yet indexed)."""
        from nexagent.knowledge.chunking import resolve_chunk_processing_params

        kb_meta = self._require_kb(kb_id)
        safe_filename = _sanitize_upload_filename(filename)
        _validate_upload_content(content, safe_filename)
        file_id = str(uuid.uuid4())
        files_dir = self.work_dir / kb_id / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        dest = files_dir / f"{file_id}_{safe_filename}"
        tmp_dest = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        tmp_dest.write_bytes(content)
        meta = FileMeta(
            file_id=file_id,
            kb_id=kb_id,
            filename=safe_filename,
            file_path=str(dest),
            file_size=len(content),
            status=FileStatus.UPLOADED,
            processing_params=resolve_chunk_processing_params(
                {
                    "chunk_preset_id": kb_meta.chunk_preset_id,
                    "chunk_parser_config": kb_meta.chunk_parser_config,
                    "chunk_size": kb_meta.chunk_size,
                    "chunk_overlap": kb_meta.chunk_overlap,
                },
                processing_params,
            ),
        )
        try:
            tmp_dest.replace(dest)
            async with self._meta_lock:
                self._files[file_id] = meta
                self._save_meta()
        except Exception:
            self._files.pop(file_id, None)
            for path in (tmp_dest, dest):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    logger.debug("Failed to clean up upload path %s", path, exc_info=True)
            raise
        return meta

    async def parse_file(self, kb_id: str, file_id: str) -> FileMeta:
        """Extract plain text from the uploaded file and save as .txt."""
        from nexagent.knowledge.parser import parse_document_structured
        meta = self._require_file(kb_id, file_id)
        if meta.status not in {FileStatus.UPLOADED, FileStatus.PARSE_ERROR}:
            raise KnowledgeFileError(
                "invalid_file_state",
                f"File {file_id} cannot be parsed from status {meta.status.value}.",
                status_code=409,
                details={
                    "file_id": file_id,
                    "status": meta.status.value,
                    "allowed_statuses": [FileStatus.UPLOADED.value, FileStatus.PARSE_ERROR.value],
                },
            )
        self._begin_processing(file_id, "parse")
        try:
            await self._update_file_status(file_id, FileStatus.PARSING)
            parsed = await parse_document_structured(meta.file_path)
            parsed_path = self.work_dir / kb_id / "parsed" / f"{file_id}.txt"
            parsed_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = parsed_path.with_name(f".{parsed_path.name}.{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(parsed.content, encoding="utf-8")
            tmp_path.replace(parsed_path)
            async with self._meta_lock:
                self._files[file_id].parsed_path = str(parsed_path)
                self._files[file_id].chunk_count = 0
                self._files[file_id].parse_metadata = {
                    **parsed.metadata,
                    "table_count": len(parsed.tables),
                    "image_count": len(parsed.images),
                }
                self._files[file_id].status = FileStatus.PARSED
                self._files[file_id].error = ""
                self._files[file_id].updated_at = datetime.now(UTC).isoformat()
                self._save_meta()
            return self._files[file_id]
        except Exception as e:
            await self._update_file_status(file_id, FileStatus.PARSE_ERROR, str(e))
            raise
        finally:
            self._end_processing(file_id)

    async def index_file(self, kb_id: str, file_id: str) -> FileMeta:
        """Chunk + embed the parsed text and index it in the backend."""
        from nexagent.knowledge.chunking import resolve_chunk_processing_params

        meta = self._require_file(kb_id, file_id)
        kb_meta = self._require_kb(kb_id)
        allowed_statuses = {
            FileStatus.PARSED,
            FileStatus.INDEX_ERROR,
            FileStatus.INDEXED,
            FileStatus.GRAPH_ERROR,
            FileStatus.GRAPH_INDEXED,
            FileStatus.INDEXED_WITH_GRAPH_DEGRADED,
        }
        if meta.status not in allowed_statuses:
            raise KnowledgeFileError(
                "invalid_file_state",
                f"File {file_id} cannot be indexed from status {meta.status.value}.",
                status_code=409,
                details={
                    "file_id": file_id,
                    "status": meta.status.value,
                    "allowed_statuses": sorted(status.value for status in allowed_statuses),
                },
            )
        parsed_path = Path(meta.parsed_path or "")
        if not meta.parsed_path or not parsed_path.exists():
            raise KnowledgeFileError(
                "parsed_file_missing",
                "Parsed text is missing; parse the file before indexing.",
                status_code=409,
                details={"file_id": file_id, "parsed_path": meta.parsed_path},
            )
        self._begin_processing(file_id, "index")
        try:
            processing_params = resolve_chunk_processing_params(
                {
                    "chunk_preset_id": kb_meta.chunk_preset_id,
                    "chunk_parser_config": kb_meta.chunk_parser_config,
                    "chunk_size": kb_meta.chunk_size,
                    "chunk_overlap": kb_meta.chunk_overlap,
                },
                meta.processing_params,
            )
            async with self._meta_lock:
                self._files[file_id].status = FileStatus.INDEXING
                self._files[file_id].error = ""
                self._files[file_id].processing_params = processing_params
                self._files[file_id].updated_at = datetime.now(UTC).isoformat()
                self._save_meta()
            chunk_count = await self._do_index(kb_meta, meta)
            async with self._meta_lock:
                self._files[file_id].status = self._index_success_status(kb_meta, self._files[file_id])
                self._files[file_id].chunk_count = chunk_count
                self._files[file_id].error = ""
                self._files[file_id].updated_at = datetime.now(UTC).isoformat()
                self._save_meta()
            return self._files[file_id]
        except Exception as e:
            await self._update_file_status(file_id, FileStatus.INDEX_ERROR, str(e))
            raise
        finally:
            self._end_processing(file_id)

    async def reparse_file(self, kb_id: str, file_id: str) -> FileMeta:
        """Force a file back through parsing while preserving the uploaded blob."""
        meta = self._require_file(kb_id, file_id)
        if meta.status in {FileStatus.PARSING, FileStatus.INDEXING, FileStatus.GRAPHING}:
            raise KnowledgeFileError(
                "file_processing",
                f"File {file_id} is currently {meta.status.value}.",
                status_code=409,
                details={"file_id": file_id, "status": meta.status.value},
            )
        async with self._meta_lock:
            self._files[file_id].status = FileStatus.PARSE_ERROR
            self._files[file_id].error = ""
            self._files[file_id].parsed_path = ""
            self._files[file_id].chunk_count = 0
            self._files[file_id].updated_at = datetime.now(UTC).isoformat()
            self._save_meta()
        return await self.parse_file(kb_id, file_id)

    async def reindex_file(self, kb_id: str, file_id: str) -> FileMeta:
        """Force index rebuild for an already parsed/indexed file."""
        meta = self._require_file(kb_id, file_id)
        if meta.status in {FileStatus.PARSING, FileStatus.INDEXING, FileStatus.GRAPHING}:
            raise KnowledgeFileError(
                "file_processing",
                f"File {file_id} is currently {meta.status.value}.",
                status_code=409,
                details={"file_id": file_id, "status": meta.status.value},
            )
        if not meta.parsed_path:
            raise KnowledgeFileError(
                "parsed_file_missing",
                "Parsed text is missing; parse the file before re-indexing.",
                status_code=409,
                details={"file_id": file_id},
            )
        async with self._meta_lock:
            self._files[file_id].status = FileStatus.INDEX_ERROR
            self._files[file_id].error = ""
            self._files[file_id].updated_at = datetime.now(UTC).isoformat()
            self._save_meta()
        return await self.index_file(kb_id, file_id)

    async def rebuild_graph_file(self, kb_id: str, file_id: str) -> FileMeta:
        """Default graph rebuild uses the normal index rebuild path."""
        return await self.reindex_file(kb_id, file_id)

    async def delete_file(self, kb_id: str, file_id: str) -> None:
        meta = self._require_file(kb_id, file_id)
        kb_meta = self._require_kb(kb_id)
        try:
            await self._do_delete_file(kb_meta, meta)
        except Exception as e:
            logger.warning(f"Backend file removal failed for {file_id}: {e}")
        # Remove local files
        for path in (meta.file_path, meta.parsed_path):
            if path:
                p = Path(path)
                if p.exists():
                    p.unlink()
        async with self._meta_lock:
            self._files.pop(file_id, None)
            self._save_meta()

    def get_file(self, kb_id: str, file_id: str) -> FileMeta | None:
        f = self._files.get(file_id)
        return f if f and f.kb_id == kb_id else None

    def list_files(self, kb_id: str) -> list[FileMeta]:
        return [f for f in self._files.values() if f.kb_id == kb_id]

    # ── search ───────────────────────────────────────────────────────────────

    async def search(self, kb_id: str, query: str, top_k: int = 5, **kwargs) -> list[SearchResult]:
        kb_meta = self._require_kb(kb_id)
        return await self._do_search(query, kb_meta, top_k=top_k, **kwargs)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _require_kb(self, kb_id: str) -> KBMeta:
        meta = self._kbs.get(kb_id)
        if meta is None:
            raise KeyError(f"Knowledge base not found: {kb_id}")
        return meta

    def _require_file(self, kb_id: str, file_id: str) -> FileMeta:
        meta = self._files.get(file_id)
        if meta is None or meta.kb_id != kb_id:
            raise KeyError(f"File not found: {file_id} in KB {kb_id}")
        return meta

    async def _update_file_status(
        self, file_id: str, status: FileStatus, error: str = ""
    ) -> None:
        async with self._meta_lock:
            if file_id in self._files:
                self._files[file_id].status = status
                self._files[file_id].error = error
                self._files[file_id].updated_at = datetime.now(UTC).isoformat()
                self._save_meta()

    # ── metadata persistence (JSON file) ────────────────────────────────────

    def _begin_processing(self, file_id: str, operation: str) -> None:
        if file_id in self._processing_files:
            raise KnowledgeFileError(
                "file_processing",
                f"File {file_id} is already being processed.",
                status_code=409,
                details={"file_id": file_id, "operation": operation},
            )
        self._processing_files.add(file_id)

    def _end_processing(self, file_id: str) -> None:
        self._processing_files.discard(file_id)

    def _normalize_kb_runtime_flags(self, kb_meta: KBMeta) -> bool:
        return False

    def _index_success_status(self, kb_meta: KBMeta, file_meta: FileMeta) -> FileStatus:
        return FileStatus.INDEXED

    def _load_meta(self) -> None:
        if not self._meta_path.exists():
            return
        try:
            raw = json.loads(self._meta_path.read_text(encoding="utf-8"))
            self._kbs = {k: KBMeta.from_dict(v) for k, v in raw.get("kbs", {}).items()}
            self._files = {k: FileMeta.from_dict(v) for k, v in raw.get("files", {}).items()}
            if self._recover_interrupted_files():
                self._save_meta()
        except Exception as e:
            logger.error(f"Failed to load KB metadata from {self._meta_path}: {e}")

    def _recover_interrupted_files(self) -> bool:
        changed = False
        now = datetime.now(UTC).isoformat()
        for file_meta in self._files.values():
            if file_meta.status == FileStatus.PARSING:
                file_meta.status = FileStatus.PARSE_ERROR
                file_meta.error = "Parsing was interrupted before completion; retry processing this file."
                file_meta.updated_at = now
                changed = True
            elif file_meta.status == FileStatus.INDEXING:
                file_meta.status = FileStatus.INDEX_ERROR
                file_meta.error = "Indexing was interrupted before completion; retry indexing this file."
                file_meta.updated_at = now
                changed = True
            elif file_meta.status == FileStatus.GRAPHING:
                file_meta.status = FileStatus.GRAPH_ERROR
                file_meta.error = "Graph construction was interrupted before completion; retry rebuilding the graph."
                file_meta.updated_at = now
                changed = True
        return changed

    def _save_meta(self) -> None:
        """Write metadata to disk. Must be called under _meta_lock."""
        try:
            data = {
                "kbs": {k: v.to_dict() for k, v in self._kbs.items()},
                "files": {k: v.to_dict() for k, v in self._files.items()},
            }
            tmp_path = self._meta_path.with_suffix(f"{self._meta_path.suffix}.tmp")
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp_path.replace(self._meta_path)
        except Exception as e:
            logger.error(f"Failed to save KB metadata: {e}")
            raise
