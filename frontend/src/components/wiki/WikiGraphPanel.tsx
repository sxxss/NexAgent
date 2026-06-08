"use client";

import "reactflow/dist/style.css";

import { useMemo } from "react";
import ReactFlow, { Background, Controls, MiniMap, Handle, Position, type Edge, type Node, type NodeProps } from "reactflow";
import { ExternalLink, GitBranch, RefreshCw, Search } from "lucide-react";
import { type WikiGraphPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface WikiGraphOptions {
  q: string;
  maxEdges: number;
  includeWeak: boolean;
}

interface WikiNodeData {
  label: string;
  type: string;
  confidence: string;
  sources: number;
  community: number;
  degree: number;
}

const nodeTypes = { wikiNode: WikiNode };

export function WikiGraphPanel({
  graph,
  options,
  fullscreen = false,
  onOptionsChange,
  onNodeSelect,
  onOpenPage,
  onReload,
}: {
  graph: WikiGraphPayload | null;
  options?: WikiGraphOptions;
  fullscreen?: boolean;
  onOptionsChange?: (options: WikiGraphOptions) => void;
  onNodeSelect?: (pageId: string) => void;
  onOpenPage?: () => void;
  onReload: () => Promise<void>;
}) {
  const effectiveOptions = options ?? { q: "", maxEdges: 80, includeWeak: false };
  const { nodes, edges, degrees } = useMemo(() => buildFlowGraph(graph), [graph]);
  const stats = graph?.stats ?? {};
  const coreNodes = useMemo(
    () =>
      (graph?.nodes ?? [])
        .map((node) => ({ ...node, degree: degrees.get(node.id) ?? 0 }))
        .filter((node) => node.degree > 0)
        .sort((left, right) => right.degree - left.degree || left.label.localeCompare(right.label))
        .slice(0, 10),
    [degrees, graph?.nodes],
  );
  const pageTitle = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node.label])), [graph?.nodes]);

  const updateOption = (patch: Partial<WikiGraphOptions>) => {
    onOptionsChange?.({ ...effectiveOptions, ...patch });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700"><GitBranch size={16} /></span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Wiki 关系图</h3>
            <p className="text-xs text-slate-500">{nodes.length} nodes · {edges.length} edges</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <GraphStat label="页面" value={Number(stats.total_nodes ?? stats.pages ?? nodes.length)} />
          <GraphStat label="展示关系" value={Number(stats.display_edge_count ?? stats.total_edges ?? edges.length)} />
          <GraphStat label="原始关系" value={Number(stats.raw_edge_count ?? stats.edges ?? edges.length)} />
          <GraphStat label="社区" value={Number(stats.communities ?? 0)} />
          {onOpenPage ? <button type="button" onClick={onOpenPage} className={iconButton} title="打开图谱详细页"><ExternalLink size={14} /></button> : null}
          <button type="button" onClick={() => void onReload()} className={iconButton} title="刷新图谱"><RefreshCw size={14} /></button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-3">
        <div className="relative min-w-56 flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={effectiveOptions.q}
            onChange={(event) => updateOption({ q: event.target.value })}
            placeholder="聚焦关键词"
            className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-xs text-slate-700 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
          />
        </div>
        <label className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600">
          关系数
          <input
            type="number"
            min={20}
            max={300}
            value={effectiveOptions.maxEdges}
            onChange={(event) => updateOption({ maxEdges: Number(event.target.value) || 80 })}
            className="h-6 w-16 rounded border border-slate-200 px-1.5 text-xs outline-none"
          />
        </label>
        <label className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600">
          <input
            type="checkbox"
            checked={effectiveOptions.includeWeak}
            onChange={(event) => updateOption({ includeWeak: event.target.checked })}
            className="h-4 w-4 accent-indigo-600"
          />
          {effectiveOptions.includeWeak ? "包含弱关系" : "核心关系"}
        </label>
      </div>

      <div className={cn("grid gap-4", fullscreen ? "xl:grid-cols-[minmax(0,1fr)_300px]" : "xl:grid-cols-[minmax(0,1fr)_260px]")}>
        <div className={cn("overflow-hidden rounded-xl border border-slate-200 bg-white", fullscreen ? "h-[calc(100vh-300px)] min-h-[620px]" : "h-[620px]")}>
          {nodes.length ? (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              onNodeClick={(_event, node) => onNodeSelect?.(node.id)}
            >
              <Background gap={18} size={1} color="#e2e8f0" />
              <MiniMap pannable zoomable nodeColor={(node) => nodeColor((node.data as WikiNodeData).type)} />
              <Controls showInteractive={false} />
            </ReactFlow>
          ) : (
            <div className="flex h-full flex-col items-center justify-center text-sm text-slate-400">
              <GitBranch size={32} className="mb-3 text-slate-300" />
              暂无 Wiki 图谱
            </div>
          )}
        </div>

        <aside className="grid content-start gap-3">
          <section className="rounded-xl border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-semibold text-slate-700">节点类型</h4>
            <div className="mt-2 grid gap-1.5">
              {typeLegend.map((item) => (
                <div key={item.type} className="flex items-center gap-2 text-xs text-slate-600">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: item.color }} />
                  {item.label}
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-xl border border-slate-200 bg-white p-3">
            <h4 className="text-xs font-semibold text-slate-700">核心节点</h4>
            <div className="mt-2 grid gap-1.5">
              {coreNodes.length ? coreNodes.map((node) => (
                <button key={node.id} type="button" onClick={() => onNodeSelect?.(node.id)} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-600 hover:bg-indigo-50 hover:text-indigo-700">
                  <span className="min-w-0 truncate">{node.label}</span>
                  <Badge variant="secondary">{node.degree}</Badge>
                </button>
              )) : <span className="text-xs text-slate-400">暂无核心节点</span>}
            </div>
          </section>
        </aside>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h4 className="text-xs font-semibold text-slate-700">关系详情</h4>
          <span className="text-[11px] text-slate-400">{graph?.edges?.length ?? 0}</span>
        </div>
        <div className="max-h-72 overflow-auto">
          {graph?.edges?.length ? graph.edges.map((edge, index) => (
            <div key={`${edge.source}-${edge.target}-${index}`} className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-600 last:border-0">
              <button type="button" onClick={() => onNodeSelect?.(edge.source)} className="font-semibold text-slate-800 hover:text-indigo-700">{pageTitle.get(edge.source) ?? edge.source}</button>
              <span className="text-slate-300">{"->"}</span>
              <button type="button" onClick={() => onNodeSelect?.(edge.target)} className="font-semibold text-slate-800 hover:text-indigo-700">{pageTitle.get(edge.target) ?? edge.target}</button>
              <Badge variant="secondary">权重 {edge.weight}</Badge>
              {edge.signals?.wikilink ? <Badge variant="info">双链</Badge> : <Badge variant="secondary">推断</Badge>}
              {Array.isArray(edge.signals?.source_overlap) && edge.signals.source_overlap.length ? <Badge variant="success">同源</Badge> : null}
              {Array.isArray(edge.signals?.common_neighbors) && edge.signals.common_neighbors.length ? <Badge variant="warning">共邻</Badge> : null}
            </div>
          )) : <div className="px-4 py-8 text-center text-xs text-slate-400">暂无关系</div>}
        </div>
      </section>
    </div>
  );
}

function WikiNode({ data }: NodeProps<WikiNodeData>) {
  return (
    <div className={cn("min-w-40 max-w-56 rounded-xl border bg-white px-3 py-2 shadow-sm", nodeBorder(data.type))}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !bg-slate-300" />
      <p className="line-clamp-2 text-sm font-semibold leading-5 text-slate-900">{data.label}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant="secondary">{pageTypeLabel(data.type)}</Badge>
        <Badge variant={data.confidence === "EXTRACTED" ? "success" : data.confidence === "INFERRED" ? "info" : "warning"}>{data.confidence}</Badge>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">{data.sources} sources · {data.degree} links · C{data.community}</p>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !bg-slate-300" />
    </div>
  );
}

function buildFlowGraph(graph: WikiGraphPayload | null): { nodes: Node<WikiNodeData>[]; edges: Edge[]; degrees: Map<string, number> } {
  const degrees = new Map<string, number>();
  for (const edge of graph?.edges ?? []) {
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  }
  if (!graph?.nodes?.length) return { nodes: [], edges: [], degrees };
  const byCommunity = new Map<number, number>();
  for (const node of graph.nodes) byCommunity.set(node.community, (byCommunity.get(node.community) ?? 0) + 1);
  const seenCommunity = new Map<number, number>();
  const total = graph.nodes.length;
  const radius = Math.max(240, Math.min(660, total * 22));
  const nodes: Node<WikiNodeData>[] = graph.nodes.map((node, index) => {
    const communityIndex = seenCommunity.get(node.community) ?? 0;
    seenCommunity.set(node.community, communityIndex + 1);
    const communitySize = byCommunity.get(node.community) || 1;
    const communityAngle = ((node.community - 1) / Math.max(1, byCommunity.size)) * Math.PI * 2;
    const localAngle = (communityIndex / communitySize) * Math.PI * 2;
    const localRadius = Math.max(80, Math.min(180, communitySize * 28));
    return {
      id: node.id,
      type: "wikiNode",
      position: {
        x: Math.cos(communityAngle) * radius + Math.cos(localAngle) * localRadius + radius + 260,
        y: Math.sin(communityAngle) * radius + Math.sin(localAngle) * localRadius + radius + 180 + index * 0.01,
      },
      data: {
        label: node.label,
        type: node.type,
        confidence: node.confidence,
        sources: node.sources.length,
        community: node.community,
        degree: degrees.get(node.id) ?? 0,
      },
    };
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: Edge[] = (graph.edges ?? [])
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.signals?.wikilink ? "双链" : "",
      animated: Boolean(edge.signals?.source_overlap),
      style: { stroke: edge.signals?.wikilink ? "#4f46e5" : "#94a3b8", strokeWidth: Math.max(1, Math.min(4, edge.weight)) },
      labelStyle: { fill: "#4f46e5", fontSize: 10, fontWeight: 700 },
    }));
  return { nodes, edges, degrees };
}

function GraphStat({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex h-8 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-600">
      <span className="text-slate-400">{label}</span>
      {value}
    </span>
  );
}

function nodeColor(type: string) {
  if (type === "source") return "#0ea5e9";
  if (type === "entity") return "#10b981";
  if (type === "topic") return "#f59e0b";
  if (type === "synthesis") return "#8b5cf6";
  return "#64748b";
}

function nodeBorder(type: string) {
  if (type === "source") return "border-sky-200";
  if (type === "entity") return "border-emerald-200";
  if (type === "topic") return "border-amber-200";
  if (type === "synthesis") return "border-violet-200";
  return "border-slate-200";
}

function pageTypeLabel(type: string) {
  return {
    source: "来源",
    entity: "实体",
    topic: "主题",
    synthesis: "综合",
    comparison: "对比",
    query: "问答",
    note: "笔记",
  }[type] ?? type;
}

const typeLegend = [
  { type: "source", label: "来源页", color: "#0ea5e9" },
  { type: "topic", label: "主题页", color: "#f59e0b" },
  { type: "entity", label: "实体页", color: "#10b981" },
  { type: "synthesis", label: "综合页", color: "#8b5cf6" },
  { type: "note", label: "笔记页", color: "#64748b" },
];

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";
