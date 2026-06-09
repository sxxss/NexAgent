"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, FileText, GitBranch, Loader2, RefreshCw, Sparkles } from "lucide-react";
import {
  compileWikiKb,
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
import { type WikiGraphOptions, WikiGraphPanel } from "./WikiGraphPanel";
import { WikiLintPanel } from "./WikiLintPanel";
import { emptyFilters, type WikiPageFilters, WikiPageDirectory, WikiPagePanel } from "./WikiPagePanel";

type WikiTab = "pages" | "graph" | "lint" | "crystallize";

const defaultGraphOptions: WikiGraphOptions = { q: "", maxEdges: 80, includeWeak: false };

export function WikiWorkbench({
  kb,
  files,
  reload,
  sidebar,
  resources,
}: {
  kb: KBMeta;
  files: FileMeta[];
  reload: () => void | Promise<void>;
  sidebar?: React.ReactNode;
  resources?: React.ReactNode;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<WikiTab>("pages");
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selectedPageId, setSelectedPageId] = useState("");
  const selectedPageIdRef = useRef("");
  const [selectedPage, setSelectedPage] = useState<WikiPageDetail | null>(null);
  const [graph, setGraph] = useState<WikiGraphPayload | null>(null);
  const [lint, setLint] = useState<WikiLintPayload | null>(null);
  const [pageFilters, setPageFilters] = useState<WikiPageFilters>(() => emptyFilters());
  const [graphOptions, setGraphOptions] = useState<WikiGraphOptions>(defaultGraphOptions);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    selectedPageIdRef.current = selectedPageId;
  }, [selectedPageId]);

  const loadSelectedPage = useCallback(async (pageId: string) => {
    setSelectedPageId(pageId);
    selectedPageIdRef.current = pageId;
    setSelectedPage(pageId ? await fetchWikiKbPage(kb.kb_id, pageId) : null);
  }, [kb.kb_id]);

  const loadWiki = useCallback(async (preferredPageId?: string) => {
    setError("");
    const [nextPages, nextGraph, nextLint] = await Promise.all([
      fetchWikiKbPages(kb.kb_id, compactParams(pageFilters)),
      fetchWikiKbGraph(kb.kb_id, graphParams(graphOptions)),
      fetchWikiKbLint(kb.kb_id),
    ]);
    setPages(nextPages);
    setGraph(nextGraph);
    setLint(nextLint);

    const urlPageId = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("wikiPage") ?? "" : "";
    const currentId = (preferredPageId ?? selectedPageIdRef.current) || urlPageId;
    const nextPageId = currentId && nextPages.some((page) => page.id === currentId) ? currentId : nextPages[0]?.id ?? "";
    await loadSelectedPage(nextPageId);
  }, [graphOptions, kb.kb_id, loadSelectedPage, pageFilters]);

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

  const selectPage = useCallback(async (pageId: string) => {
    setError("");
    try {
      await loadSelectedPage(pageId);
      setTab("pages");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 页面加载失败");
    }
  }, [loadSelectedPage]);

  const handleGraphNodeSelect = useCallback(async (pageId: string) => {
    await selectPage(pageId);
  }, [selectPage]);

  const handleIssueAction = useCallback(async (issue: WikiLintPayload["issues"][number]) => {
    if (issue.repair_action === "recompile" || issue.action === "recompile") {
      setCompiling(true);
      setError("");
      try {
        await compileWikiKb(kb.kb_id, {
          force: true,
          file_ids: issue.source_file_id ? [issue.source_file_id] : undefined,
        });
        await refresh(issue.page_id?.includes(":") ? issue.page_id : undefined);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Wiki 重新编译失败");
      } finally {
        setCompiling(false);
      }
      return;
    }
    if (issue.page_id?.includes(":")) {
      await selectPage(issue.page_id);
    }
  }, [kb.kb_id, refresh, selectPage]);

  const recompileAll = async () => {
    setCompiling(true);
    setError("");
    try {
      await compileWikiKb(kb.kb_id, { force: true });
      await refresh(selectedPageIdRef.current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 重新编译失败");
    } finally {
      setCompiling(false);
    }
  };

  const tabs = useMemo(() => [
    { id: "pages" as const, label: "Wiki 页面", icon: FileText, value: pages.length },
    { id: "graph" as const, label: "关系图谱", icon: GitBranch, value: graph?.nodes.length ?? 0 },
    { id: "lint" as const, label: "健康检查", icon: AlertCircle, value: lint?.summary?.issue_count ?? lint?.issues.length ?? 0 },
    { id: "crystallize" as const, label: "结晶化", icon: Sparkles, value: files.length },
  ], [files.length, graph?.nodes.length, lint?.issues.length, lint?.summary?.issue_count, pages.length]);

  return (
    <div className="grid h-full min-h-0 gap-3 xl:grid-cols-[minmax(430px,0.92fr)_minmax(560px,1fr)]">
      <aside className="min-h-0 overflow-auto rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="space-y-3">
          {sidebar}
          <WikiResourcePane
            resources={resources}
            pageDirectory={
              <WikiPageDirectory
                pages={pages}
                files={files}
                selectedPageId={selectedPageId}
                filters={pageFilters}
                onFilterChange={setPageFilters}
                onSelect={(pageId) => void selectPage(pageId)}
              />
            }
          />
        </div>
      </aside>

      <section className="min-h-0 min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5">
          <div className="flex min-w-0 items-center gap-7">
            {tabs.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTab(item.id)}
                className={cn(wikiWorkbenchTab, tab === item.id ? "border-sky-500 text-sky-700" : "border-transparent text-slate-700 hover:text-sky-700")}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 py-3">
            <Badge variant="secondary">{pages.length} 页</Badge>
            <button type="button" onClick={() => void recompileAll()} disabled={compiling || loading} className={headerButton}>
              {compiling ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              重新编译
            </button>
            <button type="button" onClick={() => void refresh()} disabled={refreshing || loading} className={iconButton} title="刷新 Wiki">
              {refreshing || loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            </button>
          </div>
        </div>

        {error ? <div className="mx-5 mt-4 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}

        <div className="min-h-0 overflow-auto">
          {loading ? (
            <div className="flex min-h-80 items-center justify-center text-sm text-slate-400">
              <Loader2 size={18} className="mr-2 animate-spin text-sky-600" />
              加载 Wiki...
            </div>
          ) : null}
          {!loading && tab === "pages" ? (
            <WikiPagePanel
              kbId={kb.kb_id}
              pages={pages}
              files={files}
              selectedPage={selectedPage}
              onSelect={(pageId) => void selectPage(pageId)}
              onReload={refresh}
            />
          ) : null}
          {!loading && tab === "graph" ? (
            <div className="p-4">
              <WikiGraphPanel
                graph={graph}
                options={graphOptions}
                onOptionsChange={setGraphOptions}
                onNodeSelect={(pageId) => void handleGraphNodeSelect(pageId)}
                onOpenPage={() => router.push(`/knowledge/${kb.kb_id}/wiki/graph`)}
                onReload={refresh}
              />
            </div>
          ) : null}
          {!loading && tab === "lint" ? (
            <div className="p-4">
              <WikiLintPanel
                kbId={kb.kb_id}
                lint={lint}
                onReload={refresh}
                onIssueAction={(issue) => void handleIssueAction(issue)}
              />
            </div>
          ) : null}
          {!loading && tab === "crystallize" ? (
            <div className="p-4">
              <WikiCrystallizePanel kbId={kb.kb_id} files={files} onCreated={(pageId) => void refresh(pageId)} />
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function WikiResourcePane({ resources, pageDirectory }: { resources?: React.ReactNode; pageDirectory: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <div className="grid gap-0 divide-y divide-slate-100">
        {resources ? <div>{resources}</div> : null}
        <div>{pageDirectory}</div>
      </div>
    </section>
  );
}

function compactParams(filters: WikiPageFilters): Record<string, string> {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value.trim()));
}

function graphParams(options: WikiGraphOptions): Record<string, string> {
  return {
    max_edges: String(Math.max(20, Math.min(300, options.maxEdges || 80))),
    include_weak: String(Boolean(options.includeWeak)),
    ...(options.q.trim() ? { q: options.q.trim() } : {}),
  };
}

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 disabled:opacity-40";
const headerButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-40";
const wikiWorkbenchTab = "inline-flex h-14 items-center border-b-2 px-0 text-base font-semibold transition";
