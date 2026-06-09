"use client";

import { useMemo, useState } from "react";
import { Check, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { crystallizeWikiKbPage, type FileMeta, type WikiPageType } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const pageTypes: { value: WikiPageType; label: string }[] = [
  { value: "note", label: "笔记" },
  { value: "topic", label: "主题" },
  { value: "synthesis", label: "综合" },
  { value: "query", label: "问答" },
];

type CrystalTemplateKey = "meeting" | "decision" | "debug" | "query" | "note";
type WikiConfidence = "UNVERIFIED" | "EXTRACTED" | "INFERRED" | "AMBIGUOUS";

const crystalTemplates: Record<CrystalTemplateKey, string> = {
  meeting: "## 背景\n\n## 讨论要点\n\n- \n\n## 决议\n\n- \n\n## 后续行动\n\n- ",
  decision: "## 结论\n\n## 依据\n\n- \n\n## 影响\n\n## 待复核\n\n- ",
  debug: "## 问题\n\n## 现象\n\n## 排查过程\n\n- \n\n## 结论\n\n## 后续处理\n\n- ",
  query: "## 查询问题\n\n## 可信结论\n\n- \n\n## 证据页面\n\n- \n\n## 仍需确认\n\n- ",
  note: "## 记录\n\n## 关键点\n\n- \n\n## 关联页面\n\n- ",
};

const crystalTemplateOptions: { key: CrystalTemplateKey; label: string }[] = [
  { key: "meeting", label: "会议纪要" },
  { key: "decision", label: "结论沉淀" },
  { key: "debug", label: "问题排查" },
  { key: "query", label: "查询结果" },
  { key: "note", label: "临时笔记" },
];

const confidenceSegments: { value: WikiConfidence; label: string }[] = [
  { value: "UNVERIFIED", label: "未验证" },
  { value: "EXTRACTED", label: "抽取" },
  { value: "INFERRED", label: "推断" },
  { value: "AMBIGUOUS", label: "有歧义" },
];

export function WikiCrystallizePanel({ kbId, files, onCreated }: { kbId: string; files: FileMeta[]; onCreated: (pageId: string) => void }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [pageType, setPageType] = useState<WikiPageType>("note");
  const [confidence, setConfidence] = useState<WikiConfidence>("UNVERIFIED");
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [sourcesText, setSourcesText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const indexedFiles = useMemo(() => files.filter((file) => file.status === "indexed" || file.status === "graph_indexed"), [files]);
  const typedSourceIds = useMemo(
    () => sourcesText.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean),
    [sourcesText],
  );
  const selectedSources = useMemo(() => Array.from(new Set([...sourceIds, ...typedSourceIds])), [sourceIds, typedSourceIds]);
  const selectedSourceCount = selectedSources.length;
  const typeLabel = pageTypes.find((item) => item.value === pageType)?.label ?? pageType;

  const toggleSource = (fileId: string) => {
    setSourceIds((current) => (current.includes(fileId) ? current.filter((item) => item !== fileId) : [...current, fileId]));
  };

  const applyCrystalTemplate = (key: CrystalTemplateKey) => {
    const template = crystalTemplates[key];
    setContent((current) => (current.trim() ? `${current.trimEnd()}\n\n${template}` : template));
  };

  const clearCrystalDraft = () => {
    setTitle("");
    setContent("");
    setPageType("note");
    setConfidence("UNVERIFIED");
    setSourceIds([]);
    setSourcesText("");
    setError("");
  };

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
        confidence,
        sources: selectedSources,
      });
      clearCrystalDraft();
      onCreated(page.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建 Wiki 页面失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className="space-y-3">
        <section className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-900">插入模板</h3>
            <p className="mt-1 text-xs text-slate-500">模板会追加到正文末尾</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {crystalTemplateOptions.map((template) => (
              <button
                key={template.key}
                type="button"
                onClick={() => applyCrystalTemplate(template.key)}
                className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 transition hover:border-amber-300 hover:bg-amber-50 hover:text-amber-800"
              >
                {template.label}
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">来源素材</h3>
              <p className="mt-1 text-xs text-slate-500">可留空作为纯人工笔记</p>
            </div>
            <Badge variant="secondary">{selectedSourceCount}</Badge>
          </div>
          <div className="max-h-[280px] space-y-2 overflow-auto pr-1">
            {files.length ? files.map((file) => {
              const selected = sourceIds.includes(file.file_id);
              return (
                <button
                  key={file.file_id}
                  type="button"
                  onClick={() => toggleSource(file.file_id)}
                  className={cn(
                    "w-full rounded-lg border px-3 py-2 text-left transition",
                    selected ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white hover:border-slate-300",
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={cn("flex h-5 w-5 shrink-0 items-center justify-center rounded border", selected ? "border-blue-500 bg-blue-500 text-white" : "border-slate-300 text-transparent")}>
                      <Check size={12} />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-800">{file.filename}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 pl-7 text-[11px] text-slate-500">
                    <span>{formatFileSize(file.file_size)}</span>
                    <span>·</span>
                    <span>{fileStatusLabel(file.status)}</span>
                  </div>
                </button>
              );
            }) : <p className="py-8 text-center text-xs text-slate-400">暂无来源素材</p>}
          </div>
          <label className="mt-3 block space-y-1">
            <span className="text-xs font-semibold text-slate-700">补充来源 ID</span>
            <input
              value={sourcesText}
              onChange={(event) => setSourcesText(event.target.value)}
              className={inputClass}
              placeholder="多个 ID 用逗号分隔"
            />
          </label>
        </section>
      </aside>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-50 text-amber-700"><Sparkles size={16} /></span>
            <div>
              <h3 className="text-sm font-semibold text-slate-900">写入 Wiki 页面</h3>
              <p className="text-xs text-slate-500">把对话结论、人工笔记或排查过程沉淀成 Wiki 页面</p>
            </div>
          </div>
          <Badge variant="secondary">{indexedFiles.length}/{files.length} 已入库</Badge>
        </div>

        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">页面标题</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} className={inputClass} placeholder="例如：客户访谈结论" />
          </label>
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
            <div className="space-y-1">
              <span className="text-xs font-semibold text-slate-700">页面类型</span>
              <div className="grid grid-cols-4 overflow-hidden rounded-lg border border-slate-200 bg-slate-50 p-1">
                {pageTypes.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setPageType(item.value)}
                    className={cn(segmentButton, pageType === item.value && activeSegmentButton)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-xs font-semibold text-slate-700">置信度</span>
              <div className="grid grid-cols-4 overflow-hidden rounded-lg border border-slate-200 bg-slate-50 p-1">
                {confidenceSegments.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setConfidence(item.value)}
                    className={cn(segmentButton, confidence === item.value && activeSegmentButton)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">Markdown 内容</span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              className="min-h-[330px] w-full resize-y rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none focus:border-amber-300 focus:ring-2 focus:ring-amber-100"
              placeholder={"把对话结论、人工笔记、排查过程或查询结果沉淀成 Wiki 页面"}
              spellCheck={false}
            />
          </label>
          <div className="rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="min-w-0 truncate text-sm text-slate-900">{title.trim() || "未填写标题"}</strong>
              <Badge variant="secondary">{typeLabel}</Badge>
            </div>
            <p className="mt-2 text-xs text-slate-600">
              置信度 {confidence} · 来源 {selectedSourceCount} 个 · manual_edited=true · 生成后需要人工复核
            </p>
          </div>
          {error ? <div className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={clearCrystalDraft} className={secondaryButton}>
              <RotateCcw size={14} />
              清空草稿
            </button>
            <button type="button" onClick={() => void create()} disabled={saving || !title.trim() || !content.trim()} className={primaryButton}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              预览确认并生成页面
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

const inputClass = "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-amber-300 focus:ring-2 focus:ring-amber-100 disabled:bg-slate-50 disabled:text-slate-400";
const segmentButton = "h-8 min-w-0 rounded-md px-2 text-xs font-semibold text-slate-500 transition hover:text-slate-900";
const activeSegmentButton = "bg-white text-slate-950 shadow-sm";
const primaryButton = "inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-slate-950 px-4 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
const secondaryButton = "inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50";

function fileStatusLabel(status: FileMeta["status"] | string) {
  const labels: Record<string, string> = {
    uploaded: "等待解析",
    parsing: "解析中",
    parsed: "已解析",
    parse_error: "解析失败",
    indexing: "入库中",
    indexed: "已入库",
    index_error: "入库失败",
    graphing: "图谱中",
    graph_indexed: "图谱已入库",
    error_graphing: "图谱失败",
    indexed_with_graph_degraded: "图谱降级",
  };
  return labels[status] ?? status ?? "未知";
}

function formatFileSize(size: number) {
  if (!Number.isFinite(size) || size <= 0) return "0 KB";
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
