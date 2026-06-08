from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import yaml

from nexagent.knowledge.implementations.wiki.constants import WIKI_PAGE_TYPES


class WikiStorageMixin:
    def _ensure_wiki_layout(self, kb_meta) -> None:
        for subdir in ["sources", "entities", "topics", "synthesis", "comparisons", "queries", "notes"]:
            (self._wiki_root(kb_meta.kb_id) / subdir).mkdir(parents=True, exist_ok=True)

    def _db_root(self, kb_id: str) -> Path:
        return self.work_dir / kb_id

    def _wiki_root(self, kb_id: str) -> Path:
        return self._db_root(kb_id) / "wiki"

    def _state_path(self, kb_id: str) -> Path:
        return self._db_root(kb_id) / ".wiki-state.json"

    def _cache_path(self, kb_id: str) -> Path:
        return self._db_root(kb_id) / ".wiki-cache.json"

    def _load_state(self, kb_id: str) -> dict:
        return self._read_json(self._state_path(kb_id), {"candidates": {}})

    def _save_state(self, kb_id: str, state: dict) -> None:
        self._write_json(self._state_path(kb_id), state)

    def _load_cache(self, kb_id: str) -> dict:
        return self._read_json(self._cache_path(kb_id), {})

    def _save_cache(self, kb_id: str, cache: dict) -> None:
        self._write_json(self._cache_path(kb_id), cache)

    def _read_json(self, path: Path, default: dict) -> dict:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(default)

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _page_id(self, page_type: str, title: str) -> str:
        return f"{page_type}:{self._slugify(title)}"

    def _page_path(self, kb_id: str, page_type: str, title: str) -> Path:
        subdir = {
            "source": "sources",
            "entity": "entities",
            "topic": "topics",
            "synthesis": "synthesis",
            "comparison": "comparisons",
            "query": "queries",
            "note": "notes",
        }[page_type]
        return self._wiki_root(kb_id) / subdir / f"{self._slugify(title)}.md"

    def _page_path_from_id(self, kb_id: str, page_id: str) -> Path | None:
        if ":" not in page_id:
            return None
        page_type, slug = page_id.split(":", 1)
        if page_type not in WIKI_PAGE_TYPES or not slug:
            return None
        subdir = {
            "source": "sources",
            "entity": "entities",
            "topic": "topics",
            "synthesis": "synthesis",
            "comparison": "comparisons",
            "query": "queries",
            "note": "notes",
        }[page_type]
        return self._wiki_root(kb_id) / subdir / f"{slug}.md"

    def _find_page_path(self, kb_id: str, page_id: str) -> Path | None:
        direct = self._page_path_from_id(kb_id, page_id)
        if direct and direct.exists():
            return direct
        for path in self._wiki_root(kb_id).glob("**/*.md"):
            frontmatter, _content = self._read_page(path)
            if frontmatter.get("id") == page_id:
                return path
        return None

    def _write_page(self, path: Path, frontmatter: dict, content: str) -> None:
        dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        self._atomic_write_text(path, f"---\n{dumped}\n---\n{content.strip()}\n")

    def _read_page(self, path: Path) -> tuple[dict, str]:
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            return {}, raw
        parts = raw.split("---\n", 2)
        if len(parts) < 3:
            return {}, raw
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            frontmatter = {}
        return frontmatter, parts[2].strip()

    def _page_summary(self, kb_id: str, path: Path, frontmatter: dict, content: str) -> dict:
        title = self._clean_wiki_title(frontmatter.get("title") or path.stem)
        page_type = frontmatter.get("type") or "note"
        page_id = frontmatter.get("id") or self._page_id(page_type, title)
        return {
            "id": page_id,
            "title": title,
            "type": page_type,
            "path": path.relative_to(self._db_root(kb_id)).as_posix(),
            "manual_edited": bool(frontmatter.get("manual_edited")),
            "confidence": frontmatter.get("confidence") or "UNVERIFIED",
            "updated_at": frontmatter.get("updated_at"),
            "sources": frontmatter.get("sources") or [],
            "excerpt": self._make_snippet(content, []),
        }

    def _iter_page_details(self, kb_id: str) -> list[dict]:
        state = self._load_state(kb_id)
        details = []
        for path in sorted(self._wiki_root(kb_id).glob("**/*.md")):
            frontmatter, content = self._read_page(path)
            if not frontmatter:
                continue
            summary = self._page_summary(kb_id, path, frontmatter, content)
            details.append(
                {
                    **summary,
                    "content": content,
                    "frontmatter": frontmatter,
                    "candidate": state.get("candidates", {}).get(summary["id"]),
                }
            )
        return details

    def _refresh_index(self, kb_id: str) -> None:
        lines = ["# Index", ""]
        for page in self.list_wiki_pages(kb_id)["pages"]:
            lines.append(f"- [[{page['title']}]] ({page['type']})")
        self._atomic_write_text(self._db_root(kb_id) / "index.md", "\n".join(lines) + "\n")
