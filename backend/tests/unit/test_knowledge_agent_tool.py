from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_knowledge_search_tool_uses_structured_retrieve(monkeypatch):
    from nexagent.knowledge.retriever import RetrievedChunk
    from nexagent.knowledge.search_service import SearchWarning, StructuredSearchResult
    from nexagent.tools.builtin.knowledge_search import get_knowledge_search_tool

    class FakeManager:
        def list_kbs(self):
            return []

    async def fake_structured_retrieve(**kwargs):
        assert kwargs["kb_ids"] == ["kb-1"]
        assert kwargs["mode"] == "keyword"
        return StructuredSearchResult(
            chunks=[
                RetrievedChunk(
                    content="Alpha retrieval evidence.",
                    score=0.91,
                    kb_id="kb-1",
                    source="guide.md",
                    file_id="file-1",
                    metadata={"chunk_id": "file-1_chunk_0", "chunk_index": 0},
                )
            ],
            warnings=[SearchWarning(code="native_bm25_unavailable", message="Used local shadow index.")],
            degraded=True,
        )

    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())
    monkeypatch.setattr("nexagent.knowledge.search_service.structured_retrieve", fake_structured_retrieve)

    tool = get_knowledge_search_tool(["kb-1"])
    output = await tool.ainvoke({"query": "alpha", "top_k": 1, "mode": "keyword"})

    assert "Alpha retrieval evidence." in output
    assert "chunk_id=file-1_chunk_0" in output
    assert "native_bm25_unavailable" in output
    assert "```nexagent-evidence" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_knowledge_search_tool_rejects_invalid_mode():
    from nexagent.tools.builtin.knowledge_search import get_knowledge_search_tool

    tool = get_knowledge_search_tool(["kb-1"])
    output = await tool.ainvoke({"query": "alpha", "top_k": 1, "mode": "graph"})

    assert "unsupported mode" in output


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


class _FakeWikiBackend:
    def __init__(self):
        from nexagent.knowledge.models import KBMeta, KBType

        self.kb = KBMeta(kb_id="wiki-1", name="产品 Wiki", kb_type=KBType.WIKI)
        self.calls: list[tuple] = []

    def get_kb(self, kb_id):
        return self.kb if kb_id == "wiki-1" else None

    def list_wiki_pages(self, kb_id, page_type=None, q=None, status=None, source_file_id=None):
        self.calls.append(("list", kb_id, page_type, q, status, source_file_id))
        return {
            "pages": [
                {
                    "id": "topic:alpha",
                    "title": "Alpha",
                    "type": "topic",
                    "path": "wiki/topics/alpha.md",
                    "status": "generated",
                    "has_candidate": False,
                    "frontmatter": {"confidence": "INFERRED"},
                },
                {
                    "id": "entity:beta",
                    "title": "Beta",
                    "type": "entity",
                    "path": "wiki/entities/beta.md",
                    "status": "manual_edited",
                    "has_candidate": True,
                    "frontmatter": {"confidence": "EXTRACTED"},
                },
            ]
        }

    def get_wiki_page(self, kb_id, page_id):
        self.calls.append(("read", kb_id, page_id))
        return {
            "id": page_id,
            "title": "Alpha",
            "type": "topic",
            "path": "wiki/topics/alpha.md",
            "content": "Alpha page body with [[Beta]].",
            "candidate": {"content": "candidate body"},
            "frontmatter": {
                "confidence": "INFERRED",
                "sources": ["file-1"],
                "updated_at": "2026-06-09T01:00:00Z",
            },
        }

    def lint_wiki(self, kb_id):
        self.calls.append(("lint", kb_id))
        return {
            "summary": {"issue_count": 2, "page_count": 3},
            "issues": [
                {
                    "type": "broken_link",
                    "severity": "error",
                    "page_id": "topic:alpha",
                    "message": "页面包含断开的 wikilink",
                    "action": "review",
                    "repairable": True,
                    "repair_action": "ai_candidate",
                    "target": "Missing",
                },
                {
                    "type": "pending_candidate",
                    "severity": "warning",
                    "page_id": "entity:beta",
                    "message": "存在待处理的系统候选版本",
                    "action": "accept_candidate",
                    "repairable": True,
                    "repair_action": "handle_candidate",
                },
            ],
            "compile_status": {"status": "completed"},
        }

    def get_wiki_graph(self, kb_id, *, max_edges=80, include_weak=False, q=None):
        self.calls.append(("graph", kb_id, max_edges, include_weak, q))
        return {
            "nodes": [
                {"id": "topic:alpha", "label": "Alpha", "type": "topic", "community": 1},
                {"id": "entity:beta", "label": "Beta", "type": "entity", "community": 1},
            ],
            "edges": [
                {
                    "source": "topic:alpha",
                    "target": "entity:beta",
                    "weight": 4.0,
                    "signals": {"wikilink": True, "source_overlap": ["file-1"], "common_neighbors": []},
                }
            ],
            "stats": {"total_nodes": 2, "total_edges": 1, "raw_edge_count": 1, "communities": 1},
        }

    async def compile_wiki(self, kb_id, *, file_ids=None, force=False, retry_failed=False):
        self.calls.append(("compile", kb_id, file_ids, force, retry_failed))
        return {"processed": 1, "failed": 0, "items": [{"file_id": "file-1", "status": "indexed"}]}

    async def add_file(self, kb_id, filename, content, processing_params=None):
        self.calls.append(("add_file", kb_id, filename, content, processing_params or {}))
        count = len([call for call in self.calls if call[0] == "add_file"])
        return type("File", (), {"file_id": f"file-{count}"})()

    async def parse_file(self, kb_id, file_id):
        self.calls.append(("parse_file", kb_id, file_id))

    async def index_file(self, kb_id, file_id):
        self.calls.append(("index_file", kb_id, file_id))

    async def crystallize_wiki_text(
        self,
        kb_id,
        title,
        content,
        page_type="note",
        sources=None,
        confidence="UNVERIFIED",
    ):
        self.calls.append(("crystallize", kb_id, title, content, page_type, sources, confidence))
        return {
            "id": "note:alpha-note",
            "title": title,
            "type": page_type,
            "content": content,
            "frontmatter": {"confidence": confidence, "sources": sources or []},
        }

    async def accept_generated_wiki_page(self, kb_id, page_id):
        self.calls.append(("accept", kb_id, page_id))
        return {"id": page_id, "title": "Alpha", "candidate": None}

    async def discard_generated_wiki_page(self, kb_id, page_id):
        self.calls.append(("discard", kb_id, page_id))
        return {"id": page_id, "title": "Alpha", "candidate": None}


class _FakeWikiManager:
    def __init__(self, backend):
        self.backend = backend

    def _find_backend(self, kb_id, raise_on_missing=True):
        if kb_id == "wiki-1":
            return self.backend
        if raise_on_missing:
            raise ValueError(f"Knowledge base not found: {kb_id}")
        return None

    def get_kb(self, kb_id):
        backend = self._find_backend(kb_id, raise_on_missing=False)
        return backend.get_kb(kb_id) if backend else None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_wiki_pages_tool_scopes_and_formats_pages(monkeypatch):
    from nexagent.tools.builtin.wiki import get_list_wiki_pages_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_list_wiki_pages_tool(["wiki-1"])
    output = await tool.ainvoke({"kb_id": "wiki-1", "type": "topic", "status": "generated", "q": "alpha"})

    assert backend.calls == [("list", "wiki-1", "topic", "alpha", "generated", None)]
    assert "产品 Wiki" in output
    assert "topic:alpha" in output
    assert "Alpha" in output
    assert "INFERRED" in output


@pytest.mark.unit
def test_wiki_tool_descriptions_use_wiki_knowledge_base_name():
    from nexagent.tools import registry
    from nexagent.tools.builtin import wiki

    user_facing_text = "\n".join(
        [
            *(
                spec.description
                for spec in registry._BUILTIN_SPECS.values()
                if spec.module == "nexagent.tools.builtin.wiki"
            ),
            wiki.__doc__ or "",
            wiki.get_list_wiki_pages_tool().__doc__ or "",
            wiki.get_read_wiki_page_tool().__doc__ or "",
            wiki.get_wiki_lint_tool().__doc__ or "",
            wiki.get_wiki_graph_tool().__doc__ or "",
            wiki.get_compile_wiki_tool().__doc__ or "",
        ]
    )

    assert "Wiki knowledge base" in user_facing_text
    assert "LLM Wiki" not in user_facing_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_wiki_page_tool_includes_content_metadata_and_candidate(monkeypatch):
    from nexagent.tools.builtin.wiki import get_read_wiki_page_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_read_wiki_page_tool(["wiki-1"])
    output = await tool.ainvoke({"kb_id": "wiki-1", "page_id": "topic:alpha"})

    assert "# Alpha" in output
    assert "topic:alpha" in output
    assert "Alpha page body with [[Beta]]." in output
    assert "候选版本：有" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_lint_tool_formats_repairable_issues(monkeypatch):
    from nexagent.tools.builtin.wiki import get_wiki_lint_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_wiki_lint_tool(["wiki-1"])
    output = await tool.ainvoke({"kb_id": "wiki-1"})

    assert "问题：2" in output
    assert "页面：3" in output
    assert "broken_link" in output
    assert "repair=ai_candidate" in output
    assert "pending_candidate" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_wiki_graph_tool_formats_nodes_and_relationships(monkeypatch):
    from nexagent.tools.builtin.wiki import get_wiki_graph_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_wiki_graph_tool(["wiki-1"])
    output = await tool.ainvoke({"kb_id": "wiki-1", "q": "Alpha", "max_edges": 8})

    assert backend.calls == [("graph", "wiki-1", 8, False, "Alpha")]
    assert "节点：2" in output
    assert "关系：1" in output
    assert "topic:alpha -> entity:beta" in output
    assert "wikilink" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wiki_tools_reject_unscoped_kb(monkeypatch):
    from nexagent.tools.builtin.wiki import get_read_wiki_page_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_read_wiki_page_tool(["wiki-1"])
    output = await tool.ainvoke({"kb_id": "wiki-2", "page_id": "topic:alpha"})

    assert "not available" in output
    assert backend.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compile_wiki_tool_requires_confirmation_then_runs(monkeypatch):
    from nexagent.tools.builtin.wiki import get_compile_wiki_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_compile_wiki_tool(["wiki-1"])
    preview = await tool.ainvoke({"kb_id": "wiki-1", "force": True, "retry_failed": False})

    assert "需要用户确认" in preview
    assert backend.calls == []

    output = await tool.ainvoke(
        {
            "kb_id": "wiki-1",
            "file_ids": ["file-1"],
            "force": True,
            "retry_failed": False,
            "confirmed": True,
        }
    )

    assert backend.calls == [("compile", "wiki-1", ["file-1"], True, False)]
    assert "processed" in output
    assert "file-1" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crystallize_wiki_tool_requires_confirmation_then_creates_page(monkeypatch):
    from nexagent.tools.builtin.wiki import get_crystallize_wiki_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_crystallize_wiki_tool(["wiki-1"])
    preview = await tool.ainvoke(
        {"kb_id": "wiki-1", "title": "Alpha Note", "content": "Some markdown", "page_type": "note"}
    )

    assert "需要用户确认" in preview
    assert backend.calls == []

    output = await tool.ainvoke(
        {
            "kb_id": "wiki-1",
            "title": "Alpha Note",
            "content": "Some markdown",
            "page_type": "note",
            "confidence": "unverified",
            "sources": ["file-1"],
            "confirmed": True,
        }
    )

    assert backend.calls == [
        ("crystallize", "wiki-1", "Alpha Note", "Some markdown", "note", ["file-1"], "UNVERIFIED")
    ]
    assert "已沉淀 Wiki 页面" in output
    assert "note:alpha-note" in output


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crystallize_attachments_to_wiki_requires_confirmation_then_registers_files(monkeypatch, tmp_path):
    from nexagent.tools.builtin.wiki import get_crystallize_attachments_to_wiki_tool

    source = tmp_path / "方案.docx"
    source.write_bytes(b"docx bytes")
    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))
    monkeypatch.setattr(
        "nexagent.tools.builtin.wiki._resolve_thread_file",
        lambda thread_id, path: (source, "/mnt/user-data/uploads/方案.docx"),
    )

    tool = get_crystallize_attachments_to_wiki_tool(["wiki-1"])
    preview = await tool.ainvoke(
        {"kb_id": "wiki-1", "thread_id": "thread-1", "paths": ["/mnt/user-data/uploads/方案.docx"]}
    )

    assert "需要用户确认" in preview
    assert backend.calls == []

    output = await tool.ainvoke(
        {
            "kb_id": "wiki-1",
            "thread_id": "thread-1",
            "paths": ["/mnt/user-data/uploads/方案.docx"],
            "compile_after": True,
            "confirmed": True,
        }
    )

    assert backend.calls[0][0:4] == ("add_file", "wiki-1", "方案.docx", b"docx bytes")
    assert backend.calls[0][4]["source_type"] == "conversation_attachment"
    assert backend.calls[0][4]["source_thread_id"] == "thread-1"
    assert backend.calls[0][4]["source_virtual_path"] == "/mnt/user-data/uploads/方案.docx"
    assert ("parse_file", "wiki-1", "file-1") in backend.calls
    assert ("index_file", "wiki-1", "file-1") in backend.calls
    assert "file-1" in output


@pytest.mark.unit
def test_crystallize_attachments_resolver_only_allows_thread_uploads_and_outputs(monkeypatch, tmp_path):
    from nexagent.sandbox.sandbox import VirtualPathTranslator
    from nexagent.tools.builtin import wiki

    config = type("Config", (), {"sandbox": type("SandboxConfig", (), {"base_dir": str(tmp_path)})()})()
    monkeypatch.setattr("nexagent.config.get_config", lambda: config)
    translator = VirtualPathTranslator(tmp_path)
    translator.ensure_thread_dirs("thread-1")
    upload = translator.to_real("/mnt/user-data/uploads/附件.pdf", "thread-1")
    upload.write_bytes(b"pdf bytes")
    workspace_file = translator.to_real("/mnt/user-data/workspace/private.txt", "thread-1")
    workspace_file.parent.mkdir(parents=True, exist_ok=True)
    workspace_file.write_text("secret", encoding="utf-8")

    real_path, virtual_path = wiki._resolve_thread_file("thread-1", "附件.pdf")

    assert real_path == upload
    assert virtual_path == "/mnt/user-data/uploads/附件.pdf"
    with pytest.raises(ValueError):
        wiki._resolve_thread_file("thread-1", "/mnt/user-data/workspace/private.txt")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_wiki_candidate_tool_requires_confirmation_then_handles_action(monkeypatch):
    from nexagent.tools.builtin.wiki import get_handle_wiki_candidate_tool

    backend = _FakeWikiBackend()
    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: _FakeWikiManager(backend))

    tool = get_handle_wiki_candidate_tool(["wiki-1"])

    invalid = await tool.ainvoke({"kb_id": "wiki-1", "page_id": "topic:alpha", "action": "merge"})
    assert "accept 或 discard" in invalid

    preview = await tool.ainvoke({"kb_id": "wiki-1", "page_id": "topic:alpha", "action": "accept"})
    assert "需要用户确认" in preview
    assert backend.calls == []

    output = await tool.ainvoke(
        {"kb_id": "wiki-1", "page_id": "topic:alpha", "action": "accept", "confirmed": True}
    )

    assert backend.calls == [("accept", "wiki-1", "topic:alpha")]
    assert "topic:alpha" in output
