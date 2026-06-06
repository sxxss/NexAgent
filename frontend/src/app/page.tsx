"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  Database,
  History,
  BookOpen,
  LayoutDashboard,
  Loader2,
  Maximize2,
  MessageSquare,
  Phone,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wrench,
  X,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChatInput } from "@/components/chat/ChatInput";
import { MessageBubble, type Message, type ProcessBlock, type ToolCallRuntime } from "@/components/chat/MessageBubble";
import { ThinkingToggle } from "@/components/chat/ThinkingToggle";
import { VoiceCallOverlay } from "@/components/chat/VoiceCallOverlay";
import { WikiModal } from "@/components/chat/WikiModal";
import {
  deleteConversation,
  fetchAgents,
  fetchConversation,
  fetchConversations,
  fetchInstalledMCP,
  fetchKBs,
  fetchModels,
  fetchSkills,
  fetchTools,
  streamChat,
  updateConversation,
  type AgentConfig,
  type Conversation,
  type ConversationMessage,
  type KBMeta,
  type MCPServer,
  type Model,
  type ReasoningMode,
  type StreamChunk,
  type SkillInfo,
  type SubAgentModelStrategy,
  type SubAgentRuntimeItem,
  type ToolInfo,
} from "@/lib/api";
import { useWorkspaceStore } from "@/lib/store";
import { cn } from "@/lib/utils";

let idSeed = 0;
const uid = () => `local-${++idSeed}`;
const CONVERSATION_COLLAPSED_KEY = "nexagent.home.conversationCollapsed";
const INSPECTOR_COLLAPSED_KEY = "nexagent.home.inspectorCollapsed";
const CHAT_PROFILES_KEY = "nexagent.home.chatProfiles";
const SELECTED_PROFILE_KEY = "nexagent.home.selectedProfileId";
const SELECTED_CHAT_MODE_KEY = "nexagent.home.selectedChatMode";
const CHAT_WIDTH_KEY = "nexagent.home.chatWidth";
const CHAT_DENSITY_KEY = "nexagent.home.chatDensity";

type ChatWidth = "normal" | "wide" | "full";
type ChatDensity = "comfortable" | "compact";

const CHAT_WIDTH_ORDER: ChatWidth[] = ["normal", "wide", "full"];
const CHAT_WIDTH_CLASS: Record<ChatWidth, string> = {
  normal: "max-w-3xl",
  wide: "max-w-5xl",
  full: "max-w-none",
};
const CHAT_WIDTH_LABEL: Record<ChatWidth, string> = {
  normal: "标准宽度",
  wide: "宽屏",
  full: "全宽",
};

function isChatWidth(value: string | null): value is ChatWidth {
  return value === "normal" || value === "wide" || value === "full";
}
function isChatDensity(value: string | null): value is ChatDensity {
  return value === "comfortable" || value === "compact";
}
const CHAT_STREAM_CLIENT_IDLE_TIMEOUT_MS = 35 * 60 * 1000;
const ALL_REASONING_MODES: ReasoningMode[] = ["fast", "balanced", "deep", "ultra"];
const REASONING_EFFORT_BY_MODE = {
  fast: "minimal",
  balanced: "low",
  deep: "medium",
  ultra: "high",
} as const satisfies Record<ReasoningMode, "minimal" | "low" | "medium" | "high">;
const PLANNING_ENABLED_BY_MODE = {
  fast: false,
  balanced: false,
  deep: true,
  ultra: true,
} as const satisfies Record<ReasoningMode, boolean>;

type ChatMode = "chatbot" | "deep_research";
type ResourceSection = "tools" | "knowledge" | "mcp" | "skills" | "subagents";

const CHAT_MODES: Array<{ id: ChatMode; label: string; description: string }> = [
  { id: "chatbot", label: "智能助手", description: "日常对话、工具调用和任务执行" },
  { id: "deep_research", label: "深度分析", description: "多步检索、研究规划和结构化报告" },
];

function isChatMode(value: string): value is ChatMode {
  return value === "chatbot" || value === "deep_research";
}

function normalizeProfileTools(tools: string[], allowSubagents: boolean) {
  const withoutDelegate = tools.filter((tool) => tool !== "delegate_subagents");
  return allowSubagents ? Array.from(new Set([...withoutDelegate, "delegate_subagents"])) : withoutDelegate;
}

function uniqueByName<T extends { name: string }>(items: T[]) {
  const map = new Map<string, T>();
  for (const item of items) {
    if (!map.has(item.name)) map.set(item.name, item);
  }
  return Array.from(map.values());
}

function streamEventLabel(chunk: StreamChunk) {
  if (chunk.status === "started") return "启动";
  if (chunk.status === "heartbeat") return chunk.idle_seconds ? `处理中 ${chunk.idle_seconds}s` : "处理中";
  if (chunk.status === "thinking") return "思考";
  if (chunk.status === "tool_call") return chunk.tool ? `工具 ${chunk.tool}` : "";
  if (chunk.status === "tool_result") return chunk.tool ? `工具完成 ${chunk.tool}` : "工具完成";
  if (chunk.status === "plan") return "规划";
  if (chunk.status === "research_step") return chunk.title ? `研究 ${chunk.title}` : "研究";
  if (chunk.status === "writing") return "写作";
  if (chunk.status === "state" && chunk.new_artifacts?.length) return `产物 +${chunk.new_artifacts.length}`;
  if (chunk.status === "subagent_started") return "子任务启动";
  if (chunk.status === "subagent_progress") return "子任务运行";
  if (chunk.status === "subagent_completed") return `子任务完成 ${chunk.succeeded ?? ""}/${chunk.total ?? ""}`.trim();
  if (chunk.status === "subagent_failed") return `子任务异常 ${chunk.failed ?? ""}`.trim();
  if (chunk.status === "finished") return "完成";
  if (chunk.status === "error") return "错误";
  if (chunk.status === "interrupted") return "中断";
  return "";
}

function reduceAssistantMessage(message: Message, chunk: StreamChunk): Message {
  let next: Message = message;
  const label = streamEventLabel(chunk);

  if (chunk.thread_id) {
    next = { ...next, artifactThreadId: chunk.thread_id };
  }

  if (chunk.status === "started") {
    next = {
      ...next,
      runStartedAt: next.runStartedAt ?? Date.now(),
      runtime: {
        agent: chunk.agent,
        model: chunk.model,
        tools: chunk.tools ?? [],
        kbIds: chunk.kb_ids ?? [],
        mcpIds: chunk.mcp_ids ?? [],
        skillIds: chunk.skill_ids ?? [],
        reasoningMode: chunk.reasoning_mode,
      },
    };
  }

  if (label) {
    next = {
      ...next,
      events: [
        ...(next.events ?? []),
        {
          id: chunk.event_id ?? `${chunk.status}-${Date.now()}`,
          label,
          phase: chunk.phase,
          elapsedMs: chunk.elapsed_ms,
        },
      ].slice(-16),
    };
    if (!["thinking", "tool_call", "tool_result", "heartbeat", "finished"].includes(chunk.status)) {
      next = appendProcessBlock(next, {
        id: `event-${chunk.event_id ?? `${chunk.status}-${Date.now()}`}`,
        type: "event",
        title: label,
        phase: chunk.phase,
        elapsedMs: chunk.elapsed_ms,
      });
    }
  }

  if (chunk.status === "thinking" && chunk.content) {
    return appendThinkingBlock({
      ...next,
      thinkingContent: `${next.thinkingContent ?? ""}${chunk.content}`,
    }, chunk.content);
  }

  if (chunk.status === "loading" && chunk.content) {
    if (!(next.toolCalls?.length)) {
      return { ...next, content: `${next.content}${chunk.content}` };
    }
    return appendThinkingBlock(next, chunk.content);
  }

  if (chunk.status === "tool_call" && shouldShowToolCall(chunk.tool, chunk.input)) {
    if (next.content.trim()) {
      next = appendThinkingBlock(next, next.content);
      next = { ...next, content: "" };
    }
    if (next.pendingProcessContent) {
      next = appendThinkingBlock(next, next.pendingProcessContent);
      next = { ...next, pendingProcessContent: "" };
    }
    const toolCalls = mergeToolCall(next.toolCalls ?? [], chunk);
    return {
      ...next,
      toolCalls,
      processBlocks: mergeProcessToolBlock(next.processBlocks ?? [], toolCalls[toolCalls.length - 1]),
    };
  }

  if (chunk.status === "tool_result") {
    const toolCalls = mergeToolCall(next.toolCalls ?? [], chunk);
    const updated = toolCalls.find((toolCall) => toolCall.id === (chunk.tool_call_id || `${chunk.tool ?? "tool"}-${chunk.event_id ?? ""}`));
    return {
      ...next,
      toolCalls,
      processBlocks: mergeProcessToolBlock(next.processBlocks ?? [], updated ?? toolCalls[toolCalls.length - 1]),
    };
  }

  if (chunk.status === "state" && chunk.artifacts?.length) {
    return { ...next, artifacts: Array.from(new Set([...(next.artifacts ?? []), ...chunk.artifacts])) };
  }

  if (chunk.status.startsWith("subagent") && chunk.subagents?.length) {
    const incomingSubagents = chunk.subagents.map((item) => ({
      ...item,
      run_id: item.run_id ?? chunk.run_id,
    }));
    return { ...next, subagents: mergeSubagents(next.subagents ?? [], incomingSubagents) };
  }

  if (chunk.status === "finished") {
    const finalContent = resolveFinishedContent(next, chunk);
    const fallbackContent = fallbackFinishedContent(next);
    const finishedAt = Date.now();
    const finalizedToolCalls = finalizeOpenToolCalls(next.toolCalls ?? [], "completed", finishedAt);
    return {
      ...next,
      content: finalContent.trim() ? finalContent : fallbackContent,
      toolCalls: finalizedToolCalls,
      processBlocks: syncProcessToolBlocks(next.processBlocks ?? [], finalizedToolCalls),
      pendingProcessContent: "",
      isStreaming: false,
      runFinishedAt: finishedAt,
    };
  }

  if (chunk.status === "error") {
    const finishedAt = Date.now();
    const finalizedToolCalls = finalizeOpenToolCalls(next.toolCalls ?? [], "failed", finishedAt, chunk.error ?? "Stream ended with error.");
    return {
      ...next,
      content: `请求失败：${chunk.error ?? "后端未返回错误详情"}`,
      toolCalls: finalizedToolCalls,
      processBlocks: syncProcessToolBlocks(next.processBlocks ?? [], finalizedToolCalls),
      isStreaming: false,
      runFinishedAt: finishedAt,
    };
  }

  if (chunk.status === "interrupted") {
    const finishedAt = Date.now();
    const finalizedToolCalls = finalizeOpenToolCalls(next.toolCalls ?? [], "failed", finishedAt, "用户停止了本次响应。");
    return {
      ...next,
      content: next.content.trim() ? `${next.content}\n\n已停止本次响应。` : "已停止本次响应。",
      toolCalls: finalizedToolCalls,
      processBlocks: syncProcessToolBlocks(next.processBlocks ?? [], finalizedToolCalls),
      isStreaming: false,
      runFinishedAt: finishedAt,
    };
  }

  return next;
}

function appendProcessBlock(message: Message, block: ProcessBlock): Message {
  if ((message.processBlocks ?? []).some((item) => item.id === block.id)) return message;
  return { ...message, processBlocks: [...(message.processBlocks ?? []), block].slice(-48) };
}

function appendThinkingBlock(message: Message, content: string): Message {
  const blocks = [...(message.processBlocks ?? [])];
  const last = blocks[blocks.length - 1];
  if (last?.type === "text") {
    blocks[blocks.length - 1] = { ...last, body: `${last.body}${content}` };
  } else {
    blocks.push({ id: `text-${Date.now()}`, type: "text", body: content });
  }
  return { ...message, processBlocks: blocks.slice(-48) };
}

function resolveFinishedContent(message: Message, chunk: StreamChunk) {
  const backendContent = typeof chunk.content === "string" ? chunk.content : "";
  if (!(message.toolCalls?.length)) return message.content || message.pendingProcessContent || backendContent;

  const processText = collectProcessText(message);
  if (!backendContent) return message.content;
  if (!processText) return backendContent;
  if (backendContent.startsWith(processText)) {
    return backendContent.slice(processText.length).trimStart();
  }

  return backendContent;
}

function collectProcessText(message: Message) {
  return [
    ...(message.processBlocks ?? [])
      .filter((block) => block.type === "text")
      .map((block) => block.body),
    message.pendingProcessContent ?? "",
  ].join("");
}

function fallbackFinishedContent(message: Message) {
  const lastText = [...(message.processBlocks ?? [])]
    .reverse()
    .find((block) => block.type === "text" && block.body.trim().length > 12);
  if (lastText?.type === "text") return lastText.body.trim();
  const completedSubagents = (message.subagents ?? []).filter((item) => item.status === "completed" && subagentResultText(item).trim());
  if (completedSubagents.length) {
    return completedSubagents
      .map((item, index) => `子 Agent ${index + 1}：${subagentResultText(item).trim()}`)
      .join("\n\n");
  }
  return message.toolCalls?.length ? "任务已结束，但模型没有生成单独的最终总结。处理过程见上方步骤。" : "模型没有返回可显示内容。本次调用已结束，请重试或切换模型。";
}

function subagentResultText(item: SubAgentRuntimeItem) {
  return item.response || item.summary || "";
}

function mergeProcessToolBlock(blocks: ProcessBlock[], toolCall?: ToolCallRuntime): ProcessBlock[] {
  if (!toolCall) return blocks;
  const id = `tool-${toolCall.id}`;
  const index = blocks.findIndex((block) => block.id === id);
  const block: ProcessBlock = { id, type: "tool", toolCall };
  if (index < 0) return [...blocks, block].slice(-48);
  return blocks.map((item, itemIndex) => (itemIndex === index ? block : item));
}

function mergeToolCall(items: ToolCallRuntime[], chunk: StreamChunk): ToolCallRuntime[] {
  const id = chunk.tool_call_id || `${chunk.tool ?? "tool"}-${chunk.event_id ?? Date.now()}`;
  const index = items.findIndex((item) => item.id === id);
  const current = index >= 0 ? items[index] : undefined;
  const isResult = chunk.status === "tool_result";
  const incomingStatus = chunk.tool_status || (isResult ? "completed" : "started");
  const startedAt = incomingStatus === "started" && current?.status === "preparing" ? Date.now() : current?.startedAt ?? Date.now();
  const next: ToolCallRuntime = {
    id,
    name: chunk.tool || current?.name || "unknown_tool",
    input: chunk.status === "tool_call" ? chunk.input ?? {} : current?.input,
    output: isResult ? chunk.output : current?.output,
    status: incomingStatus,
    success: isResult ? chunk.success : current?.success,
    elapsedMs: isResult ? chunk.tool_elapsed_ms ?? Math.max(0, Date.now() - startedAt) : current?.elapsedMs,
    startedAt,
  };
  if (index < 0) return [...items, next].slice(-24);
  return items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...next } : item));
}

function finalizeOpenToolCalls(
  items: ToolCallRuntime[],
  status: "completed" | "failed",
  finishedAt: number,
  output?: unknown,
): ToolCallRuntime[] {
  return items.map((item) => {
    if (item.status === "completed" || item.status === "failed") return item;
    const elapsedMs = item.startedAt ? Math.max(0, finishedAt - item.startedAt) : item.elapsedMs;
    return {
      ...item,
      status,
      success: status === "completed" ? item.success ?? true : false,
      elapsedMs,
      output: item.output ?? output ?? (status === "completed" ? "Stream finished before this tool result was emitted." : undefined),
    };
  });
}

function syncProcessToolBlocks(blocks: ProcessBlock[], toolCalls: ToolCallRuntime[]): ProcessBlock[] {
  if (!blocks.length || !toolCalls.length) return blocks;
  const byId = new Map(toolCalls.map((toolCall) => [`tool-${toolCall.id}`, toolCall]));
  return blocks.map((block) => {
    if (block.type !== "tool") return block;
    const updated = byId.get(block.id);
    return updated ? { ...block, toolCall: updated } : block;
  });
}

interface ChatProfile {
  id: string;
  name: string;
  useAgentDefaults: boolean;
  tools: string[];
  kbIds: string[];
  mcpIds: string[];
  skillIds: string[];
  allowSubagents: boolean;
  allowedAgentIds: string[];
  subagentModelStrategy: SubAgentModelStrategy;
  subagentModel: string;
}

function readStoredBool(key: string) {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(key) === "1";
}

function defaultProfile(): ChatProfile {
  return {
    id: "default",
    name: "按 Agent 默认配置",
    useAgentDefaults: true,
    tools: [],
    kbIds: [],
    mcpIds: [],
    skillIds: [],
    allowSubagents: true,
    allowedAgentIds: [],
    subagentModelStrategy: "agent_default",
    subagentModel: "",
  };
}

function readStoredProfiles() {
  if (typeof window === "undefined") return [defaultProfile()];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(CHAT_PROFILES_KEY) || "[]") as ChatProfile[];
    const normalized = parsed.map((profile) => {
      const merged = { ...defaultProfile(), ...profile };
      return merged.id === "default" && (!merged.name || merged.name === "初始配置")
        ? { ...merged, name: "按 Agent 默认配置", useAgentDefaults: true }
        : merged;
    });
    return normalized.length ? normalized : [defaultProfile()];
  } catch {
    return [defaultProfile()];
  }
}

const STARTERS = [
  {
    title: "规划复杂任务",
    desc: "拆解目标、选择工具、输出可执行计划。",
    prompt: "帮我把 NexAgent 接下来要完善成开源产品的工作拆成可执行计划，并标注优先级。",
    icon: LayoutDashboard,
  },
  {
    title: "基于知识库回答",
    desc: "结合已绑定知识库检索上下文。",
    prompt: "请基于当前知识库，总结这个项目已经具备的核心能力和短板。",
    icon: Database,
  },
  {
    title: "创建扩展工具",
    desc: "让 Agent 起草 Skill 或 MCP 配置。",
    prompt: "我想添加一个读取网页并提取结构化信息的 Skill，请帮我设计。",
    icon: Sparkles,
  },
];

export default function ChatPage() {
  const queryClient = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const shouldAutoScrollRef = useRef(true);
  const modelPickerRef = useRef<HTMLDivElement>(null);
  const agentPickerRef = useRef<HTMLDivElement>(null);
  const thinkingRef = useRef<HTMLDivElement>(null);
  const profilePickerRef = useRef<HTMLDivElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const {
    selectedAgentId,
    selectedModelName,
    reasoningMode,
    setSelectedAgentId,
    setSelectedModelName,
    setReasoningMode,
  } = useWorkspaceStore();

  const [selectedConversationId, setSelectedConversationId] = useState<string>();
  const [threadId, setThreadId] = useState<string>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [showAgentPicker, setShowAgentPicker] = useState(false);
  const [showThinkingPicker, setShowThinkingPicker] = useState(false);
  const [storageReady, setStorageReady] = useState(false);
  const [conversationCollapsed, setConversationCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [chatWidth, setChatWidth] = useState<ChatWidth>("normal");
  const [chatDensity, setChatDensity] = useState<ChatDensity>("comfortable");
  const [showVoiceCall, setShowVoiceCall] = useState(false);
  const [showWiki, setShowWiki] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);
  const [profileRenameTarget, setProfileRenameTarget] = useState<ChatProfile | null>(null);
  const [profileRenameTitle, setProfileRenameTitle] = useState("");
  const [profiles, setProfiles] = useState<ChatProfile[]>([defaultProfile()]);
  const [selectedProfileId, setSelectedProfileId] = useState("default");
  const [selectedChatMode, setSelectedChatMode] = useState<ChatMode>("chatbot");
  const [showProfilePicker, setShowProfilePicker] = useState(false);

  const conversationsQuery = useQuery({ queryKey: ["conversations"], queryFn: fetchConversations });
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: fetchAgents });
  const kbsQuery = useQuery({ queryKey: ["kbs"], queryFn: fetchKBs });
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: fetchSkills });
  const mcpQuery = useQuery({ queryKey: ["mcp-installed"], queryFn: fetchInstalledMCP });
  const toolsQuery = useQuery({ queryKey: ["tools"], queryFn: fetchTools });

  const conversations = useMemo(() => conversationsQuery.data ?? [], [conversationsQuery.data]);
  const models = useMemo(() => modelsQuery.data ?? [], [modelsQuery.data]);
  const agents = useMemo(() => agentsQuery.data ?? [], [agentsQuery.data]);
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const skills = useMemo(() => skillsQuery.data ?? [], [skillsQuery.data]);
  const mcpServers = useMemo(() => mcpQuery.data ?? [], [mcpQuery.data]);
  const tools = useMemo(() => uniqueByName(toolsQuery.data ?? []), [toolsQuery.data]);
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId) ?? profiles[0] ?? defaultProfile();
  const modeAgents = useMemo(
    () => agents.filter((agent) => agent.base_type === selectedChatMode),
    [agents, selectedChatMode],
  );

  const updateSelectedProfile = useCallback(
    (patch: Partial<ChatProfile>) => {
      setProfiles((prev) =>
        prev.map((profile) => (profile.id === selectedProfile.id ? { ...profile, ...patch } : profile)),
      );
    },
    [selectedProfile.id],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const storedMode = window.localStorage.getItem(SELECTED_CHAT_MODE_KEY) || "chatbot";
      setSelectedChatMode(isChatMode(storedMode) ? storedMode : "chatbot");
      setSelectedProfileId(window.localStorage.getItem(SELECTED_PROFILE_KEY) || "default");
      setProfiles(readStoredProfiles());
      setConversationCollapsed(readStoredBool(CONVERSATION_COLLAPSED_KEY));
      setInspectorCollapsed(readStoredBool(INSPECTOR_COLLAPSED_KEY));
      const storedWidth = window.localStorage.getItem(CHAT_WIDTH_KEY);
      if (isChatWidth(storedWidth)) setChatWidth(storedWidth);
      const storedDensity = window.localStorage.getItem(CHAT_DENSITY_KEY);
      if (isChatDensity(storedDensity)) setChatDensity(storedDensity);
      setStorageReady(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(SELECTED_CHAT_MODE_KEY, selectedChatMode);
  }, [selectedChatMode, storageReady]);

  useEffect(() => {
    if (!agents.some((agent) => agent.id === selectedAgentId) && agents[0]) {
      setSelectedAgentId(agents[0].id);
    }
  }, [agents, selectedAgentId, setSelectedAgentId]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(CHAT_PROFILES_KEY, JSON.stringify(profiles));
  }, [profiles, storageReady]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(SELECTED_PROFILE_KEY, selectedProfileId);
  }, [selectedProfileId, storageReady]);

  useEffect(() => {
    if (shouldAutoScrollRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(CONVERSATION_COLLAPSED_KEY, conversationCollapsed ? "1" : "0");
  }, [conversationCollapsed, storageReady]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(INSPECTOR_COLLAPSED_KEY, inspectorCollapsed ? "1" : "0");
  }, [inspectorCollapsed, storageReady]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(CHAT_WIDTH_KEY, chatWidth);
  }, [chatWidth, storageReady]);

  useEffect(() => {
    if (storageReady) window.localStorage.setItem(CHAT_DENSITY_KEY, chatDensity);
  }, [chatDensity, storageReady]);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      const target = event.target as Node;
      if (modelPickerRef.current && !modelPickerRef.current.contains(target)) setShowModelPicker(false);
      if (agentPickerRef.current && !agentPickerRef.current.contains(target)) setShowAgentPicker(false);
      if (thinkingRef.current && !thinkingRef.current.contains(target)) setShowThinkingPicker(false);
      if (profilePickerRef.current && !profilePickerRef.current.contains(target)) setShowProfilePicker(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const activeAgentId = selectedAgentId || (selectedChatMode === "chatbot" ? "chatbot" : "deep_research");
  const selectedAgent = agents.find((agent) => agent.id === activeAgentId && agent.base_type === selectedChatMode) ?? modeAgents[0];
  const runtimeAgentId = selectedAgent?.id ?? activeAgentId;
  const selectedModelExists = !selectedModelName || models.some((model) => model.name === selectedModelName);
  const effectiveSelectedModelName = selectedModelExists ? selectedModelName : "";
  const activeModelName = effectiveSelectedModelName || selectedAgent?.model_name || models[0]?.name || "";
  const activeReasoningMode = reasoningMode;
  const selectedModel = models.find((model) => model.name === activeModelName);
  const modelGroups = useMemo(() => groupModelsByProvider(models, modelSearch), [modelSearch, models]);
  const supportedModes = ALL_REASONING_MODES;
  const effectiveMode = ALL_REASONING_MODES.includes(activeReasoningMode) ? activeReasoningMode : "balanced";

  const switchMode = useCallback(
    (mode: ChatMode) => {
      const nextAgent = agents.find((agent) => agent.base_type === mode);
      const nextReasoningMode: ReasoningMode = mode === "deep_research" ? "deep" : "balanced";
      setSelectedChatMode(mode);
      if (nextAgent) setSelectedAgentId(nextAgent.id);
      setReasoningMode(nextReasoningMode);
      setShowAgentPicker(false);
    },
    [agents, setReasoningMode, setSelectedAgentId],
  );

  const deleteMutation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  const selectConversation = useCallback(
    async (conversationId: string) => {
      const conversation = await fetchConversation(conversationId);
      if (!conversation) return;
      setSelectedConversationId(conversation.id);
      setThreadId(conversation.id);
      setMessages((conversation.messages ?? []).map(toMessage));
      if (conversation.agent_id) {
        const conversationAgent = agents.find((agent) => agent.id === conversation.agent_id);
        setSelectedAgentId(conversation.agent_id);
        if (conversationAgent && isChatMode(conversationAgent.base_type)) {
          setSelectedChatMode(conversationAgent.base_type);
        }
      }
      if (conversation.model_name) setSelectedModelName(conversation.model_name);
    },
    [agents, setSelectedAgentId, setSelectedModelName],
  );

  const startNew = useCallback(() => {
    setMessages([]);
    setInput("");
    setThreadId(undefined);
    setSelectedConversationId(undefined);
  }, []);

  const openRenameDialog = (conversation: Conversation) => {
    setRenameTarget(conversation);
    setRenameTitle(conversation.title || "");
  };

  const closeRenameDialog = () => {
    if (renameSaving) return;
    setRenameTarget(null);
    setRenameTitle("");
  };

  const submitRename = async () => {
    const title = renameTitle.trim();
    if (!renameTarget || !title) return;
    setRenameSaving(true);
    try {
      await updateConversation(renameTarget.id, { title });
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setRenameTarget(null);
      setRenameTitle("");
    } finally {
      setRenameSaving(false);
    }
  };

  const openProfileRenameDialog = (profile: ChatProfile) => {
    setProfileRenameTarget(profile);
    setProfileRenameTitle(profile.name || "");
    setShowProfilePicker(false);
  };

  const closeProfileRenameDialog = () => {
    setProfileRenameTarget(null);
    setProfileRenameTitle("");
  };

  const submitProfileRename = () => {
    const title = profileRenameTitle.trim();
    if (!profileRenameTarget || !title) return;
    setProfiles((prev) =>
      prev.map((profile) => (profile.id === profileRenameTarget.id ? { ...profile, name: title } : profile)),
    );
    closeProfileRenameDialog();
  };

  const deleteProfile = (profileId: string) => {
    if (profileId === "default") return;
    setProfiles((prev) => {
      const next = prev.filter((profile) => profile.id !== profileId);
      if (selectedProfileId === profileId) setSelectedProfileId(next[0]?.id ?? "default");
      return next.length ? next : [defaultProfile()];
    });
    setShowProfilePicker(false);
  };

  const send = useCallback(
    async (text?: string) => {
      const userText = (text ?? input).trim();
      if (!userText || isStreaming) return;

      setInput("");
      setIsStreaming(true);
      shouldAutoScrollRef.current = true;
      const assistantId = uid();
      streamAbortRef.current?.abort("new-message");
      const controller = new AbortController();
      streamAbortRef.current = controller;
      let terminalReceived = false;
      let assistantHasContent = false;
      let idleTimer: number | undefined;
      const resetIdleTimer = () => {
        if (idleTimer) window.clearTimeout(idleTimer);
        idleTimer = window.setTimeout(() => controller.abort("idle-timeout"), CHAT_STREAM_CLIENT_IDLE_TIMEOUT_MS);
      };
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "user", content: userText },
        { id: assistantId, role: "assistant", content: "", isStreaming: true, runStartedAt: Date.now() },
      ]);

      try {
        resetIdleTimer();
        for await (const chunk of streamChat({
          message: userText,
          thread_id: threadId,
          agent: runtimeAgentId,
          model: effectiveSelectedModelName || undefined,
          tools: selectedProfile.useAgentDefaults
            ? undefined
            : normalizeProfileTools(selectedProfile.tools, selectedProfile.allowSubagents),
          kb_ids: selectedProfile.useAgentDefaults ? undefined : selectedProfile.kbIds,
          mcp_ids: selectedProfile.useAgentDefaults ? undefined : selectedProfile.mcpIds,
          skill_ids: selectedProfile.useAgentDefaults ? undefined : selectedProfile.skillIds,
          allow_subagents: selectedProfile.useAgentDefaults ? undefined : selectedProfile.allowSubagents,
          allowed_agent_ids: selectedProfile.useAgentDefaults ? undefined : selectedProfile.allowedAgentIds,
          subagent_model_strategy: selectedProfile.useAgentDefaults ? undefined : selectedProfile.subagentModelStrategy,
          subagent_model:
            selectedProfile.useAgentDefaults || selectedProfile.subagentModelStrategy !== "custom"
              ? undefined
              : selectedProfile.subagentModel || undefined,
          reasoning_mode: effectiveMode,
          reasoning_effort: REASONING_EFFORT_BY_MODE[effectiveMode],
          planning_enabled: PLANNING_ENABLED_BY_MODE[effectiveMode],
          thinking: effectiveMode !== "fast",
        }, { signal: controller.signal })) {
          resetIdleTimer();
          if (chunk.thread_id) {
            setThreadId(chunk.thread_id);
            setSelectedConversationId(chunk.thread_id);
          }

          if (chunk.status === "loading" && chunk.content) {
            assistantHasContent = true;
          }
          if (chunk.status === "finished" || chunk.status === "error" || chunk.status === "interrupted") {
            terminalReceived = true;
          }
          setMessages((prev) =>
            prev.map((item) => (item.id === assistantId ? reduceAssistantMessage(item, chunk) : item)),
          );
        }
        if (!terminalReceived) {
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    content: assistantHasContent
                      ? item.content
                      : "连接已结束，但没有收到完整结束事件。请重试，或检查后端日志。",
                    isStreaming: false,
                    runFinishedAt: Date.now(),
                  }
                : item,
            ),
          );
        }
      } catch (error) {
        const aborted = error instanceof DOMException && error.name === "AbortError";
        setMessages((prev) =>
          prev.map((item) =>
            item.id === assistantId
              ? {
                  ...item,
                  content: aborted
                    ? `${item.content}${item.content.trim() ? "\n\n" : ""}已停止本次响应。`
                    : `连接失败：${error instanceof Error ? error.message : "请确认后端服务正在运行"}`,
                  isStreaming: false,
                  runFinishedAt: Date.now(),
                }
              : item,
          ),
        );
      } finally {
        if (idleTimer) window.clearTimeout(idleTimer);
        if (streamAbortRef.current === controller) streamAbortRef.current = null;
        setIsStreaming(false);
        await queryClient.invalidateQueries({ queryKey: ["conversations"] });
      }
    },
    [
      effectiveMode,
      input,
      isStreaming,
      queryClient,
      runtimeAgentId,
      selectedProfile.kbIds,
      selectedProfile.mcpIds,
      selectedProfile.allowSubagents,
      selectedProfile.allowedAgentIds,
      selectedProfile.subagentModel,
      selectedProfile.subagentModelStrategy,
      selectedProfile.skillIds,
      selectedProfile.tools,
      selectedProfile.useAgentDefaults,
      effectiveSelectedModelName,
      threadId,
    ],
  );

  const layoutClass = cn(
    "grid h-full min-w-0 grid-cols-1 gap-4 overflow-hidden p-4",
    conversationCollapsed && inspectorCollapsed && "lg:grid-cols-[64px_1fr] xl:grid-cols-[64px_1fr_64px]",
    conversationCollapsed && !inspectorCollapsed && "lg:grid-cols-[64px_1fr] xl:grid-cols-[64px_1fr_300px]",
    !conversationCollapsed && inspectorCollapsed && "lg:grid-cols-[280px_1fr] xl:grid-cols-[280px_1fr_64px]",
    !conversationCollapsed && !inspectorCollapsed && "lg:grid-cols-[280px_1fr] xl:grid-cols-[280px_1fr_300px]",
  );

  return (
    <>
    <div className={layoutClass}>
      <ConversationPanel
        conversations={conversations}
        selectedId={selectedConversationId}
        collapsed={conversationCollapsed}
        onToggle={() => setConversationCollapsed((value) => !value)}
        onNew={startNew}
        onSelect={(id) => void selectConversation(id)}
        onRename={openRenameDialog}
        onDelete={(id) => {
          if (id === selectedConversationId) startNew();
          deleteMutation.mutate(id);
        }}
      />

      <section className="flex min-h-0 min-w-0 flex-col overflow-hidden rounded-3xl border border-white/80 bg-white/60 shadow-[0_18px_46px_rgba(83,101,132,0.10)] backdrop-blur">
        <header className="border-b border-slate-200/70 px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex h-9 overflow-hidden rounded-xl border border-slate-200 bg-white/70 p-0.5 shadow-sm">
              {CHAT_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => switchMode(mode.id)}
                  className={cn(
                    "px-3 text-xs font-semibold transition",
                    selectedChatMode === mode.id
                      ? "brand-gradient rounded-[10px] text-white shadow-[0_8px_18px_rgba(79,70,229,0.28)]"
                      : "text-slate-500 hover:text-slate-800",
                  )}
                >
                  {mode.label}
                </button>
              ))}
            </div>

            <Picker
              refNode={agentPickerRef}
              open={showAgentPicker}
              setOpen={setShowAgentPicker}
              icon={<Bot size={15} className="text-[#4f46e5]" />}
              label={selectedAgent?.name ?? "选择 Agent"}
              width="w-80"
            >
              <PickerTitle>Agent</PickerTitle>
              {modeAgents.length === 0 ? (
                <div className="px-3.5 py-4 text-sm text-slate-400">当前类别下还没有 Agent</div>
              ) : null}
              {modeAgents.map((agent) => (
                <PickerItem
                  key={agent.id}
                  active={runtimeAgentId === agent.id}
                  onClick={() => {
                    setSelectedAgentId(agent.id);
                    if (agent.reasoning_mode) setReasoningMode(agent.reasoning_mode);
                    setShowAgentPicker(false);
                  }}
                >
                  <Bot size={15} className="mt-0.5 shrink-0 text-[#4f46e5]" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{agent.name}</span>
                    <span className="block truncate text-xs text-slate-500">{agent.description || agent.base_type}</span>
                  </span>
                </PickerItem>
              ))}
            </Picker>

            <Picker
              refNode={modelPickerRef}
              open={showModelPicker}
              setOpen={setShowModelPicker}
              icon={<Zap size={15} className="text-amber-500" />}
              label={effectiveSelectedModelName ? (selectedModel ? modelLabel(selectedModel) : effectiveSelectedModelName) : "Agent 默认模型"}
              width="w-96"
            >
              <PickerTitle>模型</PickerTitle>
              <PickerItem
                active={!selectedModelName}
                onClick={() => {
                  setSelectedModelName("");
                  setModelSearch("");
                  setShowModelPicker(false);
                }}
              >
                <span className="w-20 shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-center text-[10px] font-bold uppercase text-slate-500">
                  DEFAULT
                </span>
                <span className="min-w-0 flex-1 truncate text-sm">
                  Agent 默认模型{selectedAgent?.model_name ? `：${selectedAgent.model_name}` : ""}
                </span>
              </PickerItem>
              <div className="sticky top-[37px] z-10 border-b border-slate-100 bg-white px-3 py-2">
                <label className="flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3">
                  <Search size={14} className="text-slate-400" />
                  <input
                    value={modelSearch}
                    onChange={(event) => setModelSearch(event.target.value)}
                    placeholder="搜索模型或供应商..."
                    className="min-w-0 flex-1 bg-transparent text-xs font-medium text-slate-700 outline-none placeholder:text-slate-400"
                  />
                  {modelSearch ? (
                    <button
                      type="button"
                      onClick={() => setModelSearch("")}
                      className="text-slate-400 hover:text-slate-700"
                      aria-label="清空模型搜索"
                    >
                      <X size={13} />
                    </button>
                  ) : null}
                </label>
              </div>
              {modelGroups.map((group) => (
                <div key={group.key} className="border-b border-slate-100 last:border-b-0">
                  <div className="sticky top-[91px] z-[9] flex items-center justify-between bg-slate-50/95 px-3.5 py-2 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
                    <span className="truncate">{group.label}</span>
                    <span>{group.models.length}</span>
                  </div>
                  {group.models.map((model) => (
                    <PickerItem
                      key={model.name}
                      active={selectedModelName === model.name}
                      onClick={() => {
                        setSelectedModelName(model.name);
                        setModelSearch("");
                        setShowModelPicker(false);
                      }}
                    >
                      <span className="w-20 shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-center text-[10px] font-bold uppercase text-slate-500">
                        {model.source === "db" ? "DB" : model.provider}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{modelLabel(model)}</span>
                        <span className="mt-0.5 block truncate font-mono text-[11px] text-slate-400">{model.model || model.name}</span>
                      </span>
                    </PickerItem>
                  ))}
                </div>
              ))}
              {!modelGroups.length ? (
                <div className="px-4 py-8 text-center text-sm text-slate-400">没有匹配的模型</div>
              ) : null}
            </Picker>

            <div className="relative" ref={thinkingRef}>
              <ThinkingToggle
                mode={effectiveMode}
                supportedModes={supportedModes}
                open={showThinkingPicker}
                onOpenChange={setShowThinkingPicker}
                onModeChange={(mode) => {
                  setReasoningMode(mode);
                }}
              />
            </div>

            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowVoiceCall(true)}
                title="发起语音通话"
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-600 shadow-sm hover:bg-emerald-100"
              >
                <Phone size={14} />
                通话
              </button>
              <button
                type="button"
                onClick={() => setShowWiki(true)}
                disabled={messages.length === 0}
                title="把当前对话沉淀为 Wiki 知识页面"
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-3 text-xs font-semibold text-indigo-600 shadow-sm hover:bg-indigo-100 disabled:opacity-40"
              >
                <BookOpen size={14} />
                沉淀 Wiki
              </button>
              <button
                type="button"
                onClick={() =>
                  setChatWidth((prev) => CHAT_WIDTH_ORDER[(CHAT_WIDTH_ORDER.indexOf(prev) + 1) % CHAT_WIDTH_ORDER.length])
                }
                title={`对话宽度：${CHAT_WIDTH_LABEL[chatWidth]}（点击切换）`}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl border border-slate-200 bg-white/80 px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-white"
              >
                <Maximize2 size={14} />
                {CHAT_WIDTH_LABEL[chatWidth]}
              </button>
              <button
                type="button"
                onClick={() => setChatDensity((prev) => (prev === "compact" ? "comfortable" : "compact"))}
                title={chatDensity === "compact" ? "当前：紧凑（点击切回舒适）" : "当前：舒适（点击切到紧凑）"}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-xl border px-3 text-xs font-semibold shadow-sm",
                  chatDensity === "compact"
                    ? "border-indigo-200 bg-indigo-50 text-indigo-600 hover:bg-indigo-100"
                    : "border-slate-200 bg-white/80 text-slate-700 hover:bg-white",
                )}
              >
                <SlidersHorizontal size={14} />
                {chatDensity === "compact" ? "紧凑" : "舒适"}
              </button>
              <button
                type="button"
                onClick={startNew}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-3.5 text-xs font-semibold text-slate-700 shadow-sm hover:bg-white"
              >
                <Plus size={14} />
                新对话
              </button>
            </div>
          </div>
        </header>

        <div
          ref={chatScrollRef}
          onScroll={() => {
            const el = chatScrollRef.current;
            if (!el) return;
            shouldAutoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96;
          }}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {messages.length === 0 ? (
            <EmptyState
              agents={agents.length}
              models={models.length}
              kbs={kbs.length}
              skills={skills.length}
              mcp={mcpServers.length}
              onStarter={(prompt) => void send(prompt)}
            />
          ) : (
            <div className={cn("mx-auto px-5 py-5", CHAT_WIDTH_CLASS[chatWidth], chatDensity === "compact" && "chat-compact")}>
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              <div ref={bottomRef} className="h-4" />
            </div>
          )}
        </div>

        <footer className="border-t border-slate-200/70 bg-white/55 px-5 py-4">
          <div className={cn("mx-auto", CHAT_WIDTH_CLASS[chatWidth])}>
            <div className="mb-2 flex items-center justify-end">
              <ProfilePicker
                refNode={profilePickerRef}
                open={showProfilePicker}
                profiles={profiles}
                selectedProfile={selectedProfile}
                onOpenChange={setShowProfilePicker}
                onSelect={(profileId) => {
                  setSelectedProfileId(profileId);
                  setShowProfilePicker(false);
                }}
                onCreate={() => {
                  const next = {
                    ...defaultProfile(),
                    id: `profile-${Date.now()}`,
                    name: `新配置 ${profiles.length + 1}`,
                    useAgentDefaults: false,
                  };
                  setProfiles((prev) => [...prev, next]);
                  setSelectedProfileId(next.id);
                  setShowProfilePicker(false);
                }}
                onRename={openProfileRenameDialog}
                onDelete={deleteProfile}
              />
            </div>
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={() => void send()}
              onStop={() => streamAbortRef.current?.abort("user-stop")}
              isStreaming={isStreaming}
            />
          </div>
        </footer>
      </section>

      <Inspector
        agent={selectedAgent}
        collapsed={inspectorCollapsed}
        onToggle={() => setInspectorCollapsed((value) => !value)}
        profile={selectedProfile}
        agents={agents}
        models={models}
        tools={tools}
        kbs={kbs}
        mcpServers={mcpServers}
        skills={skills}
        onProfileChange={updateSelectedProfile}
      />
    </div>
    <RenameDialog
      open={!!renameTarget}
      title={renameTitle}
      saving={renameSaving}
      onTitleChange={setRenameTitle}
      onCancel={closeRenameDialog}
      onSubmit={() => void submitRename()}
    />
    <RenameDialog
      open={!!profileRenameTarget}
      title={profileRenameTitle}
      saving={false}
      eyebrow="Chat Profile"
      heading="重命名配置"
      description="给配置文件设置一个更容易识别的名称。"
      inputLabel="配置名称"
      placeholder="输入新的配置名称"
      onTitleChange={setProfileRenameTitle}
      onCancel={closeProfileRenameDialog}
      onSubmit={submitProfileRename}
    />
    {showVoiceCall ? (
      <VoiceCallOverlay
        onClose={() => setShowVoiceCall(false)}
        agent={runtimeAgentId}
        threadId={threadId}
        model={effectiveSelectedModelName || undefined}
      />
    ) : null}
    <WikiModal
      open={showWiki}
      onClose={() => setShowWiki(false)}
      threadId={threadId}
      kbs={kbs}
      model={effectiveSelectedModelName || undefined}
    />
    </>
  );
}

function ConversationPanel({
  conversations,
  selectedId,
  collapsed,
  onToggle,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: {
  conversations: Conversation[];
  selectedId?: string;
  collapsed: boolean;
  onToggle: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRename: (conversation: Conversation) => void;
  onDelete: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = conversations.filter((item) =>
    `${item.title} ${item.agent_name} ${item.last_message ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  );

  if (collapsed) {
    return (
      <aside className="hidden min-h-0 flex-col items-center overflow-hidden rounded-3xl border border-white/80 bg-white/64 py-4 shadow-[0_18px_46px_rgba(83,101,132,0.10)] backdrop-blur lg:flex">
        <button
          type="button"
          onClick={onToggle}
          className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#eef2ff] text-[#4f46e5] hover:bg-[#e0e7ff]"
          title="展开对话记录"
          aria-label="展开对话记录"
        >
          <PanelLeftOpen size={18} />
        </button>
        <div className="mt-5 flex min-h-0 flex-1 flex-col items-center gap-3">
          <History size={18} className="text-slate-400" />
          <span className="rounded-full bg-white/80 px-2 py-1 text-[11px] font-semibold text-slate-500 shadow-sm">
            {conversations.length}
          </span>
        </div>
        <button
          type="button"
          onClick={onNew}
          className="mt-4 flex h-10 w-10 items-center justify-center rounded-2xl border border-slate-200 bg-white/80 text-slate-600 hover:bg-white"
          title="新对话"
          aria-label="新对话"
        >
          <Plus size={16} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="hidden min-h-0 flex-col overflow-hidden rounded-3xl border border-white/80 bg-white/64 shadow-[0_18px_46px_rgba(83,101,132,0.10)] backdrop-blur lg:flex">
      <div className="border-b border-slate-200/70 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <History size={15} className="text-slate-400" />
            对话记录
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onToggle}
              className="flex h-8 w-8 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 hover:text-slate-800"
              title="折叠对话记录"
              aria-label="折叠对话记录"
            >
              <PanelLeftClose size={14} />
            </button>
            <button
              type="button"
              onClick={onNew}
              className="flex h-8 w-8 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 hover:text-slate-800"
              title="新对话"
              aria-label="新对话"
            >
              <Plus size={13} />
            </button>
          </div>
        </div>
        <div className="mt-3 flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white/75 px-3">
          <Search size={13} className="shrink-0 text-slate-400" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索对话"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
        </div>
      </div>

      <div className="no-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {filtered.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white/55 p-5 text-center text-sm leading-6 text-slate-400">
            {query ? "没有匹配的对话" : "发送第一条消息后，对话会自动保存在这里。"}
          </div>
        ) : (
          filtered.map((conversation) => (
            <div
              key={conversation.id}
              className={cn(
                "group flex items-start gap-1 rounded-2xl border pr-1 transition",
                selectedId === conversation.id
                  ? "border-[#c7d2fe] bg-[#eef2ff] shadow-sm"
                  : "border-transparent hover:border-slate-200 hover:bg-white/70",
              )}
            >
              <button type="button" onClick={() => onSelect(conversation.id)} className="min-w-0 flex-1 px-3 py-3 text-left">
                <span className="block truncate text-sm font-semibold text-slate-800">
                  {conversation.title || "未命名对话"}
                </span>
                <span className="mt-1 block truncate text-xs text-slate-500">
                  {conversation.last_message || conversation.agent_name}
                </span>
                <span className="mt-2 block text-[10px] text-slate-400">{conversation.message_count} 条消息</span>
              </button>
              <div className="mt-2 hidden shrink-0 gap-0.5 group-hover:flex">
                <button
                  type="button"
                  onClick={() => onRename(conversation)}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:bg-white hover:text-slate-700"
                  title="重命名"
                >
                  <Pencil size={12} />
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(conversation.id)}
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-500"
                  title="删除"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

function EmptyState({
  agents,
  models,
  kbs,
  skills,
  mcp,
  onStarter,
}: {
  agents: number;
  models: number;
  kbs: number;
  skills: number;
  mcp: number;
  onStarter: (prompt: string) => void;
}) {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 px-5 py-6">
      <div className="rounded-3xl border border-white/80 bg-white/72 p-6 shadow-[0_18px_46px_rgba(83,101,132,0.10)]">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#4f46e5]">Agent Workbench</p>
        <div className="mt-3 grid gap-6 lg:grid-cols-[1fr_320px]">
          <div>
            <h1 className="max-w-2xl text-2xl font-bold text-slate-900 md:text-3xl">
              从一个目标开始，串起规划、知识检索、工具执行和结果交付。
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">
              选择模型与 Agent，按任务复杂度切换思考模式，让 NexAgent 在知识库、MCP、Skills 和沙盒工具之间协同完成任务。
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Link
                href="/creator"
                className="brand-gradient inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(79,70,229,0.32)] hover:brightness-[1.06]"
              >
                <Sparkles size={15} />
                AI 创建工具
              </Link>
              <Link
                href="/agents"
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 text-sm font-semibold text-slate-700 hover:bg-white"
              >
                <Bot size={15} />
                配置 Agent
              </Link>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2.5 lg:grid-cols-2">
            <Stat label="Agents" value={agents} icon={Bot} />
            <Stat label="模型" value={models} icon={Zap} />
            <Stat label="知识库" value={kbs} icon={Database} />
            <Stat label="Skills" value={skills} icon={Wrench} />
            <Stat label="MCP" value={mcp} icon={MessageSquare} />
            <Stat label="模式" value="4" icon={Brain} />
          </div>
        </div>
      </div>

      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">快速开始</p>
        <div className="grid gap-3 md:grid-cols-3">
          {STARTERS.map(({ title, desc, prompt, icon: Icon }) => (
            <button
              key={title}
              type="button"
              onClick={() => onStarter(prompt)}
              className="group rounded-2xl border border-white/80 bg-white/76 p-5 text-left shadow-[0_12px_28px_rgba(83,101,132,0.09)] transition hover:-translate-y-0.5 hover:bg-white hover:shadow-[0_18px_42px_rgba(83,101,132,0.14)]"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#eef2ff] text-[#4f46e5]">
                <Icon size={18} />
              </div>
              <h2 className="mt-4 text-sm font-semibold text-slate-900">{title}</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">{desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Inspector({
  agent,
  collapsed,
  onToggle,
  profile,
  agents,
  models,
  tools,
  kbs,
  mcpServers,
  skills,
  onProfileChange,
}: {
  agent?: AgentConfig;
  collapsed: boolean;
  onToggle: () => void;
  profile: ChatProfile;
  agents: AgentConfig[];
  models: Model[];
  tools: ToolInfo[];
  kbs: KBMeta[];
  mcpServers: MCPServer[];
  skills: SkillInfo[];
  onProfileChange: (patch: Partial<ChatProfile>) => void;
}) {
  const [activeSection, setActiveSection] = useState<ResourceSection | null>(null);
  const selectedTools = profile.tools.filter((item) => item !== "delegate_subagents").length;
  const subagentLabel = !profile.allowSubagents
    ? "关闭"
    : profile.allowedAgentIds.length > 0
      ? `${profile.allowedAgentIds.length} 个`
      : "全部";
  const subagentModelLabel = subagentModelStrategyLabel(profile.subagentModelStrategy, profile.subagentModel, models);

  if (collapsed) {
    return (
      <aside className="hidden min-h-0 flex-col items-center overflow-hidden rounded-3xl border border-white/80 bg-white/64 py-4 shadow-[0_18px_46px_rgba(83,101,132,0.10)] backdrop-blur xl:flex">
        <button
          type="button"
          onClick={onToggle}
          className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[#eef2ff] text-[#4f46e5] hover:bg-[#e0e7ff]"
          title="展开模型能力"
          aria-label="展开模型能力"
        >
          <PanelRightOpen size={18} />
        </button>
        <div className="mt-5 flex min-h-0 flex-1 flex-col items-center gap-3">
          <SlidersHorizontal size={18} className="text-slate-400" />
          <Zap size={18} className="text-slate-400" />
          <Database size={18} className="text-slate-400" />
        </div>
      </aside>
    );
  }

  return (
    <aside className="hidden min-h-0 flex-col overflow-hidden rounded-3xl border border-white/80 bg-white/64 shadow-[0_18px_46px_rgba(83,101,132,0.10)] backdrop-blur xl:flex">
      <div className="border-b border-slate-200/70 p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-[#4f46e5]">Chat Profile</p>
            <h2 className="mt-3 text-xl font-bold leading-tight text-slate-900">{profile.name}</h2>
          </div>
          <button
            type="button"
            onClick={onToggle}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 hover:text-slate-800"
            title="折叠模型能力"
            aria-label="折叠模型能力"
          >
            <PanelRightClose size={14} />
          </button>
        </div>
        <p className="mt-3 text-sm leading-7 text-slate-500">
          当前对话使用 {agent?.name ?? "当前 Agent"}。这里只管理运行资源，Agent 与模型在顶部选择。
        </p>
      </div>
      <div className="no-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <ConfigBlock
          title="配置作用方式"
          description="默认不覆盖 Agent 自己的资源配置；切换为自定义后才发送右侧选择项。"
          className="p-5"
        >
          <ConfigOption
            label="按 Agent 默认配置"
            description="使用 Agent 保存的工具、知识库、MCP、Skills 和子 Agent 设置"
            active={profile.useAgentDefaults}
            onClick={() => onProfileChange({ useAgentDefaults: true })}
          />
          <ConfigOption
            label="自定义本次运行资源"
            description="用当前配置文件覆盖 Agent 默认资源"
            active={!profile.useAgentDefaults}
            onClick={() => onProfileChange({ useAgentDefaults: false })}
          />
        </ConfigBlock>

        <ConfigBlock
          title="资源配置"
          description={profile.useAgentDefaults ? "当前正在使用 Agent 默认配置，切换为自定义后可选择资源。" : "点击条目在二级窗口中选择，右侧保持紧凑。"}
          disabled={profile.useAgentDefaults}
        >
          <ConfigSummaryItem
            label="内置工具"
            value={profile.useAgentDefaults ? "Agent 默认" : `${selectedTools} 个`}
            disabled={profile.useAgentDefaults}
            onClick={() => setActiveSection("tools")}
          />
          <ConfigSummaryItem
            label="RAG 知识库"
            value={profile.useAgentDefaults ? "Agent 默认" : `${profile.kbIds.length} 个`}
            disabled={profile.useAgentDefaults}
            onClick={() => setActiveSection("knowledge")}
          />
          <ConfigSummaryItem
            label="MCP 服务器"
            value={profile.useAgentDefaults ? "Agent 默认" : `${profile.mcpIds.length} 个`}
            disabled={profile.useAgentDefaults}
            onClick={() => setActiveSection("mcp")}
          />
          <ConfigSummaryItem
            label="Skills"
            value={profile.useAgentDefaults ? "Agent 默认" : `${profile.skillIds.length} 个`}
            disabled={profile.useAgentDefaults}
            onClick={() => setActiveSection("skills")}
          />
          <ConfigSummaryItem
            label="可调用 Agent"
            value={profile.useAgentDefaults ? "Agent 默认" : `${subagentLabel} · ${subagentModelLabel}`}
            disabled={profile.useAgentDefaults}
            onClick={() => setActiveSection("subagents")}
          />
        </ConfigBlock>
      </div>
      <ResourcePickerDialog
        section={activeSection}
        profile={profile}
        agents={agents}
        models={models}
        tools={tools}
        kbs={kbs}
        mcpServers={mcpServers}
        skills={skills}
        onClose={() => setActiveSection(null)}
        onProfileChange={onProfileChange}
      />
    </aside>
  );
}

function ConfigSummaryItem({
  label,
  value,
  disabled,
  onClick,
}: {
  label: string;
  value: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left transition",
        disabled
          ? "cursor-not-allowed border-slate-200/70 bg-slate-50/70 text-slate-400 opacity-70"
          : "border-slate-200 bg-white/80 hover:bg-white",
      )}
    >
      <span className={cn("text-sm font-semibold", disabled ? "text-slate-400" : "text-slate-800")}>{label}</span>
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500">
        {value}
        <ChevronDown size={13} className={cn("-rotate-90", disabled ? "text-slate-300" : "text-slate-400")} />
      </span>
    </button>
  );
}

function ResourcePickerDialog({
  section,
  profile,
  agents,
  models,
  tools,
  kbs,
  mcpServers,
  skills,
  onClose,
  onProfileChange,
}: {
  section: ResourceSection | null;
  profile: ChatProfile;
  agents: AgentConfig[];
  models: Model[];
  tools: ToolInfo[];
  kbs: KBMeta[];
  mcpServers: MCPServer[];
  skills: SkillInfo[];
  onClose: () => void;
  onProfileChange: (patch: Partial<ChatProfile>) => void;
}) {
  const [subagentModelSearch, setSubagentModelSearch] = useState("");
  const [subagentModelPickerOpen, setSubagentModelPickerOpen] = useState(false);
  const filteredModels = useMemo(() => {
    const keyword = subagentModelSearch.trim().toLowerCase();
    if (!keyword) return models;
    return models.filter((model) =>
      [
        model.name,
        model.display_name,
        model.model,
        model.provider,
        model.provider_name,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }, [models, subagentModelSearch]);

  if (!section) return null;

  const titleMap: Record<ResourceSection, string> = {
    tools: "选择内置工具",
    knowledge: "选择 RAG 知识库",
    mcp: "选择 MCP 服务器",
    skills: "选择 Skills",
    subagents: "选择可调用 Agent",
  };
  const descriptionMap: Record<ResourceSection, string> = {
    tools: "这些工具会覆盖当前 Agent 的默认工具配置。",
    knowledge: "限制本次对话可检索的知识库范围。",
    mcp: "选择本次对话可使用的 MCP 扩展服务。",
    skills: "选择注入到本次对话的技能能力。",
    subagents: "控制当前 Agent 是否能并行委托其他 Agent。",
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/18 p-4 backdrop-blur-sm">
      <button type="button" className="absolute inset-0 cursor-default" aria-label="关闭资源选择" onClick={onClose} />
      <section className="relative z-10 flex h-full w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/80 bg-white/95 shadow-[0_30px_90px_rgba(39,56,87,0.24)] animate-slide-down">
        <div className="border-b border-slate-100 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-[#4f46e5]">Resource Picker</p>
              <h2 className="mt-2 text-base font-bold text-slate-900">{titleMap[section]}</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500">{descriptionMap[section]}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-500 hover:text-slate-800"
              aria-label="关闭"
            >
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="no-scrollbar min-h-0 flex-1 space-y-1.5 overflow-y-auto p-4">
          {section === "tools"
            ? tools.filter((item) => item.name !== "delegate_subagents").map((item) => (
                <ConfigOption
                  key={`tool:${item.name}`}
                  label={item.name}
                  description={item.description}
                  active={profile.tools.includes(item.name)}
                  compact
                  onClick={() => onProfileChange({ useAgentDefaults: false, tools: toggleValue(profile.tools, item.name) })}
                />
              ))
            : null}
          {section === "knowledge"
            ? kbs.map((item) => (
                <ConfigOption
                  key={`kb:${item.kb_id}`}
                  label={item.name}
                  description={item.kb_type}
                  active={profile.kbIds.includes(item.kb_id)}
                  compact
                  onClick={() => onProfileChange({ useAgentDefaults: false, kbIds: toggleValue(profile.kbIds, item.kb_id) })}
                />
              ))
            : null}
          {section === "mcp"
            ? mcpServers.map((item) => (
                <ConfigOption
                  key={`mcp:${item.id}`}
                  label={item.name}
                  description={item.transport}
                  active={profile.mcpIds.includes(item.id)}
                  compact
                  onClick={() => onProfileChange({ useAgentDefaults: false, mcpIds: toggleValue(profile.mcpIds, item.id) })}
                />
              ))
            : null}
          {section === "skills"
            ? skills.map((item) => (
                <ConfigOption
                  key={`skill:${item.name}`}
                  label={item.name}
                  description={item.description}
                  active={profile.skillIds.includes(item.name)}
                  compact
                  onClick={() => onProfileChange({ useAgentDefaults: false, skillIds: toggleValue(profile.skillIds, item.name) })}
                />
              ))
            : null}
          {section === "subagents" ? (
            <>
              <ConfigOption
                label="允许调用其他 Agent"
                description="启用 delegate_subagents 编排工具"
                active={profile.allowSubagents}
                compact
                onClick={() => onProfileChange({ useAgentDefaults: false, allowSubagents: !profile.allowSubagents })}
              />
              {profile.allowSubagents ? (
                <>
                  <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-bold text-slate-900">子 Agent 模型</p>
                        <p className="mt-0.5 text-[11px] leading-4 text-slate-400">控制委派任务使用的模型</p>
                      </div>
                      <span className="shrink-0 rounded-full bg-[#eef2ff] px-2.5 py-1 text-[10px] font-bold text-[#4f46e5]">
                        {profile.subagentModelStrategy === "custom" ? "指定" : profile.subagentModelStrategy === "main_agent" ? "跟随" : "默认"}
                      </span>
                    </div>
                    <div className="mt-3 space-y-2">
                      {[
                        ["main_agent", "与主 Agent 一致", "跟随顶部模型"],
                        ["agent_default", "使用子 Agent 默认模型", "使用各自配置"],
                        ["custom", "手动指定模型", "统一指定模型"],
                      ].map(([strategy, label, description]) => (
                        <button
                          key={strategy}
                          type="button"
                          onClick={() =>
                            onProfileChange({
                              useAgentDefaults: false,
                              subagentModelStrategy: strategy as SubAgentModelStrategy,
                              subagentModel: strategy === "custom" ? profile.subagentModel || models[0]?.name || "" : "",
                            })
                          }
                          className={cn(
                            "flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left transition",
                            profile.subagentModelStrategy === strategy
                              ? "border-[#a5b4fc] bg-[#eef2ff] text-[#3730a3]"
                              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
                          )}
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-[13px] font-bold leading-5">{label}</span>
                            <span className="block truncate text-[11px] leading-4 text-slate-400">{description}</span>
                          </span>
                          <span
                            className={cn(
                              "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                              profile.subagentModelStrategy === strategy
                                ? "border-[#a5b4fc] bg-white text-[#4f46e5]"
                                : "border-slate-200 text-slate-300",
                            )}
                          >
                            {profile.subagentModelStrategy === strategy ? <Check size={12} /> : null}
                          </span>
                        </button>
                      ))}
                    </div>
                    {profile.subagentModelStrategy === "custom" ? (
                      <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/70 p-2">
                        <button
                          type="button"
                          onClick={() => setSubagentModelPickerOpen((value) => !value)}
                          className="flex h-9 w-full items-center justify-between gap-2 rounded-lg bg-white px-3 text-left text-[13px] font-bold text-slate-800 shadow-sm transition hover:bg-slate-50"
                        >
                          <span className="min-w-0 truncate">
                            {subagentModelStrategyLabel(profile.subagentModelStrategy, profile.subagentModel, models)}
                          </span>
                          <ChevronDown
                            size={14}
                            className={cn("shrink-0 text-slate-400 transition", subagentModelPickerOpen && "rotate-180")}
                          />
                        </button>
                        {subagentModelPickerOpen ? (
                          <div className="mt-2 animate-slide-down">
                            <div className="relative">
                              <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                              <input
                                value={subagentModelSearch}
                                onChange={(event) => setSubagentModelSearch(event.target.value)}
                                placeholder="搜索模型或供应商"
                                className="h-9 w-full rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-xs font-semibold text-slate-700 outline-none transition focus:border-[#a5b4fc] focus:ring-4 focus:ring-[#4f46e5]/10"
                              />
                            </div>
                            <div className="mt-2 max-h-44 space-y-1 overflow-y-auto pr-1">
                              {filteredModels.map((model, index) => {
                                const active = profile.subagentModel === model.name;
                                return (
                                  <button
                                    key={`${model.source ?? "config"}:${model.provider_id ?? model.provider}:${model.name}:${index}`}
                                    type="button"
                                    onClick={() => {
                                      onProfileChange({
                                        useAgentDefaults: false,
                                        subagentModelStrategy: "custom",
                                        subagentModel: model.name,
                                      });
                                      setSubagentModelPickerOpen(false);
                                    }}
                                    className={cn(
                                      "flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left transition",
                                      active ? "bg-[#eef2ff] text-[#3730a3]" : "text-slate-700 hover:bg-white",
                                    )}
                                  >
                                    <span className="min-w-0">
                                      <span className="block truncate text-xs font-bold">{modelLabel(model)}</span>
                                      <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">
                                        {model.model || model.name}
                                      </span>
                                    </span>
                                    {active ? <Check size={14} className="shrink-0" /> : null}
                                  </button>
                                );
                              })}
                              {!filteredModels.length ? (
                                <div className="rounded-lg border border-dashed border-slate-200 bg-white px-3 py-4 text-center text-xs text-slate-400">
                                  没有匹配的模型
                                </div>
                              ) : null}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                  <p className="px-1 pt-2 text-xs leading-5 text-slate-400">不选择时表示允许调用全部 Agent。</p>
                  {agents.map((item) => (
                    <ConfigOption
                      key={`agent:${item.id}`}
                      label={item.name}
                      description={`${item.base_type}${item.is_builtin ? " · 内置" : ""}`}
                      active={profile.allowedAgentIds.includes(item.id)}
                      compact
                      onClick={() =>
                        onProfileChange({
                          useAgentDefaults: false,
                          allowedAgentIds: toggleValue(profile.allowedAgentIds, item.id),
                        })
                      }
                    />
                  ))}
                </>
              ) : null}
            </>
          ) : null}
        </div>
        <div className="border-t border-slate-100 bg-slate-50/72 p-4">
          <button
            type="button"
            onClick={onClose}
            className="h-10 w-full rounded-xl bg-[#4f46e5] text-sm font-semibold text-white shadow-[0_10px_22px_rgba(79,70,229,0.22)] hover:bg-[#4338ca]"
          >
            完成
          </button>
        </div>
      </section>
    </div>
  );
}

function ProfilePicker({
  refNode,
  open,
  profiles,
  selectedProfile,
  onOpenChange,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: {
  refNode: React.RefObject<HTMLDivElement | null>;
  open: boolean;
  profiles: ChatProfile[];
  selectedProfile: ChatProfile;
  onOpenChange: (open: boolean) => void;
  onSelect: (profileId: string) => void;
  onCreate: () => void;
  onRename: (profile: ChatProfile) => void;
  onDelete: (profileId: string) => void;
}) {
  return (
    <div className="relative" ref={refNode}>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="inline-flex h-8 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-white"
      >
        <SlidersHorizontal size={13} className="text-slate-500" />
        {selectedProfile.name}
        <ChevronDown size={12} className="text-slate-400" />
      </button>
      {open ? (
        <div
          className="absolute bottom-full right-0 z-40 mb-2 w-56 overflow-hidden rounded-2xl border border-slate-200 bg-white animate-slide-down"
          style={{ boxShadow: "var(--shadow-picker)" }}
        >
          <div className="border-b border-slate-100 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
            配置文件
          </div>
          {profiles.map((profile) => (
            <div
              key={profile.id}
              className={cn(
                "flex items-center gap-1 px-2 py-1.5",
                profile.id === selectedProfile.id && "bg-[#eef2ff] text-[#3730a3]",
              )}
            >
              <button
                type="button"
                onClick={() => onSelect(profile.id)}
                className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-xl px-2 py-1.5 text-left text-sm hover:bg-white/70"
              >
                <span className="truncate font-semibold">{profile.name}</span>
                {profile.id === selectedProfile.id ? <Check size={14} className="shrink-0" /> : null}
              </button>
              <button
                type="button"
                onClick={() => onRename(profile)}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-white hover:text-slate-700"
                title="重命名配置"
                aria-label="重命名配置"
              >
                <Pencil size={12} />
              </button>
              <button
                type="button"
                onClick={() => onDelete(profile.id)}
                disabled={profile.id === "default"}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-500 disabled:cursor-not-allowed disabled:opacity-35 disabled:hover:bg-transparent disabled:hover:text-slate-400"
                title={profile.id === "default" ? "默认配置不能删除" : "删除配置"}
                aria-label={profile.id === "default" ? "默认配置不能删除" : "删除配置"}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={onCreate}
            className="flex w-full items-center gap-2 border-t border-slate-100 px-3 py-2.5 text-left text-sm font-semibold text-slate-600 hover:bg-slate-50"
          >
            <Plus size={14} />
            新建配置
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ConfigBlock({
  title,
  description,
  children,
  className,
  disabled,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-white/80 bg-white/74 p-4 shadow-sm transition",
        disabled && "bg-slate-50/62 opacity-75",
        className,
      )}
    >
      <h3 className={cn("text-sm font-bold", disabled ? "text-slate-500" : "text-slate-900")}>{title}</h3>
      <p className={cn("mt-1 text-xs leading-5", disabled ? "text-slate-400" : "text-slate-500")}>{description}</p>
      <div className="mt-3 space-y-2">{children}</div>
    </section>
  );
}

function ConfigOption({
  label,
  description,
  active,
  disabled,
  compact,
  onClick,
}: {
  label: string;
  description?: string;
  active: boolean;
  disabled?: boolean;
  compact?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-xl border px-3 text-left transition",
        compact ? "py-2" : "py-2.5",
        active ? "border-[#a5b4fc] bg-[#eef2ff] text-[#3730a3]" : "border-slate-200 bg-white/80 text-slate-700 hover:bg-white",
        disabled && "cursor-not-allowed opacity-55 hover:bg-white/80",
      )}
    >
      <span className="min-w-0">
        <span className={cn("block truncate font-semibold", compact ? "text-xs" : "text-sm")}>{label}</span>
        {description ? (
          <span className={cn("mt-0.5 block truncate text-slate-400", compact ? "text-[11px]" : "text-xs")}>
            {description}
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-lg border",
          compact ? "h-5 w-5" : "h-6 w-6",
          active ? "border-[#a5b4fc] bg-white text-[#4f46e5]" : "border-slate-200 text-slate-300",
        )}
      >
        {active ? <Check size={compact ? 11 : 13} /> : <Plus size={compact ? 11 : 13} />}
      </span>
    </button>
  );
}

function Picker({
  refNode,
  open,
  setOpen,
  icon,
  label,
  width,
  children,
}: {
  refNode: React.RefObject<HTMLDivElement | null>;
  open: boolean;
  setOpen: (value: boolean) => void;
  icon: React.ReactNode;
  label: string;
  width: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative" ref={refNode}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex h-9 max-w-72 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-white"
      >
        {icon}
        <span className="truncate">{label}</span>
        <ChevronDown size={12} className="shrink-0 text-slate-400" />
      </button>
      {open && (
        <div
          className={cn("no-scrollbar absolute left-0 top-full z-40 mt-2 max-h-80 overflow-y-auto rounded-2xl border border-slate-200 bg-white animate-slide-down", width)}
          style={{ boxShadow: "var(--shadow-picker)" }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

function PickerTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="sticky top-0 border-b border-slate-100 bg-white px-3.5 py-2.5 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
      {children}
    </div>
  );
}

function PickerItem({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-3 px-3.5 py-2.5 text-left transition",
        active ? "bg-[#eef2ff] text-[#3730a3]" : "hover:bg-slate-50",
      )}
    >
      {children}
    </button>
  );
}

function Stat({ label, value, icon: Icon }: { label: string; value: string | number; icon: typeof Bot }) {
  return (
    <div className="rounded-2xl border border-slate-200/70 bg-white/70 p-3">
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[#eef2ff] text-[#4f46e5]">
          <Icon size={13} />
        </div>
        <span className="text-xs font-medium text-slate-500">{label}</span>
      </div>
      <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
    </div>
  );
}

function RenameDialog({
  open,
  title,
  saving,
  eyebrow = "Conversation",
  heading = "重命名对话",
  description = "给当前对话设置一个更容易识别的名称。",
  inputLabel = "对话名称",
  placeholder = "输入新的对话名称",
  onTitleChange,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  saving: boolean;
  eyebrow?: string;
  heading?: string;
  description?: string;
  inputLabel?: string;
  placeholder?: string;
  onTitleChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 80);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onCancel, open]);

  if (!open) return null;

  const canSubmit = !!title.trim() && !saving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-slate-950/24 backdrop-blur-sm"
        aria-label="关闭重命名弹窗"
        onClick={onCancel}
      />
      <form
        className="relative z-10 w-full max-w-lg overflow-hidden rounded-3xl border border-white/80 bg-white/92 shadow-[0_30px_90px_rgba(39,56,87,0.24)] backdrop-blur-xl animate-slide-down"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit) onSubmit();
        }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#4f46e5]">{eyebrow}</p>
            <h2 className="mt-2 text-lg font-bold text-slate-900">{heading}</h2>
            <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-slate-200 bg-white/80 text-slate-500 hover:bg-white hover:text-slate-800 disabled:opacity-50"
            aria-label="关闭"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-5">
          <label className="text-xs font-semibold text-slate-500" htmlFor="conversation-title">
            {inputLabel}
          </label>
          <input
            ref={inputRef}
            id="conversation-title"
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            maxLength={80}
            disabled={saving}
            className="mt-2 h-11 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-900 outline-none transition focus:border-[#a5b4fc] focus:ring-4 focus:ring-[#4f46e5]/10 disabled:opacity-60"
            placeholder={placeholder}
          />
          <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
            <span>按 Enter 保存，Esc 取消</span>
            <span>{title.length}/80</span>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/72 px-6 py-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="inline-flex h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="brand-gradient inline-flex h-10 items-center justify-center gap-2 rounded-xl px-4 text-sm font-semibold text-white shadow-[0_10px_22px_rgba(79,70,229,0.3)] hover:brightness-[1.06] disabled:opacity-50"
          >
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            保存
          </button>
        </div>
      </form>
    </div>
  );
}

function toMessage(item: ConversationMessage): Message {
  return {
    id: item.id,
    role: item.role,
    content: item.content,
    toolName: item.tool_name ?? undefined,
    thinkingContent: item.reasoning_content ?? undefined,
  };
}

function shouldShowToolCall(tool?: string, input?: unknown) {
  if (!tool?.trim()) return false;
  if (input == null) return true;
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed || trimmed === "null" || trimmed === "undefined") return true;
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (parsed == null) return true;
    } catch {
      return true;
    }
  }
  return true;
}

function groupModelsByProvider(models: Model[], query: string) {
  const keyword = query.trim().toLowerCase();
  const groups = new Map<string, { key: string; label: string; models: Model[] }>();

  for (const model of models) {
    const label = model.provider_name || providerLabel(model.provider);
    const searchable = [
      model.name,
      model.display_name,
      model.model,
      model.provider,
      model.provider_name,
      model.source,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (keyword && !searchable.includes(keyword)) continue;

    const key = `${model.source ?? "config"}:${model.provider_id ?? model.provider ?? label}`;
    const group = groups.get(key) ?? { key, label, models: [] };
    group.models.push(model);
    groups.set(key, group);
  }

  return Array.from(groups.values()).sort((a, b) => {
    return a.label.localeCompare(b.label);
  });
}

function modelLabel(model: Model) {
  const label = model.display_name || model.model || model.name;
  return model.provider_name ? `${label} · ${model.provider_name}` : label;
}

function subagentModelStrategyLabel(strategy: SubAgentModelStrategy, modelName: string, models: Model[]) {
  if (strategy === "main_agent") return "跟随主模型";
  if (strategy === "custom") {
    const model = models.find((item) => item.name === modelName);
    return model ? modelLabel(model) : modelName || "未选模型";
  }
  return "子 Agent 默认";
}

function providerLabel(provider?: string) {
  if (!provider) return "其他供应商";
  if (provider === "openai") return "OpenAI 兼容";
  return provider;
}

function toggleValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function mergeSubagents(current: SubAgentRuntimeItem[], incoming: SubAgentRuntimeItem[]) {
  const map = new Map<string, SubAgentRuntimeItem>();
  const keyOf = (item: SubAgentRuntimeItem) => `${item.run_id ?? "legacy"}:${item.index}:${item.agent}:${item.task ?? ""}`;
  for (const item of current) map.set(keyOf(item), item);
  for (const item of incoming) map.set(keyOf(item), { ...map.get(keyOf(item)), ...item });
  return Array.from(map.values());
}
