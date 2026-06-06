"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Brain, Edit2, Lightbulb, Plus, RefreshCw, Search, Star, Tag, Trash2, User } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { createMemory, deleteMemory, fetchMemories, fetchMemoryStats, updateMemory, type MemoryEntry } from "@/lib/api";

const USER_ID = "default";

const TYPES = {
  fact: { label: "事实", icon: Lightbulb },
  preference: { label: "偏好", icon: Star },
  episode: { label: "事件", icon: Tag },
} as const;

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MemoryEntry | null>(null);
  const memoriesQuery = useQuery({ queryKey: ["memories", query, typeFilter], queryFn: () => fetchMemories(USER_ID, { q: query || undefined, memory_type: typeFilter || undefined, limit: 50 }) });
  const statsQuery = useQuery({ queryKey: ["memory-stats"], queryFn: () => fetchMemoryStats(USER_ID) });
  const entries = memoriesQuery.data?.memories ?? [];
  const stats = statsQuery.data ?? { total: 0, by_type: {} };

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["memories"] });
    void queryClient.invalidateQueries({ queryKey: ["memory-stats"] });
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Memory"
        title="长期记忆"
        description="查看、筛选和手动维护 Agent 保存的长期记忆。后续可按用户、Agent 和重要度进行更细粒度治理。"
        actions={
          <>
            <button type="button" onClick={refresh} className={outlineButton}><RefreshCw size={14} className={memoriesQuery.isFetching ? "animate-spin" : ""} />刷新</button>
            <button type="button" onClick={() => { setEditing(null); setModalOpen(true); }} className="inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white hover:bg-slate-800"><Plus size={14} />添加记忆</button>
          </>
        }
      />

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="grid gap-4 md:grid-cols-4">
          <Stat label="全部记忆" value={stats.total} icon={Brain} />
          <Stat label="事实" value={stats.by_type.fact ?? 0} icon={Lightbulb} />
          <Stat label="偏好" value={stats.by_type.preference ?? 0} icon={Star} />
          <Stat label="事件" value={stats.by_type.episode ?? 0} icon={Tag} />
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex h-9 min-w-72 flex-1 items-center gap-2 rounded-lg bg-slate-50 px-3">
            <Search size={15} className="text-slate-400" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标签或内容" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400" />
          </div>
          <div className="flex overflow-hidden rounded-lg border border-slate-200">
            <button type="button" onClick={() => setTypeFilter("")} className={tabClass(!typeFilter)}>全部</button>
            {Object.entries(TYPES).map(([key, meta]) => <button key={key} type="button" onClick={() => setTypeFilter(key)} className={tabClass(typeFilter === key)}>{meta.label}</button>)}
          </div>
        </div>

        <div className="mt-5">
          {entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white py-20 text-center"><Brain size={34} className="text-slate-300" /><p className="mt-4 text-sm font-semibold text-slate-700">暂无匹配记忆</p></div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {entries.map((entry) => <MemoryCard key={entry.id} entry={entry} onEdit={() => { setEditing(entry); setModalOpen(true); }} onDelete={() => void deleteMemory(USER_ID, entry.id).then(refresh)} />)}
            </div>
          )}
        </div>
      </main>

      <MemoryModal key={editing?.id ?? "new"} open={modalOpen} initial={editing} onClose={() => setModalOpen(false)} onSaved={refresh} />
    </div>
  );
}

function MemoryCard({ entry, onEdit, onDelete }: { entry: MemoryEntry; onEdit: () => void; onDelete: () => void }) {
  const meta = TYPES[entry.memory_type] ?? TYPES.fact;
  const Icon = meta.icon;
  return (
    <Card className="group">
      <CardContent className="p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 text-sky-700"><Icon size={18} /></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5"><h2 className="truncate text-sm font-semibold text-slate-950">{entry.key}</h2><Badge variant="secondary">{meta.label}</Badge><Badge variant="secondary">{entry.source === "agent" ? <Bot size={10} /> : <User size={10} />}{entry.source === "agent" ? "Agent" : "手动"}</Badge></div>
            <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-600">{entry.value}</p>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3">
          <span className="flex-1 text-xs text-slate-400">重要度 {Math.round(entry.importance * 100)}%</span>
          <button type="button" onClick={onEdit} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Edit2 size={14} /></button>
          <button type="button" onClick={onDelete} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button>
        </div>
      </CardContent>
    </Card>
  );
}

function MemoryModal({ open, initial, onClose, onSaved }: { open: boolean; initial: MemoryEntry | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState<{
    key: string;
    value: string;
    memory_type: MemoryEntry["memory_type"];
    importance: number;
  }>({ key: initial?.key ?? "", value: initial?.value ?? "", memory_type: initial?.memory_type ?? "fact", importance: initial?.importance ?? 0.5 });
  const mutation = useMutation({
    mutationFn: () => initial ? updateMemory(USER_ID, initial.id, form) : createMemory(USER_ID, form),
    onSuccess: () => { onClose(); onSaved(); },
  });

  return (
    <Dialog open={open} onClose={onClose} title={initial ? "编辑记忆" : "添加记忆"} description="手动保存可被 Agent 使用的长期上下文">
      <div className="space-y-4">
        <input className={inputClass} placeholder="标签，例如 编程语言偏好" value={form.key} onChange={(event) => setForm({ ...form, key: event.target.value })} />
        <textarea className={`${inputClass} min-h-28 resize-none`} placeholder="内容" value={form.value} onChange={(event) => setForm({ ...form, value: event.target.value })} />
        <select className={inputClass} value={form.memory_type} onChange={(event) => setForm({ ...form, memory_type: event.target.value as MemoryEntry["memory_type"] })}>{Object.entries(TYPES).map(([key, meta]) => <option key={key} value={key}>{meta.label}</option>)}</select>
        <label className="block text-xs font-medium text-slate-600">重要度 {Math.round(form.importance * 100)}%<input className="mt-2 w-full accent-sky-600" type="range" min={0} max={1} step={0.1} value={form.importance} onChange={(event) => setForm({ ...form, importance: Number(event.target.value) })} /></label>
        <button type="button" disabled={!form.key.trim() || !form.value.trim() || mutation.isPending} onClick={() => mutation.mutate()} className="inline-flex h-10 w-full items-center justify-center rounded-lg bg-slate-950 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50">保存</button>
      </div>
    </Dialog>
  );
}

function Stat({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Brain }) {
  return <Card><CardContent className="p-5"><div className="flex items-center gap-2 text-sm text-slate-500"><Icon size={16} />{label}</div><p className="mt-2 text-3xl font-semibold text-slate-950">{value}</p></CardContent></Card>;
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100";
const outlineButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50";
const tabClass = (active: boolean) => `h-9 px-3 text-xs font-semibold ${active ? "bg-slate-950 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`;
