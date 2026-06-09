from __future__ import annotations

import asyncio
import json
import os
import re
import textwrap
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from nexagent.knowledge.implementations.wiki.constants import (
    CONFIDENCE_VALUES,
    NOISE_WIKILINKS,
    WIKI_PROMPT_VERSION,
)

DEFAULT_WIKI_LLM_TIMEOUT_S = 90.0


class WikiCompileMixin:
    async def _compile_markdown_file(
        self,
        kb_id: str,
        file_id: str,
        file_meta,
        markdown: str,
    ) -> list[dict]:
        try:
            compiled = await self._compile_markdown_with_llm(kb_id, file_id, file_meta, markdown)
        except TimeoutError as exc:
            compiled = self._local_compiled_payload(file_meta, markdown, str(exc))
        source = compiled.get("source") or {}
        title = self._clean_wiki_title(source.get("title") or Path(file_meta.filename).stem or file_id)
        topics = self._clean_page_items(compiled.get("topics"), "topics")[:8]
        entities = self._clean_page_items(compiled.get("entities"), "entities")[:12]
        source_title_aliases = self._source_title_aliases(file_meta.filename, title)
        entities.extend(
            self._fallback_link_entities(markdown, title, topics, entities, source_title_aliases)
        )
        planned_titles = [title]
        planned_titles.extend(item["title"] for item in topics)
        planned_titles.extend(item["title"] for item in entities)
        pages = [
            await self.create_or_update_wiki_page(
                kb_id,
                page_type="source",
                title=title,
                content=self._source_page_content(
                    file_meta.filename,
                    markdown,
                    source,
                    known_titles=planned_titles,
                ),
                sources=[file_id],
                confidence=self._normalize_confidence(source.get("confidence"), "EXTRACTED"),
            )
        ]
        for item in topics:
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
                        known_titles=planned_titles,
                        known_title_aliases=source_title_aliases,
                    ),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        for item in entities:
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
                        known_titles=planned_titles,
                        known_title_aliases=source_title_aliases,
                    ),
                    sources=[file_id],
                    confidence=self._normalize_confidence(item.get("confidence"), "EXTRACTED"),
                )
            )
        cache = self._load_cache(kb_id)
        page_ids = [page["id"] for page in pages]
        self._cleanup_stale_generated_pages(kb_id, file_id, set(page_ids))
        cache = self._load_cache(kb_id)
        cache[file_id] = {
            "filename": file_meta.filename,
            "content_hash": self._content_hash(markdown),
            "prompt_version": WIKI_PROMPT_VERSION,
            "status": "compiled",
            "page_ids": page_ids,
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
            llm = await load_chat_model_async(model_ref, streaming=False)
        except Exception:
            llm = await load_chat_model_async(llm_info.model, streaming=False)
        messages = self._build_compile_prompt(
            file_meta.filename,
            self._read_purpose(kb_id),
            markdown,
            headings=self._extract_headings(markdown)[:20],
            entities=self._extract_entities(markdown)[:30],
        )
        response = await self._invoke_wiki_llm(
            llm,
            [
                SystemMessage(content=messages[0]["content"]),
                HumanMessage(content=messages[1]["content"]),
            ],
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        try:
            parsed = self._parse_llm_json(content)
            normalized = self._normalize_compiled_payload(parsed, file_meta, markdown)
            self._validate_compiled_payload(normalized)
            return normalized
        except ValueError as exc:
            repair_prompt = self._build_repair_prompt(content, str(exc))
            repaired_response = await self._invoke_wiki_llm(
                llm,
                [
                    SystemMessage(content=repair_prompt[0]["content"]),
                    HumanMessage(content=repair_prompt[1]["content"]),
                ],
            )
            repaired_content = (
                repaired_response.content
                if isinstance(repaired_response.content, str)
                else str(repaired_response.content)
            )
            repaired = self._parse_llm_json(repaired_content)
            normalized = self._normalize_compiled_payload(repaired, file_meta, markdown)
            self._validate_compiled_payload(normalized)
            return normalized

    async def _invoke_wiki_llm(self, llm, messages: list) -> Any:
        timeout_s = self._wiki_llm_timeout_s()
        try:
            return await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout_s)
        except TimeoutError as exc:
            raise TimeoutError(f"Wiki 知识库编译超时（{timeout_s:g}s）") from exc

    def _wiki_llm_timeout_s(self) -> float:
        raw = os.getenv("NEXAGENT_WIKI_LLM_TIMEOUT_S", "").strip()
        if not raw:
            return DEFAULT_WIKI_LLM_TIMEOUT_S
        try:
            value = float(raw)
        except ValueError:
            return DEFAULT_WIKI_LLM_TIMEOUT_S
        return max(value, DEFAULT_WIKI_LLM_TIMEOUT_S) if value > 0 else DEFAULT_WIKI_LLM_TIMEOUT_S

    def _read_purpose(self, kb_id: str) -> str:
        path = self._db_root(kb_id) / "purpose.md"
        return path.read_text(encoding="utf-8")[:2000] if path.exists() else ""

    def _build_compile_prompt(
        self,
        filename: str,
        purpose: str,
        markdown: str,
        headings: list[str] | None = None,
        entities: list[str] | None = None,
    ) -> list[dict]:
        source_text = markdown[:12000]
        system_prompt = "你是 NexAgent 的 Wiki 知识库编译器。只输出合法 JSON，不要输出 Markdown 代码块或解释。"
        user_prompt = textwrap.dedent(
            f"""
            Wiki purpose:
            {purpose or "未设置"}
            Source filename:
            {filename}
            Detected headings:
            {json.dumps(headings or [], ensure_ascii=False)}
            Detected entity candidates:
            {json.dumps(entities or [], ensure_ascii=False)}
            必须只返回一个 JSON 对象，顶层字段固定为 source、topics、entities。
            schema:
            {{
              "source": {{
                "title": "源文档标题",
                "summary": "源文档摘要",
                "key_points": ["要点"],
                "claims": ["重要结论"],
                "confidence": "EXTRACTED"
              }},
              "topics": [
                {{"title": "主题", "summary": "摘要", "content": "Markdown 正文", "confidence": "INFERRED"}}
              ],
              "entities": [
                {{"title": "实体", "summary": "摘要", "content": "Markdown 正文", "confidence": "INFERRED"}}
              ],
              "synthesis": {{
                "title": "Wiki Synthesis",
                "summary": "综合摘要",
                "content": "Markdown 正文",
                "confidence": "INFERRED"
              }}
            }}
            topics 和 entities 可以为空数组。不要使用 pages/document/result 等替代字段。
            title 字段必须是纯文本，不要包含 [[ ]]、Markdown 链接或额外括号；只在 content 正文里使用 wikilink。
            source.title 应稳定，通常来自文件名或一级标题。
            confidence 只能是 EXTRACTED、INFERRED、AMBIGUOUS、UNVERIFIED。
            页面正文必须使用 Markdown，可用 [[页面标题]] 表达重要关联。
            Markdown source:
            {source_text}
            """
        ).strip()
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    def _local_compiled_payload(self, file_meta, markdown: str, reason: str) -> dict:
        filename = str(getattr(file_meta, "filename", "") or "")
        headings = self._extract_headings(markdown)
        source_title = self._clean_wiki_title(headings[0] if headings else Path(filename).stem)
        summary = self._summarize(markdown)
        topic_titles = [
            heading
            for heading in headings
            if self._normalize_link_key(heading) != self._normalize_link_key(source_title)
        ][:8]
        topics = [
            {
                "title": title,
                "summary": self._section_excerpt(markdown, title),
                "content": (
                    f"本页由本地降级生成，原因：{reason}\n\n"
                    f"{self._section_excerpt(markdown, title)}"
                ),
                "confidence": "UNVERIFIED",
            }
            for title in topic_titles
        ]
        known_keys = {
            self._normalize_link_key(source_title),
            *(self._normalize_link_key(title) for title in topic_titles),
        }
        entities = []
        for entity in self._extract_entities(markdown):
            key = self._normalize_link_key(entity)
            if not key or key in known_keys:
                continue
            known_keys.add(key)
            entities.append(
                {
                    "title": entity,
                    "summary": f"源文档中出现的实体：{entity}",
                    "content": (
                        f"本页由本地降级生成，原因：{reason}\n\n"
                        f"{entity} 与 [[{source_title}]] 相关。"
                    ),
                    "confidence": "UNVERIFIED",
                }
            )
            if len(entities) >= 12:
                break
        return {
            "source": {
                "title": source_title,
                "summary": f"本地降级生成：{summary}",
                "key_points": topic_titles or [summary[:120]],
                "claims": [],
                "confidence": "UNVERIFIED",
            },
            "topics": topics,
            "entities": entities,
        }

    def _build_repair_prompt(self, bad_output: str, error: str) -> list[dict]:
        return [
            {"role": "system", "content": "你是 NexAgent Wiki JSON 修复器。只输出合法 JSON。"},
            {
                "role": "user",
                "content": (
                    f"错误：{error}\n"
                    "请修复为严格 JSON："
                    '{"source":{"title":"","summary":"","key_points":[],"confidence":"EXTRACTED"},'
                    '"topics":[],"entities":[]}\n'
                    f"{bad_output}"
                ),
            },
        ]

    def _parse_llm_json(self, content: str) -> dict:
        raw = (content or "").strip()
        match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            if start < 0:
                raise
            parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
        if not isinstance(parsed, dict):
            raise ValueError("Wiki 知识库编译结果必须是 JSON 对象")
        return parsed

    def _normalize_compiled_payload(self, payload: dict, file_meta, markdown: str) -> dict:
        source = payload.get("source")
        if not isinstance(source, dict):
            for key in ("document", "source_document", "metadata"):
                candidate = payload.get(key)
                if isinstance(candidate, dict):
                    source = candidate
                    break
        if not isinstance(source, dict):
            source = payload if any(payload.get(key) for key in ("title", "summary", "content")) else {}

        title = self._clean_wiki_title(
            source.get("title")
            or payload.get("title")
            or Path(file_meta.filename).stem
        )
        summary = str(
            source.get("summary")
            or payload.get("summary")
            or source.get("content")
            or payload.get("content")
            or self._summarize(markdown)
        ).strip()
        key_points = source.get("key_points") or payload.get("key_points") or []
        if not isinstance(key_points, list):
            key_points = [str(key_points)]

        return {
            **payload,
            "source": {
                **source,
                "title": title,
                "summary": summary,
                "key_points": key_points,
                "claims": source.get("claims") or payload.get("claims") or [],
                "confidence": source.get("confidence") or payload.get("confidence") or "EXTRACTED",
            },
            "topics": self._coerce_page_items(
                payload.get("topics")
                or payload.get("pages")
                or payload.get("wiki_pages")
                or payload.get("sections")
            ),
            "entities": self._coerce_page_items(payload.get("entities")),
        }

    def _coerce_page_items(self, value: Any) -> list[dict]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            items = []
            for key, item in value.items():
                if isinstance(item, dict):
                    items.append({"title": item.get("title") or key, **item})
            return items
        return []

    def _validate_compiled_payload(self, payload: dict) -> None:
        if not isinstance(payload.get("source"), dict):
            raise ValueError("Wiki 知识库编译结果缺少 source")
        if not str(payload["source"].get("title") or "").strip():
            raise ValueError("Wiki 知识库 source.title 不能为空")
        for section in ("topics", "entities"):
            if payload.get(section) is not None and not isinstance(payload.get(section), list):
                raise ValueError(f"Wiki 知识库 {section} 必须是列表")

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

    def _clean_string_list(self, items: Any) -> list[str]:
        if not isinstance(items, list):
            return []
        return [str(item).strip() for item in items if str(item).strip()]

    def _bullet_list(self, items: list[str]) -> str:
        if not items:
            return "- No extracted items."
        return "\n".join(f"- {item}" for item in items)

    def _normalize_confidence(self, value: Any, default: str) -> str:
        confidence = str(value or default).strip().upper()
        return confidence if confidence in CONFIDENCE_VALUES else default

    def _source_page_content(
        self,
        filename: str,
        markdown: str,
        source: dict,
        known_titles: list[str] | None = None,
    ) -> str:
        title = self._clean_wiki_title(source.get("title") or Path(filename).stem)
        summary = str(source.get("summary") or "").strip()
        key_points = self._clean_string_list(source.get("key_points"))[:8]
        claims = self._clean_string_list(source.get("claims"))[:8]
        return (
            f"# {title}\n\n"
            f"Source file: `{filename}`\n\n"
            f"## Summary\n\n{self._summarize(markdown)}\n\n"
            f"## LLM Summary\n\n{summary}\n\n"
            f"## Key Points\n\n{self._bullet_list(key_points)}\n\n"
            f"## Claims\n\n{self._bullet_list(claims)}\n\n"
            f"## Suggested Links\n\n{self._links_section(markdown, known_titles, exclude_titles=[title])}"
        )

    def _page_content_from_llm(
        self,
        title: str,
        summary: Any,
        content: Any,
        source_title: str,
        known_titles: list[str] | None = None,
        known_title_aliases: dict[str, str] | None = None,
    ) -> str:
        title_index = self._title_index_from_titles(known_titles or [])
        for alias, canonical in (known_title_aliases or {}).items():
            key = self._normalize_link_key(alias)
            clean_canonical = self._clean_wiki_title(canonical)
            if key and clean_canonical:
                title_index.setdefault(key, clean_canonical)
        summary_text = self._normalize_wikilinks(str(summary or "").strip(), title_index)
        body = self._normalize_wikilinks(str(content or "").strip(), title_index)
        sections = [f"# {title}"]
        if summary_text:
            sections.extend(["", "## Summary", "", summary_text])
        sections.extend(["", "## Notes", "", body or "No detailed content generated."])
        sections.extend(["", "## Sources", "", f"- [[{source_title}]]"])
        return "\n".join(sections)

    async def _refresh_corpus_synthesis(self, kb_id: str) -> dict | None:
        pages = self.list_wiki_pages(kb_id)["pages"]
        source_pages = [page for page in pages if page["type"] == "source"]
        topic_pages = [page for page in pages if page["type"] == "topic"]
        entity_pages = [page for page in pages if page["type"] == "entity"]
        if not source_pages and not topic_pages and not entity_pages:
            return None
        source_ids = sorted({source for page in pages for source in page.get("sources", [])})
        summary = (
            f"当前 Wiki 包含 {len(source_pages)} 个来源页、{len(topic_pages)} 个主题页、{len(entity_pages)} 个实体页。"
        )
        content = "\n".join(
            [
                "# Wiki Synthesis",
                "",
                "## Summary",
                "",
                summary,
                "",
                "## Source Pages",
                "",
                self._bullet_list([f"[[{page['title']}]]" for page in source_pages[:20]]),
                "",
                "## Core Topics",
                "",
                self._bullet_list([f"[[{page['title']}]]" for page in topic_pages[:20]]),
                "",
                "## Core Entities",
                "",
                self._bullet_list([f"[[{page['title']}]]" for page in entity_pages[:20]]),
            ]
        )
        return await self.create_or_update_wiki_page(
            kb_id,
            page_type="synthesis",
            title="Wiki Synthesis",
            content=content,
            sources=source_ids,
            confidence="INFERRED",
        )

    def _extract_headings(self, markdown: str) -> list[str]:
        headings = []
        for line in (markdown or "").splitlines():
            match = re.match(r"^#{1,3}\s+(.+)$", line.strip())
            if not match:
                continue
            title = match.group(1).strip(" #")
            if title and title not in headings:
                headings.append(title)
        return headings

    def _extract_entities(self, markdown: str) -> list[str]:
        candidates = []
        candidates.extend(self._extract_headings(markdown))
        candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9]{2,}\b", markdown or ""))
        candidates.extend(re.findall(r"[《“\"]([^《》“”\"]{2,24})[》”\"]", markdown or ""))
        chinese_term_pattern = (
            r"[\u4e00-\u9fffA-Za-z0-9]{2,24}"
            r"(?:思想|理论|治理|模型|架构|系统|平台|技术|算法|协议|知识库|图谱|凭证|流程|问答)"
        )
        candidates.extend(re.findall(chinese_term_pattern, markdown or ""))
        seen = set()
        entities = []
        for item in candidates:
            clean_item = str(item).strip(" #，,。.!！?？:：;；、")
            if not clean_item or clean_item.lower() in {"source", "summary", "notes"}:
                continue
            key = self._normalize_link_key(clean_item)
            if key in seen:
                continue
            seen.add(key)
            entities.append(clean_item)
        return entities

    def _links_section(
        self,
        markdown: str,
        known_titles: list[str] | None = None,
        exclude_titles: list[str] | None = None,
    ) -> str:
        links = []
        title_index = self._title_index_from_titles(known_titles or [])
        exclude_keys = {
            self._normalize_link_key(title)
            for title in (exclude_titles or [])
            if self._normalize_link_key(title)
        }
        for item in self._extract_headings(markdown)[:8] + self._extract_entities(markdown)[:20]:
            clean_item = self._clean_wiki_title(item)
            key = self._normalize_link_key(clean_item)
            if not key or key in NOISE_WIKILINKS or key in exclude_keys:
                continue
            link_title = title_index.get(key) if title_index else clean_item
            if not link_title:
                continue
            if link_title not in links:
                links.append(link_title)
        return ", ".join(f"[[{item}]]" for item in links) if links else "No candidate links extracted."

    def _title_index_from_titles(self, titles: list[str]) -> dict[str, str]:
        index = {}
        for title in titles:
            clean_title = self._clean_wiki_title(title)
            key = self._normalize_link_key(clean_title)
            if key and key not in index:
                index[key] = clean_title
        return index

    def _source_title_aliases(self, filename: str, source_title: str) -> dict[str, str]:
        canonical = self._clean_wiki_title(source_title)
        if not canonical:
            return {}
        stem = Path(filename or "").stem
        aliases = {stem}
        without_copy_suffix = re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", stem).strip()
        if without_copy_suffix:
            aliases.add(without_copy_suffix)
        canonical_key = self._normalize_link_key(canonical)
        return {
            alias: canonical
            for alias in aliases
            if alias and self._normalize_link_key(alias) != canonical_key
        }

    def _cleanup_stale_generated_pages(self, kb_id: str, file_id: str, keep_page_ids: set[str]) -> None:
        cache = self._load_cache(kb_id)
        stale_page_ids = set(cache.get(file_id, {}).get("page_ids") or [])
        for page in self._iter_page_details(kb_id):
            page_id = page.get("id")
            frontmatter = page.get("frontmatter") or {}
            if not page_id or page_id in keep_page_ids:
                continue
            if frontmatter.get("type") not in {"source", "topic", "entity"}:
                continue
            if frontmatter.get("manual_edited"):
                continue
            if file_id in (frontmatter.get("sources") or []):
                stale_page_ids.add(page_id)
        stale_page_ids -= keep_page_ids
        if not stale_page_ids:
            return
        state = self._load_state(kb_id)
        changed = False
        for page_id in sorted(stale_page_ids):
            path = self._find_page_path(kb_id, page_id)
            if path is None:
                continue
            frontmatter, content = self._read_page(path)
            sources = list(frontmatter.get("sources") or [])
            if frontmatter.get("manual_edited"):
                continue
            if file_id not in sources:
                continue
            if len(sources) <= 1 or frontmatter.get("type") == "source":
                path.unlink(missing_ok=True)
                state.get("candidates", {}).pop(page_id, None)
                changed = True
                continue
            frontmatter["sources"] = [source for source in sources if source != file_id]
            frontmatter["updated_at"] = datetime.now(UTC).isoformat()
            self._write_page(path, frontmatter, content)
            changed = True
        if changed:
            self._save_state(kb_id, state)
            self._refresh_index(kb_id)

    def _fallback_link_entities(
        self,
        markdown: str,
        source_title: str,
        topics: list[dict],
        entities: list[dict],
        source_title_aliases: dict[str, str],
    ) -> list[dict]:
        planned_keys = {
            self._normalize_link_key(title)
            for title in [source_title, *(item["title"] for item in topics), *(item["title"] for item in entities)]
        }
        source_alias_keys = {self._normalize_link_key(alias) for alias in source_title_aliases}
        extracted_entities = {
            self._normalize_link_key(entity): entity
            for entity in self._extract_entities(markdown)
            if self._normalize_link_key(entity)
        }
        linked_titles = [
            link
            for item in [*topics, *entities]
            for value in (item.get("summary"), item.get("content"))
            for link in self._extract_wikilinks(str(value or ""))
        ]
        fallback = []
        seen = set(planned_keys)
        for link in linked_titles:
            key = self._normalize_link_key(link)
            if not key or key in seen or key in source_alias_keys or key in NOISE_WIKILINKS:
                continue
            title = extracted_entities.get(key) or self._clean_wiki_title(link)
            if not title:
                continue
            seen.add(key)
            fallback.append(
                {
                    "title": self._clean_wiki_title(title),
                    "summary": f"编译输出引用但未生成的页面：{title}",
                    "content": f"{title} 与 [[{source_title}]] 相关，编译时根据 wikilink 自动补全。",
                    "confidence": "INFERRED" if key in extracted_entities else "UNVERIFIED",
                }
            )
        return fallback

    def _section_excerpt(self, markdown: str, title: str) -> str:
        title_key = self._normalize_link_key(title)
        lines = (markdown or "").splitlines()
        collecting = False
        collected: list[str] = []
        for line in lines:
            match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
            if match:
                current_key = self._normalize_link_key(match.group(1).strip(" #"))
                if collecting and current_key != title_key:
                    break
                collecting = current_key == title_key
                continue
            if collecting:
                collected.append(line)
        excerpt = "\n".join(collected).strip()
        return excerpt[:1200] if excerpt else self._summarize(markdown)

    def _normalize_wikilinks(
        self,
        markdown: str,
        title_index: dict[str, str],
        keep_unknown: bool = True,
    ) -> str:
        if not markdown or not title_index:
            return markdown

        def replace(match: re.Match[str]) -> str:
            raw_title = self._clean_wiki_title(match.group(1))
            canonical = title_index.get(self._normalize_link_key(raw_title))
            if canonical:
                return f"[[{canonical}]]"
            return f"[[{raw_title}]]" if keep_unknown else raw_title

        return re.sub(r"\[\[([^\]]+)\]\]", replace, markdown)

    def _summarize(self, markdown: str) -> str:
        text = re.sub(r"\s+", " ", re.sub(r"^#+\s+", "", markdown, flags=re.MULTILINE)).strip()
        return text[:800] or "No textual content extracted."

    def _content_hash(self, markdown: str) -> str:
        return sha256((markdown or "").encode("utf-8")).hexdigest()
