"""Build optional LangSmith and Langfuse callbacks from config.yaml."""

from __future__ import annotations

from typing import Any


def build_tracing_callbacks() -> list[Any]:
    """Return configured tracing callbacks.

    Tracing is disabled by default. When a provider is explicitly enabled, fail
    fast on missing credentials so observability misconfiguration is visible at
    model construction time.
    """
    from nexagent.config import get_config

    tracing = get_config().tracing
    callbacks: list[Any] = []

    if tracing.langsmith.enabled:
        if not tracing.langsmith.api_key:
            raise RuntimeError("LangSmith tracing is enabled but api_key is empty.")
        callbacks.append(_create_langsmith_tracer(tracing.langsmith.project))

    if tracing.langfuse.enabled:
        if not tracing.langfuse.public_key or not tracing.langfuse.secret_key:
            raise RuntimeError("Langfuse tracing is enabled but public_key/secret_key is empty.")
        callbacks.append(
            _create_langfuse_handler(
                public_key=tracing.langfuse.public_key,
                secret_key=tracing.langfuse.secret_key,
                host=tracing.langfuse.host,
            )
        )

    return callbacks


def _create_langsmith_tracer(project: str) -> Any:
    try:
        from langchain_core.tracers.langchain import LangChainTracer
    except ImportError as exc:  # pragma: no cover - depends on optional install set
        raise RuntimeError("LangSmith tracing requires langchain-core tracing support.") from exc

    return LangChainTracer(project_name=project)


def _create_langfuse_handler(public_key: str, secret_key: str, host: str) -> Any:
    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Langfuse tracing requires the 'langfuse' package.") from exc

    Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    return CallbackHandler(public_key=public_key)
