from __future__ import annotations

from collections import defaultdict


AI_REPAIRABLE_ISSUES = {
    "broken_link",
    "ambiguous_link",
    "needs_review",
    "orphan_page",
}

RECOMPILE_ISSUES = {"source_missing", "wiki_stale_after_delete"}


class WikiLintMixin:
    def lint_wiki(self, kb_id: str) -> dict:
        pages = self._iter_page_details(kb_id)
        title_index = self._title_index(pages)
        title_counts = defaultdict(int)
        typed_title_counts = defaultdict(int)
        for page in pages:
            key = self._normalize_link_key(page["title"])
            title_counts[key] += 1
            typed_title_counts[(page["type"], key)] += 1

        linked_ids: set[str] = set()
        issues = []
        for page in pages:
            required = {"id", "title", "type", "sources", "confidence", "updated_at", "manual_edited"}
            missing = sorted(required - set(page["frontmatter"].keys()))
            if missing:
                issues.append(self._lint_issue("missing_frontmatter", page["id"], "error", fields=missing))
            key = self._normalize_link_key(page["title"])
            if typed_title_counts[(page["type"], key)] > 1:
                issues.append(self._lint_issue("duplicate_title", page["id"], "warning"))
            elif title_counts[key] > 1:
                issues.append(self._lint_issue("ambiguous_title", page["id"], "warning"))
            for source_id in page["frontmatter"].get("sources") or []:
                if source_id not in self._files:
                    issues.append(self._lint_issue("source_missing", page["id"], "error", target=source_id))
            if page["frontmatter"].get("confidence") in {"AMBIGUOUS", "UNVERIFIED"}:
                issues.append(
                    self._lint_issue(
                        "needs_review",
                        page["id"],
                        "info",
                        confidence=page["frontmatter"].get("confidence"),
                    )
                )
            for link in self._extract_wikilinks(page["content"]):
                targets = self._resolve_wikilink(link, title_index)
                if not targets:
                    issues.append(self._lint_issue("broken_link", page["id"], "error", target=link))
                elif len(targets) > 1:
                    issues.append(self._lint_issue("ambiguous_link", page["id"], "warning", target=link))
                else:
                    linked_ids.add(targets[0]["id"])

        for page in pages:
            if page["id"] not in linked_ids and not self._extract_wikilinks(page["content"]) and page["type"] != "source":
                issues.append(self._lint_issue("orphan_page", page["id"], "warning"))
        state = self._load_state(kb_id)
        for page_id in sorted(state.get("candidates", {})):
            issues.append(self._lint_issue("pending_candidate", page_id, "warning", action="accept_candidate"))
        if state.get("needs_recompile"):
            issues.append(
                self._lint_issue(
                    "wiki_stale_after_delete",
                    kb_id,
                    "warning",
                    action="recompile",
                    reason=state.get("recompile_reason"),
                )
            )
        return {
            "issues": issues,
            "summary": {"issue_count": len(issues), "page_count": len(pages)},
            "compile_status": state.get("compile_status", {"status": "idle"}),
        }

    def _lint_issue(self, issue_type: str, page_id: str, severity: str, **extra) -> dict:
        messages = {
            "missing_frontmatter": "页面缺少必要 frontmatter 字段",
            "duplicate_title": "存在重复页面标题",
            "ambiguous_title": "不同类型页面存在同名标题",
            "source_missing": "页面引用的来源文件不存在",
            "needs_review": "页面置信度需要人工复核",
            "broken_link": "页面包含断开的 wikilink",
            "ambiguous_link": "页面 wikilink 指向多个同名页面",
            "orphan_page": "页面没有被其他页面链接且自身没有链接",
            "pending_candidate": "存在待处理的系统候选版本",
            "wiki_stale_after_delete": "素材删除后，Wiki 需要重新编译",
        }
        target = extra.get("target")
        issue_id = ":".join([issue_type, page_id, str(target or "")]).rstrip(":")
        if issue_type in AI_REPAIRABLE_ISSUES:
            repairable = True
            repair_action = "ai_candidate"
        elif issue_type in RECOMPILE_ISSUES:
            repairable = True
            repair_action = "recompile"
        elif issue_type == "pending_candidate":
            repairable = True
            repair_action = "handle_candidate"
        else:
            repairable = False
            repair_action = "review"
        return {
            "id": issue_id,
            "type": issue_type,
            "page_id": page_id,
            "severity": severity,
            "message": messages.get(issue_type, issue_type),
            "action": extra.pop("action", "review"),
            "repairable": repairable,
            "repair_action": repair_action,
            **extra,
        }
