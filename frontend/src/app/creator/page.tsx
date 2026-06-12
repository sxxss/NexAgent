"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle,
  Database,
  FileText,
  Gauge,
  Link,
  Loader2,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  Wrench,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  chatCreator,
  saveCreator,
  type CreatorChatMessage,
  type CreatorKind,
  type CreatorQuality,
  type CreatorResourcePlan,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ChatMessage = CreatorChatMessage & { id: string };

const KINDS: Array<{ id: CreatorKind; label: string; icon: typeof Bot; desc: string }> = [
  { id: "agent", label: "Agent", icon: Bot, desc: "生成可直接运行的 Agent 配置" },
  { id: "skill", label: "Skill", icon: Wrench, desc: "生成可安装到 Skills 的能力包" },
];

const STARTERS: Record<CreatorKind, string[]> = {
  agent: ["帮我做一个客服质检 Agent", "创建一个论文精读 Agent", "做一个财务报表分析 Agent"],
  skill: ["做一个周报生成 Skill", "创建一个合同审阅 Skill", "做一个竞品分析 Skill"],
};

function newId() {
  return Math.random().toString(36).slice(2);
}

function initialKindFromQuery(value: string | null): CreatorKind {
  return value === "skill" ? "skill" : "agent";
}

function seedMessage(kind: CreatorKind): ChatMessage {
  return {
    id: newId(),
    role: "assistant",
    content: kind === "agent"
      ? "说说这个 Agent 要负责什么、输出什么、有哪些边界。"
      : "说说这个 Skill 的触发场景、处理流程和期望输出。",
  };
}

export default function CreatorPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">加载创建中心...</div>}>
      <CreatorContent />
    </Suspense>
  );
}

function CreatorContent() {
  const params = useSearchParams();
  const [kind, setKind] = useState<CreatorKind>(() => initialKindFromQuery(params.get("type")));
  const [threadId, setThreadId] = useState<string | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>(() => [seedMessage(initialKindFromQuery(params.get("type")))]);
  const [input, setInput] = useState("");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [quality, setQuality] = useState<CreatorQuality | null>(null);
  const [resourcePlan, setResourcePlan] = useState<CreatorResourcePlan | null>(null);
  const [summary, setSummary] = useState("");
  const [readyToSave, setReadyToSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const [error, setError] = useState("");

  const active = useMemo(() => KINDS.find((item) => item.id === kind) ?? KINDS[0], [kind]);
  const Icon = active.icon;
  const saveBlocked = quality?.status === "blocked";

  const reset = (nextKind = kind) => {
    setKind(nextKind);
    setThreadId(undefined);
    setMessages([seedMessage(nextKind)]);
    setInput("");
    setDraft(null);
    setQuality(null);
    setResourcePlan(null);
    setSummary("");
    setReadyToSave(false);
    setSavedMessage("");
    setError("");
  };

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || busy) return;
    const userMessage: ChatMessage = { id: newId(), role: "user", content };
    const history = [...messages, userMessage];
    setMessages(history);
    setInput("");
    setBusy(true);
    setSavedMessage("");
    setError("");
    try {
      const result = await chatCreator({
        kind,
        message: content,
        thread_id: threadId,
        messages: messages.map(({ role, content }) => ({ role, content })),
        draft: draft ?? undefined,
      });
      setThreadId(result.thread_id);
      setDraft(result.draft);
      setQuality(result.quality);
      setResourcePlan(result.resource_plan);
      setSummary(result.summary);
      setReadyToSave(result.ready_to_save);
      setMessages([
        ...history,
        { id: newId(), role: "assistant", content: result.message },
      ]);
    } catch (event) {
      const message = event instanceof Error ? event.message : String(event);
      setError(message);
      setMessages([...history, { id: newId(), role: "assistant", content: `创建失败：${message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft || saving || saveBlocked) return;
    setSaving(true);
    setError("");
    setSavedMessage("");
    try {
      const result = await saveCreator(kind, draft);
      setSavedMessage(result.message);
      setReadyToSave(false);
    } catch (event) {
      setError(event instanceof Error ? event.message : String(event));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Creator"
        title="AI 创建中心"
        description="通过对话生成 Agent 或 Skill，确认当前草案后保存到 NexAgent。"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => reset()}>
              <RotateCcw size={14} />
              重新开始
            </Button>
            <Button size="sm" disabled={!draft || saving || saveBlocked} onClick={() => void save()} className="whitespace-nowrap">
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              保存 {active.label}
            </Button>
          </>
        }
      />

      <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(320px,42vh)] gap-5 overflow-hidden px-4 pb-5 md:px-6 xl:grid-cols-[minmax(0,1fr)_420px] xl:grid-rows-none">
        <section className="flex min-h-0 flex-col gap-4 overflow-hidden">
          <div className="grid shrink-0 gap-2 sm:grid-cols-2">
            {KINDS.map((item) => {
              const ItemIcon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => reset(item.id)}
                  className={cn(
                    "flex min-h-20 items-start gap-3 rounded-xl border bg-white px-4 py-3 text-left shadow-sm transition",
                    "hover:border-indigo-200 hover:bg-indigo-50/30",
                    kind === item.id ? "border-indigo-300 ring-2 ring-indigo-100" : "border-slate-200",
                  )}
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
                    <ItemIcon size={16} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-slate-950">{item.label}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">{item.desc}</span>
                  </span>
                </button>
              );
            })}
          </div>

          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardHeader className="shrink-0 border-b border-slate-100">
              <CardTitle className="flex items-center gap-2">
                <Icon size={16} className="text-indigo-600" />
                {active.label} 对话创建
              </CardTitle>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 [scrollbar-gutter:stable]">
                <div className="mx-auto flex max-w-3xl flex-col gap-3">
                  {messages.map((message) => (
                    <CreatorBubble key={message.id} message={message} />
                  ))}
                  {busy ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500">
                      <Loader2 size={15} className="animate-spin text-indigo-600" />
                      正在整理草案...
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="shrink-0 border-t border-slate-100 bg-white/70 px-4 py-3">
                {!draft ? (
                  <div className="mb-3 flex flex-wrap gap-2">
                    {STARTERS[kind].map((starter) => (
                      <button
                        key={starter}
                        type="button"
                        disabled={busy}
                        onClick={() => void send(starter)}
                        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
                      >
                        <Sparkles size={12} />
                        {starter}
                      </button>
                    ))}
                  </div>
                ) : null}
                <div className="flex items-end gap-2">
                  <textarea
                    value={input}
                    disabled={busy}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void send();
                      }
                    }}
                    rows={2}
                    placeholder={`继续描述 ${active.label} 的职责、流程或输出...`}
                    className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 disabled:opacity-60"
                  />
                  <Button disabled={busy || !input.trim()} onClick={() => void send()} className="h-11">
                    {busy ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
                    发送
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <DraftPanel
          kind={kind}
          draft={draft}
          quality={quality}
          resourcePlan={resourcePlan}
          summary={summary}
          readyToSave={readyToSave}
          savedMessage={savedMessage}
          error={error}
          saving={saving}
          onSave={() => void save()}
        />
      </main>
    </div>
  );
}

function CreatorBubble({ message }: { message: ChatMessage }) {
  const user = message.role === "user";
  return (
    <div className={cn("flex", user ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[min(86%,760px)] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2.5 text-sm leading-7 shadow-sm",
          user
            ? "rounded-br-md bg-indigo-600 text-white"
            : "rounded-tl-md border border-slate-200 bg-white text-slate-800",
        )}
      >
        {message.content}
      </div>
    </div>
  );
}

function DraftPanel({
  kind,
  draft,
  quality,
  resourcePlan,
  summary,
  readyToSave,
  savedMessage,
  error,
  saving,
  onSave,
}: {
  kind: CreatorKind;
  draft: Record<string, unknown> | null;
  quality: CreatorQuality | null;
  resourcePlan: CreatorResourcePlan | null;
  summary: string;
  readyToSave: boolean;
  savedMessage: string;
  error: string;
  saving: boolean;
  onSave: () => void;
}) {
  const blocked = quality?.status === "blocked";
  return (
    <Card className="flex min-h-0 max-h-full flex-col overflow-hidden">
      <CardHeader className="shrink-0 border-b border-slate-100">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>成品预览</CardTitle>
            <p className="mt-1 text-xs leading-5 text-slate-500">{summary || "对话后会生成当前可保存版本。"}</p>
          </div>
          <Button size="sm" disabled={!draft || saving || blocked} onClick={onSave} className="min-w-16 shrink-0 whitespace-nowrap">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden p-0">
        <div className="min-h-0 flex-1 overflow-y-auto p-4 [scrollbar-gutter:stable]">
          {!draft ? (
            <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/60 text-center">
              <Sparkles size={22} className="text-indigo-500" />
              <p className="mt-3 text-sm font-semibold text-slate-700">等待生成草案</p>
            </div>
          ) : kind === "agent" ? (
            <AgentDraft draft={draft} quality={quality} resourcePlan={resourcePlan} />
          ) : (
            <SkillDraft draft={draft} quality={quality} resourcePlan={resourcePlan} />
          )}

          {readyToSave && draft ? <StatusNote tone="success" text="当前草案已具备保存条件。" /> : null}
          {savedMessage ? (
            <p className="mt-3 flex items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700">
              <CheckCircle size={14} />
              {savedMessage}
            </p>
          ) : null}
          {error ? <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function AgentDraft({
  draft,
  quality,
  resourcePlan,
}: {
  draft: Record<string, unknown>;
  quality: CreatorQuality | null;
  resourcePlan: CreatorResourcePlan | null;
}) {
  return (
    <div className="min-h-0 space-y-4">
      <QualityPanel quality={quality} />
      <PreviewGrid
        rows={[
          ["名称", valueText(draft.name)],
          ["职责", valueText(draft.description)],
          ["类型", valueText(draft.base_type)],
          ["推理", valueText(draft.reasoning_mode)],
          ["子 Agent", draft.allow_subagents ? "开启" : "关闭"],
        ]}
      />
      <ResourcePlanPanel plan={resourcePlan} fallbackFields={["tools", "kb_ids", "skill_ids", "mcp_ids"]} draft={draft} />
      <PreviewBlock title="系统提示词" content={valueText(draft.system_prompt)} />
    </div>
  );
}

function SkillDraft({
  draft,
  quality,
  resourcePlan,
}: {
  draft: Record<string, unknown>;
  quality: CreatorQuality | null;
  resourcePlan: CreatorResourcePlan | null;
}) {
  return (
    <div className="min-h-0 space-y-4">
      <QualityPanel quality={quality} />
      <PreviewGrid
        rows={[
          ["ID", valueText(draft.id)],
          ["名称", valueText(draft.name)],
          ["说明", valueText(draft.description)],
          ["版本", valueText(draft.version)],
          ["标签", Array.isArray(draft.tags) ? draft.tags.join(", ") || "无" : "无"],
        ]}
      />
      <ResourcePlanPanel
        plan={resourcePlan}
        fallbackFields={["required_tools", "required_mcp_ids", "skill_dependencies"]}
        draft={draft}
      />
      <PreviewBlock title="SKILL.md 内容" content={valueText(draft.content)} />
    </div>
  );
}

function QualityPanel({ quality }: { quality: CreatorQuality | null }) {
  if (!quality) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white px-3 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <Gauge size={15} className="text-slate-400" />
          保存检查
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">生成草案后显示检查结果。</p>
      </section>
    );
  }
  const tone = quality.status === "ready" ? "success" : quality.status === "blocked" ? "danger" : "warning";
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Gauge size={15} className={tone === "success" ? "text-emerald-600" : tone === "danger" ? "text-rose-600" : "text-amber-600"} />
            保存检查
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{quality.recommendation}</p>
        </div>
        <div className={cn(
          "flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border text-sm font-bold",
          tone === "success" && "border-emerald-100 bg-emerald-50 text-emerald-700",
          tone === "warning" && "border-amber-100 bg-amber-50 text-amber-700",
          tone === "danger" && "border-rose-100 bg-rose-50 text-rose-700",
        )}>
          {quality.score}
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {quality.checks.map((check) => (
          <div key={check.id} className="flex gap-2 rounded-md border border-slate-100 bg-slate-50 px-2.5 py-2">
            <CheckIcon status={check.status} />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-slate-800">{check.label}</p>
              <p className="mt-0.5 text-xs leading-5 text-slate-500">{check.message}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ResourcePlanPanel({
  plan,
  fallbackFields,
  draft,
}: {
  plan: CreatorResourcePlan | null;
  fallbackFields: string[];
  draft: Record<string, unknown>;
}) {
  const fallbackItems = fallbackFields.flatMap((field) =>
    asStringList(draft[field]).map((item) => ({
      kind: field,
      id: item,
      label: item,
      purpose: field,
    })),
  );
  const items = plan?.items?.length ? plan.items : fallbackItems;
  return (
    <section className="rounded-lg border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Link size={15} className="text-indigo-600" />
          资源计划
        </div>
        <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-500">
          {items.length} 项
        </span>
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-500">
        {plan?.summary || "当前草稿没有声明外部资源。"}
      </p>
      {items.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {items.map((item) => (
            <span
              key={`${item.kind}:${item.id}`}
              title={item.purpose}
              className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700"
            >
              <ResourceIcon kind={item.kind} />
              <span className="truncate">{item.label || item.id}</span>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function PreviewGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
          <p className="text-[11px] font-semibold text-slate-400">{label}</p>
          <p className="mt-1 break-words text-sm font-medium text-slate-800">{value || "未设置"}</p>
        </div>
      ))}
    </div>
  );
}

function PreviewBlock({ title, content }: { title: string; content: string }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 text-xs font-semibold text-slate-600">
        <FileText size={14} className="text-slate-400" />
        {title}
      </div>
      <pre className="max-h-80 min-h-[4.5rem] overflow-y-auto overflow-x-auto whitespace-pre-wrap break-words px-3 py-2 text-xs leading-5 text-slate-700 [scrollbar-gutter:stable]">
        {content || "未设置"}
      </pre>
    </section>
  );
}

function CheckIcon({ status }: { status: string }) {
  if (status === "pass") {
    return (
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
        <Check size={12} />
      </span>
    );
  }
  if (status === "fail") {
    return (
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-700">
        <AlertTriangle size={12} />
      </span>
    );
  }
  return (
    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700">
      <AlertTriangle size={12} />
    </span>
  );
}

function ResourceIcon({ kind }: { kind: string }) {
  const className = "h-3.5 w-3.5 shrink-0 text-slate-400";
  if (kind === "knowledge") return <Database className={className} />;
  if (kind === "skill" || kind === "dependency") return <Wrench className={className} />;
  if (kind === "mcp") return <Link className={className} />;
  return <Sparkles className={className} />;
}

function StatusNote({ tone, text }: { tone: "success" | "warning" | "danger"; text: string }) {
  return (
    <p className={cn(
      "mt-3 rounded-lg border px-3 py-2 text-xs font-medium",
      tone === "success" && "border-emerald-100 bg-emerald-50 text-emerald-700",
      tone === "warning" && "border-amber-100 bg-amber-50 text-amber-700",
      tone === "danger" && "border-rose-100 bg-rose-50 text-rose-700",
    )}>
      {text}
    </p>
  );
}

function asStringList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function valueText(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value) ?? "";
}
