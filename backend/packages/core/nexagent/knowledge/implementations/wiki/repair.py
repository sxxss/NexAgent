from __future__ import annotations

from typing import Any


class WikiRepairMixin:
    async def repair_wiki(
        self,
        kb_id: str,
        issue_ids: list[str] | None = None,
        issue_types: list[str] | None = None,
        page_ids: list[str] | None = None,
        force: bool = False,
        context: Any | None = None,
    ) -> dict:
        selected = self._select_ai_repair_issues(kb_id, issue_ids, issue_types, page_ids)
        state = self._load_state(kb_id)
        candidates = state.setdefault("candidates", {})
        skipped_issues = []
        candidate_pages = set()

        if context is not None and hasattr(context, "set_progress"):
            await context.set_progress(10.0, "正在生成 Wiki 修复候选")

        for issue in selected:
            page_id = str(issue.get("page_id") or "")
            if not page_id or ":" not in page_id:
                continue
            if not force and page_id in candidates:
                skipped_issues.append({"id": issue["id"], "reason": "页面已有待处理候选"})
                continue
            detail = self.get_wiki_page(kb_id, page_id)
            frontmatter = dict(detail["frontmatter"])
            frontmatter["manual_edited"] = False
            frontmatter["confidence"] = self._normalize_confidence(frontmatter.get("confidence"), "UNVERIFIED")
            frontmatter["updated_at"] = _utc_now()
            content = f"{detail['content'].rstrip()}\n\n## Repair Notes\n\n- {issue['message']}"
            candidates[page_id] = {
                "frontmatter": frontmatter,
                "content": content,
                "created_at": _utc_now(),
                "repair": True,
                "issue_ids": [issue["id"]],
                "reason": issue["message"],
            }
            candidate_pages.add(page_id)

        self._save_state(kb_id, state)
        if context is not None and hasattr(context, "set_progress"):
            await context.set_progress(100.0, f"Wiki 修复候选生成完成：{len(candidate_pages)} 个页面")
        return {
            "repaired_count": len(candidate_pages),
            "candidate_count": len(candidate_pages),
            "skipped_issues": skipped_issues,
            "failed_issues": [],
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


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
