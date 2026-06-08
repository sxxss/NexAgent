from __future__ import annotations

import shutil
from datetime import UTC, datetime

from nexagent.knowledge.base import KnowledgeBase
from nexagent.knowledge.implementations.wiki.constants import CONFIDENCE_VALUES, WIKI_PAGE_TYPES
from nexagent.knowledge.implementations.wiki.links import WikiLinksMixin
from nexagent.knowledge.implementations.wiki.storage import WikiStorageMixin
from nexagent.knowledge.models import FileMeta, KBMeta, KBType, SearchResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WikiKB(WikiStorageMixin, WikiLinksMixin, KnowledgeBase):
    """Markdown-first LLM Wiki knowledge base."""

    @property
    def kb_type(self) -> KBType:
        return KBType.WIKI

    async def create_kb(self, *args, **kwargs) -> KBMeta:
        meta = await super().create_kb(*args, **kwargs)
        self._ensure_wiki_layout(meta)
        purpose = str(meta.description or meta.name).strip()
        self._atomic_write_text(self._db_root(meta.kb_id) / "purpose.md", f"# {meta.name}\n\n{purpose}\n")
        self._atomic_write_text(self._db_root(meta.kb_id) / "index.md", "# Index\n\n")
        self._atomic_write_text(self._db_root(meta.kb_id) / "log.md", "# Log\n\n")
        return meta

    def list_wiki_pages(
        self,
        kb_id: str,
        page_type: str | None = None,
        q: str | None = None,
        status: str | None = None,
        source_file_id: str | None = None,
    ) -> dict:
        pages = []
        query = (q or "").strip().lower()
        candidates = self._load_state(kb_id).get("candidates", {})
        for path in sorted(self._wiki_root(kb_id).glob("**/*.md")):
            frontmatter, content = self._read_page(path)
            if not frontmatter:
                continue
            if page_type and frontmatter.get("type") != page_type:
                continue
            if source_file_id and source_file_id not in (frontmatter.get("sources") or []):
                continue
            title = frontmatter.get("title") or path.stem
            if query and query not in f"{title} {content}".lower():
                continue
            summary = self._page_summary(kb_id, path, frontmatter, content)
            summary["has_candidate"] = summary["id"] in candidates
            summary["status"] = self._page_status(summary, frontmatter)
            if status and status != summary["status"]:
                continue
            pages.append(summary)
        return {"pages": pages}

    def get_wiki_page(self, kb_id: str, page_id: str) -> dict:
        path = self._find_page_path(kb_id, page_id)
        if path is None:
            raise ValueError(f"Wiki page {page_id} not found")
        frontmatter, content = self._read_page(path)
        summary = self._page_summary(kb_id, path, frontmatter, content)
        return {
            **summary,
            "content": content,
            "frontmatter": frontmatter,
            "candidate": self._load_state(kb_id).get("candidates", {}).get(page_id),
        }

    async def update_wiki_page(
        self,
        kb_id: str,
        page_id: str,
        content: str,
        frontmatter: dict | None = None,
    ) -> dict:
        path = self._find_page_path(kb_id, page_id)
        if path is None:
            raise ValueError(f"Wiki page {page_id} not found")
        current, _old_content = self._read_page(path)
        merged = dict(current)
        if frontmatter:
            merged.update(frontmatter)
        merged["manual_edited"] = True
        merged["updated_at"] = _now()
        merged["version"] = int(merged.get("version") or 1) + 1
        self._write_page(path, merged, content)
        self._refresh_index(kb_id)
        return self.get_wiki_page(kb_id, page_id)

    async def create_or_update_wiki_page(
        self,
        kb_id: str,
        *,
        page_type: str,
        title: str,
        content: str,
        sources: list[str] | None = None,
        confidence: str = "EXTRACTED",
        manual_edited: bool = False,
    ) -> dict:
        if page_type not in WIKI_PAGE_TYPES:
            raise ValueError(f"Unsupported wiki page type: {page_type}")
        if confidence not in CONFIDENCE_VALUES:
            raise ValueError(f"Unsupported confidence: {confidence}")
        title = self._clean_wiki_title(title)
        page_id = self._page_id(page_type, title)
        path = self._page_path(kb_id, page_type, title)
        frontmatter = {
            "id": page_id,
            "title": title,
            "type": page_type,
            "sources": sources or [],
            "confidence": confidence,
            "updated_at": _now(),
            "manual_edited": manual_edited,
            "version": 1,
        }
        if path.exists():
            old_frontmatter, _old_content = self._read_page(path)
            if old_frontmatter.get("manual_edited") and not manual_edited:
                state = self._load_state(kb_id)
                state.setdefault("candidates", {})[page_id] = {
                    "frontmatter": {**old_frontmatter, **frontmatter, "manual_edited": False},
                    "content": content,
                    "created_at": _now(),
                }
                self._save_state(kb_id, state)
                return self.get_wiki_page(kb_id, page_id)
            frontmatter["version"] = int(old_frontmatter.get("version") or 1) + 1
            frontmatter["manual_edited"] = manual_edited or bool(old_frontmatter.get("manual_edited"))
        self._write_page(path, frontmatter, content)
        self._refresh_index(kb_id)
        return self.get_wiki_page(kb_id, page_id)

    def _page_status(self, summary: dict, frontmatter: dict) -> str:
        if summary.get("has_candidate"):
            return "pending_candidate"
        if frontmatter.get("manual_edited"):
            return "manual_edited"
        if frontmatter.get("confidence") in {"AMBIGUOUS", "UNVERIFIED"}:
            return "needs_review"
        return "generated"

    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        return 0

    async def _do_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        **kwargs,
    ) -> list[SearchResult]:
        return []

    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        shutil.rmtree(self._db_root(kb_meta.kb_id), ignore_errors=True)

    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        return None
