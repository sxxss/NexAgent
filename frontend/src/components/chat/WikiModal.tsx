"use client";

import { BookOpen, Check, Copy, Loader2, Sparkles, X } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { crystallizeWiki, type KBMeta, type WikiPage } from "@/lib/api";

export function WikiModal({
  open,
  onClose,
  threadId,
  kbs,
  model,
}: {
  open: boolean;
  onClose: () => void;
  threadId?: string;
  kbs: KBMeta[];
  model?: string;
}) {
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState<WikiPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kbId, setKbId] = useState("");
  const [copied, setCopied] = useState(false);

  if (!open) return null;

  const run = async () => {
    if (!threadId) {
      setError("当前没有可沉淀的对话");
      return;
    }
    setLoading(true);
    setError(null);
    setPage(null);
    try {
      const result = await crystallizeWiki({ thread_id: threadId, kb_id: kbId || undefined, model });
      setPage(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "沉淀失败");
    } finally {
      setLoading(false);
    }
  };

  const copy = async () => {
    if (!page?.content) return;
    await navigator.clipboard.writeText(page.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm">
      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-3xl border border-white/80 bg-white shadow-[0_30px_90px_rgba(39,56,87,0.28)]">
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
              <BookOpen size={16} />
            </span>
            <div>
              <h3 className="text-sm font-bold text-slate-900">沉淀为 Wiki</h3>
              <p className="text-xs text-slate-500">把当前对话提炼成可复用的知识页面</p>
            </div>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X size={16} />
          </button>
        </header>

        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
          <select
            value={kbId}
            onChange={(e) => setKbId(e.target.value)}
            className="h-9 rounded-xl border border-slate-200 bg-white px-3 text-sm outline-none focus:border-indigo-300"
          >
            <option value="">不写入知识库（仅生成页面）</option>
            {kbs.map((kb) => (
              <option key={kb.kb_id} value={kb.kb_id}>
                写入：{kb.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading}
            className="inline-flex h-9 items-center gap-2 rounded-xl bg-[#4f46e5] px-3.5 text-xs font-semibold text-white shadow-sm hover:brightness-110 disabled:opacity-50"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {page ? "重新生成" : "开始沉淀"}
          </button>
          {page?.content ? (
            <button
              type="button"
              onClick={() => void copy()}
              className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-600 hover:bg-slate-50"
            >
              {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
              {copied ? "已复制" : "复制"}
            </button>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-sm text-rose-600">{error}</div> : null}
          {!page && !error && !loading ? (
            <div className="mt-12 text-center text-sm text-slate-400">选择是否写入知识库，然后点击「开始沉淀」</div>
          ) : null}
          {loading ? (
            <div className="mt-12 flex flex-col items-center gap-3 text-sm text-slate-400">
              <Loader2 size={24} className="animate-spin text-indigo-500" />
              正在提炼知识页面...
            </div>
          ) : null}
          {page ? (
            <div>
              {page.warning ? (
                <div className="mb-3 rounded-xl border border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-700">{page.warning}</div>
              ) : null}
              {page.tags?.length ? (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {page.tags.map((tag) => (
                    <span key={tag} className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-600">
                      {tag}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.content ?? ""}</ReactMarkdown>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
