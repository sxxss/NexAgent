"""Data models for the NexAgent knowledge base system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _now() -> str:
    return datetime.now(UTC).isoformat()


class KBType(StrEnum):
    """Supported knowledge base backends."""
    MILVUS = "milvus"       # Vector RAG (semantic search)
    LIGHTRAG = "lightrag"   # Knowledge graph (entity + relation)
    WIKI = "wiki"           # Markdown-first Wiki knowledge base


class FileStatus(StrEnum):
    """Lifecycle of a document within a knowledge base."""
    UPLOADED = "uploaded"           # File saved to disk
    PARSING = "parsing"             # Extracting text
    PARSED = "parsed"               # Text extracted, ready to index
    PARSE_ERROR = "parse_error"     # Extraction failed
    INDEXING = "indexing"           # Chunking + embedding
    INDEXED = "indexed"             # Ready for queries
    INDEX_ERROR = "index_error"     # Indexing failed
    GRAPHING = "graphing"           # Building semantic knowledge graph
    GRAPH_INDEXED = "graph_indexed" # Indexed and semantic graph built
    GRAPH_ERROR = "error_graphing"  # Graph construction failed
    INDEXED_WITH_GRAPH_DEGRADED = "indexed_with_graph_degraded"


_FILE_PROGRESS: dict[FileStatus, dict[str, object]] = {
    FileStatus.UPLOADED: {
        "percent": 10,
        "stage": "uploaded",
        "label": "待解析",
        "next_action": "process",
    },
    FileStatus.PARSING: {
        "percent": 35,
        "stage": "parsing",
        "label": "解析中",
        "next_action": "wait",
    },
    FileStatus.PARSED: {
        "percent": 60,
        "stage": "parsed",
        "label": "待入库",
        "next_action": "index",
    },
    FileStatus.PARSE_ERROR: {
        "percent": 10,
        "stage": "parse_error",
        "label": "解析失败",
        "next_action": "process",
    },
    FileStatus.INDEXING: {
        "percent": 80,
        "stage": "indexing",
        "label": "入库中",
        "next_action": "wait",
    },
    FileStatus.INDEXED: {
        "percent": 100,
        "stage": "indexed",
        "label": "可检索",
        "next_action": "search",
    },
    FileStatus.INDEX_ERROR: {
        "percent": 60,
        "stage": "index_error",
        "label": "入库失败",
        "next_action": "index",
    },
    FileStatus.GRAPHING: {
        "percent": 90,
        "stage": "graphing",
        "label": "图谱构建中",
        "next_action": "wait",
    },
    FileStatus.GRAPH_INDEXED: {
        "percent": 100,
        "stage": "graph_indexed",
        "label": "图谱可用",
        "next_action": "search",
    },
    FileStatus.GRAPH_ERROR: {
        "percent": 85,
        "stage": "error_graphing",
        "label": "图谱失败",
        "next_action": "rebuild_graph",
    },
    FileStatus.INDEXED_WITH_GRAPH_DEGRADED: {
        "percent": 100,
        "stage": "indexed_with_graph_degraded",
        "label": "降级可检索",
        "next_action": "rebuild_graph",
    },
}


@dataclass
class EmbedInfo:
    """Embedding model configuration."""
    model: str = "BAAI/bge-large-zh-v1.5"
    base_url: str = ""
    api_key: str = ""
    dimension: int = 1024

    def to_dict(self, *, include_secret: bool = True) -> dict:
        payload = {"model": self.model, "base_url": self.base_url, "dimension": self.dimension}
        if include_secret:
            payload["api_key"] = self.api_key
        return payload

    @classmethod
    def from_dict(cls, d: dict) -> EmbedInfo:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LLMInfo:
    """LLM configuration (used by LightRAG for graph construction)."""
    provider: str = "openai"
    model: str = "Qwen/Qwen2.5-7B-Instruct"
    base_url: str = ""
    api_key: str = ""

    def to_dict(self, *, include_secret: bool = True) -> dict:
        payload = {"provider": self.provider, "model": self.model, "base_url": self.base_url}
        if include_secret:
            payload["api_key"] = self.api_key
        return payload

    @classmethod
    def from_dict(cls, d: dict) -> LLMInfo:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class KBMeta:
    """Metadata for a single knowledge base."""
    kb_id: str
    name: str
    kb_type: KBType
    description: str = ""
    embed_info: EmbedInfo = field(default_factory=EmbedInfo)
    llm_info: LLMInfo = field(default_factory=LLMInfo)
    chunk_size: int = 512
    chunk_overlap: int = 64
    chunk_preset_id: str = "general"
    chunk_parser_config: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    extra: dict = field(default_factory=dict)

    def to_dict(self, *, include_secrets: bool = True) -> dict:
        return {
            "kb_id": self.kb_id,
            "name": self.name,
            "kb_type": self.kb_type.value,
            "description": self.description,
            "embed_info": self.embed_info.to_dict(include_secret=include_secrets),
            "llm_info": self.llm_info.to_dict(include_secret=include_secrets),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "chunk_preset_id": self.chunk_preset_id,
            "chunk_parser_config": self.chunk_parser_config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KBMeta:
        d = dict(d)
        d["kb_type"] = KBType(d["kb_type"])
        d["embed_info"] = EmbedInfo.from_dict(d.get("embed_info") or {})
        d["llm_info"] = LLMInfo.from_dict(d.get("llm_info") or {})
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class FileMeta:
    """Metadata for a single document inside a knowledge base."""
    file_id: str
    kb_id: str
    filename: str
    file_path: str          # Absolute path on disk
    file_size: int = 0
    status: FileStatus = FileStatus.UPLOADED
    parsed_path: str = ""   # Path to extracted markdown text
    chunk_count: int = 0
    error: str = ""
    parse_metadata: dict = field(default_factory=dict)
    processing_params: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def progress(self) -> dict:
        """Return a UI/API friendly ingestion progress snapshot."""
        base = dict(_FILE_PROGRESS[self.status])
        complete_states = {
            FileStatus.INDEXED,
            FileStatus.GRAPH_INDEXED,
            FileStatus.INDEXED_WITH_GRAPH_DEGRADED,
        }
        indexable_states = {
            FileStatus.PARSED,
            FileStatus.INDEX_ERROR,
            FileStatus.INDEXED,
            FileStatus.GRAPH_ERROR,
            FileStatus.GRAPH_INDEXED,
            FileStatus.INDEXED_WITH_GRAPH_DEGRADED,
        }
        is_running = self.status in {FileStatus.PARSING, FileStatus.INDEXING, FileStatus.GRAPHING}
        is_error = self.status in {FileStatus.PARSE_ERROR, FileStatus.INDEX_ERROR, FileStatus.GRAPH_ERROR}
        return {
            **base,
            "can_parse": self.status in {FileStatus.UPLOADED, FileStatus.PARSE_ERROR},
            "can_index": self.status in indexable_states,
            "can_process": self.status in {FileStatus.UPLOADED, FileStatus.PARSE_ERROR},
            "is_running": is_running,
            "is_error": is_error,
            "is_complete": self.status in complete_states,
        }

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "kb_id": self.kb_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "status": self.status.value,
            "parsed_path": self.parsed_path,
            "chunk_count": self.chunk_count,
            "error": self.error,
            "parse_metadata": self.parse_metadata,
            "processing_params": self.processing_params,
            "progress": self.progress(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FileMeta:
        d = dict(d)
        status_value = d.get("status")
        status_aliases = {
            "error_parsing": FileStatus.PARSE_ERROR,
            "error_indexing": FileStatus.INDEX_ERROR,
        }
        d["status"] = status_aliases.get(status_value) or FileStatus(status_value)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SearchResult:
    """A single result from a knowledge base query."""
    content: str
    score: float = 0.0
    source: str = ""
    file_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        chunk_id = self.metadata.get("chunk_id") or self.metadata.get("id") or ""
        chunk_index = self.metadata.get("chunk_index")
        return {
            "content": self.content,
            "score": self.score,
            "source": self.source,
            "file_id": self.file_id,
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "metadata": self.metadata,
        }
