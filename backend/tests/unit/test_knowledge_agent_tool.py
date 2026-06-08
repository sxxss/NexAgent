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
