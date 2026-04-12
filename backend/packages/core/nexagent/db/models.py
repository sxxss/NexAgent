"""ORM models for NexAgent."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nexagent.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


def _provider_env_fallback(name: str, base_url: str) -> str:
    text = f"{name} {base_url}".lower()
    if "siliconflow" in text or "siliconflow.cn" in text or "siliconflow.com" in text:
        return "SILICONFLOW_API_KEY"
    if "deepseek" in text:
        return "DEEPSEEK_API_KEY"
    if "dashscope" in text or "aliyun" in text:
        return "DASHSCOPE_API_KEY"
    if "moonshot" in text:
        return "MOONSHOT_API_KEY"
    if "openrouter" in text:
        return "OPENROUTER_API_KEY"
    if "openai" in text:
        return "OPENAI_API_KEY"
    return ""


# JSON column helpers

class _JsonColumn:
    """Descriptor that transparently serialises/deserialises JSON via a Text column."""

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr = f"_json_{name}"

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        raw = getattr(obj, self._attr, None)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def __set__(self, obj: Any, value: Any) -> None:
        if value is None:
            setattr(obj, self._attr, None)
        elif isinstance(value, str):
            setattr(obj, self._attr, value)
        else:
            setattr(obj, self._attr, json.dumps(value, ensure_ascii=False))


# Database models

class ModelProvider(Base):
    """A configured LLM provider (OpenAI, Anthropic, custom endpoint, etc.)."""

    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)   # openai/anthropic/google/ollama
    base_url: Mapped[str | None] = mapped_column(String(512))
    models_endpoint: Mapped[str | None] = mapped_column(String(256), default="/models")
    api_key_env: Mapped[str | None] = mapped_column(String(128))
    _json_capabilities: Mapped[str | None] = mapped_column("capabilities_json", Text)
    _json_models: Mapped[str | None] = mapped_column("models_json", Text)    # JSON list of model ids
    _json_model_configs: Mapped[str | None] = mapped_column("model_configs_json", Text)
    api_key_enc: Mapped[str | None] = mapped_column(Text)                    # encrypted or plain key
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    models = _JsonColumn()  # type: ignore[assignment]
    capabilities = _JsonColumn()  # type: ignore[assignment]
    model_configs = _JsonColumn()  # type: ignore[assignment]

    def to_dict(self, include_key: bool = False) -> dict:
        env_name = self.api_key_env or _provider_env_fallback(self.name, self.base_url or "")
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "base_url": self.base_url or "",
            "models_endpoint": self.models_endpoint or "/models",
            "api_key_env": self.api_key_env or "",
            "capabilities": self.capabilities or ["chat"],
            "models": self.models or [],
            "model_configs": self.model_configs or [],
            "is_enabled": self.is_enabled,
            "is_default": self.is_default,
            "api_key_configured": bool(self.api_key_enc or (env_name and os.environ.get(env_name))),
            "api_key": self.api_key_enc if include_key else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Database models

class AgentConfig(Base):
    """User-created Agent configuration, extending a built-in agent type."""

    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    base_type: Mapped[str] = mapped_column(String(64), default="chatbot")    # chatbot / deep_research
    model_name: Mapped[str | None] = mapped_column(String(256))
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    _json_tools: Mapped[str | None] = mapped_column("tools_json", Text)
    _json_kb_ids: Mapped[str | None] = mapped_column("kb_ids_json", Text)
    _json_skill_ids: Mapped[str | None] = mapped_column("skill_ids_json", Text)
    _json_mcp_ids: Mapped[str | None] = mapped_column("mcp_ids_json", Text)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_budget: Mapped[int] = mapped_column(Integer, default=8000)
    reasoning_mode: Mapped[str] = mapped_column(String(32), default="balanced")
    allow_subagents: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)         # built-in agents cannot be deleted
    avatar_color: Mapped[str] = mapped_column(String(32), default="indigo")  # for UI
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    tools = _JsonColumn()       # type: ignore[assignment]
    kb_ids = _JsonColumn()      # type: ignore[assignment]
    skill_ids = _JsonColumn()   # type: ignore[assignment]
    mcp_ids = _JsonColumn()     # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "base_type": self.base_type,
            "model_name": self.model_name or "",
            "system_prompt": self.system_prompt,
            "tools": self.tools or [],
            "kb_ids": self.kb_ids or [],
            "skill_ids": self.skill_ids or [],
            "mcp_ids": self.mcp_ids or [],
            "memory_enabled": self.memory_enabled,
            "thinking_enabled": self.thinking_enabled,
            "thinking_budget": self.thinking_budget,
            "reasoning_mode": self.reasoning_mode,
            "allow_subagents": self.allow_subagents,
            "is_builtin": self.is_builtin,
            "avatar_color": self.avatar_color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# MCP server models

class MCPServer(Base):
    """Installed MCP server configuration managed from the UI."""

    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    transport: Mapped[str] = mapped_column(String(32), default="stdio")
    _json_command: Mapped[str | None] = mapped_column("command_json", Text)
    url: Mapped[str | None] = mapped_column(String(512))
    _json_env: Mapped[str | None] = mapped_column("env_json", Text)
    _json_disabled_tools: Mapped[str | None] = mapped_column("disabled_tools_json", Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="registry")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    command = _JsonColumn()  # type: ignore[assignment]
    env = _JsonColumn()      # type: ignore[assignment]
    disabled_tools = _JsonColumn()  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "command": self.command or [],
            "url": self.url or "",
            "env": self.env or {},
            "disabled_tools": self.disabled_tools or [],
            "is_enabled": self.is_enabled,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Invocation log models

class InvocationLog(Base):
    """One record per agent conversation turn for the Dashboard."""

    __tablename__ = "invocation_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(128))
    thread_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model_name: Mapped[str | None] = mapped_column(String(256))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    raw_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    token_source: Mapped[str] = mapped_column(String(32), default="provider_reported")
    token_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="success")   # success/error/interrupted
    error_msg: Mapped[str | None] = mapped_column(Text)
    _json_tools_used: Mapped[str | None] = mapped_column("tools_used_json", Text)
    thinking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_mode: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    tools_used = _JsonColumn()  # type: ignore[assignment]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "thread_id": self.thread_id,
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "raw_input_tokens": self.raw_input_tokens,
            "raw_output_tokens": self.raw_output_tokens,
            "token_source": self.token_source,
            "token_estimated": self.token_estimated,
            "total_tokens": self.input_tokens + self.output_tokens,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_msg": self.error_msg,
            "tools_used": self.tools_used or [],
            "thinking_enabled": self.thinking_enabled,
            "reasoning_mode": self.reasoning_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Conversation(Base):
    """Conversation metadata shown in the chat history sidebar."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    user_id: Mapped[str | None] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(128))
    model_name: Mapped[str | None] = mapped_column(String(256))
    last_message: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "model_name": self.model_name,
            "last_message": self.last_message,
            "message_count": self.message_count,
            "archived": self.archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConversationMessage(Base):
    """Persisted chat message for a conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))  # user/assistant/tool
    content: Mapped[str] = mapped_column(Text, default="")
    tool_name: Mapped[str | None] = mapped_column(String(128))
    reasoning_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "tool_name": self.tool_name,
            "reasoning_content": self.reasoning_content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Memory models

class MemoryEntry(Base):
    """Persistent memory item stored by an agent or user."""

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), index=True)
    memory_type: Mapped[str] = mapped_column(String(32), default="fact")     # fact/preference/episode
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="agent")         # agent/user
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "memory_type": self.memory_type,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "importance": self.importance,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Production knowledge-base models

class KnowledgeBaseRecord(Base):
    """Production knowledge base metadata stored in the application database."""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kb_type: Mapped[str] = mapped_column(String(32), default="milvus", index=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=64)
    chunk_preset_id: Mapped[str] = mapped_column(String(64), default="general")
    _json_chunk_parser_config: Mapped[str | None] = mapped_column("chunk_parser_config_json", Text)
    _json_embed_info: Mapped[str | None] = mapped_column("embed_info_json", Text)
    _json_llm_info: Mapped[str | None] = mapped_column("llm_info_json", Text)
    _json_extra: Mapped[str | None] = mapped_column("extra_json", Text)
    legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    chunk_parser_config = _JsonColumn()  # type: ignore[assignment]
    embed_info = _JsonColumn()  # type: ignore[assignment]
    llm_info = _JsonColumn()  # type: ignore[assignment]
    extra = _JsonColumn()  # type: ignore[assignment]


class KnowledgeFileRecord(Base):
    """Production file metadata and object-store pointers."""

    __tablename__ = "knowledge_files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), default="")
    checksum: Mapped[str] = mapped_column(String(128), index=True, default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    raw_uri: Mapped[str] = mapped_column(Text, default="")
    parsed_uri: Mapped[str] = mapped_column(Text, default="")
    chunk_manifest_uri: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(48), default="uploaded", index=True)
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    _json_parse_metadata: Mapped[str | None] = mapped_column("parse_metadata_json", Text)
    _json_processing_params: Mapped[str | None] = mapped_column("processing_params_json", Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    parse_metadata = _JsonColumn()  # type: ignore[assignment]
    processing_params = _JsonColumn()  # type: ignore[assignment]


class KnowledgeChunkRecord(Base):
    """Production chunk metadata and content for retrieval diagnostics/eval."""

    __tablename__ = "knowledge_chunks"

    chunk_id: Mapped[str] = mapped_column(String(192), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    file_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    manifest_uri: Mapped[str] = mapped_column(Text, default="")
    _json_chunk_metadata: Mapped[str | None] = mapped_column("metadata_json", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    chunk_metadata = _JsonColumn()  # type: ignore[assignment]


class KnowledgeJobRecord(Base):
    """Production long-running knowledge job with structured logs."""

    __tablename__ = "knowledge_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    file_id: Mapped[str | None] = mapped_column(String(64), index=True)
    job_type: Mapped[str] = mapped_column(String(64), default="ingest")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    current_step: Mapped[str] = mapped_column(String(128), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    _json_input_snapshot: Mapped[str | None] = mapped_column("input_snapshot_json", Text)
    _json_logs: Mapped[str | None] = mapped_column("logs_json", Text)
    _json_result: Mapped[str | None] = mapped_column("result_json", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    input_snapshot = _JsonColumn()  # type: ignore[assignment]
    logs = _JsonColumn()  # type: ignore[assignment]
    result = _JsonColumn()  # type: ignore[assignment]


class KnowledgeIndexManifest(Base):
    """Manifest for Milvus/vector index compatibility and health."""

    __tablename__ = "knowledge_index_manifests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    backend: Mapped[str] = mapped_column(String(64), default="milvus")
    status: Mapped[str] = mapped_column(String(48), default="unavailable")
    collection_name: Mapped[str] = mapped_column(String(256), default="")
    schema_version: Mapped[str] = mapped_column(String(64), default="")
    embedding_model: Mapped[str] = mapped_column(String(256), default="")
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=0)
    requires_reindex: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    _json_config_snapshot: Mapped[str | None] = mapped_column("config_snapshot_json", Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    config_snapshot = _JsonColumn()  # type: ignore[assignment]


class KnowledgeGraphManifest(Base):
    """Manifest for LightRAG/Neo4j graph build compatibility and health."""

    __tablename__ = "knowledge_graph_manifests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    kb_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    backend: Mapped[str] = mapped_column(String(64), default="neo4j_lightrag")
    status: Mapped[str] = mapped_column(String(48), default="unavailable")
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    requires_rebuild: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    _json_config_snapshot: Mapped[str | None] = mapped_column("config_snapshot_json", Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    config_snapshot = _JsonColumn()  # type: ignore[assignment]


class EvalBenchmark(Base):
    __tablename__ = "eval_benchmarks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kb_id: Mapped[str | None] = mapped_column(String(64), index=True)
    _json_retrieval_config: Mapped[str | None] = mapped_column("retrieval_config_json", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    retrieval_config = _JsonColumn()  # type: ignore[assignment]


class EvalSample(Base):
    __tablename__ = "eval_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    benchmark_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    gold_answer: Mapped[str] = mapped_column(Text, default="")
    _json_gold_chunk_ids: Mapped[str | None] = mapped_column("gold_chunk_ids_json", Text)
    _json_gold_entities: Mapped[str | None] = mapped_column("gold_entities_json", Text)
    _json_gold_relations: Mapped[str | None] = mapped_column("gold_relations_json", Text)
    _json_retrieval_config: Mapped[str | None] = mapped_column("retrieval_config_json", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    gold_chunk_ids = _JsonColumn()  # type: ignore[assignment]
    gold_entities = _JsonColumn()  # type: ignore[assignment]
    gold_relations = _JsonColumn()  # type: ignore[assignment]
    retrieval_config = _JsonColumn()  # type: ignore[assignment]


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    benchmark_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    _json_metrics: Mapped[str | None] = mapped_column("metrics_json", Text)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    metrics = _JsonColumn()  # type: ignore[assignment]


class EvalSampleResult(Base):
    __tablename__ = "eval_sample_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    sample_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="succeeded")
    error_code: Mapped[str] = mapped_column(String(128), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    _json_retrieved_chunks: Mapped[str | None] = mapped_column("retrieved_chunks_json", Text)
    _json_graph_hits: Mapped[str | None] = mapped_column("graph_hits_json", Text)
    _json_metrics: Mapped[str | None] = mapped_column("metrics_json", Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    retrieved_chunks = _JsonColumn()  # type: ignore[assignment]
    graph_hits = _JsonColumn()  # type: ignore[assignment]
    metrics = _JsonColumn()  # type: ignore[assignment]
