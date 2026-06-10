"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, FileText, GitBranch, Loader2, RefreshCw, Sparkles } from "lucide-react";
import {
  compileWikiKb,
  createWikiKbPage,
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

const defaultGraphOptions: WikiGraphOptions = { q: "", maxEdges: 40, includeWeak: false };

export interface WikiResourceContext {
  filters: WikiPageFilters;
  setFilters: (filters: WikiPageFilters) => void;
  candidateCount: number;
  needsReviewCount: number;
}

type WikiResources = React.ReactNode | ((context: WikiResourceContext) => React.ReactNode);

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
  resources?: WikiResources;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<WikiTab>("pages");
  const [pages, setPages] = useState<WikiPageSummary[]>([]);
  const [selectedPageId, setSelectedPageId] = useState("");
  const selectedPageIdRef = useRef("");
  const [selectedPage, setSelectedPage] = useState<WikiPageDetail | null>(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [graph, setGraph] = useState<WikiGraphPayload | null>(null);
  const graphRef = useRef<WikiGraphPayload | null>(null);
  const graphLoadedKeyRef = useRef("");
  const [lint, setLint] = useState<WikiLintPayload | null>(null);
  const lintRef = useRef<WikiLintPayload | null>(null);
  const [pageFilters, setPageFilters] = useState<WikiPageFilters>(() => emptyFilters());
  const visiblePages = useMemo(() => filterWikiPages(pages, pageFilters), [pageFilters, pages]);
  const candidateCount = useMemo(() => pages.filter((page) => page.has_candidate).length, [pages]);
  const needsReviewCount = useMemo(
    () => pages.filter((page) => page.status === "needs_review" || page.confidence === "AMBIGUOUS" || page.confidence === "UNVERIFIED").length,
    [pages],
  );
  const [graphOptions, setGraphOptions] = useState<WikiGraphOptions>(defaultGraphOptions);
  const graphQueryKey = useMemo(() => JSON.stringify(graphParams(graphOptions)), [graphOptions]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    selectedPageIdRef.current = selectedPageId;
  }, [selectedPageId]);
  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);
  useEffect(() => {
    lintRef.current = lint;
  }, [lint]);

  const loadSelectedPageDetail = useCallback(async (pageId: string) => {
    if (!pageId) {
      setSelectedPage(null);
      setPageLoading(false);
      return null;
    }
    setPageLoading(true);
    try {
      const nextPage = await fetchWikiKbPage(kb.kb_id, pageId);
      if (selectedPageIdRef.current === pageId) {
        setSelectedPage(nextPage);
      }
      return nextPage;
    } finally {
      if (selectedPageIdRef.current === pageId) {
        setPageLoading(false);
      }
    }
  }, [kb.kb_id]);

  const loadSelectedPage = useCallback((pageId: string) => {
    setSelectedPageId(pageId);
    selectedPageIdRef.current = pageId;
    replaceWikiPageUrl(pageId);
    setSelectedPage(null);
    void loadSelectedPageDetail(pageId).catch((err) => {
      setError(err instanceof Error ? err.message : "Wiki 页面加载失败");
    });
  }, [loadSelectedPageDetail]);

  const loadWikiPages = useCallback(async (preferredPageId?: string) => {
    setError("");
    const nextPages = await fetchWikiKbPages(kb.kb_id);
    setPages(nextPages);
    const urlPageId = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("wikiPage") ?? "" : "";
    const currentId = (preferredPageId ?? selectedPageIdRef.current) || urlPageId;
    const nextPageId = currentId && nextPages.some((page) => page.id === currentId) ? currentId : nextPages[0]?.id ?? "";
    loadSelectedPage(nextPageId);
  }, [kb.kb_id, loadSelectedPage]);

  const loadWikiGraph = useCallback(async (nextOptions?: WikiGraphOptions) => {
    const requestOptions = nextOptions ?? graphOptions;
    const requestKey = JSON.stringify(graphParams(requestOptions));
    const nextGraph = await fetchWikiKbGraph(kb.kb_id, graphParams(requestOptions));
    setGraph(nextGraph);
    graphRef.current = nextGraph;
    graphLoadedKeyRef.current = requestKey;
    return nextGraph;
  }, [graphOptions, kb.kb_id]);

  const loadWikiLint = useCallback(async () => {
    const nextLint = await fetchWikiKbLint(kb.kb_id);
    setLint(nextLint);
    lintRef.current = nextLint;
    return nextLint;
  }, [kb.kb_id]);

  const invalidateDerivedWikiData = useCallback(() => {
    setGraph(null);
    graphRef.current = null;
    graphLoadedKeyRef.current = "";
    setLint(null);
    lintRef.current = null;
  }, []);

  const ensureTabData = useCallback(async (targetTab: WikiTab, force = false) => {
    if (targetTab === "graph" && (force || !graphRef.current || graphLoadedKeyRef.current !== graphQueryKey)) {
      await loadWikiGraph();
    }
    if (targetTab === "lint" && (force || !lintRef.current)) {
      await loadWikiLint();
    }
  }, [graphQueryKey, loadWikiGraph, loadWikiLint]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    loadWikiPages()
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : "Wiki 加载失败");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, [loadWikiPages]);

  useEffect(() => {
    if (tab !== "graph" && tab !== "lint") return;
    let mounted = true;
    setRefreshing(true);
    ensureTabData(tab)
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : "Wiki 标签数据加载失败");
      })
      .finally(() => {
        if (mounted) setRefreshing(false);
      });
    return () => { mounted = false; };
  }, [ensureTabData, tab]);

  const refresh = useCallback(async (pageId?: string) => {
    setRefreshing(true);
    try {
      await loadWikiPages(pageId);
      invalidateDerivedWikiData();
      await ensureTabData(tab, true);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 刷新失败");
    } finally {
      setRefreshing(false);
    }
  }, [ensureTabData, invalidateDerivedWikiData, loadWikiPages, reload, tab]);

  const refreshGraph = useCallback(async (nextOptions?: WikiGraphOptions) => {
    setRefreshing(true);
    setError("");
    try {
      await loadWikiGraph(nextOptions);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Wiki 图谱刷新失败");
    } finally {
      setRefreshing(false);
    }
  }, [loadWikiGraph]);

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

  const createLinkedPage = useCallback(async (title: string) => {
    setError("");
    const page = await createWikiKbPage(kb.kb_id, { title, page_type: "note" });
    invalidateDerivedWikiData();
    setTab("pages");
    await refresh(page.id);
  }, [invalidateDerivedWikiData, kb.kb_id, refresh]);

  const handleIssueAction = useCallback(async (issue: WikiLintPayload["issues"][number]) => {
    if (issue.repair_action === "recompile" || issue.action === "recompile") {
      setCompiling(true);
      setError("");
      try {
        await compileWikiKb(kb.kb_id, {
          force: true,
          file_ids: issue.source_file_id ? [issue.source_file_id] : undefined,
        });
        invalidateDerivedWikiData();
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
  }, [invalidateDerivedWikiData, kb.kb_id, refresh, selectPage]);

  const recompileAll = async () => {
    setCompiling(true);
    setError("");
    try {
      await compileWikiKb(kb.kb_id, { force: true });
      invalidateDerivedWikiData();
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

  const renderResources = useCallback(() => {
    if (typeof resources === "function") {
      return resources({ filters: pageFilters, setFilters: setPageFilters, candidateCount, needsReviewCount });
    }
    return resources;
  }, [candidateCount, needsReviewCount, pageFilters, resources]);

  return (
    <div className="grid h-full min-h-0 gap-3 xl:grid-cols-[minmax(320px,0.72fr)_minmax(680px,1.28fr)]">
      <aside className="min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
        <div className="flex h-full min-h-0 flex-col gap-3">
          {sidebar}
          <WikiResourcePane
            resources={renderResources()}
            pageDirectory={
              <WikiPageDirectory
                pages={visiblePages}
                totalCount={pages.length}
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
              loading={pageLoading}
              onSelect={(pageId) => void selectPage(pageId)}
              onCreatePage={createLinkedPage}
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
                onReload={refreshGraph}
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
    <section className={wikiResourcePaneCompact}>
      <div className="flex min-h-0 flex-1 flex-col divide-y divide-slate-100">
        {resources ? <div className="shrink-0">{resources}</div> : null}
        <div className="min-h-0 flex-1">{pageDirectory}</div>
      </div>
    </section>
  );
}

function graphParams(options: WikiGraphOptions): Record<string, string> {
  return {
    max_edges: String(Math.max(20, Math.min(300, options.maxEdges || 40))),
    include_weak: String(Boolean(options.includeWeak)),
    ...(options.q.trim() ? { q: options.q.trim() } : {}),
  };
}

function replaceWikiPageUrl(pageId: string) {
  if (typeof window === "undefined") return;
  const nextUrl = new URL(window.location.href);
  if (pageId) {
    nextUrl.searchParams.set("wikiPage", pageId);
  } else {
    nextUrl.searchParams.delete("wikiPage");
  }
  const nextPath = `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`;
  window.history.replaceState(window.history.state, "", nextPath);
}

function filterWikiPages(pages: WikiPageSummary[], filters: WikiPageFilters): WikiPageSummary[] {
  const q = filters.q.trim().toLowerCase();
  return pages.filter((page) => {
    if (q) {
      const haystack = [page.title, page.path, page.excerpt].filter(Boolean).join(" ").toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    if (filters.type && page.type !== filters.type) return false;
    if (filters.status && wikiPageStatus(page) !== filters.status) return false;
    if (filters.source_file_id && !(page.sources ?? []).includes(filters.source_file_id)) return false;
    return true;
  });
}

function wikiPageStatus(page: WikiPageSummary): string {
  if (page.has_candidate) return "pending_candidate";
  if (page.status) return page.status;
  if (page.manual_edited) return "manual_edited";
  return "generated";
}

const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 disabled:opacity-40";
const headerButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-40";
const wikiWorkbenchTab = "inline-flex h-14 items-center border-b-2 px-0 text-base font-semibold transition";
const wikiResourcePaneCompact = "flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white";
