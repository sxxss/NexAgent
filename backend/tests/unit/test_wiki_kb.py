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

        kb = await manager.create_kb(name="Wiki 知识库", description="Project memory", kb_type="wiki")
        loaded = manager.get_kb(kb.kb_id)
        all_kbs = manager.list_kbs()

        assert kb.kb_type == KBType.WIKI
        assert loaded is not None
        assert loaded.kb_id == kb.kb_id
        assert any(item.kb_id == kb.kb_id for item in all_kbs)
        assert (work_dir / "wiki" / kb.kb_id / "wiki" / "sources").exists()
        assert (work_dir / "wiki" / kb.kb_id / "purpose.md").read_text(
            encoding="utf-8"
        ).startswith("# Wiki 知识库")
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
async def test_wiki_manual_page_creation_defaults_to_note_and_manual_edit():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("manual-page")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Useful knowledge", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        page = await backend.create_wiki_page(
            kb_meta.kb_id,
            title="新概念",
            content="# 新概念\n\n从页面链接直接创建。",
        )

        assert page["id"] == "note:新概念"
        assert page["type"] == "note"
        assert page["title"] == "新概念"
        assert page["confidence"] == "UNVERIFIED"
        assert page["manual_edited"] is True
        assert page["status"] == "manual_edited"
        assert page["content"] == "# 新概念\n\n从页面链接直接创建。"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deleting_manual_wiki_page_does_not_require_recompile():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("delete-manual-page")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Useful knowledge", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        page = await backend.create_wiki_page(
            kb_meta.kb_id,
            title="临时手工页",
            content="# 临时手工页\n\n无需源文档重编译。",
        )

        await backend.delete_wiki_page(kb_meta.kb_id, page["id"])
        lint = backend.lint_wiki(kb_meta.kb_id)

        assert all(issue["type"] != "wiki_stale_after_delete" for issue in lint["issues"])
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
async def test_wiki_compile_clears_stale_reindex_flag(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-clear-reindex")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Project memory", kb_type="wiki")
        file_meta = await manager.add_file(kb_meta.kb_id, "plan.md", b"# Plan\n\nUse Wiki pages.")
        await manager.parse_file(kb_meta.kb_id, file_meta.file_id)
        backend = manager._find_backend(kb_meta.kb_id)
        kb_meta.extra["requires_reindex"] = True
        kb_meta.extra["model_config"] = {"requires_reindex": True}

        async def fake_compile(kb_id, file_id, meta, markdown):
            return [
                await backend.create_or_update_wiki_page(
                    kb_id,
                    page_type="source",
                    title="Plan",
                    content="# Plan\n\n## Summary\n\nUse Wiki pages.",
                    sources=[file_id],
                    confidence="EXTRACTED",
                )
            ]

        monkeypatch.setattr(backend, "_compile_markdown_file", fake_compile)

        result = await backend.compile_wiki(kb_meta.kb_id)

        assert result["failed"] == 0
        assert kb_meta.extra["requires_reindex"] is False
        assert kb_meta.extra["model_config"]["requires_reindex"] is False
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_llm_compile_invocation_has_no_fixed_timeout(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    class SlowLLM:
        async def ainvoke(self, messages):
            await asyncio.sleep(0.02)
            return SimpleNamespace(content="ok")

    work_dir = _work_dir("compile-no-fixed-timeout")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setenv("NEXAGENT_WIKI_LLM_TIMEOUT_S", "0.001")

        response = await backend._invoke_wiki_llm(SlowLLM(), [])

        assert response.content == "ok"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_user_facing_text_uses_wiki_knowledge_base_name():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-copy")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        prompt = backend._build_compile_prompt("alpha.md", "", "# Alpha")
        messages = [item["content"] for item in prompt]
        with pytest.raises(ValueError) as parse_error:
            backend._parse_llm_json("[]")
        with pytest.raises(ValueError) as missing_source:
            backend._validate_compiled_payload({"topics": [], "entities": []})
        with pytest.raises(ValueError) as missing_title:
            backend._validate_compiled_payload({"source": {"title": ""}, "topics": [], "entities": []})
        with pytest.raises(ValueError) as bad_topics:
            backend._validate_compiled_payload({"source": {"title": "Alpha"}, "topics": {}, "entities": []})

        user_facing_text = "\n".join(
            [
                *messages,
                str(parse_error.value),
                str(missing_source.value),
                str(missing_title.value),
                str(bad_topics.value),
            ]
        )
        assert "Wiki 知识库" in user_facing_text
        assert "LLM Wiki" not in user_facing_text
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
async def test_wiki_compile_prompt_includes_detected_headings_and_entities(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    captured = {}

    class FakeResponse:
        content = '{"source": {"title": "Alpha"}, "topics": [], "entities": []}'

    class FakeLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return FakeResponse()

    async def fake_load_chat_model_async(model_name=None, **kwargs):
        return FakeLLM()

    work_dir = _work_dir("compile-prompt-context")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_load_chat_model_async)

        await backend._compile_markdown_with_llm(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="alpha.md"),
            "# 医保电子凭证使用与维护\n\n本文介绍医保电子凭证常见问题处理。",
        )

        user_prompt = captured["messages"][1].content
        assert "Detected headings" in user_prompt
        assert "医保电子凭证使用与维护" in user_prompt
        assert "Detected entity candidates" in user_prompt
        assert "医保电子凭证" in user_prompt
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_page_content_normalizes_generated_wikilinks():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-link-normalize")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        content = backend._page_content_from_llm(
            "医保电子凭证概述",
            "关联 [[医保电子凭证使用与维护]]。",
            "处理流程见 [[医保电子凭证使用与维护]] 和 [[未知页面]]。",
            "医保中心问答",
            known_titles=["医保中心问答", "医保电子凭证使用与维护"],
        )

        assert "[[医保电子凭证使用与维护]]" in content
        assert "[[未知页面]]" in content
        assert "- [[医保中心问答]]" in content
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_page_content_normalizes_source_filename_aliases():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-source-alias")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)

        source_title = "2025-2026学年暑期留宿知情同意书"
        aliases = backend._source_title_aliases("导师知情同意书(2).docx", source_title)
        content = backend._page_content_from_llm(
            "暑期留宿申请",
            "申请材料见 [[导师知情同意书]]。",
            "学生需填写 [[导师知情同意书]] 并由导师确认。",
            source_title,
            known_titles=[source_title, "暑期留宿申请"],
            known_title_aliases=aliases,
        )

        assert "[[2025-2026学年暑期留宿知情同意书]]" in content
        assert "[[导师知情同意书]]" not in content
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_creates_fallback_entities_for_linked_source_terms(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        return {
            "source": {
                "title": "NexAgent 开源产品开发计划",
                "summary": "NexAgent 开源计划",
                "key_points": [],
                "confidence": "EXTRACTED",
            },
            "topics": [
                {
                    "title": "MVP",
                    "summary": "最小可行产品",
                    "content": "[[NexAgent]] 的核心功能采用 MVP 策略。",
                    "confidence": "INFERRED",
                }
            ],
            "entities": [],
        }

    work_dir = _work_dir("compile-fallback-entity")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="NexAgent 开源产品开发计划.md"),
            "# NexAgent 开源产品开发计划\n\nNexAgent 是开源 Agent 平台。",
        )

        entity = backend.get_wiki_page(kb_meta.kb_id, "entity:nexagent")
        lint = backend.lint_wiki(kb_meta.kb_id)

        assert entity["title"] == "NexAgent"
        assert "[[NexAgent 开源产品开发计划]]" in entity["content"]
        assert not any(issue.get("target") == "NexAgent" for issue in lint["issues"])
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_records_failure_when_llm_times_out(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        raise TimeoutError("provider timed out")

    work_dir = _work_dir("compile-timeout-failure")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", description="Project memory", kb_type="wiki")
        file_meta = await manager.add_file(
            kb_meta.kb_id,
            "NexAgent 开源产品开发计划.md",
            "# NexAgent 开源产品开发计划\n\n## MVP\n\nNexAgent 采用 MVP 策略。".encode(),
        )
        await manager.parse_file(kb_meta.kb_id, file_meta.file_id)
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        result = await backend.compile_wiki(kb_meta.kb_id, force=True)
        pages = backend.list_wiki_pages(kb_meta.kb_id)["pages"]

        assert result["processed"] == 0
        assert result["failed"] == 1
        assert result["items"] == [
            {"file_id": file_meta.file_id, "status": "error", "error": "provider timed out"}
        ]
        assert pages == []
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_creates_placeholder_pages_for_unresolved_llm_links(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        return {
            "source": {"title": "暑期留宿知情同意书", "summary": "导师管理职责", "key_points": []},
            "topics": [
                {
                    "title": "暑期留宿管理规定",
                    "summary": "管理流程",
                    "content": "相关责任见 [[导师职责]]。",
                    "confidence": "INFERRED",
                }
            ],
            "entities": [],
        }

    work_dir = _work_dir("compile-link-placeholder")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="导师知情同意书(2).docx"),
            "学生暑期留宿，导师负责管理。",
        )

        placeholder = backend.get_wiki_page(kb_meta.kb_id, "entity:导师职责")
        lint = backend.lint_wiki(kb_meta.kb_id)

        assert placeholder["title"] == "导师职责"
        assert placeholder["confidence"] == "UNVERIFIED"
        assert "自动补全" in placeholder["content"]
        assert not any(issue.get("target") == "导师职责" for issue in lint["issues"])
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_removes_stale_generated_pages_for_same_file(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    calls = 0

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "source": {"title": "Project Plan", "summary": "Old run", "key_points": []},
                "topics": [{"title": "Old Topic", "summary": "Old", "content": "Old content"}],
                "entities": [],
            }
        return {
            "source": {"title": "Project Plan", "summary": "New run", "key_points": []},
            "topics": [{"title": "New Topic", "summary": "New", "content": "New content"}],
            "entities": [],
        }

    work_dir = _work_dir("compile-stale-pages")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="project.md"),
            "# Project Plan",
        )
        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="project.md"),
            "# Project Plan",
        )

        pages = backend.list_wiki_pages(kb_meta.kb_id)["pages"]
        page_ids = {page["id"] for page in pages}

        assert "topic:new-topic" in page_ids
        assert "topic:old-topic" not in page_ids
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_source_suggested_links_only_include_generated_pages(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        return {
            "source": {
                "title": "NexAgent 开源产品开发计划",
                "summary": "开源产品开发计划",
                "key_points": [],
            },
            "topics": [
                {
                    "title": "关键要点",
                    "summary": "任务拆解和优先级",
                    "content": "核心工作涉及 [[MVP]]。",
                }
            ],
            "entities": [
                {
                    "title": "MVP",
                    "summary": "最小可行产品",
                    "content": "MVP 与项目路线图相关。",
                }
            ],
        }

    work_dir = _work_dir("compile-source-links")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="NexAgent 开源产品开发计划.md"),
            "\n".join(
                [
                    "# NexAgent 开源产品开发计划",
                    "",
                    "## 摘要",
                    "本文档提供开发计划。",
                    "",
                    "## 关键要点",
                    "### 1. 基础设施搭建 (P0)",
                    "- 搭建 Github 组织账号",
                    "MVP 是核心策略。",
                ]
            ),
        )

        source = backend.get_wiki_page(kb_meta.kb_id, "source:nexagent-开源产品开发计划")
        lint = backend.lint_wiki(kb_meta.kb_id)

        assert "[[关键要点]]" in source["content"]
        assert "[[MVP]]" in source["content"]
        assert "[[摘要]]" not in source["content"]
        assert "[[1. 基础设施搭建 (P0)]]" not in source["content"]
        assert not any(issue["type"] == "broken_link" for issue in lint["issues"])
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_compile_removes_uncached_stale_generated_pages_for_same_file(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    async def fake_compile(_kb_id, _file_id, _file_meta, _markdown):
        return {
            "source": {"title": "Project Plan", "summary": "New run", "key_points": []},
            "topics": [{"title": "New Topic", "summary": "New", "content": "New content"}],
            "entities": [],
        }

    work_dir = _work_dir("compile-uncached-stale-pages")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Old Topic",
            content="# Old Topic\n\nOld generated content.",
            sources=["file-1"],
            confidence="INFERRED",
        )
        monkeypatch.setattr(backend, "_compile_markdown_with_llm", fake_compile)

        await backend._compile_markdown_file(
            kb_meta.kb_id,
            "file-1",
            SimpleNamespace(filename="project.md"),
            "# Project Plan",
        )

        pages = backend.list_wiki_pages(kb_meta.kb_id)["pages"]
        page_ids = {page["id"] for page in pages}

        assert "topic:new-topic" in page_ids
        assert "topic:old-topic" not in page_ids
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_refresh_corpus_synthesis_creates_summary_page():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("compile-synthesis")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="source",
            title="医保中心问答",
            content="# 医保中心问答",
            sources=["file-1"],
            confidence="EXTRACTED",
        )
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="医保电子凭证使用与维护",
            content="# 医保电子凭证使用与维护",
            sources=["file-1"],
            confidence="INFERRED",
        )

        synthesis = await backend._refresh_corpus_synthesis(kb_meta.kb_id)
        detail = backend.get_wiki_page(kb_meta.kb_id, "synthesis:wiki-synthesis")

        assert synthesis["id"] == "synthesis:wiki-synthesis"
        assert "当前 Wiki 包含 1 个来源页、1 个主题页、0 个实体页" in detail["content"]
        assert "[[医保中心问答]]" in detail["content"]
        assert "[[医保电子凭证使用与维护]]" in detail["content"]
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_ai_repair_uses_llm_and_creates_candidate(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    calls = []

    class FakeResponse:
        content = """
        {
          "repairs": [
            {
              "page_id": "topic:alpha",
              "content": "# Alpha\\n\\nAI repaired content with [[Beta]].",
              "confidence": "UNVERIFIED",
              "reason": "补全断链和复核内容"
            }
          ]
        }
        """

    class FakeLLM:
        async def ainvoke(self, messages):
            calls.append(messages)
            return FakeResponse()

    async def fake_load_chat_model_async(model_name=None, **kwargs):
        calls.append((model_name, kwargs))
        return FakeLLM()

    work_dir = _work_dir("ai-repair")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Alpha",
            content="# Alpha\n\nBroken link [[Missing]].",
            sources=[],
            confidence="UNVERIFIED",
        )
        monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_load_chat_model_async)

        result = await backend.repair_wiki(kb_meta.kb_id, issue_types=["needs_review"])
        detail = backend.get_wiki_page(kb_meta.kb_id, "topic:alpha")

        assert calls[0][1]["streaming"] is False
        assert result["candidate_count"] == 1
        assert result["repaired_count"] == 1
        assert detail["content"] == "# Alpha\n\nBroken link [[Missing]]."
        assert detail["candidate"]["content"] == "# Alpha\n\nAI repaired content with Beta."
        assert detail["candidate"]["reason"] == "补全断链和复核内容"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_ai_repair_can_apply_candidate_directly(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    class FakeResponse:
        content = """
        {
          "repairs": [
            {
              "page_id": "topic:alpha",
              "content": "# Alpha\\n\\nAI repaired content with [[Beta]].",
              "confidence": "UNVERIFIED",
              "reason": "补全断链和复核内容"
            }
          ]
        }
        """

    class FakeLLM:
        async def ainvoke(self, _messages):
            return FakeResponse()

    async def fake_load_chat_model_async(model_name=None, **kwargs):
        return FakeLLM()

    work_dir = _work_dir("ai-repair-apply")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        await backend.create_or_update_wiki_page(
            kb_meta.kb_id,
            page_type="topic",
            title="Alpha",
            content="# Alpha\n\nBroken link [[Missing]].",
            sources=[],
            confidence="UNVERIFIED",
        )
        monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_load_chat_model_async)

        result = await backend.repair_wiki(kb_meta.kb_id, issue_types=["needs_review"], apply=True)
        detail = backend.get_wiki_page(kb_meta.kb_id, "topic:alpha")

        assert result["candidate_count"] == 0
        assert result["applied_count"] == 1
        assert result["repaired_count"] == 1
        assert detail["content"] == "# Alpha\n\nAI repaired content with Beta."
        assert detail["confidence"] == "INFERRED"
        assert detail["candidate"] is None
        assert not any(issue.get("type") == "broken_link" for issue in backend.lint_wiki(kb_meta.kb_id)["issues"])
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_graph_core_mode_caps_weak_inferred_degree():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("graph-core")
    try:
        manager = reset_manager(str(work_dir))
        kb_meta = await manager.create_kb(name="Wiki", kb_type="wiki")
        backend = manager._find_backend(kb_meta.kb_id)
        for index in range(6):
            await backend.create_or_update_wiki_page(
                kb_meta.kb_id,
                page_type="topic",
                title=f"Topic {index}",
                content=f"# Topic {index}\n\n同一来源的弱关系页面。",
                sources=["shared-source"],
                confidence="INFERRED",
            )

        graph = backend.get_wiki_graph(kb_meta.kb_id, max_edges=15, include_weak=False)
        weak_graph = backend.get_wiki_graph(kb_meta.kb_id, max_edges=15, include_weak=True)

        degrees: dict[str, int] = {}
        for edge in graph["edges"]:
            degrees[edge["source"]] = degrees.get(edge["source"], 0) + 1
            degrees[edge["target"]] = degrees.get(edge["target"], 0) + 1

        assert weak_graph["stats"]["raw_edge_count"] == 15
        assert graph["stats"]["raw_edge_count"] == 15
        assert graph["stats"]["display_edge_count"] == len(graph["edges"])
        assert len(graph["edges"]) < len(weak_graph["edges"])
        assert max(degrees.values()) <= 3
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
