"""Read-only tools for LLM Wiki knowledge bases."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from pathlib import Path
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


def get_compile_wiki_tool(kb_ids: list[str] | None = None):
    """Return a write tool that compiles uploaded Wiki source files."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def compile_wiki(
        kb_id: str,
        file_ids: list[str] | None = None,
        force: bool = False,
        retry_failed: bool = False,
        confirmed: bool = False,
    ) -> str:
        """Compile an enabled LLM Wiki knowledge base after explicit user confirmation."""

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            normalized_file_ids = _clean_list(file_ids)
            if not confirmed:
                scope = f"指定 {len(normalized_file_ids)} 个文件" if normalized_file_ids else "所有待处理文件"
                return (
                    f"需要用户确认：将编译 Wiki 知识库 '{target.kb_name}' 的{scope}"
                    f"（force={bool(force)}, retry_failed={bool(retry_failed)}）。"
                    "确认后请再次调用并设置 confirmed=true。"
                )
            result = await target.backend.compile_wiki(
                target.kb_id,
                file_ids=normalized_file_ids or None,
                force=bool(force),
                retry_failed=bool(retry_failed),
            )
            return _json_payload(result)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("compile_wiki tool error: %s", exc)
            return f"Compile Wiki failed: {exc}"

    return compile_wiki


def get_crystallize_wiki_tool(kb_ids: list[str] | None = None):
    """Return a write tool that distills explicit text into a Wiki page."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def crystallize_wiki(
        kb_id: str,
        title: str,
        content: str,
        page_type: str = "note",
        confidence: str = "UNVERIFIED",
        sources: list[str] | None = None,
        confirmed: bool = False,
    ) -> str:
        """Create or update a Wiki page from explicit markdown text after confirmation."""

        title_text = str(title or "").strip()
        content_text = str(content or "").strip()
        if not title_text or not content_text:
            return "标题和内容不能为空。"
        normalized_type = str(page_type or "note").strip().lower()
        if normalized_type not in {"source", "topic", "entity", "synthesis", "note"}:
            return "page_type 只支持 source、topic、entity、synthesis、note。"
        normalized_confidence = str(confidence or "UNVERIFIED").strip().upper()
        if normalized_confidence not in {"UNVERIFIED", "EXTRACTED", "INFERRED", "AMBIGUOUS"}:
            return "confidence 只支持 UNVERIFIED、EXTRACTED、INFERRED、AMBIGUOUS。"

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            normalized_sources = _clean_list(sources)
            if not confirmed:
                return (
                    f"需要用户确认：将在 Wiki 知识库 '{target.kb_name}' 中创建或更新 "
                    f"{normalized_type} 页面 '{title_text}'。确认后请再次调用并设置 confirmed=true。"
                )
            page = await target.backend.crystallize_wiki_text(
                target.kb_id,
                title=title_text,
                content=content_text,
                page_type=normalized_type,
                sources=normalized_sources,
                confidence=normalized_confidence,
            )
            return f"已沉淀 Wiki 页面 '{page.get('title') or title_text}'。\n{_json_payload(page)}"
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("crystallize_wiki tool error: %s", exc)
            return f"Crystallize Wiki failed: {exc}"

    return crystallize_wiki


def get_crystallize_attachments_to_wiki_tool(kb_ids: list[str] | None = None):
    """Return a write tool that registers thread files as Wiki source materials."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def crystallize_attachments_to_wiki(
        kb_id: str,
        thread_id: str,
        paths: list[str] | None = None,
        filenames: list[str] | None = None,
        compile_after: bool = True,
        confirmed: bool = False,
    ) -> str:
        """Register conversation upload/output files as Wiki materials after confirmation.

        Use this for PDF/DOCX/XLSX/images or other attachments that should keep their original
        file format. Do not read the file text and call crystallize_wiki for attachment ingestion.
        `paths` accepts /mnt/user-data/uploads/... or /mnt/user-data/outputs/... virtual paths.
        `filenames` may be used for exact filenames inside the current thread uploads/outputs.
        """

        thread_id_text = str(thread_id or "").strip()
        requested = _clean_list(paths) + _clean_list(filenames)
        if not thread_id_text:
            return "thread_id 不能为空。"
        if not requested:
            return "请提供 paths 或 filenames。"

        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            if not confirmed:
                return (
                    f"需要用户确认：将把 {len(requested)} 个对话附件/产物登记到 Wiki 知识库 "
                    f"'{target.kb_name}' 作为素材"
                    f"{'，并立即编译' if compile_after else ''}。"
                    "确认后请再次调用并设置 confirmed=true。"
                )

            registered: list[dict[str, Any]] = []
            failed: list[dict[str, str]] = []
            for requested_path in requested:
                try:
                    real_path, virtual_path = _resolve_thread_file(thread_id_text, requested_path)
                    file_meta = await target.backend.add_file(
                        target.kb_id,
                        real_path.name,
                        real_path.read_bytes(),
                        processing_params={
                            "source_type": "conversation_attachment",
                            "source_thread_id": thread_id_text,
                            "source_virtual_path": virtual_path,
                            "source_filename": real_path.name,
                        },
                    )
                    file_id = str(getattr(file_meta, "file_id", "") or "")
                    item: dict[str, Any] = {
                        "path": virtual_path,
                        "filename": real_path.name,
                        "file_id": file_id,
                        "status": "uploaded",
                    }
                    if compile_after and file_id:
                        await target.backend.parse_file(target.kb_id, file_id)
                        await target.backend.index_file(target.kb_id, file_id)
                        item["status"] = "compiled"
                    registered.append(item)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"path": str(requested_path), "error": str(exc)})

            return _json_payload({
                "message": "Wiki 附件素材登记完成",
                "kb_id": target.kb_id,
                "registered": registered,
                "failed": failed,
            })
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("crystallize_attachments_to_wiki tool error: %s", exc)
            return f"Crystallize attachments to Wiki failed: {exc}"

    return crystallize_attachments_to_wiki


def get_handle_wiki_candidate_tool(kb_ids: list[str] | None = None):
    """Return a write tool that accepts or discards generated Wiki candidates."""

    target_kb_ids = list(kb_ids or [])

    @tool
    async def handle_wiki_candidate(
        kb_id: str,
        page_id: str,
        action: str,
        confirmed: bool = False,
    ) -> str:
        """Accept or discard a generated Wiki candidate after explicit confirmation."""

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"accept", "discard"}:
            return "action 只支持 accept 或 discard。"
        try:
            target = _resolve_wiki_target(kb_id, target_kb_ids)
            page_id_text = str(page_id or "").strip()
            if not page_id_text:
                return "page_id 不能为空。"
            if not confirmed:
                return (
                    f"需要用户确认：将对 Wiki 知识库 '{target.kb_name}' 的页面 "
                    f"'{page_id_text}' 执行 {normalized_action} 候选版本操作。"
                    "确认后请再次调用并设置 confirmed=true。"
                )
            if normalized_action == "accept":
                page = await target.backend.accept_generated_wiki_page(target.kb_id, page_id_text)
            else:
                page = await target.backend.discard_generated_wiki_page(target.kb_id, page_id_text)
            return _json_payload(page)
        except _WikiToolError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("handle_wiki_candidate tool error: %s", exc)
            return f"Handle Wiki candidate failed: {exc}"

    return handle_wiki_candidate


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


def _resolve_thread_file(thread_id: str, path_or_filename: str) -> tuple[Path, str]:
    from nexagent.config import get_config
    from nexagent.sandbox.sandbox import VirtualPathTranslator

    requested = str(path_or_filename or "").strip()
    if not requested:
        raise ValueError("文件路径不能为空。")
    translator = VirtualPathTranslator(get_config().sandbox.base_dir)
    translator.ensure_thread_dirs(thread_id)
    allowed_roots = [
        translator.to_real(VirtualPathTranslator.UPLOADS, thread_id),
        translator.to_real(VirtualPathTranslator.OUTPUTS, thread_id),
    ]

    if requested.startswith("/"):
        real_path = translator.to_real(requested, thread_id)
        if not _inside_any(real_path, allowed_roots):
            raise ValueError("只允许导入当前线程 uploads/outputs 下的文件。")
        if not real_path.is_file():
            raise FileNotFoundError(requested)
        return real_path, translator.to_virtual(real_path, thread_id)

    matches: list[Path] = []
    for root in allowed_roots:
        if not root.exists():
            continue
        direct = (root / requested).resolve()
        if _inside_any(direct, [root]) and direct.is_file():
            matches.append(direct)
        matches.extend(path for path in root.rglob("*") if path.is_file() and path.name == requested)
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in matches:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    if not unique:
        raise FileNotFoundError(requested)
    if len(unique) > 1:
        raise ValueError(f"文件名 {requested} 匹配到多个文件，请传入完整虚拟路径。")
    return unique[0], translator.to_virtual(unique[0], thread_id)


def _inside_any(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        base = root.resolve()
        if resolved == base or base in resolved.parents:
            return True
    return False


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


def _clean_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _json_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


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
