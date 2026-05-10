from __future__ import annotations

import pytest


@pytest.mark.unit
async def test_hybrid_retriever_dedupes_and_reranks(monkeypatch):
    from nexagent.knowledge.models import SearchResult
    from nexagent.knowledge.retriever import HybridRetriever

    class FakeManager:
        async def search(self, kb_id, query, top_k=5, **kwargs):
            return [
                SearchResult(content="alpha beta exact topic", score=0.4, source="a.md", file_id="a"),
                SearchResult(content="alpha beta exact topic", score=0.2, source="a.md", file_id="a"),
                SearchResult(content="unrelated", score=0.9, source="b.md", file_id="b"),
            ]

    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())

    results = await HybridRetriever().retrieve("alpha beta", ["kb-1"], top_k=2)

    assert len(results) == 2
    assert results[0].content == "alpha beta exact topic"
    assert results[0].metadata["rerank"]["lexical_overlap"] == 1.0


@pytest.mark.unit
async def test_knowledge_evaluator_reports_ndcg(monkeypatch):
    from nexagent.knowledge.evaluator import KnowledgeBaseEvaluator, QATestCase
    from nexagent.knowledge.retriever import RetrievedChunk

    class FakeRetriever:
        async def retrieve(self, query, kb_ids, mode="hybrid", top_k=10):
            return [
                RetrievedChunk(content="miss", score=0.9, kb_id=kb_ids[0]),
                RetrievedChunk(content="expected answer", score=0.8, kb_id=kb_ids[0]),
            ]

    report = await KnowledgeBaseEvaluator(FakeRetriever()).evaluate(
        "kb-1",
        [QATestCase(question="q", expected="expected answer")],
    )

    assert report.recall == 1.0
    assert report.mrr == 0.5
    assert 0.0 < report.ndcg < 1.0
