"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, RefreshCw, XCircle } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { fetchSystemDiagnostics, type ConfigIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

const statusCopy = {
  ok: { label: "正常", tone: "text-emerald-700 bg-emerald-50 border-emerald-200", icon: CheckCircle2 },
  warning: { label: "需要关注", tone: "text-amber-800 bg-amber-50 border-amber-200", icon: AlertTriangle },
  error: { label: "阻塞启动", tone: "text-rose-800 bg-rose-50 border-rose-200", icon: XCircle },
} as const;

export default function DiagnosticsPage() {
  const diagnosticsQuery = useQuery({
    queryKey: ["system-diagnostics"],
    queryFn: fetchSystemDiagnostics,
    refetchInterval: 15000,
  });

  const data = diagnosticsQuery.data;
  const config = data?.config;
  const status = config?.status ?? "warning";
  const StatusIcon = statusCopy[status].icon;
  const issues = config?.issues ?? [];
  const errors = issues.filter((issue) => issue.severity === "error");
  const warnings = issues.filter((issue) => issue.severity === "warning");

  return (
    <main className="min-h-0 flex-1 overflow-auto">
      <PageHeader
        eyebrow="Runtime"
        title="系统诊断"
        description="检查配置、模型、知识服务、搜索、沙盒和 tracing 的启动状态。"
        actions={
          <Button
            variant="outline"
            onClick={() => diagnosticsQuery.refetch()}
            disabled={diagnosticsQuery.isFetching}
            className="gap-2"
          >
            <RefreshCw size={15} className={cn(diagnosticsQuery.isFetching && "animate-spin")} />
            刷新
          </Button>
        }
      />

      <section className="px-5 pb-8 md:px-8">
        <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
          <div className="rounded-2xl border border-white/80 bg-white/75 p-5 shadow-[0_16px_40px_rgba(83,101,132,0.09)]">
            <div className={cn("inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-semibold", statusCopy[status].tone)}>
              <StatusIcon size={16} />
              {statusCopy[status].label}
            </div>
            <dl className="mt-5 space-y-3 text-sm">
              <InfoRow label="服务" value={data?.service ?? "nexagent-gateway"} />
              <InfoRow label="版本" value={data?.version ?? "-"} />
              <InfoRow label="配置文件" value={config?.path ?? "后端未连接"} />
              <InfoRow label="配置存在" value={config?.config_exists ? "是" : "否"} />
              <InfoRow label="错误" value={`${errors.length}`} />
              <InfoRow label="警告" value={`${warnings.length}`} />
            </dl>
          </div>

          <div className="rounded-2xl border border-white/80 bg-white/75 p-5 shadow-[0_16px_40px_rgba(83,101,132,0.09)]">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-bold text-slate-900">配置问题</h2>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                {issues.length} 项
              </span>
            </div>

            {diagnosticsQuery.isLoading ? (
              <div className="mt-6 h-24 animate-pulse rounded-xl bg-slate-100" />
            ) : !data ? (
              <EmptyState title="后端未连接" description="启动 FastAPI 后端后刷新此页。" />
            ) : issues.length === 0 ? (
              <EmptyState title="未发现配置问题" description="当前配置通过基础启动诊断。" />
            ) : (
              <div className="mt-4 space-y-3">
                {issues.map((issue) => (
                  <IssueItem key={`${issue.severity}-${issue.code}-${issue.message}`} issue={issue} />
                ))}
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[72px_1fr] gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate font-medium text-slate-800" title={value}>
        {value}
      </dd>
    </div>
  );
}

function IssueItem({ issue }: { issue: ConfigIssue }) {
  const isError = issue.severity === "error";
  const Icon = isError ? XCircle : AlertTriangle;
  return (
    <article
      className={cn(
        "rounded-xl border p-4",
        isError ? "border-rose-200 bg-rose-50/70" : "border-amber-200 bg-amber-50/70",
      )}
    >
      <div className="flex items-start gap-3">
        <Icon size={17} className={isError ? "mt-0.5 text-rose-600" : "mt-0.5 text-amber-600"} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-bold text-slate-900">{issue.message}</h3>
            <span className="rounded-md bg-white/80 px-1.5 py-0.5 font-mono text-[11px] text-slate-500">
              {issue.code}
            </span>
          </div>
          {issue.fix ? <p className="mt-2 text-sm leading-6 text-slate-600">{issue.fix}</p> : null}
        </div>
      </div>
    </article>
  );
}

function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center">
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
    </div>
  );
}
