"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState } from "react";
import { CheckCircle, Edit3, FileText, Loader2, Save, ShieldAlert } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { updateWikiKbPage, type WikiPageDetail, type WikiPageSummary } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn, formatDate } from "@/lib/utils";

type PageMode = "preview" | "edit";

export function WikiPagePanel({
  kbId,
  pages,
  selectedPageId,
  selectedPage,
  onSelect,
  onReload,
}: {
  kbId: string;
  pages: WikiPageSummary[];
  selectedPageId: string;
  selectedPage: WikiPageDetail | null;
  onSelect: (pageId: string) => void;
  onReload: (pageId?: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<PageMode>("preview");
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDraft(selectedPage?.content ?? "");
    setError("");
    setMode("preview");
  }, [selectedPage?.id, selectedPage?.content]);

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
    <div className="grid min-h-[560px] gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
      <aside className="min-h-0 overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2">
          <h3 className="text-xs font-semibold text-slate-700">页面目录</h3>
          <span className="text-[11px] text-slate-400">{pages.length}</span>
        </div>
        <div className="max-h-[620px] overflow-auto p-2">
          {pages.map((page) => (
            <button
              key={page.id}
              type="button"
              onClick={() => onSelect(page.id)}
              className={cn(
                "mb-2 block w-full rounded-lg border px-3 py-2 text-left transition",
                page.id === selectedPageId ? "border-amber-200 bg-white shadow-sm" : "border-transparent bg-transparent hover:bg-white",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <p className="min-w-0 truncate text-sm font-semibold text-slate-800">{page.title}</p>
                {page.has_candidate ? <ShieldAlert size={14} className="shrink-0 text-amber-500" /> : null}
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Badge variant="secondary">{pageTypeLabel(page.type)}</Badge>
                <Badge variant={confidenceVariant(page.confidence)}>{page.confidence}</Badge>
              </div>
              {page.excerpt ? <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{page.excerpt}</p> : null}
              <p className="mt-2 truncate text-[11px] text-slate-400">{page.updated_at ? formatDate(page.updated_at) : page.path}</p>
            </button>
          ))}
        </div>
      </aside>

      <section className="min-w-0 rounded-xl border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-900">{selectedPage?.title ?? "选择页面"}</h3>
            {selectedPage ? (
              <p className="mt-1 truncate text-xs text-slate-400">{selectedPage.id} · {selectedPage.sources.length} sources</p>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex h-9 overflow-hidden rounded-lg border border-slate-200 bg-white p-1">
              <button type="button" onClick={() => setMode("preview")} className={cn(segmentButton, mode === "preview" && "bg-slate-900 text-white")}>预览</button>
              <button type="button" onClick={() => setMode("edit")} className={cn(segmentButton, mode === "edit" && "bg-slate-900 text-white")}><Edit3 size={12} />编辑</button>
            </div>
            <button type="button" onClick={() => void save()} disabled={!selectedPage || saving || draft === selectedPage?.content} className={cn(actionButton, "border-amber-200 text-amber-800")}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              保存
            </button>
          </div>
        </div>

        {error ? <div className="mx-4 mt-4 rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        {selectedPage?.has_candidate ? (
          <div className="mx-4 mt-4 flex items-center gap-2 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            <ShieldAlert size={14} />
            存在待确认的自动生成候选版本，当前保留手动编辑内容。
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
            className="m-4 min-h-[480px] w-[calc(100%-2rem)] resize-y rounded-xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-50 outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
            spellCheck={false}
          />
        ) : (
          <div className="max-h-[640px] overflow-auto px-5 py-4">
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedPage?.content ?? ""}</ReactMarkdown>
            </div>
          </div>
        )}
      </section>
    </div>
  );
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

function confidenceVariant(confidence: string): "secondary" | "info" | "success" | "warning" | "error" {
  if (confidence === "EXTRACTED") return "success";
  if (confidence === "INFERRED") return "info";
  if (confidence === "AMBIGUOUS") return "warning";
  if (confidence === "UNVERIFIED") return "secondary";
  return "secondary";
}

const segmentButton = "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold text-slate-600 transition";
const actionButton = "inline-flex h-9 items-center gap-2 rounded-lg border bg-white px-3 text-xs font-semibold transition hover:bg-slate-50 disabled:opacity-40";
