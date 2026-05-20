"use client";

import { Bot, CheckCircle, ChevronDown, ChevronRight, Clock3, Database, FileText, Loader2, User, Wrench, XCircle } from "lucide-react";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingBubble } from "@/components/chat/ThinkingBubble";
import { artifactDownloadUrl, fetchArtifactPreview } from "@/lib/api";
import type { EvidenceRef, SubAgentRuntimeItem } from "@/lib/api";
import { cn } from "@/lib/utils";

export type MessageRole = "user" | "assistant" | "tool";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  toolName?: string;
  isStreaming?: boolean;
  thinkingContent?: string;
  events?: RuntimeEvent[];
  artifacts?: string[];
  artifactThreadId?: string;
  subagents?: SubAgentRuntimeItem[];
  runtime?: RuntimeResourceSnapshot;
  toolCalls?: ToolCallRuntime[];
  processBlocks?: ProcessBlock[];
  pendingProcessContent?: string;
  runStartedAt?: number;
  runFinishedAt?: number;
}

export interface RuntimeEvent {
  id: string;
  label: string;
  phase?: string;
  elapsedMs?: number;
}

export interface RuntimeResourceSnapshot {
  agent?: string;
  model?: string;
  tools?: string[];
  kbIds?: string[];
  mcpIds?: string[];
  skillIds?: string[];
  reasoningMode?: string;
}

export interface ToolCallRuntime {
  id: string;
  name: string;
  input?: unknown;
  output?: unknown;
  status: "started" | "completed" | "failed" | string;
  success?: boolean;
  elapsedMs?: number;
  startedAt?: number;
}

export type ProcessBlock =
  | {
      id: string;
      type: "text";
      body: string;
      elapsedMs?: number;
    }
  | {
      id: string;
      type: "event";
      title: string;
      elapsedMs?: number;
      phase?: string;
    }
  | {
      id: string;
      type: "tool";
      toolCall: ToolCallRuntime;
    };

export function MessageBubble({ message }: { message: Message }) {
  if (message.role === "tool") return <ToolBubble message={message} />;
  if (message.role === "user") return <UserBubble message={message} />;
  return <AssistantBubble message={message} />;
}

function UserBubble({ message }: { message: Message }) {
  return (
    <div className="flex justify-end py-2 animate-fade-up">
      <div className="flex max-w-[78%] min-w-0 items-end gap-2.5">
        <div className="min-w-0 rounded-2xl rounded-br-md bg-[#6d5cf0] px-4 py-3 text-sm leading-[1.75] text-white shadow-[0_10px_22px_rgba(109,92,240,0.22)]">
          <p className="whitespace-pre-wrap break-words">{cleanDisplayText(message.content)}</p>
        </div>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#efeafe] text-[#6d5cf0] shadow-sm">
          <User size={13} />
        </div>
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: Message }) {
  const evidence = extractEvidenceBlock(message.content);
  const displayContent = cleanDisplayText(stripInternalBlocks(stripEvidenceBlocks(message.content)));
  const citations = extractCitationIds(displayContent);
  const hasProcess = Boolean(
    message.thinkingContent ||
      message.pendingProcessContent ||
      message.events?.length ||
      message.toolCalls?.length ||
      message.processBlocks?.length ||
      message.subagents?.length,
  );
  const showFinalCard = Boolean(displayContent || !message.isStreaming || !hasProcess);

  return (
    <div className="flex items-start gap-3 py-2 animate-fade-up">
      <div className="relative mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#6d5cf0] text-white shadow-[0_10px_22px_rgba(109,92,240,0.22)]">
        <Bot size={14} />
        {message.isStreaming ? (
          <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#6d5cf0]" />
        ) : null}
      </div>

      <div className="min-w-0 max-w-[86%] flex-1 overflow-hidden">
        {hasProcess ? (
          <ThinkingBubble
            content={message.thinkingContent}
            events={message.events}
            toolCalls={message.toolCalls}
            blocks={message.processBlocks}
            subagents={message.subagents}
            streaming={message.isStreaming}
            startedAt={message.runStartedAt}
            finishedAt={message.runFinishedAt}
          />
        ) : null}

        {message.runtime ? <RuntimeResources runtime={message.runtime} /> : null}

        {showFinalCard ? (
        <div className="min-w-0 overflow-hidden rounded-2xl rounded-tl-md border border-white/80 bg-white/88 px-4 py-3.5 text-sm leading-[1.75] text-slate-800 shadow-[0_12px_28px_rgba(83,101,132,0.09)]">
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent || (message.isStreaming ? "" : "")}</ReactMarkdown>
          </div>
          {message.isStreaming && !displayContent ? (
            <div className="flex items-center gap-1 py-1">
              <span className="h-1.5 w-1.5 rounded-full bg-[#6d5cf0]" />
              <span className="h-1.5 w-1.5 rounded-full bg-[#6d5cf0]" />
              <span className="h-1.5 w-1.5 rounded-full bg-[#6d5cf0]" />
            </div>
          ) : null}
          {message.isStreaming && displayContent ? (
            <span className="ml-0.5 inline-block h-3.5 w-0.5 rounded-full bg-[#6d5cf0] animate-cursor-blink" />
          ) : null}
          {message.artifacts?.length ? (
            <ArtifactList artifacts={message.artifacts} threadId={message.artifactThreadId} />
          ) : null}
          {citations.length ? <CitationChips citations={citations} evidence={evidence} /> : null}
        </div>
        ) : null}
      </div>
    </div>
  );
}

// Kept for a short rollback window; the active tool detail UI now lives inside ThinkingBubble.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ToolCallPanel({ toolCalls, streaming }: { toolCalls: ToolCallRuntime[]; streaming?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const latest = toolCalls[toolCalls.length - 1];
  const completed = toolCalls.filter((item) => item.status === "completed").length;
  const running = toolCalls.filter((item) => item.status === "started").length;

  return (
    <div className="mb-2 overflow-hidden rounded-xl border border-amber-200/80 bg-amber-50/60 shadow-sm animate-fade-up">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs transition hover:bg-white/55"
      >
        <span className="inline-flex min-w-0 items-center gap-2 font-semibold text-amber-900">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {streaming && running ? <Loader2 size={12} className="animate-spin text-amber-600" /> : <Wrench size={12} className="text-amber-600" />}
          <span>工具调用</span>
          {latest?.name ? <span className="truncate font-mono text-[10px] text-amber-700">{latest.name}</span> : null}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-amber-700">
          {completed}/{toolCalls.length}
          {running ? " running" : ""}
        </span>
      </button>
      {expanded ? (
        <div className="space-y-2 border-t border-amber-200/70 px-3 py-2.5 animate-slide-down">
          {toolCalls.map((call) => (
            <ToolCallRow key={call.id} call={call} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ToolCallRow({ call }: { call: ToolCallRuntime }) {
  const [expanded, setExpanded] = useState(false);
  const done = call.status === "completed";
  const failed = call.status === "failed" || call.success === false;
  const inputText = formatToolPayload(call.input);
  const outputText = formatToolPayload(call.output);

  return (
    <div className="rounded-lg border border-white/80 bg-white px-2.5 py-2 text-[11px] text-slate-700 shadow-sm">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          {failed ? (
            <XCircle size={12} className="shrink-0 text-rose-600" />
          ) : done ? (
            <CheckCircle size={12} className="shrink-0 text-fuchsia-600" />
          ) : (
            <Loader2 size={12} className="shrink-0 animate-spin text-amber-600" />
          )}
          <span className="truncate font-mono font-semibold text-slate-800">{call.name || "unknown_tool"}</span>
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-400">
          {typeof call.elapsedMs === "number" ? `${call.elapsedMs}ms` : call.status}
        </span>
      </button>
      {expanded ? (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <ToolPayload title="输入" value={inputText} />
          <ToolPayload title={failed ? "错误" : "结果"} value={outputText || (done ? "(empty)" : "等待工具返回...")} />
        </div>
      ) : null}
    </div>
  );
}

function ToolPayload({ title, value }: { title: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[10px] font-semibold text-slate-400">{title}</div>
      <pre className="max-h-44 overflow-auto rounded-md bg-slate-950 px-2.5 py-2 font-mono text-[10px] leading-4 text-slate-100">
        {value || "{}"}
      </pre>
    </div>
  );
}

function formatToolPayload(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return "";
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      return trimmed;
    }
  }
  return JSON.stringify(value, null, 2);
}

function RuntimeResources({ runtime }: { runtime: RuntimeResourceSnapshot }) {
  const [expanded, setExpanded] = useState(false);
  const skills = runtime.skillIds ?? [];
  const mcps = runtime.mcpIds ?? [];
  const knowledge = runtime.kbIds ?? [];
  const rawTools = runtime.tools ?? [];
  const tools = rawTools.filter((tool) => tool !== "delegate_subagents");
  const subagentsEnabled = rawTools.includes("delegate_subagents");
  const chips = [
    runtime.model ? `模型：${runtime.model}` : "",
    tools.length ? `可用工具：${tools.length} 个` : "",
    subagentsEnabled ? "可调用 Agent：已启用" : "",
    skills.length ? `技能：${skills.join(", ")}` : "",
    mcps.length ? `外部服务：${mcps.join(", ")}` : "",
    knowledge.length ? `知识库：${knowledge.length} 个` : "",
  ].filter(Boolean);

  if (!chips.length && !runtime.agent) return null;

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="mb-2 flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/72 px-3 py-2 text-left text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-white animate-fade-up"
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          <ChevronRight size={12} />
          <Database size={12} className="text-slate-400" />
          <span>本次启用能力</span>
          {runtime.agent ? <span className="truncate font-mono text-[10px] text-slate-400">{runtime.agent}</span> : null}
        </span>
        <span className="shrink-0 text-[10px] text-slate-400">{chips.length} 项</span>
      </button>
    );
  }

  return (
    <div
      className="mb-2 cursor-pointer rounded-xl border border-slate-200 bg-white/72 px-3 py-2 text-xs text-slate-600 shadow-sm transition animate-slide-down"
      onClick={() => setExpanded(false)}
    >
      <div className="flex items-center gap-2 font-semibold text-slate-700">
        <Database size={12} className="text-slate-400" />
        <span>本次启用能力</span>
        {runtime.agent ? <span className="font-mono text-[10px] text-slate-400">{runtime.agent}</span> : null}
      </div>
      <p className="mt-1 text-[11px] leading-4 text-slate-400">
        这些是本次回答可使用的模型、工具、技能、知识库和外部服务。
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <span key={chip} className="inline-flex max-w-full items-center rounded-lg bg-slate-100 px-2 py-1">
            <span className="truncate">{chip}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// Kept for quick rollback while the new process panel settles.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function RuntimeTimeline({ events, streaming }: { events: RuntimeEvent[]; streaming?: boolean }) {
  const visible = events.slice(-6);
  return (
    <div className="mb-2 rounded-xl border border-slate-200 bg-white/70 px-3 py-2 text-xs text-slate-600 shadow-sm">
      <div className="flex items-center gap-2 font-semibold text-slate-700">
        <Clock3 size={12} className={streaming ? "text-[#6d5cf0]" : "text-slate-400"} />
        运行状态
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {visible.map((event) => (
          <span
            key={event.id}
            className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-lg bg-slate-100 px-2 py-1"
            title={event.phase}
          >
            <span className="truncate">{event.label}</span>
            {typeof event.elapsedMs === "number" ? (
              <span className="shrink-0 font-mono text-[10px] text-slate-400">{event.elapsedMs}ms</span>
            ) : null}
          </span>
        ))}
      </div>
    </div>
  );
}

// Kept for a short rollback window; Sub-Agent progress now renders inside ThinkingBubble.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function SubAgentPanel({ items }: { items: SubAgentRuntimeItem[] }) {
  const [expanded, setExpanded] = useState(true);
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.length - completed;

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 text-left text-xs font-semibold text-slate-700"
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <Bot size={12} className="text-[#6d5cf0]" />
          <span>Sub-Agent 进度</span>
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-400">
          {completed}/{items.length}
          {failed ? ` · ${failed} failed` : ""}
        </span>
      </button>
      {expanded ? (
        <div className="mt-2 space-y-1.5">
          {items.map((item) => (
            <div key={`${item.run_id ?? "run"}:${item.index}:${item.agent}:${item.task ?? ""}`} className="rounded-lg border border-white bg-white px-2.5 py-2 text-[11px] text-slate-600 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold text-slate-800">
                  <SubAgentStatusIcon status={item.status} />
                  <span className="truncate">{item.agent}</span>
                </span>
                {typeof item.latency_ms === "number" ? (
                  <span className="shrink-0 font-mono text-[10px] text-slate-400">{item.latency_ms}ms</span>
                ) : null}
              </div>
              {item.run_id ? (
                <p className="mt-1 font-mono text-[10px] text-slate-400">run {item.run_id.slice(0, 8)}</p>
              ) : null}
              {item.task ? <p className="mt-1 line-clamp-2 text-slate-500">{item.task}</p> : null}
              {item.summary ? <p className="mt-1 line-clamp-3 text-slate-700">{item.summary}</p> : null}
              {item.error ? <p className="mt-1 rounded-md bg-rose-50 px-2 py-1 text-rose-700">{item.error}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SubAgentStatusIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle size={12} className="shrink-0 text-fuchsia-600" />;
  if (status === "queued" || status === "running") return <Loader2 size={12} className="shrink-0 animate-spin text-[#6d5cf0]" />;
  return <XCircle size={12} className="shrink-0 text-rose-600" />;
}

function ArtifactList({ artifacts, threadId }: { artifacts: string[]; threadId?: string }) {
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [loading, setLoading] = useState(false);

  const openPreview = async (artifact: string) => {
    if (!threadId) return;
    setPreviewPath(artifact);
    setPreviewError("");
    setPreviewContent("");
    setLoading(true);
    try {
      const preview = await fetchArtifactPreview(threadId, artifact);
      if (!preview.previewable) {
        setPreviewError("此文件类型不支持文本预览，请下载查看。");
      } else {
        setPreviewContent(preview.content || "(empty)");
      }
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "预览失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
        <FileText size={12} />
        产物
      </div>
      <div className="mt-1.5 space-y-1">
        {artifacts.map((artifact) => (
          <div key={artifact} className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => openPreview(artifact)}
              disabled={!threadId}
              className="min-w-0 flex-1 truncate text-left font-mono text-[11px] text-slate-600 hover:text-[#6d5cf0] disabled:hover:text-slate-600"
              title={artifact}
            >
              {artifact}
            </button>
            {threadId ? (
              <a
                href={artifactDownloadUrl(threadId, artifact)}
                className="shrink-0 rounded-md bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600 hover:text-[#6d5cf0]"
              >
                下载
              </a>
            ) : null}
          </div>
        ))}
      </div>
      {previewPath ? (
        <div className="mt-2 rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-2.5 py-1.5">
            <span className="min-w-0 truncate font-mono text-[11px] font-semibold text-slate-600">{previewPath}</span>
            <button
              type="button"
              onClick={() => setPreviewPath(null)}
              className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
            >
              关闭
            </button>
          </div>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap px-3 py-2 font-mono text-[11px] leading-5 text-slate-700">
            {loading ? "加载中..." : previewError || previewContent}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function ToolBubble({ message }: { message: Message }) {
  const [expanded, setExpanded] = useState(false);
  const evidence = extractEvidenceBlock(message.content);
  const displayContent = stripInternalBlocks(stripEvidenceBlocks(message.content));
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(displayContent);
  } catch {
    parsed = null;
  }

  return (
    <div className="flex items-start gap-3 py-1 pl-11 animate-fade-up">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className={cn("min-w-0 rounded-xl border px-3.5 py-2.5 text-left text-xs transition hover:bg-white")}
        style={{
          background: "rgba(255, 255, 255, 0.82)",
          borderColor: "rgba(216, 145, 24, 0.28)",
          boxShadow: "var(--shadow-xs)",
        }}
      >
        <span className="flex items-center gap-2 font-semibold text-amber-800">
          {expanded ? <ChevronDown size={12} className="text-amber-500" /> : <ChevronRight size={12} className="text-amber-500" />}
          <Wrench size={12} className="text-amber-600" />
          <span>工具调用</span>
          <span className="rounded-md bg-amber-100 px-1.5 py-0.5 font-mono text-[10px] text-amber-800">
            {message.toolName}
          </span>
        </span>
        {evidence.length ? <EvidencePanel evidence={evidence} /> : null}
        {expanded ? (
          <pre className="mt-2.5 max-h-52 overflow-auto rounded-lg bg-slate-950 px-3.5 py-2.5 font-mono text-[11px] leading-5 text-slate-100 animate-fade-up">
            {parsed ? JSON.stringify(parsed, null, 2) : displayContent}
          </pre>
        ) : null}
      </button>
    </div>
  );
}

function CitationChips({ citations, evidence }: { citations: string[]; evidence: EvidenceRef[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const evidenceById = new Map(evidence.map((item) => [item.id.toUpperCase(), item]));
  const selectedEvidence = selected ? evidenceById.get(selected) : null;

  return (
    <div className="mt-3 border-t border-slate-100 pt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold text-slate-500">引用</span>
        {citations.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setSelected((value) => (value === id ? null : id))}
            className={cn(
              "rounded-md px-1.5 py-0.5 font-mono text-[11px] font-semibold",
              selected === id ? "bg-violet-600 text-white" : "bg-violet-50 text-violet-700 hover:bg-violet-100",
            )}
            title={evidenceById.has(id) ? "查看引用来源" : "当前回答没有附带该引用的结构化详情"}
          >
            {id}
          </button>
        ))}
      </div>
      {selected ? (
        selectedEvidence ? (
          <div className="mt-2 rounded-lg border border-violet-100 bg-violet-50/70 px-2.5 py-2 text-[11px] text-violet-950">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono font-semibold">{selectedEvidence.id}</span>
              <span className="font-mono text-[10px] text-violet-700">
                {Math.round((selectedEvidence.score || 0) * 100)}%
              </span>
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] text-violet-700">{selectedEvidence.source || "unknown"}</div>
            {selectedEvidence.preview ? <p className="mt-1 line-clamp-3 leading-4">{selectedEvidence.preview}</p> : null}
          </div>
        ) : (
          <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-500">
            该引用没有随回答返回结构化详情，可展开上方知识库工具调用查看来源。
          </div>
        )
      ) : null}
    </div>
  );
}

function EvidencePanel({ evidence }: { evidence: EvidenceRef[] }) {
  return (
    <div className="mt-2.5 space-y-1.5">
      {evidence.slice(0, 5).map((item) => (
        <div key={item.id} className="rounded-lg border border-amber-100 bg-amber-50/70 px-2.5 py-2 text-[11px] text-amber-950">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono font-semibold text-amber-800">{item.id}</span>
            <span className="font-mono text-[10px] text-amber-700">{Math.round((item.score || 0) * 100)}%</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-amber-700">{item.source || "unknown"}</div>
          {item.preview ? <p className="mt-1 line-clamp-2 leading-4 text-amber-900">{item.preview}</p> : null}
        </div>
      ))}
    </div>
  );
}

function cleanDisplayText(value: string) {
  return value
    .replace(/\u0000/g, "")
    .replace(/\uFEFF/g, "")
    .replace(/\uFFFD/g, "")
    .replace(/锟斤拷/g, "")
    .replace(/锟/g, "")
    .replace(/(?:["""]\s*){12,}/g, " ")
    .replace(/[ \t]{2,}/g, " ")
    .trimStart();
}

function stripEvidenceBlocks(value: string) {
  return value.replace(/```nexagent-evidence\s*[\s\S]*?```/g, "").trimEnd();
}

function stripInternalBlocks(value: string) {
  return value.replace(/```nexagent-subagents\s*[\s\S]*?```/g, "").trimEnd();
}

function extractEvidenceBlock(value: string): EvidenceRef[] {
  const refs: EvidenceRef[] = [];
  for (const match of value.matchAll(/```nexagent-evidence\s*([\s\S]*?)```/g)) {
    try {
      const parsed = JSON.parse(match[1].trim());
      if (Array.isArray(parsed)) refs.push(...parsed);
    } catch {
      // Keep the tool output readable even if an older backend produced malformed evidence.
    }
  }
  return refs;
}

function extractCitationIds(value: string) {
  const seen = new Set<string>();
  for (const match of value.matchAll(/\[(E\d+)\]/gi)) {
    seen.add(match[1].toUpperCase());
  }
  return Array.from(seen);
}
