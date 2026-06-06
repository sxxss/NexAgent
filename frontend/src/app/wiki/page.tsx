"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/PageHeader";
import { deleteWikiPage, fetchWikiPage, fetchWikiPages, type WikiPage } from "@/lib/api";
import { cn } from "@/lib/utils";

const outlineButton =
  "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50";

export default function WikiPageView() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [synced, setSynced] = useState(false);

  const listQuery = useQuery({ queryKey: ["wiki-pages"], queryFn: fetchWikiPages });
  const pages = listQuery.data ?? [];

  // Auto-select the first page once the list loads.
  if (!synced && pages.length > 0 && !selectedId) {
    setSynced(true);
    setSelectedId(pages[0].id);
  }

  const detailQuery = useQuery({
    queryKey: ["wiki-page", selectedId],
    queryFn: () => (selectedId ? fetchWikiPage(selectedId) : Promise.resolve(null)),
    enabled: !!selectedId,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteWikiPage(id),
    onSuccess: (_data, id) => {
      if (selectedId === id) setSelectedId(null);
      void queryClient.invalidateQueries({ queryKey: ["wiki-pages"] });
    },
  });

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="LLM Wiki"
        title="知识沉淀"
        description="把对话提炼成的结构化 Wiki 知识页面集中在这里浏览与管理。在对话页点击「沉淀 Wiki」即可新增。"
        actions={
          <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: ["wiki-pages"] })} className={outlineButton}>
            <RefreshCw size={14} className={listQuery.isFetching ? "animate-spin" : ""} />
            刷新
          </button>
        }
      />

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* List */}
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-4 py-3 text-xs font-semibold text-slate-500">
            共 {pages.length} 篇
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {listQuery.isLoading ? (
              <div className="flex items-center gap-2 px-3 py-6 text-sm text-slate-400"><Loader2 size={15} className="animate-spin" /> 加载中...</div>
            ) : pages.length === 0 ? (
              <div className="px-3 py-10 text-center text-sm text-slate-400">
                <BookOpen size={22} className="mx-auto mb-2 text-slate-300" />
                还没有 Wiki 页面。<br />在对话页点击「沉淀 Wiki」生成。
              </div>
            ) : (
              pages.map((page) => (
                <button
                  key={page.id}
                  type="button"
                  onClick={() => setSelectedId(page.id)}
                  className={cn(
                    "group mb-1 flex w-full items-start gap-2 rounded-xl px-3 py-2.5 text-left transition",
                    selectedId === page.id ? "bg-indigo-50" : "hover:bg-slate-50",
                  )}
                >
                  <FileText size={15} className={cn("mt-0.5 shrink-0", selectedId === page.id ? "text-indigo-600" : "text-slate-400")} />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate text-sm font-semibold", selectedId === page.id ? "text-indigo-700" : "text-slate-800")}>{page.title}</span>
                    {page.tags?.length ? (
                      <span className="mt-0.5 block truncate text-[11px] text-slate-400">{page.tags.join(" · ")}</span>
                    ) : null}
                  </span>
                  <Trash2
                    size={14}
                    className="mt-0.5 shrink-0 text-slate-300 opacity-0 transition hover:text-rose-500 group-hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteMutation.mutate(page.id);
                    }}
                  />
                </button>
              ))
            )}
          </div>
        </aside>

        {/* Detail */}
        <section className="min-h-0 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
          {!selectedId ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">选择左侧的页面查看内容</div>
          ) : detailQuery.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 size={16} className="animate-spin" /> 加载中...</div>
          ) : detailQuery.data ? (
            <WikiContent page={detailQuery.data} />
          ) : (
            <div className="text-sm text-slate-400">页面不存在</div>
          )}
        </section>
      </main>
    </div>
  );
}

function WikiContent({ page }: { page: WikiPage }) {
  return (
    <article>
      {page.tags?.length ? (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {page.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-600">{tag}</span>
          ))}
        </div>
      ) : null}
      {page.warning ? (
        <div className="mb-4 rounded-xl border border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-700">{page.warning}</div>
      ) : null}
      <div className="markdown-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.content ?? ""}</ReactMarkdown>
      </div>
    </article>
  );
}
