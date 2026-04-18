"""Knowledge base search tool backed by structured_retrieve."""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

VALID_TOOL_MODES = {
    "vector",
    "keyword",
    "hybrid",
    "lightrag_local",
    "lightrag_global",
    "lightrag_hybrid",
}


def get_knowledge_search_tool(kb_ids: list[str] | None = None):
    """Return a knowledge base search tool scoped to given KB IDs, or all KBs."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def knowledge_search(query: str, top_k: int = 5, mode: str = "hybrid") -> str:
        """Search uploaded knowledge bases and return cited evidence passages."""

        try:
            from nexagent.knowledge.manager import get_manager
            from nexagent.knowledge.search_service import structured_retrieve

            normalized_mode = str(mode or "hybrid").lower()
            if normalized_mode == "bm25":
                normalized_mode = "keyword"
            if normalized_mode not in VALID_TOOL_MODES:
                return (
                    f"Knowledge base search failed: unsupported mode '{mode}'. "
                    "Use vector, keyword, hybrid, lightrag_local, lightrag_global, or lightrag_hybrid."
                )

            mgr = get_manager()
            ids_to_search = target_kb_ids or [kb.kb_id for kb in mgr.list_kbs()]
            if not ids_to_search:
                return "No knowledge bases available. Please upload and index documents first."

            top_k = min(max(1, int(top_k or 5)), 10)
            result = await structured_retrieve(
                query=query,
                kb_ids=ids_to_search,
                mode=normalized_mode,
                top_k=top_k,
            )
            return _format_tool_result(query=query, result=result, top_k=top_k)
        except Exception as exc:
            logger.error("knowledge_search tool error: %s", exc)
            return f"Knowledge base search failed: {exc}"

    return knowledge_search


def _format_tool_result(*, query: str, result, top_k: int) -> str:
    chunks = list(result.chunks or [])[:top_k]
    warnings = result.warning_dicts()
    if result.error_code and not chunks:
        return _format_error(query=query, error_code=result.error_code, error=result.error, warnings=warnings)
    if not chunks:
        suffix = _format_warnings(warnings)
        return f"No relevant results found in the knowledge base.{suffix}"

    rows: list[dict] = []
    lines = [f"Found {len(chunks)} relevant passages:"]
    for index, chunk in enumerate(chunks, 1):
        evidence = chunk.evidence(index)
        metadata = evidence.get("metadata") or {}
        evidence["chunk_id"] = metadata.get("chunk_id") or evidence.get("id")
        evidence["chunk_index"] = metadata.get("chunk_index")
        rows.append(
            {
                "evidence": evidence,
                "kb_id": chunk.kb_id,
                "source": chunk.source or metadata.get("source") or "unknown",
                "file_id": chunk.file_id,
                "chunk_id": evidence.get("chunk_id"),
                "score": round(float(chunk.score or 0.0), 4),
                "content": chunk.content,
            }
        )
        lines.append(
            f"[{evidence['id']}] Source: {rows[-1]['source']} "
            f"file_id={rows[-1]['file_id'] or '-'} chunk_id={rows[-1]['chunk_id'] or '-'} "
            f"(score: {rows[-1]['score']:.3f})\n{chunk.content}"
        )
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"- {item.get('code')}: {item.get('message')}" for item in warnings)
    lines.extend(
        [
            "```nexagent-evidence",
            json.dumps([row["evidence"] for row in rows], ensure_ascii=False),
            "```",
            "Use evidence ids like [E1] when citing knowledge-base facts in the final answer.",
        ]
    )
    return "\n\n".join(lines)


def _format_error(*, query: str, error_code: str, error: str, warnings: list[dict]) -> str:
    payload = {
        "query": query,
        "error_code": error_code,
        "error": error,
        "warnings": warnings,
    }
    return "Knowledge base search failed:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def _format_warnings(warnings: list[dict]) -> str:
    if not warnings:
        return ""
    return "\nWarnings:\n" + "\n".join(f"- {item.get('code')}: {item.get('message')}" for item in warnings)
