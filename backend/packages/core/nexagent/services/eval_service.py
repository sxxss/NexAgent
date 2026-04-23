"""Evaluation service for agent, RAG, tool, and task regression checks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVAL_DIR = Path(".nexagent") / "evals"
EVAL_TYPES = {"agent", "rag", "tool", "task"}


def _cases_path() -> Path:
    path = _EVAL_DIR / "cases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _suites_path() -> Path:
    path = _EVAL_DIR / "suites.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _results_path() -> Path:
    path = _EVAL_DIR / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> list[dict]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _save_json(path: Path, data: list[dict]) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    eval_type = str(case.get("type") or "agent").strip() or "agent"
    if eval_type not in EVAL_TYPES:
        eval_type = "agent"
    expected_answer = str(case.get("expected_answer") or case.get("expected") or "")
    gold_chunk_ids = _list_of_strings(case.get("gold_chunk_ids")) or _list_of_strings(case.get("expected_sources"))
    expected_sources = _list_of_strings(case.get("expected_sources")) or gold_chunk_ids
    normalized = {
        "id": str(case.get("id") or uuid.uuid4()),
        "name": str(case.get("name") or "Untitled eval"),
        "type": eval_type,
        "query": str(case.get("query") or ""),
        "expected": expected_answer,
        "expected_answer": expected_answer,
        "expected_sources": expected_sources,
        "gold_chunk_ids": gold_chunk_ids,
        "expected_tools": _list_of_strings(case.get("expected_tools")),
        "agent": str(case.get("agent") or "chatbot"),
        "model": str(case.get("model") or ""),
        "kb_ids": _list_of_strings(case.get("kb_ids")),
        "retrieval_config": _normalize_retrieval_config(case.get("retrieval_config")),
        "generation_source": str(case.get("generation_source") or ""),
        "generated_by_ai": bool(case.get("generated_by_ai", False)),
        "tags": _list_of_strings(case.get("tags")),
        "created_at": str(case.get("created_at") or datetime.now(UTC).isoformat()),
    }
    for key in ("task_id", "metadata"):
        if key in case:
            normalized[key] = case[key]
    return normalized


def _list_of_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_retrieval_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_modes = {
        "vector",
        "keyword",
        "hybrid",
        "lightrag_local",
        "lightrag_global",
        "lightrag_hybrid",
    }
    config = dict(value)
    mode = str(config.get("mode") or "")
    if mode and mode not in allowed_modes:
        config["mode"] = "hybrid"
    for key in ("top_k", "final_top_k", "recall_top_k", "bm25_top_k", "graph_depth", "graph_limit"):
        if key in config:
            try:
                config[key] = max(1, int(config[key]))
            except (TypeError, ValueError):
                config.pop(key, None)
    for key in ("similarity_threshold", "vector_weight", "keyword_weight", "bm25_weight", "bm25_drop_ratio_search"):
        if key in config:
            try:
                config[key] = max(0.0, min(float(config[key]), 1.0))
            except (TypeError, ValueError):
                config.pop(key, None)
    if "use_reranker" in config:
        config["use_reranker"] = bool(config["use_reranker"])
    if "reranker_model" in config:
        config["reranker_model"] = str(config["reranker_model"] or "")
    return config


def list_cases(tag: str | None = None) -> list[dict]:
    cases = [_normalize_case(case) for case in _load_json(_cases_path())]
    if tag:
        cases = [case for case in cases if tag in case.get("tags", [])]
    return cases


def get_case(case_id: str) -> dict | None:
    return next((case for case in list_cases() if case["id"] == case_id), None)


def _normalize_sample(sample: dict[str, Any]) -> dict[str, Any]:
    expected_answer = str(sample.get("expected_answer") or sample.get("expected") or "")
    gold_chunk_ids = _list_of_strings(sample.get("gold_chunk_ids")) or _list_of_strings(sample.get("expected_sources"))
    expected_sources = _list_of_strings(sample.get("expected_sources")) or gold_chunk_ids
    return {
        "id": str(sample.get("id") or uuid.uuid4()),
        "query": str(sample.get("query") or sample.get("question") or ""),
        "expected_answer": expected_answer,
        "expected": expected_answer,
        "expected_sources": expected_sources,
        "gold_chunk_ids": gold_chunk_ids,
        "expected_tools": _list_of_strings(sample.get("expected_tools")),
        "tags": _list_of_strings(sample.get("tags")),
        "difficulty": str(sample.get("difficulty") or "normal"),
        "notes": str(sample.get("notes") or ""),
    }


def _case_to_suite(case: dict[str, Any]) -> dict[str, Any]:
    case = _normalize_case(case)
    sample = _normalize_sample(
        {
            "id": case["id"],
            "query": case["query"],
            "expected_answer": case.get("expected_answer") or case.get("expected") or "",
            "expected_sources": case.get("expected_sources", []),
            "gold_chunk_ids": case.get("gold_chunk_ids", []),
            "expected_tools": case.get("expected_tools", []),
            "tags": case.get("tags", []),
        }
    )
    return {
        "id": case["id"],
        "name": case["name"],
        "type": case.get("type") or "rag",
        "agent": case.get("agent") or "chatbot",
        "model": case.get("model") or "",
        "kb_ids": _list_of_strings(case.get("kb_ids")),
        "task_id": str(case.get("task_id") or ""),
        "retrieval_override_enabled": bool(case.get("retrieval_config")),
        "retrieval_config": _normalize_retrieval_config(case.get("retrieval_config")),
        "samples": [sample],
        "generation_source": str(case.get("generation_source") or ""),
        "generated_by_ai": bool(case.get("generated_by_ai", False)),
        "tags": _list_of_strings(case.get("tags")),
        "created_at": case.get("created_at") or datetime.now(UTC).isoformat(),
        "updated_at": case.get("created_at") or datetime.now(UTC).isoformat(),
        "legacy_case_id": case["id"],
    }


def _normalize_suite(suite: dict[str, Any]) -> dict[str, Any]:
    if "samples" not in suite and ("query" in suite or "expected_answer" in suite or "expected" in suite):
        return _case_to_suite(suite)
    eval_type = str(suite.get("type") or "rag").strip() or "rag"
    if eval_type not in EVAL_TYPES:
        eval_type = "rag"
    samples = [_normalize_sample(item) for item in suite.get("samples", []) if isinstance(item, dict)]
    return {
        "id": str(suite.get("id") or uuid.uuid4()),
        "name": str(suite.get("name") or "Untitled eval suite"),
        "type": eval_type,
        "agent": str(suite.get("agent") or "chatbot"),
        "model": str(suite.get("model") or ""),
        "kb_ids": _list_of_strings(suite.get("kb_ids")),
        "task_id": str(suite.get("task_id") or ""),
        "retrieval_override_enabled": bool(suite.get("retrieval_override_enabled", False)),
        "retrieval_config": _normalize_retrieval_config(suite.get("retrieval_config")),
        "samples": samples,
        "generation_source": str(suite.get("generation_source") or ""),
        "generated_by_ai": bool(suite.get("generated_by_ai", False)),
        "tags": _list_of_strings(suite.get("tags")),
        "created_at": str(suite.get("created_at") or datetime.now(UTC).isoformat()),
        "updated_at": str(suite.get("updated_at") or suite.get("created_at") or datetime.now(UTC).isoformat()),
    }


def _validate_suite(suite: dict[str, Any]) -> None:
    if not suite["name"].strip():
        raise ValueError("Eval suite name is required.")
    if not suite["samples"]:
        raise ValueError("Eval suite must contain at least one sample.")
    for index, sample in enumerate(suite["samples"], start=1):
        if not sample["query"].strip():
            raise ValueError(f"Sample {index} query is required.")
        if (
            suite["type"] == "rag"
            and not sample["expected_answer"].strip()
            and not sample.get("gold_chunk_ids")
            and not sample.get("expected_sources")
        ):
            raise ValueError(f"Sample {index} must configure expected answer or gold chunk ids for RAG eval.")
    if suite["type"] == "rag" and not suite["kb_ids"]:
        raise ValueError("RAG eval suite requires at least one knowledge base.")
    if suite["retrieval_override_enabled"] and _kb_types_for_ids(suite["kb_ids"]) == {"milvus", "lightrag"}:
        raise ValueError("Mixed Milvus and LightRAG suites must use each knowledge base default retrieval strategy.")


def _kb_types_for_ids(kb_ids: list[str]) -> set[str]:
    if not kb_ids:
        return set()
    try:
        from nexagent.knowledge.manager import get_manager

        manager = get_manager()
        types: set[str] = set()
        for kb_id in kb_ids:
            kb = manager.get_kb(kb_id)
            if kb is not None:
                types.add(kb.kb_type.value)
        return types
    except Exception:
        return set()


def list_suites(tag: str | None = None) -> list[dict]:
    suites = [_normalize_suite(suite) for suite in _load_json(_suites_path())]
    legacy_ids = {suite.get("legacy_case_id") for suite in suites if suite.get("legacy_case_id")}
    for case in _load_json(_cases_path()):
        normalized_case = _normalize_case(case)
        if normalized_case["id"] not in legacy_ids and not any(
            suite["id"] == normalized_case["id"] for suite in suites
        ):
            suites.append(_case_to_suite(normalized_case))
    if tag:
        suites = [suite for suite in suites if tag in suite.get("tags", [])]
    return suites


def get_suite(suite_id: str) -> dict | None:
    return next((suite for suite in list_suites() if suite["id"] == suite_id), None)


def create_suite(
    *,
    name: str,
    samples: list[dict[str, Any]],
    type: str = "rag",
    agent: str = "chatbot",
    model: str = "",
    kb_ids: list[str] | None = None,
    task_id: str = "",
    retrieval_override_enabled: bool = False,
    retrieval_config: dict[str, Any] | None = None,
    generation_source: str = "",
    generated_by_ai: bool = False,
    tags: list[str] | None = None,
) -> dict:
    now = datetime.now(UTC).isoformat()
    suite = _normalize_suite(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "type": type,
            "agent": agent,
            "model": model,
            "kb_ids": kb_ids or [],
            "task_id": task_id,
            "retrieval_override_enabled": retrieval_override_enabled,
            "retrieval_config": retrieval_config or {},
            "samples": samples,
            "generation_source": generation_source,
            "generated_by_ai": generated_by_ai,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
        }
    )
    _validate_suite(suite)
    suites = [_normalize_suite(item) for item in _load_json(_suites_path())]
    suites.append(suite)
    _save_json(_suites_path(), suites)
    return suite


def update_suite(suite_id: str, patch: dict[str, Any]) -> dict:
    suites = [_normalize_suite(item) for item in _load_json(_suites_path())]
    for index, suite in enumerate(suites):
        if suite["id"] != suite_id:
            continue
        merged = {**suite, **patch, "id": suite_id, "updated_at": datetime.now(UTC).isoformat()}
        normalized = _normalize_suite(merged)
        _validate_suite(normalized)
        suites[index] = normalized
        _save_json(_suites_path(), suites)
        return normalized
    legacy = get_case(suite_id)
    if legacy:
        raise ValueError("Legacy single-case evals cannot be edited as suites. Create a new eval suite instead.")
    raise ValueError(f"Eval suite not found: {suite_id}")


def delete_suite(suite_id: str) -> bool:
    suites = [_normalize_suite(item) for item in _load_json(_suites_path())]
    next_suites = [suite for suite in suites if suite["id"] != suite_id]
    if len(next_suites) != len(suites):
        _save_json(_suites_path(), next_suites)
        return True
    return delete_case(suite_id)


def create_case(
    name: str,
    query: str,
    expected: str = "",
    agent: str = "chatbot",
    tags: list[str] | None = None,
    *,
    type: str = "agent",
    expected_answer: str = "",
    expected_sources: list[str] | None = None,
    expected_tools: list[str] | None = None,
    model: str | None = None,
    kb_ids: list[str] | None = None,
    task_id: str = "",
    retrieval_config: dict[str, Any] | None = None,
    generation_source: str = "",
    generated_by_ai: bool = False,
) -> dict:
    case = _normalize_case(
        {
            "id": str(uuid.uuid4()),
            "name": name,
            "type": type,
            "query": query,
            "expected": expected_answer or expected,
            "expected_answer": expected_answer or expected,
            "expected_sources": expected_sources or [],
            "expected_tools": expected_tools or [],
            "agent": agent,
            "model": model or "",
            "kb_ids": kb_ids or [],
            "task_id": task_id,
            "retrieval_config": retrieval_config or {},
            "generation_source": generation_source,
            "generated_by_ai": generated_by_ai,
            "tags": tags or [],
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    cases = [_normalize_case(item) for item in _load_json(_cases_path())]
    cases.append(case)
    _save_json(_cases_path(), cases)
    return case


def delete_case(case_id: str) -> bool:
    cases = [_normalize_case(case) for case in _load_json(_cases_path())]
    next_cases = [case for case in cases if case["id"] != case_id]
    if len(next_cases) == len(cases):
        return False
    _save_json(_cases_path(), next_cases)
    return True


def list_results(test_id: str | None = None) -> list[dict]:
    results = _load_json(_results_path())
    if test_id:
        results = [result for result in results if result.get("test_id") == test_id]
    return sorted(results, key=lambda result: result.get("timestamp", ""), reverse=True)


def _save_result(result: dict) -> None:
    results = _load_json(_results_path())
    results.append(result)
    _save_json(_results_path(), results)


async def run_case(case_id: str, model: str | None = None) -> dict:
    """Execute one eval case and persist a scored result."""
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Test case not found: {case_id}")
    return await _execute_case(case, result_test_id=case_id, model=model)


async def _execute_case(
    case: dict[str, Any],
    *,
    result_test_id: str,
    model: str | None = None,
    suite_id: str = "",
    sample_id: str = "",
) -> dict:
    start = time.monotonic()
    response_text = ""
    error = None
    artifacts: list[str] = []
    evidence: list[dict[str, Any]] = []
    retrieved_chunks: list[dict[str, Any]] = []
    retrieval_warnings: list[dict[str, Any]] = []
    tools_used: list[str] = []
    task_status = ""
    selected_model = model or case.get("model") or None
    error_code = ""

    try:
        if case["type"] == "rag":
            rag_result = await _run_rag_case_full(case, selected_model)
            response_text = rag_result[0]
            evidence = rag_result[1]
            retrieved_chunks = rag_result[2]
            retrieval_warnings = rag_result[3]
            error_code = str(rag_result[4] or "")
            if rag_result[5]:
                error = str(rag_result[5])
        elif case["type"] == "task":
            response_text, task_status = _run_task_case(case)
        else:
            response_text, artifacts, tools_used = await _run_agent_case(case, selected_model)
    except Exception as exc:
        response_text = ""
        error = str(exc)
        error_code = _eval_error_code(exc)

    latency_ms = int((time.monotonic() - start) * 1000)
    embedded_evidence = extract_evidence_blocks(response_text)
    if embedded_evidence:
        evidence = embedded_evidence
    if not retrieved_chunks:
        retrieved_chunks = [dict(item) for item in evidence]
    retrieved_source_ids = source_ids_from_evidence(retrieved_chunks)
    gold_source_ids = _list_of_strings(case.get("gold_chunk_ids")) or _list_of_strings(case.get("expected_sources"))
    scores = score_eval_result(
        case=case,
        response=response_text,
        evidence=evidence,
        tools_used=tools_used,
        task_status=task_status,
        error=error,
    )
    metrics = {
        **retrieval_metrics_at_k(retrieved_source_ids, gold_source_ids),
        **scores,
    }
    passed = passed_from_scores(scores, error=error)
    judge_reason = score_reason(scores, error=error)
    if case.get("metadata", {}).get("judge") == "llm" and case.get("expected_answer") and response_text and not error:
        passed, judge_reason = await _llm_judge(
            query=case["query"],
            expected=case["expected_answer"],
            actual=response_text,
            model=selected_model,
        )

    token_usage = {
        "input_tokens": estimate_tokens(case["query"]),
        "output_tokens": estimate_tokens(response_text),
    }
    result = {
        "test_id": result_test_id,
        "run_id": str(uuid.uuid4()),
        "suite_id": suite_id,
        "sample_id": sample_id,
        "type": case["type"],
        "agent": case.get("agent", "chatbot"),
        "model": selected_model or "",
        "query": case["query"],
        "response": response_text,
        "actual_answer": response_text,
        "error": error,
        "error_code": error_code,
        "latency_ms": latency_ms,
        "tokens_estimated": token_usage["input_tokens"] + token_usage["output_tokens"],
        "token_usage": token_usage,
        "passed": passed,
        "judge_reason": judge_reason,
        "scores": scores,
        "metrics": metrics,
        "artifacts": artifacts,
        "evidence": evidence,
        "retrieved_chunks": retrieved_chunks,
        "retrieved_source_ids": retrieved_source_ids,
        "gold_source_ids": gold_source_ids,
        "gold_chunk_ids": gold_source_ids,
        "retrieval_warnings": retrieval_warnings or _retrieval_warnings_from_evidence(evidence),
        "tools_used": tools_used,
        "retrieval_config": case.get("retrieval_config") or {},
        "timestamp": datetime.now(UTC).isoformat(),
    }
    _save_result(result)
    return result


async def _run_agent_case(case: dict[str, Any], model: str | None) -> tuple[str, list[str], list[str]]:
    from nexagent.services.chat_service import invoke_chat

    context: dict[str, Any] = {}
    if model:
        context["model"] = model
    if case.get("kb_ids"):
        context["kb_ids"] = case["kb_ids"]
    response = await invoke_chat(
        message=case["query"],
        agent_name=case.get("agent", "chatbot"),
        context_overrides=context,
    )
    return (
        str(response.get("response") or ""),
        _list_of_strings(response.get("artifacts")),
        _list_of_strings(response.get("tools_used")),
    )


async def _run_rag_case(
    case: dict[str, Any], model: str | None = None
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    result = await _run_rag_case_full(case, model)
    if result[4] or result[5]:
        raise RuntimeError(result[5] or result[4])
    return result[0], result[1], result[2]


async def _run_rag_case_full(
    case: dict[str, Any], model: str | None = None
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str, str]:
    if not case.get("kb_ids"):
        return "", [], [], [], "no_knowledge_base", "No knowledge base configured for this RAG eval."
    from nexagent.knowledge.search_service import structured_retrieve

    retrieval_config = _normalize_retrieval_config(case.get("retrieval_config"))
    if not retrieval_config and len(case.get("kb_ids") or []) == 1:
        try:
            from nexagent.knowledge.manager import get_manager

            retrieval_config = _normalize_retrieval_config(get_manager().get_query_config(case["kb_ids"][0]))
        except Exception:
            retrieval_config = {}
    mode = str(retrieval_config.get("mode") or "hybrid")
    top_k = int(retrieval_config.get("final_top_k") or retrieval_config.get("top_k") or 10)
    search_kwargs = dict(retrieval_config)
    search_kwargs.pop("mode", None)
    search_kwargs.pop("search_mode", None)
    search_result = await structured_retrieve(
        query=case["query"],
        kb_ids=case["kb_ids"],
        mode=mode,  # type: ignore[arg-type]
        top_k=top_k,
        **search_kwargs,
    )
    chunks = search_result.chunks
    evidence: list[dict[str, Any]] = []
    retrieved_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        if hasattr(chunk, "evidence"):
            item = chunk.evidence(index)
        else:
            item = {
                "id": f"E{index}",
                "source": getattr(chunk, "source", ""),
                "file_id": getattr(chunk, "file_id", ""),
            }
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        item["chunk_id"] = metadata.get("chunk_id") or item.get("chunk_id") or item.get("id")
        item["chunk_index"] = metadata.get("chunk_index")
        item["content"] = str(getattr(chunk, "content", ""))[:500]
        evidence.append(item)
        retrieved_chunks.append(dict(item))
    if search_result.error and not chunks:
        return (
            "",
            evidence,
            retrieved_chunks,
            search_result.warning_dicts(),
            search_result.error_code,
            search_result.error,
        )
    if not (case.get("expected_answer") or case.get("expected")) and (
        case.get("gold_chunk_ids") or case.get("expected_sources")
    ):
        return "", evidence, retrieved_chunks, search_result.warning_dicts(), "", ""
    try:
        answer, _, _ = await _run_agent_case(case, model)
    except Exception as exc:
        logger.warning("RAG eval agent answer failed.", exc_info=True)
        return "", evidence, retrieved_chunks, search_result.warning_dicts(), "model_failed", str(exc)
    return answer, evidence, retrieved_chunks, search_result.warning_dicts(), "", ""


def _eval_error_code(error: Exception | str) -> str:
    detail = str(error).lower()
    if "collection not found" in detail:
        return "milvus_collection_missing"
    if "pymilvus" in detail or "dependency missing" in detail:
        return "milvus_dependency_missing"
    if "embedding" in detail or "api key" in detail:
        return "embedding_failed"
    if "milvus" in detail or "service unavailable" in detail:
        return "milvus_service_unavailable"
    if "timeout" in detail:
        return "search_timeout"
    return "eval_sample_failed"


def _failed_sample_result(
    suite: dict[str, Any],
    sample: dict[str, Any],
    case: dict[str, Any],
    *,
    model: str | None,
    error: Exception,
) -> dict[str, Any]:
    error_code = _eval_error_code(error)
    now = datetime.now(UTC).isoformat()
    gold_ids = _list_of_strings(case.get("gold_chunk_ids")) or _list_of_strings(case.get("expected_sources"))
    result = {
        "test_id": suite["id"],
        "run_id": str(uuid.uuid4()),
        "suite_id": suite["id"],
        "sample_id": sample.get("id", ""),
        "type": case.get("type", suite.get("type", "rag")),
        "agent": case.get("agent", suite.get("agent", "chatbot")),
        "model": model or case.get("model") or "",
        "query": case.get("query") or sample.get("query") or "",
        "response": "",
        "actual_answer": "",
        "error": str(error),
        "error_code": error_code,
        "latency_ms": 0,
        "tokens_estimated": 0,
        "token_usage": {"input_tokens": 0, "output_tokens": 0},
        "passed": False,
        "judge_reason": str(error),
        "scores": {
            "rag_hit_rate": 0,
            "citation_accuracy": None,
            "answer_match": 0,
            "tool_success_rate": None,
            "task_completion_rate": None,
        },
        "metrics": {
            "recall@1": 0,
            "recall@3": 0,
            "recall@5": 0,
            "recall@10": 0,
            "precision@1": 0,
            "precision@3": 0,
            "precision@5": 0,
            "precision@10": 0,
            "f1@1": 0,
            "f1@3": 0,
            "f1@5": 0,
            "f1@10": 0,
            "answer_match": 0,
        },
        "artifacts": [],
        "evidence": [],
        "retrieved_chunks": [],
        "retrieved_source_ids": [],
        "gold_source_ids": gold_ids,
        "gold_chunk_ids": gold_ids,
        "retrieval_warnings": [{"code": error_code, "message": str(error), "action": ""}],
        "tools_used": [],
        "retrieval_config": case.get("retrieval_config") or {},
        "timestamp": now,
    }
    try:
        _save_result(result)
    except Exception:
        logger.warning("Failed to persist eval failure result", exc_info=True)
    return result


def _run_task_case(case: dict[str, Any]) -> tuple[str, str]:
    task_id = str(case.get("task_id") or case.get("metadata", {}).get("task_id") or "")
    if not task_id:
        return "No task_id configured for this eval case.", ""
    from nexagent.services.task_service import get_task

    task = get_task(task_id)
    if task is None:
        return f"Task not found: {task_id}", "missing"
    return json.dumps(task.to_dict(), ensure_ascii=False), task.status


async def run_all(tag: str | None = None, model: str | None = None) -> list[dict]:
    cases = list_cases(tag=tag)
    if not cases:
        return []
    tasks = [run_case(case["id"], model=model) for case in cases]
    return await asyncio.gather(*tasks, return_exceptions=False)


def _suite_sample_to_case(suite: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    retrieval_config = suite.get("retrieval_config") if suite.get("retrieval_override_enabled") else {}
    return _normalize_case(
        {
            "id": sample["id"],
            "name": f"{suite['name']} / {sample.get('query', '')[:32]}",
            "type": suite["type"],
            "query": sample["query"],
            "expected": sample.get("expected_answer") or sample.get("expected") or "",
            "expected_answer": sample.get("expected_answer") or sample.get("expected") or "",
            "expected_sources": sample.get("expected_sources", []),
            "gold_chunk_ids": sample.get("gold_chunk_ids", []),
            "expected_tools": sample.get("expected_tools", []),
            "agent": suite.get("agent") or "chatbot",
            "model": suite.get("model") or "",
            "kb_ids": suite.get("kb_ids") or [],
            "task_id": suite.get("task_id") or "",
            "retrieval_config": retrieval_config,
            "tags": sorted(set(_list_of_strings(suite.get("tags")) + _list_of_strings(sample.get("tags")))),
        }
    )


async def run_suite(suite_id: str, model: str | None = None) -> dict[str, Any]:
    suite = get_suite(suite_id)
    if not suite:
        raise ValueError(f"Eval suite not found: {suite_id}")
    results: list[dict[str, Any]] = []
    for sample in suite["samples"]:
        case = _suite_sample_to_case(suite, sample)
        try:
            results.append(
                await _execute_case(
                    case,
                    result_test_id=suite_id,
                    model=model,
                    suite_id=suite_id,
                    sample_id=sample["id"],
                )
            )
        except Exception as exc:
            logger.exception("Eval suite %s sample %s failed", suite_id, sample.get("id"))
            results.append(_failed_sample_result(suite, sample, case, model=model, error=exc))
    passed = sum(1 for item in results if item.get("passed") is True)
    failed = sum(1 for item in results if item.get("passed") is False)
    skipped = sum(1 for item in results if item.get("passed") is None)
    summary = _summarize_suite_results(results)
    return {
        "suite": suite,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "summary": summary,
        "sample_results": results,
        "results": results,
    }


async def generate_cases(
    *,
    source: str = "knowledge",
    type: str = "rag",
    count: int = 5,
    neighbors_count: int = 0,
    kb_ids: list[str] | None = None,
    agent: str = "chatbot",
    model: str = "",
    tags: list[str] | None = None,
    topic: str = "",
    retrieval_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate editable eval case drafts without persisting them."""
    eval_type = type if type in EVAL_TYPES else "rag"
    count = max(1, min(int(count or 5), 20))
    neighbors_count = max(0, min(int(neighbors_count or 0), 10))
    kb_ids = kb_ids or []
    tags = tags or []
    retrieval_config = _normalize_retrieval_config(retrieval_config)
    contexts, diagnostics = _collect_generation_contexts(
        source=source, kb_ids=kb_ids, topic=topic, limit=count * 2, neighbors_count=neighbors_count
    )
    if not contexts:
        if source == "knowledge":
            raise ValueError("该知识库没有可用于生成评估的 indexed chunks，请先完成入库。")
        raise ValueError(
            "No source material found for eval generation. Select an indexed knowledge base or provide a topic."
        )

    drafts = await _generate_with_llm(
        contexts=contexts,
        count=count,
        eval_type=eval_type,
        agent=agent,
        model=model,
        kb_ids=kb_ids,
        tags=tags,
        source=source,
        retrieval_config=retrieval_config,
    )
    if not drafts:
        drafts = _generate_rule_based_drafts(
            contexts=contexts,
            count=count,
            eval_type=eval_type,
            agent=agent,
            model=model,
            kb_ids=kb_ids,
            tags=tags,
            source=source,
            retrieval_config=retrieval_config,
        )
    return {"drafts": drafts, "total": len(drafts), "source": source, "diagnostics": diagnostics}


async def generate_suite(
    *,
    name: str = "",
    source: str = "knowledge",
    type: str = "rag",
    count: int = 5,
    neighbors_count: int = 0,
    kb_ids: list[str] | None = None,
    agent: str = "chatbot",
    model: str = "",
    tags: list[str] | None = None,
    topic: str = "",
    retrieval_override_enabled: bool = False,
    retrieval_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated = await generate_cases(
        source=source,
        type=type,
        count=count,
        neighbors_count=neighbors_count,
        kb_ids=kb_ids,
        agent=agent,
        model=model,
        tags=tags,
        topic=topic,
        retrieval_config=retrieval_config if retrieval_override_enabled else {},
    )
    samples = [
        _normalize_sample(
            {
                "id": draft.get("id"),
                "query": draft.get("query"),
                "expected_answer": draft.get("expected_answer") or draft.get("expected"),
                "expected_sources": draft.get("expected_sources", []),
                "gold_chunk_ids": draft.get("gold_chunk_ids", draft.get("expected_sources", [])),
                "expected_tools": draft.get("expected_tools", []),
                "tags": draft.get("tags", []),
            }
        )
        for draft in generated["drafts"]
    ]
    suite = _normalize_suite(
        {
            "id": f"draft-suite-{uuid.uuid4().hex[:10]}",
            "name": name or "AI generated eval suite",
            "type": type,
            "agent": agent,
            "model": model,
            "kb_ids": kb_ids or [],
            "retrieval_override_enabled": retrieval_override_enabled,
            "retrieval_config": retrieval_config or {},
            "samples": samples,
            "generation_source": source,
            "generated_by_ai": True,
            "tags": tags or [],
        }
    )
    return {
        "suite": suite,
        "samples": samples,
        "total": len(samples),
        "source": source,
        "diagnostics": generated.get("diagnostics", []),
    }


def score_eval_result(
    *,
    case: dict[str, Any],
    response: str,
    evidence: list[dict[str, Any]] | None = None,
    tools_used: list[str] | None = None,
    task_status: str = "",
    error: str | None = None,
) -> dict[str, float | None]:
    evidence = evidence or []
    tools_used = tools_used or []
    return {
        "rag_hit_rate": score_rag_hit(case.get("expected_sources", []), evidence),
        "citation_accuracy": score_citation_accuracy(response, evidence),
        "answer_match": score_answer_match(case.get("expected_answer") or case.get("expected") or "", response),
        "tool_success_rate": score_tool_success(case.get("expected_tools", []), tools_used, error=error),
        "task_completion_rate": score_task_completion(task_status),
    }


def _summarize_suite_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    if not total:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": None,
            "avg_latency_ms": 0,
            "error_count": 0,
            "scores": {},
            "metrics": {},
        }
    passed = sum(1 for item in results if item.get("passed") is True)
    failed = sum(1 for item in results if item.get("passed") is False)
    error_count = sum(1 for item in results if item.get("error"))
    score_keys = ["rag_hit_rate", "citation_accuracy", "answer_match", "tool_success_rate", "task_completion_rate"]
    scores: dict[str, float | None] = {}
    for key in score_keys:
        values = [
            float(item.get("scores", {}).get(key)) for item in results if item.get("scores", {}).get(key) is not None
        ]
        scores[key] = round(sum(values) / len(values), 3) if values else None
    metric_keys = [
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@10",
        "precision@1",
        "precision@3",
        "precision@5",
        "precision@10",
        "f1@1",
        "f1@3",
        "f1@5",
        "f1@10",
        *score_keys,
    ]
    metrics: dict[str, float | None] = {}
    for key in metric_keys:
        values = [
            float(item.get("metrics", {}).get(key)) for item in results if item.get("metrics", {}).get(key) is not None
        ]
        metrics[key] = round(sum(values) / len(values), 3) if values else None
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 3),
        "avg_latency_ms": round(sum(int(item.get("latency_ms") or 0) for item in results) / total),
        "error_count": error_count,
        "scores": scores,
        "metrics": metrics,
    }


def _retrieval_warnings_from_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: dict[str, dict[str, str]] = {}
    for item in evidence:
        metadata = item.get("metadata") or {}
        if not isinstance(metadata, dict) or not metadata.get("degraded"):
            continue
        reason = str(metadata.get("degraded_reason") or "degraded_search")
        warnings[reason] = {
            "code": reason,
            "message": "Retrieval used a degraded local fallback.",
            "action": str(metadata.get("action") or ""),
        }
    return list(warnings.values())


def score_answer_match(expected: str, actual: str) -> float | None:
    expected = expected.strip()
    actual = actual.strip()
    if not expected:
        return None
    if not actual:
        return 0.0
    expected_lower = expected.lower()
    actual_lower = actual.lower()
    if expected_lower in actual_lower:
        return 1.0
    expected_tokens = set(_tokens(expected_lower))
    actual_tokens = set(_tokens(actual_lower))
    if not expected_tokens:
        return 0.0
    return round(len(expected_tokens & actual_tokens) / len(expected_tokens), 3)


def score_rag_hit(expected_sources: list[str], evidence: list[dict[str, Any]]) -> float | None:
    expected = {item.lower() for item in expected_sources if item}
    if not expected:
        return None
    haystack: set[str] = set()
    for item in evidence:
        for key in ("chunk_id", "id", "source", "file_id", "path", "title"):
            value = str(item.get(key) or "").lower()
            if value:
                haystack.add(value)
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            for key in ("chunk_id", "id", "source", "file_id", "path", "title"):
                value = str(metadata.get(key) or "").lower()
                if value:
                    haystack.add(value)
    hits = sum(1 for source in expected if any(source in item or item in source for item in haystack))
    return round(hits / len(expected), 3)


def source_ids_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for item in evidence:
        candidates = [
            item.get("chunk_id"),
            item.get("id"),
            item.get("source"),
            item.get("file_id"),
            item.get("path"),
            item.get("title"),
        ]
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            candidates.extend(
                [
                    metadata.get("chunk_id"),
                    metadata.get("id"),
                    metadata.get("source"),
                    metadata.get("file_id"),
                    metadata.get("path"),
                    metadata.get("title"),
                ]
            )
        for candidate in candidates:
            value = str(candidate or "").strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
                break
    return ids


def retrieval_metrics_at_k(
    retrieved_ids: list[str], gold_ids: list[str], k_values: tuple[int, ...] = (1, 3, 5, 10)
) -> dict[str, float | None]:
    gold = [item for item in gold_ids if item]
    if not gold:
        return {f"{name}@{k}": None for k in k_values for name in ("recall", "precision", "f1")}
    metrics: dict[str, float | None] = {}
    for k in k_values:
        top = retrieved_ids[:k]
        matched_retrieved = sum(1 for item in top if any(_source_id_matches(item, gold_item) for gold_item in gold))
        matched_gold = sum(1 for gold_item in gold if any(_source_id_matches(item, gold_item) for item in top))
        precision = matched_retrieved / len(top) if top else 0.0
        recall = matched_gold / len(gold)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        metrics[f"precision@{k}"] = round(precision, 3)
        metrics[f"recall@{k}"] = round(recall, 3)
        metrics[f"f1@{k}"] = round(f1, 3)
    return metrics


def _source_id_matches(left: str, right: str) -> bool:
    left_norm = str(left or "").strip().lower()
    right_norm = str(right or "").strip().lower()
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm or left_norm in right_norm or right_norm in left_norm


def score_citation_accuracy(response: str, evidence: list[dict[str, Any]]) -> float | None:
    citations = extract_citation_ids(response)
    if not citations:
        return None
    evidence_ids = {str(item.get("id") or "").strip() for item in evidence if item.get("id")}
    if not evidence_ids:
        return 0.0
    hits = sum(1 for citation in citations if citation in evidence_ids)
    return round(hits / len(citations), 3)


def score_tool_success(expected_tools: list[str], tools_used: list[str], *, error: str | None = None) -> float | None:
    expected = {tool for tool in expected_tools if tool}
    if not expected:
        return None
    if error:
        return 0.0
    used = set(tools_used)
    hits = len(expected & used)
    return round(hits / len(expected), 3)


def score_task_completion(status: str) -> float | None:
    if not status:
        return None
    if status == "completed":
        return 1.0
    if status in {"failed", "interrupted", "cancelled", "missing"}:
        return 0.0
    return 0.5


def extract_citation_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in re.finditer(r"\[([A-Za-z][A-Za-z0-9_-]{0,32})\]", text or ""):
        citation = match.group(1)
        if citation not in seen:
            seen.add(citation)
            ids.append(citation)
    return ids


def extract_evidence_blocks(text: str) -> list[dict[str, Any]]:
    if "```nexagent-evidence" not in (text or ""):
        return []
    items: list[dict[str, Any]] = []
    for match in re.finditer(r"```nexagent-evidence\s*([\s\S]*?)```", text):
        try:
            parsed = json.loads(match.group(1).strip())
        except Exception:
            continue
        if isinstance(parsed, list):
            items.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            items.append(parsed)
    return items


def passed_from_scores(scores: dict[str, float | None], *, error: str | None = None) -> bool | None:
    if error:
        return False
    active_scores = [score for score in scores.values() if score is not None]
    if not active_scores:
        return None
    return sum(active_scores) / len(active_scores) >= 0.7


def score_reason(scores: dict[str, float | None], *, error: str | None = None) -> str:
    if error:
        return f"Evaluation failed: {error}"
    active = {key: value for key, value in scores.items() if value is not None}
    if not active:
        return "No objective scoring criteria were configured."
    return ", ".join(f"{key}={value:.2f}" for key, value in active.items())


def estimate_tokens(text: str) -> int:
    text = text or ""
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    if tokens:
        return tokens
    return list(text)


def _collect_generation_contexts(
    *, source: str, kb_ids: list[str], topic: str, limit: int, neighbors_count: int = 0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source == "manual":
        text = _clean_generation_text(topic.strip())
        contexts = [{"content": text, "source": "manual", "file_id": "manual", "chunk_id": "manual"}] if text else []
        return contexts, [
            {
                "kb_id": "manual",
                "name": "Manual topic",
                "status": "ready" if contexts else "empty",
                "chunks": len(contexts),
                "source": "manual",
                "warnings": [],
            }
        ]
    if source == "recent_logs":
        contexts = _collect_recent_log_contexts(limit=limit)
        return contexts, [
            {
                "kb_id": "recent_logs",
                "name": "Recent logs",
                "status": "ready" if contexts else "empty",
                "chunks": len(contexts),
                "source": "recent_logs",
                "warnings": [],
            }
        ]
    return _collect_kb_contexts(kb_ids=kb_ids, topic=topic, limit=limit, neighbors_count=neighbors_count)


def _collect_kb_contexts(
    *, kb_ids: list[str], topic: str, limit: int, neighbors_count: int = 0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from nexagent.knowledge.manager import get_manager

    manager = get_manager()
    selected_kbs = kb_ids or [kb.kb_id for kb in manager.list_kbs()]
    contexts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    topic_terms = set(_tokens(topic))
    for kb_id in selected_kbs:
        kb = manager.get_kb(kb_id)
        if kb is None:
            diagnostics.append(
                {
                    "kb_id": kb_id,
                    "name": kb_id,
                    "status": "missing",
                    "chunks": 0,
                    "source": "",
                    "warnings": ["Knowledge base not found."],
                }
            )
            continue
        before_count = len(contexts)
        warnings: list[str] = []
        indexed_chunks = manager.list_indexed_chunks(kb_id, limit=max(limit * (neighbors_count + 1), limit * 3))
        context_source = "indexed_chunks" if indexed_chunks else "parsed_files"
        if indexed_chunks:
            contexts.extend(
                _contexts_from_chunks(
                    indexed_chunks,
                    kb_id=kb_id,
                    topic_terms=topic_terms,
                    limit=max(limit - len(contexts), 0),
                    neighbors_count=neighbors_count,
                )
            )
            if topic_terms and len(contexts) == before_count:
                warnings.append("Topic did not match available chunks; generated from general chunks instead.")
                contexts.extend(
                    _contexts_from_chunks(
                        indexed_chunks,
                        kb_id=kb_id,
                        topic_terms=set(),
                        limit=max(limit - len(contexts), 0),
                        neighbors_count=neighbors_count,
                    )
                )
        for file_meta in manager.list_files(kb_id):
            if len(contexts) >= limit:
                break
            if not file_meta.parsed_path:
                continue
            path = Path(file_meta.parsed_path)
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for index, chunk in enumerate(_split_context_text(text), start=1):
                if topic_terms and not topic_terms.intersection(_tokens(chunk)) and len(contexts) > before_count:
                    continue
                cleaned = _clean_generation_text(chunk)
                if len(cleaned) < 10:
                    continue
                contexts.append(
                    {
                        "content": cleaned,
                        "source": file_meta.filename,
                        "file_id": file_meta.file_id,
                        "chunk_id": f"{file_meta.file_id}:{index}",
                        "kb_id": kb_id,
                        "context_source": "parsed_file",
                    }
                )
                if len(contexts) >= limit:
                    break
        added = len(contexts) - before_count
        diagnostics.append(
            {
                "kb_id": kb_id,
                "name": kb.name,
                "status": "ready" if added else "empty",
                "chunks": added,
                "source": context_source if added else "",
                "kb_type": kb.kb_type.value,
                "warnings": warnings or ([] if added else ["No indexed or parsed chunks were available."]),
            }
        )
        if len(contexts) >= limit:
            break
    return contexts[:limit], diagnostics


def _contexts_from_chunks(
    chunks: list[dict[str, Any]],
    *,
    kb_id: str,
    topic_terms: set[str],
    limit: int,
    neighbors_count: int,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    if limit <= 0:
        return contexts
    for index, chunk in enumerate(chunks):
        content = _clean_generation_text(str(chunk.get("content") or ""))
        if len(content) < 10:
            continue
        if topic_terms and not topic_terms.intersection(_tokens(content)):
            continue
        neighbor_text = ""
        if neighbors_count:
            start = max(0, index - neighbors_count)
            end = min(len(chunks), index + neighbors_count + 1)
            neighbor_text = "\n\n".join(
                _clean_generation_text(str(item.get("content") or ""))
                for item in chunks[start:end]
                if item is not chunk and item.get("content")
            )
        contexts.append(
            {
                "content": f"{content}\n\n{neighbor_text}".strip()[:1800],
                "source": chunk.get("filename") or chunk.get("source") or "indexed_chunk",
                "file_id": str(chunk.get("file_id") or ""),
                "chunk_id": str(
                    chunk.get("chunk_id") or chunk.get("id") or f"{chunk.get('file_id')}:{chunk.get('chunk_index')}"
                ),
                "kb_id": kb_id,
                "context_source": chunk.get("source") or "indexed_chunk",
            }
        )
        if len(contexts) >= limit:
            break
    return contexts


def _clean_generation_text(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(
        r"\b(graph|flowchart|subgraph|direction\s+(TB|LR|RL|BT)|classDef|style)\b[^\n]*", " ", text, flags=re.I
    )
    text = re.sub(r"[A-Za-z0-9_]+\s*(-->|---|==>|-.->|:::) *[A-Za-z0-9_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1800]


def _question_seed(text: str, *, max_length: int = 28) -> str:
    text = re.sub(r"[#*_`>\[\]{}()<>|]+", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip(" ，。,.;；:")
    if not text:
        return "这个知识点"
    sentences = re.split(r"[。！？!?；;\n]", text)
    seed = next((item.strip() for item in sentences if len(item.strip()) >= 4), text)
    return seed[:max_length].strip() or "这个知识点"


def _collect_recent_log_contexts(*, limit: int) -> list[dict[str, Any]]:
    try:
        from nexagent.db.models import InvocationLog
        from nexagent.db.session import session_scope

        rows: list[InvocationLog] = []
        with session_scope() as session:
            query = session.query(InvocationLog).order_by(InvocationLog.created_at.desc()).limit(limit)
            rows = list(query)
        return [
            {
                "content": (
                    f"Query: {getattr(row, 'input_preview', '')}\n"
                    f"Response: {getattr(row, 'output_preview', '')}"
                ),
                "source": "recent_logs",
                "file_id": str(getattr(row, "id", "")),
                "chunk_id": str(getattr(row, "id", "")),
            }
            for row in rows
            if str(getattr(row, "input_preview", "") or getattr(row, "output_preview", "") or "").strip()
        ]
    except Exception:
        return []


def _split_context_text(text: str, *, chunk_size: int = 1200) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 > chunk_size and current:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    if not chunks and text.strip():
        chunks = [text.strip()[:chunk_size]]
    return chunks


async def _generate_with_llm(
    *,
    contexts: list[dict[str, Any]],
    count: int,
    eval_type: str,
    agent: str,
    model: str,
    kb_ids: list[str],
    tags: list[str],
    source: str,
    retrieval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not model or model in {"fake", "nexagent/fake", "test/fake"}:
        return []
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from nexagent.models.factory import load_chat_model

        context_text = "\n\n".join(
            f"片段ID={item['chunk_id']}\n来源={item['source']}\n{item['content'][:1200]}"
            for item in contexts[: min(len(contexts), count * 2)]
        )
        prompt = (
            f"请基于以下上下文生成 {count} 个 NexAgent 评估用例草稿。"
            "只返回 JSON 数组，每项包含 name、query、expected_answer、expected_sources、expected_tools、tags。"
            "expected_sources 应使用片段ID或来源文件名。\n\n"
            f"上下文：\n{context_text}"
        )
        context_text = "\n\n".join(
            f"Chunk ID={item['chunk_id']}\nSource={item['source']}\n{item['content'][:1200]}"
            for item in contexts[: min(len(contexts), count * 2)]
        )
        prompt = (
            f"Generate {count} NexAgent RAG evaluation samples from the context below. "
            "Return a valid JSON array only. Each item must include name, query, "
            "expected_answer, expected_sources, expected_tools, and tags. "
            "The query must be a natural user question, not a template such as "
            "'According to the material...'. Mix question styles: factual checks, "
            "why/how explanations, comparisons, step-by-step process questions, "
            "scenario application, and boundary-condition questions. The expected_answer must be "
            "short, factual, and grounded in the provided context. expected_sources "
            "must use the chunk ID or source file name.\n\n"
            f"Context:\n{context_text}"
        )
        llm = load_chat_model(model)
        response = await llm.ainvoke(
            [
                SystemMessage(content="You generate concise, objective eval test cases. Return valid JSON only."),
                HumanMessage(content=prompt),
            ]
        )
        parsed = _parse_json_array(str(response.content))
    except Exception as exc:
        logger.warning("AI eval generation failed, falling back to rule-based drafts: %s", exc)
        return []
    drafts: list[dict[str, Any]] = []
    for index, item in enumerate(parsed[:count], start=1):
        if not isinstance(item, dict):
            continue
        drafts.append(
            _draft_payload(
                name=str(item.get("name") or f"AI generated eval {index}"),
                query=str(item.get("query") or ""),
                expected_answer=str(item.get("expected_answer") or item.get("expected") or ""),
                expected_sources=_list_of_strings(item.get("expected_sources")),
                expected_tools=_list_of_strings(item.get("expected_tools")),
                eval_type=eval_type,
                agent=agent,
                model=model,
                kb_ids=kb_ids,
                tags=_list_of_strings(item.get("tags")) or tags,
                source=source,
                retrieval_config=retrieval_config,
            )
        )
    return [draft for draft in drafts if draft["query"]]


def _generate_rule_based_drafts(
    *,
    contexts: list[dict[str, Any]],
    count: int,
    eval_type: str,
    agent: str,
    model: str,
    kb_ids: list[str],
    tags: list[str],
    source: str,
    retrieval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    if not contexts:
        return drafts
    templates = [
        "如何判断{topic}是否符合资料中的描述？",
        "为什么{topic}会影响相关流程或结果？",
        "{topic}和资料中的其他要点有什么区别？",
        "在什么情况下应该重点关注{topic}？",
        "如果要落地{topic}，需要先确认哪些信息？",
        "{topic}的边界条件或限制是什么？",
    ]
    for index in range(1, count + 1):
        item = contexts[(index - 1) % len(contexts)]
        content = " ".join(str(item["content"]).split())
        preview = content[:180]
        source_name = str(item.get("source") or item.get("chunk_id") or "source")
        drafts.append(
            _draft_payload(
                name=f"生成用例 {index} - {source_name[:24]}",
                query=f"根据资料说明：{preview[:80]}",
                expected_answer=preview,
                expected_sources=[str(item.get("chunk_id") or source_name)],
                expected_tools=["knowledge_search"] if eval_type == "tool" else [],
                eval_type=eval_type,
                agent=agent,
                model=model,
                kb_ids=kb_ids,
                tags=tags,
                source=source,
                retrieval_config=retrieval_config,
            )
        )
    for index, draft in enumerate(drafts):
        draft["name"] = draft.get("name") or f"Generated sample {index + 1}"
        draft["query"] = templates[index % len(templates)].format(
            topic=_question_seed(str(draft.get("expected_answer") or draft.get("expected") or ""))
        )
    return drafts


def _draft_payload(
    *,
    name: str,
    query: str,
    expected_answer: str,
    expected_sources: list[str],
    expected_tools: list[str],
    eval_type: str,
    agent: str,
    model: str,
    kb_ids: list[str],
    tags: list[str],
    source: str,
    retrieval_config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": f"draft-{uuid.uuid4().hex[:10]}",
        "name": name,
        "type": eval_type,
        "query": query,
        "expected": expected_answer,
        "expected_answer": expected_answer,
        "expected_sources": expected_sources,
        "gold_chunk_ids": expected_sources,
        "expected_tools": expected_tools,
        "agent": agent,
        "model": model,
        "kb_ids": kb_ids,
        "tags": tags,
        "retrieval_config": retrieval_config,
        "generation_source": source,
        "generated_by_ai": True,
    }


def _parse_json_array(text: str) -> list[Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return []
    return parsed if isinstance(parsed, list) else []


async def _llm_judge(query: str, expected: str, actual: str, model: str | None) -> tuple[bool, str]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from nexagent.models.factory import load_chat_model

    judge_model = load_chat_model(model)
    prompt = (
        f"Question: {query}\n\n"
        f"Expected answer: {expected}\n\n"
        f"Actual answer: {actual}\n\n"
        "Does the actual answer correctly and completely address the question, "
        "consistent with the expected answer? "
        "Reply with exactly: PASS or FAIL, then a brief one-sentence reason."
    )
    try:
        resp = await judge_model.ainvoke(
            [
                SystemMessage(content="You are an impartial evaluator. Be strict but fair."),
                HumanMessage(content=prompt),
            ]
        )
        text = str(resp.content).strip()
        passed = text.upper().startswith("PASS")
        reason = text.split("\n", 1)[-1].strip() if "\n" in text else text
        return passed, reason
    except Exception as exc:
        logger.warning("LLM judge failed: %s", exc)
        return False, str(exc)
