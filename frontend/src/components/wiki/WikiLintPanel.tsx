"use client";

import { AlertCircle, CheckCircle, RefreshCw, Wrench } from "lucide-react";
import { type WikiLintPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function WikiLintPanel({ lint, onReload }: { lint: WikiLintPayload | null; onReload: () => Promise<void> }) {
  const issues = lint?.issues ?? [];
  const pageCount = lint?.summary?.page_count ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={cn("flex h-9 w-9 items-center justify-center rounded-lg", issues.length ? "bg-amber-50 text-amber-700" : "bg-emerald-50 text-emerald-700")}>
            {issues.length ? <AlertCircle size={16} /> : <CheckCircle size={16} />}
          </span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Wiki 健康检查</h3>
            <p className="text-xs text-slate-500">{pageCount} pages · {issues.length} issues</p>
          </div>
        </div>
        <button type="button" onClick={() => void onReload()} className={iconButton} title="刷新检查"><RefreshCw size={14} /></button>
      </div>

      {!issues.length ? (
        <div className="flex min-h-72 flex-col items-center justify-center rounded-xl border border-emerald-100 bg-emerald-50 text-center">
          <CheckCircle size={30} className="text-emerald-600" />
          <p className="mt-3 text-sm font-semibold text-emerald-900">未发现 Wiki 结构问题</p>
        </div>
      ) : (
        <div className="space-y-2">
          {issues.map((issue) => (
            <div key={issue.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={severityVariant(issue.severity)}>{issue.severity}</Badge>
                    <Badge variant="secondary">{issue.type}</Badge>
                    <span className="truncate font-mono text-[11px] text-slate-400">{issue.page_id}</span>
                  </div>
                  <p className="mt-2 text-sm font-semibold text-slate-800">{issue.message}</p>
                  {issue.action ? <p className="mt-1 text-xs text-slate-500">{issue.action}</p> : null}
                </div>
                {issue.repairable ? (
                  <span className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2 text-xs font-semibold text-amber-700">
                    <Wrench size={13} />
                    {issue.repair_action || "repairable"}
                  </span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function severityVariant(severity: string): "secondary" | "info" | "success" | "warning" | "error" {
  if (severity === "error" || severity === "critical") return "error";
  if (severity === "warning") return "warning";
  if (severity === "info") return "info";
  return "secondary";
}

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";
