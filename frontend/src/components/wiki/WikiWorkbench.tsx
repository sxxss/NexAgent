"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, BookOpen, FileText, GitBranch, Loader2, RefreshCw, Sparkles } from "lucide-react";
import {
  fetchWikiKbGraph,
  fetchWikiKbLint,
  fetchWikiKbPage,
  fetchWikiKbPages,
  type FileMeta,
  type KBMeta,
  type WikiGraphPayload,
  type WikiLintPayload,
  type WikiPageDetail,
  type WikiPageSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { WikiCrystallizePanel } from "./WikiCrystallizePanel";
import { WikiGraphPanel } from "./WikiGraphPanel";
import { WikiLintPanel } from "./WikiLintPanel";
import { WikiPagePanel } from "./WikiPagePanel";

type WikiTab = "pages" | "graph" | "lint" | "crystallize";

export function WikiWorkbench({ kb, files, reload }: { kb: KBMeta; files: FileMeta[]; reload: () => void | Promise<void> }) {
  const [tab, setTab] = useState<WikiTab>("pages");
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selectedPageId, setSelectedPageId] = useState("");
  const selectedPageIdRef = useRef("");
  const [selectedPage, setSelectedPage] = useState<WikiPageDetail | null>(null);
  const [graph, setGraph] = useState<WikiGraphPayload | null>(null);
  const [lint, setLint] = useState<WikiLintPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    selectedPageIdRef.current = selectedPageId;
  }, [selectedPageId]);

  const loadWiki = useCallback(async (preferredPageId?: string) => {
    setError("");
    const [nextPages, nextGraph, nextLint] = await Promise.all([
      fetchWikiKbPages(kb.kb_id),
      fetchWikiKbGraph(kb.kb_id),
      fetchWikiKbLint(kb.kb_id),
    ]);
    setPages(nextPages);
    setGraph(nextGraph);
    setLint(nextLint);

    const currentId = preferredPageId ?? selectedPageIdRef.current;
    const nextPageId = currentId && nextPages.some((page) => page.id === currentId) ? currentId : nextPages[0]?.id ?? "";
    setSelectedPageId(nextPageId);
    selectedPageIdRef.current = nextPageId;
    setSelectedPage(nextPageId ? await fetchWikiKbPage(kb.kb_id, nextPageId) : null);
  }, [kb.kb_id]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    loadWiki()
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : "Wiki 加载失败");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, [loadWiki]);

  const refresh = useCallback(async (pageId?: string) => {
    setRefreshing(true);
    try {
      await loadWiki(pageId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 刷新失败");
    } finally {
      setRefreshing(false);
    }
  }, [loadWiki, reload]);

  const tabs = useMemo(() => [
    { id: "pages" as const, label: "页面", icon: FileText, value: pages.length },
    { id: "graph" as const, label: "图谱", icon: GitBranch, value: graph?.nodes.length ?? 0 },
    { id: "lint" as const, label: "健康", icon: AlertCircle, value: lint?.summary?.issue_count ?? lint?.issues.length ?? 0 },
    { id: "crystallize" as const, label: "沉淀", icon: Sparkles, value: files.length },
  ], [files.length, graph?.nodes.length, lint?.issues.length, lint?.summary?.issue_count, pages.length]);

  return (
    <div className="min-w-0 rounded-2xl border border-amber-100 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700">
            <BookOpen size={16} />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-slate-900">Wiki 工作台</h2>
            <p className="truncate text-xs text-slate-500">{kb.name}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="warning">{pages.length} pages</Badge>
          <button type="button" onClick={() => void refresh()} disabled={refreshing || loading} className={iconButton} title="刷新 Wiki">
            {refreshing || loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-slate-100 px-4 py-3">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={cn(
                "inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-xs font-semibold transition",
                tab === item.id ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
              )}
            >
              <Icon size={14} />
              {item.label}
              <span className="rounded-full bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-500">{item.value}</span>
            </button>
          );
        })}
      </div>

      {error ? <div className="mx-4 mt-4 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}

      <div className="p-4">
        {loading ? (
          <div className="flex min-h-80 items-center justify-center text-sm text-slate-400">
            <Loader2 size={18} className="mr-2 animate-spin text-amber-600" />
            加载 Wiki...
          </div>
        ) : null}
        {!loading && tab === "pages" ? (
          <WikiPagePanel
            kbId={kb.kb_id}
            pages={pages}
            selectedPageId={selectedPageId}
            selectedPage={selectedPage}
            onSelect={(pageId) => void refresh(pageId)}
            onReload={refresh}
          />
        ) : null}
        {!loading && tab === "graph" ? <WikiGraphPanel graph={graph} onReload={refresh} /> : null}
        {!loading && tab === "lint" ? <WikiLintPanel lint={lint} onReload={refresh} /> : null}
        {!loading && tab === "crystallize" ? <WikiCrystallizePanel kbId={kb.kb_id} files={files} onCreated={(pageId) => void refresh(pageId)} /> : null}
      </div>
    </div>
  );
}

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 disabled:opacity-40";
