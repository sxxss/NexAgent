"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Boxes,
  CheckCircle,
  Code2,
  Eye,
  FileJson,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import {
  createCustomMCP,
  fetchInstalledMCP,
  fetchMCPRegistry,
  installMCP,
  testMCP,
  uninstallMCP,
  updateMCP,
  updateMCPTool,
  type MCPCustomBody,
  type MCPServer,
  type MCPTestResult,
} from "@/lib/api";

type TestState = MCPTestResult | { ok: false; message: string };
type AddMode = "form" | "json";
type ValidationResult = { ok: true; message?: string } | { ok: false; message: string };

type MCPForm = {
  id: string;
  name: string;
  description: string;
  transport: "stdio" | "sse" | "http" | "streamable_http";
  command: string;
  url: string;
  env: string;
  enabled: boolean;
};

const emptyForm: MCPForm = {
  id: "",
  name: "",
  description: "",
  transport: "stdio",
  command: "npx -y",
  url: "",
  env: "{}",
  enabled: true,
};

const defaultJson = JSON.stringify(
  {
    id: "filesystem",
    name: "Filesystem",
    description: "Local filesystem MCP server",
    transport: "stdio",
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
    env: {},
    enabled: true,
  },
  null,
  2,
);

const TRANSPORT_OPTIONS: Array<{
  id: MCPForm["transport"];
  label: string;
  description: string;
  hint: string;
}> = [
  { id: "stdio", label: "STDIO", description: "本地命令进程", hint: "适合 npx、uvx、本地脚本" },
  { id: "sse", label: "SSE", description: "远程事件流", hint: "旧版远程 MCP 常见方式" },
  { id: "http", label: "HTTP", description: "普通 HTTP 连接", hint: "适合兼容 HTTP endpoint" },
  { id: "streamable_http", label: "Streamable HTTP", description: "新版流式 HTTP", hint: "推荐的远程 MCP 传输方式" },
];

export default function MCPPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<MCPForm>(emptyForm);
  const [jsonBody, setJsonBody] = useState(defaultJson);
  const [mode, setMode] = useState<AddMode>("form");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [error, setError] = useState("");
  const [results, setResults] = useState<Record<string, TestState>>({});

  const installedQuery = useQuery({ queryKey: ["mcp-installed"], queryFn: fetchInstalledMCP });
  const registryQuery = useQuery({ queryKey: ["mcp-registry"], queryFn: fetchMCPRegistry });
  const installed = installedQuery.data ?? [];
  const registry = registryQuery.data ?? [];
  const selectedServerLive = selectedServer
    ? installed.find((server) => server.id === selectedServer.id) ?? selectedServer
    : null;
  const jsonValidation = useMemo(() => validateJsonConfig(jsonBody), [jsonBody]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["mcp-installed"] });
    void queryClient.invalidateQueries({ queryKey: ["mcp-registry"] });
  };

  const resetDialog = () => {
    setDialogOpen(false);
    setMode("form");
    setForm(emptyForm);
    setJsonBody(defaultJson);
    setError("");
  };

  const createMutation = useMutation({
    mutationFn: () => createCustomMCP(mode === "json" ? parseJsonConfig(jsonBody) : formToBody(form)),
    onSuccess: () => {
      resetDialog();
      refresh();
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  const runTest = async (id: string) => {
    try {
      const result = await testMCP(id);
      setResults((prev) => ({ ...prev, [id]: result }));
      refresh();
    } catch (err) {
      setResults((prev) => ({ ...prev, [id]: { ok: false, message: err instanceof Error ? err.message : String(err) } }));
    }
  };

  const toggleTool = async (serverId: string, toolName: string, enabled: boolean) => {
    await updateMCPTool(serverId, toolName, enabled);
    setResults((prev) => {
      const current = prev[serverId];
      if (!current || !("tools" in current)) return prev;
      return {
        ...prev,
        [serverId]: {
          ...current,
          tools: current.tools.map((tool) => tool.name === toolName ? { ...tool, enabled } : tool),
        },
      };
    });
    refresh();
  };

  const submit = () => {
    setError("");
    const validation = mode === "json" ? validateJsonConfig(jsonBody) : validateForm(form);
    if (!validation.ok) {
      setError(validation.message);
      return;
    }
    createMutation.mutate();
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="MCP"
        title="MCP 工具中心"
        description="管理 MCP server，测试连接状态，并控制每个 server 暴露给 Agent 的具体工具。"
        actions={
          <>
            <Link href="/creator?type=mcp" className="inline-flex h-9 items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs font-semibold text-sky-700 hover:bg-sky-100">
              <Sparkles size={14} />
              AI 创建
            </Link>
            <Button size="sm" onClick={() => setDialogOpen(true)}>
              <Plus size={14} />
              新增 MCP
            </Button>
            <button type="button" onClick={refresh} className={outlineButton}>
              <RefreshCw size={14} className={installedQuery.isFetching ? "animate-spin" : ""} />
              刷新
            </button>
          </>
        }
      />

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <section className="grid gap-4 xl:grid-cols-2">
          {installed.map((server) => (
            <InstalledMCPCard
              key={server.id}
              server={server}
              onView={() => setSelectedServer(server)}
              onToggleServer={() => void updateMCP(server.id, { is_enabled: !server.is_enabled }).then(refresh)}
              onDelete={() => void uninstallMCP(server.id).then(refresh)}
            />
          ))}
        </section>

        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-slate-950">内置市场</h2>
          <div className="grid gap-4 xl:grid-cols-3">
            {registry.map((item) => (
              <Card key={item.id}>
                <CardContent className="p-5">
                  <div className="flex items-start gap-3">
                    <Wrench size={18} className="mt-1 text-slate-500" />
                    <div className="min-w-0 flex-1">
                      <h3 className="text-sm font-semibold text-slate-950">{item.name}</h3>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{item.description}</p>
                    </div>
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600">{item.transport}</span>
                  </div>
                  <button type="button" disabled={item.installed} onClick={() => void installMCP(item.id).then(refresh)} className="mt-4 inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                    {item.installed ? "已安装" : "安装"}
                  </button>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      </main>

      <Dialog
        open={dialogOpen}
        onClose={resetDialog}
        title="新增 MCP"
        description="使用表单快速创建，或粘贴完整 JSON 配置。保存后可以立即测试工具发现结果。"
        className="max-w-4xl"
        contentClassName="min-h-[600px] px-5 py-5"
      >
        <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-1">
          <div className="grid grid-cols-2 gap-1">
            <ModeButton active={mode === "form"} onClick={() => setMode("form")} icon={<Boxes size={14} />} label="表单" />
            <ModeButton active={mode === "json"} onClick={() => setMode("json")} icon={<FileJson size={14} />} label="JSON" />
          </div>
        </div>

        <div key={mode} className="mcp-panel-enter min-h-[410px] rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          {mode === "form" ? <MCPFormFields form={form} setForm={setForm} /> : null}
          {mode === "json" ? (
            <JsonConfigEditor value={jsonBody} onChange={setJsonBody} validation={jsonValidation} />
          ) : null}
        </div>

        {error ? <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={resetDialog}>取消</Button>
          <Button type="button" size="sm" disabled={createMutation.isPending} onClick={submit}>
            {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            保存
          </Button>
        </div>
      </Dialog>

      {selectedServerLive ? (
        <MCPDetailDialog
          key={selectedServerLive.id}
          server={selectedServerLive}
          result={results[selectedServerLive.id]}
          onClose={() => setSelectedServer(null)}
          onTest={() => void runTest(selectedServerLive.id)}
          onToggleServer={() => void updateMCP(selectedServerLive.id, { is_enabled: !selectedServerLive.is_enabled }).then(refresh)}
          onToggleTool={(toolName, enabled) => void toggleTool(selectedServerLive.id, toolName, enabled)}
          onSaved={() => {
            setResults((prev) => {
              const next = { ...prev };
              delete next[selectedServerLive.id];
              return next;
            });
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function MCPFormFields({ form, setForm, lockedId = false }: { form: MCPForm; setForm: (form: MCPForm) => void; lockedId?: boolean }) {
  const selectedTransport = TRANSPORT_OPTIONS.find((item) => item.id === form.transport) ?? TRANSPORT_OPTIONS[0];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="MCP ID" required hint="用于 Agent 绑定和配置引用，建议小写短横线。">
          <input
            className={`${inputClass} disabled:bg-slate-50 disabled:text-slate-400`}
            disabled={lockedId}
            placeholder="filesystem"
            value={form.id}
            onChange={(event) => setForm({ ...form, id: event.target.value })}
          />
        </Field>
        <Field label="名称" required>
          <input className={inputClass} placeholder="Filesystem" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
      </div>
      <Field label="描述">
        <textarea className={`${inputClass} min-h-20 resize-none`} placeholder="描述这个 MCP 提供的能力" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
      </Field>
      <Field label="连接方式" required>
        <div className="grid gap-2 md:grid-cols-4">
          {TRANSPORT_OPTIONS.map((item) => {
            const active = form.transport === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setForm({ ...form, transport: item.id })}
                className={`min-h-24 rounded-xl border px-3 py-3 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm ${active ? "border-sky-300 bg-sky-50 text-sky-800 shadow-sm" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
              >
                <span className="block text-xs font-bold">{item.label}</span>
                <span className="mt-1 block text-sm font-semibold">{item.description}</span>
                <span className="mt-1 block text-[11px] leading-4 text-slate-400">{item.hint}</span>
              </button>
            );
          })}
        </div>
      </Field>
      {form.transport === "stdio" ? (
        <Field label="stdio 命令" required hint="会按空格拆分，例如 npx -y @modelcontextprotocol/server-filesystem .">
          <input className={inputClass} placeholder="npx -y @modelcontextprotocol/server-filesystem ." value={form.command} onChange={(event) => setForm({ ...form, command: event.target.value })} />
        </Field>
      ) : (
        <Field label={`${selectedTransport.label} URL`} required hint={form.transport === "streamable_http" ? "通常是支持 Streamable HTTP 的 MCP endpoint。" : "填写远程 MCP server 的 URL。"}>
          <input className={inputClass} placeholder="https://example.com/mcp" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} />
        </Field>
      )}
      <Field label="环境变量 JSON" hint='例如 {"API_KEY":"..."}，留空等同于 {}。'>
        <textarea className={`${inputClass} min-h-24 resize-none font-mono text-xs`} placeholder='{"API_KEY":"..."}' value={form.env} onChange={(event) => setForm({ ...form, env: event.target.value })} />
      </Field>
      <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
        <input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
        保存后启用
      </label>
    </div>
  );
}

function InstalledMCPCard({
  server,
  onView,
  onToggleServer,
  onDelete,
}: {
  server: MCPServer;
  onView: () => void;
  onToggleServer: () => void;
  onDelete: () => void;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-sky-50 text-sky-700"><Boxes size={18} /></div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold text-slate-950">{server.name}</h2>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{server.description || server.id}</p>
          </div>
          <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600">{server.transport}</span>
        </div>

        <p className="mt-3 truncate font-mono text-xs text-slate-500">{server.url || server.command.join(" ") || "未配置命令"}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
          <span className={server.is_enabled ? "text-emerald-700" : "text-slate-400"}>{server.is_enabled ? "Server enabled" : "Server disabled"}</span>
          <span>Disabled tools {server.disabled_tool_count ?? server.disabled_tools?.length ?? 0}</span>
          {server.cache ? <span>Cache {server.cache.tool_count} tools / {server.cache.ttl_remaining_seconds}s</span> : null}
        </div>

        <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
          <button type="button" onClick={onView} className={outlineButton}><Eye size={13} />详情</button>
          <button type="button" onClick={onToggleServer} className={outlineButton}>{server.is_enabled ? "停用" : "启用"}</button>
          <button type="button" onClick={onDelete} className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg border border-rose-200 px-2.5 text-xs font-semibold text-rose-600 hover:bg-rose-50"><Trash2 size={13} /></button>
        </div>
      </CardContent>
    </Card>
  );
}

function TestResult({ result }: { result: TestState }) {
  return (
    <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${result.ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
      <div className="flex items-center gap-2">
        {result.ok ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
        <span>
          {"tool_count" in result
            ? `${result.ok ? "可用" : "不可用"}，工具数 ${result.tool_count}，延迟 ${result.latency_ms}ms${result.error_type ? `，${result.error_type}` : ""}`
            : "不可用"}
        </span>
      </div>
      <p className="mt-1 break-words">{result.message}</p>
    </div>
  );
}

function ToolToggleList({
  tools,
  onToggle,
}: {
  tools: MCPTestResult["tools"];
  onToggle: (toolName: string, enabled: boolean) => void;
}) {
  return (
    <div className="mt-3 space-y-2 rounded-lg border border-slate-100 bg-slate-50 p-2">
      {tools.map((tool) => (
        <div key={tool.name} className="flex items-center gap-2 rounded-md bg-white px-2 py-1.5">
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-[11px] font-semibold text-slate-700">{tool.name}</p>
            {tool.description ? <p className="truncate text-[10px] text-slate-400">{tool.description}</p> : null}
          </div>
          <button
            type="button"
            onClick={() => onToggle(tool.name, !(tool.enabled ?? true))}
            className={`h-7 rounded-md px-2 text-[10px] font-semibold ${tool.enabled ?? true ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}
          >
            {tool.enabled ?? true ? "启用" : "停用"}
          </button>
        </div>
      ))}
    </div>
  );
}

function MCPDetailDialog({
  server,
  result,
  onClose,
  onTest,
  onToggleServer,
  onToggleTool,
  onSaved,
}: {
  server: MCPServer;
  result?: TestState;
  onClose: () => void;
  onTest: () => void;
  onToggleServer: () => void;
  onToggleTool: (toolName: string, enabled: boolean) => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<"overview" | "edit">("overview");
  const [editForm, setEditForm] = useState<MCPForm>(() => serverToForm(server));
  const [editError, setEditError] = useState("");
  const tools = result && "tools" in result ? result.tools : [];
  const configJson = JSON.stringify({
    id: server.id,
    name: server.name,
    description: server.description,
    transport: server.transport,
    command: server.command,
    url: server.url,
    env: maskEnv(server.env),
    enabled: server.is_enabled,
    disabled_tools: server.disabled_tools,
  }, null, 2);
  const saveMutation = useMutation({
    mutationFn: () => {
      const validation = validateForm(editForm);
      if (!validation.ok) throw new Error(validation.message);
      const body = formToBody(editForm);
      return updateMCP(server.id, {
        name: body.name,
        description: body.description,
        transport: body.transport,
        command: body.command,
        url: body.url,
        env: body.env,
        is_enabled: body.enabled,
      });
    },
    onSuccess: async () => {
      setEditError("");
      setMode("overview");
      onSaved();
    },
    onError: (err) => setEditError(err instanceof Error ? err.message : String(err)),
  });

  const cancelEdit = () => {
    setEditForm(serverToForm(server));
    setEditError("");
    setMode("overview");
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={server.name}
      description="查看 MCP 配置、缓存、工具发现结果，并测试该 MCP 暴露的工具是否可用。"
      className="max-w-5xl"
      contentClassName="min-h-[640px] px-5 py-5"
    >
      <div className="mb-3 flex justify-end">
        <div className="inline-grid grid-cols-2 gap-0.5 rounded-lg border border-slate-200 bg-slate-50 p-0.5">
          <ModeButton compact active={mode === "overview"} onClick={() => setMode("overview")} icon={<Eye size={13} />} label="概览" />
          <ModeButton compact active={mode === "edit"} onClick={() => setMode("edit")} icon={<Pencil size={13} />} label="编辑" />
        </div>
      </div>
      <div className="grid min-h-[560px] gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
          <div>
            <p className="font-semibold text-slate-700">连接信息</p>
            <div className="mt-2 space-y-2 text-slate-500">
              <MetaLine label="ID" value={server.id} />
              <MetaLine label="Transport" value={server.transport} />
              <MetaLine label="Source" value={server.source} />
              <MetaLine label="Status" value={server.is_enabled ? "enabled" : "disabled"} />
            </div>
          </div>
          <div>
            <p className="font-semibold text-slate-700">入口</p>
            <p className="mt-2 break-words rounded-lg bg-white p-2 font-mono text-[11px] text-slate-600">{server.url || server.command.join(" ") || "未配置"}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-700">缓存</p>
            {server.cache ? (
              <div className="mt-2 space-y-1 text-slate-500">
                <MetaLine label="Tools" value={String(server.cache.tool_count)} />
                <MetaLine label="TTL" value={`${server.cache.ttl_remaining_seconds}s`} />
                <MetaLine label="Expired" value={server.cache.expired ? "yes" : "no"} />
              </div>
            ) : (
              <p className="mt-2 text-slate-400">暂无缓存，点击测试后会生成工具发现结果。</p>
            )}
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onToggleServer} className={outlineButton}>{server.is_enabled ? "停用" : "启用"}</button>
            <button type="button" onClick={onTest} className={outlineButton}><CheckCircle size={13} />测试</button>
          </div>
        </aside>
        <section className="min-w-0 space-y-4">
          {mode === "overview" ? (
            <div key="overview" className="mcp-panel-enter space-y-4">
              {result ? <TestResult result={result} /> : (
                <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-5 text-sm text-slate-500">
                  点击“测试”连接 MCP server，并加载它暴露的工具。
                </div>
              )}
              <div className="rounded-xl border border-slate-200 bg-white">
                <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                  <p className="text-sm font-semibold text-slate-800">工具列表</p>
                  <span className="text-xs text-slate-400">{tools.length} tools</span>
                </div>
                {tools.length ? (
                  <div className="max-h-72 overflow-y-auto p-3">
                    <ToolToggleList tools={tools} onToggle={onToggleTool} />
                  </div>
                ) : (
                  <div className="px-4 py-8 text-center text-sm text-slate-400">还没有工具发现结果。</div>
                )}
              </div>
              <div className="rounded-xl border border-slate-200 bg-white">
                <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">
                  <Code2 size={15} />
                  配置快照
                </div>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap p-4 text-xs leading-6 text-slate-700">{configJson}</pre>
              </div>
            </div>
          ) : (
            <div key="edit" className="mcp-panel-enter rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
              <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <p className="text-sm font-semibold text-slate-900">编辑 MCP 配置</p>
                  <p className="mt-1 text-xs text-slate-500">保存后会自动刷新 MCP 缓存和工具发现缓存。</p>
                </div>
                <span className="rounded-md bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600">{server.source}</span>
              </div>
              <MCPFormFields form={editForm} setForm={setEditForm} lockedId />
              {editError ? <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{editError}</div> : null}
              <div className="mt-5 flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={cancelEdit}>取消</Button>
                <Button type="button" size="sm" disabled={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
                  {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                  保存修改
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>
    </Dialog>
  );
}

function JsonConfigEditor({
  value,
  onChange,
  validation,
}: {
  value: string;
  onChange: (value: string) => void;
  validation: ValidationResult;
}) {
  return (
    <div className="space-y-3">
      <div className={`rounded-xl border px-3 py-2 text-xs ${validation.ok ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-rose-100 bg-rose-50 text-rose-700"}`}>
        {validation.ok ? "JSON 校验通过，可以保存。" : validation.message}
      </div>
      <textarea className={`${inputClass} min-h-80 resize-none font-mono text-xs`} value={value} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

function Field({ label, required, hint, children }: { label: string; required?: boolean; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <span className="flex items-center gap-1 text-xs font-semibold text-slate-700">
        {label}
        {required ? <span className="text-rose-500" aria-label="必填">*</span> : null}
      </span>
      {children}
      {hint ? <span className="block text-[11px] leading-4 text-slate-400">{hint}</span> : null}
    </div>
  );
}

function MetaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-slate-400">{label}</span>
      <span className="min-w-0 break-all text-right font-mono text-slate-600">{value}</span>
    </div>
  );
}

function ModeButton({
  active,
  compact = false,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  compact?: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 text-xs font-semibold transition-all duration-200 ${compact ? "h-8 rounded-md px-2" : "h-10 rounded-lg px-2 hover:-translate-y-0.5"} ${active ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200" : "text-slate-500 hover:bg-white/70 hover:text-slate-800"}`}
    >
      {icon}
      {label}
    </button>
  );
}

function formToBody(form: MCPForm): MCPCustomBody {
  const env = parseEnv(form.env);
  return {
    id: form.id.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    transport: form.transport,
    command: form.transport === "stdio" ? splitCommand(form.command) : [],
    url: form.transport === "stdio" ? "" : form.url.trim(),
    env,
    enabled: form.enabled,
  };
}

function validateForm(form: MCPForm): ValidationResult {
  if (!form.id.trim()) return { ok: false, message: "请填写 MCP ID。" };
  if (!form.name.trim()) return { ok: false, message: "请填写名称。" };
  if (form.transport === "stdio" && !form.command.trim()) return { ok: false, message: "stdio MCP 必须填写命令。" };
  if (form.transport !== "stdio" && !form.url.trim()) return { ok: false, message: "远程 MCP 必须填写 URL。" };
  try {
    parseEnv(form.env);
  } catch (err) {
    return { ok: false, message: `环境变量 JSON 无效：${err instanceof Error ? err.message : String(err)}` };
  }
  return { ok: true };
}

function validateJsonConfig(value: string): ValidationResult {
  try {
    parseJsonConfig(value);
    return { ok: true };
  } catch (err) {
    return { ok: false, message: err instanceof Error ? err.message : String(err) };
  }
}

function parseJsonConfig(value: string): MCPCustomBody {
  const parsed = JSON.parse(value) as MCPCustomBody;
  if (!parsed.id || !parsed.name) throw new Error("JSON 必须包含 id 和 name");
  if (!parsed.transport) parsed.transport = parsed.url ? "sse" : "stdio";
  if (!parsed.command) parsed.command = [];
  if (!parsed.env) parsed.env = {};
  if (parsed.transport === "stdio" && (!Array.isArray(parsed.command) || !parsed.command.length)) {
    throw new Error("stdio MCP 的 command 必须是非空数组");
  }
  if (parsed.transport !== "stdio" && !parsed.url) throw new Error("远程 MCP 必须包含 url");
  if (typeof parsed.env !== "object" || Array.isArray(parsed.env)) throw new Error("env 必须是对象");
  return parsed;
}

function parseEnv(value: string): Record<string, string> {
  if (!value.trim()) return {};
  const parsed = JSON.parse(value) as Record<string, unknown>;
  return Object.fromEntries(Object.entries(parsed).map(([key, val]) => [key, String(val)]));
}

function splitCommand(command: string) {
  return command.split(" ").map((item) => item.trim()).filter(Boolean);
}

function serverToForm(server: MCPServer): MCPForm {
  return {
    id: server.id,
    name: server.name,
    description: server.description ?? "",
    transport: normalizeTransport(server.transport),
    command: server.command?.join(" ") ?? "",
    url: server.url ?? "",
    env: JSON.stringify(server.env ?? {}, null, 2),
    enabled: server.is_enabled,
  };
}

function normalizeTransport(value?: string): MCPForm["transport"] {
  return TRANSPORT_OPTIONS.some((item) => item.id === value) ? (value as MCPForm["transport"]) : "stdio";
}

function maskEnv(env: Record<string, string>) {
  return Object.fromEntries(
    Object.entries(env ?? {}).map(([key, value]) => [
      key,
      /key|token|secret|password/i.test(key) && value ? "••••••••" : value,
    ]),
  );
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100";
const outlineButton = "inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50";
