"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import "reactflow/dist/style.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "reactflow";
import { ArrowLeft, Copy, Eye, EyeOff, GitBranch, Loader2, Maximize2, Network, RefreshCw, RotateCcw, Search, X } from "lucide-react";
import {
  fetchKBs,
  fetchKnowledgeGraph,
  fetchKnowledgeGraphSummary,
  fetchKnowledgeSubgraph,
  searchKnowledgeGraph,
  type GraphEdge,
  type GraphNode,
  type KBMeta,
  type KnowledgeGraph,
  type KnowledgeGraphSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn, formatDate } from "@/lib/utils";

type ViewMode = "empty" | "whole" | "subgraph";

interface EntityNodeData {
  label: string;
  fullLabel: string;
  count: number;
  degree: number;
  index: number;
  active: boolean;
  adjacent: boolean;
  muted: boolean;
  noise: boolean;
}

const wholeLimits = [100, 300, 600, 1000];
const depths = [1, 2, 3];
const subgraphLimits = [60, 120, 300];
const noiseTerms = new Set(["style", "stroke", "fill", "classdef", "linkstyle", "transparent", "none", "color", "data"]);
const graphNodeTypes = { entity: EntityNode };
const graphButton = "inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition-all duration-200 hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-sm disabled:translate-y-0 disabled:opacity-40 disabled:shadow-none";
const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition-all duration-200 hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-sm disabled:translate-y-0 disabled:opacity-40 disabled:shadow-none";

export default function KnowledgeGraphPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [kb, setKb] = useState<KBMeta | null>(null);
  const [summary, setSummary] = useState<KnowledgeGraphSummary | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [mode, setMode] = useState<ViewMode>("empty");
  const [search, setSearch] = useState("");
  const [wholeLimit, setWholeLimit] = useState(300);
  const [depth, setDepth] = useState(1);
  const [subgraphLimit, setSubgraphLimit] = useState(120);
  const [showNoise, setShowNoise] = useState(false);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);

  const loadSummary = useCallback(async () => {
    setLoadingSummary(true);
    setError("");
    try {
      const [kbs, nextSummary] = await Promise.all([fetchKBs(), fetchKnowledgeGraphSummary(id)]);
      const found = kbs.find((item) => item.kb_id === id) ?? null;
      setKb(found);
      setSummary(nextSummary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图谱摘要加载失败");
    } finally {
      setLoadingSummary(false);
    }
  }, [id]);

  useEffect(() => { void loadSummary(); }, [loadSummary]);

  const loadWholeGraph = useCallback(async () => {
    setLoadingGraph(true);
    setNotice("");
    setError("");
    try {
      const next = await fetchKnowledgeGraph(id, wholeLimit);
      setGraph(next);
      setSelected(null);
      setMode(next?.nodes?.length ? "whole" : "empty");
      window.requestAnimationFrame(() => flow?.fitView({ padding: 0.18, duration: 300 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "整图加载失败");
    } finally {
      setLoadingGraph(false);
    }
  }, [flow, id, wholeLimit]);

  const loadSubgraph = useCallback(async (nodeName: string) => {
    if (!nodeName.trim()) return;
    setLoadingGraph(true);
    setNotice("");
    setError("");
    try {
      const next = await fetchKnowledgeSubgraph(id, nodeName, depth, subgraphLimit);
      setGraph(next);
      setSelected(next.nodes.find((node) => node.name === nodeName) ?? { name: nodeName, count: 0, files: [] });
      setMode("subgraph");
      window.requestAnimationFrame(() => flow?.fitView({ padding: 0.2, duration: 300 }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "邻域子图加载失败");
    } finally {
      setLoadingGraph(false);
    }
  }, [depth, flow, id, subgraphLimit]);

  const runSearch = async () => {
    const query = search.trim();
    if (!query) {
      setNotice("请输入实体名称或关键词后再搜索。");
      return;
    }
    setLoadingGraph(true);
    setNotice("");
    setError("");
    try {
      const result = await searchKnowledgeGraph(id, query, 20);
      if (!result.nodes[0]) {
        setNotice(`未找到与“${query}”匹配的实体。`);
        return;
      }
      await loadSubgraph(result.nodes[0].name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图谱搜索失败");
    } finally {
      setLoadingGraph(false);
    }
  };

  const reloadCurrent = () => {
    if (mode === "whole") void loadWholeGraph();
    else if (mode === "subgraph" && selected) void loadSubgraph(selected.name);
    else void loadSummary();
  };

  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = useMemo(() => graph?.edges ?? [], [graph]);
  const noiseNodeCount = useMemo(() => nodes.filter((node) => isNoiseEntity(node.name)).length, [nodes]);
  const visibleNodes = useMemo(() => nodes.filter((node) => showNoise || !isNoiseEntity(node.name)), [nodes, showNoise]);
  const visibleNodeNames = useMemo(() => new Set(visibleNodes.map((node) => node.name)), [visibleNodes]);
  const visibleEdges = useMemo(() => edges.filter((edge) => visibleNodeNames.has(edge.source) && visibleNodeNames.has(edge.target)), [edges, visibleNodeNames]);
  const selectedEdges = useMemo(() => selected ? visibleEdges.filter((edge) => edge.source === selected.name || edge.target === selected.name) : [], [selected, visibleEdges]);

  const unsupported = kb && kb.kb_type !== "lightrag";

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-1.5 text-xs text-slate-400">
              <button onClick={() => router.push("/knowledge")} className="hover:text-slate-600">知识库</button>
              <span>/</span>
              <button onClick={() => router.push(`/knowledge/${id}`)} className="truncate hover:text-slate-600">{kb?.name ?? "加载中"}</button>
              <span>/</span>
              <span className="text-slate-600">图谱浏览</span>
            </div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-slate-950"><Network size={20} className="text-indigo-600" />图谱工作台</h1>
            <p className="mt-1 text-sm text-slate-500">按需渲染整图或实体邻域，查看关系、来源和上下文。</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => router.push(`/knowledge/${id}`)} className={graphButton}><ArrowLeft size={14} />返回详情</button>
            <button type="button" onClick={reloadCurrent} className={iconButton} title="重新加载"><RefreshCw size={14} /></button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 p-4">
        {unsupported ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
            <Network className="mx-auto text-slate-300" size={36} />
            <p className="mt-3 text-sm font-semibold text-slate-900">当前知识库不是 LightRAG 图谱类型</p>
            <p className="mt-1 text-xs text-slate-500">向量 RAG 知识库不提供图谱浏览入口。</p>
          </div>
        ) : (
          <div className="grid h-full min-h-[720px] gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
              <GraphToolbar
                search={search}
                setSearch={setSearch}
                wholeLimit={wholeLimit}
                setWholeLimit={setWholeLimit}
                depth={depth}
                setDepth={setDepth}
                subgraphLimit={subgraphLimit}
                setSubgraphLimit={setSubgraphLimit}
                loading={loadingGraph}
                onSearch={runSearch}
                onLoadWhole={loadWholeGraph}
                onFit={() => flow?.fitView({ padding: 0.18, duration: 300 })}
                onClear={() => setSelected(null)}
              />
              <GraphStatusBar
                summary={summary}
                loading={loadingSummary}
                nodeCount={visibleNodes.length}
                edgeCount={visibleEdges.length}
                mode={mode}
                showNoise={showNoise}
                hiddenNoiseCount={showNoise ? 0 : noiseNodeCount}
                onToggleNoise={() => setShowNoise(!showNoise)}
              />
              {notice ? <div className="mx-4 mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">{notice}</div> : null}
              {error ? <div className="mx-4 mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
              <div className="min-h-0 flex-1">
                {!visibleNodes.length ? (
                  <GraphEmptyState loading={loadingGraph || loadingSummary} onLoadWhole={loadWholeGraph} />
                ) : (
                  <GraphCanvas
                    nodes={visibleNodes}
                    edges={visibleEdges}
                    selected={selected?.name ?? ""}
                    onSelect={setSelected}
                    onExpand={(node) => void loadSubgraph(node.name)}
                    onInit={setFlow}
                  />
                )}
              </div>
            </section>

            <GraphInspector
              selected={selected}
              edges={selectedEdges}
              mode={mode}
              onCopy={(value) => void navigator.clipboard?.writeText(value)}
              onExpand={(node) => void loadSubgraph(node.name)}
              onLoadWhole={loadWholeGraph}
              onClear={() => setSelected(null)}
            />
          </div>
        )}
      </main>
      <style jsx global>{`
        @keyframes graphNodeIn {
          from {
            opacity: 0;
            transform: translateY(8px) scale(0.98);
          }
          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }

        @keyframes graphPanelIn {
          from {
            opacity: 0;
            transform: translateY(6px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .react-flow__edge.graph-edge-active path {
          stroke-dasharray: 7 6;
          animation: graphEdgeFlow 1.2s linear infinite;
        }

        @keyframes graphEdgeFlow {
          to {
            stroke-dashoffset: -26;
          }
        }
      `}</style>
    </div>
  );
}

function GraphToolbar({
  search,
  setSearch,
  wholeLimit,
  setWholeLimit,
  depth,
  setDepth,
  subgraphLimit,
  setSubgraphLimit,
  loading,
  onSearch,
  onLoadWhole,
  onFit,
  onClear,
}: {
  search: string;
  setSearch: (value: string) => void;
  wholeLimit: number;
  setWholeLimit: (value: number) => void;
  depth: number;
  setDepth: (value: number) => void;
  subgraphLimit: number;
  setSubgraphLimit: (value: number) => void;
  loading: boolean;
  onSearch: () => void;
  onLoadWhole: () => void;
  onFit: () => void;
  onClear: () => void;
}) {
  return (
    <div className="border-b border-slate-100 bg-white/95 p-4">
      <div className="grid gap-3 xl:grid-cols-[minmax(280px,1fr)_auto]">
        <div className="flex min-w-0 gap-2">
          <Input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => event.key === "Enter" && onSearch()} placeholder="搜索实体，例如 K1、模型、配置" />
          <button type="button" onClick={onSearch} disabled={loading} className={cn(iconButton, "border-sky-600 bg-sky-600 text-white hover:bg-sky-700")}>{loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}</button>
        </div>
        <div className="flex flex-wrap items-center justify-start gap-2 xl:justify-end">
          <button type="button" onClick={onLoadWhole} disabled={loading} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 text-xs font-semibold text-white shadow-sm shadow-indigo-100 transition-all duration-200 hover:-translate-y-0.5 hover:bg-indigo-700 hover:shadow-md disabled:translate-y-0 disabled:opacity-40 disabled:shadow-none"><GitBranch size={14} />渲染整图</button>
          <button type="button" onClick={onFit} className={iconButton} title="适配视图"><Maximize2 size={14} /></button>
          <button type="button" onClick={onClear} className={iconButton} title="清除选择"><X size={14} /></button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Segmented label="整图" value={wholeLimit} values={wholeLimits} onChange={setWholeLimit} />
        <Segmented label="深度" value={depth} values={depths} suffix="跳" onChange={setDepth} />
        <Segmented label="子图" value={subgraphLimit} values={subgraphLimits} onChange={setSubgraphLimit} />
        <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-400">
          单击选择节点，双击展开邻域
        </div>
      </div>
    </div>
  );
}

function Segmented({ label, value, values, suffix = "", onChange }: { label: string; value: number; values: number[]; suffix?: string; onChange: (value: number) => void }) {
  return (
    <div className="flex h-9 items-center gap-1 rounded-lg border border-slate-200 bg-white p-1 text-xs font-semibold text-slate-500 shadow-sm shadow-slate-100/60">
      <span className="px-2 text-slate-400">{label}</span>
      {values.map((item) => (
        <button key={item} type="button" onClick={() => onChange(item)} className={cn("h-7 rounded-md px-2 transition-all duration-200 hover:bg-slate-50", value === item && "bg-indigo-50 text-indigo-700 shadow-sm shadow-indigo-100")}>{item}{suffix}</button>
      ))}
    </div>
  );
}

function GraphStatusBar({
  summary,
  loading,
  nodeCount,
  edgeCount,
  mode,
  showNoise,
  hiddenNoiseCount,
  onToggleNoise,
}: {
  summary: KnowledgeGraphSummary | null;
  loading: boolean;
  nodeCount: number;
  edgeCount: number;
  mode: ViewMode;
  showNoise: boolean;
  hiddenNoiseCount: number;
  onToggleNoise: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/80 px-4 py-3 text-xs text-slate-500">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="violet">LightRAG</Badge>
        <span>{loading ? "摘要加载中..." : `${summary?.stats?.nodes ?? 0} entities · ${summary?.stats?.edges ?? 0} relations`}</span>
        {summary?.updated_at ? <span>更新于 {formatDate(summary.updated_at)}</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span>{modeLabel(mode)} · 当前画布 {nodeCount} 节点 / {edgeCount} 关系{hiddenNoiseCount ? ` · 已隐藏 ${hiddenNoiseCount} 噪声节点` : ""}</span>
        <button
          type="button"
          onClick={onToggleNoise}
          title="过滤 Mermaid/SVG/HTML 样式词、颜色值和技术属性节点。"
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-semibold transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm",
            showNoise ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-white text-slate-600",
          )}
        >
          {showNoise ? <Eye size={12} /> : <EyeOff size={12} />}
          噪声节点：{showNoise ? "已显示" : "已隐藏"}
        </button>
      </div>
    </div>
  );
}

function GraphEmptyState({ loading, onLoadWhole }: { loading: boolean; onLoadWhole: () => void }) {
  return (
    <div className="flex h-full min-h-[520px] items-center justify-center bg-[radial-gradient(circle_at_center,#f8fafc_0,#f8fafc_45%,#f1f5f9_100%)]">
      <div className="max-w-sm animate-[graphPanelIn_240ms_ease-out] text-center">
        <div className="mx-auto flex h-16 w-16 animate-pulse items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-300 shadow-sm">
          <Network size={34} />
        </div>
        <p className="mt-4 text-sm font-semibold text-slate-900">{loading ? "图谱加载中..." : "尚未渲染图谱"}</p>
        <p className="mt-2 text-xs leading-5 text-slate-500">默认只加载摘要。点击渲染整图，或搜索实体后展开邻域子图。</p>
        <button type="button" onClick={onLoadWhole} disabled={loading} className="mt-4 inline-flex h-10 items-center gap-2 rounded-lg bg-indigo-600 px-4 text-sm font-semibold text-white shadow-sm shadow-indigo-100 transition-all duration-200 hover:-translate-y-0.5 hover:bg-indigo-700 hover:shadow-md disabled:translate-y-0 disabled:opacity-40 disabled:shadow-none">
          {loading ? <Loader2 size={15} className="animate-spin" /> : <GitBranch size={15} />}
          渲染整图
        </button>
      </div>
    </div>
  );
}

function GraphCanvas({ nodes, edges, selected, onSelect, onExpand, onInit }: { nodes: GraphNode[]; edges: GraphEdge[]; selected: string; onSelect: (node: GraphNode) => void; onExpand: (node: GraphNode) => void; onInit: (flow: ReactFlowInstance) => void }) {
  const degree = useMemo(() => {
    const next = new Map<string, number>();
    edges.forEach((edge) => {
      next.set(edge.source, (next.get(edge.source) ?? 0) + 1);
      next.set(edge.target, (next.get(edge.target) ?? 0) + 1);
    });
    return next;
  }, [edges]);
  const adjacent = useMemo(() => {
    if (!selected) return new Set<string>();
    const next = new Set<string>([selected]);
    edges.forEach((edge) => {
      if (edge.source === selected) next.add(edge.target);
      if (edge.target === selected) next.add(edge.source);
    });
    return next;
  }, [edges, selected]);
  const graphNodes = useMemo<Node<EntityNodeData>[]>(() => {
    const ordered = [...nodes].sort((a, b) => (degree.get(b.name) ?? 0) - (degree.get(a.name) ?? 0));
    const columns = Math.ceil(Math.sqrt(Math.max(ordered.length, 1)));
    return ordered.map((node, index) => {
      const nodeDegree = degree.get(node.name) ?? 0;
      const active = selected === node.name;
      const near = !selected || adjacent.has(node.name);
      const size = Math.min(210, 128 + Math.log((node.count || 0) + 1) * 18 + Math.min(nodeDegree, 10) * 3);
      return {
        id: node.name,
        type: "entity",
        position: { x: (index % columns) * 220 + 40, y: Math.floor(index / columns) * 118 + 40 },
        data: {
          label: truncateNodeLabel(node.name),
          fullLabel: node.name,
          count: node.count ?? 0,
          degree: nodeDegree,
          index,
          active,
          adjacent: selected ? adjacent.has(node.name) : false,
          muted: Boolean(selected && !near),
          noise: isNoiseEntity(node.name),
        },
        draggable: true,
        style: { width: size },
      };
    });
  }, [adjacent, degree, nodes, selected]);
  const nodeSet = useMemo(() => new Set(nodes.map((node) => node.name)), [nodes]);
  const graphEdges = useMemo<Edge[]>(() => edges.filter((edge) => nodeSet.has(edge.source) && nodeSet.has(edge.target)).map((edge, index) => {
    const active = selected && (edge.source === selected || edge.target === selected);
    const muted = selected && !active;
    return {
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: active ? (edge.relation || "related") : undefined,
      animated: Boolean(active),
      style: { stroke: active ? "#4338ca" : "#cbd5e1", strokeWidth: active ? 2.4 : 1, opacity: muted ? 0.18 : 0.72 },
      labelStyle: { fill: "#4338ca", fontSize: 10, fontWeight: 700 },
      labelBgPadding: [5, 3],
      labelBgBorderRadius: 4,
      labelBgStyle: { fill: "#eef2ff", fillOpacity: 0.95 },
      className: active ? "graph-edge-active" : undefined,
    };
  }), [edges, nodeSet, selected]);
  return (
    <div className="h-full min-h-[560px] bg-[linear-gradient(180deg,#f8fafc_0%,#f1f5f9_100%)]">
      <ReactFlow
        nodeTypes={graphNodeTypes}
        nodes={graphNodes}
        edges={graphEdges}
        fitView
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        onInit={onInit}
        onNodeClick={(_, node) => {
          const original = nodes.find((item) => item.name === node.id);
          if (original) onSelect(original);
        }}
        onNodeDoubleClick={(_, node) => {
          const original = nodes.find((item) => item.name === node.id);
          if (original) onExpand(original);
        }}
      >
        <Background color="#dbe3ef" gap={22} />
        <MiniMap pannable zoomable nodeStrokeWidth={3} nodeColor={(node) => node.data?.active ? "#4338ca" : node.data?.noise ? "#f59e0b" : "#6366f1"} />
        <Controls />
      </ReactFlow>
    </div>
  );
}

function EntityNode({ data }: NodeProps<EntityNodeData>) {
  return (
    <div
      title={data.fullLabel}
      style={{ animationDelay: `${Math.min(data.index, 20) * 18}ms` }}
      className={cn(
        "animate-[graphNodeIn_260ms_ease-out_both] rounded-lg border bg-white px-3 py-2 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:scale-[1.02] hover:border-sky-200 hover:shadow-md",
        data.active && "border-sky-500 bg-sky-50 shadow-lg shadow-sky-100",
        data.adjacent && !data.active && "border-sky-200 shadow-sky-50",
        data.muted && "opacity-25",
        data.noise && !data.active && "border-amber-200 bg-amber-50 text-amber-800",
      )}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <p className="truncate text-xs font-bold text-slate-900">{data.label}</p>
      <p className="mt-1 text-[10px] font-semibold text-slate-400">{data.count} 次 · {data.degree} 关系</p>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  );
}

function GraphInspector({ selected, edges, mode, onCopy, onExpand, onLoadWhole, onClear }: { selected: GraphNode | null; edges: GraphEdge[]; mode: ViewMode; onCopy: (value: string) => void; onExpand: (node: GraphNode) => void; onLoadWhole: () => void; onClear: () => void }) {
  return (
    <aside className="flex min-h-0 animate-[graphPanelIn_240ms_ease-out] flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-900">节点详情</h2>
          <Badge variant={mode === "subgraph" ? "teal" : "secondary"}>{modeLabel(mode)}</Badge>
        </div>
        <p className="mt-1 text-xs text-slate-500">单击节点查看详情，双击节点展开邻域。</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {selected ? (
          <div key={selected.name} className="animate-[graphPanelIn_220ms_ease-out] space-y-4">
            <div>
              <p className="break-words text-base font-bold text-slate-950">{selected.name}</p>
              <p className="mt-1 text-xs text-slate-500">出现 {selected.count} 次 · {selected.files?.length || 0} 个来源 · {edges.length} 条当前关系</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={() => onCopy(selected.name)} className={graphButton}><Copy size={14} />复制 ID</button>
                <button type="button" onClick={() => onExpand(selected)} className={cn(graphButton, "border-sky-200 text-sky-700")}><GitBranch size={14} />展开邻域</button>
                <button type="button" onClick={onClear} className={iconButton} title="清除选择"><X size={14} /></button>
              </div>
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold text-slate-400">相邻关系</p>
              <div className="space-y-2">
                {edges.length ? edges.slice(0, 30).map((edge, index) => (
                  <div key={`${edge.source}-${edge.target}-${index}`} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-xs text-slate-600 transition-all duration-200 hover:border-sky-100 hover:bg-white hover:shadow-sm">
                    <p className="break-words font-semibold text-slate-800">{edge.source}</p>
                    <p className="my-1 text-[11px] text-sky-700">{edge.relation || "related"} · {edge.count} 次</p>
                    <p className="break-words font-semibold text-slate-800">{edge.target}</p>
                  </div>
                )) : <p className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-xs text-slate-400">当前画布没有相邻关系。</p>}
              </div>
            </div>
            {selected.files?.length ? (
              <div>
                <p className="mb-2 text-xs font-semibold text-slate-400">来源文件</p>
                <div className="flex flex-wrap gap-1.5">
                  {selected.files.slice(0, 20).map((file, index) => <span key={`${file}-${index}`} className="rounded-md bg-slate-50 px-2 py-1 text-[11px] text-slate-500">{file}</span>)}
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center">
            <Network className="mx-auto text-slate-300" size={30} />
            <p className="mt-3 text-sm font-semibold text-slate-800">未选择节点</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">点击画布中的实体节点后，会在这里显示关系、来源和展开操作。</p>
            <button type="button" onClick={onLoadWhole} className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg bg-indigo-600 px-3 text-xs font-semibold text-white transition hover:bg-indigo-700">
              <RotateCcw size={14} />
              返回整图
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}

function isNoiseEntity(name: string) {
  const normalized = name.trim().toLowerCase();
  return noiseTerms.has(normalized) || normalized.startsWith("stroke-") || normalized.startsWith("fill-") || normalized.startsWith("linkstyle") || /^#[0-9a-f]{3,8}$/i.test(normalized);
}

function truncateNodeLabel(value: string) {
  return value.length > 20 ? `${value.slice(0, 18)}...` : value;
}

function modeLabel(mode: ViewMode) {
  if (mode === "whole") return "整图";
  if (mode === "subgraph") return "邻域子图";
  return "未渲染";
}
