"use client";

import "reactflow/dist/style.css";

import { useMemo } from "react";
import ReactFlow, { Background, Controls, MiniMap, Handle, Position, type Edge, type Node, type NodeProps } from "reactflow";
import { GitBranch, RefreshCw } from "lucide-react";
import { type WikiGraphPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface WikiNodeData {
  label: string;
  type: string;
  confidence: string;
  sources: number;
  community: number;
}

const nodeTypes = { wikiNode: WikiNode };

export function WikiGraphPanel({ graph, onReload }: { graph: WikiGraphPayload | null; onReload: () => Promise<void> }) {
  const { nodes, edges } = useMemo(() => buildFlowGraph(graph), [graph]);
  const stats = graph?.stats ?? {};

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
          <GraphStat label="页面" value={Number(stats.pages ?? nodes.length)} />
          <GraphStat label="关系" value={Number(stats.edges ?? edges.length)} />
          <button type="button" onClick={() => void onReload()} className={iconButton} title="刷新图谱"><RefreshCw size={14} /></button>
        </div>
      </div>

      <div className="h-[620px] overflow-hidden rounded-xl border border-slate-200 bg-white">
        {nodes.length ? (
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.18 }}>
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
    </div>
  );
}

function WikiNode({ data }: NodeProps<WikiNodeData>) {
  return (
    <div className={cn("min-w-40 max-w-56 rounded-xl border bg-white px-3 py-2 shadow-sm", nodeBorder(data.type))}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !bg-slate-300" />
      <p className="line-clamp-2 text-sm font-semibold leading-5 text-slate-900">{data.label}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant="secondary">{data.type}</Badge>
        <Badge variant={data.confidence === "EXTRACTED" ? "success" : data.confidence === "INFERRED" ? "info" : "warning"}>{data.confidence}</Badge>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">{data.sources} sources · C{data.community}</p>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !bg-slate-300" />
    </div>
  );
}

function buildFlowGraph(graph: WikiGraphPayload | null): { nodes: Node<WikiNodeData>[]; edges: Edge[] } {
  if (!graph?.nodes?.length) return { nodes: [], edges: [] };
  const total = graph.nodes.length;
  const radius = Math.max(220, Math.min(560, total * 18));
  const nodes: Node<WikiNodeData>[] = graph.nodes.map((node, index) => {
    const angle = (index / total) * Math.PI * 2;
    const lane = 1 + (node.community % 3) * 0.18;
    return {
      id: node.id,
      type: "wikiNode",
      position: { x: Math.cos(angle) * radius * lane + radius + 80, y: Math.sin(angle) * radius * lane + radius + 60 },
      data: {
        label: node.label,
        type: node.type,
        confidence: node.confidence,
        sources: node.sources.length,
        community: node.community,
      },
    };
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: Edge[] = graph.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.signals?.wikilink ? "wikilink" : "",
      animated: Boolean(edge.signals?.source_overlap),
      style: { stroke: "#94a3b8", strokeWidth: Math.max(1, Math.min(4, edge.weight)) },
      labelStyle: { fill: "#64748b", fontSize: 10, fontWeight: 600 },
    }));
  return { nodes, edges };
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

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";
