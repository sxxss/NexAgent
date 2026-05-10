from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.mark.unit
def test_eval_case_create_and_list_keeps_legacy_fields(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    case = eval_service.create_case(
        name="RAG source check",
        type="rag",
        query="Where is the answer?",
        expected_answer="answer",
        expected_sources=["doc-1"],
        kb_ids=["kb-1"],
        tags=["rag"],
    )
    cases = eval_service.list_cases(tag="rag")

    assert cases == [case]
    assert case["expected"] == "answer"
    assert case["expected_answer"] == "answer"
    assert case["type"] == "rag"
    assert case["expected_sources"] == ["doc-1"]
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
def test_eval_case_keeps_retrieval_config_generated_fields_and_task_id(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    case = eval_service.create_case(
        name="hybrid rag check",
        type="rag",
        query="question",
        kb_ids=["kb-1"],
        task_id="task-1",
        retrieval_config={"mode": "keyword", "final_top_k": 6, "similarity_threshold": 0.2},
        generation_source="knowledge",
        generated_by_ai=True,
    )

    assert case["retrieval_config"]["mode"] == "keyword"
    assert case["retrieval_config"]["final_top_k"] == 6
    assert case["retrieval_config"]["similarity_threshold"] == 0.2
    assert case["generated_by_ai"] is True
    assert case["generation_source"] == "knowledge"
    assert case["task_id"] == "task-1"
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
def test_eval_suite_create_list_and_legacy_case_compatibility(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    case = eval_service.create_case(
        name="legacy",
        type="rag",
        query="legacy question",
        expected_answer="legacy answer",
        kb_ids=["kb-1"],
        tags=["rag"],
    )
    suite = eval_service.create_suite(
        name="suite",
        type="rag",
        kb_ids=["kb-1"],
        samples=[
            {
                "query": "question 1",
                "expected_answer": "answer 1",
                "expected_sources": ["doc.md"],
            },
            {
                "query": "question 2",
                "expected_answer": "answer 2",
            },
        ],
        tags=["rag"],
    )

    suites = eval_service.list_suites(tag="rag")

    assert {item["id"] for item in suites} == {case["id"], suite["id"]}
    assert next(item for item in suites if item["id"] == case["id"])["samples"][0]["query"] == "legacy question"
    assert next(item for item in suites if item["id"] == suite["id"])["samples"][1]["expected_answer"] == "answer 2"
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
def test_eval_suite_rejects_mixed_kb_override(monkeypatch):
    from nexagent.knowledge.models import KBMeta, KBType
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    class FakeManager:
        def get_kb(self, kb_id):
            return KBMeta(kb_id=kb_id, name=kb_id, kb_type=KBType.MILVUS if kb_id == "m" else KBType.LIGHTRAG)

    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())

    with pytest.raises(ValueError, match="Mixed Milvus and LightRAG"):
        eval_service.create_suite(
            name="mixed",
            type="rag",
            kb_ids=["m", "l"],
            retrieval_override_enabled=True,
            retrieval_config={"mode": "hybrid"},
            samples=[{"query": "q", "expected_answer": "a"}],
        )
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eval_suite_run_persists_sample_results(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    async def fake_rag_case_full(case, model=None):
        return (
            f"{case['expected_answer']} [doc.md]",
            [{"id": "doc.md", "source": "doc.md"}],
            [{"id": "doc.md", "source": "doc.md"}],
            [],
            "",
            "",
        )

    monkeypatch.setattr(eval_service, "_run_rag_case_full", fake_rag_case_full)

    suite = eval_service.create_suite(
        name="suite",
        type="rag",
        kb_ids=["kb-1"],
        samples=[
            {"id": "s1", "query": "q1", "expected_answer": "a1", "expected_sources": ["doc.md"]},
            {"id": "s2", "query": "q2", "expected_answer": "a2", "expected_sources": ["doc.md"]},
        ],
    )

    result = await eval_service.run_suite(suite["id"])
    stored = eval_service.list_results(suite["id"])

    assert result["total"] == 2
    assert result["passed"] == 2
    assert result["summary"]["metrics"]["recall@1"] == 1.0
    assert result["sample_results"][0]["actual_answer"] == "a1 [doc.md]"
    assert {item["sample_id"] for item in stored} == {"s1", "s2"}
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_eval_cases_returns_editable_drafts_without_persisting(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    result = await eval_service.generate_cases(
        source="manual",
        type="agent",
        count=2,
        topic="release quality",
        agent="chatbot",
        tags=["generated"],
        retrieval_config={"mode": "hybrid", "final_top_k": 5},
    )

    assert result["total"] == 2
    assert len(result["drafts"]) == 2
    assert result["drafts"][0]["generated_by_ai"] is True
    assert result["drafts"][0]["generation_source"] == "manual"
    assert result["drafts"][0]["retrieval_config"]["mode"] == "hybrid"
    assert eval_service.list_cases() == []
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generate_eval_cases_uses_indexed_milvus_chunks(monkeypatch):
    from nexagent.knowledge.models import KBMeta, KBType
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    class FakeManager:
        def list_kbs(self):
            return [KBMeta(kb_id="kb-1", name="kb", kb_type=KBType.MILVUS)]

        def get_kb(self, kb_id):
            return KBMeta(kb_id=kb_id, name="kb", kb_type=KBType.MILVUS)

        def list_indexed_chunks(self, kb_id, limit=1000):
            return [
                {
                    "id": "file-1:0",
                    "content": "NexAgent supports hybrid retrieval.",
                    "filename": "doc.md",
                    "file_id": "file-1",
                    "chunk_index": 0,
                },
                {
                    "id": "file-1:1",
                    "content": "Eval cases can use gold chunk ids.",
                    "filename": "doc.md",
                    "file_id": "file-1",
                    "chunk_index": 1,
                },
            ]

        def list_files(self, kb_id):
            return []

    monkeypatch.setattr("nexagent.knowledge.manager.get_manager", lambda: FakeManager())

    result = await eval_service.generate_cases(
        source="knowledge", type="rag", count=1, kb_ids=["kb-1"], neighbors_count=1
    )

    assert result["total"] == 1
    assert result["diagnostics"][0]["status"] == "ready"
    assert result["diagnostics"][0]["chunks"] >= 1
    assert result["drafts"][0]["expected_sources"]
    assert result["drafts"][0]["expected_sources"][0].startswith("file-1:")
    assert result["drafts"][0]["kb_ids"] == ["kb-1"]
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
def test_eval_scoring_helpers_cover_rag_citation_answer_tool_and_task():
    from nexagent.services.eval_service import (
        score_answer_match,
        score_citation_accuracy,
        score_rag_hit,
        score_task_completion,
        score_tool_success,
    )

    evidence = [{"id": "E1", "source": "docs/guide.md", "file_id": "file-1"}]

    assert score_rag_hit(["guide.md"], evidence) == 1.0
    assert score_citation_accuracy("Use [E1] and [E2].", evidence) == 0.5
    assert score_answer_match("alpha beta", "alpha beta gamma") == 1.0
    assert score_tool_success(["web_search", "fetch"], ["web_search"], error=None) == 0.5
    assert score_task_completion("completed") == 1.0
    assert score_task_completion("failed") == 0.0


@pytest.mark.unit
def test_eval_retrieval_metrics_at_k():
    from nexagent.services.eval_service import retrieval_metrics_at_k

    metrics = retrieval_metrics_at_k(["doc-a", "doc-b", "doc-c"], ["doc-b", "doc-x"])

    assert metrics["recall@1"] == 0.0
    assert metrics["precision@3"] == 0.333
    assert metrics["recall@3"] == 0.5
    assert metrics["f1@3"] == 0.4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rag_suite_can_score_gold_chunk_ids_without_answer_generation(monkeypatch):
    from nexagent.knowledge.retriever import RetrievedChunk
    from nexagent.knowledge.search_service import StructuredSearchResult
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    async def fake_structured_retrieve(**kwargs):
        return StructuredSearchResult(
            chunks=[
                RetrievedChunk(
                    content="Gold evidence.",
                    score=1.0,
                    kb_id="kb-1",
                    source="guide.md",
                    file_id="file-1",
                    metadata={"chunk_id": "file-1_chunk_0", "chunk_index": 0},
                )
            ]
        )

    async def fail_agent_case(*args, **kwargs):
        raise AssertionError("retrieval-only suite should not generate an answer")

    monkeypatch.setattr("nexagent.knowledge.search_service.structured_retrieve", fake_structured_retrieve)
    monkeypatch.setattr(eval_service, "_run_agent_case", fail_agent_case)

    suite = eval_service.create_suite(
        name="retrieval benchmark",
        type="rag",
        kb_ids=["kb-1"],
        samples=[{"id": "s1", "query": "Where is alpha?", "gold_chunk_ids": ["file-1_chunk_0"]}],
    )
    result = await eval_service.run_suite(suite["id"])

    assert result["passed"] == 1
    assert result["sample_results"][0]["metrics"]["recall@1"] == 1.0
    assert result["sample_results"][0]["gold_chunk_ids"] == ["file-1_chunk_0"]
    shutil.rmtree(eval_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rag_case_actual_answer_comes_from_agent(monkeypatch):
    from nexagent.knowledge import retriever
    from nexagent.services import eval_service

    class FakeChunk:
        content = "retrieved snippet should only appear as evidence"
        source = "guide.md"
        file_id = "guide"

        def evidence(self, index):
            return {"id": "guide.md", "source": "guide.md", "file_id": "guide"}

    async def fake_retrieve(self, query, kb_ids, **kwargs):
        return [FakeChunk()]

    async def fake_agent_case(case, model):
        return "agent generated final answer", [], []

    monkeypatch.setattr(retriever.HybridRetriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(eval_service, "_run_agent_case", fake_agent_case)

    answer, evidence, chunks = await eval_service._run_rag_case(
        {"query": "q", "type": "rag", "kb_ids": ["kb-1"], "retrieval_config": {}},
        model="test-model",
    )

    assert answer == "agent generated final answer"
    assert evidence[0]["content"] == "retrieved snippet should only appear as evidence"
    assert chunks[0]["source"] == "guide.md"


@pytest.mark.unit
def test_rule_based_generation_uses_natural_question_templates():
    from nexagent.services import eval_service

    drafts = eval_service._generate_rule_based_drafts(
        contexts=[
            {
                "content": "Hybrid retrieval combines vector and keyword signals for better recall.",
                "chunk_id": "chunk-1",
            }
        ],
        count=3,
        eval_type="rag",
        agent="chatbot",
        model="",
        kb_ids=["kb-1"],
        tags=["generated"],
        source="knowledge",
        retrieval_config={},
    )

    assert len(drafts) == 3
    assert all(not item["query"].startswith("根据资料说明") for item in drafts)
    assert len({item["query"] for item in drafts}) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eval_run_case_persists_rule_scored_result(monkeypatch):
    from nexagent.services import eval_service

    eval_dir = _fresh_eval_dir()
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)

    async def fake_agent_case(case, model):
        response = 'The expected answer cites [E1]. ```nexagent-evidence\n[{"id":"E1","source":"doc.md"}]\n```'
        return response, [], []

    monkeypatch.setattr(eval_service, "_run_agent_case", fake_agent_case)

    case = eval_service.create_case(
        name="answer check",
        query="question",
        expected_answer="expected answer",
        expected_sources=["doc.md"],
    )

    result = await eval_service.run_case(case["id"])
    stored = eval_service.list_results(case["id"])

    assert result["passed"] is True
    assert result["scores"]["answer_match"] == 1.0
    assert result["scores"]["citation_accuracy"] == 1.0
    assert result["scores"]["rag_hit_rate"] == 1.0
    assert stored[0]["run_id"] == result["run_id"]
    shutil.rmtree(eval_dir, ignore_errors=True)


def _fresh_eval_dir() -> Path:
    path = Path("test-artifacts") / "eval-service" / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path
