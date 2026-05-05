"""Evaluation router — test case management and batch evaluation runs.

Endpoints
---------
GET  /api/eval/cases              List all test cases
POST /api/eval/cases              Create a test case
DELETE /api/eval/cases/{id}       Delete a test case
POST /api/eval/cases/{id}/run     Run a single test case
POST /api/eval/run                Run all (or tag-filtered) test cases
GET  /api/eval/results            List all run results
GET  /api/eval/results/{test_id}  Results for a specific test case
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateCaseRequest(BaseModel):
    name: str
    type: str = "agent"
    query: str
    expected: str = ""
    expected_answer: str = ""
    expected_sources: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    agent: str = "chatbot"
    model: str = ""
    kb_ids: list[str] = Field(default_factory=list)
    task_id: str = ""
    retrieval_config: dict = Field(default_factory=dict)
    generation_source: str = ""
    generated_by_ai: bool = False
    tags: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    model: str | None = None
    tag: str | None = None


class KnowledgeQACase(BaseModel):
    question: str
    expected: str = ""
    relevant_file_ids: list[str] = []


class KnowledgeEvalRequest(BaseModel):
    kb_id: str
    cases: list[KnowledgeQACase]
    mode: str = "hybrid"
    top_k: int = 10
    recall_top_k: int | None = None
    final_top_k: int | None = None
    similarity_threshold: float | None = None
    vector_weight: float | None = None
    keyword_weight: float | None = None
    use_reranker: bool | None = None
    reranker_model: str = ""


class GenerateEvalRequest(BaseModel):
    source: str = "knowledge"
    type: str = "rag"
    count: int = Field(default=5, ge=1, le=20)
    neighbors_count: int = Field(default=0, ge=0, le=10)
    kb_ids: list[str] = Field(default_factory=list)
    agent: str = "chatbot"
    model: str = ""
    tags: list[str] = Field(default_factory=list)
    topic: str = ""
    retrieval_config: dict = Field(default_factory=dict)


class EvalSampleRequest(BaseModel):
    id: str = ""
    query: str
    expected_answer: str = ""
    expected_sources: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "normal"
    notes: str = ""


class CreateSuiteRequest(BaseModel):
    name: str
    type: str = "rag"
    agent: str = "chatbot"
    model: str = ""
    kb_ids: list[str] = Field(default_factory=list)
    task_id: str = ""
    retrieval_override_enabled: bool = False
    retrieval_config: dict = Field(default_factory=dict)
    samples: list[EvalSampleRequest]
    generation_source: str = ""
    generated_by_ai: bool = False
    tags: list[str] = Field(default_factory=list)


class UpdateSuiteRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    agent: str | None = None
    model: str | None = None
    kb_ids: list[str] | None = None
    task_id: str | None = None
    retrieval_override_enabled: bool | None = None
    retrieval_config: dict | None = None
    samples: list[EvalSampleRequest] | None = None
    tags: list[str] | None = None


class GenerateSuiteRequest(GenerateEvalRequest):
    name: str = ""
    retrieval_override_enabled: bool = False


# ── Test cases ────────────────────────────────────────────────────────────────

@router.get("/suites")
async def list_suites(tag: str | None = Query(default=None)):
    from nexagent.services.eval_service import list_suites as _list

    return {"suites": _list(tag=tag)}


@router.post("/suites", status_code=201)
async def create_suite(req: CreateSuiteRequest):
    from nexagent.services.eval_service import create_suite as _create

    try:
        return _create(
            name=req.name,
            type=req.type,
            agent=req.agent,
            model=req.model,
            kb_ids=req.kb_ids,
            task_id=req.task_id,
            retrieval_override_enabled=req.retrieval_override_enabled,
            retrieval_config=req.retrieval_config,
            samples=[sample.model_dump() for sample in req.samples],
            generation_source=req.generation_source,
            generated_by_ai=req.generated_by_ai,
            tags=req.tags,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/suites/{suite_id}")
async def update_suite(suite_id: str, req: UpdateSuiteRequest):
    from nexagent.services.eval_service import update_suite as _update

    patch = req.model_dump(exclude_unset=True)
    if req.samples is not None:
        patch["samples"] = [sample.model_dump() for sample in req.samples]
    try:
        return _update(suite_id, patch)
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/suites/{suite_id}", status_code=204)
async def delete_suite(suite_id: str):
    from nexagent.services.eval_service import delete_suite as _delete

    if not _delete(suite_id):
        raise HTTPException(status_code=404, detail="Eval suite not found")


@router.post("/suites/{suite_id}/run")
async def run_suite(suite_id: str, req: RunRequest = RunRequest()):
    from nexagent.services.eval_service import run_suite as _run

    try:
        return await _run(suite_id, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Eval suite run failed before sample execution: %s", suite_id)
        return {
            "suite": {"id": suite_id, "name": suite_id, "samples": []},
            "total": 0,
            "passed": 0,
            "failed": 1,
            "skipped": 0,
            "summary": {
                "status": "failed",
                "error": str(exc),
                "metrics": {},
            },
            "sample_results": [],
            "results": [],
        }


@router.post("/suites/generate")
async def generate_suite(req: GenerateSuiteRequest):
    from nexagent.services.eval_service import generate_suite as _generate

    try:
        return await _generate(
            name=req.name,
            source=req.source,
            type=req.type,
            count=req.count,
            neighbors_count=req.neighbors_count,
            kb_ids=req.kb_ids,
            agent=req.agent,
            model=req.model,
            tags=req.tags,
            topic=req.topic,
            retrieval_override_enabled=req.retrieval_override_enabled,
            retrieval_config=req.retrieval_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/cases")
async def list_cases(tag: str | None = Query(default=None)):
    from nexagent.services.eval_service import list_cases as _list
    return {"cases": _list(tag=tag)}


@router.post("/cases", status_code=201)
async def create_case(req: CreateCaseRequest):
    from nexagent.services.eval_service import create_case as _create
    case = _create(
        name=req.name,
        query=req.query,
        expected=req.expected,
        agent=req.agent,
        tags=req.tags,
        type=req.type,
        expected_answer=req.expected_answer,
        expected_sources=req.expected_sources,
        expected_tools=req.expected_tools,
        model=req.model,
        kb_ids=req.kb_ids,
        task_id=req.task_id,
        retrieval_config=req.retrieval_config,
        generation_source=req.generation_source,
        generated_by_ai=req.generated_by_ai,
    )
    return case


@router.post("/generate")
async def generate_cases(req: GenerateEvalRequest):
    from nexagent.services.eval_service import generate_cases as _generate

    try:
        return await _generate(
            source=req.source,
            type=req.type,
            count=req.count,
            neighbors_count=req.neighbors_count,
            kb_ids=req.kb_ids,
            agent=req.agent,
            model=req.model,
            tags=req.tags,
            topic=req.topic,
            retrieval_config=req.retrieval_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cases/{case_id}", status_code=204)
async def delete_case(case_id: str):
    from nexagent.services.eval_service import delete_case as _delete
    if not _delete(case_id):
        raise HTTPException(status_code=404, detail="Test case not found")


# ── Run ───────────────────────────────────────────────────────────────────────

@router.post("/cases/{case_id}/run")
async def run_case(case_id: str, req: RunRequest = RunRequest()):
    from nexagent.services.eval_service import run_case as _run
    try:
        result = await _run(case_id, model=req.model)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
async def run_all(req: RunRequest = RunRequest()):
    from nexagent.services.eval_service import run_all as _run_all
    results = await _run_all(tag=req.tag, model=req.model)
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("passed") is True),
        "failed": sum(1 for r in results if r.get("passed") is False),
        "skipped": sum(1 for r in results if r.get("passed") is None),
        "results": results,
    }


@router.post("/knowledge")
async def evaluate_knowledge(req: KnowledgeEvalRequest):
    from nexagent.knowledge.evaluator import (
        KnowledgeBaseEvaluator,
        QATestCase,
        RetrievalConfig,
    )

    report = await KnowledgeBaseEvaluator().evaluate(
        kb_id=req.kb_id,
        test_cases=[
            QATestCase(
                question=case.question,
                expected=case.expected,
                relevant_file_ids=case.relevant_file_ids,
            )
            for case in req.cases
        ],
        retrieval_config=RetrievalConfig(
            mode=req.mode,
            top_k=req.top_k,
            recall_top_k=req.recall_top_k,
            final_top_k=req.final_top_k,
            similarity_threshold=req.similarity_threshold,
            vector_weight=req.vector_weight,
            keyword_weight=req.keyword_weight,
            use_reranker=req.use_reranker,
            reranker_model=req.reranker_model,
        ),
    )
    return report.__dict__


# ── Results ───────────────────────────────────────────────────────────────────

@router.get("/results")
async def list_results():
    from nexagent.services.eval_service import list_results as _list
    return {"results": _list()}


@router.get("/results/{test_id}")
async def results_for_case(test_id: str):
    from nexagent.services.eval_service import list_results as _list
    results = _list(test_id=test_id)
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this test case")
    return {"results": results}
