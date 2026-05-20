"use client";

import {
  BookOpenText,
  Bot,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock3,
  FilePenLine,
  FolderOpen,
  Globe,
  Loader2,
  Search,
  SquareTerminal,
  Wrench,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SubAgentRuntimeItem } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ProcessEvent {
  id: string;
  label: string;
  phase?: string;
  elapsedMs?: number;
}

interface ProcessToolCall {
  id: string;
  name: string;
  input?: unknown;
  output?: unknown;
  status: string;
  success?: boolean;
  elapsedMs?: number;
  startedAt?: number;
}

type ProcessBlock =
  | { id: string; type: "text"; body: string; elapsedMs?: number }
  | { id: string; type: "event"; title: string; elapsedMs?: number; phase?: string }
  | { id: string; type: "tool"; toolCall: ProcessToolCall };

export function ThinkingBubble({
  content = "",
  events = [],
  toolCalls = [],
  blocks = [],
  subagents = [],
  streaming = false,
  startedAt,
  finishedAt,
}: {
  content?: string;
  events?: ProcessEvent[];
  toolCalls?: ProcessToolCall[];
  blocks?: ProcessBlock[];
  subagents?: SubAgentRuntimeItem[];
  streaming?: boolean;
  startedAt?: number;
  finishedAt?: number;
}) {
  const [expanded, setExpanded] = useState(streaming);
  const [now, setNow] = useState(finishedAt ?? startedAt ?? 0);

  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  const elapsedMs = useMemo(
    () => resolveElapsedMs({ events, toolCalls, startedAt, finishedAt, now }),
    [events, toolCalls, finishedAt, now, startedAt],
  );
  const processBlocks = useMemo(
    () => (blocks.length ? blocks : buildFallbackBlocks(content, events, toolCalls)),
    [blocks, content, events, toolCalls],
  );
  const runningSubagents = subagents.filter((item) => item.status === "running" || item.status === "queued").length;
  const completedTools = toolCalls.filter((tool) => tool.status === "completed").length;
  const failedTools = toolCalls.filter((tool) => tool.status === "failed" || tool.success === false).length;

  if (!content && !events.length && !toolCalls.length && !blocks.length && !subagents.length) return null;

  return (
    <div className="mb-2 overflow-hidden rounded-2xl border border-slate-200/70 bg-white/48 px-3 py-2 shadow-sm animate-fade-up">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className={cn(
          "inline-flex max-w-full items-center gap-2 rounded-full px-2 py-1 text-left text-xs transition hover:bg-slate-100/80",
          expanded && "mb-2",
        )}
      >
        {streaming ? (
          <Loader2 size={13} className="shrink-0 animate-spin text-slate-500" />
        ) : (
          <CheckCircle size={13} className="shrink-0 text-slate-400" />
        )}
        <span className="shrink-0 font-semibold text-slate-500">
          {streaming ? "处理中" : "已处理"} {formatDuration(elapsedMs)}
        </span>
        {toolCalls.length ? (
          <span className="hidden truncate text-slate-400 sm:inline">
            {completedTools}/{toolCalls.length} tools{failedTools ? ` · ${failedTools} failed` : ""}
          </span>
        ) : null}
        <span className="hidden text-slate-400 sm:inline">{expanded ? "隐藏步骤" : "显示步骤"}</span>
        {expanded ? <ChevronDown size={13} className="text-slate-400" /> : <ChevronRight size={13} className="text-slate-400" />}
      </button>

      {expanded ? (
        <div className="space-y-2 animate-slide-down">
          {streaming && runningSubagents > 0 ? <CurrentWorkHint runningSubagents={runningSubagents} /> : null}
          {processBlocks.map((block) => (
            <ProcessBlockView key={block.id} block={block} />
          ))}
          {subagents.length ? <SubAgentProcess items={subagents} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function CurrentWorkHint({ runningSubagents }: { runningSubagents: number }) {
  if (runningSubagents > 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-[#efeafe] px-2.5 py-1.5 text-xs font-semibold text-[#4733c9]">
        <Loader2 size={12} className="animate-spin" />
        <span>正在等待 {runningSubagents} 个子 Agent 返回结果</span>
      </div>
    );
  }
  return null;
}

function ProcessBlockView({ block }: { block: ProcessBlock }) {
  if (block.type === "tool") return <ToolCallBlock call={block.toolCall} />;
  if (block.type === "text") {
    return <ProcessText body={block.body} />;
  }
  return (
    <section className="flex items-center gap-2 py-0.5 text-xs font-semibold text-slate-500">
      <Clock3 size={13} />
      <span>{block.title}</span>
      {block.elapsedMs != null ? <span className="font-mono text-[11px] text-slate-400">{formatDuration(block.elapsedMs)}</span> : null}
    </section>
  );
}

function ProcessText({ body }: { body: string }) {
  return (
    <div className="process-markdown text-sm font-semibold leading-6 text-slate-800">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="my-1 leading-6">{children}</p>,
          h1: ({ children }) => <h1 className="mb-1 mt-2 text-base font-bold leading-6">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-1 mt-2 text-sm font-bold leading-6">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-1 mt-1.5 text-sm font-bold leading-6">{children}</h3>,
          ul: ({ children }) => <ul className="my-1 list-disc space-y-0 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="my-1 list-decimal space-y-0 pl-5">{children}</ol>,
          li: ({ children }) => <li className="my-0 leading-6">{children}</li>,
          code: ({ children }) => <code className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[12px] text-slate-800">{children}</code>,
          pre: ({ children }) => <pre className="my-1.5 overflow-auto rounded-lg bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">{children}</pre>,
        }}
      >
        {normalizeProcessMarkdown(body)}
      </ReactMarkdown>
    </div>
  );
}

function ToolCallBlock({ call }: { call: ProcessToolCall }) {
  const [expanded, setExpanded] = useState(call.status !== "completed" && call.status !== "failed");
  const failed = call.status === "failed" || call.success === false;
  const completed = call.status === "completed";
  const descriptor = describeToolCall(call);
  const Icon = descriptor.icon;
  const elapsedMs = resolveToolElapsedMs(call);
  const statusText = toolStatusText(call.status);

  return (
    <div className="group relative pl-7">
      <span className="absolute left-[7px] top-6 h-[calc(100%-1rem)] w-px bg-slate-200" />
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className={cn(
          "flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-left transition hover:bg-slate-50",
          !completed && !failed && "bg-[#efeafe] text-[#4733c9] ring-1 ring-[#e4ddfc]",
        )}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="absolute left-0 top-2 flex h-4 w-4 items-center justify-center rounded-full bg-white">
            <Icon size={15} className="text-slate-500" />
          </span>
          <span className="min-w-0">
            <span className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-semibold leading-5 text-slate-700">
              <span className="truncate">{descriptor.activity}</span>
              <span className="font-mono text-[11px] text-slate-400">{call.name}</span>
            </span>
            {descriptor.target ? (
              <span className="mt-0.5 block truncate font-mono text-[11px] leading-4 text-slate-400">
                {descriptor.target}
              </span>
            ) : null}
          </span>
        </span>
        <span className="mt-0.5 inline-flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-slate-400">
          {failed ? (
            <XCircle size={13} className="shrink-0 text-rose-600" />
          ) : completed ? (
            <CheckCircle size={13} className="shrink-0 text-fuchsia-600" />
          ) : (
            <Loader2 size={13} className="shrink-0 animate-spin text-[#6d5cf0]" />
          )}
          {typeof elapsedMs === "number" ? formatDuration(elapsedMs) : statusText}
        </span>
      </button>
      {expanded ? (
        <div className="ml-2 mt-1.5 space-y-2 rounded-xl border border-slate-200 bg-white/90 p-3 animate-slide-down">
          <ToolExecutionPlan call={call} descriptor={descriptor} />
          <div className="grid gap-2 md:grid-cols-2">
            <ToolPayload title="输入" value={formatToolPayload(call.input)} />
            <ToolPayload
              title={failed ? "错误" : "结果"}
              value={formatToolPayload(call.output) || (completed ? "(empty)" : call.status === "preparing" ? "等待模型生成完整工具参数..." : "等待工具返回...")}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ToolExecutionPlan({
  call,
  descriptor,
}: {
  call: ProcessToolCall;
  descriptor: ReturnType<typeof describeToolCall>;
}) {
  const failed = call.status === "failed" || call.success === false;
  const completed = call.status === "completed";
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold text-slate-700">{descriptor.activity}</div>
          {descriptor.target ? <div className="mt-0.5 truncate font-mono text-[11px] text-slate-400">{descriptor.target}</div> : null}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold",
            failed ? "bg-rose-50 text-rose-600" : completed ? "bg-fuchsia-50 text-fuchsia-700" : "bg-[#efeafe] text-[#4733c9]",
          )}
        >
          {failed ? "执行失败" : completed ? "执行完成" : call.status === "preparing" ? "准备参数" : "正在执行"}
        </span>
      </div>
      {descriptor.steps.length ? (
        <ol className="mt-2 space-y-1">
          {descriptor.steps.map((step, index) => (
            <li key={`${call.id}-step-${index}`} className="flex gap-2 text-xs leading-5 text-slate-600">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-white font-mono text-[10px] text-slate-400 ring-1 ring-slate-200">
                {index + 1}
              </span>
              <span className="min-w-0 break-words">{step}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

function SubAgentProcess({ items }: { items: SubAgentRuntimeItem[] }) {
  const [expanded, setExpanded] = useState(true);
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const running = items.length - completed - failed;

  return (
    <div className="relative pl-7">
      <span className="absolute left-[7px] top-6 h-[calc(100%-1rem)] w-px bg-slate-200" />
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 rounded-xl px-2 py-1 text-left transition hover:bg-slate-50"
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="absolute left-0 top-2 flex h-4 w-4 items-center justify-center rounded-full bg-white">
            <Bot size={15} className="text-slate-500" />
          </span>
          <span className="min-w-0 text-sm font-medium text-slate-600">
            子 Agent 进度
            <span className="ml-2 font-mono text-[11px] text-slate-400">
              {completed}/{items.length}
              {running > 0 ? ` · ${running} running` : ""}
              {failed > 0 ? ` · ${failed} failed` : ""}
            </span>
          </span>
        </span>
        {expanded ? <ChevronDown size={13} className="text-slate-400" /> : <ChevronRight size={13} className="text-slate-400" />}
      </button>
      {expanded ? (
        <div className="ml-2 mt-1.5 space-y-1.5">
          {items.map((item, index) => (
            <div key={`${item.run_id ?? "run"}-${item.index}-${index}`} className="rounded-xl border border-slate-200 bg-white/85 px-3 py-2">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate font-semibold text-slate-700">{item.agent || `sub-agent ${item.index + 1}`}</span>
                <span className={cn("shrink-0 font-mono text-[10px]", item.status === "failed" ? "text-rose-500" : "text-slate-400")}>
                  {item.status}
                </span>
              </div>
              {item.task ? <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{item.task}</p> : null}
              {item.error ? <p className="mt-1 rounded-lg bg-rose-50 px-2 py-1 text-xs text-rose-600">{item.error}</p> : null}
              {subagentResultText(item) ? <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-600">{subagentResultText(item)}</p> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ToolPayload({ title, value }: { title: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[11px] font-semibold text-slate-400">{title}</div>
      <pre className="max-h-56 overflow-auto rounded-lg bg-slate-950 px-3 py-2.5 font-mono text-[11px] leading-5 text-slate-100">
        {value || "{}"}
      </pre>
    </div>
  );
}

function subagentResultText(item: SubAgentRuntimeItem) {
  return item.response || item.summary || "";
}

function describeToolCall(call: ProcessToolCall) {
  const input = normalizeObject(call.input);
  const name = call.name || "unknown_tool";
  const explicitDescription = pickString(input, ["description", "reason", "title"]);
  const chips = compactStrings([
    ...pickStringArray(input, ["path", "paths", "directory", "root", "id", "skill_id", "name", "query", "url", "pattern", "command"]),
  ]).slice(0, 6);
  const target = inferToolTarget(name, input);

  if (["directory_tree", "list_directory", "list_directory_with_sizes", "ls"].includes(name)) {
    return {
      label: explicitDescription || "查看文件结构",
      activity: target ? `查看目录结构：${target}` : "查看当前可访问目录结构",
      target,
      steps: compactStrings(["读取目录入口", target ? `列出 ${target} 下的文件与文件夹` : "", "返回可用于下一步判断的目录摘要"]),
      icon: FolderOpen,
      chips,
    };
  }
  if (["search_files", "web_search", "image_search"].includes(name)) {
    return {
      label: explicitDescription || (name === "search_files" ? "搜索本地文件" : "搜索相关信息"),
      activity: target ? `搜索：${target}` : "搜索可用信息",
      target,
      steps: compactStrings(["整理检索关键词", target ? `检索 ${target}` : "执行检索", "返回候选结果供后续分析"]),
      icon: Search,
      chips,
    };
  }
  if (["read_file", "read_text_file", "read_multiple_files", "read_media_file", "read_skill"].includes(name)) {
    return {
      label: explicitDescription || (name === "read_skill" ? "读取 skill 文件" : "读取文件内容"),
      activity: name === "read_skill" ? `读取 Skill 内容：${target || "SKILL.md"}` : `读取文件内容${target ? `：${target}` : ""}`,
      target,
      steps:
        name === "read_skill"
          ? compactStrings(["定位 managed skill", target ? `读取 ${target}` : "读取 SKILL.md", "返回文件树、内容和可执行工具摘要"])
          : compactStrings([target ? `读取 ${target}` : "读取目标文件", "返回文本内容供模型分析"]),
      icon: BookOpenText,
      chips,
    };
  }
  if (["write_file", "edit_file", "create_directory", "move_file", "skill_manage"].includes(name)) {
    if (name === "skill_manage") {
      const skill = describeSkillManage(input);
      return {
        ...skill,
        icon: FilePenLine,
        chips: compactStrings([...chips, ...(skill.target ? [skill.target] : [])]).slice(0, 6),
      };
    }
    return {
      label: explicitDescription || "修改文件",
      activity: target ? `修改文件：${target}` : "修改文件内容",
      target,
      steps: compactStrings([target ? `定位 ${target}` : "定位目标路径", "写入或更新内容", "返回写入结果"]),
      icon: FilePenLine,
      chips,
    };
  }
  if (["bash", "shell", "run_command"].includes(name)) {
    return {
      label: explicitDescription || "运行命令",
      activity: target ? `运行命令：${target}` : "运行命令",
      target,
      steps: compactStrings(["准备命令参数", target ? `执行 ${target}` : "执行命令", "收集 stdout/stderr 和退出状态"]),
      icon: SquareTerminal,
      chips,
    };
  }
  if (["fetch", "web_fetch"].includes(name)) {
    return {
      label: explicitDescription || "读取网页内容",
      activity: target ? `抓取网页：${target}` : "抓取网页内容",
      target,
      steps: compactStrings(["发起网页请求", "提取页面正文", "返回可引用的网页内容"]),
      icon: Globe,
      chips,
    };
  }
  return {
    label: explicitDescription || `调用工具 ${name}`,
    activity: target ? `调用 ${name}：${target}` : `调用 ${name}`,
    target,
    steps: compactStrings(["准备工具输入", "执行工具", "返回工具结果"]),
    icon: Wrench,
    chips,
  };
}

function describeSkillManage(input: Record<string, unknown>) {
  const action = pickString(input, ["action"]) || "update";
  const id = pickString(input, ["id", "skill_id", "name"]);
  const path = pickString(input, ["path"]);
  const target =
    action === "patch" || action === "edit" || action === "create"
      ? `${id || "skill"}/SKILL.md`
      : action === "write_file" || action === "remove_file"
        ? `${id || "skill"}/${path || "resource file"}`
        : action === "delete" || action === "history"
          ? id
          : path || id;
  const executable = typeof input.executable_code === "string" && input.executable_code.trim().length > 0;
  const files = Array.isArray(input.files) ? input.files.length : 0;
  const actionLabel: Record<string, string> = {
    create: "创建 Skill",
    edit: "重写 Skill",
    patch: "精确修补 Skill",
    write_file: "写入 Skill 资源文件",
    remove_file: "删除 Skill 资源文件",
    delete: "删除 Skill",
    history: "查看 Skill 历史",
  };
  const steps = compactStrings([
    id ? `定位 managed skill：${id}` : "定位目标 Skill",
    action === "patch" ? "按 find/replace 精确修改 SKILL.md" : "",
    action === "edit" ? "重写 SKILL.md，并保留未覆盖的资源文件" : "",
    action === "create" ? "创建 SKILL.md 和资源文件" : "",
    action === "write_file" ? `写入资源文件：${path || "未指定路径"}` : "",
    action === "remove_file" ? `移除资源文件：${path || "未指定路径"}` : "",
    files > 0 ? `同步 ${files} 个 bundled resource 文件` : "",
    executable ? "更新可执行入口 skill.py" : "",
    action !== "history" ? "校验内容、记录历史并刷新 Skill 缓存" : "读取最近的变更历史",
  ]);
  return {
    label: actionLabel[action] || "更新 skill 内容",
    activity: `${actionLabel[action] || "更新 Skill"}${target ? `：${target}` : ""}`,
    target,
    steps,
  };
}

function inferToolTarget(name: string, input: Record<string, unknown>) {
  if (name === "read_skill") {
    const id = pickString(input, ["id", "skill_id"]);
    const path = pickString(input, ["path"]) || "SKILL.md";
    return id ? `${id}/${path}` : path;
  }
  if (name === "skill_manage") return describeSkillManage(input).target;
  const values = pickStringArray(input, ["path", "paths", "directory", "root", "id", "skill_id", "query", "url", "pattern", "command"]);
  return values[0] || "";
}

function buildFallbackBlocks(content: string, events: ProcessEvent[], toolCalls: ProcessToolCall[]): ProcessBlock[] {
  const blocks: ProcessBlock[] = [];
  const trimmed = content.trim();

  if (trimmed) blocks.push({ id: "thinking-summary", type: "text", body: trimmed });
  for (const event of events) {
    if (!event.label || event.label === "思考") continue;
    blocks.push({
      id: `event-${event.id}`,
      type: "event",
      title: phaseLabel(event.phase, event.label),
      elapsedMs: event.elapsedMs,
      phase: event.phase,
    });
  }
  for (const toolCall of toolCalls) {
    blocks.push({ id: `tool-${toolCall.id}`, type: "tool", toolCall });
  }
  return blocks.length ? blocks.slice(-32) : [{ id: "waiting", type: "event", title: "等待模型返回处理过程" }];
}

function phaseLabel(phase: string | undefined, fallback: string) {
  if (phase === "startup") return "准备运行";
  if (phase === "reasoning") return "分析问题";
  if (phase === "planning") return "制定计划";
  if (phase === "writing") return "整理回答";
  if (phase === "done") return "完成处理";
  if (phase === "error") return "处理异常";
  return fallback;
}

function resolveElapsedMs({
  events,
  toolCalls,
  startedAt,
  finishedAt,
  now,
}: {
  events: ProcessEvent[];
  toolCalls: ProcessToolCall[];
  startedAt?: number;
  finishedAt?: number;
  now: number;
}) {
  if (startedAt) return Math.max(0, (finishedAt ?? now) - startedAt);
  const eventElapsed = events.map((event) => event.elapsedMs ?? 0);
  const toolElapsed = toolCalls.map((tool) => tool.elapsedMs ?? 0);
  return Math.max(0, ...eventElapsed, ...toolElapsed);
}

function resolveToolElapsedMs(call: ProcessToolCall) {
  if (typeof call.elapsedMs === "number") return call.elapsedMs;
  if (call.status === "preparing") return undefined;
  const running = call.status !== "completed" && call.status !== "failed";
  if (running && typeof call.startedAt === "number") return Math.max(0, Date.now() - call.startedAt);
  return undefined;
}

function toolStatusText(status: string) {
  if (status === "preparing") return "准备参数";
  if (status === "started") return "执行中";
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  return status;
}

function normalizeObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function pickString(input: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function pickStringArray(input: Record<string, unknown>, keys: string[]) {
  const values: string[] = [];
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) {
      values.push(value.trim());
    } else if (Array.isArray(value)) {
      values.push(...value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim()));
    }
  }
  return values;
}

function compactStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function normalizeProcessMarkdown(value: string) {
  return value
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\s+$/gm, "")
    .trim();
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

function formatDuration(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes <= 0) return `${rest}s`;
  return `${minutes}m ${rest}s`;
}
