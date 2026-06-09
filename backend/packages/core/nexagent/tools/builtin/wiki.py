"""Read-only tools for LLM Wiki knowledge bases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


class _WikiToolError(Exception):
    """User-facing Wiki tool failure."""


@dataclass(frozen=True)
class _WikiTarget:
    kb_id: str
    kb_name: str
    backend: Any


def get_list_wiki_pages_tool(kb_ids: list[str] | None = None):
    """Return a tool that lists Wiki pages in a scoped Wiki knowledge base."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def list_wiki_pages(
        kb_id: str,
        type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        source_file_id: str | None = None,
    ) -> str:
        """List pages in an enabled LLM Wiki knowledge base with optional filters."""

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            pages = target.backend.list_wiki_pages(
                target.kb_id,
                page_type=_clean_optional(type),
                q=_clean_optional(q),
                status=_clean_optional(status),
                source_file_id=_clean_optional(source_file_id),
            ).get("pages", [])
            return _format_page_list(target, pages)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("list_wiki_pages tool error: %s", exc)
            return f"List Wiki pages failed: {exc}"

    return list_wiki_pages


def get_read_wiki_page_tool(kb_ids: list[str] | None = None):
    """Return a tool that reads a Wiki page body and metadata."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def read_wiki_page(kb_id: str, page_id: str) -> str:
        """Read a page from an enabled LLM Wiki knowledge base."""

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            page = target.backend.get_wiki_page(target.kb_id, page_id)
            return _format_page_detail(page)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("read_wiki_page tool error: %s", exc)
            return f"Read Wiki page failed: {exc}"

    return read_wiki_page


def get_wiki_lint_tool(kb_ids: list[str] | None = None):
    """Return a tool that reports Wiki health issues."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def wiki_lint(kb_id: str) -> str:
        """Inspect health issues for an enabled LLM Wiki knowledge base."""

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            lint = target.backend.lint_wiki(target.kb_id)
            return _format_lint(target, lint)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("wiki_lint tool error: %s", exc)
            return f"Wiki lint failed: {exc}"

    return wiki_lint


def get_wiki_graph_tool(kb_ids: list[str] | None = None):
    """Return a tool that summarizes the Wiki relationship graph."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def get_wiki_graph(kb_id: str, q: str | None = None, max_edges: int = 80) -> str:
        """Read a relationship graph summary for an enabled LLM Wiki knowledge base."""

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            edge_limit = min(max(1, int(max_edges or 80)), 200)
            graph = target.backend.get_wiki_graph(
                target.kb_id,
                max_edges=edge_limit,
                include_weak=False,
                q=_clean_optional(q),
            )
            return _format_graph(target, graph, edge_limit=edge_limit)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("get_wiki_graph tool error: %s", exc)
            return f"Get Wiki graph failed: {exc}"

    return get_wiki_graph


def _resolve_wiki_target(kb_id: str, allowed_kb_ids: list[str]) -> _WikiTarget:
    normalized_kb_id = str(kb_id or "").strip()
    if not normalized_kb_id and len(allowed_kb_ids) == 1:
        normalized_kb_id = allowed_kb_ids[0]
    if not normalized_kb_id:
        raise _WikiToolError("Wiki knowledge base id is required.")
    if allowed_kb_ids and normalized_kb_id not in allowed_kb_ids:
        raise _WikiToolError(f"Wiki knowledge base '{normalized_kb_id}' is not available in this run.")

    from nexagent.knowledge.manager import get_manager

    mgr = get_manager()
    backend = _find_backend(mgr, normalized_kb_id)
    kb = _get_kb(mgr, backend, normalized_kb_id)
    if kb is None:
        raise _WikiToolError(f"Wiki knowledge base '{normalized_kb_id}' was not found.")
    if _kb_type(kb) != "wiki":
        raise _WikiToolError(f"Knowledge base '{normalized_kb_id}' is not an LLM Wiki knowledge base.")
    if backend is None:
        backend = _find_backend(mgr, normalized_kb_id, raise_on_missing=True)
    if backend is None:
        raise _WikiToolError(f"Wiki backend for '{normalized_kb_id}' was not found.")
    return _WikiTarget(
        kb_id=normalized_kb_id,
        kb_name=str(getattr(kb, "name", "") or normalized_kb_id),
        backend=backend,
    )


def _find_backend(mgr: Any, kb_id: str, *, raise_on_missing: bool = False) -> Any | None:
    finder = getattr(mgr, "_find_backend", None)
    if not callable(finder):
        return None
    try:
        return finder(kb_id, raise_on_missing=raise_on_missing)
    except TypeError:
        try:
            return finder(kb_id)
        except Exception:
            if raise_on_missing:
                raise
            return None
    except Exception:
        if raise_on_missing:
            raise
        return None


def _get_kb(mgr: Any, backend: Any | None, kb_id: str) -> Any | None:
    if backend is not None:
        getter = getattr(backend, "get_kb", None)
        if callable(getter):
            kb = getter(kb_id)
            if kb is not None:
                return kb
    getter = getattr(mgr, "get_kb", None)
    if callable(getter):
        return getter(kb_id)
    return None


def _kb_type(kb: Any) -> str:
    value = getattr(kb, "kb_type", "")
    return str(getattr(value, "value", value) or "").lower()


def _clean_optional(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _format_page_list(target: _WikiTarget, pages: list[dict]) -> str:
    if not pages:
        return f"Wiki 知识库 '{target.kb_name}' 没有匹配页面。"
    lines = [f"Wiki 页面列表：{target.kb_name} ({target.kb_id})", f"共 {len(pages)} 页"]
    for page in pages[:80]:
        frontmatter = page.get("frontmatter") or {}
        confidence = page.get("confidence") or frontmatter.get("confidence") or "UNVERIFIED"
        candidate = " | candidate" if page.get("has_candidate") else ""
        lines.append(
            "- "
            f"{page.get('id') or '-'} | "
            f"{page.get('title') or '-'} | "
            f"{page.get('type') or frontmatter.get('type') or 'unknown'} | "
            f"{page.get('status') or 'generated'} | "
            f"{confidence}{candidate}"
        )
    if len(pages) > 80:
        lines.append(f"... 还有 {len(pages) - 80} 页未显示，请使用 q/type/status 过滤。")
    return "\n".join(lines)


def _format_page_detail(page: dict) -> str:
    frontmatter = page.get("frontmatter") or {}
    sources = frontmatter.get("sources") or page.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    lines = [
        f"# {page.get('title') or page.get('id') or 'Untitled'}",
        "",
        f"- 页面 ID：{page.get('id') or '-'}",
        f"- 类型：{page.get('type') or frontmatter.get('type') or 'unknown'}",
        f"- 路径：{page.get('path') or '未知'}",
        f"- 置信度：{page.get('confidence') or frontmatter.get('confidence') or 'UNVERIFIED'}",
        f"- 来源：{'、'.join(str(source) for source in sources) or '无'}",
        f"- 候选版本：{'有' if page.get('candidate') else '无'}",
    ]
    updated_at = page.get("updated_at") or frontmatter.get("updated_at")
    if updated_at:
        lines.append(f"- 更新时间：{updated_at}")
    lines.extend(["", page.get("content") or ""])
    return "\n".join(lines).strip()


def _format_lint(target: _WikiTarget, lint: dict) -> str:
    summary = lint.get("summary") or {}
    issues = lint.get("issues") or []
    compile_status = (lint.get("compile_status") or {}).get("status") or "idle"
    lines = [
        f"Wiki 健康检查：{target.kb_name} ({target.kb_id})",
        f"问题：{summary.get('issue_count', len(issues))}，页面：{summary.get('page_count', 0)}，编译状态：{compile_status}",
    ]
    if not issues:
        lines.append("未发现问题。")
        return "\n".join(lines)

    for severity in ("error", "warning", "info"):
        bucket = [issue for issue in issues if str(issue.get("severity") or "info") == severity]
        if not bucket:
            continue
        lines.append(f"\n## {severity}")
        for issue in bucket[:40]:
            target_value = issue.get("target") or issue.get("source_file_id") or ""
            lines.append(
                "- "
                f"{issue.get('type') or 'issue'} | "
                f"{issue.get('page_id') or '-'} | "
                f"{issue.get('message') or ''} | "
                f"action={issue.get('action') or 'review'} | "
                f"repair={issue.get('repair_action') or 'review'}"
                f"{f' | target={target_value}' if target_value else ''}"
            )
        if len(bucket) > 40:
            lines.append(f"... {severity} 还有 {len(bucket) - 40} 个问题未显示。")
    return "\n".join(lines)


def _format_graph(target: _WikiTarget, graph: dict, *, edge_limit: int) -> str:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    stats = graph.get("stats") or {}
    type_counts: dict[str, int] = {}
    for node in nodes:
        node_type = str(node.get("type") or "unknown")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    lines = [
        f"Wiki 图谱：{target.kb_name} ({target.kb_id})",
        (
            f"节点：{stats.get('total_nodes', len(nodes))}，关系：{stats.get('total_edges', len(edges))}，"
            f"原始边：{stats.get('raw_edge_count', len(edges))}，社区：{stats.get('communities', 0)}"
        ),
    ]
    if type_counts:
        lines.append("页面类型：" + "、".join(f"{key}={value}" for key, value in sorted(type_counts.items())))

    lines.append("\n核心节点：")
    for node in nodes[:20]:
        lines.append(
            "- "
            f"{node.get('id') or '-'} | "
            f"{node.get('label') or node.get('title') or '-'} | "
            f"{node.get('type') or 'unknown'} | "
            f"community={node.get('community', 0)}"
        )
    if len(nodes) > 20:
        lines.append(f"... 还有 {len(nodes) - 20} 个节点未显示。")

    lines.append("\n核心关系：")
    for edge in edges[:edge_limit]:
        signals = _active_signals(edge.get("signals") or {})
        lines.append(
            "- "
            f"{edge.get('source') or '-'} -> {edge.get('target') or '-'} | "
            f"weight={edge.get('weight', 0)} | "
            f"signals={', '.join(signals) or 'none'}"
        )
    if not edges:
        lines.append("- 暂无关系；可能尚未编译页面，或关键词过滤过窄。")
    return "\n".join(lines)


def _active_signals(signals: dict) -> list[str]:
    active: list[str] = []
    for key, value in signals.items():
        if value:
            active.append(str(key))
    return active
