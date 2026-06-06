"""LLM Wiki — crystallize a conversation thread into a structured wiki page.

Pipeline:
  1. Load the conversation's messages.
  2. Ask an LLM to distill them into a clean, reusable Markdown knowledge page
     (title, summary, key points, decisions, open questions, tags).
  3. Persist the page under the data dir (always available for browsing).
  4. Optionally push it into a knowledge base so it joins vector + graph search.

This mirrors a-yuxi's "对话沉淀 → Wiki" flow while reusing NexAgent's own model
factory and knowledge stack.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

WIKI_SYSTEM_PROMPT = """你是一名知识管理专家。请把下面的对话沉淀成一篇结构化、可复用的中文 Wiki 知识页面。

要求：
- 用 Markdown 输出，第一行必须是 `# 标题`（精炼、概括主题，不超过 30 字）。
- 包含这些小节（如无内容可省略）：## 摘要、## 关键要点、## 结论与决策、## 待办与未决问题、## 相关概念。
- 只保留有长期价值的事实、结论、方法与定义；剔除寒暄、口语和重复内容。
- 客观、第三人称、条理清晰；不要编造对话中不存在的信息。
- 结尾加一行：`标签: tag1, tag2, tag3`（3-6 个）。"""


def _wiki_dir() -> Path:
    path = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent")) / "wiki"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return _wiki_dir() / "index.json"


def _load_index() -> list[dict[str, Any]]:
    p = _index_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    _index_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


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


async def _push_to_kb(kb_id: str, title: str, markdown: str) -> dict[str, Any]:
    """Best-effort: add the page to a KB and trigger processing. Never raises."""
    result: dict[str, Any] = {"kb_id": kb_id, "file_id": None, "warning": None}
    try:
        from nexagent.knowledge.manager import get_manager

        manager = get_manager()
        safe = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", title).strip("_")[:60] or "wiki"
        meta = await manager.add_file(kb_id, f"{safe}.md", markdown.encode("utf-8"))
        file_id = getattr(meta, "id", None) or (meta.get("id") if isinstance(meta, dict) else None)
        result["file_id"] = file_id
        # Kick off parse + index in the background; ignore failures (infra may be down).
        try:
            await manager.parse_file(kb_id, file_id)
            await manager.index_file(kb_id, file_id)
        except Exception as exc:  # noqa: BLE001
            result["warning"] = f"已存入知识库，但解析/索引未完成：{exc}"
    except Exception as exc:  # noqa: BLE001
        result["warning"] = f"未能写入知识库（{kb_id}）：{exc}"
    return result


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

    messages = await list_messages(thread_id)
    transcript = _format_transcript(messages)
    if not transcript.strip():
        raise ValueError("该对话没有可沉淀的内容。")

    llm = await load_chat_model_async(model)
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
    page_id = uuid.uuid4().hex[:12]
    created_at = time.time()

    # Persist the markdown file + index entry.
    (_wiki_dir() / f"{page_id}.md").write_text(markdown, encoding="utf-8")
    entry: dict[str, Any] = {
        "id": page_id,
        "title": title,
        "tags": tags,
        "thread_id": thread_id,
        "kb_id": kb_id,
        "created_at": created_at,
        "char_count": len(markdown),
    }

    kb_result: dict[str, Any] | None = None
    if kb_id:
        kb_result = await _push_to_kb(kb_id, title, markdown)
        entry["file_id"] = kb_result.get("file_id")
        if kb_result.get("warning"):
            entry["warning"] = kb_result["warning"]

    index = _load_index()
    index.insert(0, entry)
    _save_index(index)

    return {**entry, "content": markdown}


def list_pages() -> list[dict[str, Any]]:
    return _load_index()


def get_page(page_id: str) -> dict[str, Any] | None:
    entry = next((item for item in _load_index() if item.get("id") == page_id), None)
    if not entry:
        return None
    md_path = _wiki_dir() / f"{page_id}.md"
    content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    return {**entry, "content": content}


def delete_page(page_id: str) -> bool:
    index = _load_index()
    remaining = [item for item in index if item.get("id") != page_id]
    if len(remaining) == len(index):
        return False
    _save_index(remaining)
    md_path = _wiki_dir() / f"{page_id}.md"
    if md_path.exists():
        md_path.unlink()
    return True
