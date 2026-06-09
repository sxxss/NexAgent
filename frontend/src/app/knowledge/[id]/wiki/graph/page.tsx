"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, BookOpen, Loader2, RefreshCw } from "lucide-react";
import { fetchKBs, fetchWikiKbGraph, type KBMeta, type WikiGraphPayload } from "@/lib/api";
import { type WikiGraphOptions, WikiGraphPanel } from "@/components/wiki/WikiGraphPanel";
import { Badge } from "@/components/ui/badge";

const headerButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50";
const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50";

export default function WikiGraphPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [kb, setKb] = useState<KBMeta | null>(null);
  const [graph, setGraph] = useState<WikiGraphPayload | null>(null);
  const [graphOptions, setGraphOptions] = useState<WikiGraphOptions>({ q: "", maxEdges: 240, includeWeak: true });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const [kbs, nextGraph] = await Promise.all([fetchKBs(), fetchWikiKbGraph(id, graphParams(graphOptions))]);
      setKb(kbs.find((item) => item.kb_id === id) ?? null);
      setGraph(nextGraph);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 图谱加载失败");
    } finally {
      setLoading(false);
    }
  }, [graphOptions, id]);

  useEffect(() => { void loadData(); }, [loadData]);

  const unsupported = kb && kb.kb_type !== "wiki";

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
              <span className="text-slate-600">Wiki 图谱</span>
            </div>
            <h1 className="flex items-center gap-2 text-xl font-bold text-slate-950"><BookOpen size={20} className="text-amber-700" />Wiki 图谱工作台</h1>
            <p className="mt-1 text-sm text-slate-500">{kb?.description || "页面关系 / 主题结构 / 来源关联，不等同于系统 Neo4j 三元组知识图谱。"}</p>
            <p className="mt-2 text-xs text-slate-400">图谱说明：左侧筛选关系范围，中间拖拽浏览节点，右侧查看节点详情和关系列表。</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="warning">LLM Wiki</Badge>
            <button type="button" onClick={() => router.push(`/knowledge/${id}`)} className={headerButton}><ArrowLeft size={14} />返回详情</button>
            <button type="button" onClick={() => void loadData()} className={iconButton} title="重新加载"><RefreshCw size={14} /></button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto p-6">
        {loading ? (
          <div className="flex min-h-96 items-center justify-center text-sm text-slate-400">
            <Loader2 size={18} className="mr-2 animate-spin text-amber-600" />
            加载 Wiki 图谱...
          </div>
        ) : null}
        {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}
        {!loading && unsupported ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
            <BookOpen className="mx-auto text-slate-300" size={36} />
            <p className="mt-3 text-sm font-semibold text-slate-900">当前知识库不是 Wiki 类型</p>
          </div>
        ) : null}
        {!loading && !unsupported && !error ? (
          <WikiGraphPanel
            graph={graph}
            options={graphOptions}
            fullscreen
            onOptionsChange={setGraphOptions}
            onNodeSelect={(pageId) => router.push(`/knowledge/${id}?wikiPage=${encodeURIComponent(pageId)}`)}
            onReload={loadData}
          />
        ) : null}
      </main>
    </div>
  );
}

function graphParams(options: WikiGraphOptions): Record<string, string> {
  return {
    max_edges: String(Math.max(20, Math.min(300, options.maxEdges || 240))),
    include_weak: String(Boolean(options.includeWeak)),
    ...(options.q.trim() ? { q: options.q.trim() } : {}),
  };
}
