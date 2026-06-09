"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useMemo, useState } from "react";
import { CheckCircle, Edit3, FileText, Loader2, Save, ShieldAlert, Trash2, X } from "lucide-react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  acceptGeneratedWikiKbPage,
  crystallizeWikiKbPage,
  deleteWikiKbPage,
  discardGeneratedWikiKbPage,
  updateWikiKbPage,
  type FileMeta,
  type WikiPageDetail,
  type WikiPageSummary,
  type WikiPageType,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

type PageMode = "preview" | "edit";

export interface WikiPageFilters {
  q: string;
  type: string;
  status: string;
  source_file_id: string;
}

export function WikiPagePanel({
  kbId,
  pages,
  files,
  selectedPage,
  onSelect,
  onReload,
}: {
  kbId: string;
  pages: WikiPageSummary[];
  files: FileMeta[];
  selectedPage: WikiPageDetail | null;
  onSelect: (pageId: string) => void;
  onReload: (pageId?: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<PageMode>("preview");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [acting, setActing] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(selectedPage?.content ?? "");
    setError("");
    setMode("preview");
  }, [selectedPage?.id, selectedPage?.content]);

  const pageLookup = useMemo(() => buildPageLookup(pages), [pages]);
  const renderedContent = useMemo(() => renderWikiLinks(selectedPage?.content ?? "", pageLookup), [pageLookup, selectedPage?.content]);

  const save = async () => {
    if (!selectedPage) return;
    setSaving(true);
    setError("");
    try {
      await updateWikiKbPage(kbId, selectedPage.id, { content: draft, frontmatter: selectedPage.frontmatter });
      await onReload(selectedPage.id);
      setMode("preview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Wiki 页面失败");
    } finally {
      setSaving(false);
    }
  };

  const acceptCandidate = async () => {
    if (!selectedPage) return;
    setActing("accept");
    setError("");
    try {
      await acceptGeneratedWikiKbPage(kbId, selectedPage.id);
      await onReload(selectedPage.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "接受候选失败");
    } finally {
      setActing("");
    }
  };

  const discardCandidate = async () => {
    if (!selectedPage) return;
    setActing("discard");
    setError("");
    try {
      await discardGeneratedWikiKbPage(kbId, selectedPage.id);
      await onReload(selectedPage.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "丢弃候选失败");
    } finally {
      setActing("");
    }
  };

  const deletePage = async () => {
    if (!selectedPage || !confirm(`确认删除 Wiki 页面「${selectedPage.title}」？删除后建议重新编译以刷新图谱。`)) return;
    setActing("delete");
    setError("");
    try {
      await deleteWikiKbPage(kbId, selectedPage.id);
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Wiki 页面失败");
    } finally {
      setActing("");
    }
  };

  const createLinkedPage = async (title: string) => {
    if (!title.trim()) return;
    setActing(`create:${title}`);
    setError("");
    try {
      const sourceTitle = selectedPage?.title || "Wiki";
      const page = await crystallizeWikiKbPage(kbId, {
        title: title.trim(),
        type: "topic",
        confidence: "UNVERIFIED",
        content: `# ${title.trim()}\n\n## Summary\n待补充。\n\n## Notes\n- 从 [[${sourceTitle}]] 创建。\n\n## Sources\n- [[${sourceTitle}]]`,
        sources: selectedPage?.sources ?? [],
      });
      await onReload(page.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建 Wiki 页面失败");
    } finally {
      setActing("");
    }
  };

  if (!pages.length) {
    return (
      <div className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 text-center">
        <FileText size={28} className="text-slate-300" />
        <p className="mt-3 text-sm font-semibold text-slate-700">还没有 Wiki 页面</p>
        <p className="mt-1 text-xs text-slate-400">上传文档并处理，或在沉淀面板手动创建页面。</p>
      </div>
    );
  }

  return (
      <section className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-900">{selectedPage?.title ?? "选择页面"}</h3>
            {selectedPage ? <p className="mt-1 truncate text-xs text-slate-400">{selectedPage.path}</p> : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-9 overflow-hidden rounded-lg border border-slate-200 bg-white p-1">
              <button type="button" onClick={() => setMode("preview")} className={cn(segmentButton, mode === "preview" && "bg-slate-900 text-white")}>预览</button>
              <button type="button" onClick={() => setMode("edit")} className={cn(segmentButton, mode === "edit" && "bg-slate-900 text-white")}><Edit3 size={12} />编辑</button>
            </div>
            <button type="button" onClick={() => void save()} disabled={!selectedPage || saving || draft === selectedPage?.content} className={cn(actionButton, "border-amber-200 text-amber-800")}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              保存
            </button>
            <button type="button" onClick={() => void deletePage()} disabled={!selectedPage || acting === "delete"} className={cn(actionButton, "border-rose-200 text-rose-700")}>
              {acting === "delete" ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              删除
            </button>
          </div>
        </div>

        {error ? <div className="mx-4 mt-4 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        {selectedPage ? (
          <div className="mx-4 mt-4 grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600 sm:grid-cols-3">
            <MetaItem label="类型" value={pageTypeLabel(selectedPage.type)} />
            <MetaItem label="置信度" value={selectedPage.confidence} />
            <MetaItem label="更新时间" value={selectedPage.updated_at ? formatDate(selectedPage.updated_at) : "未知"} />
            <MetaItem label="来源" value={sourceNames(selectedPage.sources, files).join("、") || "无"} className="sm:col-span-2" />
            <MetaItem label="编辑状态" value={selectedPage.manual_edited ? "人工编辑" : "系统生成"} />
          </div>
        ) : null}

        {selectedPage?.candidate ? (
          <div className="mx-4 mt-4 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 font-semibold"><ShieldAlert size={14} />存在待确认候选</span>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => void acceptCandidate()} disabled={Boolean(acting)} className={cn(actionButton, "h-8 border-emerald-200 text-emerald-700")}>
                  {acting === "accept" ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                  接受候选
                </button>
                <button type="button" onClick={() => void discardCandidate()} disabled={Boolean(acting)} className={cn(actionButton, "h-8 border-slate-200 text-slate-600")}>
                  {acting === "discard" ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />}
                  丢弃候选
                </button>
              </div>
            </div>
            {selectedPage.candidate.reason ? <p className="mt-2 text-amber-700">{selectedPage.candidate.reason}</p> : null}
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <CandidateBlock title="当前版本" content={selectedPage.content} />
              <CandidateBlock title="候选版本" content={selectedPage.candidate.content} />
            </div>
          </div>
        ) : selectedPage ? (
          <div className="mx-4 mt-4 flex items-center gap-2 rounded-xl border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
            <CheckCircle size={14} />
            页面内容可用于 Wiki 检索。
          </div>
        ) : null}

        {mode === "edit" ? (
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="m-4 min-h-[500px] w-[calc(100%-2rem)] resize-y rounded-xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-50 outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
            spellCheck={false}
          />
        ) : (
          <div className="max-h-[720px] overflow-auto bg-slate-50/50 px-5 py-4">
            <div className="markdown-body rounded-xl border border-slate-100 bg-white px-5 py-4 shadow-sm">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                urlTransform={preserveWikiUrl}
                components={{
                  a: ({ href, children }) => {
                    if (href?.startsWith("wiki:")) {
                      const pageId = decodeURIComponent(href.slice(5));
                      return <button type="button" className="wiki-link font-semibold text-blue-700 underline decoration-blue-300 underline-offset-2 transition hover:text-blue-800" onClick={() => onSelect(pageId)}>{children}</button>;
                    }
                    if (href?.startsWith("wiki-new:")) {
                      const title = decodeURIComponent(href.slice(9));
                      return (
                        <button
                          type="button"
                          className="wiki-link font-semibold text-blue-700 underline decoration-blue-300 underline-offset-2 transition hover:text-blue-800 disabled:opacity-60"
                          disabled={Boolean(acting)}
                          onClick={() => void createLinkedPage(title)}
                        >
                          {acting === `create:${title}` ? "创建中..." : children}
                        </button>
                      );
                    }
                    return <a href={href} target="_blank" rel="noreferrer" className="font-medium text-blue-700 underline decoration-blue-200 underline-offset-2 hover:text-blue-800">{children}</a>;
                  },
                }}
              >
                {renderedContent}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </section>
  );
}

export function WikiPageDirectory({
  pages,
  files,
  selectedPageId,
  filters,
  onFilterChange,
  onSelect,
}: {
  pages: WikiPageSummary[];
  files: FileMeta[];
  selectedPageId: string;
  filters: WikiPageFilters;
  onFilterChange: (filters: WikiPageFilters) => void;
  onSelect: (pageId: string) => void;
}) {
  const sourceFilter = filters.source_file_id;
  const updateFilter = (key: keyof WikiPageFilters, value: string) => {
    onFilterChange({ ...filters, [key]: value });
  };

  return (
    <section className="bg-white">
      <div className="border-b border-slate-100 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800"><FileText size={14} />页面</h3>
          <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">{pages.length}</span>
        </div>
        <div className={compactFilterBar}>
          <input
            value={filters.q}
            onChange={(event) => updateFilter("q", event.target.value)}
            placeholder="搜索页面"
            className={cn(filterInput, "min-w-0 flex-1")}
          />
          <select value={filters.type} onChange={(event) => updateFilter("type", event.target.value)} className={cn(filterInput, "w-24")}>
            <option value="">类型</option>
            {pageTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)} className={cn(filterInput, "w-24")}>
            <option value="">状态</option>
            {pageStatuses.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <select value={sourceFilter} onChange={(event) => updateFilter("source_file_id", event.target.value)} className={cn(filterInput, "w-28")}>
            <option value="">全部来源</option>
            {files.map((file) => <option key={file.file_id} value={file.file_id}>{file.filename}</option>)}
          </select>
          {filters.q || filters.type || filters.status || filters.source_file_id ? (
            <button type="button" onClick={() => onFilterChange(emptyFilters())} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 hover:bg-slate-50" title="清空筛选">
              <X size={13} />
            </button>
          ) : null}
        </div>
      </div>
      <div className="max-h-[420px] overflow-auto py-2">
        {pages.length ? pages.map((page) => (
          <button
            key={page.id}
            type="button"
            onClick={() => onSelect(page.id)}
            className={cn(
              "flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left transition",
              page.id === selectedPageId ? "bg-sky-50 text-sky-800" : "text-slate-700 hover:bg-slate-50",
            )}
          >
            <span className="min-w-0 truncate text-sm font-semibold">{page.title}</span>
            <span className="flex shrink-0 items-center gap-1.5">
              {page.has_candidate ? <ShieldAlert size={13} className="text-amber-500" /> : null}
              <span className="text-xs text-slate-400">{pageTypeLabel(page.type)}</span>
            </span>
          </button>
        )) : (
          <div className="mx-3 rounded-lg border border-dashed border-slate-200 bg-white px-3 py-8 text-center text-xs text-slate-400">没有匹配页面</div>
        )}
      </div>
    </section>
  );
}

function MetaItem({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <span className="block text-[11px] text-slate-400">{label}</span>
      <strong className="mt-1 block overflow-hidden text-ellipsis whitespace-nowrap font-medium text-slate-700">{value}</strong>
    </div>
  );
}

function CandidateBlock({ title, content }: { title: string; content: string }) {
  return (
    <div className="min-w-0">
      <span className="mb-1 block text-[11px] font-semibold text-amber-700">{title}</span>
      <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg border border-amber-100 bg-white/80 p-3 text-[11px] leading-5 text-slate-700">{content}</pre>
    </div>
  );
}

export function emptyFilters(): WikiPageFilters {
  return { q: "", type: "", status: "", source_file_id: "" };
}

function buildPageLookup(pages: WikiPageSummary[]) {
  const lookup = new Map<string, string>();
  for (const page of pages) {
    for (const key of [page.title, page.id, page.path?.split("/").pop()?.replace(/\.md$/, "")]) {
      const normalized = normalizeWikiKey(key);
      if (normalized && !lookup.has(normalized)) lookup.set(normalized, page.id);
    }
  }
  return lookup;
}

function renderWikiLinks(content: string, pageLookup: Map<string, string>) {
  return content.replace(/\[\[([^\]#|]+)(?:[|#][^\]]*)?\]\]/g, (_match, rawTitle: string) => {
    const title = String(rawTitle || "").trim();
    const pageId = pageLookup.get(normalizeWikiKey(title));
    return pageId ? `[${title}](wiki:${encodeURIComponent(pageId)})` : `[${title}](wiki-new:${encodeURIComponent(title)})`;
  });
}

function preserveWikiUrl(value: string) {
  if (value.startsWith("wiki:") || value.startsWith("wiki-new:")) return value;
  return defaultUrlTransform(value);
}

function normalizeWikiKey(value = "") {
  return String(value)
    .trim()
    .replace(/^([^:]+):/, "")
    .replace(/\.md$/, "")
    .replace(/[“”‘’"']/g, "")
    .replace(/[《》]/g, "")
    .replace(/[\s\-_/\\、，,。.!?！？:：;；()[\]{}<>`]+/g, "")
    .toLowerCase();
}

function sourceNames(sourceIds: string[], files: FileMeta[]) {
  return sourceIds.map((id) => files.find((file) => file.file_id === id)?.filename || id);
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

const pageTypes: Array<{ value: WikiPageType; label: string }> = [
  { value: "source", label: "来源" },
  { value: "entity", label: "实体" },
  { value: "topic", label: "主题" },
  { value: "synthesis", label: "综合" },
  { value: "comparison", label: "对比" },
  { value: "query", label: "问答" },
  { value: "note", label: "笔记" },
];

const pageStatuses = [
  { value: "generated", label: "生成页" },
  { value: "manual_edited", label: "人工编辑" },
  { value: "pending_candidate", label: "候选待处理" },
  { value: "needs_review", label: "需要复核" },
];

const compactFilterBar = "mt-3 flex flex-wrap items-center gap-1.5";
const filterInput = "h-8 rounded-lg border border-slate-200 bg-white px-2.5 text-xs text-slate-700 outline-none transition focus:border-sky-300 focus:ring-2 focus:ring-sky-100";
const segmentButton = "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold text-slate-600 transition";
const actionButton = "inline-flex h-9 items-center gap-2 rounded-lg border bg-white px-3 text-xs font-semibold transition hover:bg-slate-50 disabled:opacity-40";
