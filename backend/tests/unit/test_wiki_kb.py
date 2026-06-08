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
        assert (work_dir / "wiki" / kb.kb_id / "purpose.md").read_text(
            encoding="utf-8"
        ).startswith("# LLM Wiki")
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


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
