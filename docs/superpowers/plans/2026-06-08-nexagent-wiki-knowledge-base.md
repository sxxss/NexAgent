# NexAgent Wiki Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Wiki as a first-class NexAgent knowledge base type modeled after `a-yuxi`, with Markdown pages, compilation, page graph, lint, conversation crystallization, Agent search, and frontend management.

**Architecture:** Add a dedicated local `KBType.WIKI` backend under NexAgent's existing `KnowledgeBase` abstraction. Wiki pages are Markdown files with YAML frontmatter, while normal upload/parse/file metadata remains owned by the existing base class. Knowledge APIs route Wiki KBs to the local manager even in production mode, and the frontend renders a Wiki workbench for `kb_type === "wiki"`.

**Tech Stack:** Python 3.12, FastAPI, pytest/pytest-asyncio, PyYAML, LangChain model factory, Next.js 16, TypeScript, React Markdown, React Flow, existing NexAgent task registry.

---

## File Structure

Create backend Wiki implementation package:

- `backend/packages/core/nexagent/knowledge/implementations/wiki/__init__.py`: exports `WikiKB`.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/constants.py`: page type, confidence, wikilink constants.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/storage.py`: layout, atomic write, frontmatter parsing, page summary.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/links.py`: title normalization, wikilinks, snippets, search tokenization.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/compile.py`: LLM compile, payload validation, source/topic/entity/synthesis page generation.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/graph.py`: page graph using wikilink/source-overlap/common-neighbor/type-affinity signals.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/lint.py`: health checks.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/repair.py`: optional AI repair candidates.
- `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`: `WikiKB` backend that wires all mixins into `KnowledgeBase`.

Modify backend integration:

- `backend/packages/core/nexagent/knowledge/models.py`: add `KBType.WIKI`.
- `backend/packages/core/nexagent/knowledge/manager.py`: register Wiki backend and query config behavior.
- `backend/packages/core/nexagent/knowledge/search_service.py`: make structured retrieval route Wiki mode correctly.
- `backend/packages/core/nexagent/tools/builtin/knowledge_search.py`: allow `wiki` mode.
- `backend/app/gateway/routers/knowledge.py`: add `wiki` create/list/routing/endpoints/task handling.
- `backend/packages/core/nexagent/services/wiki_service.py`: move first-class crystallization into Wiki KBs while preserving global notebook compatibility.

Create or modify backend tests:

- `backend/tests/unit/test_wiki_kb.py`
- `backend/tests/unit/test_wiki_routes.py`
- `backend/tests/unit/test_wiki_service.py`
- `backend/tests/unit/test_knowledge_agent_tool.py`
- `backend/tests/unit/test_knowledge_upload_lifecycle.py`

Modify frontend:

- `frontend/src/lib/api.ts`: add `wiki` types and API functions.
- `frontend/src/app/knowledge/page.tsx`: add Wiki create option and card behavior.
- `frontend/src/app/knowledge/[id]/page.tsx`: branch Wiki detail UI.
- `frontend/src/app/knowledge/[id]/wiki/graph/page.tsx`: dedicated Wiki graph route.
- `frontend/src/components/chat/WikiModal.tsx`: target only Wiki KBs.

Create frontend components:

- `frontend/src/components/wiki/WikiWorkbench.tsx`
- `frontend/src/components/wiki/WikiSourcePanel.tsx`
- `frontend/src/components/wiki/WikiPagePanel.tsx`
- `frontend/src/components/wiki/WikiGraphPanel.tsx`
- `frontend/src/components/wiki/WikiLintPanel.tsx`
- `frontend/src/components/wiki/WikiCrystallizePanel.tsx`

---

### Task 1: Register Wiki KB Type and Backend Skeleton

**Files:**
- Modify: `backend/packages/core/nexagent/knowledge/models.py`
- Modify: `backend/packages/core/nexagent/knowledge/manager.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/__init__.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/constants.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`
- Test: `backend/tests/unit/test_wiki_kb.py`

- [ ] **Step 1: Write the failing registration test**

Create `backend/tests/unit/test_wiki_kb.py` with:

```python
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


def _work_dir(prefix: str) -> Path:
    path = Path("test-artifacts") / "wiki-kb" / prefix / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_kb_can_be_created_and_discovered_by_manager():
    from nexagent.knowledge.manager import reset_manager
    from nexagent.knowledge.models import KBType

    work_dir = _work_dir("create")
    try:
        manager = reset_manager(str(work_dir))

        kb = await manager.create_kb(name="LLM Wiki", description="Project memory", kb_type="wiki")
        loaded = manager.get_kb(kb.kb_id)
        all_kbs = manager.list_kbs()

        assert kb.kb_type == KBType.WIKI
        assert loaded is not None
        assert loaded.kb_id == kb.kb_id
        assert any(item.kb_id == kb.kb_id for item in all_kbs)
        assert (work_dir / "wiki" / kb.kb_id / "wiki" / "sources").exists()
        assert (work_dir / "wiki" / kb.kb_id / "purpose.md").read_text(encoding="utf-8").startswith("# LLM Wiki")
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_kb_can_be_created_and_discovered_by_manager -q
```

Expected: FAIL with `ValueError: 'wiki' is not a valid KBType` or `Unknown KB type`.

- [ ] **Step 3: Add `KBType.WIKI`**

Modify `backend/packages/core/nexagent/knowledge/models.py`:

```python
class KBType(StrEnum):
    """Supported knowledge base backends."""
    MILVUS = "milvus"       # Vector RAG (semantic search)
    LIGHTRAG = "lightrag"   # Knowledge graph (entity + relation)
    WIKI = "wiki"           # Markdown-first LLM Wiki
```

- [ ] **Step 4: Add constants**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/constants.py`:

```python
from __future__ import annotations

import re

WIKI_PAGE_TYPES = {"source", "entity", "topic", "synthesis", "comparison", "query", "note"}
CONFIDENCE_VALUES = {"EXTRACTED", "INFERRED", "AMBIGUOUS", "UNVERIFIED"}
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[|#][^\]]*)?\]\]")
WIKI_PROMPT_VERSION = "2026-06-08-v1"
NOISE_WIKILINKS = {"content", "contents", "目录", "tableofcontents"}
```

- [ ] **Step 5: Add backend skeleton**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`:

```python
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

    async def _do_search(self, query: str, kb_meta: KBMeta, top_k: int = 5, **kwargs) -> list[SearchResult]:
        return []

    async def _do_delete_kb(self, kb_meta: KBMeta) -> None:
        shutil.rmtree(self._db_root(kb_meta.kb_id), ignore_errors=True)

    async def _do_delete_file(self, kb_meta: KBMeta, file_meta: FileMeta) -> None:
        return None
```

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/__init__.py`:

```python
from nexagent.knowledge.implementations.wiki.kb import WikiKB

__all__ = ["WikiKB"]
```

- [ ] **Step 6: Register backend in manager**

Modify `backend/packages/core/nexagent/knowledge/manager.py` in `_create_backend`:

```python
        elif kb_type == KBType.WIKI:
            from nexagent.knowledge.implementations.wiki import WikiKB

            return WikiKB(work_dir=str(Path(self._work_dir) / "wiki"))
```

- [ ] **Step 7: Run test to verify it passes**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_kb_can_be_created_and_discovered_by_manager -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add backend/packages/core/nexagent/knowledge/models.py backend/packages/core/nexagent/knowledge/manager.py backend/packages/core/nexagent/knowledge/implementations/wiki backend/tests/unit/test_wiki_kb.py
git commit -m "feat: register wiki knowledge backend"
```

### Task 2: Add Wiki Storage, Pages, and Manual Candidates

**Files:**
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/storage.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/links.py`
- Modify: `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`
- Test: `backend/tests/unit/test_wiki_kb.py`

- [ ] **Step 1: Write failing page storage tests**

Append to `backend/tests/unit/test_wiki_kb.py`:

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_pages_are_frontmatter_markdown_and_manual_pages_get_candidates():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("pages")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Useful knowledge", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        first = await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Transformer Architecture",
            content="# Transformer Architecture\n\nLinks to [[Attention]].",
            sources=["file-1"],
            confidence="EXTRACTED",
        )
        manual = await backend.update_wiki_page(
            kb_meta.kb_id,
            first["id"],
            "# Transformer Architecture\n\nManual version.",
        )
        generated = await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Transformer Architecture",
            content="# Transformer Architecture\n\nGenerated version.",
            sources=["file-2"],
            confidence="INFERRED",
        )

        pages = backend.list_wiki_pages(kb_meta.kb_id)["pages"]
        detail = backend.get_wiki_page(kb_meta.kb_id, first["id"])

        assert first["id"] == "topic:transformer-architecture"
        assert manual["manual_edited"] is True
        assert generated["candidate"] is not None
        assert detail["content"] == "# Transformer Architecture\n\nManual version."
        assert detail["candidate"]["content"] == "# Transformer Architecture\n\nGenerated version."
        assert pages[0]["has_candidate"] is True
        assert "wiki/topics/transformer-architecture.md" in detail["path"]
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_pages_are_frontmatter_markdown_and_manual_pages_get_candidates -q
```

Expected: FAIL because page methods do not exist.

- [ ] **Step 3: Implement link helpers**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/links.py`:

```python
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from nexagent.knowledge.implementations.wiki.constants import NOISE_WIKILINKS, WIKILINK_RE, WIKI_PAGE_TYPES


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
            for key in {
                self._normalize_link_key(page["title"]),
                self._normalize_link_key(page["id"]),
                self._normalize_link_key(str(page.get("path") or "").rsplit("/", 1)[-1].removesuffix(".md")),
            }:
                if key and all(existing["id"] != page["id"] for existing in index[key]):
                    index[key].append(entry)
        return dict(index)

    def _resolve_wikilink(self, link_title: str, title_index: dict[str, list[dict]]) -> list[dict]:
        key = self._normalize_link_key(link_title)
        if not key or key in NOISE_WIKILINKS:
            return []
        return title_index.get(key, [])

    def _tokenize(self, text: str) -> list[str]:
        return [item.lower() for item in re.findall(r"[\w\u4e00-\u9fff]+", text or "") if len(item) > 1]

    def _make_snippet(self, content: str, terms: list[str]) -> str:
        text = re.sub(r"\s+", " ", content or "").strip()
        if not text:
            return ""
        lower = text.lower()
        positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
        start = max(0, min(positions) - 80) if positions else 0
        return text[start : start + 260]
```

- [ ] **Step 4: Implement storage mixin**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/storage.py`:

```python
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
            frontmatter, _ = self._read_page(path)
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
        return yaml.safe_load(parts[1]) or {}, parts[2].strip()

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
```

- [ ] **Step 5: Wire page methods into `WikiKB`**

Modify `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py` so the class inherits `WikiStorageMixin` and `WikiLinksMixin`, then add:

```python
from datetime import UTC, datetime

from nexagent.knowledge.implementations.wiki.constants import CONFIDENCE_VALUES, WIKI_PAGE_TYPES
from nexagent.knowledge.implementations.wiki.links import WikiLinksMixin
from nexagent.knowledge.implementations.wiki.storage import WikiStorageMixin


def _now() -> str:
    return datetime.now(UTC).isoformat()
```

Inside `WikiKB`:

```python
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

    async def update_wiki_page(self, kb_id: str, page_id: str, content: str, frontmatter: dict | None = None) -> dict:
        path = self._find_page_path(kb_id, page_id)
        if path is None:
            raise ValueError(f"Wiki page {page_id} not found")
        current, _ = self._read_page(path)
        merged = dict(current)
        if frontmatter:
            merged.update(frontmatter)
        merged["manual_edited"] = True
        merged["updated_at"] = _now()
        merged["version"] = int(merged.get("version") or 1) + 1
        self._write_page(path, merged, content)
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
            old_frontmatter, _ = self._read_page(path)
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
        return self.get_wiki_page(kb_id, page_id)

    def _page_status(self, summary: dict, frontmatter: dict) -> str:
        if summary.get("has_candidate"):
            return "pending_candidate"
        if frontmatter.get("manual_edited"):
            return "manual_edited"
        if frontmatter.get("confidence") in {"AMBIGUOUS", "UNVERIFIED"}:
            return "needs_review"
        return "generated"
```

- [ ] **Step 6: Run page tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_pages_are_frontmatter_markdown_and_manual_pages_get_candidates -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/packages/core/nexagent/knowledge/implementations/wiki backend/tests/unit/test_wiki_kb.py
git commit -m "feat: add wiki page storage"
```

### Task 3: Add Wiki Compile and Search

**Files:**
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/compile.py`
- Modify: `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`
- Modify: `backend/packages/core/nexagent/knowledge/manager.py`
- Modify: `backend/packages/core/nexagent/knowledge/search_service.py`
- Modify: `backend/packages/core/nexagent/tools/builtin/knowledge_search.py`
- Test: `backend/tests/unit/test_wiki_kb.py`
- Test: `backend/tests/unit/test_knowledge_agent_tool.py`

- [ ] **Step 1: Write failing compile/search test**

Append to `backend/tests/unit/test_wiki_kb.py`:

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_kb_indexes_markdown_into_pages_and_searches(monkeypatch):
    from nexagent.knowledge.manager import reset_manager
    from nexagent.knowledge.models import FileStatus

    work_dir = _work_dir("compile")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Architecture notes", kb_type="wiki")
        file_meta = await manager.add_file(kb_meta.kb_id, "paper.md", b"# Transformer\n\nAttention links Encoder.")
        parsed = await manager.parse_file(kb_meta.kb_id, file_meta.file_id)
        backend = manager._find_backend(kb_meta.kb_id)

        async def fake_compile(kb_id, file_id, meta, markdown):
            assert "Attention links Encoder" in markdown
            source = await backend.create_or_update_wiki_page(
                kb_id,
                page_type="source",
                title="Transformer Paper",
                content="# Transformer Paper\n\n## Summary\n\nAttention links [[Encoder]].",
                sources=[file_id],
                confidence="EXTRACTED",
            )
            topic = await backend.create_or_update_wiki_page(
                kb_id,
                page_type="topic",
                title="Transformer Architecture",
                content="# Transformer Architecture\n\nAttention and Encoder are related.",
                sources=[file_id],
                confidence="EXTRACTED",
            )
            return [source, topic]

        monkeypatch.setattr(backend, "_compile_markdown_file", fake_compile)

        indexed = await manager.index_file(kb_meta.kb_id, parsed.file_id)
        pages = backend.list_wiki_pages(kb_meta.kb_id)["pages"]
        results = await manager.search(kb_meta.kb_id, "attention encoder", top_k=5, mode="wiki")

        assert indexed.status == FileStatus.INDEXED
        assert indexed.chunk_count == 2
        assert {page["type"] for page in pages} == {"source", "topic"}
        assert results[0].metadata["page_id"] == "topic:transformer-architecture"
        assert results[0].metadata["page_type"] == "topic"
        assert "Attention" in results[0].content
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_kb_indexes_markdown_into_pages_and_searches -q
```

Expected: FAIL because `_do_index` returns `0` and `_do_search` returns no results.

- [ ] **Step 3: Implement compile mixin**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/compile.py` with:

```python
from __future__ import annotations

import json
import re
import textwrap
from hashlib import sha256
from pathlib import Path
from typing import Any

from nexagent.knowledge.implementations.wiki.constants import CONFIDENCE_VALUES, WIKI_PROMPT_VERSION


class WikiCompileMixin:
    async def _compile_markdown_file(self, kb_id: str, file_id: str, file_meta, markdown: str) -> list[dict]:
        compiled = await self._compile_markdown_with_llm(kb_id, file_id, file_meta, markdown)
        source = compiled.get("source") or {}
        title = self._clean_wiki_title(source.get("title") or Path(file_meta.filename).stem or file_id)
        pages = [
            await self.create_or_update_wiki_page(
                kb_id,
                page_type="source",
                title=title,
                content=self._source_page_content(file_meta.filename, markdown, source),
                sources=[file_id],
                confidence=self._normalize_confidence(source.get("confidence"), "EXTRACTED"),
            )
        ]
        for item in self._clean_page_items(compiled.get("topics"), "topics")[:8]:
            pages.append(
                await self.create_or_update_wiki_page(
                    kb_id,
                    page_type="topic",
                    title=item["title"],
                    content=self._page_content_from_llm(item["title"], item.get("summary"), item.get("content"), title),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        for item in self._clean_page_items(compiled.get("entities"), "entities")[:12]:
            pages.append(
                await self.create_or_update_wiki_page(
                    kb_id,
                    page_type="entity",
                    title=item["title"],
                    content=self._page_content_from_llm(item["title"], item.get("summary"), item.get("content"), title),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        cache = self._load_cache(kb_id)
        cache[file_id] = {
            "filename": file_meta.filename,
            "content_hash": self._content_hash(markdown),
            "prompt_version": WIKI_PROMPT_VERSION,
            "status": "compiled",
            "page_ids": [page["id"] for page in pages],
        }
        self._save_cache(kb_id, cache)
        return pages

    async def _compile_markdown_with_llm(self, kb_id: str, file_id: str, file_meta, markdown: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        from nexagent.models.factory import load_chat_model_async

        llm = await load_chat_model_async()
        messages = self._build_compile_prompt(file_meta.filename, self._read_purpose(kb_id), markdown)
        response = await llm.ainvoke(
            [
                SystemMessage(content=messages[0]["content"]),
                HumanMessage(content=messages[1]["content"]),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            parsed = self._parse_llm_json(content)
            self._validate_compiled_payload(parsed)
            return parsed
        except ValueError as exc:
            repair_prompt = self._build_repair_prompt(content, str(exc))
            repaired_response = await llm.ainvoke(
                [
                    SystemMessage(content=repair_prompt[0]["content"]),
                    HumanMessage(content=repair_prompt[1]["content"]),
                ]
            )
            repaired_content = repaired_response.content if isinstance(repaired_response.content, str) else str(repaired_response.content)
            repaired = self._parse_llm_json(repaired_content)
            self._validate_compiled_payload(repaired)
            return repaired

    def _read_purpose(self, kb_id: str) -> str:
        path = self._db_root(kb_id) / "purpose.md"
        return path.read_text(encoding="utf-8")[:2000] if path.exists() else ""

    def _build_compile_prompt(self, filename: str, purpose: str, markdown: str) -> list[dict]:
        source_text = markdown[:12000]
        system_prompt = "你是 NexAgent 的 LLM Wiki 编译器。只输出合法 JSON，不要输出 Markdown 代码块或解释。"
        user_prompt = textwrap.dedent(f"""
            Wiki purpose:
            {purpose or "未设置"}
            Source filename:
            {filename}
            请返回 JSON 对象，结构为 source/topics/entities/synthesis。topics 和 entities 可以为空数组。
            confidence 只能是 EXTRACTED、INFERRED、AMBIGUOUS、UNVERIFIED。
            页面正文必须使用 Markdown，可用 [[页面标题]] 表达重要关联。
            Markdown source:
            {source_text}
        """).strip()
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    def _build_repair_prompt(self, bad_output: str, error: str) -> list[dict]:
        return [
            {"role": "system", "content": "你是 NexAgent Wiki JSON 修复器。只输出合法 JSON。"},
            {"role": "user", "content": f"错误：{error}\n请修复为 source/topics/entities/synthesis JSON：\n{bad_output}"},
        ]

    def _parse_llm_json(self, content: str) -> dict:
        raw = (content or "").strip()
        if raw.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM Wiki compile result must be a JSON object")
        return parsed

    def _validate_compiled_payload(self, payload: dict) -> None:
        if not isinstance(payload.get("source"), dict):
            raise ValueError("LLM Wiki compile result is missing source")
        if not str(payload["source"].get("title") or "").strip():
            raise ValueError("LLM Wiki source.title is empty")
        for section in ("topics", "entities"):
            if payload.get(section) is not None and not isinstance(payload.get(section), list):
                raise ValueError(f"LLM Wiki {section} must be a list")

    def _clean_page_items(self, items: Any, label: str) -> list[dict]:
        cleaned: list[dict] = []
        if not isinstance(items, list):
            return cleaned
        for item in items:
            if not isinstance(item, dict):
                continue
            title = self._clean_wiki_title(item.get("title"))
            body = str(item.get("content") or item.get("summary") or "").strip()
            if title and body:
                cleaned.append({**item, "title": title})
        return cleaned

    def _normalize_confidence(self, value: Any, default: str) -> str:
        confidence = str(value or default).strip().upper()
        return confidence if confidence in CONFIDENCE_VALUES else default

    def _source_page_content(self, filename: str, markdown: str, source: dict) -> str:
        summary = str(source.get("summary") or "").strip()
        key_points = source.get("key_points") if isinstance(source.get("key_points"), list) else []
        bullets = "\n".join(f"- {item}" for item in key_points if str(item).strip()) or "- No extracted items."
        return f"# {self._clean_wiki_title(source.get('title') or Path(filename).stem)}\n\nSource file: `{filename}`\n\n## Summary\n\n{summary or self._summarize(markdown)}\n\n## Key Points\n\n{bullets}"

    def _page_content_from_llm(self, title: str, summary: Any, content: Any, source_title: str) -> str:
        sections = [f"# {title}"]
        if str(summary or "").strip():
            sections.extend(["", "## Summary", "", str(summary).strip()])
        sections.extend(["", "## Notes", "", str(content or "").strip() or "No detailed content generated."])
        sections.extend(["", "## Sources", "", f"- [[{source_title}]]"])
        return "\n".join(sections)

    def _summarize(self, markdown: str) -> str:
        text = re.sub(r"\s+", " ", re.sub(r"^#+\s+", "", markdown, flags=re.MULTILINE)).strip()
        return text[:800] or "No textual content extracted."

    def _content_hash(self, markdown: str) -> str:
        return sha256((markdown or "").encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Wire compile and search into `WikiKB`**

Modify `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`:

```python
from nexagent.knowledge.implementations.wiki.compile import WikiCompileMixin


class WikiKB(WikiCompileMixin, WikiLinksMixin, WikiStorageMixin, KnowledgeBase):
```

Replace `_do_index` and `_do_search`:

```python
    async def _do_index(self, kb_meta: KBMeta, file_meta: FileMeta) -> int:
        parsed_path = Path(file_meta.parsed_path)
        markdown = parsed_path.read_text(encoding="utf-8", errors="replace")
        pages = await self._compile_markdown_file(kb_meta.kb_id, file_meta.file_id, file_meta, markdown)
        if pages:
            await self._refresh_corpus_synthesis(kb_meta.kb_id)
        self._refresh_index(kb_meta.kb_id)
        return len(pages)

    async def _do_search(self, query: str, kb_meta: KBMeta, top_k: int = 5, **kwargs) -> list[SearchResult]:
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

    def _iter_page_details(self, kb_id: str) -> list[dict]:
        details = []
        for path in sorted(self._wiki_root(kb_id).glob("**/*.md")):
            frontmatter, content = self._read_page(path)
            if not frontmatter:
                continue
            summary = self._page_summary(kb_id, path, frontmatter, content)
            details.append({**summary, "content": content, "frontmatter": frontmatter})
        return details

    def _score_page_match(self, detail: dict, terms: list[str]) -> dict:
        title = detail["title"].lower()
        content = detail["content"].lower()
        links = " ".join(self._extract_wikilinks(detail["content"])).lower()
        source_names = " ".join((self.get_file(detail["frontmatter"].get("kb_id", ""), source) or source).__str__() for source in detail["frontmatter"].get("sources", []))
        score = 0.0
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
                score += 4
                reasons.append("wikilink")
            if term in source_names.lower():
                score += 3
                reasons.append("source")
        return {"score": score, "reasons": sorted(set(reasons))}

    def _refresh_index(self, kb_id: str) -> None:
        lines = ["# Index", ""]
        for page in self.list_wiki_pages(kb_id)["pages"]:
            lines.append(f"- [[{page['title']}]] ({page['type']})")
        self._atomic_write_text(self._db_root(kb_id) / "index.md", "\n".join(lines) + "\n")

    async def _refresh_corpus_synthesis(self, kb_id: str) -> dict | None:
        pages = self.list_wiki_pages(kb_id)["pages"]
        source_pages = [page for page in pages if page["type"] == "source"]
        topic_pages = [page for page in pages if page["type"] == "topic"]
        entity_pages = [page for page in pages if page["type"] == "entity"]
        if not source_pages and not topic_pages and not entity_pages:
            return None
        content = "\n".join(
            [
                "# Wiki Synthesis",
                "",
                "## Summary",
                "",
                f"当前 Wiki 包含 {len(source_pages)} 个来源页、{len(topic_pages)} 个主题页、{len(entity_pages)} 个实体页。",
                "",
                "## Source Pages",
                "",
                "\n".join(f"- [[{page['title']}]]" for page in source_pages[:20]) or "- None",
                "",
                "## Core Topics",
                "",
                "\n".join(f"- [[{page['title']}]]" for page in topic_pages[:20]) or "- None",
                "",
                "## Core Entities",
                "",
                "\n".join(f"- [[{page['title']}]]" for page in entity_pages[:20]) or "- None",
            ]
        )
        sources = sorted({source for page in pages for source in page.get("sources", [])})
        return await self.create_or_update_wiki_page(
            kb_id,
            page_type="synthesis",
            title="Wiki Synthesis",
            content=content,
            sources=sources,
            confidence="INFERRED",
        )
```

After adding the snippet, fix `source_names` to look up `self._files` directly:

```python
        source_names = " ".join(
            (self._files.get(source_id).filename if self._files.get(source_id) else source_id)
            for source_id in detail["frontmatter"].get("sources", [])
        )
```

- [ ] **Step 5: Add query config support**

Modify `backend/packages/core/nexagent/knowledge/manager.py`:

```python
def _default_query_config(kb_type: str) -> dict:
    if kb_type == "wiki":
        return {
            "mode": "wiki",
            "search_mode": "wiki",
            "final_top_k": 10,
            "recall_top_k": 10,
            "similarity_threshold": 0.0,
            "use_reranker": False,
            "reranker_model": "",
        }
```

Add to `_available_modes`:

```python
    if kb_type == "wiki":
        return ["wiki"]
```

Add to `_query_options`:

```python
    if kb_type == "wiki":
        return [
            {"key": "final_top_k", "label": "返回数量", "type": "number", "min": 1, "max": 50},
        ]
```

- [ ] **Step 6: Allow `knowledge_search` wiki mode**

Modify `backend/packages/core/nexagent/tools/builtin/knowledge_search.py`:

```python
VALID_TOOL_MODES = {
    "vector",
    "keyword",
    "hybrid",
    "lightrag_local",
    "lightrag_global",
    "lightrag_hybrid",
    "wiki",
}
```

Update unsupported-mode message to include `wiki`.

- [ ] **Step 7: Add failing tool assertion**

Append to `backend/tests/unit/test_knowledge_agent_tool.py`:

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_knowledge_search_tool_accepts_wiki_mode(monkeypatch):
    from nexagent.knowledge.retriever import RetrievedChunk
    from nexagent.knowledge.search_service import StructuredSearchResult
    from nexagent.tools.builtin.knowledge_search import get_knowledge_search_tool

    class FakeManager:
        def list_kbs(self):
            return []

    async def fake_structured_retrieve(**kwargs):
        assert kwargs["mode"] == "wiki"
        return StructuredSearchResult(
            chunks=[
                RetrievedChunk(
                    content="Wiki page evidence.",
                    score=8.0,
                    kb_id="wiki-1",
                    source="Transformer Architecture",
                    file_id="file-1",
                    metadata={"page_id": "topic:transformer-architecture", "page_type": "topic"},
                )
            ],
            warnings=[],
        )

    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())
    monkeypatch.setattr("nexagent.knowledge.search_service.structured_retrieve", fake_structured_retrieve)

    tool = get_knowledge_search_tool(["wiki-1"])
    output = await tool.ainvoke({"query": "transformer", "top_k": 1, "mode": "wiki"})

    assert "Wiki page evidence." in output
    assert "Transformer Architecture" in output
    assert "```nexagent-evidence" in output
```

- [ ] **Step 8: Run tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_kb_indexes_markdown_into_pages_and_searches tests/unit/test_knowledge_agent_tool.py::test_knowledge_search_tool_accepts_wiki_mode -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add backend/packages/core/nexagent/knowledge/implementations/wiki backend/packages/core/nexagent/knowledge/manager.py backend/packages/core/nexagent/tools/builtin/knowledge_search.py backend/tests/unit/test_wiki_kb.py backend/tests/unit/test_knowledge_agent_tool.py
git commit -m "feat: compile and search wiki pages"
```

### Task 4: Add Wiki Graph, Lint, Candidate Actions, and Source Cleanup

**Files:**
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/graph.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/lint.py`
- Create: `backend/packages/core/nexagent/knowledge/implementations/wiki/repair.py`
- Modify: `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`
- Test: `backend/tests/unit/test_wiki_kb.py`

- [ ] **Step 1: Write failing graph/lint/candidate tests**

Append to `backend/tests/unit/test_wiki_kb.py`:

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_graph_lint_and_candidate_actions():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("graph-lint")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        page = await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Alpha",
            content="# Alpha\n\nLinks to [[Beta]] and [[Missing]].",
            sources=["file-1"],
            confidence="UNVERIFIED",
        )
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="entity",
            title="Beta",
            content="# Beta\n\nBack to [[Alpha]].",
            sources=["file-1"],
            confidence="EXTRACTED",
        )
        await backend.update_wiki_page(kb_meta.kb_id, page["id"], "# Alpha\n\nManual.")
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Alpha",
            content="# Alpha\n\nCandidate mentions [[Beta]].",
            confidence="INFERRED",
        )

        graph = backend.get_wiki_graph(kb_meta.kb_id)
        lint = backend.lint_wiki(kb_meta.kb_id)
        accepted = await backend.accept_generated_wiki_page(kb_meta.kb_id, page["id"])

        assert graph["stats"]["total_nodes"] == 2
        assert any(edge["signals"]["wikilink"] for edge in graph["edges"])
        assert any(issue["type"] == "source_missing" for issue in lint["issues"])
        assert any(issue["type"] == "needs_review" for issue in lint["issues"])
        assert accepted["candidate"] is None
        assert "Candidate mentions" in accepted["content"]
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_graph_lint_and_candidate_actions -q
```

Expected: FAIL because graph/lint/candidate action methods are missing.

- [ ] **Step 3: Implement graph mixin**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/graph.py` with a direct adaptation of the spec:

```python
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class WikiGraphMixin:
    def get_wiki_graph(self, kb_id: str, *, max_edges: int = 80, include_weak: bool = False, q: str | None = None) -> dict:
        pages = self._iter_page_details(kb_id)
        if q:
            key = self._normalize_link_key(q)
            pages = [page for page in pages if key and (key in self._normalize_link_key(page["title"]) or key in self._normalize_link_key(page["content"]))]
        title_index = self._title_index(pages)
        explicit_neighbors: dict[str, set[str]] = defaultdict(set)
        edge_signals: dict[tuple[str, str], dict[str, Any]] = {}

        def edge_key(left: str, right: str) -> tuple[str, str]:
            return tuple(sorted((left, right)))

        for page in pages:
            for link_title in self._extract_wikilinks(page["content"]):
                targets = self._resolve_wikilink(link_title, title_index)
                if len(targets) != 1:
                    continue
                target_id = targets[0]["id"]
                if target_id == page["id"]:
                    continue
                explicit_neighbors[page["id"]].add(target_id)
                explicit_neighbors[target_id].add(page["id"])
                edge_signals.setdefault(edge_key(page["id"], target_id), self._empty_signals())["wikilink"] = True

        pages_by_source: dict[str, list[dict]] = defaultdict(list)
        for page in pages:
            for source_id in page["frontmatter"].get("sources") or []:
                pages_by_source[source_id].append(page)
        for source_id, source_pages in pages_by_source.items():
            for index, left in enumerate(source_pages):
                for right in source_pages[index + 1 :]:
                    signals = edge_signals.setdefault(edge_key(left["id"], right["id"]), self._empty_signals())
                    if source_id not in signals["source_overlap"]:
                        signals["source_overlap"].append(source_id)

        page_type_by_id = {page["id"]: page["type"] for page in pages}
        edges = []
        for (source, target), signals in edge_signals.items():
            signals["type_affinity"] = page_type_by_id.get(source) == page_type_by_id.get(target)
            weight = self._edge_weight(signals)
            if weight > 0:
                edges.append({"source": source, "target": target, "weight": weight, "signals": signals})
        display_edges = self._display_edges(edges, max_edges=max_edges, include_weak=include_weak)
        communities = self._communities([page["id"] for page in pages], display_edges)
        nodes = [
            {
                "id": page["id"],
                "label": page["title"],
                "type": page["type"],
                "sources": page["frontmatter"].get("sources") or [],
                "confidence": page["frontmatter"].get("confidence", "UNVERIFIED"),
                "community": communities.get(page["id"], 0),
            }
            for page in pages
        ]
        return {"nodes": nodes, "edges": display_edges, "stats": {"total_nodes": len(nodes), "total_edges": len(display_edges), "raw_edge_count": len(edges), "communities": len(set(communities.values())) if communities else 0}}

    def _empty_signals(self) -> dict[str, Any]:
        return {"wikilink": False, "source_overlap": [], "common_neighbors": [], "type_affinity": False}

    def _edge_weight(self, signals: dict[str, Any]) -> float:
        return (3.0 if signals.get("wikilink") else 0.0) + (4.0 if signals.get("source_overlap") else 0.0) + (1.0 if signals.get("type_affinity") else 0.0)

    def _display_edges(self, edges: list[dict], *, max_edges: int, include_weak: bool) -> list[dict]:
        ordered = sorted(edges, key=lambda item: item.get("weight", 0), reverse=True)
        if include_weak:
            return ordered[: max(1, int(max_edges or 80))]
        explicit = [edge for edge in ordered if edge.get("signals", {}).get("wikilink")]
        weak = [edge for edge in ordered if not edge.get("signals", {}).get("wikilink")]
        return (explicit + weak)[: max(1, int(max_edges or 80))]

    def _communities(self, node_ids: list[str], edges: list[dict]) -> dict[str, int]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge["source"]].add(edge["target"])
            adjacency[edge["target"]].add(edge["source"])
        communities: dict[str, int] = {}
        community_id = 0
        for node_id in node_ids:
            if node_id in communities:
                continue
            community_id += 1
            queue = deque([node_id])
            communities[node_id] = community_id
            while queue:
                current = queue.popleft()
                for nxt in adjacency[current]:
                    if nxt not in communities:
                        communities[nxt] = community_id
                        queue.append(nxt)
        return communities
```

- [ ] **Step 4: Implement lint mixin**

Create `backend/packages/core/nexagent/knowledge/implementations/wiki/lint.py`:

```python
from __future__ import annotations

from collections import defaultdict


class WikiLintMixin:
    def lint_wiki(self, kb_id: str) -> dict:
        pages = self._iter_page_details(kb_id)
        title_index = self._title_index(pages)
        title_counts = defaultdict(int)
        typed_title_counts = defaultdict(int)
        for page in pages:
            key = self._normalize_link_key(page["title"])
            title_counts[key] += 1
            typed_title_counts[(page["type"], key)] += 1
        linked_ids: set[str] = set()
        issues = []
        for page in pages:
            required = {"id", "title", "type", "sources", "confidence", "updated_at", "manual_edited"}
            missing = sorted(required - set(page["frontmatter"].keys()))
            if missing:
                issues.append(self._lint_issue("missing_frontmatter", page["id"], "error", fields=missing))
            key = self._normalize_link_key(page["title"])
            if typed_title_counts[(page["type"], key)] > 1:
                issues.append(self._lint_issue("duplicate_title", page["id"], "warning"))
            elif title_counts[key] > 1:
                issues.append(self._lint_issue("ambiguous_title", page["id"], "warning"))
            for source_id in page["frontmatter"].get("sources") or []:
                if source_id not in self._files:
                    issues.append(self._lint_issue("source_missing", page["id"], "error", target=source_id))
            if page["frontmatter"].get("confidence") in {"AMBIGUOUS", "UNVERIFIED"}:
                issues.append(self._lint_issue("needs_review", page["id"], "info", confidence=page["frontmatter"].get("confidence")))
            for link in self._extract_wikilinks(page["content"]):
                targets = self._resolve_wikilink(link, title_index)
                if not targets:
                    issues.append(self._lint_issue("broken_link", page["id"], "error", target=link))
                elif len(targets) > 1:
                    issues.append(self._lint_issue("ambiguous_link", page["id"], "warning", target=link))
                else:
                    linked_ids.add(targets[0]["id"])
        for page in pages:
            if page["id"] not in linked_ids and not self._extract_wikilinks(page["content"]) and page["type"] != "source":
                issues.append(self._lint_issue("orphan_page", page["id"], "warning"))
        for page_id in sorted(self._load_state(kb_id).get("candidates", {})):
            issues.append(self._lint_issue("pending_candidate", page_id, "warning", action="accept_candidate"))
        return {"issues": issues, "summary": {"issue_count": len(issues), "page_count": len(pages)}, "compile_status": self._load_state(kb_id).get("compile_status", {"status": "idle"})}

    def _lint_issue(self, issue_type: str, page_id: str, severity: str, **extra) -> dict:
        messages = {
            "missing_frontmatter": "页面缺少必要 frontmatter 字段",
            "duplicate_title": "存在重复页面标题",
            "ambiguous_title": "不同类型页面存在同名标题",
            "source_missing": "页面引用的来源文件不存在",
            "needs_review": "页面置信度需要人工复核",
            "broken_link": "页面包含断开的 wikilink",
            "ambiguous_link": "页面 wikilink 指向多个同名页面",
            "orphan_page": "页面没有被其他页面链接且自身没有链接",
            "pending_candidate": "存在待处理的系统候选版本",
        }
        target = extra.get("target")
        issue_id = ":".join([issue_type, page_id, str(target or "")]).rstrip(":")
        repairable = issue_type in {"broken_link", "ambiguous_link", "needs_review", "orphan_page"}
        return {"id": issue_id, "type": issue_type, "page_id": page_id, "severity": severity, "message": messages.get(issue_type, issue_type), "action": extra.pop("action", "review"), "repairable": repairable, "repair_action": "ai_candidate" if repairable else "review", **extra}
```

- [ ] **Step 5: Add candidate and delete methods**

Modify `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`:

```python
from nexagent.knowledge.implementations.wiki.graph import WikiGraphMixin
from nexagent.knowledge.implementations.wiki.lint import WikiLintMixin


class WikiKB(WikiGraphMixin, WikiLintMixin, WikiCompileMixin, WikiLinksMixin, WikiStorageMixin, KnowledgeBase):
```

Add methods:

```python
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
```

- [ ] **Step 6: Run tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py::test_wiki_graph_lint_and_candidate_actions -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/packages/core/nexagent/knowledge/implementations/wiki backend/tests/unit/test_wiki_kb.py
git commit -m "feat: add wiki graph and health checks"
```

### Task 5: Add Wiki Knowledge API and Task Routing

**Files:**
- Modify: `backend/app/gateway/routers/knowledge.py`
- Test: `backend/tests/unit/test_wiki_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `backend/tests/unit/test_wiki_routes.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.routers import knowledge


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_kb_accepts_wiki_without_embedding(monkeypatch):
    calls = {}

    class FakeManager:
        async def create_kb(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(to_dict=lambda: {"kb_id": "wiki-1", "kb_type": "wiki", "name": kwargs["name"]})

    monkeypatch.setattr(knowledge, "_prod_enabled", lambda: True)
    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    result = await knowledge.create_kb(knowledge.KBCreateRequest(name="Wiki", description="notes", kb_type="wiki"))

    assert result == {"kb_id": "wiki-1", "kb_type": "wiki", "name": "Wiki"}
    assert calls["kb_type"] == "wiki"
    assert calls["embed_info"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_pages_route_rejects_non_wiki(monkeypatch):
    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="milvus"))

    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    with pytest.raises(HTTPException) as exc:
        await knowledge.list_wiki_pages("kb-1")

    assert exc.value.status_code == 400
    assert "Wiki" in str(exc.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_pages_route_delegates_to_backend(monkeypatch):
    calls = {}

    class FakeBackend:
        def list_wiki_pages(self, kb_id, page_type=None, q=None, status=None, source_file_id=None):
            calls.update({"kb_id": kb_id, "page_type": page_type, "q": q, "status": status, "source_file_id": source_file_id})
            return {"pages": [{"id": "topic:alpha"}]}

    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return FakeBackend()

    monkeypatch.setattr(knowledge, "_mgr", lambda: FakeManager())

    result = await knowledge.list_wiki_pages("wiki-1", type="topic", q="alpha", status="generated", source_file_id="file-1")

    assert result == {"pages": [{"id": "topic:alpha"}]}
    assert calls == {"kb_id": "wiki-1", "page_type": "topic", "q": "alpha", "status": "generated", "source_file_id": "file-1"}
```

- [ ] **Step 2: Run route tests to verify failures**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_routes.py -q
```

Expected: FAIL because route support is missing.

- [ ] **Step 3: Add Wiki helpers to router**

Modify `backend/app/gateway/routers/knowledge.py` after `_kb_or_404`:

```python
def _local_wiki_kb_or_404(kb_id: str):
    mgr = _mgr()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base not found: {kb_id}")
    if kb.kb_type.value != "wiki":
        raise HTTPException(status_code=400, detail="This endpoint only supports Wiki knowledge bases.")
    return mgr, kb, mgr._find_backend(kb_id)


async def _is_local_wiki_kb(kb_id: str) -> bool:
    try:
        kb = _mgr().get_kb(kb_id)
        return bool(kb and kb.kb_type.value == "wiki")
    except Exception:
        return False
```

- [ ] **Step 4: Route Wiki creation through local manager**

In `create_kb`, before production branch:

```python
    if req.kb_type == "wiki":
        mgr = _mgr()
        kb = await mgr.create_kb(
            name=req.name,
            description=req.description,
            kb_type="wiki",
            embed_info=None,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            chunk_preset_id=req.chunk_preset_id,
            chunk_parser_config=req.chunk_parser_config,
        )
        return kb.to_dict()
```

- [ ] **Step 5: Merge local Wiki Kbs in production list**

In `list_kbs`, inside `_prod_enabled()` branch, add local Wiki items:

```python
        local_wiki = []
        try:
            for kb in _mgr().list_kbs():
                if kb.kb_type.value != "wiki":
                    continue
                item = kb.to_dict()
                item["extra"] = {**item.get("extra", {}), "storage": "local_wiki"}
                local_wiki.append(item)
        except Exception:
            local_wiki = []
        items = prod_kbs + local_wiki + legacy
```

- [ ] **Step 6: Add Wiki endpoints**

Add endpoints before `@router.get("/{kb_id}", ...)`:

```python
@router.post("/{kb_id}/wiki/compile", summary="Compile Wiki pages")
async def compile_wiki(kb_id: str, body: dict[str, Any] | None = None):
    mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    file_ids = (body or {}).get("file_ids")
    if file_ids is not None and not isinstance(file_ids, list):
        raise HTTPException(status_code=400, detail="file_ids must be a list")
    force = bool((body or {}).get("force"))
    retry_failed = bool((body or {}).get("retry_failed"))
    result = await backend.compile_wiki(kb_id, file_ids=file_ids, force=force, retry_failed=retry_failed)
    return result


@router.get("/{kb_id}/wiki/pages", summary="List Wiki pages")
async def list_wiki_pages(kb_id: str, type: str | None = None, q: str | None = None, status: str | None = None, source_file_id: str | None = None):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.list_wiki_pages(kb_id, page_type=type, q=q, status=status, source_file_id=source_file_id)


@router.get("/{kb_id}/wiki/pages/{page_id}", summary="Get Wiki page")
async def get_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return backend.get_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{kb_id}/wiki/pages/{page_id}", summary="Update Wiki page")
async def update_wiki_page(kb_id: str, page_id: str, body: dict[str, Any]):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return await backend.update_wiki_page(kb_id, page_id, str(body.get("content") or ""), frontmatter=body.get("frontmatter") if isinstance(body.get("frontmatter"), dict) else None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{kb_id}/wiki/pages/{page_id}", summary="Delete Wiki page")
async def delete_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    try:
        return await backend.delete_wiki_page(kb_id, page_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{kb_id}/wiki/pages/{page_id}/accept-generated", summary="Accept Wiki candidate")
async def accept_generated_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return await backend.accept_generated_wiki_page(kb_id, page_id)


@router.post("/{kb_id}/wiki/pages/{page_id}/discard-generated", summary="Discard Wiki candidate")
async def discard_generated_wiki_page(kb_id: str, page_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return await backend.discard_generated_wiki_page(kb_id, page_id)


@router.get("/{kb_id}/wiki/graph", summary="Get Wiki graph")
async def get_wiki_graph(kb_id: str, max_edges: int = Query(80), include_weak: bool = Query(False), q: str | None = Query(None)):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.get_wiki_graph(kb_id, max_edges=max_edges, include_weak=include_weak, q=q)


@router.get("/{kb_id}/wiki/lint", summary="Lint Wiki")
async def lint_wiki(kb_id: str):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    return backend.lint_wiki(kb_id)
```

- [ ] **Step 7: Route file/list/search operations to local Wiki in production mode**

For each production branch in `get_kb`, `get_query_config`, `list_files`, `upload_file`, `process_file_async`, `process_all_files`, `get_file`, `delete_file`, `preview_parsed_file`, and `search_kb`, add a first check:

```python
    if await _is_local_wiki_kb(kb_id):
        # use the same local manager path as legacy mode for this endpoint
```

Use the existing non-production local code body for Wiki. This keeps Milvus/LightRAG production behavior untouched.

- [ ] **Step 8: Run route tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_routes.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add backend/app/gateway/routers/knowledge.py backend/tests/unit/test_wiki_routes.py
git commit -m "feat: expose wiki knowledge routes"
```

### Task 6: Add Conversation Crystallization Into Wiki KB

**Files:**
- Modify: `backend/packages/core/nexagent/services/wiki_service.py`
- Modify: `backend/app/gateway/routers/wiki.py`
- Modify: `backend/app/gateway/routers/knowledge.py`
- Test: `backend/tests/unit/test_wiki_service.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/unit/test_wiki_service.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crystallize_thread_into_wiki_kb_registers_source_and_page(monkeypatch):
    from nexagent.services import wiki_service

    calls = {}

    class FakeLLM:
        async def ainvoke(self, messages):
            return SimpleNamespace(content="# Decision Log\n\n## Summary\n\nUse Wiki KB.\n\n标签: wiki, decision")

    class FakeBackend:
        async def add_file(self, kb_id, filename, content):
            calls["add_file"] = {"kb_id": kb_id, "filename": filename, "content": content.decode("utf-8")}
            return SimpleNamespace(file_id="file-1")

        async def parse_file(self, kb_id, file_id):
            calls["parse_file"] = (kb_id, file_id)

        async def index_file(self, kb_id, file_id):
            calls["index_file"] = (kb_id, file_id)

        async def crystallize_wiki_text(self, kb_id, title, content, page_type="note", sources=None, confidence="UNVERIFIED"):
            calls["crystallize"] = {"kb_id": kb_id, "title": title, "content": content, "sources": sources, "confidence": confidence}
            return {"id": "note:decision-log", "title": title, "type": page_type, "sources": sources}

    class FakeManager:
        def get_kb(self, kb_id):
            return SimpleNamespace(kb_id=kb_id, kb_type=SimpleNamespace(value="wiki"))

        def _find_backend(self, kb_id):
            return FakeBackend()

    async def fake_list_messages(thread_id):
        return [{"role": "user", "content": "Should we use Wiki KB?"}, {"role": "assistant", "content": "Yes."}]

    monkeypatch.setattr("nexagent.services.conversation_service.list_messages", fake_list_messages)
    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", lambda model=None: FakeLLM())
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())

    result = await wiki_service.crystallize_thread("thread-1", kb_id="wiki-1", model="test/model")

    assert result["id"] == "note:decision-log"
    assert result["file_id"] == "file-1"
    assert calls["add_file"]["filename"] == "Decision Log.md"
    assert calls["crystallize"]["sources"] == ["file-1"]
    assert calls["crystallize"]["confidence"] == "UNVERIFIED"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_service.py -q
```

Expected: FAIL because current service writes local global pages.

- [ ] **Step 3: Implement Wiki KB crystallization path**

In `backend/packages/core/nexagent/services/wiki_service.py`, add:

```python
async def _crystallize_into_wiki_kb(kb_id: str, title: str, markdown: str) -> dict[str, Any]:
    from nexagent.knowledge.manager import get_manager

    manager = get_manager()
    kb = manager.get_kb(kb_id)
    if kb is None:
        raise ValueError(f"知识库 {kb_id} 不存在。")
    if kb.kb_type.value != "wiki":
        raise ValueError(f"知识库 {kb_id} 不是 Wiki 类型。")
    backend = manager._find_backend(kb_id)
    source = await backend.add_file(kb_id, f"{title}.md", markdown.encode("utf-8"))
    file_id = source.file_id
    warning = ""
    try:
        await backend.parse_file(kb_id, file_id)
        await backend.index_file(kb_id, file_id)
    except Exception as exc:
        warning = f"页面已创建，但素材解析/编译未完成：{exc}"
    page = await backend.crystallize_wiki_text(
        kb_id,
        title=title,
        content=markdown,
        page_type="note",
        sources=[file_id],
        confidence="UNVERIFIED",
    )
    return {**page, "kb_id": kb_id, "file_id": file_id, "warning": warning or None, "content": markdown}
```

In `crystallize_thread`, after generating `markdown`, title, and tags:

```python
    if kb_id:
        try:
            return await _crystallize_into_wiki_kb(kb_id, title, markdown)
        except ValueError:
            raise
```

Keep the old global notebook behavior when `kb_id` is omitted.

- [ ] **Step 4: Add `crystallize_wiki_text` to `WikiKB`**

In `backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py`:

```python
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
```

- [ ] **Step 5: Add per-KB crystallize route**

In `backend/app/gateway/routers/knowledge.py`:

```python
@router.post("/{kb_id}/wiki/crystallize", summary="Crystallize Markdown into Wiki")
async def crystallize_wiki(kb_id: str, body: dict[str, Any]):
    _mgr, _kb, backend = _local_wiki_kb_or_404(kb_id)
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    page_type = str(body.get("type") or "note").strip()
    confidence = str(body.get("confidence") or "UNVERIFIED").strip().upper()
    sources = body.get("sources") if isinstance(body.get("sources"), list) else []
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content are required")
    return await backend.crystallize_wiki_text(kb_id, title, content, page_type=page_type, sources=sources, confidence=confidence)
```

- [ ] **Step 6: Run service tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add backend/packages/core/nexagent/services/wiki_service.py backend/app/gateway/routers/wiki.py backend/app/gateway/routers/knowledge.py backend/packages/core/nexagent/knowledge/implementations/wiki/kb.py backend/tests/unit/test_wiki_service.py
git commit -m "feat: crystallize conversations into wiki kbs"
```

### Task 7: Frontend API Types and Knowledge Create Flow

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/knowledge/page.tsx`

- [ ] **Step 1: Update TypeScript API types**

Modify `frontend/src/lib/api.ts`:

```ts
export interface KBMeta {
  kb_id: string;
  name: string;
  kb_type: "milvus" | "lightrag" | "wiki";
  description: string;
  chunk_size: number;
  chunk_overlap: number;
  chunk_preset_id?: "general" | "qa" | "book" | "laws" | "paper";
  chunk_parser_config?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  embed_info: { model: string; dimension: number; base_url?: string };
  extra?: Record<string, unknown>;
}
```

Add Wiki types and API functions near the knowledge functions:

```ts
export interface WikiPageSummary {
  id: string;
  title: string;
  type: "source" | "entity" | "topic" | "synthesis" | "comparison" | "query" | "note";
  path: string;
  manual_edited: boolean;
  confidence: "EXTRACTED" | "INFERRED" | "AMBIGUOUS" | "UNVERIFIED" | string;
  updated_at?: string;
  sources: string[];
  excerpt: string;
  has_candidate?: boolean;
  status?: string;
}

export interface WikiPageDetail extends WikiPageSummary {
  content: string;
  frontmatter: Record<string, unknown>;
  candidate?: { frontmatter: Record<string, unknown>; content: string; created_at: string } | null;
}

export interface WikiGraphPayload {
  nodes: Array<{ id: string; label: string; type: string; sources: string[]; confidence: string; community: number }>;
  edges: Array<{ source: string; target: string; weight: number; signals: Record<string, unknown> }>;
  stats: Record<string, number>;
}

export interface WikiLintPayload {
  issues: Array<{ id: string; type: string; page_id: string; severity: string; message: string; action?: string; repairable?: boolean; repair_action?: string }>;
  summary: { issue_count?: number; page_count?: number };
  compile_status?: Record<string, unknown>;
}

export async function fetchWikiKbPages(kbId: string, params: Record<string, string> = {}): Promise<WikiPageSummary[]> {
  const query = new URLSearchParams(params);
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages${query.toString() ? `?${query}` : ""}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return (await res.json()).pages ?? [];
}

export async function fetchWikiKbPage(kbId: string, pageId: string): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function updateWikiKbPage(kbId: string, pageId: string, body: { content: string; frontmatter?: Record<string, unknown> }): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function fetchWikiKbGraph(kbId: string, params: Record<string, string> = {}): Promise<WikiGraphPayload> {
  const query = new URLSearchParams(params);
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/graph${query.toString() ? `?${query}` : ""}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function fetchWikiKbLint(kbId: string): Promise<WikiLintPayload> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/lint`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}
```

- [ ] **Step 2: Update Knowledge create type and defaults**

In `frontend/src/app/knowledge/page.tsx`:

```ts
type KBKind = "milvus" | "lightrag" | "wiki";
```

In the type cards grid, add a Wiki card:

```tsx
<TypeCard
  active={form.kb_type === "wiki"}
  icon={BookOpen}
  title="Wiki"
  description="适合把资料和对话沉淀成可维护页面、双链和页面关系图。"
  onClick={() => setForm({ ...form, kb_type: "wiki" })}
/>
```

Change submit disabled:

```ts
const submitDisabled = !form.name.trim() || (form.kb_type !== "wiki" && !form.embed_model) || createMutation.isPending;
```

Change create payload:

```ts
const kb = await createKB({
  name: form.name.trim(),
  description: form.description.trim(),
  kb_type: form.kb_type,
  chunk_size: form.chunk_size,
  chunk_overlap: form.chunk_overlap,
  chunk_preset_id: form.chunk_preset_id,
  embed_model: form.kb_type === "wiki" ? undefined : form.embed_model || undefined,
  embed_dimension: form.kb_type === "wiki" ? undefined : form.embed_dimension || undefined,
});
```

Hide embedding section when `form.kb_type === "wiki"` by wrapping it:

```tsx
{form.kb_type !== "wiki" ? (
  <FormSection title="Embedding 配置" description="从设置页已添加的模型供应商中选择 embedding 模型。保存时使用 provider::model，避免同名模型串供应商。">
    ...
  </FormSection>
) : null}
```

- [ ] **Step 3: Update stats and cards**

Change stats:

```tsx
<Stat label="LLM Wiki" value={kbs.filter((item) => item.kb_type === "wiki").length} icon={BookOpen} />
```

Change `KBCard`:

```tsx
const isWiki = kb.kb_type === "wiki";
const isRag = kb.kb_type === "milvus";
```

Use labels:

```tsx
<Badge variant={isWiki ? "warning" : isRag ? "teal" : "violet"}>
  {isWiki ? "Wiki" : isRag ? "向量 RAG" : "LightRAG"}
</Badge>
```

Hide embedding dimension badge for Wiki:

```tsx
{isWiki ? <Badge variant="secondary">Markdown</Badge> : <Badge variant="secondary">{kb.embed_info?.dimension || "-"} dim</Badge>}
```

- [ ] **Step 4: Run frontend lint**

Run:

```bash
cd frontend && npm run lint
```

Expected: PASS or existing unrelated lint failures only. Fix new TypeScript/ESLint errors before continuing.

- [ ] **Step 5: Commit**

Run:

```bash
git add frontend/src/lib/api.ts frontend/src/app/knowledge/page.tsx
git commit -m "feat: add wiki knowledge creation UI"
```

### Task 8: Frontend Wiki Workbench and Chat Modal

**Files:**
- Create: `frontend/src/components/wiki/WikiWorkbench.tsx`
- Create: `frontend/src/components/wiki/WikiPagePanel.tsx`
- Create: `frontend/src/components/wiki/WikiGraphPanel.tsx`
- Create: `frontend/src/components/wiki/WikiLintPanel.tsx`
- Create: `frontend/src/components/wiki/WikiCrystallizePanel.tsx`
- Modify: `frontend/src/app/knowledge/[id]/page.tsx`
- Create: `frontend/src/app/knowledge/[id]/wiki/graph/page.tsx`
- Modify: `frontend/src/components/chat/WikiModal.tsx`

- [ ] **Step 1: Create Wiki workbench shell**

Create `frontend/src/components/wiki/WikiWorkbench.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { BookOpen, FileText, GitBranch, HeartPulse, Sparkles } from "lucide-react";
import {
  fetchWikiKbGraph,
  fetchWikiKbLint,
  fetchWikiKbPage,
  fetchWikiKbPages,
  type FileMeta,
  type KBMeta,
  type WikiGraphPayload,
  type WikiLintPayload,
  type WikiPageDetail,
  type WikiPageSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { WikiPagePanel } from "@/components/wiki/WikiPagePanel";
import { WikiGraphPanel } from "@/components/wiki/WikiGraphPanel";
import { WikiLintPanel } from "@/components/wiki/WikiLintPanel";
import { WikiCrystallizePanel } from "@/components/wiki/WikiCrystallizePanel";

type Tab = "pages" | "graph" | "lint" | "crystallize";

export function WikiWorkbench({ kb, files, reload }: { kb: KBMeta; files: FileMeta[]; reload: () => Promise<void> }) {
  const [tab, setTab] = useState<Tab>("pages");
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selectedPage, setSelectedPage] = useState<WikiPageDetail | null>(null);
  const [graph, setGraph] = useState<WikiGraphPayload>({ nodes: [], edges: [], stats: {} });
  const [lint, setLint] = useState<WikiLintPayload>({ issues: [], summary: {} });
  const [loading, setLoading] = useState(false);

  const loadWiki = useCallback(async () => {
    setLoading(true);
    try {
      const [nextPages, nextGraph, nextLint] = await Promise.all([
        fetchWikiKbPages(kb.kb_id),
        fetchWikiKbGraph(kb.kb_id),
        fetchWikiKbLint(kb.kb_id),
      ]);
      setPages(nextPages);
      setGraph(nextGraph);
      setLint(nextLint);
      if (!selectedPage && nextPages[0]) {
        setSelectedPage(await fetchWikiKbPage(kb.kb_id, nextPages[0].id));
      }
    } finally {
      setLoading(false);
    }
  }, [kb.kb_id, selectedPage]);

  useEffect(() => {
    void loadWiki();
  }, [loadWiki]);

  const tabs: Array<{ key: Tab; label: string; icon: typeof BookOpen }> = [
    { key: "pages", label: "Wiki 页面", icon: FileText },
    { key: "graph", label: "关系图谱", icon: GitBranch },
    { key: "lint", label: "健康检查", icon: HeartPulse },
    { key: "crystallize", label: "结晶化", icon: Sparkles },
  ];

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-2 border-b border-slate-200">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.key} type="button" onClick={() => setTab(item.key)} className={cn("inline-flex h-10 items-center gap-2 border-b-2 px-3 text-sm font-semibold", tab === item.key ? "border-amber-500 text-amber-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </div>
      {tab === "pages" ? <WikiPagePanel kbId={kb.kb_id} pages={pages} selectedPage={selectedPage} loading={loading} onSelect={setSelectedPage} onReload={loadWiki} /> : null}
      {tab === "graph" ? <WikiGraphPanel kbId={kb.kb_id} graph={graph} onReload={loadWiki} /> : null}
      {tab === "lint" ? <WikiLintPanel kbId={kb.kb_id} lint={lint} onReload={loadWiki} /> : null}
      {tab === "crystallize" ? <WikiCrystallizePanel kbId={kb.kb_id} files={files} onCreated={async () => { await reload(); await loadWiki(); }} /> : null}
    </section>
  );
}
```

- [ ] **Step 2: Create minimal page panel**

Create `frontend/src/components/wiki/WikiPagePanel.tsx`:

```tsx
"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2, Save } from "lucide-react";
import { fetchWikiKbPage, updateWikiKbPage, type WikiPageDetail, type WikiPageSummary } from "@/lib/api";

export function WikiPagePanel({ kbId, pages, selectedPage, loading, onSelect, onReload }: { kbId: string; pages: WikiPageSummary[]; selectedPage: WikiPageDetail | null; loading: boolean; onSelect: (page: WikiPageDetail) => void; onReload: () => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const select = async (pageId: string) => {
    const page = await fetchWikiKbPage(kbId, pageId);
    onSelect(page);
    setDraft(page.content);
    setEditing(false);
  };

  const save = async () => {
    if (!selectedPage) return;
    const page = await updateWikiKbPage(kbId, selectedPage.id, { content: draft });
    onSelect(page);
    setEditing(false);
    await onReload();
  };

  return (
    <div className="grid min-h-[540px] gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-500">共 {pages.length} 页</div>
        <div className="max-h-[520px] overflow-y-auto p-2">
          {pages.map((page) => (
            <button key={page.id} type="button" onClick={() => void select(page.id)} className="mb-1 block w-full rounded-lg px-3 py-2 text-left hover:bg-slate-50">
              <span className="block truncate text-sm font-semibold text-slate-800">{page.title}</span>
              <span className="text-[11px] text-slate-400">{page.type} · {page.confidence}</span>
            </button>
          ))}
        </div>
      </aside>
      <article className="min-w-0 rounded-xl border border-slate-200 bg-white p-5">
        {loading ? <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 size={16} className="animate-spin" />加载 Wiki...</div> : null}
        {selectedPage ? (
          <>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="truncate text-lg font-bold text-slate-950">{selectedPage.title}</h2>
              <div className="flex gap-2">
                <button type="button" onClick={() => { setEditing((value) => !value); setDraft(selectedPage.content); }} className="h-8 rounded-lg border border-slate-200 px-3 text-xs font-semibold">编辑</button>
                {editing ? <button type="button" onClick={() => void save()} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white"><Save size={13} />保存</button> : null}
              </div>
            </div>
            {editing ? <textarea className="h-[440px] w-full resize-none rounded-xl border border-slate-200 p-3 font-mono text-sm outline-none focus:border-amber-300" value={draft} onChange={(event) => setDraft(event.target.value)} /> : <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedPage.content}</ReactMarkdown></div>}
          </>
        ) : <div className="text-sm text-slate-400">选择左侧页面查看内容</div>}
      </article>
    </div>
  );
}
```

- [ ] **Step 3: Create graph, lint, crystallize panels**

Create `WikiGraphPanel.tsx`, `WikiLintPanel.tsx`, and `WikiCrystallizePanel.tsx` as compact panels:

```tsx
// WikiGraphPanel.tsx
"use client";
import ReactFlow, { Background, Controls, MiniMap } from "reactflow";
import "reactflow/dist/style.css";
import type { WikiGraphPayload } from "@/lib/api";

export function WikiGraphPanel({ graph }: { kbId: string; graph: WikiGraphPayload; onReload: () => Promise<void> }) {
  const nodes = graph.nodes.map((node, index) => ({ id: node.id, position: { x: (index % 5) * 180, y: Math.floor(index / 5) * 120 }, data: { label: node.label }, style: { border: "1px solid #e2e8f0", borderRadius: 8, padding: 8 } }));
  const edges = graph.edges.map((edge, index) => ({ id: `${edge.source}-${edge.target}-${index}`, source: edge.source, target: edge.target, animated: Boolean(edge.signals?.wikilink), style: { strokeWidth: Math.max(1, Number(edge.weight || 1) / 2) } }));
  return <div className="h-[560px] overflow-hidden rounded-xl border border-slate-200 bg-white"><ReactFlow nodes={nodes} edges={edges} fitView><MiniMap /><Controls /><Background /></ReactFlow></div>;
}
```

```tsx
// WikiLintPanel.tsx
"use client";
import type { WikiLintPayload } from "@/lib/api";

export function WikiLintPanel({ lint }: { kbId: string; lint: WikiLintPayload; onReload: () => Promise<void> }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 text-sm font-semibold text-slate-900">问题 {lint.summary.issue_count ?? lint.issues.length}</div>
      <div className="space-y-2">
        {lint.issues.map((issue) => (
          <div key={issue.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
            <div className="font-semibold text-slate-800">{issue.message}</div>
            <div className="mt-1 text-xs text-slate-500">{issue.severity} · {issue.type} · {issue.page_id}</div>
          </div>
        ))}
        {!lint.issues.length ? <div className="text-sm text-slate-400">暂无健康检查问题</div> : null}
      </div>
    </div>
  );
}
```

```tsx
// WikiCrystallizePanel.tsx
"use client";
import { useState } from "react";
import type { FileMeta } from "@/lib/api";

export function WikiCrystallizePanel({ kbId, onCreated }: { kbId: string; files: FileMeta[]; onCreated: () => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const create = async () => {
    setError("");
    const res = await fetch(`/api/knowledge/${kbId}/wiki/crystallize`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, content, type: "note", confidence: "UNVERIFIED", sources: [] }) });
    if (!res.ok) {
      setError(await res.text());
      return;
    }
    setTitle("");
    setContent("");
    await onCreated();
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <input value={title} onChange={(event) => setTitle(event.target.value)} className="mb-3 h-10 w-full rounded-lg border border-slate-200 px-3 text-sm outline-none" placeholder="页面标题" />
      <textarea value={content} onChange={(event) => setContent(event.target.value)} className="h-72 w-full resize-none rounded-lg border border-slate-200 p-3 font-mono text-sm outline-none" placeholder="Markdown 内容" />
      {error ? <div className="mt-2 text-xs text-rose-600">{error}</div> : null}
      <button type="button" onClick={() => void create()} className="mt-3 h-9 rounded-lg bg-slate-950 px-4 text-sm font-semibold text-white">生成 Wiki 页面</button>
    </div>
  );
}
```

- [ ] **Step 4: Branch detail page**

In `frontend/src/app/knowledge/[id]/page.tsx`, import:

```ts
import { WikiWorkbench } from "@/components/wiki/WikiWorkbench";
```

Before rendering normal detail panels, add:

```tsx
if (kb.kb_type === "wiki") {
  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        ...
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <FileUploadCard uploading={uploading} inputRef={fileInputRef} onUpload={handleUpload} />
        <UploadResultList results={uploadResults} />
        <FileList files={files} processingIds={processingIds} onProcess={handleProcess} onPreview={handlePreview} onDelete={handleDelete} />
        <WikiWorkbench kb={kb} files={files} reload={loadData} />
      </main>
    </div>
  );
}
```

Use the existing header JSX and existing upload/list components already defined in the file.

- [ ] **Step 5: Update chat modal**

In `frontend/src/components/chat/WikiModal.tsx`:

```ts
const wikiKbs = kbs.filter((kb) => kb.kb_type === "wiki");
```

Replace `kbs.map` with `wikiKbs.map`.

Change the empty option label:

```tsx
<option value="">选择 Wiki 知识库</option>
```

Before calling `crystallizeWiki`, reject missing target:

```ts
if (!kbId) {
  setError("请选择一个 Wiki 知识库");
  return;
}
```

- [ ] **Step 6: Run frontend lint**

Run:

```bash
cd frontend && npm run lint
```

Expected: PASS or only pre-existing unrelated lint failures. Fix new import/type errors.

- [ ] **Step 7: Commit**

Run:

```bash
git add frontend/src/components/wiki frontend/src/app/knowledge/[id]/page.tsx frontend/src/app/knowledge/[id]/wiki/graph/page.tsx frontend/src/components/chat/WikiModal.tsx
git commit -m "feat: add wiki knowledge workbench"
```

### Task 9: Full Verification and Finish

**Files:**
- Verify only.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_wiki_kb.py tests/unit/test_wiki_routes.py tests/unit/test_wiki_service.py tests/unit/test_knowledge_agent_tool.py -q
```

Expected: PASS.

- [ ] **Step 2: Run shared backend tests**

Run:

```bash
cd backend && uv run pytest tests/unit/test_knowledge_upload_lifecycle.py tests/unit/test_knowledge_search_modes.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend lint**

Run:

```bash
cd frontend && npm run lint
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short
```

Expected: only the pre-existing uncommitted `docker-compose.yml` change remains, unless the user has made other unrelated changes.

- [ ] **Step 5: Summarize completion**

Report:

- Wiki KB type added.
- Wiki backend compiles/searches pages.
- Wiki API routes added.
- Chat crystallization targets Wiki KBs.
- Frontend create flow and workbench added.
- Verification commands and outcomes.
- Note that `docker-compose.yml` was intentionally not touched.
