"use client";

import "reactflow/dist/style.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "reactflow";
import { ExternalLink, GitBranch, LocateFixed, Network, RefreshCw, RotateCcw, Search } from "lucide-react";
import { type WikiGraphPayload } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface WikiGraphOptions {
  q: string;
  maxEdges: number;
  includeWeak: boolean;
  typeFilters?: string[];
  communityFilters?: string[];
}

interface WikiNodeData {
  label: string;
  type: string;
  confidence: string;
  sources: number;
  community: number;
  degree: number;
}

type WikiGraphNode = WikiGraphPayload["nodes"][number];
type WikiGraphEdge = WikiGraphPayload["edges"][number];

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
  onReload: (options?: WikiGraphOptions) => Promise<void>;
}) {
  const effectiveOptions = useMemo(() => normalizeGraphOptions(options), [options]);
  const [draftOptions, setDraftOptions] = useState<WikiGraphOptions>(effectiveOptions);
  const typeFilters = useMemo(() => effectiveOptions.typeFilters ?? [], [effectiveOptions.typeFilters]);
  const communityFilters = useMemo(() => effectiveOptions.communityFilters ?? [], [effectiveOptions.communityFilters]);
  const visibleGraph = useMemo(() => filterGraph(graph, typeFilters, communityFilters), [communityFilters, graph, typeFilters]);
  const { nodes: builtNodes, edges: builtEdges, degrees } = useMemo(() => buildFlowGraph(visibleGraph), [visibleGraph]);
  const [nodes, setNodes, onNodesChange] = useNodesState<WikiNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [focusNodeId, setFocusNodeId] = useState("");
  const stats = graph?.stats ?? {};
  const pageTitle = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node.label])), [graph?.nodes]);
  const selectedNode = useMemo(
    () => (visibleGraph?.nodes ?? []).find((node) => node.id === selectedNodeId) ?? null,
    [selectedNodeId, visibleGraph?.nodes],
  );
  const selectedNodeDegree = selectedNode ? degrees.get(selectedNode.id) ?? 0 : 0;
  const selectedEdges = useMemo(
    () => selectedNode ? (visibleGraph?.edges ?? []).filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id) : [],
    [selectedNode, visibleGraph?.edges],
  );
  const coreNodes = useMemo(
    () =>
      (visibleGraph?.nodes ?? [])
        .map((node) => ({ ...node, degree: degrees.get(node.id) ?? 0 }))
        .filter((node) => node.degree > 0)
        .sort((left, right) => right.degree - left.degree || left.label.localeCompare(right.label))
        .slice(0, fullscreen ? 14 : 10),
    [degrees, fullscreen, visibleGraph?.nodes],
  );
  const typeOptions = useMemo(
    () => uniqueSorted((graph?.nodes ?? []).map((node) => node.type || "unknown")),
    [graph?.nodes],
  );
  const communityOptions = useMemo(
    () => uniqueSorted((graph?.nodes ?? []).map((node) => String(node.community ?? 0)), true),
    [graph?.nodes],
  );
  const displayNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        className: cn(node.className, node.id === selectedNodeId && "wiki-graph-node-selected", node.id === focusNodeId && "wiki-graph-node-focus"),
      })),
    [focusNodeId, nodes, selectedNodeId],
  );

  const updateOption = useCallback((patch: Partial<WikiGraphOptions>) => {
    onOptionsChange?.({ ...effectiveOptions, ...patch });
  }, [effectiveOptions, onOptionsChange]);

  const updateDraftOption = useCallback((patch: Partial<WikiGraphOptions>) => {
    setDraftOptions((current) => ({ ...current, ...patch }));
  }, []);

  const applyGraphOptions = useCallback(async () => {
    const nextOptions = {
      ...effectiveOptions,
      q: draftOptions.q,
      maxEdges: draftOptions.maxEdges,
      includeWeak: draftOptions.includeWeak,
    };
    onOptionsChange?.(nextOptions);
    await onReload(nextOptions);
  }, [draftOptions.includeWeak, draftOptions.maxEdges, draftOptions.q, effectiveOptions, onOptionsChange, onReload]);

  const toggleArrayOption = useCallback((key: "typeFilters" | "communityFilters", value: string) => {
    const current = key === "typeFilters" ? typeFilters : communityFilters;
    const next = current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
    updateOption({ [key]: next } as Partial<WikiGraphOptions>);
  }, [communityFilters, typeFilters, updateOption]);

  const onFitView = useCallback(() => {
    flow?.fitView({ padding: 0.22, duration: 450 });
  }, [flow]);

  const resetView = useCallback(() => {
    setFocusNodeId("");
    setSelectedNodeId("");
    flow?.fitView({ padding: 0.22, duration: 450 });
  }, [flow]);

  const focusNode = useCallback((nodeId: string) => {
    const target = nodes.find((node) => node.id === nodeId);
    setSelectedNodeId(nodeId);
    setFocusNodeId(nodeId);
    if (target) {
      flow?.setCenter(target.position.x + 80, target.position.y + 60, { zoom: 1.25, duration: 450 });
    }
  }, [flow, nodes]);

  const handleNodeClick = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    setFocusNodeId(nodeId);
    if (!fullscreen) onNodeSelect?.(nodeId);
  }, [fullscreen, onNodeSelect]);

  useEffect(() => {
    setNodes(builtNodes);
  }, [builtNodes, setNodes]);

  useEffect(() => {
    setEdges(builtEdges);
  }, [builtEdges, setEdges]);

  return (
    <div className={cn("space-y-4", fullscreen && "flex min-h-0 flex-1 flex-col")}>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700"><GitBranch size={16} /></span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Wiki 关系图</h3>
            <p className="text-xs text-slate-500">{nodes.length} nodes · {edges.length} edges</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <GraphStat label="页面" value={Number(stats.total_nodes ?? stats.pages ?? graph?.nodes?.length ?? nodes.length)} />
          <GraphStat label="展示关系" value={edges.length} />
          <GraphStat label="原始关系" value={Number(stats.raw_edge_count ?? stats.edges ?? graph?.edges?.length ?? edges.length)} />
          <GraphStat label="社区" value={Number(stats.communities ?? communityOptions.length)} />
          {onOpenPage ? <button type="button" onClick={onOpenPage} className={iconButton} title="打开图谱详细页"><ExternalLink size={14} /></button> : null}
          <button type="button" onClick={() => void applyGraphOptions()} className={iconButton} title="刷新图谱"><RefreshCw size={14} /></button>
        </div>
      </div>

      {fullscreen ? (
        <WikiGraphExplorerShell
          graph={visibleGraph}
          displayNodes={displayNodes}
          edges={edges}
          effectiveOptions={effectiveOptions}
          draftOptions={draftOptions}
          typeFilters={typeFilters}
          communityFilters={communityFilters}
          typeOptions={typeOptions}
          communityOptions={communityOptions}
          selectedNode={selectedNode}
          selectedNodeDegree={selectedNodeDegree}
          selectedEdges={selectedEdges}
          coreNodes={coreNodes}
          pageTitle={pageTitle}
          onDraftOptionsChange={updateDraftOption}
          onToggleOption={toggleArrayOption}
          onApplyOptions={applyGraphOptions}
          onFitView={onFitView}
          onResetView={resetView}
          onFocusNode={focusNode}
          onOpenNode={onNodeSelect}
          setFlow={setFlow}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={handleNodeClick}
        />
      ) : (
        <>
          <CompactGraphControls draftOptions={draftOptions} onDraftOptionsChange={updateDraftOption} onApplyOptions={applyGraphOptions} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
            <GraphCanvas
              nodes={displayNodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              setFlow={setFlow}
              heightClass="h-[620px]"
            />
            <CompactGraphAside coreNodes={coreNodes} onFocusNode={(nodeId) => onNodeSelect?.(nodeId)} />
          </div>
          <RelationshipList edges={visibleGraph?.edges ?? []} pageTitle={pageTitle} onFocusNode={(nodeId) => onNodeSelect?.(nodeId)} compact />
        </>
      )}
    </div>
  );
}

function WikiGraphExplorerShell({
  graph,
  displayNodes,
  edges,
  effectiveOptions,
  draftOptions,
  typeFilters,
  communityFilters,
  typeOptions,
  communityOptions,
  selectedNode,
  selectedNodeDegree,
  selectedEdges,
  coreNodes,
  pageTitle,
  onDraftOptionsChange,
  onToggleOption,
  onApplyOptions,
  onFitView,
  onResetView,
  onFocusNode,
  onOpenNode,
  setFlow,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
}: {
  graph: WikiGraphPayload | null;
  displayNodes: Node<WikiNodeData>[];
  edges: Edge[];
  effectiveOptions: WikiGraphOptions;
  draftOptions: WikiGraphOptions;
  typeFilters: string[];
  communityFilters: string[];
  typeOptions: string[];
  communityOptions: string[];
  selectedNode: WikiGraphNode | null;
  selectedNodeDegree: number;
  selectedEdges: WikiGraphEdge[];
  coreNodes: Array<WikiGraphNode & { degree: number }>;
  pageTitle: Map<string, string>;
  onDraftOptionsChange: (patch: Partial<WikiGraphOptions>) => void;
  onToggleOption: (key: "typeFilters" | "communityFilters", value: string) => void;
  onApplyOptions: () => Promise<void>;
  onFitView: () => void;
  onResetView: () => void;
  onFocusNode: (nodeId: string) => void;
  onOpenNode?: (nodeId: string) => void;
  setFlow: (flow: ReactFlowInstance) => void;
  onNodesChange: ReturnType<typeof useNodesState<WikiNodeData>>[2];
  onEdgesChange: ReturnType<typeof useEdgesState>[2];
  onNodeClick: (nodeId: string) => void;
}) {
  return (
    <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[260px_minmax(0,1fr)_320px]">
      <aside className="min-h-0 overflow-auto rounded-xl border border-slate-200 bg-white p-3">
        <section className="space-y-3 border-b border-slate-100 pb-4">
          <div>
            <h4 className="text-sm font-semibold text-slate-900">关系范围</h4>
            <p className="mt-1 text-xs leading-5 text-slate-500">核心关系优先显示显式双链；弱关系会加入来源重叠、共同邻居等推断关系。</p>
          </div>
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={draftOptions.q}
              onChange={(event) => onDraftOptionsChange({ q: event.target.value })}
              onKeyDown={(event) => { if (event.key === "Enter") void onApplyOptions(); }}
              placeholder="搜索页面或主题"
              className={filterInput}
            />
          </div>
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            关系数
            <input
              type="number"
              min={20}
              max={300}
              value={draftOptions.maxEdges}
              onChange={(event) => onDraftOptionsChange({ maxEdges: Number(event.target.value) || 80 })}
              className={numberInput}
            />
          </label>
          <label className="flex h-9 items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600">
            {draftOptions.includeWeak ? "包含弱关系" : "核心关系"}
            <input type="checkbox" checked={draftOptions.includeWeak} onChange={(event) => onDraftOptionsChange({ includeWeak: event.target.checked })} className="h-4 w-4 accent-indigo-600" />
          </label>
          <button type="button" onClick={() => void onApplyOptions()} className={primaryButton}><RefreshCw size={14} />刷新图谱</button>
        </section>

        <FilterGroup title="页面类型" values={typeOptions} selected={typeFilters} labelFor={pageTypeLabel} onToggle={(value) => onToggleOption("typeFilters", value)} />
        <FilterGroup title="社区" values={communityOptions} selected={communityFilters} labelFor={(value) => `社区 ${value}`} onToggle={(value) => onToggleOption("communityFilters", value)} />

        <section className="space-y-2 border-t border-slate-100 pt-4">
          <h4 className="text-sm font-semibold text-slate-900">视图</h4>
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={onFitView} className={secondaryButton}><LocateFixed size={14} />适应</button>
            <button type="button" onClick={onResetView} className={secondaryButton}><RotateCcw size={14} />重置</button>
          </div>
        </section>
      </aside>

      <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Network size={16} className="text-indigo-600" />
            {effectiveOptions.includeWeak ? "包含弱关系" : "核心关系"}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3 text-xs text-slate-500">
            {typeLegend.map((type) => (
              <span key={type.type} className="inline-flex items-center gap-1.5">
                <i className="h-2.5 w-2.5 rounded-full" style={{ background: type.color }} />
                {type.label}
              </span>
            ))}
          </div>
        </div>
        <GraphCanvas
          nodes={displayNodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          setFlow={setFlow}
          heightClass="h-full min-h-[640px]"
        />
      </section>

      <aside className="min-h-0 overflow-auto rounded-xl border border-slate-200 bg-white p-3">
        <section className="space-y-3 border-b border-slate-100 pb-4">
          <h4 className="text-sm font-semibold text-slate-900">当前节点</h4>
          {selectedNode ? (
            <div className="space-y-3">
              <div>
                <h3 className="break-words text-base font-bold text-slate-950">{selectedNode.label}</h3>
                <p className="mt-1 break-all font-mono text-[11px] text-slate-400">{selectedNode.id}</p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="secondary">{pageTypeLabel(selectedNode.type)}</Badge>
                <Badge variant={confidenceVariant(selectedNode.confidence)}>{selectedNode.confidence || "UNVERIFIED"}</Badge>
                <Badge variant="info">社区 {selectedNode.community ?? 0}</Badge>
                <Badge variant="warning">{selectedNodeDegree} links</Badge>
              </div>
              <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
                <p>来源数量：{selectedNode.sources?.length ?? 0}</p>
                <p>相关关系：{selectedEdges.length}</p>
              </div>
              {onOpenNode ? <button type="button" onClick={() => onOpenNode(selectedNode.id)} className={primaryButton}><ExternalLink size={14} />在 Wiki 页面中查看</button> : null}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-xs text-slate-400">点击图中节点查看详情</div>
          )}
        </section>

        <section className="space-y-2 border-b border-slate-100 py-4">
          <h4 className="text-sm font-semibold text-slate-900">核心节点</h4>
          <div className="grid gap-1.5">
            {coreNodes.length ? coreNodes.map((node) => (
              <button key={node.id} type="button" onClick={() => onFocusNode(node.id)} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-600 hover:bg-indigo-50 hover:text-indigo-700">
                <span className="min-w-0 truncate">{node.label}</span>
                <Badge variant="secondary">{node.degree}</Badge>
              </button>
            )) : <span className="text-xs text-slate-400">暂无核心节点</span>}
          </div>
        </section>

        <RelationshipList edges={graph?.edges ?? []} pageTitle={pageTitle} onFocusNode={onFocusNode} title="关系列表" />
      </aside>
    </div>
  );
}

function CompactGraphControls({
  draftOptions,
  onDraftOptionsChange,
  onApplyOptions,
}: {
  draftOptions: WikiGraphOptions;
  onDraftOptionsChange: (patch: Partial<WikiGraphOptions>) => void;
  onApplyOptions: () => Promise<void>;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-3">
      <div className="relative min-w-56 flex-1">
        <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={draftOptions.q}
          onChange={(event) => onDraftOptionsChange({ q: event.target.value })}
          onKeyDown={(event) => { if (event.key === "Enter") void onApplyOptions(); }}
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
          value={draftOptions.maxEdges}
          onChange={(event) => onDraftOptionsChange({ maxEdges: Number(event.target.value) || 80 })}
          className="h-6 w-16 rounded border border-slate-200 px-1.5 text-xs outline-none"
        />
      </label>
      <label className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600">
        <input type="checkbox" checked={draftOptions.includeWeak} onChange={(event) => onDraftOptionsChange({ includeWeak: event.target.checked })} className="h-4 w-4 accent-indigo-600" />
        {draftOptions.includeWeak ? "包含弱关系" : "核心关系"}
      </label>
      <button type="button" onClick={() => void onApplyOptions()} className={secondaryButton}><RefreshCw size={14} />刷新图谱</button>
    </div>
  );
}

function GraphCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onNodeClick,
  setFlow,
  heightClass,
}: {
  nodes: Node<WikiNodeData>[];
  edges: Edge[];
  onNodesChange: ReturnType<typeof useNodesState<WikiNodeData>>[2];
  onEdgesChange: ReturnType<typeof useEdgesState>[2];
  onNodeClick: (nodeId: string) => void;
  setFlow: (flow: ReactFlowInstance) => void;
  heightClass: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-xl border border-slate-200 bg-white", heightClass)}>
      {nodes.length ? (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable
          nodesConnectable={false}
          nodesFocusable
          edgesFocusable
          panOnDrag
          zoomOnScroll
          zoomOnPinch
          zoomOnDoubleClick
          onInit={setFlow}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={(_event, node) => onNodeClick(node.id)}
        >
          <Background gap={18} size={1} color="#e2e8f0" />
          <MiniMap pannable zoomable nodeColor={(node) => nodeColor((node.data as WikiNodeData).type)} />
          <Controls showInteractive />
        </ReactFlow>
      ) : (
        <div className="flex h-full flex-col items-center justify-center text-sm text-slate-400">
          <GitBranch size={32} className="mb-3 text-slate-300" />
          暂无 Wiki 图谱
        </div>
      )}
    </div>
  );
}

function FilterGroup({ title, values, selected, labelFor, onToggle }: { title: string; values: string[]; selected: string[]; labelFor: (value: string) => string; onToggle: (value: string) => void }) {
  return (
    <section className="space-y-2 border-t border-slate-100 py-4">
      <h4 className="text-sm font-semibold text-slate-900">{title}</h4>
      <div className="grid gap-1.5">
        {values.length ? values.map((value) => (
          <label key={value} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">
            <span className="min-w-0 truncate">{labelFor(value)}</span>
            <input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(value)} className="h-4 w-4 accent-indigo-600" />
          </label>
        )) : <span className="text-xs text-slate-400">暂无可筛选项</span>}
      </div>
    </section>
  );
}

function CompactGraphAside({ coreNodes, onFocusNode }: { coreNodes: Array<WikiGraphNode & { degree: number }>; onFocusNode: (nodeId: string) => void }) {
  return (
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
            <button key={node.id} type="button" onClick={() => onFocusNode(node.id)} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-slate-600 hover:bg-indigo-50 hover:text-indigo-700">
              <span className="min-w-0 truncate">{node.label}</span>
              <Badge variant="secondary">{node.degree}</Badge>
            </button>
          )) : <span className="text-xs text-slate-400">暂无核心节点</span>}
        </div>
      </section>
    </aside>
  );
}

function RelationshipList({ edges, pageTitle, onFocusNode, title = "关系详情", compact = false }: { edges: WikiGraphEdge[]; pageTitle: Map<string, string>; onFocusNode: (nodeId: string) => void; title?: string; compact?: boolean }) {
  return (
    <section className={cn(!compact && "space-y-2 pt-4", compact && "rounded-xl border border-slate-200 bg-white")}>
      <div className={cn("flex items-center justify-between", compact ? "border-b border-slate-100 px-4 py-3" : "pb-1")}>
        <h4 className="text-xs font-semibold text-slate-700">{title}</h4>
        <span className="text-[11px] text-slate-400">{edges.length}</span>
      </div>
      <div className={cn("overflow-auto", compact ? "max-h-72" : "max-h-96")}>
        {edges.length ? edges.map((edge, index) => (
          <div key={`${edge.source}-${edge.target}-${index}`} className={cn("flex flex-wrap items-center gap-2 border-b border-slate-100 text-xs text-slate-600 last:border-0", compact ? "px-4 py-2" : "py-2")}>
            <button type="button" onClick={() => onFocusNode(edge.source)} className="min-w-0 max-w-full truncate font-semibold text-slate-800 hover:text-indigo-700">{pageTitle.get(edge.source) ?? edge.source}</button>
            <span className="text-slate-300">{"->"}</span>
            <button type="button" onClick={() => onFocusNode(edge.target)} className="min-w-0 max-w-full truncate font-semibold text-slate-800 hover:text-indigo-700">{pageTitle.get(edge.target) ?? edge.target}</button>
            <Badge variant="secondary">权重 {edge.weight}</Badge>
            {edge.signals?.wikilink ? <Badge variant="info">双链</Badge> : <Badge variant="secondary">推断</Badge>}
            {Array.isArray(edge.signals?.source_overlap) && edge.signals.source_overlap.length ? <Badge variant="success">同源</Badge> : null}
            {Array.isArray(edge.signals?.common_neighbors) && edge.signals.common_neighbors.length ? <Badge variant="warning">共邻</Badge> : null}
          </div>
        )) : <div className={cn("text-center text-xs text-slate-400", compact ? "px-4 py-8" : "py-6")}>暂无关系</div>}
      </div>
    </section>
  );
}

function WikiNode({ data }: NodeProps<WikiNodeData>) {
  return (
    <div className={cn("min-w-40 max-w-56 rounded-xl border bg-white px-3 py-2 shadow-sm", nodeBorder(data.type))}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !bg-slate-300" />
      <p className="line-clamp-2 text-sm font-semibold leading-5 text-slate-900">{data.label}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <Badge variant="secondary">{pageTypeLabel(data.type)}</Badge>
        <Badge variant={confidenceVariant(data.confidence)}>{data.confidence}</Badge>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">{data.sources} sources · {data.degree} links · C{data.community}</p>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !bg-slate-300" />
    </div>
  );
}

function normalizeGraphOptions(options?: WikiGraphOptions): WikiGraphOptions {
  return {
    q: options?.q ?? "",
    maxEdges: options?.maxEdges ?? 80,
    includeWeak: options?.includeWeak ?? false,
    typeFilters: options?.typeFilters ?? [],
    communityFilters: options?.communityFilters ?? [],
  };
}

function filterGraph(graph: WikiGraphPayload | null, typeFilters: string[], communityFilters: string[]): WikiGraphPayload | null {
  if (!graph) return null;
  const nodes = graph.nodes.filter((node) => {
    const typeOk = !typeFilters.length || typeFilters.includes(node.type || "unknown");
    const communityOk = !communityFilters.length || communityFilters.includes(String(node.community ?? 0));
    return typeOk && communityOk;
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  return {
    ...graph,
    nodes,
    edges: graph.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)),
  };
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

function uniqueSorted(values: string[], numeric = false) {
  return [...new Set(values.filter(Boolean))].sort((left, right) => numeric ? Number(left) - Number(right) : left.localeCompare(right));
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
    unknown: "未知",
  }[type] ?? type;
}

function confidenceVariant(confidence: string): "secondary" | "info" | "success" | "warning" | "error" {
  if (confidence === "EXTRACTED") return "success";
  if (confidence === "INFERRED") return "info";
  if (confidence === "AMBIGUOUS") return "warning";
  return "secondary";
}

const typeLegend = [
  { type: "source", label: "来源页", color: "#0ea5e9" },
  { type: "topic", label: "主题页", color: "#f59e0b" },
  { type: "entity", label: "实体页", color: "#10b981" },
  { type: "synthesis", label: "综合页", color: "#8b5cf6" },
  { type: "note", label: "笔记页", color: "#64748b" },
];

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";
const primaryButton = "inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-40";
const secondaryButton = "inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50";
const filterInput = "h-9 w-full rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-xs text-slate-700 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100";
const numberInput = "h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100";
