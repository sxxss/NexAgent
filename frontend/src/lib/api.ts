// NexAgent API client — talks to the FastAPI backend.
// Defaults to the same-origin "/api" (Next.js rewrites in local dev). In Docker
// the browser can't reach the gateway via Next's proxy due to trailing-slash
// handling, so NEXT_PUBLIC_API_BASE points the client straight at the backend.
const BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

async function apiErrorMessage(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return `HTTP ${res.status}`;
  try {
    const error = JSON.parse(text);
    const detail = error.detail;
    if (typeof detail === "string") return detail;
    if (detail?.message) return detail.message;
    if (error.message) return error.message;
  } catch {
    return text;
  }
  return `HTTP ${res.status}`;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Model {
  name: string;
  display_name: string;
  provider: string;
  model?: string;
  base_url?: string;
  max_tokens?: number;
  supports_streaming?: boolean;
  api_key_configured?: boolean;
  is_default?: boolean;
  source?: "config" | "db";
  provider_id?: string;
  provider_name?: string;
  capabilities?: ModelCapabilities;
}

export type ReasoningMode = "fast" | "balanced" | "deep" | "ultra";
export type SubAgentModelStrategy = "main_agent" | "agent_default" | "custom";

export interface ModelCapabilities {
  input_modalities?: string[];
  output_modalities?: string[];
  supports_streaming?: boolean;
  supports_native_reasoning?: boolean;
  supported_reasoning_modes?: ReasoningMode[];
  reasoning_mode_reasons?: Record<ReasoningMode, string>;
}

export interface ChatRequest {
  message: string;
  thread_id?: string;
  user_id?: string;
  model?: string;
  agent?: string;
  tools?: string[];
  kb_ids?: string[];
  mcp_ids?: string[];
  skill_ids?: string[];
  allow_subagents?: boolean;
  allowed_agent_ids?: string[];
  subagent_model_strategy?: SubAgentModelStrategy;
  subagent_model?: string;
  thinking?: boolean;
  thinking_budget?: number;
  reasoning_mode?: ReasoningMode;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  reasoning_budget?: number;
  planning_enabled?: boolean;
}

export type StreamStatus =
  | "started" | "loading" | "tool_call" | "tool_result" | "state" | "finished" | "error" | "interrupted"
  | "heartbeat"
  | "thinking"
  | "plan" | "research_step" | "writing"
  | "subagent_started" | "subagent_progress" | "subagent_completed" | "subagent_failed";

export interface SubAgentRuntimeItem {
  run_id?: string;
  index: number;
  agent: string;
  runtime_agent?: string;
  task?: string;
  status: "queued" | "running" | "completed" | "failed" | "timed_out" | "cancelled" | string;
  response?: string;
  summary?: string;
  error?: string;
  latency_ms?: number;
  thread_id?: string;
  context?: {
    model?: string;
    tools?: string[];
    kb_ids?: string[];
    mcp_ids?: string[];
    skill_ids?: string[];
  };
}

export interface StreamChunk {
  request_id?: string;
  event_id?: string;
  seq?: number;
  status: StreamStatus;
  content?: string;
  phase?: "startup" | "reasoning" | "model" | "tool" | "planning" | "research" | "writing" | "artifact" | "subagent" | "done" | "error";
  tool?: string;
  tool_call_id?: string;
  input?: unknown;
  output?: unknown;
  success?: boolean;
  tool_status?: "started" | "completed" | "failed" | string;
  tool_elapsed_ms?: number;
  message?: string;
  idle_seconds?: number;
  agent?: string;
  model?: string;
  tools?: string[];
  kb_ids?: string[];
  mcp_ids?: string[];
  skill_ids?: string[];
  reasoning_mode?: ReasoningMode | string;
  thread_id?: string;
  elapsed_ms?: number;
  error_type?: string;
  error?: string;
  artifacts?: string[];
  new_artifacts?: string[];
  usage?: { input_tokens: number; output_tokens: number };
  steps?: PlanStep[];
  total?: number;
  step?: number;
  title?: string;
  run_id?: string;
  succeeded?: number;
  failed?: number;
  summary?: string;
  subagents?: SubAgentRuntimeItem[];
}

export interface ArtifactMeta {
  thread_id: string;
  path: string;
  name: string;
  size: number;
  mime_type: string;
  previewable: boolean;
  download_url: string;
  preview_url: string;
}

export interface ArtifactPreview extends ArtifactMeta {
  content: string;
  truncated: boolean;
}

export interface PlanStep {
  id: number;
  title: string;
  description: string;
}

export interface KBMeta {
  kb_id: string;
  name: string;
  kb_type: "milvus" | "lightrag" | "wiki";
  description: string;
  chunk_size: number;
  chunk_overlap: number;
  chunk_preset_id?: "general" | "qa" | "book" | "laws" | "paper";
  chunk_parser_config?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  embed_info: { model: string; dimension: number; base_url?: string };
  llm_info?: { provider?: string; model: string; base_url?: string };
  extra?: Record<string, unknown>;
}

export type WikiPageType = "source" | "entity" | "topic" | "synthesis" | "comparison" | "query" | "note";

export interface WikiPageSummary {
  id: string;
  title: string;
  type: WikiPageType;
  path: string;
  manual_edited: boolean;
  confidence: "EXTRACTED" | "INFERRED" | "AMBIGUOUS" | "UNVERIFIED" | string;
  updated_at?: string;
  sources: string[];
  excerpt: string;
  has_candidate?: boolean;
  status?: string;
}

export interface WikiPageDetail extends WikiPageSummary {
  content: string;
  frontmatter: Record<string, unknown>;
  candidate?: { frontmatter: Record<string, unknown>; content: string; created_at: string; reason?: string } | null;
}

export interface WikiGraphPayload {
  nodes: Array<{ id: string; label: string; type: string; sources: string[]; confidence: string; community: number }>;
  edges: Array<{ source: string; target: string; weight: number; signals: Record<string, unknown> }>;
  stats: Record<string, number>;
}

export interface WikiLintPayload {
  issues: Array<{
    id: string;
    type: string;
    page_id: string;
    severity: string;
    message: string;
    action?: string;
    repairable?: boolean;
    repair_action?: string;
    target?: string;
    source_file_id?: string;
  }>;
  summary: { issue_count?: number; page_count?: number };
  compile_status?: Record<string, unknown>;
}

export interface WikiRepairResult {
  repaired_count: number;
  candidate_count: number;
  skipped_issues: Array<{ id: string; reason: string }>;
  failed_issues: Array<{ id: string; error: string }>;
}

export interface FileMeta {
  file_id: string;
  kb_id: string;
  filename: string;
  file_size: number;
  status:
    | "uploaded"
    | "parsing"
    | "parsed"
    | "parse_error"
    | "indexing"
    | "indexed"
    | "index_error"
    | "graphing"
    | "graph_indexed"
    | "error_graphing"
    | "indexed_with_graph_degraded";
  parsed_path?: string;
  chunk_count: number;
  error: string;
  parse_metadata?: Record<string, unknown>;
  processing_params?: Record<string, unknown>;
  progress?: FileProgress;
  created_at: string;
  updated_at: string;
}

export interface FileProgress {
  percent: number;
  stage: string;
  label: string;
  next_action: "process" | "index" | "wait" | "search" | string;
  can_parse: boolean;
  can_index: boolean;
  can_process: boolean;
  is_running: boolean;
  is_error: boolean;
  is_complete: boolean;
}

export interface ParsedFilePreview {
  file: FileMeta;
  content: string;
  truncated: boolean;
  chars: number;
}

export interface TaskRecord {
  task_id: string;
  kind: string;
  status: "queued" | "running" | "completed" | "failed" | "interrupted" | "cancelled" | string;
  progress: number;
  current_step: string;
  completed_steps: number;
  total_steps: number;
  result: Record<string, unknown>;
  error: string;
  metadata: Record<string, unknown>;
  cancel_requested: boolean;
  created_at: number;
  updated_at: number;
}

export type IngestionJob = TaskRecord;

export interface EvidenceRef {
  id: string;
  kb_id?: string;
  file_id?: string;
  source: string;
  score: number;
  metadata: Record<string, unknown>;
  preview?: string;
}

export interface SearchResult {
  content: string;
  score: number;
  source: string;
  file_id: string;
  chunk_id?: string;
  chunk_index?: number;
  metadata: Record<string, unknown>;
  evidence?: EvidenceRef;
}

export interface SearchWarning {
  code: string;
  message: string;
  action?: string;
}

export interface SearchResponse {
  query: string;
  kb_id?: string;
  kb_ids?: string[];
  kb_type?: KBMeta["kb_type"];
  mode?: string;
  retrieval_config?: RetrievalConfig;
  results: SearchResult[];
  total: number;
  degraded?: boolean;
  warnings?: SearchWarning[];
  error_code?: string;
  message?: string;
  detail?: string;
  action?: string;
  fallback_source?: "local_index" | "parsed_chunks" | "none" | string;
}

export interface KnowledgeStatus {
  status: string;
  work_dir: string;
  backends: Record<string, Record<string, unknown>>;
  neo4j: Record<string, unknown>;
  total_knowledge_bases: number;
}

export interface GraphNode {
  id?: string;
  name: string;
  entity_type?: string;
  description?: string;
  count: number;
  files: string[];
  source_files?: string[];
  source_chunks?: string[];
}
export interface GraphEdge {
  id?: string;
  source: string;
  target: string;
  relation: string;
  keywords?: string[];
  weight?: number;
  description?: string;
  count: number;
  files: string[];
  source_files?: string[];
  source_chunks?: string[];
}
export interface KnowledgeGraph {
  kb_id: string; kb_type: "lightrag";
  nodes: GraphNode[]; edges: GraphEdge[];
  stats: { nodes: number; edges: number; files: string[] };
  warnings?: string[];
  degraded?: boolean;
  error_code?: string;
  graph_source?: string;
  diagnostics?: Record<string, unknown>;
}
export interface KnowledgeGraphSummary {
  kb_id: string;
  kb_type: string;
  stats: { nodes?: number; edges?: number; files?: string[] };
  relations?: string[];
  updated_at?: string;
  warnings?: string[];
  degraded?: boolean;
  error_code?: string;
  graph_source?: string;
}

export interface ToolInfo { name: string; description: string; category: string; available?: boolean; enabled?: boolean }
export interface SkillIssue {
  severity: "ok" | "warning" | "error" | string;
  code: string;
  message: string;
  fix?: string;
}
export interface SkillInfo {
  id?: string;
  name: string;
  description: string;
  version: string;
  tags?: string[];
  required_mcp_ids?: string[];
  required_tools?: string[];
  skill_dependencies?: string[];
  content_hash?: string;
  files?: Array<{ path: string; size: number; kind: string; text: boolean }>;
  resources?: Array<{ path: string; content: string }>;
  validation_issues?: SkillIssue[];
  issues?: SkillIssue[];
  content?: string;
  content_preview: string;
}
export interface SkillRegistryItem {
  id: string;
  name: string;
  description: string;
  version: string;
  tags: string[];
  installed: boolean;
  content_hash?: string;
  issues?: SkillIssue[];
}
export interface MCPRegistryItem {
  id: string;
  name: string;
  description: string;
  transport: string;
  command: string[];
  url: string;
  env_schema: { name: string; description: string }[];
  tags: string[];
  installed: boolean;
  is_enabled: boolean;
}
export interface MCPServer {
  id: string;
  name: string;
  description: string;
  transport: string;
  command: string[];
  url: string;
  env: Record<string, string>;
  disabled_tools: string[];
  disabled_tool_count?: number;
  cache?: MCPCacheEntry | null;
  is_enabled: boolean;
  source: string;
}
export interface MCPCacheEntry {
  server_id: string;
  tool_count: number;
  created_at: number;
  expires_at: number;
  ttl_remaining_seconds: number;
  expired: boolean;
}
export interface MCPTestResult {
  ok: boolean;
  server_id: string;
  latency_ms: number;
  tool_count: number;
  error_type: "" | "connection_error" | "auth_error" | "schema_error" | "timeout" | "tool_runtime_error" | string;
  tools: ToolInfo[];
  message: string;
  cache_ttl_seconds: number;
}
export interface MCPCustomBody {
  id: string;
  name: string;
  description?: string;
  transport?: string;
  command?: string[];
  url?: string;
  env?: Record<string, string>;
  enabled?: boolean;
}
export interface MCPUpdateBody {
  name?: string;
  description?: string;
  transport?: string;
  command?: string[];
  url?: string;
  is_enabled?: boolean;
  env?: Record<string, string>;
  disabled_tools?: string[];
}
export interface SkillCustomBody {
  id: string;
  name: string;
  description?: string;
  content?: string;
  version?: string;
  tags?: string[];
  required_mcp_ids?: string[];
  required_tools?: string[];
  skill_dependencies?: string[];
  force?: boolean;
}
export interface SkillRemoteInstallBody {
  source: string;
  id?: string;
  subdir?: string;
  branch?: string;
  force?: boolean;
}
export interface RemoteSkillCandidate {
  id: string;
  name: string;
  description: string;
  version: string;
  tags: string[];
  required_mcp_ids: string[];
  required_tools: string[];
  skill_dependencies: string[];
  subdir: string;
  file_count: number;
  files: Array<{ path: string; size: number; kind: string; text: boolean }>;
  content_hash: string;
  content_preview: string;
}
export interface SkillFileContent {
  path: string;
  text: boolean;
  markdown: boolean;
  content: string;
  truncated: boolean;
  size: number;
}
export interface SkillHistoryRecord {
  ts: string;
  action: string;
  source?: string;
  file_path?: string;
  message?: string;
  prev_hash?: string;
  new_hash?: string;
  replacements?: number;
  matches?: number;
  scanner?: { decision?: string; reason?: string };
}
export interface CreatorDraftResponse {
  kind: "agent" | "skill" | "mcp";
  summary: string;
  draft: Record<string, unknown>;
}
export interface SystemInfo {
  status: string; service: string; version: string;
  config: {
    debug: boolean; default_model: string; model_count: number; models: Model[];
    knowledge: Record<string, unknown>; web_search: Record<string, unknown>;
    mcp_server_count: number; sandbox: Record<string, unknown>; data_dir: string;
    diagnostics?: ConfigDiagnostics;
  };
}

export interface ConfigIssue {
  severity: "ok" | "warning" | "error";
  code: string;
  message: string;
  fix: string;
}

export interface ConfigDiagnostics {
  status: "ok" | "warning" | "error";
  path: string;
  config_exists: boolean;
  issues: ConfigIssue[];
}

export interface SystemDiagnostics {
  status: string;
  service: string;
  version: string;
  uptime_seconds: number;
  config: ConfigDiagnostics;
}

export interface ChannelInfo { id: string; name: string; description: string; webhook_path: string; enabled: boolean }

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  tool_name?: string | null;
  reasoning_content?: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  user_id?: string | null;
  agent_id: string;
  agent_name: string;
  model_name?: string | null;
  last_message?: string | null;
  message_count: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
  messages?: ConversationMessage[];
}

// ── Agent types ───────────────────────────────────────────────────────────────

export interface AgentConfig {
  id: string;
  name: string;
  description: string;
  base_type: string;
  model_name: string;
  system_prompt: string;
  tools: string[];
  kb_ids: string[];
  skill_ids: string[];
  mcp_ids: string[];
  memory_enabled: boolean;
  thinking_enabled: boolean;
  thinking_budget: number;
  reasoning_mode: ReasoningMode;
  allow_subagents: boolean;
  is_builtin: boolean;
  avatar_color: string;
  created_at: string;
  updated_at: string;
}

export interface AgentCreateBody {
  name: string;
  description?: string;
  base_type?: string;
  model_name?: string;
  system_prompt?: string;
  kb_ids?: string[];
  skill_ids?: string[];
  mcp_ids?: string[];
  allow_subagents?: boolean;
  memory_enabled?: boolean;
  thinking_enabled?: boolean;
  thinking_budget?: number;
  reasoning_mode?: ReasoningMode;
  avatar_color?: string;
}

// ── Provider types ────────────────────────────────────────────────────────────

export interface ModelProvider {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  models_endpoint?: string;
  api_key_env?: string;
  capabilities?: ProviderCapability[];
  models: string[];
  model_configs?: ProviderModelConfig[];
  is_enabled: boolean;
  is_default: boolean;
  api_key_configured: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderCreateBody {
  id?: string;
  name: string;
  provider_type: string;
  base_url?: string;
  models_endpoint?: string;
  api_key_env?: string;
  api_key?: string;
  capabilities?: ProviderCapability[];
  models?: string[];
  model_configs?: ProviderModelConfig[];
  is_enabled?: boolean;
  is_default?: boolean;
}

export type ProviderCapability = "chat" | "embedding" | "rerank";

export interface ProviderModelConfig {
  id: string;
  display_name?: string;
  type: ProviderCapability;
  protocol_override?: string;
  base_url_override?: string;
  context_window?: number | null;
  dimension?: number | null;
  batch_size?: number | null;
  input_price_per_1m?: number | null;
  output_price_per_1m?: number | null;
  currency?: string;
}

export interface ProviderModelFetchResult {
  models: ProviderModelConfig[];
  warning?: string;
}

export interface ModelProbeResult {
  ok: boolean;
  provider_id: string;
  model_id: string;
  capability: ProviderCapability;
  latency_ms: number;
  dimension?: number;
  score?: number | null;
  message: string;
}

export type SearchServiceId = "duckduckgo" | "tavily" | "brave" | "serpapi" | "bing" | "exa" | "searxng";
export type SearchProviderId = "auto" | SearchServiceId;

export interface SearchProviderInfo {
  id: SearchServiceId;
  name: string;
  recommended: boolean;
  requires_api_key: boolean;
  requires_base_url: boolean;
  description: string;
  capabilities: string[];
  enabled: boolean;
  configured: boolean;
  api_key_configured: boolean;
  base_url: string;
}

export interface SearchConfig {
  provider: SearchProviderId;
  preferred_provider: SearchServiceId;
  enabled_providers: SearchServiceId[];
  effective_provider: SearchServiceId | "";
  max_results: number;
  fetch_max_chars: number;
  tavily_api_key_configured: boolean;
  providers: SearchProviderInfo[];
}

export interface SearchProviderUpdate {
  enabled?: boolean;
  api_key?: string;
  base_url?: string;
}

export interface SearchConfigUpdate {
  provider: SearchProviderId;
  preferred_provider: SearchServiceId;
  enabled_providers: SearchServiceId[];
  max_results: number;
  fetch_max_chars: number;
  tavily_api_key?: string;
  providers?: Record<string, SearchProviderUpdate>;
}

// ── Memory types ──────────────────────────────────────────────────────────────

export interface MemoryEntry {
  id: string;
  user_id: string;
  agent_id: string | null;
  memory_type: "fact" | "preference" | "episode";
  key: string;
  value: string;
  source: "agent" | "user";
  importance: number;
  created_at: string;
  updated_at: string;
}

// ── Dashboard types ───────────────────────────────────────────────────────────

export interface DashboardSummary {
  days: number;
  total_calls: number;
  total_tokens: number;
  input_tokens?: number;
  output_tokens?: number;
  token_anomaly_count?: number;
  token_sources?: { provider_reported: number; estimated: number; ignored: number };
  token_source_counts?: Record<string, number>;
  total_cost?: number;
  cost_by_currency?: Record<string, number>;
  currency?: string;
  priced_call_count?: number;
  pricing_coverage?: { priced_calls: number; total_calls: number; percent: number };
  unpriced_models?: { model_name: string; calls: number; tokens: number; reason: string }[];
  avg_latency_ms: number;
  p95_latency_ms?: number;
  error_rate: number;
  error_count: number;
  agent_count: number;
  status_breakdown?: { status: string; count: number }[];
  top_agents: { agent_id: string; agent_name: string; calls: number; tokens: number; cost?: number; cost_by_currency?: Record<string, number>; avg_latency_ms: number }[];
  top_models?: { model_name: string; calls: number; tokens: number; cost?: number; cost_by_currency?: Record<string, number>; avg_latency_ms: number }[];
  top_tools?: { name: string; count: number }[];
}

export interface TimeSeriesPoint { timestamp: string; value: number; values?: Record<string, number> }
export interface DashboardAnomaly {
  id: string;
  agent_name?: string;
  agent_id?: string;
  model_name?: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  raw_input_tokens: number;
  raw_output_tokens: number;
  raw_total_tokens: number;
  token_source: string;
  token_estimated: boolean;
  token_usage_anomalous: boolean;
  repairable: boolean;
  created_at?: string;
}
export interface AgentDashboardStats {
  agent_id: string;
  days: number;
  calls: number;
  tokens: number;
  avg_latency_ms: number;
  error_rate: number;
  top_tools: { name: string; count: number }[];
  recent: unknown[];
}

// ── Models ────────────────────────────────────────────────────────────────────

export async function fetchModels(): Promise<Model[]> {
  const res = await fetch(`${BASE}/models`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.models ?? [];
}

// ── Chat ──────────────────────────────────────────────────────────────────────

export async function* streamChat(req: ChatRequest, options?: { signal?: AbortSignal }): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal: options?.signal,
  });

  if (!res.ok || !res.body) {
    yield { status: "error", error: `HTTP ${res.status}: ${res.statusText}` };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        yield JSON.parse(trimmed) as StreamChunk;
      } catch {
        yield { status: "error", error: `无法解析后端流式响应：${trimmed.slice(0, 180)}` };
      }
    }
  }
  const tail = buffer.trim();
  if (tail) {
    try {
      yield JSON.parse(tail) as StreamChunk;
    } catch {
      yield { status: "error", error: `无法解析后端流式响应：${tail.slice(0, 180)}` };
    }
  }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // The stream may already be closed.
    } finally {
      reader.releaseLock();
    }
  }
}

export async function fetchHistory(threadId: string) {
  const res = await fetch(`${BASE}/chat/history/${threadId}`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.messages ?? [];
}

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BASE}/conversations/`);
  if (!res.ok) return [];
  return (await res.json()).conversations ?? [];
}

export async function createConversation(body: {
  title?: string;
  user_id?: string;
  agent_id?: string;
  agent_name?: string;
  model_name?: string;
}): Promise<Conversation> {
  const res = await fetch(`${BASE}/conversations/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchConversation(id: string): Promise<Conversation | null> {
  const res = await fetch(`${BASE}/conversations/${id}`);
  if (!res.ok) return null;
  const data = await res.json();
  if (data.conversation) return { ...data.conversation, messages: data.messages ?? [] };
  return data;
}

export async function updateConversation(id: string, body: { title?: string; archived?: boolean }): Promise<Conversation> {
  const res = await fetch(`${BASE}/conversations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}`, { method: "DELETE" });
}

// ── Knowledge bases ───────────────────────────────────────────────────────────

export async function fetchKBs(): Promise<KBMeta[]> {
  const res = await fetch(`${BASE}/knowledge/`);
  if (!res.ok) return [];
  return (await res.json()).knowledge_bases ?? [];
}

export async function fetchKnowledgeStatus(): Promise<KnowledgeStatus | null> {
  const res = await fetch(`${BASE}/knowledge/status`);
  if (!res.ok) return null;
  return res.json();
}

export async function createKB(body: {
  name: string;
  description?: string;
  kb_type?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  chunk_preset_id?: "general" | "qa" | "book" | "laws" | "paper";
  chunk_parser_config?: Record<string, unknown>;
  embed_model?: string;
  embed_base_url?: string;
  embed_api_key?: string;
  embed_dimension?: number | null;
  llm_model?: string;
  llm_provider?: string;
  llm_base_url?: string;
  llm_api_key?: string;
  language?: string;
  purpose?: string;
}): Promise<KBMeta> {
  const res = await fetch(`${BASE}/knowledge/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateKBModelConfig(kbId: string, body: {
  embed_model?: string;
  embed_base_url?: string;
  embed_api_key?: string;
  embed_dimension?: number | null;
  llm_model?: string;
  llm_provider?: string;
  llm_base_url?: string;
  llm_api_key?: string;
  use_reranker?: boolean;
  reranker_model?: string;
}): Promise<{ kb: KBMeta; requires_reindex: boolean; indexed_files: number; query_config: RetrievalConfig }> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/model-config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function deleteKB(kbId: string): Promise<void> {
  await fetch(`${BASE}/knowledge/${kbId}`, { method: "DELETE" });
}

export async function fetchFiles(kbId: string): Promise<FileMeta[]> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files`);
  if (!res.ok) return [];
  return (await res.json()).files ?? [];
}

export async function uploadFile(kbId: string, file: File): Promise<FileMeta> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/knowledge/${kbId}/files`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function deleteFile(kbId: string, fileId: string): Promise<void> {
  await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}`, { method: "DELETE" });
}

export async function parseFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/parse`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function indexFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/index`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function reparseFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/reparse`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function reindexFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/reindex`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function rebuildGraphFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/rebuild-graph`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function processFileAsync(kbId: string, fileId: string): Promise<{ task?: TaskRecord | null; job?: IngestionJob | null; file: FileMeta; message?: string }> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/process-async`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function processAllFiles(kbId: string, retryErrors = true): Promise<{ task?: TaskRecord | null; job?: IngestionJob | null; queued: number; message?: string }> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/process-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ retry_errors: retryErrors }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchKnowledgeDiagnostics(kbId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/diagnostics`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchIngestionJobs(kbId: string): Promise<IngestionJob[]> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/jobs`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.tasks ?? data.jobs ?? [];
}

export async function retryIngestionJob(jobId: string): Promise<{ task?: TaskRecord; job?: IngestionJob; retried_from?: string; queued?: number; message?: string }> {
  const res = await fetch(`${BASE}/knowledge/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchTasks(params?: { kind?: string; status?: string; limit?: number }): Promise<TaskRecord[]> {
  const url = new URL(`${BASE}/tasks/`, window.location.origin);
  if (params?.kind) url.searchParams.set("kind", params.kind);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  const res = await fetch(url.toString());
  if (!res.ok) return [];
  return (await res.json()).tasks ?? [];
}

export async function fetchTask(taskId: string): Promise<TaskRecord | null> {
  const res = await fetch(`${BASE}/tasks/${encodeURIComponent(taskId)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(`${BASE}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return (await res.json()).task;
}

export async function retryTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(`${BASE}/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return (await res.json()).task;
}

export async function fetchParsedFilePreview(kbId: string, fileId: string): Promise<ParsedFilePreview> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/preview`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function processFile(kbId: string, fileId: string): Promise<FileMeta> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/files/${fileId}/process`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return (await res.json()).indexed;
}

export async function searchKB(kbId: string, query: string, topK = 5): Promise<SearchResult[]> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, top_k: topK }) });
  if (!res.ok) return [];
  return (await res.json()).results ?? [];
}

export type RetrievalMode = "vector" | "keyword" | "hybrid" | "lightrag_local" | "lightrag_global" | "lightrag_hybrid" | "wiki";
export interface RetrievalConfig {
  mode?: RetrievalMode | string;
  search_mode?: RetrievalMode | string;
  recall_top_k?: number;
  final_top_k?: number;
  similarity_threshold?: number;
  vector_weight?: number;
  keyword_weight?: number;
  bm25_weight?: number;
  bm25_top_k?: number;
  bm25_drop_ratio_search?: number;
  use_reranker?: boolean;
  reranker_model?: string;
  graph_depth?: number;
  graph_limit?: number;
}

export interface QueryConfigOption {
  key: keyof RetrievalConfig | string;
  label: string;
  type: "select" | "number" | "boolean" | "text" | string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
}

export interface KnowledgeQueryConfigResponse {
  kb_id: string;
  kb_type: KBMeta["kb_type"];
  available_modes: RetrievalMode[];
  options: QueryConfigOption[];
  query_config: RetrievalConfig;
  effective_config: RetrievalConfig;
}

function extractError(res: Response, fallback: string) {
  return res.json().catch(() => ({})).then((body) => {
    const detail = body?.detail;
    if (Array.isArray(detail)) return detail.map((item) => item?.msg || JSON.stringify(item)).join("; ");
    if (detail && typeof detail === "object") {
      const message = detail.message || detail.detail || JSON.stringify(detail);
      const code = detail.error_code || detail.code;
      return code ? `${message} (${code})` : message;
    }
    return detail || body?.message || fallback;
  });
}

export async function searchKBWithConfig(kbId: string, query: string, config: RetrievalConfig = {}): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: config.final_top_k ?? 5, ...config }),
  });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  const body = await res.json();
  return {
    ...body,
    results: body.results ?? [],
    total: body.total ?? body.results?.length ?? 0,
    warnings: body.warnings ?? [],
    degraded: Boolean(body.degraded),
    error_code: body.error_code ?? "",
    message: body.message ?? "",
    detail: body.detail ?? "",
    action: body.action ?? "",
    fallback_source: body.fallback_source ?? "none",
  };
}

export async function fetchKBQueryConfig(kbId: string): Promise<KnowledgeQueryConfigResponse> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/query-config`);
  if (!res.ok) {
    return { kb_id: kbId, kb_type: "milvus", available_modes: ["vector", "keyword", "hybrid"], options: [], query_config: {}, effective_config: {} };
  }
  const body = await res.json();
  return {
    kb_id: body.kb_id ?? kbId,
    kb_type: body.kb_type ?? "milvus",
    available_modes: body.available_modes ?? ["vector", "keyword", "hybrid"],
    options: body.options ?? [],
    query_config: body.query_config ?? {},
    effective_config: body.effective_config ?? body.query_config ?? {},
  };
}

export async function fetchWikiKbPages(kbId: string, params: Record<string, string> = {}): Promise<WikiPageSummary[]> {
  const query = new URLSearchParams(params);
  const suffix = query.toString() ? `?${query}` : "";
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages${suffix}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return (await res.json()).pages ?? [];
}

export async function fetchWikiKbPage(kbId: string, pageId: string): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function updateWikiKbPage(
  kbId: string,
  pageId: string,
  body: { content: string; frontmatter?: Record<string, unknown> },
): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function deleteWikiKbPage(kbId: string, pageId: string): Promise<{ message: string; page_id: string }> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function acceptGeneratedWikiKbPage(kbId: string, pageId: string): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}/accept-generated`, { method: "POST" });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function discardGeneratedWikiKbPage(kbId: string, pageId: string): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/pages/${encodeURIComponent(pageId)}/discard-generated`, { method: "POST" });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function fetchWikiKbGraph(kbId: string, params: Record<string, string> = {}): Promise<WikiGraphPayload> {
  const query = new URLSearchParams(params);
  const suffix = query.toString() ? `?${query}` : "";
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/graph${suffix}`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function fetchWikiKbLint(kbId: string): Promise<WikiLintPayload> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/lint`);
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function repairWikiKbIssues(
  kbId: string,
  body: { issue_ids?: string[]; issue_types?: string[]; page_ids?: string[]; force?: boolean } = {},
): Promise<WikiRepairResult> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/repair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function compileWikiKb(
  kbId: string,
  body: { file_ids?: string[]; force?: boolean; retry_failed?: boolean } = {},
): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function crystallizeWikiKbPage(
  kbId: string,
  body: { title: string; content: string; type?: WikiPageType; sources?: string[]; confidence?: string },
): Promise<WikiPageDetail> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/wiki/crystallize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function updateKBQueryConfig(kbId: string, body: RetrievalConfig): Promise<KnowledgeQueryConfigResponse> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/query-config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  const next = await res.json();
  return {
    kb_id: next.kb_id ?? kbId,
    kb_type: next.kb_type ?? "milvus",
    available_modes: next.available_modes ?? ["vector", "keyword", "hybrid"],
    options: next.options ?? [],
    query_config: next.query_config ?? {},
    effective_config: next.effective_config ?? next.query_config ?? {},
  };
}

export async function fetchKnowledgeGraph(kbId: string, limit = 200): Promise<KnowledgeGraph | null> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/graph?limit=${limit}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchKnowledgeGraphSummary(kbId: string): Promise<KnowledgeGraphSummary | null> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/graph/summary`);
  if (!res.ok) return null;
  return res.json();
}

export async function searchKnowledgeGraph(kbId: string, query: string, limit = 20): Promise<{ query: string; nodes: GraphNode[]; total: number }> {
  const url = new URL(`${BASE}/knowledge/${kbId}/graph/search`, window.location.origin);
  url.searchParams.set("q", query);
  url.searchParams.set("limit", String(limit));
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function fetchKnowledgeSubgraph(kbId: string, nodeId: string, depth = 1, limit = 80): Promise<KnowledgeGraph> {
  const url = new URL(`${BASE}/knowledge/${kbId}/graph/subgraph`, window.location.origin);
  url.searchParams.set("node_id", nodeId);
  url.searchParams.set("depth", String(depth));
  url.searchParams.set("limit", String(limit));
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function uploadGraph(kbId: string, body: { nodes: Record<string, unknown>[]; edges: Record<string, unknown>[]; source?: string }): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/knowledge/${kbId}/graph/upload`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

// ── Agents ────────────────────────────────────────────────────────────────────

export async function fetchAgents(): Promise<AgentConfig[]> {
  const res = await fetch(`${BASE}/agents/`);
  if (!res.ok) return [];
  return (await res.json()).agents ?? [];
}

export async function fetchAgent(id: string): Promise<AgentConfig | null> {
  const res = await fetch(`${BASE}/agents/${id}`);
  if (!res.ok) return null;
  return res.json();
}

export async function createAgent(body: AgentCreateBody): Promise<AgentConfig> {
  const res = await fetch(`${BASE}/agents/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateAgent(id: string, body: Partial<AgentCreateBody>): Promise<AgentConfig> {
  const res = await fetch(`${BASE}/agents/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function deleteAgent(id: string): Promise<void> {
  await fetch(`${BASE}/agents/${id}`, { method: "DELETE" });
}

export async function cloneAgent(id: string): Promise<AgentConfig> {
  const res = await fetch(`${BASE}/agents/${id}/clone`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function chatWithAgent(id: string, body: ChatRequest): Promise<{ response: string; thread_id: string; agent: string; model?: string; artifacts: string[] }> {
  const res = await fetch(`${BASE}/agents/${id}/chat`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchTools(): Promise<ToolInfo[]> {
  const res = await fetch(`${BASE}/agents/tools`);
  if (!res.ok) return [];
  return (await res.json()).tools ?? [];
}

export async function fetchSkills(): Promise<SkillInfo[]> {
  const res = await fetch(`${BASE}/skills/`);
  if (!res.ok) return [];
  return (await res.json()).skills ?? [];
}

export async function fetchSkillRegistry(): Promise<SkillRegistryItem[]> {
  const res = await fetch(`${BASE}/skills/registry`);
  if (!res.ok) return [];
  return (await res.json()).registry ?? [];
}

export async function installSkill(id: string, force = false): Promise<SkillInfo> {
  const res = await fetch(`${BASE}/skills/install`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, force }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function uninstallSkill(id: string): Promise<void> {
  await fetch(`${BASE}/skills/${id}`, { method: "DELETE" });
}

// ── Providers (Settings) ──────────────────────────────────────────────────────

export async function fetchProviders(): Promise<ModelProvider[]> {
  const res = await fetch(`${BASE}/settings/providers`);
  if (!res.ok) return [];
  return (await res.json()).providers ?? [];
}

export async function createProvider(body: ProviderCreateBody): Promise<ModelProvider> {
  const res = await fetch(`${BASE}/settings/providers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateProvider(id: string, body: Partial<ProviderCreateBody>): Promise<ModelProvider> {
  const res = await fetch(`${BASE}/settings/providers/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function deleteProvider(id: string): Promise<void> {
  await fetch(`${BASE}/settings/providers/${id}`, { method: "DELETE" });
}

export async function testProvider(id: string): Promise<{ ok: boolean; latency_ms: number; message: string }> {
  const res = await fetch(`${BASE}/settings/providers/${id}/test`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function testProviderCapabilities(id: string): Promise<{
  provider_id: string;
  models: { model: string; capabilities: ModelCapabilities; tests: Record<string, { ok: boolean; message: string }> }[];
}> {
  const res = await fetch(`${BASE}/settings/providers/${id}/test-capabilities`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function testProviderModel(body: {
  provider_id: string;
  model_id: string;
  capability: "embedding" | "rerank";
  sample_text?: string;
}): Promise<ModelProbeResult> {
  const res = await fetch(`${BASE}/settings/models/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function fetchProviderModels(id: string): Promise<ProviderModelFetchResult> {
  const res = await fetch(`${BASE}/settings/providers/${id}/models`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  const models = Array.isArray(data.model_configs)
    ? data.model_configs
    : (data.models ?? []).map((model: string) => ({ id: model, display_name: model, type: "chat" as const }));
  return { models, warning: data.warning };
}

export async function fetchSearchConfig(): Promise<SearchConfig> {
  const res = await fetch(`${BASE}/settings/search`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateSearchConfig(body: SearchConfigUpdate): Promise<SearchConfig> {
  const res = await fetch(`${BASE}/settings/search`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

// ── Speech (ASR / TTS) ──────────────────────────────────────────────────────

export interface SpeechConfig {
  asr: {
    enabled: boolean;
    base_url: string;
    api_key: string;
    api_key_configured: boolean;
    model: string;
    language: string;
  };
  tts: {
    enabled: boolean;
    base_url: string;
    api_key: string;
    api_key_configured: boolean;
    model: string;
    voice: string;
    format: string;
    sample_rate: number;
    speed: number;
  };
}

export async function fetchSpeechConfig(): Promise<SpeechConfig> {
  const res = await fetch(`${BASE}/settings/speech`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateSpeechConfig(body: {
  asr_enabled: boolean;
  asr_base_url: string;
  asr_api_key: string | null;
  asr_model: string;
  asr_language: string;
  tts_enabled: boolean;
  tts_base_url: string;
  tts_api_key: string | null;
  tts_model: string;
  tts_voice: string;
  tts_format: string;
  tts_sample_rate: number;
  tts_speed: number;
}): Promise<SpeechConfig> {
  const res = await fetch(`${BASE}/settings/speech`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export interface ImageConfig {
  enabled: boolean;
  base_url: string;
  api_key: string;
  api_key_configured: boolean;
  model: string;
  size: string;
}

export async function fetchImageConfig(): Promise<ImageConfig> {
  const res = await fetch(`${BASE}/settings/image`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateImageConfig(body: {
  enabled: boolean;
  base_url: string;
  api_key: string | null;
  model: string;
  size: string;
}): Promise<ImageConfig> {
  const res = await fetch(`${BASE}/settings/image`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

/** Speech-to-text: send a recorded audio blob, get back the transcript. */
export async function transcribeAudio(blob: Blob, filename = "audio.webm"): Promise<string> {
  const form = new FormData();
  form.append("file", blob, filename);
  const res = await fetch(`${BASE}/media/transcribe`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return (await res.json()).text ?? "";
}

/** Text-to-speech: returns a playable object URL for the synthesized audio. */
export async function synthesizeSpeech(
  text: string,
  opts?: { voice?: string; model?: string; format?: string; speed?: number },
): Promise<{ url: string; mime: string }> {
  const res = await fetch(`${BASE}/media/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, ...opts }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  const mime = res.headers.get("Content-Type") || "audio/mpeg";
  const buf = await res.blob();
  return { url: URL.createObjectURL(buf), mime };
}

// ── LLM Wiki ────────────────────────────────────────────────────────────────

export interface WikiPage {
  id: string;
  title: string;
  tags?: string[];
  thread_id?: string;
  kb_id?: string | null;
  file_id?: string | null;
  created_at?: number;
  char_count?: number;
  warning?: string;
  content?: string;
}

export async function crystallizeWiki(body: { thread_id: string; kb_id: string; model?: string }): Promise<WikiPage> {
  const res = await fetch(`${BASE}/wiki/crystallize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchWikiPages(): Promise<WikiPage[]> {
  const res = await fetch(`${BASE}/wiki/pages`);
  if (!res.ok) return [];
  return (await res.json()).pages ?? [];
}

export async function fetchWikiPage(id: string): Promise<WikiPage | null> {
  const res = await fetch(`${BASE}/wiki/pages/${id}`);
  if (!res.ok) return null;
  return res.json();
}

export async function deleteWikiPage(id: string): Promise<void> {
  await fetch(`${BASE}/wiki/pages/${id}`, { method: "DELETE" });
}

// ── Realtime voice call ─────────────────────────────────────────────────────

/** Resolve the WebSocket URL for the realtime voice call endpoint. */
export function voiceCallWsUrl(): string {
  if (typeof window === "undefined") return "";
  const base = BASE.startsWith("http")
    ? BASE.replace(/^http/, "ws")
    : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${BASE}`;
  return `${base}/voice/call`;
}

export async function testSearchConfig(body: {
  mode?: "search" | "fetch";
  query?: string;
  url?: string;
  provider?: SearchProviderId;
  preferred_provider?: SearchServiceId;
  enabled_providers?: SearchServiceId[];
  max_results?: number;
  fetch_max_chars?: number;
  tavily_api_key?: string;
  providers?: Record<string, SearchProviderUpdate>;
}): Promise<{ ok: boolean; latency_ms: number; message: string }> {
  const res = await fetch(`${BASE}/settings/search/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

// ── Memory ────────────────────────────────────────────────────────────────────

export async function fetchMemories(userId: string, params?: { agent_id?: string; memory_type?: string; q?: string; limit?: number; offset?: number }): Promise<{ memories: MemoryEntry[]; total: number }> {
  const url = new URL(`${BASE}/memory/${userId}`, window.location.origin);
  if (params?.agent_id) url.searchParams.set("agent_id", params.agent_id);
  if (params?.memory_type) url.searchParams.set("memory_type", params.memory_type);
  if (params?.q) url.searchParams.set("q", params.q);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  if (params?.offset) url.searchParams.set("offset", String(params.offset));
  const res = await fetch(url.toString());
  if (!res.ok) return { memories: [], total: 0 };
  const data = await res.json();
  return { memories: data.memories ?? [], total: data.total ?? 0 };
}

export async function createMemory(userId: string, body: { key: string; value: string; memory_type?: string; importance?: number }): Promise<MemoryEntry> {
  const res = await fetch(`${BASE}/memory/${userId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateMemory(userId: string, memoryId: string, body: { key?: string; value?: string; memory_type?: string; importance?: number }): Promise<MemoryEntry> {
  const res = await fetch(`${BASE}/memory/${userId}/${memoryId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function deleteMemory(userId: string, memoryId: string): Promise<void> {
  await fetch(`${BASE}/memory/${userId}/${memoryId}`, { method: "DELETE" });
}

export async function clearMemories(userId: string): Promise<void> {
  await fetch(`${BASE}/memory/${userId}`, { method: "DELETE" });
}

export async function fetchMemoryStats(userId: string): Promise<{ total: number; by_type: Record<string, number> }> {
  const res = await fetch(`${BASE}/memory/${userId}/stats`);
  if (!res.ok) return { total: 0, by_type: {} };
  return res.json();
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export async function fetchDashboardSummary(days = 7): Promise<DashboardSummary | null> {
  const res = await fetch(`${BASE}/dashboard/summary?days=${days}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchTimeSeries(metric: "calls" | "tokens" | "latency" | "errors" | "cost", days = 7): Promise<TimeSeriesPoint[]> {
  const res = await fetch(`${BASE}/dashboard/timeseries?metric=${metric}&days=${days}`);
  if (!res.ok) return [];
  return (await res.json()).series ?? [];
}

export async function fetchRecentLogs(limit = 20) {
  const res = await fetch(`${BASE}/dashboard/recent?limit=${limit}`);
  if (!res.ok) return [];
  return (await res.json()).logs ?? [];
}

export async function fetchDashboardAnomalies(limit = 50): Promise<DashboardAnomaly[]> {
  const res = await fetch(`${BASE}/dashboard/anomalies?limit=${limit}`);
  if (!res.ok) return [];
  return (await res.json()).anomalies ?? [];
}

export async function repairDashboardAnomalies(body: { ids?: string[]; mode: "repair" | "ignore" }): Promise<{ updated: number; mode: string }> {
  const res = await fetch(`${BASE}/dashboard/anomalies/repair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchAgentDashboardStats(agentId: string, days = 7): Promise<AgentDashboardStats | null> {
  const res = await fetch(`${BASE}/dashboard/agents/${agentId}/stats?days=${days}`);
  if (!res.ok) return null;
  return res.json();
}

// ── MCP ───────────────────────────────────────────────────────────────────────

export async function fetchMCPRegistry(): Promise<MCPRegistryItem[]> {
  const res = await fetch(`${BASE}/mcp/registry`);
  if (!res.ok) return [];
  return (await res.json()).registry ?? [];
}

export async function fetchInstalledMCP(): Promise<MCPServer[]> {
  const res = await fetch(`${BASE}/mcp/installed`);
  if (!res.ok) return [];
  return (await res.json()).servers ?? [];
}

export async function installMCP(id: string, env: Record<string, string> = {}): Promise<MCPServer> {
  const res = await fetch(`${BASE}/mcp/install`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, env }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function createCustomMCP(body: MCPCustomBody): Promise<MCPServer> {
  const res = await fetch(`${BASE}/mcp/custom`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateMCP(id: string, body: MCPUpdateBody): Promise<MCPServer> {
  const res = await fetch(`${BASE}/mcp/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function updateMCPTool(id: string, toolName: string, isEnabled: boolean): Promise<MCPServer> {
  const res = await fetch(`${BASE}/mcp/${id}/tools/${encodeURIComponent(toolName)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_enabled: isEnabled }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function uninstallMCP(id: string): Promise<void> {
  await fetch(`${BASE}/mcp/${id}`, { method: "DELETE" });
}

export async function testMCP(id: string): Promise<MCPTestResult> {
  const res = await fetch(`${BASE}/mcp/${id}/test`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function createCustomSkill(body: SkillCustomBody): Promise<SkillInfo> {
  const res = await fetch(`${BASE}/skills/custom`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function installRemoteSkill(body: SkillRemoteInstallBody): Promise<SkillInfo> {
  const res = await fetch(`${BASE}/skills/install/remote`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchRemoteSkillList(body: { source: string; branch?: string }): Promise<RemoteSkillCandidate[]> {
  const res = await fetch(`${BASE}/skills/remote/list`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()).skills ?? [];
}

export async function fetchSkillFileContent(skillId: string, path: string): Promise<SkillFileContent> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/files/content?path=${encodeURIComponent(path)}`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function updateSkillFileContent(skillId: string, path: string, content: string): Promise<SkillFileContent> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/files/content?path=${encodeURIComponent(path)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function deleteSkillFileContent(skillId: string, path: string): Promise<void> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/files/content?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
}

export async function fetchSkillHistory(skillId: string, limit = 30): Promise<SkillHistoryRecord[]> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(skillId)}/history?limit=${limit}`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return (await res.json()).history ?? [];
}

export async function uploadSkill(file: File, options: { id?: string; force?: boolean } = {}): Promise<SkillInfo> {
  const form = new FormData();
  form.append("file", file);
  if (options.id) form.append("id", options.id);
  form.append("force", String(options.force ?? false));
  const res = await fetch(`${BASE}/skills/upload`, { method: "POST", body: form });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail?.message ?? error.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function updateSkill(id: string, body: Partial<SkillCustomBody>): Promise<SkillInfo> {
  const res = await fetch(`${BASE}/skills/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await apiErrorMessage(res));
  return res.json();
}

export async function testSkill(id: string): Promise<{ ok: boolean; message: string; content_hash?: string; issues?: SkillIssue[] }> {
  const res = await fetch(`${BASE}/skills/${id}/test`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function analyzeImage(file: File, model?: string) {
  const form = new FormData();
  form.append("file", file);
  if (model) form.append("model", model);
  const res = await fetch(`${BASE}/media/analyze-image`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function analyzeVideo(file: File, model?: string) {
  const form = new FormData();
  form.append("file", file);
  if (model) form.append("model", model);
  const res = await fetch(`${BASE}/media/analyze-video`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

/** Generate an image from a prompt; returns a displayable URL for the result. */
export async function generateImage(prompt: string, model?: string): Promise<string> {
  const res = await fetch(`${BASE}/media/generate-image`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, model }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  const rel = data?.artifact?.url as string | undefined;
  if (!rel) throw new Error("生成结果缺少图片地址");
  if (rel.startsWith("http")) return rel;
  const origin = BASE.startsWith("http") ? new URL(BASE).origin : "";
  return `${origin}${rel}`;
}

export async function generateVideo(prompt: string, model?: string) {
  const res = await fetch(`${BASE}/media/generate-video`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, model }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function draftCreator(kind: "agent" | "skill" | "mcp", goal: string, details: Record<string, string> = {}): Promise<CreatorDraftResponse> {
  const res = await fetch(`${BASE}/creator/${kind}/draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal, details }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function saveCreator(kind: "agent" | "skill" | "mcp", draft: Record<string, unknown>): Promise<{ saved: unknown; message: string }> {
  const res = await fetch(`${BASE}/creator/${kind}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

// ── System ────────────────────────────────────────────────────────────────────

export async function fetchSystemInfo(): Promise<SystemInfo | null> {
  const res = await fetch(`${BASE}/system/info`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchSystemDiagnostics(): Promise<SystemDiagnostics | null> {
  const res = await fetch(`${BASE}/system/diagnostics`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchThreadArtifacts(threadId: string): Promise<ArtifactMeta[]> {
  const res = await fetch(`${BASE}/artifacts/threads/${encodeURIComponent(threadId)}`);
  if (!res.ok) return [];
  return (await res.json()).artifacts ?? [];
}

export async function fetchArtifactPreview(threadId: string, path: string): Promise<ArtifactPreview> {
  const res = await fetch(
    `${BASE}/artifacts/threads/${encodeURIComponent(threadId)}/preview?path=${encodeURIComponent(path)}`,
  );
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export function artifactDownloadUrl(threadId: string, path: string): string {
  return `${BASE}/artifacts/threads/${encodeURIComponent(threadId)}/download?path=${encodeURIComponent(path)}`;
}

export async function fetchChannels(): Promise<ChannelInfo[]> {
  const res = await fetch(`${BASE}/channels/`);
  if (!res.ok) return [];
  return (await res.json()).channels ?? [];
}

export async function sendChannelMessage(channel: string, body: { text: string; user_id?: string; agent?: string; model?: string }): Promise<{ response: string; thread_id: string; channel: string }> {
  const res = await fetch(`${BASE}/channels/${channel}/webhook`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

// ── Evaluation ────────────────────────────────────────────────────────────────

export type EvalType = "agent" | "rag" | "tool" | "task";
export interface EvalScores {
  rag_hit_rate?: number | null;
  citation_accuracy?: number | null;
  answer_match?: number | null;
  tool_success_rate?: number | null;
  task_completion_rate?: number | null;
}
export interface EvalCase {
  id: string;
  name: string;
  type?: EvalType;
  query: string;
  expected: string;
  expected_answer?: string;
  expected_sources?: string[];
  expected_tools?: string[];
  agent: string;
  model?: string;
  kb_ids?: string[];
  task_id?: string;
  retrieval_config?: RetrievalConfig;
  generation_source?: string;
  generated_by_ai?: boolean;
  tags: string[];
  created_at: string;
}
export interface EvalSample {
  id: string;
  query: string;
  expected: string;
  expected_answer: string;
  expected_sources?: string[];
  expected_tools?: string[];
  tags: string[];
  difficulty?: string;
  notes?: string;
}
export interface EvalSuite {
  id: string;
  name: string;
  type?: EvalType;
  agent: string;
  model?: string;
  kb_ids?: string[];
  task_id?: string;
  retrieval_override_enabled?: boolean;
  retrieval_config?: RetrievalConfig;
  samples: EvalSample[];
  generation_source?: string;
  generated_by_ai?: boolean;
  tags: string[];
  created_at: string;
  updated_at?: string;
  legacy_case_id?: string;
}
export interface EvalResult {
  test_id: string;
  run_id: string;
  type?: EvalType;
  agent: string;
  model?: string;
  query: string;
  response: string;
  actual_answer?: string;
  error?: string;
  error_code?: string;
  latency_ms: number;
  tokens_estimated: number;
  token_usage?: { input_tokens: number; output_tokens: number };
  passed: boolean | null;
  judge_reason: string;
  scores?: EvalScores;
  metrics?: Record<string, number | null | undefined> & EvalScores;
  artifacts?: string[];
  evidence?: Array<Record<string, unknown>>;
  retrieved_chunks?: Array<Record<string, unknown>>;
  retrieved_source_ids?: string[];
  gold_source_ids?: string[];
  tools_used?: string[];
  retrieval_config?: RetrievalConfig;
  retrieval_warnings?: SearchWarning[];
  summary?: EvalSuiteRunSummary;
  sample_results?: EvalResult[];
  suite_id?: string;
  sample_id?: string;
  timestamp: string;
}

export interface EvalSuiteRunSummary {
  total: number;
  passed: number;
  failed: number;
  pass_rate?: number | null;
  avg_latency_ms?: number;
  error_count?: number;
  scores?: EvalScores;
  metrics?: Record<string, number | null | undefined> & EvalScores;
}

export interface EvalGenerationDiagnostic {
  kb_id: string;
  name: string;
  status: "ready" | "empty" | "missing" | string;
  chunks: number;
  source: string;
  kb_type?: KBMeta["kb_type"] | string;
  warnings?: string[];
}

export interface EvalDraft extends Omit<EvalCase, "created_at"> {
  id: string;
}

export interface EvalSuiteDraft extends Omit<EvalSuite, "created_at"> {
  id: string;
}

export async function fetchEvalSuites(tag?: string): Promise<EvalSuite[]> {
  const url = tag ? `${BASE}/eval/suites?tag=${encodeURIComponent(tag)}` : `${BASE}/eval/suites`;
  const res = await fetch(url);
  if (!res.ok) return [];
  return (await res.json()).suites ?? [];
}

export async function createEvalSuite(body: {
  name: string;
  type?: EvalType;
  agent?: string;
  model?: string;
  kb_ids?: string[];
  task_id?: string;
  retrieval_override_enabled?: boolean;
  retrieval_config?: RetrievalConfig;
  samples: Array<Partial<EvalSample> & { query: string }>;
  generation_source?: string;
  generated_by_ai?: boolean;
  tags?: string[];
}): Promise<EvalSuite> {
  const res = await fetch(`${BASE}/eval/suites`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function updateEvalSuite(suiteId: string, body: Partial<EvalSuite>): Promise<EvalSuite> {
  const res = await fetch(`${BASE}/eval/suites/${suiteId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function deleteEvalSuite(suiteId: string): Promise<void> {
  const res = await fetch(`${BASE}/eval/suites/${suiteId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
}

export async function runEvalSuite(suiteId: string, model?: string): Promise<{ suite: EvalSuite; total: number; passed: number; failed: number; skipped: number; summary?: EvalSuiteRunSummary; sample_results?: EvalResult[]; results: EvalResult[] }> {
  const res = await fetch(`${BASE}/eval/suites/${suiteId}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function generateEvalSuiteDraft(body: {
  name?: string;
  source?: "knowledge" | "recent_logs" | "manual" | string;
  type?: EvalType;
  count?: number;
  neighbors_count?: number;
  kb_ids?: string[];
  agent?: string;
  model?: string;
  tags?: string[];
  topic?: string;
  retrieval_override_enabled?: boolean;
  retrieval_config?: RetrievalConfig;
}): Promise<{ suite: EvalSuiteDraft; samples: EvalSample[]; total: number; source: string; diagnostics?: EvalGenerationDiagnostic[] }> {
  const res = await fetch(`${BASE}/eval/suites/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error(await extractError(res, `HTTP ${res.status}`));
  return res.json();
}

export async function fetchEvalCases(tag?: string): Promise<EvalCase[]> {
  const url = tag ? `${BASE}/eval/cases?tag=${encodeURIComponent(tag)}` : `${BASE}/eval/cases`;
  const res = await fetch(url);
  if (!res.ok) return [];
  return (await res.json()).cases ?? [];
}

export async function createEvalCase(body: {
  name: string;
  type?: EvalType;
  query: string;
  expected?: string;
  expected_answer?: string;
  expected_sources?: string[];
  expected_tools?: string[];
  agent?: string;
  model?: string;
  kb_ids?: string[];
  task_id?: string;
  retrieval_config?: RetrievalConfig;
  generation_source?: string;
  generated_by_ai?: boolean;
  tags?: string[];
}): Promise<EvalCase> {
  const res = await fetch(`${BASE}/eval/cases`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function deleteEvalCase(caseId: string): Promise<void> {
  await fetch(`${BASE}/eval/cases/${caseId}`, { method: "DELETE" });
}

export async function runEvalCase(caseId: string, model?: string): Promise<EvalResult> {
  const res = await fetch(`${BASE}/eval/cases/${caseId}/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function runAllEvals(tag?: string, model?: string): Promise<{ total: number; passed: number; failed: number; skipped: number; results: EvalResult[] }> {
  const res = await fetch(`${BASE}/eval/run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tag, model }) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function fetchEvalResults(testId?: string): Promise<EvalResult[]> {
  const url = testId ? `${BASE}/eval/results/${testId}` : `${BASE}/eval/results`;
  const res = await fetch(url);
  if (!res.ok) return [];
  return (await res.json()).results ?? [];
}

export async function generateEvalDrafts(body: {
  source?: "knowledge" | "recent_logs" | "manual" | string;
  type?: EvalType;
  count?: number;
  neighbors_count?: number;
  kb_ids?: string[];
  agent?: string;
  model?: string;
  tags?: string[];
  topic?: string;
  retrieval_config?: RetrievalConfig;
}): Promise<{ drafts: EvalDraft[]; total: number; source: string }> {
  const res = await fetch(`${BASE}/eval/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`);
  return res.json();
}
