"""Web search tool with provider fallback.

Configured via config.yaml:
  web_search:
    provider: auto
    preferred_provider: duckduckgo
    enabled_providers: [duckduckgo]
    providers:
      tavily:
        enabled: false
        api_key: $TAVILY_API_KEY
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)

SEARCH_PROVIDER_IDS = ("duckduckgo", "tavily", "brave", "serpapi", "bing", "exa", "searxng")
API_KEY_PROVIDERS = {"tavily", "brave", "serpapi", "bing", "exa"}
HTTP_TIMEOUT = httpx.Timeout(12.0, connect=5.0)


def get_web_search_tool() -> BaseTool:
    """Return the configured web search tool."""
    from nexagent.config import get_config

    cfg = get_config().web_search
    return get_web_search_tool_for(
        provider=cfg.provider,
        preferred_provider=cfg.preferred_provider,
        enabled_providers=cfg.enabled_providers,
        provider_keys=cfg.provider_keys,
        provider_base_urls=cfg.provider_base_urls,
        max_results=cfg.max_results,
        tavily_api_key=cfg.tavily_api_key,
    )


def get_web_search_tool_for(
    *,
    provider: str = "auto",
    preferred_provider: str = "duckduckgo",
    enabled_providers: list[str] | None = None,
    provider_keys: dict[str, str] | None = None,
    provider_base_urls: dict[str, str] | None = None,
    max_results: int = 5,
    tavily_api_key: str | None = None,
) -> BaseTool:
    """Return a web search tool for an explicit provider configuration."""
    keys = dict(provider_keys or {})
    if tavily_api_key:
        keys["tavily"] = tavily_api_key
    base_urls = dict(provider_base_urls or {})
    enabled = [item for item in (enabled_providers or ["duckduckgo"]) if item in SEARCH_PROVIDER_IDS]

    @tool("web_search")
    def web_search(query: str) -> str:
        """Search the web for current information."""
        query = query.strip()
        if not query:
            return "Web search failed: query is required."

        sequence = _provider_sequence(
            provider=provider,
            preferred_provider=preferred_provider,
            enabled_providers=enabled,
            provider_keys=keys,
            provider_base_urls=base_urls,
        )
        if not sequence:
            return "Web search failed: no enabled and configured search provider is available."

        failures: list[str] = []
        for provider_id in sequence:
            try:
                result = _search_provider(
                    provider_id,
                    query,
                    max_results=max_results,
                    api_key=keys.get(provider_id, ""),
                    base_url=base_urls.get(provider_id, ""),
                )
                if not result or result.startswith("No web search results found."):
                    failures.append(f"{_provider_label(provider_id)}: no results")
                    continue
                logger.info("Web search: using %s", provider_id)
                return result
            except Exception as exc:
                logger.warning("Web search provider %s failed: %s", provider_id, exc)
                failures.append(f"{_provider_label(provider_id)}: {exc}")

        return (
            "Web search failed because all enabled search providers were unavailable. "
            "Enable a production provider such as Tavily, Brave, Bing, SerpAPI, Exa, "
            "or SearxNG for more stable search.\n"
            + "\n".join(f"- {item}" for item in failures)
        )

    web_search.description = (
        "Search the web for current information. "
        "Uses the configured provider strategy and falls back across enabled providers. "
        "Input: a search query string."
    )
    return web_search


def _provider_sequence(
    *,
    provider: str,
    preferred_provider: str,
    enabled_providers: list[str],
    provider_keys: dict[str, str],
    provider_base_urls: dict[str, str],
) -> list[str]:
    provider = (provider or "auto").lower()
    preferred_provider = (preferred_provider or "duckduckgo").lower()
    available = [
        item
        for item in enabled_providers
        if item in SEARCH_PROVIDER_IDS and _provider_configured(item, provider_keys, provider_base_urls)
    ]
    if provider != "auto":
        return [provider] if provider in available else []
    ordered: list[str] = []
    if preferred_provider in available:
        ordered.append(preferred_provider)
    ordered.extend(item for item in available if item not in ordered)
    return ordered


def _provider_configured(provider_id: str, provider_keys: dict[str, str], provider_base_urls: dict[str, str]) -> bool:
    if provider_id == "duckduckgo":
        return True
    if provider_id in API_KEY_PROVIDERS:
        return bool(provider_keys.get(provider_id))
    if provider_id == "searxng":
        return bool(provider_base_urls.get("searxng"))
    return False


def _search_provider(provider_id: str, query: str, *, max_results: int, api_key: str, base_url: str) -> str:
    if provider_id == "duckduckgo":
        return _search_duckduckgo(query, max_results)
    if provider_id == "tavily":
        return _search_tavily(query, max_results, api_key)
    if provider_id == "brave":
        return _search_brave(query, max_results, api_key)
    if provider_id == "serpapi":
        return _search_serpapi(query, max_results, api_key)
    if provider_id == "bing":
        return _search_bing(query, max_results, api_key)
    if provider_id == "exa":
        return _search_exa(query, max_results, api_key)
    if provider_id == "searxng":
        return _search_searxng(query, max_results, base_url)
    raise ValueError(f"Unsupported search provider: {provider_id}")


def _search_duckduckgo(query: str, max_results: int) -> str:
    DDGS = _load_duckduckgo_client()
    try:
        results = _ddgs_text(DDGS, query, max_results=max_results, verify=True)
    except Exception as exc:
        if not _looks_like_retryable_connection_error(exc):
            raise
        results = _ddgs_text(DDGS, query, max_results=max_results, verify=False)
    return _format_results(
        [
            {
                "title": item.get("title") or "Untitled",
                "url": item.get("href") or item.get("url") or "",
                "snippet": item.get("body") or item.get("snippet") or "",
            }
            for item in results
        ]
    )


def _search_tavily(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        raise ValueError("Tavily API Key is required")
    from tavily import TavilyClient

    response = TavilyClient(api_key=api_key).search(query=query, max_results=max_results)
    return _format_results(
        [
            {
                "title": item.get("title") or "Untitled",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
            }
            for item in response.get("results", [])
        ]
    )


def _search_brave(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        raise ValueError("Brave Search API Key is required")
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    results = response.json().get("web", {}).get("results", [])
    return _format_results([
        {"title": item.get("title"), "url": item.get("url"), "snippet": item.get("description")} for item in results
    ])


def _search_serpapi(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        raise ValueError("SerpAPI Key is required")
    response = httpx.get(
        "https://serpapi.com/search.json",
        params={"engine": "google", "q": query, "num": max_results, "api_key": api_key},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return _format_results(
        [
            {"title": item.get("title"), "url": item.get("link"), "snippet": item.get("snippet")}
            for item in response.json().get("organic_results", [])
        ]
    )


def _search_bing(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        raise ValueError("Bing Search API Key is required")
    response = httpx.get(
        "https://api.bing.microsoft.com/v7.0/search",
        params={"q": query, "count": max_results},
        headers={"Ocp-Apim-Subscription-Key": api_key},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return _format_results(
        [
            {"title": item.get("name"), "url": item.get("url"), "snippet": item.get("snippet")}
            for item in response.json().get("webPages", {}).get("value", [])
        ]
    )


def _search_exa(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        raise ValueError("Exa API Key is required")
    response = httpx.post(
        "https://api.exa.ai/search",
        json={"query": query, "numResults": max_results, "contents": {"text": True}},
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return _format_results(
        [
            {"title": item.get("title"), "url": item.get("url"), "snippet": item.get("text")}
            for item in response.json().get("results", [])
        ]
    )


def _search_searxng(query: str, max_results: int, base_url: str) -> str:
    if not base_url:
        raise ValueError("SearxNG Base URL is required")
    response = httpx.get(
        f"{base_url.rstrip('/')}/search",
        params={"q": query, "format": "json", "language": "auto"},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return _format_results(
        [
            {"title": item.get("title"), "url": item.get("url"), "snippet": item.get("content")}
            for item in response.json().get("results", [])[:max_results]
        ]
    )


def _format_results(results: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(results, start=1):
        title = item.get("title") or "Untitled"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        lines.append(f"{index}. {title}\nURL: {url}\nSnippet: {snippet}")
    return "\n\n".join(lines) if lines else "No web search results found."


def _load_duckduckgo_client() -> type:
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS

        return DDGS


def _ddgs_text(ddgs_cls: type, query: str, *, max_results: int, verify: bool) -> list[dict]:
    results: Iterable[dict] = ddgs_cls(verify=verify, timeout=12).text(query, max_results=max_results)
    return list(results)


def _looks_like_retryable_connection_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "certificate" in text
        or "cert" in text
        or "native root" in text
        or "connecterror" in text
        or "connection" in text
    )


def _provider_label(provider_id: str) -> str:
    return {
        "duckduckgo": "DuckDuckGo / DDGS",
        "tavily": "Tavily",
        "brave": "Brave Search",
        "serpapi": "SerpAPI",
        "bing": "Bing Web Search",
        "exa": "Exa",
        "searxng": "SearxNG",
    }.get(provider_id, provider_id)
