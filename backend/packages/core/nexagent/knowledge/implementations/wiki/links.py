from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from nexagent.knowledge.implementations.wiki.constants import (
    NOISE_WIKILINKS,
    WIKILINK_RE,
    WIKI_PAGE_TYPES,
)


class WikiLinksMixin:
    def _clean_wiki_title(self, value: Any) -> str:
        text = str(value or "").strip().strip("`")
        markdown_link = re.fullmatch(r"\[([^\]]+)\]\([^)]+\)", text)
        if markdown_link:
            text = markdown_link.group(1).strip()
        text = re.sub(r"^\[+", "", text)
        text = re.sub(r"\]+$", "", text)
        return text.strip()

    def _normalize_link_key(self, value: str) -> str:
        text = str(value or "").strip()
        if ":" in text:
            prefix, suffix = text.split(":", 1)
            if prefix.strip().lower() in WIKI_PAGE_TYPES:
                text = suffix
        text = text.removesuffix(".md")
        text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
        text = text.replace('"', "").replace("'", "").replace("《", "").replace("》", "")
        return re.sub(r"[\s\-_/\\、，,。.!?！？:：;；()（）\[\]{}<>`]+", "", text).lower()

    def _slugify(self, value: str) -> str:
        value = self._clean_wiki_title(value)
        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip()).strip("-").lower()
        return slug[:80] or "untitled"

    def _extract_wikilinks(self, markdown: str) -> list[str]:
        links: list[str] = []
        for match in WIKILINK_RE.findall(markdown or ""):
            title = match.strip()
            if title and title not in links:
                links.append(title)
        return links

    def _title_index(self, pages: list[dict]) -> dict[str, list[dict]]:
        index: dict[str, list[dict]] = defaultdict(list)
        for page in pages:
            entry = {"id": page["id"], "title": page["title"], "type": page["type"]}
            keys = {
                self._normalize_link_key(page["title"]),
                self._normalize_link_key(page["id"]),
                self._normalize_link_key(
                    str(page.get("path") or "").rsplit("/", 1)[-1].removesuffix(".md")
                ),
            }
            for key in keys:
                if key and all(existing["id"] != page["id"] for existing in index[key]):
                    index[key].append(entry)
        return dict(index)

    def _resolve_wikilink(self, link_title: str, title_index: dict[str, list[dict]]) -> list[dict]:
        key = self._normalize_link_key(link_title)
        if not key or key in NOISE_WIKILINKS:
            return []
        return title_index.get(key, [])

    def _tokenize(self, text: str) -> list[str]:
        return [
            item.lower()
            for item in re.findall(r"[\w\u4e00-\u9fff]+", text or "")
            if len(item) > 1
        ]

    def _make_snippet(self, content: str, terms: list[str]) -> str:
        text = re.sub(r"\s+", " ", content or "").strip()
        if not text:
            return ""
        lower = text.lower()
        positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
        start = max(0, min(positions) - 80) if positions else 0
        return text[start : start + 260]
