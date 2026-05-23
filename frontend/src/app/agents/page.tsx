"use client";

import "reactflow/dist/style.css";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactFlow, { Background, Controls, Handle, Position, type Edge, type Node, type NodeProps } from "reactflow";
import { Bot, Brain, Copy, Database, GitBranch, Plus, RefreshCw, Save, Sparkles, Trash2, Wrench, Zap } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  cloneAgent,
  createAgent,
  deleteAgent,
  fetchAgents,
  fetchInstalledMCP,
  fetchKBs,
  fetchModels,
  fetchSkills,
  updateAgent,
  type AgentConfig,
  type AgentCreateBody,
  type Model,
  type ReasoningMode,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const REASONING: Array<{ id: ReasoningMode; label: string }> = [
  { id: "fast", label: "快速" },
  { id: "balanced", label: "思考" },
  { id: "deep", label: "Pro" },
  { id: "ultra", label: "Ultra" },
];
const ALL_REASONING_MODES = REASONING.map((item) => item.id);

const formSchema = z.object({
  name: z.string().min(1, "请输入名称"),
  description: z.string(),
  base_type: z.string(),
  model_name: z.string(),
  system_prompt: z.string(),
  kb_ids: z.array(z.string()),
  skill_ids: z.array(z.string()),
  mcp_ids: z.array(z.string()),
  memory_enabled: z.boolean(),
  thinking_enabled: z.boolean(),
  thinking_budget: z.number(),
  reasoning_mode: z.enum(["fast", "balanced", "deep", "ultra"]),
  allow_subagents: z.boolean(),
  avatar_color: z.string(),
});

type AgentForm = z.infer<typeof formSchema>;

const EMPTY_FORM: AgentForm = {
  name: "",
  description: "",
  base_type: "chatbot",
  model_name: "",
  system_prompt: "",
  kb_ids: [],
  skill_ids: [],
  mcp_ids: [],
  memory_enabled: false,
  thinking_enabled: false,
  thinking_budget: 8000,
  reasoning_mode: "balanced",
  allow_subagents: true,
  avatar_color: "teal",
};

const FLOW_NODE_TYPES = { agent: FlowNode };

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<AgentConfig | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string>();

  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: fetchAgents });
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const kbsQuery = useQuery({ queryKey: ["kbs"], queryFn: fetchKBs });
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: fetchSkills });
  const mcpQuery = useQuery({ queryKey: ["mcp-installed"], queryFn: fetchInstalledMCP });

  const agents = useMemo(() => agentsQuery.data ?? [], [agentsQuery.data]);
  const models = useMemo(() => dedupeModels(modelsQuery.data ?? []), [modelsQuery.data]);
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const skills = useMemo(() => skillsQuery.data ?? [], [skillsQuery.data]);
  const mcpServers = useMemo(() => mcpQuery.data ?? [], [mcpQuery.data]);

  const form = useForm<AgentForm>({
    resolver: zodResolver(formSchema),
    defaultValues: EMPTY_FORM,
  });

  const supportedModes = ALL_REASONING_MODES;
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId) ?? agents[0];

  const saveMutation = useMutation({
    mutationFn: async (values: AgentForm) => {
      const body: AgentCreateBody = values;
      if (editing) return updateAgent(editing.id, body);
      return createAgent(body);
    },
    onSuccess: async () => {
      setEditing(null);
      form.reset(EMPTY_FORM);
      await queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
  });

  const nodesAndEdges = useMemo(() => buildFlow(selectedAgent), [selectedAgent]);

  const openEdit = (agent: AgentConfig) => {
    setEditing(agent);
    setSelectedAgentId(agent.id);
    form.reset({
      name: agent.name,
      description: agent.description,
      base_type: agent.base_type,
      model_name: agent.model_name,
      system_prompt: agent.system_prompt,
      kb_ids: agent.kb_ids,
      skill_ids: agent.skill_ids,
      mcp_ids: agent.mcp_ids,
      memory_enabled: agent.memory_enabled,
      thinking_enabled: agent.thinking_enabled,
      thinking_budget: agent.thinking_budget,
      reasoning_mode: agent.reasoning_mode ?? "balanced",
      allow_subagents: agent.allow_subagents,
      avatar_color: agent.avatar_color,
    });
  };

  const refresh = () => {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["agents"] }),
      queryClient.invalidateQueries({ queryKey: ["models"] }),
      queryClient.invalidateQueries({ queryKey: ["kbs"] }),
      queryClient.invalidateQueries({ queryKey: ["skills"] }),
      queryClient.invalidateQueries({ queryKey: ["mcp-installed"] }),
    ]);
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Agent Studio"
        title="Agent 编排中心"
        description="用表单配置 Agent 的模型、系统提示词、知识库、Skills、MCP 和可调用 Agent；用流程图观察每个 Agent 的资源连接。"
        actions={
          <>
            <Link
              href="/creator?type=agent"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-fuchsia-200 bg-fuchsia-50 px-3 text-xs font-semibold text-fuchsia-700 hover:bg-fuchsia-100"
            >
              <Sparkles size={14} />
              AI 创建
            </Link>
            <button
              type="button"
              onClick={refresh}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              <RefreshCw size={14} className={agentsQuery.isFetching ? "animate-spin" : ""} />
              刷新
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                form.reset(EMPTY_FORM);
              }}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white hover:bg-slate-800"
            >
              <Plus size={14} />
              新建 Agent
            </button>
          </>
        }
      />

      <main className="grid min-h-0 flex-1 gap-5 overflow-y-auto p-6 xl:grid-cols-[minmax(0,1fr)_430px]">
        <section className="space-y-5">
          <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                selected={selectedAgent?.id === agent.id}
                onSelect={() => setSelectedAgentId(agent.id)}
                onEdit={() => openEdit(agent)}
                onClone={() => void cloneAgent(agent.id).then(() => queryClient.invalidateQueries({ queryKey: ["agents"] }))}
                onDelete={() => void deleteAgent(agent.id).then(() => queryClient.invalidateQueries({ queryKey: ["agents"] }))}
              />
            ))}
          </div>

          <Card className="h-[420px] overflow-hidden">
            <CardHeader>
              <CardTitle>资源编排图</CardTitle>
            </CardHeader>
            <div className="h-[360px]">
              <ReactFlow
                nodes={nodesAndEdges.nodes}
                edges={nodesAndEdges.edges}
                nodeTypes={FLOW_NODE_TYPES}
                fitView
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
              >
                <Background gap={18} color="#e2e8f0" />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </Card>
        </section>

        <AgentFormPanel
          form={form}
          editing={editing}
          models={models}
          kbs={kbs.map((item) => ({ id: item.kb_id, label: item.name }))}
          skills={skills.map((item) => ({ id: item.name, label: item.name }))}
          mcp={mcpServers.map((item) => ({ id: item.id, label: item.name }))}
          supportedModes={supportedModes}
          saving={saveMutation.isPending}
          onSubmit={(values) => saveMutation.mutate(values)}
        />
      </main>
    </div>
  );
}

function AgentCard({
  agent,
  selected,
  onSelect,
  onEdit,
  onClone,
  onDelete,
}: {
  agent: AgentConfig;
  selected: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onClone: () => void;
  onDelete: () => void;
}) {
  return (
    <Card className={cn("transition hover:-translate-y-0.5 hover:border-slate-300", selected && "border-fuchsia-300 ring-2 ring-fuchsia-100")}>
      <CardContent className="p-4">
        <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 text-left">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-fuchsia-50 text-fuchsia-700">
            <Bot size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-semibold text-slate-950">{agent.name}</h2>
              {agent.is_builtin ? <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">内置</span> : null}
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{agent.description || "未填写描述"}</p>
          </div>
        </button>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <Meta icon={Zap} label="模型" value={agent.model_name || "默认"} />
          <Meta icon={Brain} label="思考" value={REASONING.find((item) => item.id === agent.reasoning_mode)?.label ?? "思考"} />
          <Meta icon={Database} label="知识库" value={agent.kb_ids.length} />
          <Meta icon={Wrench} label="Skills/MCP" value={`${agent.skill_ids.length}/${agent.mcp_ids.length}`} />
        </div>

        <div className="mt-4 flex items-center gap-2">
          <button type="button" onClick={onEdit} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50">
            <Save size={13} />
            配置
          </button>
          <button type="button" onClick={onClone} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100" title="复制">
            <Copy size={14} />
          </button>
          {!agent.is_builtin ? (
            <button type="button" onClick={onDelete} className="ml-auto flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-rose-50 hover:text-rose-600" title="删除">
              <Trash2 size={14} />
            </button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function AgentFormPanel({
  form,
  editing,
  models,
  kbs,
  skills,
  mcp,
  supportedModes,
  saving,
  onSubmit,
}: {
  form: ReturnType<typeof useForm<AgentForm>>;
  editing: AgentConfig | null;
  models: Model[];
  kbs: Array<{ id: string; label: string }>;
  skills: Array<{ id: string; label: string }>;
  mcp: Array<{ id: string; label: string }>;
  supportedModes: ReasoningMode[];
  saving: boolean;
  onSubmit: (values: AgentForm) => void;
}) {
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>{editing ? "编辑 Agent" : "新建 Agent"}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <Field label="名称" error={form.formState.errors.name?.message}>
            <input {...form.register("name")} className={inputClass} placeholder="例如：产品分析助手" />
          </Field>
          <Field label="描述">
            <textarea {...form.register("description")} className={cn(inputClass, "min-h-20 resize-none")} placeholder="说明这个 Agent 的职责和使用场景" />
          </Field>
          <Field label="系统提示词">
            <textarea {...form.register("system_prompt")} className={cn(inputClass, "min-h-24 resize-none font-mono text-xs")} placeholder="可选：覆盖默认系统提示词" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="基础类型">
              <select {...form.register("base_type")} className={inputClass}>
                <option value="chatbot">智能对话</option>
                <option value="deep_research">深度研究</option>
              </select>
            </Field>
            <Field label="默认模型">
              <select {...form.register("model_name")} className={inputClass}>
                <option value="">系统默认</option>
                {models.map((model) => (
                  <option key={model.name} value={model.name}>
                    {modelLabel(model)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="思考模式">
            <Controller
              control={form.control}
              name="reasoning_mode"
              render={({ field }) => (
                <div className="grid grid-cols-4 gap-1">
                  {REASONING.map((mode) => {
                    const disabled = !supportedModes.includes(mode.id);
                    return (
                      <button
                        key={mode.id}
                        type="button"
                        disabled={disabled}
                        onClick={() => field.onChange(mode.id)}
                        className={cn(
                          "rounded-lg border px-2 py-2 text-xs font-semibold",
                          field.value === mode.id ? "border-fuchsia-300 bg-fuchsia-50 text-fuchsia-800" : "border-slate-200 text-slate-600",
                          disabled && "cursor-not-allowed opacity-35",
                        )}
                      >
                        {mode.label}
                      </button>
                    );
                  })}
                </div>
              )}
            />
          </Field>
          <MultiSelect control={form.control} name="kb_ids" title="绑定知识库" items={kbs} />
          <MultiSelect control={form.control} name="skill_ids" title="绑定 Skills" items={skills} />
          <MultiSelect control={form.control} name="mcp_ids" title="绑定 MCP" items={mcp} />
          <Controller
            control={form.control}
            name="allow_subagents"
            render={({ field }) => (
              <label className="flex items-center justify-between rounded-lg border border-slate-200 p-3 text-sm">
                <span className="flex items-center gap-2 text-slate-700">
                  <GitBranch size={14} />
                  允许调用其他 Agent
                </span>
                <input type="checkbox" checked={field.value} onChange={(event) => field.onChange(event.target.checked)} />
              </label>
            )}
          />
          <button
            type="submit"
            disabled={saving}
            className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <Save size={15} />
            {saving ? "保存中..." : "保存 Agent"}
          </button>
        </form>
      </CardContent>
    </Card>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-fuchsia-300 focus:ring-2 focus:ring-fuchsia-100";

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium text-slate-600">
      <span>{label}</span>
      <div className="mt-1">{children}</div>
      {error ? <p className="mt-1 text-xs text-rose-600">{error}</p> : null}
    </label>
  );
}

function MultiSelect({
  control,
  name,
  title,
  items,
}: {
  control: ReturnType<typeof useForm<AgentForm>>["control"];
  name: "kb_ids" | "skill_ids" | "mcp_ids";
  title: string;
  items: Array<{ id: string; label: string }>;
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => {
        const selected = field.value ?? [];
        const toggle = (id: string) => {
          field.onChange(selected.includes(id) ? selected.filter((item: string) => item !== id) : [...selected, id]);
        };
        return (
          <div className="rounded-lg border border-slate-200 p-3">
            <div className="mb-2 flex items-center justify-between text-xs font-medium text-slate-600">
              <span>{title}</span>
              <span className="text-slate-400">{selected.length}</span>
            </div>
            <div className="max-h-28 space-y-1 overflow-y-auto">
              {items.length === 0 ? (
                <p className="text-xs text-slate-400">暂无可选项</p>
              ) : (
                items.map((item) => (
                  <label key={item.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-slate-50">
                    <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} />
                    <span className="truncate">{item.label}</span>
                  </label>
                ))
              )}
            </div>
          </div>
        );
      }}
    />
  );
}

function Meta({ icon: Icon, label, value }: { icon: typeof Bot; label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-slate-50 p-2">
      <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
        <Icon size={12} />
        {label}
      </div>
      <div className="mt-1 truncate text-xs font-semibold text-slate-800">{value}</div>
    </div>
  );
}

function FlowNode({ data }: NodeProps<{ label: string; icon: string; count?: number }>) {
  return (
    <div className="min-w-36 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />
      <div className="text-xs font-semibold text-slate-900">{data.label}</div>
      {data.count !== undefined ? <div className="mt-1 text-[11px] text-slate-500">{data.count} 项</div> : null}
      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
    </div>
  );
}

function dedupeModels(models: Model[]) {
  const byName = new Map<string, Model>();
  for (const model of models) {
    const existing = byName.get(model.name);
    if (!existing) {
      byName.set(model.name, model);
      continue;
    }
    const existingScore = Number(existing.is_default) * 4 + Number(existing.api_key_configured) * 2 + Number(existing.source === "db");
    const nextScore = Number(model.is_default) * 4 + Number(model.api_key_configured) * 2 + Number(model.source === "db");
    if (nextScore > existingScore) byName.set(model.name, model);
  }
  return Array.from(byName.values());
}

function modelLabel(model: Model) {
  const label = model.display_name || model.model || model.name;
  return model.provider_name ? `${label} · ${model.provider_name}` : label;
}

function buildFlow(agent?: AgentConfig): { nodes: Node[]; edges: Edge[] } {
  if (!agent) return { nodes: [], edges: [] };
  const nodes: Node[] = [
    { id: "agent", type: "agent", position: { x: 0, y: 130 }, data: { label: agent.name, icon: "agent" } },
    { id: "model", type: "agent", position: { x: 260, y: 20 }, data: { label: agent.model_name || "系统默认模型", icon: "model" } },
    { id: "kb", type: "agent", position: { x: 260, y: 120 }, data: { label: "知识库", icon: "kb", count: agent.kb_ids.length } },
    { id: "tools", type: "agent", position: { x: 260, y: 220 }, data: { label: "Skills / MCP", icon: "tools", count: agent.skill_ids.length + agent.mcp_ids.length } },
    { id: "subagents", type: "agent", position: { x: 520, y: 130 }, data: { label: agent.allow_subagents ? "可调用 Agent 开启" : "可调用 Agent 关闭", icon: "subagents" } },
  ];
  const edges: Edge[] = [
    { id: "agent-model", source: "agent", target: "model", animated: true },
    { id: "agent-kb", source: "agent", target: "kb" },
    { id: "agent-tools", source: "agent", target: "tools" },
    { id: "tools-subagents", source: "tools", target: "subagents", animated: agent.allow_subagents },
  ];
  return { nodes, edges };
}
