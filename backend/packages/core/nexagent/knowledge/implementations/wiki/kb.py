from __future__ import annotations

import shutil
from pathlib import Path

from nexagent.knowledge.base import KnowledgeBase
from nexagent.knowledge.models import FileMeta, KBMeta, KBType, SearchResult


class WikiKB(KnowledgeBase):
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

    def _db_root(self, kb_id: str) -> Path:
        return self.work_dir / kb_id

    def _wiki_root(self, kb_id: str) -> Path:
        return self._db_root(kb_id) / "wiki"

    def _ensure_wiki_layout(self, kb_meta: KBMeta) -> None:
        for subdir in ["sources", "entities", "topics", "synthesis", "comparisons", "queries", "notes"]:
            (self._wiki_root(kb_meta.kb_id) / subdir).mkdir(parents=True, exist_ok=True)

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

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
