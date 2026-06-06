"""NexAgent configuration management.

Loads settings from config.yaml and environment variables.
"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

CONFIG_VERSION = 2

IssueSeverity = Literal["ok", "warning", "error"]


@dataclass(frozen=True)
class ConfigIssue:
    """Actionable configuration diagnostic."""

    severity: IssueSeverity
    code: str
    message: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass(frozen=True)
class ConfigDiagnostics:
    """Configuration health summary used by startup checks and API diagnostics."""

    status: IssueSeverity
    path: str
    config_exists: bool
    issues: list[ConfigIssue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "path": self.path,
            "config_exists": self.config_exists,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class ModelConfig:
    """Configuration for a single LLM model."""

    name: str
    display_name: str
    provider: str  # "openai", "anthropic", "google", "ollama"
    model: str
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    supports_streaming: bool = True


@dataclass
class KnowledgeConfig:
    """Configuration for knowledge base services."""

    milvus_host: str = "localhost"
    milvus_port: int = 19530
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    # Embedding model for vector search
    embed_model: str = "BAAI/bge-large-zh-v1.5"
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_dimension: int = 1024
    vector_store_enabled: bool = True
    vector_store_provider: str = "milvus"
    vector_store_uri: str = ""
    graph_store_enabled: bool = False
    graph_store_provider: str = "neo4j"
    graph_store_uri: str = ""
    rerank_model: str = ""
    rerank_top_k_multiplier: int = 3
    storage_backend: str = "legacy"
    object_store_endpoint: str = "localhost:9000"
    object_store_access_key: str = "minioadmin"
    object_store_secret_key: str = "minioadmin"
    object_store_secure: bool = False
    object_store_public_endpoint: str = ""
    raw_bucket: str = "kb-raw"
    parsed_bucket: str = "kb-parsed"
    chunks_bucket: str = "kb-chunks"
    eval_bucket: str = "kb-eval"
    artifacts_bucket: str = "kb-artifacts"


@dataclass
class WebSearchConfig:
    """Configuration for web search tool."""

    provider: str = "auto"   # "auto" or a concrete provider id
    preferred_provider: str = "duckduckgo"
    enabled_providers: list[str] = field(default_factory=lambda: ["duckduckgo"])
    provider_keys: dict[str, str] = field(default_factory=dict)
    provider_base_urls: dict[str, str] = field(default_factory=dict)
    tavily_api_key: str = ""
    max_results: int = 5
    fetch_max_chars: int = 12000


@dataclass
class SpeechConfig:
    """Voice (ASR / TTS) configuration.

    ``*_provider_id`` references a row in the DB ``model_providers`` table for the
    base URL + API key. When empty, the speech service falls back to the default
    chat provider so SiliconFlow works out of the box. Endpoints are
    OpenAI-compatible (``/audio/transcriptions`` and ``/audio/speech``).
    """

    asr_enabled: bool = True
    asr_provider_id: str = ""
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    asr_language: str = ""  # empty = auto-detect

    tts_enabled: bool = True
    tts_provider_id: str = ""
    tts_model: str = "FunAudioLLM/CosyVoice2-0.5B"
    tts_voice: str = "FunAudioLLM/CosyVoice2-0.5B:alex"
    tts_format: str = "mp3"
    tts_sample_rate: int = 32000
    tts_speed: float = 1.0


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str = ""
    transport: str = "stdio"        # "stdio" | "sse" | "http"
    command: list[str] = field(default_factory=list)   # stdio: command + args
    url: str = ""                   # sse/http: server URL
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxConfig:
    """Configuration for the code execution sandbox."""

    enabled: bool = True
    provider: str = "local"
    base_dir: str = ".nexagent"
    timeout_seconds: int = 30
    max_output_chars: int = 8000
    docker_image: str = "python:3.12-slim"
    docker_memory_limit: str = "512m"
    docker_cpu_quota: int = 50000
    docker_network: str = "none"
    audit_enabled: bool = True
    audit_path: str = ".nexagent/sandbox_audit.jsonl"
    allow_bash: bool = True
    blocked_commands: list[str] = field(
        default_factory=lambda: [
            "rm -rf /",
            "format ",
            "shutdown",
            "reboot",
            "mkfs",
            "diskpart",
            "reg delete",
        ]
    )


@dataclass
class LangSmithConfig:
    enabled: bool = False
    api_key: str = ""
    project: str = "nexagent"
    endpoint: str = "https://api.smith.langchain.com"


@dataclass
class LangfuseConfig:
    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"


@dataclass
class TracingConfig:
    langsmith: LangSmithConfig = field(default_factory=LangSmithConfig)
    langfuse: LangfuseConfig = field(default_factory=LangfuseConfig)


@dataclass
class AppConfig:
    """Root application configuration."""

    models: list[ModelConfig] = field(default_factory=list)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    debug: bool = False
    config_version: int = CONFIG_VERSION

    # Skills directory — empty string means auto-resolve from project root
    skills_dir: str = ""

    # Derived
    default_model: str = ""


_config: AppConfig | None = None
_config_path: Path | None = None
_config_mtime: float | None = None


def _issue(severity: IssueSeverity, code: str, message: str, fix: str = "") -> ConfigIssue:
    return ConfigIssue(severity=severity, code=code, message=message, fix=fix)


def _resolve_env_var(value: str) -> str:
    """Resolve $ENV_VAR references in config values."""
    if isinstance(value, str) and value.startswith("$"):
        return os.environ.get(value[1:], "")
    return value


def _expand_env_vars(value: Any) -> Any:
    """Recursively resolve $ENV_VAR string values in nested config structures."""
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return _resolve_env_var(value)


def _migrate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply lightweight in-memory migrations for older config.yaml files."""
    migrated = deepcopy(raw)
    version = int(migrated.get("config_version", 1))

    if version < 2:
        migrated.setdefault("tracing", {})
        migrated.setdefault("sandbox", {})
        migrated["sandbox"].setdefault("provider", "local")
        migrated["sandbox"].setdefault("local", {"base_dir": ".nexagent"})

        knowledge = migrated.setdefault("knowledge", {})
        knowledge.setdefault(
            "vector_store",
            {
                "enabled": True,
                "provider": "milvus",
                "uri": os.environ.get("MILVUS_URI", ""),
            },
        )
        knowledge.setdefault(
            "graph_store",
            {
                "enabled": False,
                "provider": "neo4j",
                "uri": knowledge.get("neo4j_uri", os.environ.get("NEO4J_URI", "")),
            },
        )
        migrated["config_version"] = CONFIG_VERSION

    return migrated


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _env_or_config(env_name: str, configured: Any, default: Any = "") -> Any:
    value = os.environ.get(env_name)
    if value not in (None, ""):
        return value
    if configured not in (None, ""):
        return configured
    return default


def reset_config_cache() -> None:
    """Clear the loaded config singleton. Useful for tests and hot reload."""
    global _config, _config_path, _config_mtime
    _config = None
    _config_path = None
    _config_mtime = None


def _resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is None:
        config_path = os.environ.get("NEXAGENT_CONFIG_PATH")
    if config_path is not None:
        return Path(config_path)

    # config.yaml lives at the project root (NexAgent/), which is 4 levels up
    # from this file (backend/packages/core/nexagent/config.py).
    candidates = [
        Path(__file__).parents[4] / "config.yaml",
        Path(__file__).parents[3] / "config.yaml",
        Path.cwd() / "config.yaml",
        Path.cwd().parent / "config.yaml",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


def _current_mtime(path: Path) -> float | None:
    return path.stat().st_mtime if path.exists() else None


def _enabled_provider_needs_key(provider_id: str, config: WebSearchConfig) -> bool:
    if provider_id in {"duckduckgo", "searxng"}:
        return False
    return not config.provider_keys.get(provider_id)


def validate_config(config: AppConfig | None = None, config_path: str | Path | None = None) -> list[ConfigIssue]:
    """Return actionable config issues without leaking secrets."""
    path = _resolve_config_path(config_path)
    config = config or load_config(path)
    issues: list[ConfigIssue] = []

    if not path.exists():
        issues.append(
            _issue(
                "warning",
                "config_file_missing",
                f"Config file was not found at {path}. NexAgent is using defaults.",
                "Copy config.example.yaml to config.yaml or set NEXAGENT_CONFIG_PATH.",
            )
        )

    if config.config_version < CONFIG_VERSION:
        issues.append(
            _issue(
                "warning",
                "config_version_old",
                f"config_version={config.config_version} is older than supported version {CONFIG_VERSION}.",
                "Regenerate config.yaml from config.example.yaml or let the in-memory migration guide your changes.",
            )
        )

    if not config.models:
        issues.append(
            _issue(
                "error",
                "models_empty",
                "No chat models are configured.",
                "Add at least one item under models in config.yaml.",
            )
        )
    else:
        names = [model.name for model in config.models if model.name]
        if len(names) != len(set(names)):
            issues.append(
                _issue(
                    "error",
                    "model_names_not_unique",
                    "Model names must be unique.",
                    "Rename duplicated model entries in config.yaml.",
                )
            )
        if config.default_model and config.default_model not in names:
            issues.append(
                _issue(
                    "error",
                    "default_model_missing",
                    f"default_model '{config.default_model}' does not match any configured model name.",
                    "Set default_model to one of the configured models.",
                )
            )
        if not config.default_model:
            issues.append(
                _issue(
                    "warning",
                    "default_model_empty",
                    "default_model is empty; NexAgent will use the first configured model.",
                    "Set default_model explicitly for predictable startup behavior.",
                )
            )
        for model in config.models:
            if model.provider.lower() in {"openai", "anthropic", "google"} and not model.api_key:
                issues.append(
                    _issue(
                        "warning",
                        "model_api_key_missing",
                        f"Model '{model.name}' has no API key configured.",
                        "Fill the referenced environment variable in .env or config.yaml.",
                    )
                )
            if model.provider.lower() == "openai" and not model.model:
                issues.append(
                    _issue(
                        "error",
                        "model_id_missing",
                        f"Model '{model.name}' is missing the provider model id.",
                        "Set the model field, for example gpt-4o-mini or Qwen/Qwen2.5-7B-Instruct.",
                    )
                )

    if config.knowledge.vector_store_enabled and config.knowledge.vector_store_provider == "milvus":
        if not config.knowledge.milvus_host:
            issues.append(
                _issue("error", "milvus_host_missing", "Milvus is enabled but milvus_host is empty.")
            )
        if not config.knowledge.embed_api_key and config.knowledge.embed_base_url:
            issues.append(
                _issue(
                    "warning",
                    "embedding_api_key_missing",
                    "Embedding model has a remote base_url but no API key.",
                    "Set EMBED_API_KEY or knowledge.embedding.api_key.",
                )
            )

    if config.knowledge.graph_store_enabled and config.knowledge.graph_store_provider == "neo4j":
        if not config.knowledge.neo4j_uri:
            issues.append(_issue("error", "neo4j_uri_missing", "Neo4j graph store is enabled but neo4j_uri is empty."))
        if not config.knowledge.neo4j_password:
            issues.append(
                _issue(
                    "warning",
                    "neo4j_password_missing",
                    "Neo4j graph store is enabled but no password is configured.",
                    "Set NEO4J_PASSWORD or knowledge.neo4j_password.",
                )
            )

    if config.web_search.provider != "auto" and config.web_search.provider not in config.web_search.enabled_providers:
        issues.append(
            _issue(
                "warning",
                "web_search_provider_not_enabled",
                f"web_search.provider '{config.web_search.provider}' is not listed in enabled_providers.",
                "Add the provider to enabled_providers or use provider: auto.",
            )
        )
    for provider_id in config.web_search.enabled_providers:
        if _enabled_provider_needs_key(provider_id, config.web_search):
            issues.append(
                _issue(
                    "warning",
                    "web_search_key_missing",
                    f"Web search provider '{provider_id}' is enabled but has no API key.",
                    "Disable the provider or configure its API key.",
                )
            )

    if config.sandbox.enabled and config.sandbox.provider not in {"local", "docker"}:
        issues.append(
            _issue(
                "error",
                "sandbox_provider_invalid",
                f"Unsupported sandbox provider '{config.sandbox.provider}'.",
                "Use sandbox.provider: local or docker.",
            )
        )
    if config.sandbox.enabled and config.sandbox.provider == "local" and config.sandbox.allow_bash:
        issues.append(
            _issue(
                "warning",
                "local_bash_enabled",
                "Local sandbox bash execution is enabled.",
                "Use docker sandbox or disable sandbox.allow_bash before serving untrusted users.",
            )
        )

    if config.tracing.langsmith.enabled and not config.tracing.langsmith.api_key:
        issues.append(
            _issue("warning", "langsmith_key_missing", "LangSmith tracing is enabled but no API key is configured.")
        )
    if config.tracing.langfuse.enabled and (
        not config.tracing.langfuse.public_key or not config.tracing.langfuse.secret_key
    ):
        issues.append(
            _issue(
                "warning",
                "langfuse_key_missing",
                "Langfuse tracing is enabled but public_key or secret_key is missing.",
            )
        )

    return issues


def get_config_diagnostics(config_path: str | Path | None = None) -> ConfigDiagnostics:
    """Load config and return a startup-friendly diagnostic summary."""
    path = _resolve_config_path(config_path)
    config = load_config(path)
    issues = validate_config(config, path)
    if any(issue.severity == "error" for issue in issues):
        status: IssueSeverity = "error"
    elif any(issue.severity == "warning" for issue in issues):
        status = "warning"
    else:
        status = "ok"
    return ConfigDiagnostics(status=status, path=str(path), config_exists=path.exists(), issues=issues)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file, with env var substitution."""
    global _config, _config_path, _config_mtime

    config_path = _resolve_config_path(config_path)
    mtime = _current_mtime(config_path)
    if _config is not None and _config_path == config_path and _config_mtime == mtime:
        return _config

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}
    raw = _migrate_config(_expand_env_vars(raw))

    # Parse models
    models = []
    for m in raw.get("models", []):
        models.append(
            ModelConfig(
                name=m.get("name", ""),
                display_name=m.get("display_name", ""),
                provider=m.get("provider", "openai"),
                model=m.get("model", ""),
                api_key=m.get("api_key", ""),
                base_url=m.get("base_url", ""),
                max_tokens=m.get("max_tokens", 4096),
                supports_streaming=m.get("supports_streaming", True),
            )
        )

    # Parse knowledge config
    kb_raw = raw.get("knowledge", {})
    embed_raw = kb_raw.get("embedding", {})
    vector_raw = kb_raw.get("vector_store", {})
    graph_raw = kb_raw.get("graph_store", {})
    rerank_raw = kb_raw.get("rerank", {})
    object_raw = kb_raw.get("object_store", {})
    buckets_raw = object_raw.get("buckets", {}) if isinstance(object_raw.get("buckets", {}), dict) else {}
    knowledge = KnowledgeConfig(
        milvus_host=str(_env_or_config("MILVUS_HOST", kb_raw.get("milvus_host"), "localhost")),
        milvus_port=int(_env_or_config("MILVUS_PORT", kb_raw.get("milvus_port"), "19530")),
        neo4j_uri=str(_env_or_config("NEO4J_URI", kb_raw.get("neo4j_uri"), "bolt://localhost:7687")),
        neo4j_user=str(_env_or_config("NEO4J_USER", kb_raw.get("neo4j_user"), "neo4j")),
        neo4j_password=str(_env_or_config("NEO4J_PASSWORD", kb_raw.get("neo4j_password"), "")),
        embed_model=str(_env_or_config("EMBED_MODEL", embed_raw.get("model"), "BAAI/bge-large-zh-v1.5")),
        embed_base_url=str(_env_or_config("EMBED_BASE_URL", embed_raw.get("base_url"), "")),
        embed_api_key=str(_env_or_config("EMBED_API_KEY", embed_raw.get("api_key"), "")),
        embed_dimension=int(_env_or_config("EMBED_DIMENSION", embed_raw.get("dimension"), "1024")),
        vector_store_enabled=_as_bool(vector_raw.get("enabled", True)),
        vector_store_provider=vector_raw.get("provider", "milvus"),
        vector_store_uri=str(_env_or_config("MILVUS_URI", vector_raw.get("uri"), "")),
        graph_store_enabled=_as_bool(graph_raw.get("enabled", False)),
        graph_store_provider=graph_raw.get("provider", "neo4j"),
        graph_store_uri=str(_env_or_config("NEO4J_URI", graph_raw.get("uri", kb_raw.get("neo4j_uri")), "")),
        rerank_model=rerank_raw.get("model", os.environ.get("NEXAGENT_RERANK_MODEL", "")),
        rerank_top_k_multiplier=int(rerank_raw.get("top_k_multiplier", 3)),
        storage_backend=str(_env_or_config("NEXAGENT_KB_STORAGE", kb_raw.get("storage_backend"), "legacy")),
        object_store_endpoint=str(_env_or_config("MINIO_ENDPOINT", object_raw.get("endpoint"), "localhost:9000")),
        object_store_access_key=str(_env_or_config("MINIO_ACCESS_KEY", object_raw.get("access_key"), "minioadmin")),
        object_store_secret_key=str(_env_or_config("MINIO_SECRET_KEY", object_raw.get("secret_key"), "minioadmin")),
        object_store_secure=_as_bool(_env_or_config("MINIO_SECURE", object_raw.get("secure"), "0")),
        object_store_public_endpoint=str(
            _env_or_config("MINIO_PUBLIC_ENDPOINT", object_raw.get("public_endpoint"), "")
        ),
        raw_bucket=str(_env_or_config("NEXAGENT_KB_RAW_BUCKET", buckets_raw.get("raw"), "kb-raw")),
        parsed_bucket=str(_env_or_config("NEXAGENT_KB_PARSED_BUCKET", buckets_raw.get("parsed"), "kb-parsed")),
        chunks_bucket=str(_env_or_config("NEXAGENT_KB_CHUNKS_BUCKET", buckets_raw.get("chunks"), "kb-chunks")),
        eval_bucket=str(_env_or_config("NEXAGENT_KB_EVAL_BUCKET", buckets_raw.get("eval"), "kb-eval")),
        artifacts_bucket=str(
            _env_or_config("NEXAGENT_KB_ARTIFACTS_BUCKET", buckets_raw.get("artifacts"), "kb-artifacts")
        ),
    )

    # Parse web_search config
    ws_raw = raw.get("web_search", {})
    ws_providers_raw = ws_raw.get("providers", {}) if isinstance(ws_raw.get("providers", {}), dict) else {}
    provider_keys = {
        "tavily": ws_raw.get("tavily_api_key", os.environ.get("TAVILY_API_KEY", "")),
        "brave": os.environ.get("BRAVE_SEARCH_API_KEY", ""),
        "serpapi": os.environ.get("SERPAPI_API_KEY", ""),
        "bing": os.environ.get("BING_SEARCH_API_KEY", ""),
        "exa": os.environ.get("EXA_API_KEY", ""),
    }
    provider_base_urls = {
        "searxng": os.environ.get("SEARXNG_BASE_URL", ""),
    }
    enabled_providers = ws_raw.get("enabled_providers")
    if not isinstance(enabled_providers, list):
        enabled_providers = ["duckduckgo"]

    for provider_id, provider_raw in ws_providers_raw.items():
        if not isinstance(provider_raw, dict):
            continue
        if provider_id in provider_keys:
            provider_keys[provider_id] = provider_raw.get("api_key", provider_keys[provider_id])
        if provider_id in provider_base_urls:
            provider_base_urls[provider_id] = provider_raw.get("base_url", provider_base_urls[provider_id])
        if provider_raw.get("enabled") and provider_id not in enabled_providers:
            enabled_providers.append(provider_id)

    web_search = WebSearchConfig(
        provider=ws_raw.get("provider", "auto"),
        preferred_provider=ws_raw.get("preferred_provider", "duckduckgo"),
        enabled_providers=[str(item) for item in enabled_providers],
        provider_keys={key: str(value or "") for key, value in provider_keys.items()},
        provider_base_urls={key: str(value or "") for key, value in provider_base_urls.items()},
        tavily_api_key=provider_keys.get("tavily", ""),
        max_results=int(ws_raw.get("max_results", 5)),
        fetch_max_chars=int(ws_raw.get("fetch_max_chars", 12000)),
    )

    # Parse speech (ASR/TTS) config
    speech_raw = raw.get("speech", {}) if isinstance(raw.get("speech"), dict) else {}
    asr_raw = speech_raw.get("asr", {}) if isinstance(speech_raw.get("asr"), dict) else {}
    tts_raw = speech_raw.get("tts", {}) if isinstance(speech_raw.get("tts"), dict) else {}
    speech = SpeechConfig(
        asr_enabled=_as_bool(asr_raw.get("enabled", True)),
        asr_provider_id=str(asr_raw.get("provider_id", "") or ""),
        asr_model=str(asr_raw.get("model", SpeechConfig().asr_model)),
        asr_language=str(asr_raw.get("language", "") or ""),
        tts_enabled=_as_bool(tts_raw.get("enabled", True)),
        tts_provider_id=str(tts_raw.get("provider_id", "") or ""),
        tts_model=str(tts_raw.get("model", SpeechConfig().tts_model)),
        tts_voice=str(tts_raw.get("voice", SpeechConfig().tts_voice)),
        tts_format=str(tts_raw.get("format", "mp3") or "mp3"),
        tts_sample_rate=int(tts_raw.get("sample_rate", 32000) or 32000),
        tts_speed=float(tts_raw.get("speed", 1.0) or 1.0),
    )

    # Parse MCP servers
    mcp_servers = []
    for srv in raw.get("mcp_servers", []):
        mcp_servers.append(MCPServerConfig(
            name=srv.get("name", ""),
            transport=srv.get("transport", "stdio"),
            command=srv.get("command", []),
            url=srv.get("url", ""),
            env=srv.get("env", {}),
        ))

    # Parse sandbox config
    sb_raw = raw.get("sandbox", {})
    sb_local = sb_raw.get("local", {})
    sb_docker = sb_raw.get("docker", {})
    sandbox = SandboxConfig(
        enabled=sb_raw.get("enabled", True),
        provider=sb_raw.get("provider", "local"),
        base_dir=sb_local.get("base_dir", sb_raw.get("base_dir", ".nexagent")),
        timeout_seconds=int(sb_raw.get("timeout_seconds", 30)),
        max_output_chars=int(sb_raw.get("max_output_chars", 8000)),
        docker_image=sb_docker.get("image", sb_raw.get("docker_image", "python:3.12-slim")),
        docker_memory_limit=sb_docker.get("memory_limit", sb_raw.get("docker_memory_limit", "512m")),
        docker_cpu_quota=int(sb_docker.get("cpu_quota", sb_raw.get("docker_cpu_quota", 50000))),
        docker_network=sb_docker.get("network", sb_raw.get("docker_network", "none")),
        audit_enabled=_as_bool(sb_raw.get("audit_enabled", True)),
        audit_path=sb_raw.get("audit_path", ".nexagent/sandbox_audit.jsonl"),
        allow_bash=_as_bool(sb_raw.get("allow_bash", True)),
        blocked_commands=sb_raw.get("blocked_commands", SandboxConfig().blocked_commands),
    )

    tracing_raw = raw.get("tracing", {})
    langsmith_raw = tracing_raw.get("langsmith", {})
    langfuse_raw = tracing_raw.get("langfuse", {})
    tracing = TracingConfig(
        langsmith=LangSmithConfig(
            enabled=_as_bool(langsmith_raw.get("enabled", os.environ.get("LANGSMITH_TRACING", "false"))),
            api_key=langsmith_raw.get("api_key", os.environ.get("LANGCHAIN_API_KEY", "")),
            project=langsmith_raw.get("project", os.environ.get("LANGSMITH_PROJECT", "nexagent")),
            endpoint=langsmith_raw.get("endpoint", os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")),
        ),
        langfuse=LangfuseConfig(
            enabled=_as_bool(langfuse_raw.get("enabled", os.environ.get("LANGFUSE_TRACING", "false"))),
            public_key=langfuse_raw.get("public_key", os.environ.get("LANGFUSE_PUBLIC_KEY", "")),
            secret_key=langfuse_raw.get("secret_key", os.environ.get("LANGFUSE_SECRET_KEY", "")),
            host=langfuse_raw.get("host", os.environ.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")),
        ),
    )

    _config = AppConfig(
        models=models,
        knowledge=knowledge,
        web_search=web_search,
        speech=speech,
        mcp_servers=mcp_servers,
        sandbox=sandbox,
        tracing=tracing,
        debug=raw.get("debug", False),
        config_version=int(raw.get("config_version", CONFIG_VERSION)),
        skills_dir=raw.get("skills_dir", ""),
        default_model=raw.get("default_model", models[0].name if models else ""),
    )
    _config_path = config_path
    _config_mtime = mtime
    return _config


def get_config() -> AppConfig:
    """Get the current configuration (load if needed)."""
    return load_config()
