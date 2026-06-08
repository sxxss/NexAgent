"use client";

import { useMemo, useState } from "react";
import { AlertCircle, CheckCircle, Loader2, RefreshCw, WandSparkles, Wrench } from "lucide-react";
import { repairWikiKbIssues, type WikiLintPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type WikiIssue = WikiLintPayload["issues"][number];

export function WikiLintPanel({
  kbId,
  lint,
  onReload,
  onIssueAction,
}: {
  kbId: string;
  lint: WikiLintPayload | null;
  onReload: () => Promise<void>;
  onIssueAction?: (issue: WikiIssue) => void | Promise<void>;
}) {
  const [repairing, setRepairing] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const issues = useMemo(() => lint?.issues ?? [], [lint?.issues]);
  const pageCount = lint?.summary?.page_count ?? 0;
  const groupedIssues = useMemo(() => groupIssues(issues), [issues]);
  const repairableAiIssues = useMemo(() => issues.filter((issue) => issue.repair_action === "ai_candidate"), [issues]);

  const repairIssues = async (items: WikiIssue[], force = false) => {
    if (!items.length) return;
    setRepairing(items.length === 1 ? items[0].id : "all");
    setMessage("");
    setError("");
    try {
      const result = await repairWikiKbIssues(kbId, { issue_ids: items.map((item) => item.id), force });
      const failed = result.failed_issues?.length ?? 0;
      setMessage(
        result.candidate_count
          ? `AI 修复已生成 ${result.candidate_count} 个候选，请到页面中接受或丢弃。`
          : failed
            ? `AI 修复完成，但 ${failed} 个问题未生成候选。`
            : "没有可生成候选的问题。",
      );
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 修复失败");
    } finally {
      setRepairing("");
    }
  };

  const handleAction = async (issue: WikiIssue) => {
    if (issue.repair_action === "ai_candidate") {
      await repairIssues([issue]);
      return;
    }
    await onIssueAction?.(issue);
  };

  return (
    <div className="space-y-4">
      <div className={cn("rounded-xl border px-4 py-3", issues.length ? "border-amber-100 bg-amber-50" : "border-emerald-100 bg-emerald-50")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className={cn("flex h-9 w-9 items-center justify-center rounded-lg", issues.length ? "bg-white text-amber-700" : "bg-white text-emerald-700")}>
              {issues.length ? <AlertCircle size={16} /> : <CheckCircle size={16} />}
            </span>
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Wiki 健康检查</h3>
              <p className="text-xs text-slate-500">{pageCount} pages · {issues.length} issues · 可 AI 修复 {repairableAiIssues.length} 项</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void repairIssues(repairableAiIssues)}
              disabled={!repairableAiIssues.length || Boolean(repairing)}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-amber-200 bg-white px-3 text-xs font-semibold text-amber-800 transition hover:bg-amber-50 disabled:opacity-40"
            >
              {repairing === "all" ? <Loader2 size={14} className="animate-spin" /> : <WandSparkles size={14} />}
              一键 AI 修复
            </button>
            <button type="button" onClick={() => void onReload()} className={iconButton} title="刷新检查"><RefreshCw size={14} /></button>
          </div>
        </div>
      </div>

      {message ? <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{message}</div> : null}
      {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}

      {!issues.length ? (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-emerald-100 bg-emerald-50 text-center">
          <CheckCircle size={30} className="text-emerald-600" />
          <p className="mt-3 text-sm font-semibold text-emerald-900">未发现 Wiki 结构问题</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groupedIssues.map((group) => (
            <section key={group.severity} className="rounded-xl border border-slate-200 bg-white">
              <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
                <Badge variant={severityVariant(group.severity)}>{severityLabel(group.severity)}</Badge>
                <span className="text-xs text-slate-400">{group.items.length} 项</span>
              </div>
              <div>
                {group.items.map((issue) => (
                  <div key={issue.id} className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3 last:border-0">
                    <button type="button" onClick={() => void onIssueAction?.(issue)} className="min-w-0 flex-1 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{issueTitle(issue.type)}</Badge>
                        <span className="truncate font-mono text-[11px] text-slate-400">{issue.page_id}</span>
                      </div>
                      <p className="mt-2 text-sm font-semibold text-slate-800">{issue.message}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        影响对象：{issue.page_id || issue.source_file_id || issue.target || "当前 Wiki"}
                        {issue.target ? ` -> ${issue.target}` : ""}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">建议动作：{actionAdvice(issue)}</p>
                    </button>
                    <button type="button" onClick={() => void handleAction(issue)} className={cn(actionButton, issue.repair_action === "ai_candidate" && "border-amber-200 text-amber-800")}>
                      {repairing === issue.id ? <Loader2 size={13} className="animate-spin" /> : <Wrench size={13} />}
                      {actionLabel(issue)}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function groupIssues(issues: WikiIssue[]) {
  const order: Record<string, number> = { error: 0, warning: 1, info: 2 };
  const groups = new Map<string, WikiIssue[]>();
  for (const issue of [...issues].sort((left, right) => (order[left.severity] ?? 3) - (order[right.severity] ?? 3))) {
    const severity = issue.severity || "info";
    groups.set(severity, [...(groups.get(severity) ?? []), issue]);
  }
  return [...groups.entries()].map(([severity, items]) => ({ severity, items }));
}

function issueTitle(type: string) {
  return {
    broken_link: "断链",
    ambiguous_link: "歧义链接",
    pending_candidate: "候选待处理",
    compile_cache_stale: "缓存过期",
    synthesis_stale: "综合页需重建",
    source_missing: "来源缺失",
    wiki_stale_after_delete: "删除后待重编译",
    needs_review: "需要复核",
    orphan_page: "孤立页面",
    missing_source: "缺少来源",
    duplicate_title: "重复标题",
    ambiguous_title: "同名标题",
  }[type] ?? type;
}

function severityLabel(severity: string) {
  return { error: "错误", warning: "警告", info: "待复核" }[severity] ?? severity;
}

function actionAdvice(issue: WikiIssue) {
  return {
    recompile: "重新编译相关素材，刷新综合页和图谱",
    review: "跳转到相关页面人工复核",
    accept_candidate: "打开页面候选区，选择接受或丢弃",
    ai_candidate: "由 AI 生成候选版本，人工确认后再覆盖",
    handle_candidate: "打开页面候选区，选择接受或丢弃",
  }[issue.repair_action || issue.action || "review"] ?? "查看问题对象";
}

function actionLabel(issue: WikiIssue) {
  if (issue.repair_action === "ai_candidate") return "AI 修复";
  if (issue.repair_action === "recompile" || issue.action === "recompile") return "重新编译";
  if (issue.repair_action === "handle_candidate" || issue.action === "accept_candidate") return "处理候选";
  return "查看";
}

function severityVariant(severity: string): "secondary" | "info" | "success" | "warning" | "error" {
  if (severity === "error" || severity === "critical") return "error";
  if (severity === "warning") return "warning";
  if (severity === "info") return "info";
  return "secondary";
}

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";
const actionButton = "inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-40";
