"""Settings router — LLM provider management.

Endpoints:
  GET    /api/settings/providers            list all providers
  POST   /api/settings/providers            create provider
  PUT    /api/settings/providers/{id}       update provider
  DELETE /api/settings/providers/{id}       delete provider
  POST   /api/settings/providers/{id}/test  test connectivity
  GET    /api/settings/providers/{id}/models fetch remote model list
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request / Response schemas ─────────────────────────────────────────────────

class ProviderCreate(BaseModel):
    id: str | None = None
    name: str
    provider_type: str                          # openai / anthropic / google / ollama
    base_url: str = ""
    models_endpoint: str = "/models"
    api_key_env: str = ""
    api_key: str = ""
    capabilities: list[str] = ["chat"]
    models: list[str] = []
    model_configs: list[dict] = []
    is_enabled: bool = True
    is_default: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    models_endpoint: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None                  # empty string = clear key
    capabilities: list[str] | None = None
    models: list[str] | None = None
    model_configs: list[dict] | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


SearchProviderId = Literal["auto", "duckduckgo", "tavily", "brave", "serpapi", "bing", "exa", "searxng"]
SearchServiceId = Literal["duckduckgo", "tavily", "brave", "serpapi", "bing", "exa", "searxng"]


class SearchProviderUpdate(BaseModel):
    enabled: bool = False
    api_key: str | None = None
    base_url: str | None = None


class SearchConfigUpdate(BaseModel):
    provider: SearchProviderId = "auto"
    preferred_provider: SearchServiceId = "duckduckgo"
    enabled_providers: list[SearchServiceId] = ["duckduckgo"]
    max_results: int = 5
    fetch_max_chars: int = 12000
    tavily_api_key: str | None = None
    providers: dict[str, SearchProviderUpdate] = {}


class SearchTestRequest(BaseModel):
    query: str = "NexAgent web search test"
    url: str = ""
    mode: Literal["search", "fetch"] = "search"
    provider: SearchProviderId | None = None
    preferred_provider: SearchServiceId | None = None
    enabled_providers: list[SearchServiceId] | None = None
    max_results: int | None = None
    fetch_max_chars: int | None = None
    tavily_api_key: str | None = None
    providers: dict[str, SearchProviderUpdate] = {}


class ModelProbeRequest(BaseModel):
    provider_id: str
    model_id: str
    capability: Literal["chat", "embedding", "rerank"]
    sample_text: str = "NexAgent model connectivity test"


class SpeechConfigUpdate(BaseModel):
    asr_enabled: bool = True
    asr_base_url: str = ""
    asr_api_key: str | None = None
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    asr_language: str = ""
    tts_enabled: bool = True
    tts_base_url: str = ""
    tts_api_key: str | None = None
    tts_model: str = "FunAudioLLM/CosyVoice2-0.5B"
    tts_voice: str = "FunAudioLLM/CosyVoice2-0.5B:alex"
    tts_format: str = "mp3"
    tts_sample_rate: int = 32000
    tts_speed: float = 1.0


class ImageConfigUpdate(BaseModel):
    enabled: bool = True
    base_url: str = ""
    api_key: str | None = None
    model: str = "Kwai-Kolors/Kolors"
    size: str = "1024x1024"


class MemoryConfigUpdate(BaseModel):
    enabled: bool = True
    injection_enabled: bool = True
    extraction_enabled: bool = True
    max_facts: int = 100
    max_injection_facts: int = 15
    min_confidence: float = 0.0
    model_name: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _invalidate_model_cache() -> None:
    """Tell the model factory to re-read providers from DB."""
    try:
        from nexagent.models.factory import invalidate_provider_cache
        invalidate_provider_cache()
    except Exception:
        pass


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


def _provider_api_key(provider, decrypt_key) -> str:
    import os

    env_name = provider.api_key_env or _provider_env_fallback(provider.name, provider.base_url or "")
    if env_name:
        env_value = os.environ.get(env_name, "")
        if env_value:
            return env_value
    return decrypt_key(provider.api_key_enc or "")


def _model_type(model_id: str) -> str:
    value = model_id.lower()
    if "rerank" in value:
        return "rerank"
    if "embed" in value or "bge-m3" in value or "bge-large" in value or "text-embedding" in value:
        return "embedding"
    return "chat"


def _normalise_remote_model(model_id: str) -> dict:
    model_type = _model_type(model_id)
    item = {
        "id": model_id,
        "display_name": model_id,
        "type": model_type,
    }
    if model_type == "embedding":
        item["dimension"] = 1024
        item["batch_size"] = 32
    if model_type == "rerank":
        item["batch_size"] = 16
    return item


def _config_payload() -> dict:
    from nexagent.config import get_config

    config = get_config()
    return {
        "config_version": config.config_version,
        "default_model": config.default_model,
        "debug": config.debug,
        "tracing": {
            "langsmith": {
                "enabled": config.tracing.langsmith.enabled,
                "project": config.tracing.langsmith.project,
                "api_key_configured": bool(config.tracing.langsmith.api_key),
            },
            "langfuse": {
                "enabled": config.tracing.langfuse.enabled,
                "host": config.tracing.langfuse.host,
                "public_key_configured": bool(config.tracing.langfuse.public_key),
                "secret_key_configured": bool(config.tracing.langfuse.secret_key),
            },
        },
        "sandbox": {
            "enabled": config.sandbox.enabled,
            "provider": config.sandbox.provider,
            "base_dir": config.sandbox.base_dir,
            "timeout_seconds": config.sandbox.timeout_seconds,
            "max_output_chars": config.sandbox.max_output_chars,
            "audit_enabled": config.sandbox.audit_enabled,
            "audit_path": config.sandbox.audit_path,
            "allow_bash": config.sandbox.allow_bash,
        },
        "knowledge": {
            "vector_store_enabled": config.knowledge.vector_store_enabled,
            "vector_store_provider": config.knowledge.vector_store_provider,
            "graph_store_enabled": config.knowledge.graph_store_enabled,
            "graph_store_provider": config.knowledge.graph_store_provider,
            "rerank_model_configured": bool(config.knowledge.rerank_model),
            "rerank_top_k_multiplier": config.knowledge.rerank_top_k_multiplier,
        },
        "web_search": _search_config_payload(),
    }


def _search_config_payload() -> dict:
    from nexagent.config import get_config

    config = get_config().web_search
    providers = _search_provider_payloads(config)
    effective_provider = _search_effective_provider(
        config.provider,
        config.preferred_provider,
        config.enabled_providers,
        providers,
    )
    return {
        "provider": config.provider,
        "preferred_provider": config.preferred_provider,
        "enabled_providers": config.enabled_providers,
        "effective_provider": effective_provider,
        "max_results": config.max_results,
        "fetch_max_chars": config.fetch_max_chars,
        "tavily_api_key_configured": bool(config.tavily_api_key),
        "providers": providers,
    }


def _search_provider_payloads(config) -> list[dict]:
    definitions = [
        {
            "id": "duckduckgo",
            "name": "DuckDuckGo / DDGS",
            "recommended": False,
            "requires_api_key": False,
            "requires_base_url": False,
            "description": "免 API Key 的开发兜底方案，稳定性受本机网络和上游搜索服务限制。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "tavily",
            "name": "Tavily",
            "recommended": True,
            "requires_api_key": True,
            "requires_base_url": False,
            "description": "面向 Agent 的结构化联网搜索，适合生产环境、引用生成和深度研究。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "brave",
            "name": "Brave Search",
            "recommended": True,
            "requires_api_key": True,
            "requires_base_url": False,
            "description": "通用 Web 搜索 API，延迟和稳定性通常优于免 Key 兜底服务。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "serpapi",
            "name": "SerpAPI",
            "recommended": False,
            "requires_api_key": True,
            "requires_base_url": False,
            "description": "聚合搜索结果 API，适合需要 Google 风格结果的场景。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "bing",
            "name": "Bing Web Search",
            "recommended": False,
            "requires_api_key": True,
            "requires_base_url": False,
            "description": "微软 Bing 官方搜索 API，适合企业订阅和稳定联网搜索。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "exa",
            "name": "Exa",
            "recommended": False,
            "requires_api_key": True,
            "requires_base_url": False,
            "description": "面向 AI 应用的语义搜索，适合研究型查询和内容发现。",
            "capabilities": ["web_search", "web_fetch"],
        },
        {
            "id": "searxng",
            "name": "SearxNG",
            "recommended": False,
            "requires_api_key": False,
            "requires_base_url": True,
            "description": "自托管元搜索服务，适合需要私有化部署和可控联网能力的场景。",
            "capabilities": ["web_search", "web_fetch"],
        },
    ]
    rows = []
    for item in definitions:
        provider_id = item["id"]
        api_key_configured = bool(config.provider_keys.get(provider_id))
        base_url = config.provider_base_urls.get(provider_id, "")
        base_url_configured = bool(base_url)
        configured = (
            True
            if provider_id == "duckduckgo"
            else api_key_configured if item["requires_api_key"]
            else base_url_configured if item["requires_base_url"]
            else True
        )
        rows.append({
            **item,
            "enabled": provider_id in config.enabled_providers and configured,
            "configured": configured,
            "api_key_configured": api_key_configured,
            "base_url": base_url,
        })
    return rows


def _search_effective_provider(provider: str, preferred: str, enabled: list[str], providers: list[dict]) -> str:
    available = [item["id"] for item in providers if item.get("enabled")]
    if provider != "auto":
        return provider if provider in available else ""
    if preferred in available:
        return preferred
    return available[0] if available else ""


def _read_config_yaml() -> tuple[dict, object]:
    from nexagent.config import _resolve_config_path  # type: ignore

    path = _resolve_config_path()
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="config.yaml root must be an object")
    return data, path


def _write_config_yaml(data: dict, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelProvider).order_by(ModelProvider.created_at))
        providers = result.scalars().all()
    return {"providers": [p.to_dict() for p in providers]}


@router.get("/config")
async def get_runtime_config():
    return _config_payload()


@router.post("/config/reload")
async def reload_runtime_config():
    from nexagent.config import reset_config_cache

    reset_config_cache()
    _invalidate_model_cache()
    return _config_payload()


@router.get("/search")
async def get_search_config():
    return _search_config_payload()


@router.put("/search")
async def update_search_config(body: SearchConfigUpdate):
    from nexagent.config import reset_config_cache

    if body.max_results < 1 or body.max_results > 20:
        raise HTTPException(status_code=422, detail="max_results must be between 1 and 20")
    if body.fetch_max_chars < 1000 or body.fetch_max_chars > 50000:
        raise HTTPException(status_code=422, detail="fetch_max_chars must be between 1000 and 50000")

    data, path = _read_config_yaml()
    section = dict(data.get("web_search") or {})
    section["provider"] = body.provider
    section["preferred_provider"] = body.preferred_provider
    section["enabled_providers"] = list(dict.fromkeys(["duckduckgo", *body.enabled_providers]))
    section["max_results"] = body.max_results
    section["fetch_max_chars"] = body.fetch_max_chars
    if body.tavily_api_key is not None:
        if body.tavily_api_key.strip():
            section["tavily_api_key"] = body.tavily_api_key.strip()
        else:
            section.pop("tavily_api_key", None)

    providers_section = dict(section.get("providers") or {})
    for provider_id, patch in body.providers.items():
        current = dict(providers_section.get(provider_id) or {})
        current["enabled"] = provider_id in section["enabled_providers"]
        if patch.api_key is not None and "••" not in patch.api_key:
            if patch.api_key.strip():
                current["api_key"] = patch.api_key.strip()
            else:
                current.pop("api_key", None)
        if patch.base_url is not None:
            if patch.base_url.strip():
                current["base_url"] = patch.base_url.strip()
            else:
                current.pop("base_url", None)
        providers_section[provider_id] = current
    section["providers"] = providers_section
    data["web_search"] = section
    _write_config_yaml(data, path)
    reset_config_cache()
    return _search_config_payload()


def _memory_config_payload() -> dict:
    from nexagent.config import get_config

    cfg = get_config().memory
    return {
        "enabled": cfg.enabled,
        "injection_enabled": cfg.injection_enabled,
        "extraction_enabled": cfg.extraction_enabled,
        "max_facts": cfg.max_facts,
        "max_injection_facts": cfg.max_injection_facts,
        "min_confidence": cfg.min_confidence,
        "model_name": cfg.model_name,
    }


@router.get("/memory")
async def get_memory_config():
    return _memory_config_payload()


@router.put("/memory")
async def update_memory_config(body: MemoryConfigUpdate):
    from nexagent.config import reset_config_cache

    if not 1 <= body.max_facts <= 1000:
        raise HTTPException(status_code=422, detail="max_facts must be between 1 and 1000")
    if not 1 <= body.max_injection_facts <= 100:
        raise HTTPException(status_code=422, detail="max_injection_facts must be between 1 and 100")
    if not 0.0 <= body.min_confidence <= 1.0:
        raise HTTPException(status_code=422, detail="min_confidence must be between 0.0 and 1.0")

    data, path = _read_config_yaml()
    section = dict(data.get("memory") or {})
    section["enabled"] = body.enabled
    section["injection_enabled"] = body.injection_enabled
    section["extraction_enabled"] = body.extraction_enabled
    section["max_facts"] = body.max_facts
    section["max_injection_facts"] = body.max_injection_facts
    section["min_confidence"] = body.min_confidence
    section["model_name"] = body.model_name.strip()
    data["memory"] = section
    _write_config_yaml(data, path)
    reset_config_cache()
    return _memory_config_payload()


def _speech_config_payload() -> dict:
    from nexagent.services.speech import speech_status

    return speech_status()


def _image_config_payload() -> dict:
    from nexagent.services.image_service import image_status

    return image_status()


def _resolve_secret(incoming: str | None, existing: str) -> str:
    """Keep the stored secret when the client sends the masked placeholder or None."""
    if incoming is None:
        return existing
    if "•" in incoming:
        return existing
    return incoming.strip()


@router.get("/speech")
async def get_speech_config():
    return _speech_config_payload()


@router.put("/speech")
async def update_speech_config(body: SpeechConfigUpdate):
    from nexagent.config import reset_config_cache

    if body.tts_sample_rate < 8000 or body.tts_sample_rate > 48000:
        raise HTTPException(status_code=422, detail="tts_sample_rate must be between 8000 and 48000")
    if body.tts_speed < 0.5 or body.tts_speed > 2.0:
        raise HTTPException(status_code=422, detail="tts_speed must be between 0.5 and 2.0")

    data, path = _read_config_yaml()
    section = dict(data.get("speech") or {})
    prev_asr = dict(section.get("asr") or {})
    prev_tts = dict(section.get("tts") or {})
    section["asr"] = {
        "enabled": body.asr_enabled,
        "base_url": body.asr_base_url.strip(),
        "api_key": _resolve_secret(body.asr_api_key, str(prev_asr.get("api_key", ""))),
        "model": body.asr_model.strip(),
        "language": body.asr_language.strip(),
    }
    section["tts"] = {
        "enabled": body.tts_enabled,
        "base_url": body.tts_base_url.strip(),
        "api_key": _resolve_secret(body.tts_api_key, str(prev_tts.get("api_key", ""))),
        "model": body.tts_model.strip(),
        "voice": body.tts_voice.strip(),
        "format": (body.tts_format or "mp3").strip() or "mp3",
        "sample_rate": body.tts_sample_rate,
        "speed": body.tts_speed,
    }
    data["speech"] = section
    _write_config_yaml(data, path)
    reset_config_cache()
    return _speech_config_payload()


@router.get("/image")
async def get_image_config():
    return _image_config_payload()


@router.put("/image")
async def update_image_config(body: ImageConfigUpdate):
    from nexagent.config import reset_config_cache

    data, path = _read_config_yaml()
    section = dict(data.get("image") or {})
    section = {
        "enabled": body.enabled,
        "base_url": body.base_url.strip(),
        "api_key": _resolve_secret(body.api_key, str(section.get("api_key", ""))),
        "model": body.model.strip(),
        "size": (body.size or "1024x1024").strip() or "1024x1024",
    }
    data["image"] = section
    _write_config_yaml(data, path)
    reset_config_cache()
    return _image_config_payload()


@router.post("/search/test")
async def test_search_config(body: SearchTestRequest):
    start = time.monotonic()
    try:
        if body.mode == "fetch":
            from nexagent.tools.builtin.web_fetch import get_web_fetch_tool

            if not body.url.strip():
                raise ValueError("URL is required for web_fetch test")
            tool = get_web_fetch_tool()
            result = tool.invoke({"url": body.url.strip()})
        else:
            from nexagent.config import get_config
            from nexagent.tools.builtin.web_search import get_web_search_tool, get_web_search_tool_for

            cfg = get_config().web_search
            if body.provider:
                provider_keys = dict(cfg.provider_keys)
                provider_base_urls = dict(cfg.provider_base_urls)
                for provider_id, patch in body.providers.items():
                    if patch.api_key is not None and "••" not in patch.api_key:
                        provider_keys[provider_id] = patch.api_key
                    if patch.base_url is not None:
                        provider_base_urls[provider_id] = patch.base_url
                if body.tavily_api_key is not None:
                    provider_keys["tavily"] = body.tavily_api_key
                tool = get_web_search_tool_for(
                    provider=body.provider,
                    preferred_provider=body.preferred_provider or cfg.preferred_provider,
                    enabled_providers=body.enabled_providers or cfg.enabled_providers,
                    max_results=body.max_results or cfg.max_results,
                    provider_keys=provider_keys,
                    provider_base_urls=provider_base_urls,
                )
            else:
                tool = get_web_search_tool()
            result = tool.invoke({"query": body.query.strip() or "NexAgent web search test"})
        text = str(result)
        ok = not text.lower().startswith(("web search failed", "web fetch failed", "error:"))
        return {
            "ok": ok,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "message": text[:1200],
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - start) * 1000),
            "message": str(exc),
        }


@router.post("/providers", status_code=201)
async def create_provider(body: ProviderCreate):
    from nexagent.db.crypto import encrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        if body.is_default:
            # Clear other defaults
            result = await session.execute(select(ModelProvider).where(ModelProvider.is_default == True))  # noqa
            for p in result.scalars().all():
                p.is_default = False

        provider_kwargs = {
            "name": body.name,
            "provider_type": body.provider_type,
            "base_url": body.base_url or None,
            "models_endpoint": body.models_endpoint or "/models",
            "api_key_env": body.api_key_env or None,
            "api_key_enc": encrypt_key(body.api_key) if body.api_key else None,
            "is_enabled": body.is_enabled,
            "is_default": body.is_default,
        }
        if body.id:
            provider_kwargs["id"] = body.id
        provider = ModelProvider(**provider_kwargs)
        provider.capabilities = body.capabilities or ["chat"]
        provider.model_configs = body.model_configs or [
            {"id": model, "display_name": model, "type": "chat"} for model in body.models
        ]
        provider.models = body.models or [item.get("id") for item in provider.model_configs if item.get("id")]
        session.add(provider)
        await session.commit()
        await session.refresh(provider)
        data = provider.to_dict()

    _invalidate_model_cache()
    return data


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: ProviderUpdate):
    from nexagent.db.crypto import encrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        if body.name is not None:
            provider.name = body.name
        if body.provider_type is not None:
            provider.provider_type = body.provider_type
        if body.base_url is not None:
            provider.base_url = body.base_url or None
        if body.models_endpoint is not None:
            provider.models_endpoint = body.models_endpoint or "/models"
        if body.api_key_env is not None:
            provider.api_key_env = body.api_key_env or None
        if body.api_key is not None:
            provider.api_key_enc = encrypt_key(body.api_key) if body.api_key else None
        if body.capabilities is not None:
            provider.capabilities = body.capabilities
        if body.model_configs is not None:
            provider.model_configs = body.model_configs
            provider.models = [item.get("id") for item in body.model_configs if item.get("id")]
        if body.models is not None:
            provider.models = body.models
            if body.model_configs is None:
                existing = {
                    item.get("id"): item
                    for item in (provider.model_configs or [])
                    if isinstance(item, dict) and item.get("id")
                }
                provider.model_configs = [
                    existing.get(model, {"id": model, "display_name": model, "type": "chat"})
                    for model in body.models
                ]
        if body.is_enabled is not None:
            provider.is_enabled = body.is_enabled
        if body.is_default is not None:
            if body.is_default:
                result = await session.execute(
                    select(ModelProvider).where(ModelProvider.is_default == True)  # noqa
                )
                for p in result.scalars().all():
                    if p.id != provider_id:
                        p.is_default = False
            provider.is_default = body.is_default

        await session.commit()
        await session.refresh(provider)
        data = provider.to_dict()

    _invalidate_model_cache()
    return data


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str):
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        await session.delete(provider)
        await session.commit()

    _invalidate_model_cache()


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str):
    """Send a minimal request to verify the provider is reachable."""
    from nexagent.db.crypto import decrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = _provider_api_key(provider, decrypt_key)
        base_url = provider.base_url or ""
        provider_type = provider.provider_type
        models_list = provider.models or []

    test_model = models_list[0] if models_list else _default_test_model(provider_type)

    start = time.monotonic()
    try:
        result = await _probe_model(provider_type, test_model, api_key, base_url)
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"ok": True, "latency_ms": latency_ms, "message": result}
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"ok": False, "latency_ms": latency_ms, "message": str(exc)}


@router.post("/providers/{provider_id}/test-capabilities")
async def test_provider_capabilities(provider_id: str):
    """Return capability checks for every model configured on a provider."""
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal
    from nexagent.models.factory import get_model_capabilities

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        models_list = provider.models or [_default_test_model(provider.provider_type)]
        provider_type = provider.provider_type

    checks = []
    for model in models_list:
        capabilities = get_model_capabilities(provider_type, model, model)
        checks.append(
            {
                "model": model,
                "capabilities": capabilities,
                "tests": {
                    "text": {"ok": True, "message": "文本对话可测试"},
                    "tool_calling": {
                        "ok": bool(capabilities.get("supports_tool_calling")),
                        "message": (
                            "支持工具调用"
                            if capabilities.get("supports_tool_calling")
                            else "未声明工具调用能力"
                        ),
                    },
                    "vision": {
                        "ok": bool(capabilities.get("supports_vision")),
                        "message": "支持图片识别" if capabilities.get("supports_vision") else "未声明图片识别能力",
                    },
                    "image_generation": {
                        "ok": bool(capabilities.get("supports_image_generation")),
                        "message": (
                            "支持图片生成"
                            if capabilities.get("supports_image_generation")
                            else "未声明图片生成能力"
                        ),
                    },
                    "video_generation": {
                        "ok": bool(capabilities.get("supports_video_generation")),
                        "message": (
                            "支持视频生成"
                            if capabilities.get("supports_video_generation")
                            else "未声明视频生成能力"
                        ),
                    },
                    "reasoning": {
                        "ok": bool(capabilities.get("supports_native_reasoning")),
                        "message": (
                            "支持原生推理"
                            if capabilities.get("supports_native_reasoning")
                            else "未声明原生推理能力"
                        ),
                    },
                },
            }
        )
    return {"provider_id": provider_id, "models": checks}


@router.post("/models/test")
async def test_provider_model(req: ModelProbeRequest):
    """Probe a concrete chat, embedding, or rerank model from the configured providers."""
    from nexagent.db.crypto import decrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    provider_id = req.provider_id.strip()
    model_id = req.model_id.strip()
    if not provider_id or not model_id:
        raise HTTPException(status_code=400, detail="provider_id and model_id are required")

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        configs = provider.model_configs or []
        models = provider.models or []
        configured = next((item for item in configs if item.get("id") == model_id), None)
        if model_id not in models and configured is None:
            raise HTTPException(
                status_code=404, detail=f"Model '{model_id}' is not configured on provider '{provider_id}'"
            )
        if configured and configured.get("type") != req.capability:
            raise HTTPException(
                status_code=400,
                detail=f"Model '{model_id}' is configured as {configured.get('type')}, not {req.capability}",
            )
        api_key = _provider_api_key(provider, decrypt_key)
        base_url = (configured or {}).get("base_url_override") or provider.base_url or ""
        provider_type = (configured or {}).get("protocol_override") or provider.provider_type

    start = time.monotonic()
    try:
        if req.capability == "chat":
            content = await _probe_model(provider_type, model_id, api_key, base_url)
            result = {"message": content}
        elif req.capability == "embedding":
            result = await _probe_embedding_model(provider_type, model_id, api_key, base_url, req.sample_text)
        else:
            result = await _probe_rerank_model(provider_type, model_id, api_key, base_url, req.sample_text)
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": True,
            "provider_id": provider_id,
            "model_id": model_id,
            "capability": req.capability,
            "latency_ms": latency_ms,
            **result,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "ok": False,
            "provider_id": provider_id,
            "model_id": model_id,
            "capability": req.capability,
            "latency_ms": latency_ms,
            "message": str(exc),
        }


@router.get("/providers/{provider_id}/models")
async def fetch_provider_models(provider_id: str):
    """Attempt to fetch available models from an OpenAI-compatible /models endpoint."""
    from nexagent.db.crypto import decrypt_key
    from nexagent.db.models import ModelProvider
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        provider = await session.get(ModelProvider, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        api_key = _provider_api_key(provider, decrypt_key)
        base_url = provider.base_url or ""
        models_endpoint = provider.models_endpoint or "/models"
        provider_type = provider.provider_type
        existing_models = provider.models or []
        existing_model_configs = provider.model_configs or []

    try:
        models = await _list_remote_models(provider_type, api_key, base_url, models_endpoint)
        return {"models": models, "model_configs": [_normalise_remote_model(model) for model in models]}
    except Exception as exc:
        detail = _remote_model_listing_error(exc, base_url, models_endpoint)
        fallback_configs = existing_model_configs or [_normalise_remote_model(model) for model in existing_models]
        if fallback_configs:
            return {
                "models": [item.get("id") for item in fallback_configs if item.get("id")],
                "model_configs": fallback_configs,
                "warning": detail,
            }
        raise HTTPException(status_code=502, detail=detail) from exc


# ── Internal helpers ───────────────────────────────────────────────────────────

def _default_test_model(provider_type: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-haiku-4-5-20251001",
        "google": "gemini-2.0-flash",
        "ollama": "llama3",
    }.get(provider_type, "gpt-4o-mini")


async def _probe_model(provider_type: str, model: str, api_key: str, base_url: str) -> str:
    """Send a tiny chat request to verify credentials work."""
    import httpx

    if provider_type == "openai":
        endpoint = (base_url.rstrip("/") + "/chat/completions") if base_url else "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    if provider_type == "anthropic":
        import anthropic  # type: ignore
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "hi"}]
        )
        return msg.content[0].text

    if provider_type == "ollama":
        endpoint = (base_url.rstrip("/") + "/api/chat") if base_url else "http://localhost:11434/api/chat"
        payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": False}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    raise ValueError(f"Cannot test provider type '{provider_type}' automatically")


async def _probe_embedding_model(provider_type: str, model: str, api_key: str, base_url: str, sample_text: str) -> dict:
    """Send a minimal embedding request and report the returned vector dimension."""
    import httpx

    if provider_type != "openai":
        raise ValueError(f"Embedding probe currently supports OpenAI-compatible providers only, got '{provider_type}'")
    if not api_key:
        raise ValueError("API key is not configured. Set API Key first.")
    endpoint = (base_url.rstrip("/") + "/embeddings") if base_url else "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "input": sample_text or "NexAgent embedding test"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    vector = ((data.get("data") or [{}])[0] or {}).get("embedding") or []
    if not isinstance(vector, list) or not vector:
        raise ValueError("Embedding endpoint returned no vector")
    return {"dimension": len(vector), "message": f"Embedding model returned {len(vector)} dimensions."}


async def _probe_rerank_model(provider_type: str, model: str, api_key: str, base_url: str, sample_text: str) -> dict:
    """Probe a rerank model using the common OpenAI-compatible /rerank shape."""
    import httpx

    if provider_type != "openai":
        raise ValueError(f"Rerank probe currently supports OpenAI-compatible providers only, got '{provider_type}'")
    if not api_key:
        raise ValueError("API key is not configured. Set API Key first.")
    endpoint = (base_url.rstrip("/") + "/rerank") if base_url else "https://api.openai.com/v1/rerank"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    query = sample_text or "NexAgent rerank test"
    payload = {
        "model": model,
        "query": query,
        "documents": [query, "A different unrelated document."],
        "top_n": 2,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results") or data.get("data") or []
    score = None
    if results:
        first = results[0]
        score = first.get("relevance_score", first.get("score")) if isinstance(first, dict) else None
    return {"score": score, "message": "Rerank endpoint responded successfully."}


async def _list_remote_models(
    provider_type: str,
    api_key: str,
    base_url: str,
    models_endpoint: str = "/models",
) -> list[str]:
    import httpx

    if provider_type == "openai":
        if not api_key:
            raise ValueError("API key is not configured. Set API Key first.")
        endpoint_path = models_endpoint if models_endpoint.startswith("/") else f"/{models_endpoint}"
        endpoint = (base_url.rstrip("/") + endpoint_path) if base_url else "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(endpoint, headers=headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = resp.text[:300]
                raise ValueError(f"{resp.status_code} from {endpoint}: {detail}") from exc
            data = resp.json()
            items = data.get("data", data.get("models", []))
            if not isinstance(items, list):
                raise ValueError("Provider response does not contain a model list.")
            result = []
            for item in items:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict) and item.get("id"):
                    result.append(str(item["id"]))
            return sorted(set(result))

    raise ValueError(f"Auto model listing not supported for provider type '{provider_type}'")


def _remote_model_listing_error(exc: Exception, base_url: str, models_endpoint: str) -> str:
    endpoint_path = models_endpoint if models_endpoint.startswith("/") else f"/{models_endpoint}"
    endpoint = (base_url.rstrip("/") + endpoint_path) if base_url else endpoint_path
    text = str(exc)
    if 'Required parameter "model" missing' in text or endpoint_path.rstrip("/") == "/model":
        return (
            f"无法从 {endpoint} 拉取模型列表：当前路径是单模型查询接口，需要 model 参数，不是列表接口。"
            "请把“模型列表路径”改为 /models；如果该服务商不提供 /models，请使用“手动添加”维护模型。"
        )
    return f"Failed to fetch models: {text}"
