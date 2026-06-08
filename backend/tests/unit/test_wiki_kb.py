from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_llm_compile_invocation_times_out(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    class SlowLLM:
        async def ainvoke(self, messages):
            await asyncio.sleep(1)

    work_dir = _work_dir("compile-timeout")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setenv("NEXAGENT_WIKI_LLM_TIMEOUT_S", "0.01")

        with pytest.raises(TimeoutError, match="LLM Wiki compile timed out after"):
            await backend._invoke_wiki_llm(SlowLLM(), [])
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_llm_json_parser_accepts_wrapped_json():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-json")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        parsed = backend._parse_llm_json(
            """
            下面是结果：
            {"source": {"title": "Alpha"}, "topics": [], "entities": []}
            已完成。
            """
        )

        assert parsed["source"]["title"] == "Alpha"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_normalizes_missing_source_payload():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-normalize")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        normalized = backend._normalize_compiled_payload(
            {
                "title": "Alpha",
                "summary": "Alpha summary",
                "pages": [{"title": "Topic A", "summary": "Topic summary", "content": "Topic body"}],
            },
            SimpleNamespace(filename="alpha.md"),
            "# Alpha",
        )

        assert normalized["source"]["title"] == "Alpha"
        assert normalized["source"]["summary"] == "Alpha summary"
        assert normalized["topics"][0]["title"] == "Topic A"
        assert normalized["entities"] == []
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_loads_llm_without_streaming(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    calls = []

    class FakeResponse:
        content = '{"source": {"title": "Alpha"}, "topics": [], "entities": []}'

    class FakeLLM:
        async def ainvoke(self, messages):
            return FakeResponse()

    async def fake_load_chat_model_async(model_name=None, **kwargs):
        calls.append((model_name, kwargs))
        return FakeLLM()

    work_dir = _work_dir("compile-non-streaming")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_load_chat_model_async)

        parsed = await backend._compile_markdown_with_llm(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="alpha.md"),
            "# Alpha",
        )

        assert parsed["source"]["title"] == "Alpha"
        assert calls[0][1]["streaming"] is False
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


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
