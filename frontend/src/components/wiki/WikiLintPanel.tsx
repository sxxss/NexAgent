"use client";

import { useMemo, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle, ExternalLink, Loader2, RefreshCw, RotateCcw, WandSparkles, Wrench } from "lucide-react";
import { repairWikiKbIssues, type WikiLintPayload, type WikiRepairResult } from "@/lib/api";
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
  const [repairResult, setRepairResult] = useState<WikiRepairResult | null>(null);
  const [lastRepairItems, setLastRepairItems] = useState<WikiIssue[]>([]);
  const issues = useMemo(() => lint?.issues ?? [], [lint?.issues]);
  const pageCount = lint?.summary?.page_count ?? 0;
  const groupedIssues = useMemo(() => groupIssues(issues), [issues]);
  const repairableAiIssues = useMemo(() => issues.filter((issue) => issue.repair_action === "ai_candidate"), [issues]);

  const repairIssues = async (items: WikiIssue[], force = false) => {
    if (!items.length) return;
    setRepairing(items.length === 1 ? items[0].id : "all");
    setMessage("");
    setError("");
    setRepairResult(null);
    setLastRepairItems(items);
    try {
      const result = await repairWikiKbIssues(kbId, { issue_ids: items.map((item) => item.id), force });
      const failed = result.failed_issues?.length ?? 0;
      const skipped = result.skipped_issues?.length ?? 0;
      setRepairResult(result);
      setMessage(
        result.candidate_count
          ? `AI 修复已生成 ${result.candidate_count} 个候选，请到页面中接受或丢弃。`
          : skipped
            ? `${skipped} 个问题已有待处理候选，可直接处理候选或强制重新生成。`
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

  const openCandidatePage = async (pageId: string) => {
    await onIssueAction?.({
      id: `repair-result:${pageId}`,
      type: "pending_candidate",
      page_id: pageId,
      severity: "info",
      message: "处理 AI 修复候选",
      action: "handle_candidate",
      repair_action: "handle_candidate",
    });
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
              <p className="mt-0.5 text-[11px] text-slate-500">AI 修复只生成候选版本，不会直接覆盖页面正文。</p>
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
              一键 AI 生成修复候选
            </button>
            <button type="button" onClick={() => void onReload()} className={iconButton} title="刷新检查"><RefreshCw size={14} /></button>
          </div>
        </div>
      </div>

      {message ? <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{message}</div> : null}
      {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
      <WikiRepairResultCard
        result={repairResult}
        issues={lastRepairItems}
        repairing={Boolean(repairing)}
        onOpenPage={(pageId) => void openCandidatePage(pageId)}
        onForce={() => void repairIssues(lastRepairItems, true)}
      />

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

function WikiRepairResultCard({
  result,
  issues,
  repairing,
  onOpenPage,
  onForce,
}: {
  result: WikiRepairResult | null;
  issues: WikiIssue[];
  repairing: boolean;
  onOpenPage: (pageId: string) => void;
  onForce: () => void;
}) {
  if (!result) return null;
  const issueById = new Map(issues.map((issue) => [issue.id, issue]));
  const failedIds = new Set((result.failed_issues ?? []).map((item) => item.id));
  const candidatePages = uniqueStrings(
    issues
      .filter((issue) => issue.page_id && !failedIds.has(issue.id))
      .map((issue) => issue.page_id),
  );
  const skippedPages = uniqueStrings(
    (result.skipped_issues ?? [])
      .map((item) => issueById.get(item.id)?.page_id)
      .filter(Boolean),
  );
  const failedIssues = result.failed_issues ?? [];
  const skippedIssues = result.skipped_issues ?? [];
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div>
          <h4 className="text-sm font-semibold text-slate-900">AI 修复结果</h4>
          <p className="mt-1 text-xs text-slate-500">生成候选 {result.candidate_count} 个 · 修复问题 {result.repaired_count} 个 · 跳过 {skippedIssues.length} 个 · 失败 {failedIssues.length} 个</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {candidatePages.length ? (
            <button type="button" onClick={() => onOpenPage(candidatePages[0])} className={cn(actionButton, "border-sky-200 text-sky-700")}>
              <ExternalLink size={13} />
              处理候选
            </button>
          ) : null}
          {skippedIssues.length ? (
            <button type="button" onClick={onForce} disabled={repairing} className={cn(actionButton, "border-amber-200 text-amber-800")}>
              {repairing ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
              强制重新生成候选
            </button>
          ) : null}
        </div>
      </div>
      <div className="grid gap-3 px-4 py-3 text-xs text-slate-600 lg:grid-cols-3">
        <ResultColumn title="待处理候选" items={candidatePages} empty="暂无候选页面" render={(pageId) => (
          <button type="button" onClick={() => onOpenPage(pageId)} className="truncate text-left font-semibold text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-800">
            {pageId}
          </button>
        )} />
        <ResultColumn title="已跳过" items={skippedIssues} empty="暂无跳过项" render={(item) => (
          <span className="min-w-0">
            <span className="block truncate font-mono text-[11px] text-slate-500">{item.id}</span>
            <span className="block text-slate-400">{item.reason}</span>
          </span>
        )} />
        <ResultColumn title="失败项" items={failedIssues} empty="暂无失败项" render={(item) => (
          <span className="min-w-0">
            <span className="block truncate font-mono text-[11px] text-slate-500">{item.id}</span>
            <span className="block text-rose-500">{item.error}</span>
          </span>
        )} />
      </div>
      {skippedPages.length ? (
        <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
          已有候选页面：
          <span className="ml-1 inline-flex flex-wrap gap-1">
            {skippedPages.map((pageId) => (
              <button key={pageId} type="button" onClick={() => onOpenPage(pageId)} className="font-semibold text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-800">{pageId}</button>
            ))}
          </span>
        </div>
      ) : null}
    </section>
  );
}

function ResultColumn<T>({ title, items, empty, render }: { title: string; items: T[]; empty: string; render: (item: T) => ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-slate-50 p-3">
      <p className="mb-2 font-semibold text-slate-700">{title}</p>
      <div className="grid gap-2">
        {items.length ? items.map((item, index) => (
          <div key={index} className="min-w-0 rounded-md bg-white px-2 py-1.5 shadow-sm">{render(item)}</div>
        )) : <span className="text-slate-400">{empty}</span>}
      </div>
    </div>
  );
}

function uniqueStrings(values: Array<string | undefined>) {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
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
