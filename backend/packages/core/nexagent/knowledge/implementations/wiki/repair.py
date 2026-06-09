from __future__ import annotations

import json
import textwrap
from typing import Any


class WikiRepairMixin:
    async def repair_wiki(
        self,
        kb_id: str,
        issue_ids: list[str] | None = None,
        issue_types: list[str] | None = None,
        page_ids: list[str] | None = None,
        force: bool = False,
        apply: bool = False,
        context: Any | None = None,
    ) -> dict:
        selected = self._select_ai_repair_issues(kb_id, issue_ids, issue_types, page_ids)
        state = self._load_state(kb_id)
        candidates = state.setdefault("candidates", {})
        skipped_issues = []
        pending = []

        for issue in selected:
            page_id = str(issue.get("page_id") or "")
            if not page_id or ":" not in page_id:
                continue
            if not force and page_id in candidates:
                skipped_issues.append({"id": issue["id"], "reason": "页面已有待处理候选"})
                continue
            pending.append(issue)

        if not pending:
            return {
                "repaired_count": 0,
                "candidate_count": 0,
                "skipped_issues": skipped_issues,
                "failed_issues": [],
            }

        if context is not None and hasattr(context, "set_progress"):
            await context.set_progress(10.0, "正在生成 Wiki AI 修复候选")

        repairs = await self._generate_repair_candidates(kb_id, pending)
        repairs_by_page = {
            str(item.get("page_id") or "").strip(): item
            for item in repairs
            if str(item.get("page_id") or "").strip()
        }
        issues_by_page: dict[str, list[dict]] = {}
        for issue in pending:
            issues_by_page.setdefault(str(issue["page_id"]), []).append(issue)

        failed_issues = []
        candidate_pages = set()
        applied_pages = set()
        repaired_count = 0
        for page_id, page_issues in issues_by_page.items():
            repair = repairs_by_page.get(page_id)
            if not repair:
                failed_issues.extend(
                    {"id": issue["id"], "error": "AI 未返回该问题的修复候选"} for issue in page_issues
                )
                continue
            content = str(repair.get("content") or "").strip()
            if not content:
                failed_issues.extend({"id": issue["id"], "error": "AI 修复候选正文为空"} for issue in page_issues)
                continue
            content = self._safe_repair_content(kb_id, content)
            try:
                detail = self.get_wiki_page(kb_id, page_id)
            except Exception as exc:  # noqa: BLE001
                failed_issues.extend({"id": issue["id"], "error": str(exc)} for issue in page_issues)
                continue

            frontmatter = dict(detail["frontmatter"])
            frontmatter["manual_edited"] = False
            frontmatter["confidence"] = self._normalize_confidence(
                repair.get("confidence"),
                frontmatter.get("confidence") or "UNVERIFIED",
            )
            if apply and frontmatter["confidence"] == "UNVERIFIED":
                frontmatter["confidence"] = "INFERRED"
            frontmatter["updated_at"] = _utc_now()
            if apply:
                path = self._find_page_path(kb_id, page_id)
                if path is None:
                    failed_issues.extend({"id": issue["id"], "error": "Wiki 页面文件不存在"} for issue in page_issues)
                    continue
                self._write_page(path, frontmatter, content)
                candidates.pop(page_id, None)
                applied_pages.add(page_id)
            else:
                candidates[page_id] = {
                    "frontmatter": frontmatter,
                    "content": content,
                    "created_at": _utc_now(),
                    "repair": True,
                    "issue_ids": [issue["id"] for issue in page_issues],
                    "reason": str(repair.get("reason") or "AI 生成修复候选").strip(),
                }
                candidate_pages.add(page_id)
            repaired_count += len(page_issues)

        self._save_state(kb_id, state)
        if applied_pages:
            self._refresh_index(kb_id)
        if context is not None and hasattr(context, "set_progress"):
            if apply:
                await context.set_progress(100.0, f"Wiki AI 修复完成，已应用 {len(applied_pages)} 个页面")
            else:
                await context.set_progress(100.0, f"Wiki AI 修复完成，生成 {len(candidate_pages)} 个候选")
        return {
            "repaired_count": repaired_count,
            "candidate_count": len(candidate_pages),
            "applied_count": len(applied_pages),
            "skipped_issues": skipped_issues,
            "failed_issues": failed_issues,
        }

    def _select_ai_repair_issues(
        self,
        kb_id: str,
        issue_ids: list[str] | None,
        issue_types: list[str] | None,
        page_ids: list[str] | None,
    ) -> list[dict]:
        wanted_ids = set(issue_ids or [])
        wanted_types = set(issue_types or [])
        wanted_pages = set(page_ids or [])
        selected = []
        for issue in self.lint_wiki(kb_id).get("issues", []):
            if issue.get("repair_action") != "ai_candidate":
                continue
            if wanted_ids and issue.get("id") not in wanted_ids:
                continue
            if wanted_types and issue.get("type") not in wanted_types:
                continue
            if wanted_pages and issue.get("page_id") not in wanted_pages:
                continue
            selected.append(issue)
        return selected

    async def _generate_repair_candidates(self, kb_id: str, issues: list[dict]) -> list[dict]:
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
        prompt = self._build_repair_wiki_prompt(kb_id, issues)
        response = await self._invoke_wiki_llm(
            llm,
            [
                SystemMessage(content=prompt[0]["content"]),
                HumanMessage(content=prompt[1]["content"]),
            ],
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = self._parse_llm_json(content)
        repairs = parsed.get("repairs")
        if not isinstance(repairs, list):
            raise ValueError("Wiki AI 修复结果缺少 repairs 数组")
        return [item for item in repairs if isinstance(item, dict)]

    def _safe_repair_content(self, kb_id: str, content: str) -> str:
        title_index = self._title_index_from_titles(
            [page["title"] for page in self.list_wiki_pages(kb_id).get("pages", [])]
        )
        return self._normalize_wikilinks(content, title_index, keep_unknown=False)

    def _build_repair_wiki_prompt(self, kb_id: str, issues: list[dict]) -> list[dict]:
        page_ids = sorted({str(issue["page_id"]) for issue in issues})
        pages = []
        for page_id in page_ids:
            detail = self.get_wiki_page(kb_id, page_id)
            pages.append(
                {
                    "id": detail["id"],
                    "title": detail["title"],
                    "type": detail["type"],
                    "frontmatter": detail["frontmatter"],
                    "content": detail["content"],
                    "issues": [issue for issue in issues if issue["page_id"] == page_id],
                }
            )
        output_schema = json.dumps(
            {
                "repairs": [
                    {
                        "page_id": "topic:example",
                        "content": "完整 Markdown 正文",
                        "confidence": "INFERRED",
                        "reason": "修复原因",
                    }
                ]
            },
            ensure_ascii=False,
        )
        user_prompt = textwrap.dedent(
            f"""
            请为下面 NexAgent Wiki 页面生成修复版本。
            要求：
            - 只返回合法 JSON，不要输出 Markdown 代码块或解释。
            - 修复正文必须是完整 Markdown。
            - 不要编造来源；无法确定时使用 UNVERIFIED 或 INFERRED。
            - 可以用 [[页面标题]] 保留或补充明确的 Wiki 关联。
            - confidence 只能是 EXTRACTED、INFERRED、AMBIGUOUS、UNVERIFIED。

            输出 schema:
            {output_schema}

            输入页面和健康检查问题:
            {json.dumps(pages, ensure_ascii=False)}
            """
        ).strip()
        return [
            {"role": "system", "content": "你是 NexAgent Wiki 健康检查修复助手。只输出合法 JSON。"},
            {"role": "user", "content": user_prompt},
        ]


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
