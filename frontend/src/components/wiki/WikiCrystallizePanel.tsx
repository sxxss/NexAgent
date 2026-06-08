"use client";

import { useMemo, useState } from "react";
import { FileText, Loader2, Sparkles } from "lucide-react";
import { crystallizeWikiKbPage, type FileMeta, type WikiPageType } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const pageTypes: { value: WikiPageType; label: string }[] = [
  { value: "note", label: "笔记" },
  { value: "topic", label: "主题" },
  { value: "entity", label: "实体" },
  { value: "synthesis", label: "综合" },
  { value: "comparison", label: "对比" },
  { value: "query", label: "问答" },
];

export function WikiCrystallizePanel({ kbId, files, onCreated }: { kbId: string; files: FileMeta[]; onCreated: (pageId: string) => void }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [pageType, setPageType] = useState<WikiPageType>("note");
  const [sourceFileId, setSourceFileId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const indexedFiles = useMemo(() => files.filter((file) => file.status === "indexed" || file.status === "graph_indexed"), [files]);

  const create = async () => {
    if (!title.trim() || !content.trim()) {
      setError("标题和内容不能为空");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const page = await crystallizeWikiKbPage(kbId, {
        title: title.trim(),
        content: content.trim(),
        type: pageType,
        confidence: "UNVERIFIED",
        sources: sourceFileId ? [sourceFileId] : [],
      });
      setTitle("");
      setContent("");
      setSourceFileId("");
      onCreated(page.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建 Wiki 页面失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-50 text-amber-700"><Sparkles size={16} /></span>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">写入 Wiki 页面</h3>
            <p className="text-xs text-slate-500">把整理好的 Markdown 保存为可检索页面</p>
          </div>
        </div>

        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} className={inputClass} placeholder="例如：项目鉴权流程" />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">页面类型</span>
              <select value={pageType} onChange={(event) => setPageType(event.target.value as WikiPageType)} className={inputClass}>
                {pageTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">来源文件</span>
              <select value={sourceFileId} onChange={(event) => setSourceFileId(event.target.value)} className={inputClass}>
                <option value="">不绑定来源文件</option>
                {indexedFiles.map((file) => <option key={file.file_id} value={file.file_id}>{file.filename}</option>)}
              </select>
            </label>
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">Markdown 内容</span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              className="min-h-[340px] w-full resize-y rounded-xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs leading-6 text-slate-50 outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
              placeholder={"## 核心结论\n\n- ..."}
              spellCheck={false}
            />
          </label>
          {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
          <button type="button" onClick={() => void create()} disabled={saving || !title.trim() || !content.trim()} className={cn(primaryButton, "sm:w-auto")}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            保存页面
          </button>
        </div>
      </section>

      <aside className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-semibold text-slate-700">来源文件</h3>
          <Badge variant="secondary">{indexedFiles.length}/{files.length}</Badge>
        </div>
        <div className="max-h-[460px] space-y-2 overflow-auto">
          {files.length ? files.map((file) => (
            <div key={file.file_id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
              <div className="flex items-center gap-2">
                <FileText size={14} className="shrink-0 text-slate-400" />
                <p className="min-w-0 truncate text-xs font-semibold text-slate-700">{file.filename}</p>
              </div>
              <p className="mt-1 font-mono text-[10px] text-slate-400">{file.file_id}</p>
            </div>
          )) : <p className="py-8 text-center text-xs text-slate-400">暂无来源文件</p>}
        </div>
      </aside>
    </div>
  );
}

const inputClass = "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-amber-300 focus:ring-2 focus:ring-amber-100 disabled:bg-slate-50 disabled:text-slate-400";
const primaryButton = "inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
