"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Bot, Boxes, CheckCircle, Loader2, Save, Sparkles, Wrench } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { draftCreator, saveCreator } from "@/lib/api";
import { cn } from "@/lib/utils";

type CreatorKind = "agent" | "skill" | "mcp";

const KINDS: Array<{ id: CreatorKind; label: string; icon: typeof Bot; desc: string }> = [
  { id: "agent", label: "Agent", icon: Bot, desc: "生成可保存的 Agent 配置" },
  { id: "skill", label: "Skill", icon: Wrench, desc: "生成 Skill 草案或工具代码" },
  { id: "mcp", label: "MCP", icon: Boxes, desc: "生成 MCP 连接配置" },
];

export default function CreatorPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">加载创建中心...</div>}>
      <CreatorContent />
    </Suspense>
  );
}

function CreatorContent() {
  const params = useSearchParams();
  const initialType = (params.get("type") as CreatorKind | null) ?? "agent";
  const [kind, setKind] = useState<CreatorKind>(KINDS.some((item) => item.id === initialType) ? initialType : "agent");
  const [goal, setGoal] = useState("");
  const [draftText, setDraftText] = useState("");
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const [error, setError] = useState("");

  const active = useMemo(() => KINDS.find((item) => item.id === kind) ?? KINDS[0], [kind]);

  const generate = async () => {
    if (!goal.trim()) return;
    setBusy(true);
    setError("");
    setSavedMessage("");
    try {
      const result = await draftCreator(kind, goal);
      setSummary(result.summary);
      setDraftText(JSON.stringify(result.draft, null, 2));
    } catch (event) {
      setError(event instanceof Error ? event.message : String(event));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const draft = JSON.parse(draftText) as Record<string, unknown>;
      const result = await saveCreator(kind, draft);
      setSavedMessage(result.message);
    } catch (event) {
      setError(event instanceof Error ? event.message : String(event));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Creator"
        title="AI 创建中心"
        description="描述你想添加的 Agent、Skill 或 MCP，系统会生成可编辑 JSON 草案；确认后才会写入正式配置。"
      />

      <main className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <section className="space-y-4">
          <div className="grid gap-2">
            {KINDS.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => {
                    setKind(item.id);
                    setDraftText("");
                    setSummary("");
                    setSavedMessage("");
                    setError("");
                  }}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border bg-white p-4 text-left shadow-sm transition hover:border-slate-300",
                    kind === item.id ? "border-sky-300 ring-2 ring-sky-100" : "border-slate-200",
                  )}
                >
                  <Icon size={18} className="mt-0.5 text-sky-700" />
                  <span>
                    <span className="block text-sm font-semibold text-slate-950">{item.label}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">{item.desc}</span>
                  </span>
                </button>
              );
            })}
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles size={15} className="text-sky-700" />
                需求描述
              </CardTitle>
            </CardHeader>
            <CardContent>
              <textarea
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                placeholder={`描述你想创建的 ${active.label}，包括用途、输入输出、是否需要外部服务。`}
                className="min-h-48 w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100"
              />
              <button
                type="button"
                disabled={busy || !goal.trim()}
                onClick={() => void generate()}
                className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {busy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                生成草案
              </button>
            </CardContent>
          </Card>
        </section>

        <Card className="min-w-0">
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <div>
              <CardTitle>草案预览</CardTitle>
              <p className="mt-1 text-xs text-slate-500">{summary || "生成后可在这里编辑 JSON 草案。"}</p>
            </div>
            <button
              type="button"
              disabled={busy || !draftText.trim()}
              onClick={() => void save()}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs font-semibold text-sky-700 hover:bg-sky-100 disabled:opacity-50"
            >
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              确认保存
            </button>
          </CardHeader>
          <CardContent>
            <textarea
              value={draftText}
              onChange={(event) => setDraftText(event.target.value)}
              spellCheck={false}
              className="min-h-[560px] w-full resize-none rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 font-mono text-xs leading-5 text-slate-100 outline-none focus:border-sky-400"
              placeholder="{ }"
            />
            {savedMessage ? (
              <p className="mt-3 flex items-center gap-2 rounded-lg bg-sky-50 px-3 py-2 text-xs text-sky-700">
                <CheckCircle size={14} />
                {savedMessage}
              </p>
            ) : null}
            {error ? <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p> : null}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
