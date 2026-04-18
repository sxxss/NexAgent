"""Web fetch tool for reading page content from exact URLs.

Search and fetch are intentionally separate: ``web_search`` discovers relevant
URLs, while ``web_fetch`` extracts content from a URL the user or search tool
has already provided.
"""

from __future__ import annotations

import html
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)


def get_web_fetch_tool() -> BaseTool:
    """Return the configured web page fetch tool."""
    from nexagent.config import get_config

    cfg = get_config().web_search
    provider = (cfg.provider or "auto").lower()
    if provider in {"auto", "tavily"} and cfg.tavily_api_key:
        return _tavily_fetch_tool(cfg.tavily_api_key, cfg.fetch_max_chars)
    if provider == "tavily" and not cfg.tavily_api_key:
        return _missing_tavily_key_tool()
    return _http_fetch_tool(cfg.fetch_max_chars)


def _tavily_fetch_tool(api_key: str, max_chars: int) -> BaseTool:
    try:
        from tavily import TavilyClient
    except ImportError as exc:
        raise ImportError("tavily-python is required for Tavily web_fetch. Run: pip install tavily-python") from exc

    client = TavilyClient(api_key=api_key)

    @tool("web_fetch")
    def web_fetch(url: str) -> str:
        """Fetch the readable content of an exact web URL."""
        normalized = _validate_url(url)
        if normalized.startswith("Error:"):
            return normalized
        try:
            response = client.extract([normalized])
        except Exception as exc:
            logger.warning("Tavily extract failed: %s", exc)
            return f"Web fetch failed because Tavily could not extract the URL. Error: {exc}"

        failed = response.get("failed_results") or []
        if failed:
            return f"Web fetch failed: {failed[0].get('error') or 'unknown extraction error'}"
        results = response.get("results") or []
        if not results:
            return "Web fetch failed: no content extracted."
        result = results[0]
        title = result.get("title") or normalized
        content = str(result.get("raw_content") or result.get("content") or "")
        return f"# {title}\n\nURL: {normalized}\n\n{content[:max_chars]}"

    web_fetch.description = (
        "Fetch readable page content from an exact URL. Only use URLs provided by the user "
        "or returned by web_search. Input: a full http(s) URL."
    )
    return web_fetch


def _http_fetch_tool(max_chars: int) -> BaseTool:
    @tool("web_fetch")
    def web_fetch(url: str) -> str:
        """Fetch the readable content of an exact web URL."""
        normalized = _validate_url(url)
        if normalized.startswith("Error:"):
            return normalized
        try:
            import httpx

            with httpx.Client(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": "NexAgent/0.1 (+https://local.nexagent)"},
            ) as client:
                response = client.get(normalized)
                response.raise_for_status()
        except Exception as exc:
            logger.warning("HTTP web_fetch failed: %s", exc)
            return f"Web fetch failed because the URL could not be reached. Error: {exc}"

        text = _html_to_text(response.text)
        return f"URL: {str(response.url)}\n\n{text[:max_chars]}" if text else "Web fetch found no readable text."

    web_fetch.description = (
        "Fetch readable page content from an exact URL. Only use URLs provided by the user "
        "or returned by web_search. Input: a full http(s) URL."
    )
    return web_fetch


def _missing_tavily_key_tool() -> BaseTool:
    @tool("web_fetch")
    def web_fetch(url: str) -> str:
        """Fetch the readable content of an exact web URL."""
        return (
            "Web fetch is configured to use Tavily, but TAVILY_API_KEY is not set. "
            "Add tavily_api_key in config.yaml or set the TAVILY_API_KEY environment variable."
        )

    return web_fetch


def _validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Error: web_fetch requires a full http(s) URL."
    return value


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = html.unescape(" ".join(self._parts))
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    return parser.text()
