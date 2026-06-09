"""Conversation-to-Wiki service.

Pipeline:
  1. Load the conversation's messages.
  2. Ask an LLM to distill them into a clean, reusable Markdown knowledge page
     (title, summary, key points, decisions, open questions, tags).
  3. Persist the page into the selected Wiki knowledge base so it joins the
     user-managed knowledge workflow.

This mirrors a-yuxi's "对话沉淀 → Wiki" flow while reusing NexAgent's own model
factory and knowledge stack.
"""

from __future__ import annotations

import re
from inspect import isawaitable
from typing import Any

WIKI_SYSTEM_PROMPT = """你是一名知识管理专家。请把下面的对话沉淀成一篇结构化、可复用的中文 Wiki 知识页面。

要求：
- 用 Markdown 输出，第一行必须是 `# 标题`（精炼、概括主题，不超过 30 字）。
- 包含这些小节（如无内容可省略）：## 摘要、## 关键要点、## 结论与决策、## 待办与未决问题、## 相关概念。
- 只保留有长期价值的事实、结论、方法与定义；剔除寒暄、口语和重复内容。
- 客观、第三人称、条理清晰；不要编造对话中不存在的信息。
- 结尾加一行：`标签: tag1, tag2, tag3`（3-6 个）。"""

CRYSTALLIZE_SOURCE_TYPE = "conversation_crystallize"


def _extract_title(markdown: str) -> str:
    for line in markdown.splitlines():
        m = re.match(r"^#\s+(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    return "未命名 Wiki 页面"


def _extract_tags(markdown: str) -> list[str]:
    m = re.search(r"标签[:：]\s*(.+)$", markdown, re.MULTILINE)
    if not m:
        return []
    raw = m.group(1).strip().lstrip("#").strip()
    parts = re.split(r"[,，、;；/|]+|#+|\s{2,}", raw)
    return [t.strip().strip("#").strip() for t in parts if t.strip().strip("#").strip()][:8]


def _format_transcript(messages: list[dict[str, Any]]) -> str:
    role_label = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
    lines: list[str] = []
    for msg in messages:
        role = role_label.get(str(msg.get("role", "")), str(msg.get("role", "")))
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}：{content}")
    return "\n\n".join(lines)


async def _maybe_await(value):
    if isawaitable(value):
        return await value
    return value


async def _crystallize_into_wiki_kb(kb_id: str, title: str, markdown: str, *, thread_id: str) -> dict[str, Any]:
    from nexagent.knowledge.manager import get_manager

    manager = get_manager()
    kb = manager.get_kb(kb_id)
    if kb is None:
        raise ValueError(f"知识库 {kb_id} 不存在。")
    if getattr(kb.kb_type, "value", kb.kb_type) != "wiki":
        raise ValueError(f"知识库 {kb_id} 不是 Wiki 类型。")
    backend = manager._find_backend(kb_id)
    source = await backend.add_file(
        kb_id,
        f"{title}.md",
        markdown.encode("utf-8"),
        processing_params={
            "source_type": CRYSTALLIZE_SOURCE_TYPE,
            "source_thread_id": thread_id,
            "crystallized_title": title,
            "crystallized_page_type": "note",
        },
    )
    file_id = source.file_id
    warning = ""
    try:
        await backend.parse_file(kb_id, file_id)
        await backend.index_file(kb_id, file_id)
    except Exception as exc:  # noqa: BLE001
        warning = f"页面已创建，但素材解析/编译未完成：{exc}"
    page = await backend.crystallize_wiki_text(
        kb_id,
        title=title,
        content=markdown,
        page_type="note",
        sources=[file_id],
        confidence="UNVERIFIED",
    )
    return {**page, "kb_id": kb_id, "file_id": file_id, "warning": warning or None, "content": markdown}


async def crystallize_thread(
    thread_id: str,
    *,
    kb_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Distill a conversation thread into a wiki page and persist it."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from nexagent.models.factory import load_chat_model_async
    from nexagent.services.conversation_service import list_messages

    if not kb_id:
        raise ValueError("请选择目标 Wiki 知识库后再沉淀。")

    messages = await list_messages(thread_id)
    transcript = _format_transcript(messages)
    if not transcript.strip():
        raise ValueError("该对话没有可沉淀的内容。")

    llm = await _maybe_await(load_chat_model_async(model or _model_ref_for_wiki_kb(kb_id)))
    response = await llm.ainvoke(
        [
            SystemMessage(content=WIKI_SYSTEM_PROMPT),
            HumanMessage(content=f"以下是需要沉淀的对话记录：\n\n{transcript}"),
        ]
    )
    markdown = response.content if isinstance(response.content, str) else str(response.content)
    markdown = markdown.strip()

    title = _extract_title(markdown)
    tags = _extract_tags(markdown)

    page = await _crystallize_into_wiki_kb(kb_id, title, markdown, thread_id=thread_id)
    return {**page, "tags": tags, "thread_id": thread_id, "char_count": len(markdown)}


def _model_ref_for_wiki_kb(kb_id: str) -> str | None:
    from nexagent.knowledge.manager import get_manager

    kb = get_manager().get_kb(kb_id)
    if kb is None:
        raise ValueError(f"知识库 {kb_id} 不存在。")
    if getattr(kb.kb_type, "value", kb.kb_type) != "wiki":
        raise ValueError(f"知识库 {kb_id} 不是 Wiki 类型。")
    llm = kb.llm_info
    if not llm.model:
        return None
    if llm.provider and "::" not in llm.model:
        return f"{llm.provider}::{llm.model}"
    return llm.model
