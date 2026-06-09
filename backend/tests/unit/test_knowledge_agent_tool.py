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
