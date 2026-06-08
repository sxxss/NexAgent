from __future__ import annotations

import json
import re
import textwrap
from hashlib import sha256
from pathlib import Path
from typing import Any

from nexagent.knowledge.implementations.wiki.constants import CONFIDENCE_VALUES, WIKI_PROMPT_VERSION


class WikiCompileMixin:
    async def _compile_markdown_file(
        self,
        kb_id: str,
        file_id: str,
        file_meta,
        markdown: str,
    ) -> list[dict]:
        compiled = await self._compile_markdown_with_llm(kb_id, file_id, file_meta, markdown)
        source = compiled.get("source") or {}
        title = self._clean_wiki_title(source.get("title") or Path(file_meta.filename).stem or file_id)
        pages = [
            await self.create_or_update_wiki_page(
                kb_id,
                page_type="source",
                title=title,
                content=self._source_page_content(file_meta.filename, markdown, source),
                sources=[file_id],
                confidence=self._normalize_confidence(source.get("confidence"), "EXTRACTED"),
            )
        ]
        for item in self._clean_page_items(compiled.get("topics"), "topics")[:8]:
            pages.append(
                await self.create_or_update_wiki_page(
                    kb_id,
                    page_type="topic",
                    title=item["title"],
                    content=self._page_content_from_llm(
                        item["title"],
                        item.get("summary"),
                        item.get("content"),
                        title,
                    ),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        for item in self._clean_page_items(compiled.get("entities"), "entities")[:12]:
            pages.append(
                await self.create_or_update_wiki_page(
                    kb_id,
                    page_type="entity",
                    title=item["title"],
                    content=self._page_content_from_llm(
                        item["title"],
                        item.get("summary"),
                        item.get("content"),
                        title,
                    ),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        cache = self._load_cache(kb_id)
        cache[file_id] = {
            "filename": file_meta.filename,
            "content_hash": self._content_hash(markdown),
            "prompt_version": WIKI_PROMPT_VERSION,
            "status": "compiled",
            "page_ids": [page["id"] for page in pages],
        }
        self._save_cache(kb_id, cache)
        return pages

    async def _compile_markdown_with_llm(self, kb_id: str, file_id: str, file_meta, markdown: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        from nexagent.models.factory import load_chat_model_async

        kb_meta = self._require_kb(kb_id)
        llm_info = kb_meta.llm_info
        model_ref = llm_info.model
        if llm_info.provider and "::" not in model_ref:
            model_ref = f"{llm_info.provider}::{llm_info.model}"
        try:
            llm = await load_chat_model_async(model_ref)
        except Exception:
            llm = await load_chat_model_async(llm_info.model)
        messages = self._build_compile_prompt(file_meta.filename, self._read_purpose(kb_id), markdown)
        response = await llm.ainvoke(
            [
                SystemMessage(content=messages[0]["content"]),
                HumanMessage(content=messages[1]["content"]),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            parsed = self._parse_llm_json(content)
            self._validate_compiled_payload(parsed)
            return parsed
        except ValueError as exc:
            repair_prompt = self._build_repair_prompt(content, str(exc))
            repaired_response = await llm.ainvoke(
                [
                    SystemMessage(content=repair_prompt[0]["content"]),
                    HumanMessage(content=repair_prompt[1]["content"]),
                ]
            )
            repaired_content = (
                repaired_response.content
                if isinstance(repaired_response.content, str)
                else str(repaired_response.content)
            )
            repaired = self._parse_llm_json(repaired_content)
            self._validate_compiled_payload(repaired)
            return repaired

    def _read_purpose(self, kb_id: str) -> str:
        path = self._db_root(kb_id) / "purpose.md"
        return path.read_text(encoding="utf-8")[:2000] if path.exists() else ""

    def _build_compile_prompt(self, filename: str, purpose: str, markdown: str) -> list[dict]:
        source_text = markdown[:12000]
        system_prompt = "你是 NexAgent 的 LLM Wiki 编译器。只输出合法 JSON，不要输出 Markdown 代码块或解释。"
        user_prompt = textwrap.dedent(
            f"""
            Wiki purpose:
            {purpose or "未设置"}
            Source filename:
            {filename}
            请返回 JSON 对象，结构为 source/topics/entities/synthesis。topics 和 entities 可以为空数组。
            confidence 只能是 EXTRACTED、INFERRED、AMBIGUOUS、UNVERIFIED。
            页面正文必须使用 Markdown，可用 [[页面标题]] 表达重要关联。
            Markdown source:
            {source_text}
            """
        ).strip()
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    def _build_repair_prompt(self, bad_output: str, error: str) -> list[dict]:
        return [
            {"role": "system", "content": "你是 NexAgent Wiki JSON 修复器。只输出合法 JSON。"},
            {
                "role": "user",
                "content": f"错误：{error}\n请修复为 source/topics/entities/synthesis JSON：\n{bad_output}",
            },
        ]

    def _parse_llm_json(self, content: str) -> dict:
        raw = (content or "").strip()
        if raw.startswith("```"):
            match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("LLM Wiki compile result must be a JSON object")
        return parsed

    def _validate_compiled_payload(self, payload: dict) -> None:
        if not isinstance(payload.get("source"), dict):
            raise ValueError("LLM Wiki compile result is missing source")
        if not str(payload["source"].get("title") or "").strip():
            raise ValueError("LLM Wiki source.title is empty")
        for section in ("topics", "entities"):
            if payload.get(section) is not None and not isinstance(payload.get(section), list):
                raise ValueError(f"LLM Wiki {section} must be a list")

    def _clean_page_items(self, items: Any, label: str) -> list[dict]:
        cleaned: list[dict] = []
        if not isinstance(items, list):
            return cleaned
        for item in items:
            if not isinstance(item, dict):
                continue
            title = self._clean_wiki_title(item.get("title"))
            body = str(item.get("content") or item.get("summary") or "").strip()
            if title and body:
                cleaned.append({**item, "title": title})
        return cleaned

    def _normalize_confidence(self, value: Any, default: str) -> str:
        confidence = str(value or default).strip().upper()
        return confidence if confidence in CONFIDENCE_VALUES else default

    def _source_page_content(self, filename: str, markdown: str, source: dict) -> str:
        title = self._clean_wiki_title(source.get("title") or Path(filename).stem)
        summary = str(source.get("summary") or "").strip()
        key_points = source.get("key_points") if isinstance(source.get("key_points"), list) else []
        bullets = "\n".join(f"- {item}" for item in key_points if str(item).strip()) or "- No extracted items."
        return (
            f"# {title}\n\n"
            f"Source file: `{filename}`\n\n"
            f"## Summary\n\n{summary or self._summarize(markdown)}\n\n"
            f"## Key Points\n\n{bullets}"
        )

    def _page_content_from_llm(self, title: str, summary: Any, content: Any, source_title: str) -> str:
        sections = [f"# {title}"]
        if str(summary or "").strip():
            sections.extend(["", "## Summary", "", str(summary).strip()])
        sections.extend(["", "## Notes", "", str(content or "").strip() or "No detailed content generated."])
        sections.extend(["", "## Sources", "", f"- [[{source_title}]]"])
        return "\n".join(sections)

    def _summarize(self, markdown: str) -> str:
        text = re.sub(r"\s+", " ", re.sub(r"^#+\s+", "", markdown, flags=re.MULTILINE)).strip()
        return text[:800] or "No textual content extracted."

    def _content_hash(self, markdown: str) -> str:
        return sha256((markdown or "").encode("utf-8")).hexdigest()
