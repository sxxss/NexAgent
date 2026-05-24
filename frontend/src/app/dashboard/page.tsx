"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  CheckCircle2,
  Clock,
  Database,
  Gauge,
  type LucideIcon,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Wrench,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import {
  fetchDashboardAnomalies,
  fetchDashboardSummary,
  fetchKBs,
  fetchRecentLogs,
  fetchTimeSeries,
  repairDashboardAnomalies,
  type DashboardAnomaly,
  type TimeSeriesPoint,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface LogRow {
  id: string;
  agent_name?: string;
  agent_id?: string;
  model_name?: string;
  status: string;
  latency_ms: number;
  total_tokens: number;
  input_tokens?: number;
  output_tokens?: number;
  raw_input_tokens?: number;
  raw_output_tokens?: number;
  raw_total_tokens?: number;
  token_source?: string;
  token_estimated?: boolean;
  token_usage_anomalous?: boolean;
  total_cost?: number;
  input_cost?: number;
  output_cost?: number;
  currency?: string;
  priced?: boolean;
  price_missing_reason?: string;
  tools_used?: string[];
  reasoning_mode?: string;
  created_at?: string;
}

const DAY_OPTIONS = [1, 7, 14, 30] as const;
type DayOption = (typeof DAY_OPTIONS)[number];
type RankMetric = "calls" | "tokens" | "cost";

export default function DashboardPage() {
  const queryClient = useQueryClient();
  const [days, setDays] = useState<DayOption>(7);
  const [rankMetric, setRankMetric] = useState<RankMetric>("calls");

  const summaryQuery = useQuery({ queryKey: ["dashboard-summary", days], queryFn: () => fetchDashboardSummary(days) });
  const callSeriesQuery = useQuery({ queryKey: ["dashboard-calls", days], queryFn: () => fetchTimeSeries("calls", days) });
  const tokenSeriesQuery = useQuery({ queryKey: ["dashboard-tokens", days], queryFn: () => fetchTimeSeries("tokens", days) });
  const costSeriesQuery = useQuery({ queryKey: ["dashboard-cost", days], queryFn: () => fetchTimeSeries("cost", days) });
  const latencySeriesQuery = useQuery({ queryKey: ["dashboard-latency", days], queryFn: () => fetchTimeSeries("latency", days) });
  const errorSeriesQuery = useQuery({ queryKey: ["dashboard-errors", days], queryFn: () => fetchTimeSeries("errors", days) });
  const logsQuery = useQuery({ queryKey: ["dashboard-logs"], queryFn: () => fetchRecentLogs(25) });
  const anomaliesQuery = useQuery({ queryKey: ["dashboard-anomalies"], queryFn: () => fetchDashboardAnomalies(50) });
  const kbsQuery = useQuery({ queryKey: ["kbs"], queryFn: fetchKBs });
  const repairMutation = useMutation({
    mutationFn: repairDashboardAnomalies,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-anomalies"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-logs"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-tokens"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-cost"] }),
      ]);
    },
  });

  const summary = summaryQuery.data;
  const logs = (logsQuery.data ?? []) as LogRow[];
  const loading =
    summaryQuery.isFetching ||
    callSeriesQuery.isFetching ||
    tokenSeriesQuery.isFetching ||
    costSeriesQuery.isFetching ||
    latencySeriesQuery.isFetching ||
    errorSeriesQuery.isFetching ||
    logsQuery.isFetching;

  const successRate = summary?.total_calls ? Math.max(0, 100 - (summary.error_rate ?? 0)) : 0;
  const costCurrencies = Object.keys(summary?.cost_by_currency ?? {});
  const activeCostCurrency = costCurrencies[0] || summary?.currency || "USD";
  const costSeries = useMemo(
    () =>
      (costSeriesQuery.data ?? []).map((point) => ({
        ...point,
        value: point.values?.[activeCostCurrency] ?? point.value ?? 0,
      })),
    [activeCostCurrency, costSeriesQuery.data],
  );
  const tokenSplit = useMemo(
    () => [
      { label: "输入", value: summary?.input_tokens ?? 0, color: "#6d5cf0" },
      { label: "输出", value: summary?.output_tokens ?? 0, color: "#c451e8" },
    ],
    [summary],
  );
  const tokenSourceSplit = useMemo(() => {
    const sources = summary?.token_sources;
    return [
      { label: "真实", value: sources?.provider_reported ?? 0, color: "#6d5cf0" },
      { label: "估算", value: sources?.estimated ?? 0, color: "#c451e8" },
      { label: "忽略", value: sources?.ignored ?? 0, color: "#f59e0b" },
    ];
  }, [summary]);
  const modelRankRows = useMemo(() => {
    const rows = (summary?.top_models ?? []).map((item) => {
      const cost = item.cost ?? 0;
      return {
        id: item.model_name,
        name: item.model_name,
        tokens: item.tokens,
        calls: item.calls,
        cost,
        meta: `${formatNum(item.tokens)} tok · ${formatCostMap(item.cost_by_currency, cost, summary?.currency)} · ${Math.round(item.avg_latency_ms)}ms`,
        value: rankValue({ calls: item.calls, tokens: item.tokens, cost }, rankMetric),
      };
    });
    return rows.sort((a, b) => b.value - a.value);
  }, [rankMetric, summary]);

  const refresh = () => {
    void summaryQuery.refetch();
    void callSeriesQuery.refetch();
    void tokenSeriesQuery.refetch();
    void costSeriesQuery.refetch();
    void latencySeriesQuery.refetch();
    void errorSeriesQuery.refetch();
    void logsQuery.refetch();
    void anomaliesQuery.refetch();
    void kbsQuery.refetch();
  };

  return (
    <div className="flex h-full min-w-0 flex-col">
      <PageHeader
        eyebrow="Runtime Observability"
        title="运行洞察"
        description="跟踪 Agent 调用、Token、成本、延迟、错误、模型与工具使用情况，帮助判断系统是否稳定、可控、可运营。"
        actions={
          <>
            <div className="flex overflow-hidden rounded-xl border border-slate-200 bg-white/80 shadow-sm">
              {DAY_OPTIONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setDays(item)}
                  className={cn(
                    "h-9 px-3 text-xs font-semibold transition",
                    days === item ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-white",
                  )}
                >
                  {item} 天
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={refresh}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-white"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              刷新
            </button>
          </>
        }
      />

      <main className="no-scrollbar min-h-0 flex-1 overflow-y-auto px-5 pb-6 md:px-8">
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <MetricCard icon={TrendingUp} label="总调用" value={formatNum(summary?.total_calls ?? 0)} sub={`近 ${days} 天`} tone="blue" />
          <MetricCard
            icon={Zap}
            label="Token 消耗"
            value={formatNum(summary?.total_tokens ?? 0)}
            sub={(summary?.token_anomaly_count ?? 0) > 0 ? `${summary?.token_anomaly_count} 条异常` : "输入 + 输出"}
            tone="teal"
          />
          <MetricCard
            icon={Gauge}
            label="估算成本"
            value={formatCostMap(summary?.cost_by_currency, summary?.total_cost ?? 0, summary?.currency)}
            sub={`${summary?.pricing_coverage?.percent ?? 0}% 已计价`}
            tone="blue"
          />
          <MetricCard icon={Clock} label="平均延迟" value={`${Math.round(summary?.avg_latency_ms ?? 0)}ms`} sub={`P95 ${Math.round(summary?.p95_latency_ms ?? 0)}ms`} tone="amber" />
          <MetricCard
            icon={(summary?.error_rate ?? 0) > 5 ? AlertTriangle : CheckCircle2}
            label="成功率"
            value={summary?.total_calls ? `${successRate.toFixed(1)}%` : "-"}
            sub={`${summary?.error_count ?? 0} 次错误`}
            tone={(summary?.error_rate ?? 0) > 5 ? "rose" : "emerald"}
          />
        </section>

        <section className="mt-5 grid items-start gap-4 xl:grid-cols-3">
          <Panel title="调用量趋势" icon={BarChart3} action={loading ? "更新中..." : `${days} 天窗口`}>
            <TrendChart data={callSeriesQuery.data ?? []} days={days} color="#6d5cf0" unit="次" size="large" />
          </Panel>
          <Panel title="Token 消耗趋势" icon={Zap} action={loading ? "更新中..." : `${days} 天窗口`}>
            <TrendChart data={tokenSeriesQuery.data ?? []} days={days} color="#c451e8" unit="tok" size="large" />
          </Panel>
          <Panel title={`成本趋势 ${activeCostCurrency}`} icon={Gauge} action={loading ? "更新中..." : `${days} 天窗口`}>
            <TrendChart data={costSeries} days={days} color="#6d5cf0" unit={activeCostCurrency} size="large" valueFormatter={(value) => formatCost(value, activeCostCurrency)} />
          </Panel>
        </section>

        <HealthStrip
          successRate={successRate}
          statusItems={summary?.status_breakdown ?? []}
          totalCalls={summary?.total_calls ?? 0}
          tokenSplit={tokenSplit}
          tokenSourceSplit={tokenSourceSplit}
          pricingCoverage={summary?.pricing_coverage}
        />

        <section className="mt-5 grid gap-4 xl:grid-cols-2">
          <Panel title="延迟趋势" icon={Clock}>
            <TrendChart data={latencySeriesQuery.data ?? []} days={days} color="#f59e0b" unit="ms" />
          </Panel>
          <Panel title="错误趋势" icon={AlertTriangle}>
            <TrendChart data={errorSeriesQuery.data ?? []} days={days} color="#ef4444" unit="次" />
          </Panel>
        </section>

        <section className="mt-5 grid gap-4 xl:grid-cols-3">
          <ResourceCard icon={Bot} label="Agent 数量" value={summary?.agent_count ?? 0} description="当前系统可用 Agent 配置" />
          <ResourceCard icon={Database} label="知识库数量" value={kbsQuery.data?.length ?? 0} description="已创建 RAG / LightRAG 知识库" />
          <ResourceCard icon={Sparkles} label="最近活跃" value={logs.length} description="最近调用记录样本数量" />
        </section>

        <section className="mt-5 grid gap-4 xl:grid-cols-2">
          <UnpricedModels items={summary?.unpriced_models ?? []} />
          <AnomalyPanel
            items={anomaliesQuery.data ?? []}
            loading={anomaliesQuery.isFetching || repairMutation.isPending}
            onIgnore={(id) => repairMutation.mutate({ ids: [id], mode: "ignore" })}
            onRepair={(id) => repairMutation.mutate({ ids: [id], mode: "repair" })}
          />
        </section>

        <section className="mt-5 grid gap-4 xl:grid-cols-[1fr_1fr_360px]">
          <RecentLogs logs={logs} />
          <RankPanel title="模型排行" icon={Zap} rows={modelRankRows} action={<RankMetricSwitch value={rankMetric} onChange={setRankMetric} />} />
          <div className="space-y-4">
            <RankPanel
              title="Agent 排行"
              icon={Bot}
              rows={(summary?.top_agents ?? []).map((item) => ({
                id: item.agent_id || item.agent_name,
                name: item.agent_name || item.agent_id || "unknown",
                meta: `${formatNum(item.tokens)} tok · ${formatCostMap(item.cost_by_currency, item.cost ?? 0, summary?.currency)} · ${Math.round(item.avg_latency_ms)}ms`,
                value: item.calls,
              }))}
              compact
            />
            <RankPanel
              title="工具使用"
              icon={Wrench}
              rows={(summary?.top_tools ?? []).map((item) => ({
                id: item.name,
                name: item.name,
                meta: "调用次数",
                value: item.count,
              }))}
              compact
            />
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  sub: string;
  tone: "blue" | "teal" | "amber" | "rose" | "emerald";
}) {
  return (
    <div className="rounded-3xl border border-white/80 bg-white/78 p-5 shadow-[0_18px_40px_rgba(39,56,87,0.08)]">
      <div className={cn("mb-5 flex h-12 w-12 items-center justify-center rounded-2xl", toneClass(tone))}>
        <Icon size={20} />
      </div>
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-1 truncate text-3xl font-bold tracking-tight text-slate-950">{value}</p>
      <p className="mt-2 text-xs text-slate-400">{sub}</p>
    </div>
  );
}

function Panel({
  title,
  icon: Icon,
  action,
  className,
  children,
}: {
  title: string;
  icon: LucideIcon;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("overflow-hidden rounded-3xl border border-white/80 bg-white/78 shadow-[0_18px_40px_rgba(39,56,87,0.08)]", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={17} className="shrink-0 text-slate-500" />
          <h2 className="truncate text-base font-bold text-slate-900">{title}</h2>
        </div>
        {typeof action === "string" ? <span className="text-xs font-medium text-slate-400">{action}</span> : action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function ResourceCard({ icon: Icon, label, value, description }: { icon: LucideIcon; label: string; value: string | number; description: string }) {
  return (
    <div className="rounded-3xl border border-white/80 bg-white/78 p-5 shadow-[0_18px_40px_rgba(39,56,87,0.08)]">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#efeafe] text-[#6d5cf0]">
          <Icon size={18} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-700">{label}</p>
          <p className="text-xs text-slate-400">{description}</p>
        </div>
      </div>
      <p className="mt-5 text-3xl font-bold text-slate-950">{value}</p>
    </div>
  );
}

function HealthStrip({
  successRate,
  statusItems,
  totalCalls,
  tokenSplit,
  tokenSourceSplit,
  pricingCoverage,
}: {
  successRate: number;
  statusItems: { status: string; count: number }[];
  totalCalls: number;
  tokenSplit: { label: string; value: number; color: string }[];
  tokenSourceSplit: { label: string; value: number; color: string }[];
  pricingCoverage?: { priced_calls: number; total_calls: number; percent: number };
}) {
  return (
    <section className="mt-5 overflow-hidden rounded-3xl border border-white/80 bg-white/78 shadow-[0_18px_40px_rgba(39,56,87,0.08)]">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex min-w-0 items-center gap-2">
          <Gauge size={17} className="shrink-0 text-slate-500" />
          <h2 className="truncate text-base font-bold text-slate-900">运行健康</h2>
        </div>
        <span className="text-xs font-medium text-slate-400">横向概览</span>
      </div>
      <div className="grid gap-4 p-5 lg:grid-cols-5">
        <div className="rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
          <div className="flex items-center gap-3">
            <div
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full"
              style={{ background: `conic-gradient(${successRate >= 95 ? "#c451e8" : "#f59e0b"} ${Math.max(0, Math.min(successRate, 100)) * 3.6}deg, #e8edf5 0deg)` }}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-xs font-bold text-slate-900">
                {successRate ? `${successRate.toFixed(0)}%` : "-"}
              </div>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900">成功率</p>
              <p className="mt-1 text-xs text-slate-500">成功与错误调用</p>
            </div>
          </div>
        </div>
        <MiniBars title="状态分布" items={statusItems.length ? statusItems.map((item) => ({ label: statusLabel(item.status), value: item.count, color: item.status === "error" ? "#ef4444" : "#c451e8" })) : [{ label: "暂无", value: 0, color: "#94a3b8" }]} total={totalCalls} />
        <MiniBars title="Token 拆分" items={tokenSplit} />
        <MiniBars title="Token 来源" items={tokenSourceSplit} />
        <div className="rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">价格覆盖率</p>
            <span className="font-mono text-xs font-semibold text-slate-600">{(pricingCoverage?.percent ?? 0).toFixed(1)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-[#6d5cf0]" style={{ width: `${Math.max(0, Math.min(pricingCoverage?.percent ?? 0, 100))}%` }} />
          </div>
          <p className="mt-3 text-xs text-slate-500">
            {pricingCoverage?.priced_calls ?? 0}/{pricingCoverage?.total_calls ?? 0} 次调用已计价
          </p>
        </div>
      </div>
    </section>
  );
}

function MiniBars({ title, items, total }: { title: string; items: { label: string; value: number; color: string }[]; total?: number }) {
  const sum = total ?? items.reduce((acc, item) => acc + item.value, 0);
  return (
    <div className="rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
      <p className="mb-3 text-xs font-bold uppercase tracking-[0.16em] text-slate-400">{title}</p>
      <div className="space-y-2">
        {items.map((item) => {
          const percent = sum ? (item.value / sum) * 100 : 0;
          return (
            <div key={item.label}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-600">{item.label}</span>
                <span className="font-mono text-slate-400">{formatNum(item.value)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white">
                <div className="h-full rounded-full" style={{ width: `${percent}%`, backgroundColor: item.color }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrendChart({
  title,
  data,
  days,
  color,
  unit,
  size = "default",
  valueFormatter,
}: {
  title?: string;
  data: TimeSeriesPoint[];
  days: number;
  color: string;
  unit: string;
  size?: "default" | "large";
  valueFormatter?: (value: number) => string;
}) {
  const series = useMemo(() => normalizeSeries(data, days), [data, days]);
  const total = series.reduce((sum, item) => sum + Number(item.value || 0), 0);
  const max = Math.max(...series.map((item) => Number(item.value) || 0), 1);
  const width = 680;
  const height = size === "large" ? 240 : 210;
  const padding = { top: 20, right: 18, bottom: 32, left: 46 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const hasValue = series.some((item) => Number(item.value) > 0);

  const points = series.map((item, index) => {
    const x = padding.left + (series.length === 1 ? chartWidth / 2 : (index / (series.length - 1)) * chartWidth);
    const y = padding.top + chartHeight - ((Number(item.value) || 0) / max) * chartHeight;
    return { ...item, x, y };
  });
  const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const areaPath = points.length
    ? `${linePath} L ${points.at(-1)?.x ?? padding.left} ${padding.top + chartHeight} L ${points[0].x} ${padding.top + chartHeight} Z`
    : "";
  const gradientId = `area-${color.replace("#", "")}-${unit}`;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        {title ? <h3 className="text-sm font-bold text-slate-800">{title}</h3> : <span />}
        <span className="font-mono text-xs text-slate-400">合计 {valueFormatter ? valueFormatter(total) : `${formatNum(total)} ${unit}`}</span>
      </div>
      <div className={cn("relative w-full overflow-hidden rounded-2xl bg-slate-50/80", size === "large" ? "h-[240px]" : "h-[210px]")}>
        <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title ?? unit} 趋势`}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.24" />
              <stop offset="100%" stopColor={color} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {[0, 0.5, 1].map((ratio) => {
            const y = padding.top + chartHeight * ratio;
            const label = Math.round(max * (1 - ratio));
            return (
              <g key={ratio}>
                <line x1={padding.left} x2={padding.left + chartWidth} y1={y} y2={y} stroke="#e8edf5" strokeWidth="1" />
                <text x={padding.left - 10} y={y + 4} textAnchor="end" className="fill-slate-400 text-[11px]">
                  {formatNum(label)}
                </text>
              </g>
            );
          })}
          {areaPath ? <path d={areaPath} fill={`url(#${gradientId})`} /> : null}
          {linePath ? <path d={linePath} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /> : null}
          {points.map((point) => (
            <g key={point.timestamp}>
              <circle cx={point.x} cy={point.y} r="4.5" fill="white" stroke={color} strokeWidth="2.5" />
              <title>{`${formatLabel(point.timestamp)}: ${valueFormatter ? valueFormatter(point.value) : `${formatNum(point.value)} ${unit}`}`}</title>
            </g>
          ))}
          {points.map((point, index) => {
            const shouldShow = series.length <= 8 || index === 0 || index === series.length - 1 || index % Math.ceil(series.length / 4) === 0;
            if (!shouldShow) return null;
            return (
              <text key={`label-${point.timestamp}`} x={point.x} y={height - 10} textAnchor="middle" className="fill-slate-400 text-[11px]">
                {formatLabel(point.timestamp)}
              </text>
            );
          })}
        </svg>
        {!hasValue ? <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-slate-400">暂无非零数据</div> : null}
      </div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function Ring({ value, label, color }: { value: number; label: string; color: string }) {
  const clamped = Math.max(0, Math.min(value, 100));
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
      <div
        className="flex h-20 w-20 items-center justify-center rounded-full"
        style={{ background: `conic-gradient(${color} ${clamped * 3.6}deg, #e8edf5 0deg)` }}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-sm font-bold text-slate-900">
          {value ? `${clamped.toFixed(0)}%` : "-"}
        </div>
      </div>
      <div>
        <p className="text-sm font-bold text-slate-900">{label}</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">基于当前时间窗口内成功与错误调用计算。</p>
      </div>
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function StatusBreakdown({ items, total }: { items: { status: string; count: number }[]; total: number }) {
  const normalized = items.length ? items : [{ status: "none", count: 0 }];
  return (
    <div className="space-y-2">
      <div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">状态分布</div>
      {normalized.map((item) => {
        const percent = total ? (item.count / total) * 100 : 0;
        return (
          <div key={item.status}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-600">{statusLabel(item.status)}</span>
              <span className="font-mono text-slate-400">{item.count}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className={cn("h-full rounded-full", item.status === "error" ? "bg-rose-500" : "bg-fuchsia-500")} style={{ width: `${percent}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function TokenSplit({ items, title = "Token 拆分" }: { items: { label: string; value: number; color: string }[]; title?: string }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  return (
    <div className="space-y-2">
      <div className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">{title}</div>
      {items.map((item) => {
        const percent = total ? (item.value / total) * 100 : 0;
        return (
          <div key={item.label}>
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-semibold text-slate-600">{item.label}</span>
              <span className="font-mono text-slate-400">{formatNum(item.value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${percent}%`, backgroundColor: item.color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function PricingCoverage({ coverage }: { coverage?: { priced_calls: number; total_calls: number; percent: number } }) {
  const percent = coverage?.percent ?? 0;
  return (
    <div className="rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">价格覆盖率</span>
        <span className="font-mono text-xs font-semibold text-slate-600">{percent.toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-[#6d5cf0]" style={{ width: `${Math.max(0, Math.min(percent, 100))}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {coverage?.priced_calls ?? 0}/{coverage?.total_calls ?? 0} 次调用已匹配模型价格。
      </p>
    </div>
  );
}

function UnpricedModels({ items }: { items: { model_name: string; calls: number; tokens: number; reason: string }[] }) {
  return (
    <Panel title="未计价模型" icon={AlertTriangle} action={<Link className="text-xs font-semibold text-[#6d5cf0] hover:underline" href="/settings">去配置价格</Link>}>
      {items.length === 0 ? (
        <p className="py-10 text-center text-sm text-slate-400">当前窗口内没有未计价模型。</p>
      ) : (
        <div className="max-h-[320px] space-y-3 overflow-y-auto">
          {items.map((item) => (
            <div key={item.model_name} className="rounded-2xl border border-slate-100 bg-slate-50/72 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-900">{item.model_name}</p>
                  <p className="mt-1 text-xs text-slate-500">{reasonLabel(item.reason)}</p>
                </div>
                <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700">未计价</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
                <div className="rounded-xl bg-white px-3 py-2">
                  <p className="text-slate-400">调用</p>
                  <p className="font-mono font-semibold text-slate-700">{item.calls}</p>
                </div>
                <div className="rounded-xl bg-white px-3 py-2">
                  <p className="text-slate-400">Token</p>
                  <p className="font-mono font-semibold text-slate-700">{formatNum(item.tokens)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function AnomalyPanel({
  items,
  loading,
  onIgnore,
  onRepair,
}: {
  items: DashboardAnomaly[];
  loading: boolean;
  onIgnore: (id: string) => void;
  onRepair: (id: string) => void;
}) {
  return (
    <Panel title="Token 异常记录" icon={AlertTriangle} action={loading ? "处理中..." : `${items.length} 条`}>
      {items.length === 0 ? (
        <p className="py-10 text-center text-sm text-slate-400">暂无需要治理的 Token 异常。</p>
      ) : (
        <div className="max-h-[320px] space-y-3 overflow-y-auto">
          {items.map((item) => (
            <div key={item.id} className="rounded-2xl border border-rose-100 bg-rose-50/50 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-900">{item.agent_name || item.agent_id || "unknown agent"}</p>
                  <p className="truncate font-mono text-xs text-slate-500">{item.model_name || "default model"}</p>
                </div>
                <StatusBadge text={item.repairable ? "可确认修正" : "不可重算"} tone={item.repairable ? "amber" : "slate"} />
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                <MiniStat label="Raw" value={formatNum(item.raw_total_tokens ?? 0)} />
                <MiniStat label="修正后" value={formatNum(item.total_tokens ?? 0)} />
                <MiniStat label="来源" value={tokenSourceLabel(item.token_source)} />
                <MiniStat label="时间" value={formatTime(item.created_at) || "-"} />
              </div>
              <div className="mt-3 flex justify-end gap-2">
                {item.repairable ? (
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => onRepair(item.id)}
                    className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-50"
                  >
                    确认估算修正
                  </button>
                ) : null}
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => onIgnore(item.id)}
                  className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 shadow-sm ring-1 ring-rose-200 hover:bg-rose-50 disabled:opacity-50"
                >
                  忽略异常
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function RecentLogs({ logs }: { logs: LogRow[] }) {
  return (
    <Panel title="最近调用" icon={Activity}>
      {logs.length === 0 ? (
        <p className="py-12 text-center text-sm text-slate-400">暂无调用记录</p>
      ) : (
        <div className="max-h-[470px] divide-y divide-slate-100 overflow-y-auto">
          {logs.map((log) => (
            <div key={log.id} className="grid grid-cols-[10px_1fr_auto] items-center gap-3 py-3">
              <span className={cn("h-2.5 w-2.5 rounded-full", log.status === "error" ? "bg-rose-500" : "bg-fuchsia-500")} />
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-800">{log.agent_name || log.agent_id || "unknown agent"}</p>
                <p className="truncate font-mono text-xs text-slate-400">{log.model_name || "default model"}</p>
                <p className="mt-1 truncate text-xs text-slate-400">
                  {log.tools_used?.length ? `工具：${log.tools_used.join(", ")}` : "未记录工具调用"}
                </p>
              </div>
              <div className="space-y-1 text-right font-mono text-xs text-slate-400">
                <p>{log.latency_ms}ms</p>
                <StatusBadge text={recentLogBadge(log)} tone={recentLogBadgeTone(log)} />
                <p>{formatNum(log.total_tokens)} tok</p>
                <p>{log.priced ? formatCost(log.total_cost ?? 0, log.currency) : reasonLabel(log.price_missing_reason)}</p>
                <p>{formatTime(log.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function RankMetricSwitch({ value, onChange }: { value: RankMetric; onChange: (value: RankMetric) => void }) {
  const options: { key: RankMetric; label: string }[] = [
    { key: "calls", label: "调用" },
    { key: "tokens", label: "Token" },
    { key: "cost", label: "成本" },
  ];
  return (
    <div className="flex rounded-xl border border-slate-200 bg-white p-0.5">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          onClick={() => onChange(option.key)}
          className={cn(
            "rounded-lg px-2.5 py-1 text-xs font-semibold transition",
            value === option.key ? "bg-slate-950 text-white" : "text-slate-500 hover:bg-slate-50",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function RankPanel({
  title,
  icon,
  rows,
  compact,
  action,
}: {
  title: string;
  icon: LucideIcon;
  rows: { id: string; name: string; meta: string; value: number }[];
  compact?: boolean;
  action?: ReactNode;
}) {
  const max = Math.max(...rows.map((item) => item.value), 1);
  return (
    <Panel title={title} icon={icon} action={action}>
      {rows.length === 0 ? (
        <p className={cn("text-center text-sm text-slate-400", compact ? "py-8" : "py-12")}>暂无数据</p>
      ) : (
        <div className={cn("space-y-4", compact && "space-y-3")}>
          {rows.map((row) => (
            <div key={row.id}>
              <div className="mb-1.5 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-800">{row.name}</p>
                  <p className="truncate text-xs text-slate-400">{row.meta}</p>
                </div>
                <span className="font-mono text-xs text-slate-400">{formatNum(row.value)}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-[#6d5cf0]" style={{ width: `${(row.value / max) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white px-3 py-2">
      <p className="text-slate-400">{label}</p>
      <p className="truncate font-mono font-semibold text-slate-700">{value}</p>
    </div>
  );
}

function StatusBadge({ text, tone }: { text: string; tone: "blue" | "teal" | "amber" | "rose" | "slate" }) {
  const tones = {
    blue: "bg-violet-50 text-violet-700",
    teal: "bg-fuchsia-50 text-fuchsia-700",
    amber: "bg-amber-50 text-amber-700",
    rose: "bg-rose-50 text-rose-700",
    slate: "bg-slate-100 text-slate-600",
  };
  return <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone])}>{text}</span>;
}

function normalizeSeries(data: TimeSeriesPoint[], days: number): TimeSeriesPoint[] {
  if (days <= 1 || data.some((item) => item.timestamp.includes("T"))) {
    return fillHourlySeries(data);
  }
  const byDay = new Map(data.map((item) => [item.timestamp.slice(0, 10), item]));
  const today = new Date();
  return Array.from({ length: days }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (days - 1 - index));
    const key = date.toISOString().slice(0, 10);
    return byDay.get(key) ?? { timestamp: key, value: 0 };
  });
}

function fillHourlySeries(data: TimeSeriesPoint[]) {
  if (!data.length) return [];
  const byHour = new Map(data.map((item) => [item.timestamp.slice(0, 13), item]));
  const start = new Date(data[0].timestamp);
  const end = new Date(data[data.length - 1].timestamp);
  const result: TimeSeriesPoint[] = [];
  for (const cursor = new Date(start); cursor <= end; cursor.setHours(cursor.getHours() + 1)) {
    const key = cursor.toISOString().slice(0, 13);
    result.push(byHour.get(key) ?? { timestamp: `${key}:00`, value: 0 });
  }
  return result.length ? result : data;
}

function formatLabel(timestamp: string) {
  if (timestamp.includes("T")) return timestamp.slice(11, 16);
  return timestamp.slice(5);
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    success: "成功",
    error: "错误",
    interrupted: "中断",
    none: "暂无",
  };
  return map[status] ?? status;
}

function formatNum(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(Math.round(value));
}

function formatCost(value?: number, currency = "USD") {
  if (!value) return "-";
  const symbol = currency === "CNY" ? "¥" : currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${value < 0.01 ? value.toFixed(6) : value.toFixed(4)}`;
}

function formatCostMap(values?: Record<string, number>, fallback = 0, fallbackCurrency = "USD") {
  const entries = Object.entries(values ?? {}).filter(([, value]) => value > 0);
  if (!entries.length) return formatCost(fallback, fallbackCurrency);
  return entries.map(([currency, value]) => formatCost(value, currency)).join(" / ");
}

function tokenSourceLabel(source?: string) {
  const labels: Record<string, string> = {
    provider_reported: "真实",
    estimated: "估算",
    missing_estimated: "缺失估算",
    anomaly_corrected: "异常修正",
    ignored: "异常忽略",
  };
  return labels[source || ""] ?? "异常";
}

function reasonLabel(reason?: string) {
  const labels: Record<string, string> = {
    missing_model_name: "缺少模型名",
    model_price_not_configured: "未配置模型价格",
    ambiguous_or_unmanaged_model: "同名模型未绑定供应商或未配置价格",
  };
  return labels[reason || ""] ?? "未计价";
}

function recentLogBadge(log: LogRow) {
  if (log.token_usage_anomalous) return tokenSourceLabel(log.token_source);
  if (log.token_estimated) return "估算";
  if (!log.priced && log.total_tokens > 0) return "未计价";
  return "正常";
}

function recentLogBadgeTone(log: LogRow): "blue" | "teal" | "amber" | "rose" | "slate" {
  if (log.token_usage_anomalous) return "rose";
  if (log.token_estimated || (!log.priced && log.total_tokens > 0)) return "amber";
  return "teal";
}

function rankValue(item: { calls: number; tokens: number; cost: number }, metric: RankMetric) {
  if (metric === "tokens") return item.tokens;
  if (metric === "cost") return item.cost;
  return item.calls;
}

function toneClass(tone: "blue" | "teal" | "amber" | "rose" | "emerald") {
  const tones = {
    blue: "bg-sky-50 text-sky-700",
    teal: "bg-fuchsia-50 text-fuchsia-700",
    amber: "bg-amber-50 text-amber-700",
    rose: "bg-rose-50 text-rose-700",
    emerald: "bg-emerald-50 text-emerald-700",
  };
  return tones[tone];
}
