from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from nexagent.knowledge.base import KnowledgeBase
from nexagent.knowledge.implementations.wiki.compile import WikiCompileMixin
from nexagent.knowledge.implementations.wiki.constants import CONFIDENCE_VALUES, WIKI_PAGE_TYPES
from nexagent.knowledge.implementations.wiki.graph import WikiGraphMixin
from nexagent.knowledge.implementations.wiki.links import WikiLinksMixin
from nexagent.knowledge.implementations.wiki.lint import WikiLintMixin
from nexagent.knowledge.implementations.wiki.repair import WikiRepairMixin
from nexagent.knowledge.implementations.wiki.storage import WikiStorageMixin
from nexagent.knowledge.models import FileMeta, FileStatus, KBMeta, KBType, SearchResult


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WikiKB(
    WikiGraphMixin,
    WikiLintMixin,
    WikiRepairMixin,
    WikiCompileMixin,
    WikiStorageMixin,
    WikiLinksMixin,
    KnowledgeBase,
):
    """Markdown-first Wiki knowledge base."""

    @property
    def kb_type(self) -> KBType:
        return KBType.WIKI

    async def create_kb(self, *args, **kwargs) -> KBMeta:
        meta = await super().create_kb(*args, **kwargs)
        self._ensure_wiki_layout(meta)
        purpose = str((meta.chunk_parser_config or {}).get("purpose") or meta.description or meta.name).strip()
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

    async def compile_wiki(
        self,
        kb_id: str,
        *,
        file_ids: list[str] | None = None,
        force: bool = False,
        retry_failed: bool = False,
    ) -> dict:
        wanted = set(file_ids or [])
        candidates = []
        for file_meta in self.list_files(kb_id):
            if wanted and file_meta.file_id not in wanted:
                continue
            if file_meta.status in {FileStatus.UPLOADED, FileStatus.PARSED}:
                candidates.append(file_meta.file_id)
            elif retry_failed and file_meta.status in {FileStatus.PARSE_ERROR, FileStatus.INDEX_ERROR}:
                candidates.append(file_meta.file_id)
            elif force and file_meta.status in {FileStatus.INDEXED, FileStatus.GRAPH_INDEXED}:
                candidates.append(file_meta.file_id)

        result = {"processed": 0, "failed": 0, "items": []}
        state = self._load_state(kb_id)
        state["compile_status"] = {"status": "running", "total": len(candidates), "processed": 0}
        self._save_state(kb_id, state)
        for file_id in candidates:
            try:
                file_meta = self.get_file(kb_id, file_id)
                if file_meta is None:
                    raise ValueError(f"File not found: {file_id}")
                if file_meta.status in {FileStatus.UPLOADED, FileStatus.PARSE_ERROR}:
                    file_meta = await self.parse_file(kb_id, file_id)
                if force and file_meta.status in {FileStatus.INDEXED, FileStatus.GRAPH_INDEXED}:
                    file_meta = await self.reindex_file(kb_id, file_id)
                elif file_meta.status in {FileStatus.PARSED, FileStatus.INDEX_ERROR}:
                    file_meta = await self.index_file(kb_id, file_id)
                result["processed"] += 1
                result["items"].append({"file_id": file_id, "status": file_meta.status.value})
            except Exception as exc:
                result["failed"] += 1
                result["items"].append({"file_id": file_id, "status": "error", "error": str(exc)})
            finally:
                state = self._load_state(kb_id)
                state["compile_status"] = {
                    "status": "running",
                    "total": len(candidates),
                    "processed": int(result["processed"]) + int(result["failed"]),
                }
                self._save_state(kb_id, state)
        if result["processed"]:
            synthesis = await self._refresh_corpus_synthesis(kb_id)
            if synthesis:
                result["synthesis_page_id"] = synthesis["id"]
        state = self._load_state(kb_id)
        state["compile_status"] = {
            "status": "failed" if result["failed"] and not result["processed"] else "completed",
            "total": len(candidates),
            "processed": int(result["processed"]),
            "failed": int(result["failed"]),
        }
        state["needs_recompile"] = False
        self._save_state(kb_id, state)
        return result

    async def accept_generated_wiki_page(self, kb_id: str, page_id: str) -> dict:
        state = self._load_state(kb_id)
        candidate = state.get("candidates", {}).get(page_id)
        if not candidate:
            raise ValueError(f"Wiki page {page_id} has no generated candidate")
        path = self._find_page_path(kb_id, page_id)
        if path is None:
            raise ValueError(f"Wiki page {page_id} not found")
        frontmatter = dict(candidate["frontmatter"])
        frontmatter["manual_edited"] = False
        frontmatter["updated_at"] = _now()
        self._write_page(path, frontmatter, candidate["content"])
        del state["candidates"][page_id]
        self._save_state(kb_id, state)
        self._refresh_index(kb_id)
        return self.get_wiki_page(kb_id, page_id)

    async def discard_generated_wiki_page(self, kb_id: str, page_id: str) -> dict:
        state = self._load_state(kb_id)
        if page_id not in state.get("candidates", {}):
            raise ValueError(f"Wiki page {page_id} has no generated candidate")
        del state["candidates"][page_id]
        self._save_state(kb_id, state)
        return self.get_wiki_page(kb_id, page_id)

    async def delete_wiki_page(self, kb_id: str, page_id: str) -> dict:
        path = self._find_page_path(kb_id, page_id)
        if path is None:
            raise ValueError(f"Wiki page {page_id} not found")
        state = self._load_state(kb_id)
        state.get("candidates", {}).pop(page_id, None)
        state["needs_recompile"] = True
        state["recompile_reason"] = "page_deleted"
        self._save_state(kb_id, state)
        path.unlink(missing_ok=True)
        self._refresh_index(kb_id)
        return {"message": "deleted", "page_id": page_id}

    async def crystallize_wiki_text(
        self,
        kb_id: str,
        title: str,
        content: str,
        page_type: str = "note",
        sources: list[str] | None = None,
        confidence: str = "UNVERIFIED",
    ) -> dict:
        return await self.create_or_update_wiki_page(
            kb_id,
            page_type=page_type,
            title=title,
            content=content,
            sources=sources or [],
            confidence=confidence,
            manual_edited=True,
        )

    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        parsed_path = Path(file_meta.parsed_path)
        markdown = parsed_path.read_text(encoding="utf-8", errors="replace")
        pages = await self._compile_markdown_file(kb_meta.kb_id, file_meta.file_id, file_meta, markdown)
        self._refresh_index(kb_meta.kb_id)
        return len(pages)

    async def _do_search(
        self,
        query: str,
        kb_meta: KBMeta,
        top_k: int = 5,
        **kwargs,
    ) -> list[SearchResult]:
        terms = self._tokenize(query)
        if not terms:
            return []
        results: list[SearchResult] = []
        for detail in self._iter_page_details(kb_meta.kb_id):
            match = self._score_page_match(detail, terms)
            if match["score"] <= 0:
                continue
            results.append(
                SearchResult(
                    content=self._make_snippet(detail["content"], terms),
                    score=float(match["score"]),
                    source=detail["title"],
                    file_id=",".join(detail["frontmatter"].get("sources") or []),
                    metadata={
                        "kb_id": kb_meta.kb_id,
                        "page_id": detail["id"],
                        "page_type": detail["type"],
                        "confidence": detail["frontmatter"].get("confidence", "UNVERIFIED"),
                        "sources": detail["frontmatter"].get("sources") or [],
                        "match_reason": match["reasons"],
                        "engine": "wiki",
                    },
                )
            )
        results.sort(key=lambda item: (-item.score, item.source))
        return results[: int(top_k or 5)]

    def _score_page_match(self, detail: dict, terms: list[str]) -> dict:
        title = detail["title"].lower()
        content = detail["content"].lower()
        links = " ".join(self._extract_wikilinks(detail["content"])).lower()
        source_names = " ".join(
            (self._files.get(source_id).filename if self._files.get(source_id) else source_id)
            for source_id in detail["frontmatter"].get("sources", [])
        )
        score = 2.0 if detail.get("type") in {"topic", "entity", "synthesis"} else 0.0
        reasons: list[str] = []
        for term in terms:
            if term in title:
                score += 10
                reasons.append("title")
            body_hits = content.count(term)
            if body_hits:
                score += body_hits
                reasons.append("content")
            if term in links:
                score += 2
                reasons.append("wikilink")
            if term in source_names.lower():
                score += 3
                reasons.append("source")
        return {"score": score, "reasons": sorted(set(reasons))}

    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        shutil.rmtree(self._db_root(kb_meta.kb_id), ignore_errors=True)

    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        removed_pages: list[str] = []
        for detail in self._iter_page_details(kb_meta.kb_id):
            sources = list(detail["frontmatter"].get("sources") or [])
            if file_meta.file_id not in sources:
                continue
            if detail["type"] == "source" or sources == [file_meta.file_id]:
                path = self._find_page_path(kb_meta.kb_id, detail["id"])
                if path:
                    path.unlink(missing_ok=True)
                    removed_pages.append(detail["id"])
                continue
            sources = [source for source in sources if source != file_meta.file_id]
            frontmatter = dict(detail["frontmatter"])
            frontmatter["sources"] = sources
            frontmatter["updated_at"] = _now()
            path = self._find_page_path(kb_meta.kb_id, detail["id"])
            if path:
                self._write_page(path, frontmatter, detail["content"])
        state = self._load_state(kb_meta.kb_id)
        for page_id in removed_pages:
            state.get("candidates", {}).pop(page_id, None)
        state["needs_recompile"] = True
        state["recompile_reason"] = f"source_deleted:{file_meta.file_id}"
        self._save_state(kb_meta.kb_id, state)
        self._refresh_index(kb_meta.kb_id)
