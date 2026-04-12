"""Model factory -load a LangChain chat model from config or DB providers.

Lookup order:
  1. DB ModelProvider table (hot-reloadable, managed via /api/settings/providers)
  2. config.yaml models list
  3. Fallback: pass the name directly to init_chat_model (provider/model format)

Thinking mode:
Reasoning modes:
  fast / balanced / deep / ultra. Models that expose native reasoning receive
  provider-specific parameters; other text models still receive a generic
  reasoning profile through the agent system prompt.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from langchain_core.language_models import BaseChatModel

SUPPORTED_PROVIDERS = {"openai", "anthropic", "google", "ollama", "fake"}
REASONING_MODES = ("fast", "balanced", "deep", "ultra")

logger = logging.getLogger(__name__)

# Provider cache: list of dicts loaded from DB
# Invalidated by settings router after every write.
_provider_cache: list[dict] | None = None
_provider_cache_at: float = 0.0
_CACHE_TTL = 300.0  # seconds


def _stream_chunk_timeout() -> float | None:
    """How long an OpenAI-compatible stream may stay silent between chunks.

    NexAgent owns UI heartbeat and idle termination in chat_service, so this is
    disabled by default to avoid aborting valid long post-tool reasoning. Set
    NEXAGENT_STREAM_CHUNK_TIMEOUT_S to a positive value only when debugging
    provider-level stalled streams.
    """
    raw = os.getenv("NEXAGENT_STREAM_CHUNK_TIMEOUT_S", "0").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 75.0
    return None if value <= 0 else value


def invalidate_provider_cache() -> None:
    """Called by settings router after any provider CRUD operation."""
    global _provider_cache
    _provider_cache = None
    logger.debug("Model provider cache invalidated")


def _provider_api_key(provider: Any, decrypt_key: Any) -> str:
    env_name = getattr(provider, "api_key_env", None) or _provider_env_fallback(
        getattr(provider, "name", ""),
        getattr(provider, "base_url", "") or "",
    )
    if env_name:
        env_value = os.environ.get(env_name, "")
        if env_value:
            return env_value
    return decrypt_key(provider.api_key_enc or "")


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


def _get_db_providers() -> list[dict]:
    """Return providers from DB, using a TTL cache. Returns [] on any error."""
    global _provider_cache, _provider_cache_at

    now = time.monotonic()
    if _provider_cache is not None and (now - _provider_cache_at) < _CACHE_TTL:
        return _provider_cache

    try:
        from nexagent.db.crypto import decrypt_key
        from nexagent.db.models import ModelProvider

        async def _fetch():
            from sqlalchemy import select

            from nexagent.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ModelProvider).where(ModelProvider.is_enabled == True)  # noqa
                )
                return result.scalars().all()

        try:
            loop = asyncio.get_running_loop()
            # Can't await in sync context -schedule and use cached result for now
            if loop.is_running():
                # We're inside an async context but called from sync; return stale cache
                if _provider_cache is not None:
                    return _provider_cache
                return []
        except RuntimeError:
            pass

        # No running loop -run in a new event loop
        providers = asyncio.run(_fetch())
        _provider_cache = [
            {
                "id": p.id,
                "name": p.name,
                "provider_type": p.provider_type,
                "base_url": p.base_url or "",
                "api_key": _provider_api_key(p, decrypt_key),
                "models": p.models or [],
                "model_configs": p.model_configs or [],
                "is_default": p.is_default,
            }
            for p in providers
        ]
        _provider_cache_at = now
        return _provider_cache
    except Exception as exc:
        logger.debug("Could not load DB providers: %s", exc)
        return []


async def _get_db_providers_async() -> list[dict]:
    """Async version of DB provider fetch."""
    global _provider_cache, _provider_cache_at

    now = time.monotonic()
    if _provider_cache is not None and (now - _provider_cache_at) < _CACHE_TTL:
        return _provider_cache

    try:
        from sqlalchemy import select

        from nexagent.db.crypto import decrypt_key
        from nexagent.db.models import ModelProvider
        from nexagent.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ModelProvider).where(ModelProvider.is_enabled == True)  # noqa
            )
            providers = result.scalars().all()

        _provider_cache = [
            {
                "id": p.id,
                "name": p.name,
                "provider_type": p.provider_type,
                "base_url": p.base_url or "",
                "api_key": _provider_api_key(p, decrypt_key),
                "models": p.models or [],
                "model_configs": p.model_configs or [],
                "is_default": p.is_default,
            }
            for p in providers
        ]
        _provider_cache_at = now
        return _provider_cache
    except Exception as exc:
        logger.debug("Could not load DB providers (async): %s", exc)
        return []


def load_chat_model(
    model_name: str | None = None,
    thinking: bool = False,
    thinking_budget: int = 8000,
    reasoning_mode: str | None = None,
    reasoning_effort: str | None = None,
) -> BaseChatModel:
    """Return a ready-to-use LangChain chat model.

    ``model_name`` can be:
      - A logical name defined in config.yaml (e.g. "qwen-7b")
      - A DB provider model id (e.g. "gpt-4o" when a provider named "OpenAI" has that model)
      - A scoped DB provider model ref (e.g. "openai-main::gpt-4o")
      - provider/model format (e.g. "openai/gpt-4o") passed to init_chat_model
    """
    if not model_name:
        model_name = _default_model_name()

    if model_name in {"fake", "nexagent/fake", "test/fake"}:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        return FakeListChatModel(responses=["NexAgent test response."])

    reasoning_mode = _normalize_reasoning_mode(reasoning_mode, thinking)

    # 1. Try DB providers -match model_name against any chat model managed in Settings
    db_match = _find_in_db_providers(model_name)
    if db_match is not None:
        provider, model_id = db_match
        logger.debug("Loading model '%s' from DB provider '%s'", model_id, provider["name"])
        return _build_from_db_provider(
            provider,
            model_id,
            thinking=thinking,
            thinking_budget=thinking_budget,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        )

    # 2. Config.yaml is kept only as a compatibility fallback.
    cfg = _find_model_config(model_name)
    if cfg is not None:
        logger.debug("Loading model '%s' from config.yaml fallback", model_name)
        return _build_from_config(
            cfg,
            thinking=thinking,
            thinking_budget=thinking_budget,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        )

    # 3. Fallback
    logger.debug("Loading model '%s' via init_chat_model", model_name)
    return _init_model_fallback(model_name)


async def load_chat_model_async(
    model_name: str | None = None,
    thinking: bool = False,
    thinking_budget: int = 8000,
    reasoning_mode: str | None = None,
    reasoning_effort: str | None = None,
) -> BaseChatModel:
    """Async variant -refreshes DB provider cache properly."""
    if not model_name:
        model_name = _default_model_name()

    if model_name in {"fake", "nexagent/fake", "test/fake"}:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        return FakeListChatModel(responses=["NexAgent test response."])

    reasoning_mode = _normalize_reasoning_mode(reasoning_mode, thinking)

    db_providers = await _get_db_providers_async()
    scoped_match = _find_in_provider_rows(model_name, db_providers)
    if scoped_match is not None:
        provider, model_id = scoped_match
        return _build_from_db_provider(
            provider,
            model_id,
            thinking=thinking,
            thinking_budget=thinking_budget,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        )

    # DB providers managed from Settings.
    db_match = _find_unscoped_in_provider_rows(model_name, db_providers)
    if db_match is not None:
        provider, model_id = db_match
        return _build_from_db_provider(
            provider,
            model_id,
            thinking=thinking,
            thinking_budget=thinking_budget,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        )

    # Config.yaml is kept only as a compatibility fallback.
    cfg = _find_model_config(model_name)
    if cfg is not None:
        return _build_from_config(
            cfg,
            thinking=thinking,
            thinking_budget=thinking_budget,
            reasoning_mode=reasoning_mode,
            reasoning_effort=reasoning_effort,
        )

    return _init_model_fallback(model_name)


def list_model_configs() -> list[dict]:
    """Return non-secret chat model metadata managed from Settings."""
    results: list[dict] = []

    # DB providers -expose each chat model entry. Embedding/rerank models stay
    # in Settings and are not valid for conversation model selection.
    for provider in _get_db_providers():
        results.extend(_provider_model_rows(provider))

    return _dedupe_model_configs(results)


def validate_model_name(model_name: str | None) -> str:
    effective = model_name or _default_model_name()
    cfg = _find_model_config(effective)
    if cfg is not None:
        return effective
    if effective in {"fake", "nexagent/fake", "test/fake"} or "/" in effective:
        return effective
    # Check DB providers
    if _find_in_db_providers(effective) is not None:
        return effective
    available = [m["name"] for m in list_model_configs()]
    raise ValueError(f"Unknown model '{effective}'. Available: {available}")


async def validate_model_name_async(model_name: str | None) -> str:
    """Async variant that can see DB-managed providers inside request handlers."""
    effective = model_name or _default_model_name()
    cfg = _find_model_config(effective)
    if cfg is not None:
        return effective
    if effective in {"fake", "nexagent/fake", "test/fake"} or "/" in effective:
        return effective

    db_providers = await _get_db_providers_async()
    if _find_in_provider_rows(effective, db_providers) is not None:
        return effective
    if _find_unscoped_in_provider_rows(effective, db_providers) is not None:
        return effective

    available = [m["name"] for m in list_model_configs()]
    for provider in db_providers:
        available.extend(_chat_models_for_provider(provider))
    raise ValueError(f"Unknown model '{effective}'. Available: {sorted(set(available))}")


async def list_model_configs_async() -> list[dict]:
    """Async API/UI metadata helper that includes hot-loaded DB providers."""
    results: list[dict] = []

    for provider in await _get_db_providers_async():
        results.extend(_provider_model_rows(provider))

    return _dedupe_model_configs(results)


# Model factory helpers

def _default_model_name() -> str:
    try:
        from nexagent.config import get_config
        cfg = get_config()
        if cfg.default_model:
            return cfg.default_model
    except Exception:
        pass
    return os.environ.get("NEXAGENT_DEFAULT_MODEL", "openai/gpt-4o-mini")


def _find_model_config(name: str) -> Any:
    try:
        from nexagent.config import get_config
        cfg = get_config()
        for m in cfg.models:
            if m.name == name:
                return m
    except Exception:
        pass
    return None


def _chat_models_for_provider(provider: dict) -> list[str]:
    model_configs = provider.get("model_configs") or []
    if model_configs:
        return [
            item.get("id")
            for item in model_configs
            if isinstance(item, dict) and item.get("id") and item.get("type", "chat") == "chat"
        ]
    return provider.get("models") or []


def _provider_model_ref(provider_id: str, model_id: str) -> str:
    return f"{provider_id}::{model_id}"


def _split_provider_model_ref(model_name: str) -> tuple[str, str] | None:
    if "::" not in model_name:
        return None
    provider_id, model_id = model_name.split("::", 1)
    provider_id = provider_id.strip()
    model_id = model_id.strip()
    if not provider_id or not model_id:
        return None
    return provider_id, model_id


def _find_in_provider_rows(model_name: str, providers: list[dict]) -> tuple[dict, str] | None:
    scoped = _split_provider_model_ref(model_name)
    if scoped is None:
        return None
    provider_id, model_id = scoped
    for provider in providers:
        if provider.get("id") == provider_id and model_id in _chat_models_for_provider(provider):
            return provider, model_id
    return None


def _matching_unscoped_provider_rows(model_name: str, providers: list[dict]) -> list[tuple[dict, str]]:
    matches: list[tuple[dict, str]] = []
    for provider in providers:
        models_list = _chat_models_for_provider(provider)
        if model_name in models_list:
            matches.append((provider, model_name))
        elif model_name == provider["name"] and models_list:
            matches.append((provider, models_list[0]))
    return matches


def _ambiguous_model_message(model_name: str, matches: list[tuple[dict, str]]) -> str:
    choices = [
        f"{provider.get('name') or provider.get('id')} ({provider.get('id')}::{model_id})"
        for provider, model_id in matches
    ]
    return (
        f"Model '{model_name}' is provided by multiple providers: {', '.join(choices)}. "
        "Please reselect the exact provider/model in Agent settings."
    )


def _find_unscoped_in_provider_rows(model_name: str, providers: list[dict]) -> tuple[dict, str] | None:
    matches = _matching_unscoped_provider_rows(model_name, providers)
    if len(matches) > 1:
        raise ValueError(_ambiguous_model_message(model_name, matches))
    return matches[0] if matches else None


def _provider_model_rows(provider: dict) -> list[dict]:
    rows: list[dict] = []
    model_configs = {
        item.get("id"): item
        for item in (provider.get("model_configs") or [])
        if isinstance(item, dict) and item.get("id")
    }
    for model_id in _chat_models_for_provider(provider):
        model_config = model_configs.get(model_id, {})
        display_name = model_config.get("display_name") or model_id
        rows.append({
            "name": _provider_model_ref(provider["id"], model_id),
            "display_name": display_name,
            "provider": provider["provider_type"],
            "model": model_id,
            "base_url": model_config.get("base_url_override") or provider["base_url"],
            "max_tokens": model_config.get("context_window") or 4096,
            "supports_streaming": True,
            "api_key_configured": bool(provider["api_key"]),
            "is_default": provider["is_default"],
            "source": "db",
            "provider_id": provider["id"],
            "provider_name": provider["name"],
            "capabilities": get_model_capabilities(
                provider=provider["provider_type"],
                model=model_id,
                display_name=display_name,
            ),
        })
    return rows


def _find_in_db_providers(model_name: str) -> tuple[dict, str] | None:
    """Return (provider_dict, model_id) if model_name matches a DB provider entry."""
    providers = _get_db_providers()
    scoped_match = _find_in_provider_rows(model_name, providers)
    if scoped_match is not None:
        return scoped_match
    return _find_unscoped_in_provider_rows(model_name, providers)


def get_model_capabilities(provider: str, model: str, display_name: str = "") -> dict:
    """Infer UI-facing model capabilities from provider and model id."""
    provider_l = (provider or "").lower()
    model_l = f"{model} {display_name}".lower()
    native_reasoning = _has_native_reasoning(provider_l, model_l)
    supports_vision = any(token in model_l for token in ("vision", "vl", "gpt-4o", "gemini", "claude-3", "claude-4"))
    supports_tool_calling = provider_l in {"openai", "anthropic", "google", "fake"} and "embedding" not in model_l
    return {
        "supports_text": True,
        "supports_streaming": True,
        "supports_tool_calling": supports_tool_calling,
        "supports_vision": supports_vision,
        "supports_image_generation": any(
            token in model_l for token in ("image", "dall-e", "gpt-image", "flux", "stable-diffusion")
        ),
        "supports_video_generation": any(token in model_l for token in ("video", "sora", "wan", "kling")),
        "supports_native_reasoning": native_reasoning,
        "supported_reasoning_modes": list(REASONING_MODES),
        "reasoning_mode_reasons": _reasoning_mode_reasons(native_reasoning),
    }


def _has_native_reasoning(provider: str, model_text: str) -> bool:
    if provider == "anthropic":
        return any(token in model_text for token in ("claude-3.7", "claude-4", "opus-4", "sonnet-4"))
    if provider == "google":
        return "gemini-2.5" in model_text or "gemini 2.5" in model_text
    if provider == "openai":
        return any(
            token in model_text
            for token in ("o1", "o3", "o4", "gpt-5", "gpt-4.1", "deepseek-r1", "qwq", "qwen3")
        )
    return provider == "fake"


def _reasoning_mode_reasons(native_reasoning: bool) -> dict[str, str]:
    if native_reasoning:
        return {
            "fast": "低延迟回答，适合简单任务。",
            "balanced": "默认模式，兼顾质量和速度。",
            "deep": "启用更高推理预算。",
            "ultra": "启用最高推理预算，适合复杂规划。",
        }
    return {
        "fast": "所有文本模型均可用。",
        "balanced": "所有文本模型均可用。",
        "deep": "通过 Agent 通用思考策略增强分析；模型未声明原生推理预算。",
        "ultra": "通过 Agent 通用思考策略增强规划与校验；模型未声明原生推理预算。",
    }


def _normalize_reasoning_mode(reasoning_mode: str | None, thinking: bool) -> str:
    if reasoning_mode in REASONING_MODES:
        return reasoning_mode
    return "deep" if thinking else "balanced"


def _reasoning_budget_for_mode(mode: str, requested: int) -> int:
    defaults = {"fast": 1024, "balanced": 4096, "deep": 12000, "ultra": 32000}
    return min(max(requested or defaults.get(mode, 4096), 1024), 32000)


def _openai_reasoning_effort(mode: str, requested: str | None = None) -> str:
    if requested in {"low", "medium", "high"}:
        return requested
    # OpenAI-compatible chat APIs commonly accept low/medium/high. Keep
    # "minimal" as a UI/runtime profile, but do not send it unless a provider
    # explicitly supports it.
    return {"fast": "low", "balanced": "low", "deep": "medium", "ultra": "high"}.get(mode, "low")


def _dedupe_model_configs(items: list[dict]) -> list[dict]:
    """Deduplicate config and DB model rows, preferring user-facing config aliases.

    The settings bootstrap mirrors config.yaml providers into the DB so users can
    edit them later. Without this pass, /api/models shows both the friendly
    config alias (for example qwen2.5-7b) and the raw provider model id
    (Qwen/Qwen2.5-7B-Instruct). They are the same backend model.
    """
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []

    def sort_key(item: dict) -> int:
        return 0 if item.get("source") == "config" else 1

    for item in sorted(items, key=sort_key):
        provider = str(item.get("provider") or "").lower()
        base_url = str(item.get("base_url") or "").rstrip("/")
        model = str(item.get("model") or item.get("name") or "")
        key = (provider, base_url, model)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _build_from_config(
    m: Any,
    thinking: bool = False,
    thinking_budget: int = 8000,
    reasoning_mode: str = "balanced",
    reasoning_effort: str | None = None,
) -> BaseChatModel:
    provider = m.provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}' for model '{m.name}'.")
    callbacks = _safe_tracing_callbacks()

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr
        kwargs: dict = {"model": m.model, "streaming": True, "stream_chunk_timeout": _stream_chunk_timeout()}
        if callbacks:
            kwargs["callbacks"] = callbacks
        if m.api_key:
            kwargs["api_key"] = SecretStr(m.api_key)
        if m.base_url:
            kwargs["base_url"] = m.base_url
        if _has_native_reasoning(provider, m.model.lower()) and (thinking or reasoning_mode != "fast"):
            kwargs["reasoning_effort"] = _openai_reasoning_effort(reasoning_mode, reasoning_effort)
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        native = _has_native_reasoning(provider, m.model.lower())
        return _build_anthropic(
            m.model,
            m.api_key,
            thinking=native and (thinking or reasoning_mode in {"deep", "ultra"}),
            thinking_budget=_reasoning_budget_for_mode(reasoning_mode, thinking_budget),
            callbacks=callbacks,
        )

    if provider == "google":
        native = _has_native_reasoning(provider, m.model.lower())
        return _build_google(
            m.model,
            m.api_key,
            thinking=native and (thinking or reasoning_mode in {"deep", "ultra"}),
            thinking_budget=_reasoning_budget_for_mode(reasoning_mode, thinking_budget),
            callbacks=callbacks,
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore
        kwargs = {"model": m.model, "base_url": m.base_url or "http://localhost:11434"}
        if callbacks:
            kwargs["callbacks"] = callbacks
        return ChatOllama(**kwargs)  # type: ignore

    if provider == "fake":
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        return FakeListChatModel(responses=["NexAgent test response."])

    raise ValueError(f"Provider '{provider}' is configured but not available")


def _build_from_db_provider(
    provider: dict,
    model_id: str,
    thinking: bool = False,
    thinking_budget: int = 8000,
    reasoning_mode: str = "balanced",
    reasoning_effort: str | None = None,
) -> BaseChatModel:
    ptype = provider["provider_type"].lower()
    api_key = provider["api_key"]
    base_url = provider["base_url"]
    callbacks = _safe_tracing_callbacks()

    if ptype == "openai":
        from langchain_openai import ChatOpenAI
        from pydantic import SecretStr
        kwargs: dict = {"model": model_id, "streaming": True, "stream_chunk_timeout": _stream_chunk_timeout()}
        if callbacks:
            kwargs["callbacks"] = callbacks
        if api_key:
            kwargs["api_key"] = SecretStr(api_key)
        if base_url:
            kwargs["base_url"] = base_url
        if _has_native_reasoning(ptype, model_id.lower()) and (thinking or reasoning_mode != "fast"):
            kwargs["reasoning_effort"] = _openai_reasoning_effort(reasoning_mode, reasoning_effort)
        return ChatOpenAI(**kwargs)

    if ptype == "anthropic":
        native = _has_native_reasoning(ptype, model_id.lower())
        return _build_anthropic(
            model_id,
            api_key,
            thinking=native and (thinking or reasoning_mode in {"deep", "ultra"}),
            thinking_budget=_reasoning_budget_for_mode(reasoning_mode, thinking_budget),
            callbacks=callbacks,
        )

    if ptype == "google":
        native = _has_native_reasoning(ptype, model_id.lower())
        return _build_google(
            model_id,
            api_key,
            thinking=native and (thinking or reasoning_mode in {"deep", "ultra"}),
            thinking_budget=_reasoning_budget_for_mode(reasoning_mode, thinking_budget),
            callbacks=callbacks,
        )

    if ptype == "ollama":
        from langchain_ollama import ChatOllama  # type: ignore
        kwargs = {"model": model_id, "base_url": base_url or "http://localhost:11434"}
        if callbacks:
            kwargs["callbacks"] = callbacks
        return ChatOllama(**kwargs)  # type: ignore

    raise ValueError(f"Unsupported DB provider type: {ptype}")


def _build_anthropic(
    model: str,
    api_key: str,
    thinking: bool = False,
    thinking_budget: int = 8000,
    callbacks: list[Any] | None = None,
) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic  # type: ignore
    from pydantic import SecretStr

    kwargs: dict = {
        "model": model,
        "api_key": SecretStr(api_key) if api_key else None,
    }
    if thinking:
        # Extended Thinking requires temperature=1 and sufficient max_tokens
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        kwargs["temperature"] = 1
        kwargs["max_tokens"] = thinking_budget + 4096
        logger.debug("Claude Extended Thinking enabled (budget=%d tokens)", thinking_budget)
    if callbacks:
        kwargs["callbacks"] = callbacks
    return ChatAnthropic(**kwargs)  # type: ignore


def _build_google(
    model: str,
    api_key: str,
    thinking: bool = False,
    thinking_budget: int = 8000,
    callbacks: list[Any] | None = None,
) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore

    kwargs: dict = {"model": model, "google_api_key": api_key or None}
    if thinking:
        # Gemini 2.5 thinking budget
        kwargs["generation_config"] = {
            "thinking_config": {"thinking_budget": thinking_budget}
        }
        logger.debug("Gemini Thinking enabled (budget=%d tokens)", thinking_budget)
    if callbacks:
        kwargs["callbacks"] = callbacks
    return ChatGoogleGenerativeAI(**kwargs)  # type: ignore


def _init_model_fallback(model_name: str) -> BaseChatModel:
    from langchain.chat_models import init_chat_model
    try:
        model = init_chat_model(model_name)
        callbacks = _safe_tracing_callbacks()
        if callbacks and hasattr(model, "with_config"):
            return model.with_config({"callbacks": callbacks})
        return model
    except Exception as e:
        raise RuntimeError(
            f"Cannot load model '{model_name}': {e}\n"
            "Either add it to config.yaml, create a provider in Settings, "
            "or use provider/model format (e.g. openai/gpt-4o-mini)."
        ) from e


def _safe_tracing_callbacks() -> list[Any]:
    """Build tracing callbacks, preserving fail-fast behavior when enabled."""
    from nexagent.tracing import build_tracing_callbacks

    return build_tracing_callbacks()
