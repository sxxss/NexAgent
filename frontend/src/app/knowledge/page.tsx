"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Database,
  FileText,
  Layers,
  Loader2,
  Network,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import {
  createKB,
  deleteKB,
  fetchKBs,
  fetchProviders,
  testProviderModel,
  updateKBModelConfig,
  type KBMeta,
  type ModelProbeResult,
  type ModelProvider,
  type ProviderCapability,
  type ProviderModelConfig,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

type KBKind = "milvus" | "lightrag";

interface ProviderModelOption {
  value: string;
  providerId: string;
  providerName: string;
  modelId: string;
  label: string;
  detail: string;
  dimension?: number | null;
}

const initialForm = {
  name: "",
  description: "",
  kb_type: "milvus" as KBKind,
  chunk_size: 512,
  chunk_overlap: 64,
  chunk_preset_id: "general" as "general" | "qa" | "book" | "laws" | "paper",
  embed_model: "",
  embed_dimension: 1024,
  use_reranker: false,
  reranker_model: "",
};

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(initialForm);
  const [probeResult, setProbeResult] = useState<ModelProbeResult | null>(null);
  const [probeError, setProbeError] = useState("");

  const kbsQuery = useQuery({ queryKey: ["kbs"], queryFn: fetchKBs });
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const providers = useMemo(() => providersQuery.data ?? [], [providersQuery.data]);
  const embeddingModels = useMemo(() => providerModelOptions(providers, "embedding"), [providers]);
  const rerankModels = useMemo(() => providerModelOptions(providers, "rerank"), [providers]);
  const filtered = kbs.filter((kb) => `${kb.name} ${kb.description ?? ""}`.toLowerCase().includes(search.toLowerCase()));

  const selectedEmbedding = embeddingModels.find((item) => item.value === form.embed_model);
  const selectedReranker = rerankModels.find((item) => item.value === form.reranker_model);

  const createMutation = useMutation({
    mutationFn: async () => {
      const kb = await createKB({
        name: form.name.trim(),
        description: form.description.trim(),
        kb_type: form.kb_type,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
        chunk_preset_id: form.chunk_preset_id,
        embed_model: form.embed_model || undefined,
        embed_dimension: form.embed_dimension || undefined,
      });
      if (form.use_reranker || form.reranker_model) {
        await updateKBModelConfig(kb.kb_id, {
          use_reranker: form.use_reranker,
          reranker_model: form.reranker_model,
        });
      }
      return kb;
    },
    onSuccess: async () => {
      setShowCreate(false);
      setForm(initialForm);
      setProbeResult(null);
      setProbeError("");
      await queryClient.invalidateQueries({ queryKey: ["kbs"] });
    },
  });

  const testModelMutation = useMutation({
    mutationFn: ({ option, capability }: { option: ProviderModelOption; capability: "embedding" | "rerank" }) =>
      testProviderModel({
        provider_id: option.providerId,
        model_id: option.modelId,
        capability,
        sample_text: "NexAgent knowledge base model test",
      }),
    onSuccess: (result) => {
      setProbeResult(result);
      setProbeError("");
      if (result.dimension && result.capability === "embedding") {
        setForm((prev) => ({ ...prev, embed_dimension: result.dimension ?? prev.embed_dimension }));
      }
    },
    onError: (error) => {
      setProbeResult(null);
      setProbeError(error instanceof Error ? error.message : "模型检测失败");
    },
  });

  const resetDialog = () => {
    setShowCreate(false);
    setProbeResult(null);
    setProbeError("");
  };

  const submitDisabled = !form.name.trim() || !form.embed_model || createMutation.isPending;

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Knowledge Hub"
        title="知识库"
        description="管理 Agent 可检索的私有知识。向量 RAG 负责语义召回，LightRAG 负责实体关系与图谱增强。"
        actions={
          <>
            <button type="button" onClick={() => void kbsQuery.refetch()} className={outlineButton}>
              <RefreshCw size={14} className={kbsQuery.isFetching ? "animate-spin" : ""} />
              刷新
            </button>
            <button type="button" onClick={() => setShowCreate(true)} className={primarySmallButton}>
              <Plus size={14} />
              新建知识库
            </button>
          </>
        }
      />

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="grid gap-4 md:grid-cols-3">
          <Stat label="知识库总数" value={kbs.length} icon={Database} />
          <Stat label="向量 RAG" value={kbs.filter((item) => item.kb_type === "milvus").length} icon={Layers} />
          <Stat label="LightRAG 图谱" value={kbs.filter((item) => item.kb_type === "lightrag").length} icon={Network} />
        </div>

        <div className="mt-5 flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 shadow-sm">
          <Search size={16} className="text-slate-400" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索知识库名称或描述"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
        </div>

        <div className="mt-5">
          {kbsQuery.isLoading ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[1, 2, 3].map((item) => <div key={item} className="h-52 animate-pulse rounded-xl bg-white" />)}</div>
          ) : filtered.length === 0 ? (
            <Empty onCreate={() => setShowCreate(true)} />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {filtered.map((kb) => (
                <KBCard
                  key={kb.kb_id}
                  kb={kb}
                  onDelete={() => void deleteKB(kb.kb_id).then(() => queryClient.invalidateQueries({ queryKey: ["kbs"] }))}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      <Dialog
        open={showCreate}
        onClose={resetDialog}
        title="新建知识库"
        description="选择知识库类型、Embedding 模型和检索增强配置。创建后进入详情页上传并入库文件。"
        className="max-w-5xl"
        contentClassName="bg-slate-50"
      >
        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-4">
            <FormSection title="基础信息" description="名称用于 Agent 选择和评估结果展示。">
              <Field label="名称" required>
                <input className={inputClass} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：产品文档知识库" />
              </Field>
              <Field label="描述">
                <textarea className={`${inputClass} min-h-20 resize-none`} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="描述知识库内容、适用 Agent 或维护范围" />
              </Field>
              <Field label="知识库类型" required>
                <div className="grid gap-3 sm:grid-cols-2">
                  <TypeCard
                    active={form.kb_type === "milvus"}
                    icon={Layers}
                    title="向量 RAG"
                    description="适合文档问答、引用召回、RAG 评估。支持向量、关键词和混合检索。"
                    onClick={() => setForm({ ...form, kb_type: "milvus" })}
                  />
                  <TypeCard
                    active={form.kb_type === "lightrag"}
                    icon={Network}
                    title="LightRAG 图谱"
                    description="适合实体关系、图谱浏览和跨文档关联分析。"
                    onClick={() => setForm({ ...form, kb_type: "lightrag" })}
                  />
                </div>
              </Field>
            </FormSection>

            <FormSection title="Embedding 配置" description="从设置页已添加的模型供应商中选择 embedding 模型。保存时使用 provider::model，避免同名模型串供应商。">
              <Field label="Embedding 模型" required hint="只显示已启用供应商中标记为 embedding 的模型。">
                <ModelPicker
                  value={form.embed_model}
                  options={embeddingModels}
                  placeholder={providersQuery.isLoading ? "加载模型中..." : "选择 Embedding 模型"}
                  onChange={(option) => {
                    setForm({ ...form, embed_model: option.value, embed_dimension: option.dimension || form.embed_dimension });
                    setProbeResult(null);
                    setProbeError("");
                  }}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                <Field label="向量维度" hint="检测成功后会自动填入返回维度。">
                  <input className={inputClass} type="number" min={1} max={8192} value={form.embed_dimension} onChange={(event) => setForm({ ...form, embed_dimension: Number(event.target.value) })} />
                </Field>
                <button
                  type="button"
                  className={cn(outlineButton, "mt-6 justify-center")}
                  disabled={!selectedEmbedding || testModelMutation.isPending}
                  onClick={() => selectedEmbedding && testModelMutation.mutate({ option: selectedEmbedding, capability: "embedding" })}
                >
                  {testModelMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  检测模型
                </button>
              </div>
              <ProbeNotice result={probeResult} error={probeError} />
            </FormSection>

            <FormSection title="分块与检索增强" description="分块参数会影响后续入库结果。Rerank 可先关闭，之后在详情页随时开启。">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Chunk preset">
                  <select className={inputClass} value={form.chunk_preset_id} onChange={(event) => setForm({ ...form, chunk_preset_id: event.target.value as typeof form.chunk_preset_id })}>
                    <option value="general">General</option>
                    <option value="qa">QA</option>
                    <option value="book">Book</option>
                    <option value="laws">Laws</option>
                    <option value="paper">Paper</option>
                  </select>
                </Field>
                <Field label="分块大小">
                  <input className={inputClass} type="number" min={64} max={4096} value={form.chunk_size} onChange={(event) => setForm({ ...form, chunk_size: Number(event.target.value) })} />
                </Field>
                <Field label="重叠长度">
                  <input className={inputClass} type="number" min={0} max={512} value={form.chunk_overlap} onChange={(event) => setForm({ ...form, chunk_overlap: Number(event.target.value) })} />
                </Field>
              </div>
              <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-3">
                <div>
                  <p className="text-sm font-semibold text-slate-800">启用 Rerank</p>
                  <p className="text-xs text-slate-500">适合需要更高引用准确性的 RAG 场景。</p>
                </div>
                <input type="checkbox" checked={form.use_reranker} onChange={(event) => setForm({ ...form, use_reranker: event.target.checked })} />
              </label>
              {form.use_reranker ? (
                <Field label="Rerank 模型">
                  <ModelPicker value={form.reranker_model} options={rerankModels} placeholder="选择 Rerank 模型" onChange={(option) => setForm({ ...form, reranker_model: option.value })} />
                </Field>
              ) : null}
            </FormSection>
          </div>

          <aside className="space-y-4">
            <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-sm font-semibold text-slate-900">创建预览</p>
              <div className="mt-4 space-y-3 text-sm">
                <PreviewRow label="类型" value={form.kb_type === "milvus" ? "向量 RAG" : "LightRAG 图谱"} />
                <PreviewRow label="Embedding" value={selectedEmbedding?.label || "未选择"} />
                <PreviewRow label="维度" value={String(form.embed_dimension || "-")} />
                <PreviewRow label="分块" value={`${form.chunk_preset_id} · ${form.chunk_size} / ${form.chunk_overlap}`} />
                <PreviewRow label="Rerank" value={form.use_reranker ? (selectedReranker?.label || "已开启，未选择模型") : "关闭"} />
              </div>
              {embeddingModels.length === 0 ? (
                <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs leading-5 text-amber-700">
                  没有可用的 Embedding 模型。请先到设置页给供应商添加 embedding 类型模型并启用供应商。
                </div>
              ) : null}
            </div>

            <button type="button" disabled={submitDisabled} onClick={() => createMutation.mutate()} className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-slate-950 text-sm font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
              {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
              创建知识库
            </button>
            {createMutation.error ? (
              <div className="rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-700">
                {createMutation.error instanceof Error ? createMutation.error.message : "创建失败"}
              </div>
            ) : null}
          </aside>
        </div>
      </Dialog>
    </div>
  );
}

function KBCard({ kb, onDelete }: { kb: KBMeta; onDelete: () => void }) {
  const isRag = kb.kb_type === "milvus";
  const requiresReindex = Boolean(kb.extra?.requires_reindex);
  return (
    <Card className="group transition hover:-translate-y-0.5 hover:border-slate-300">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", isRag ? "bg-fuchsia-50 text-fuchsia-700" : "bg-violet-50 text-violet-700")}>{isRag ? <FileText size={20} /> : <Network size={20} />}</div>
          <button type="button" onClick={onDelete} className="hidden h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-600 group-hover:flex"><Trash2 size={14} /></button>
        </div>
        <div className="mt-4 flex items-start justify-between gap-2">
          <h2 className="truncate text-sm font-semibold text-slate-950">{kb.name}</h2>
          {requiresReindex ? <Badge variant="warning">需重建</Badge> : null}
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{kb.description || "未填写描述"}</p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          <Badge variant={isRag ? "teal" : "violet"}>{isRag ? "向量 RAG" : "LightRAG"}</Badge>
          <Badge variant="secondary">{kb.embed_info?.dimension || "-"} dim</Badge>
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
          <span className="truncate">{kb.embed_info?.model || "默认 Embedding"}</span>
          <span>{formatDate(kb.updated_at || kb.created_at)}</span>
        </div>
        <Link href={`/knowledge/${kb.kb_id}`} className="mt-4 inline-flex h-8 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50">
          打开
          <ChevronRight size={13} />
        </Link>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Database }) {
  return <Card><CardContent className="p-5"><div className="flex items-center gap-2 text-sm text-slate-500"><Icon size={16} />{label}</div><p className="mt-2 text-3xl font-semibold text-slate-950">{value}</p></CardContent></Card>;
}

function Empty({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white py-20 text-center">
      <Database size={32} className="text-slate-300" />
      <p className="mt-4 text-sm font-semibold text-slate-700">还没有知识库</p>
      <p className="mt-1 text-xs text-slate-400">新建一个向量 RAG 或 LightRAG 图谱知识库。</p>
      <button type="button" onClick={onCreate} className={cn(primarySmallButton, "mt-5")}><Plus size={14} />新建知识库</button>
    </div>
  );
}

function FormSection({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
        {description ? <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p> : null}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Field({ label, required, hint, children }: { label: string; required?: boolean; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-semibold text-slate-700">
        {label} {required ? <span className="text-rose-500">*</span> : null}
      </span>
      {children}
      {hint ? <span className="block text-[11px] leading-4 text-slate-400">{hint}</span> : null}
    </label>
  );
}

function TypeCard({ active, icon: Icon, title, description, onClick }: { active: boolean; icon: typeof Layers; title: string; description: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("rounded-xl border p-3 text-left transition", active ? "border-fuchsia-300 bg-fuchsia-50 text-fuchsia-800" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300")}
    >
      <div className="flex items-center gap-2 text-sm font-semibold"><Icon size={16} />{title}</div>
      <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
    </button>
  );
}

function ModelPicker({ value, options, placeholder, onChange }: { value: string; options: ProviderModelOption[]; placeholder: string; onChange: (option: ProviderModelOption) => void }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const selected = options.find((item) => item.value === value);
  const visible = options.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((next) => !next)} className="flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 text-left text-sm outline-none transition hover:border-slate-300 focus:border-fuchsia-300 focus:ring-2 focus:ring-fuchsia-100">
        <span className={cn("truncate", selected ? "font-semibold text-slate-800" : "text-slate-400")}>{selected?.label || placeholder}</span>
        <ChevronDown size={15} className={cn("shrink-0 text-slate-400 transition", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="absolute z-20 mt-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="border-b border-slate-100 p-2">
            <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="搜索模型或供应商" className="h-9 w-full rounded-lg bg-slate-50 px-3 text-sm outline-none" />
          </div>
          <div className="max-h-64 overflow-auto p-1">
            {visible.length ? visible.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option);
                  setOpen(false);
                  setFilter("");
                }}
                className={cn("flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left hover:bg-slate-50", value === option.value && "bg-fuchsia-50")}
              >
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[10px] font-bold text-slate-500">{option.providerName.slice(0, 1)}</span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-800">{option.label}</span>
                  <span className="block truncate text-xs text-slate-400">{option.detail}</span>
                </span>
              </button>
            )) : <p className="px-3 py-6 text-center text-xs text-slate-400">没有匹配的模型</p>}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProbeNotice({ result, error }: { result: ModelProbeResult | null; error: string }) {
  if (!result && !error) return null;
  if (error || result?.ok === false) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs leading-5 text-rose-700">
        <AlertCircle size={14} className="mt-0.5 shrink-0" />
        <span>{error || result?.message || "模型检测失败"}</span>
      </div>
    );
  }
  if (!result) return null;
  return (
    <div className="flex items-start gap-2 rounded-xl border border-emerald-100 bg-emerald-50 p-3 text-xs leading-5 text-emerald-700">
      <CheckCircle size={14} className="mt-0.5 shrink-0" />
      <span>{result.message} {result.dimension ? `维度 ${result.dimension}，` : ""}耗时 {result.latency_ms}ms。</span>
    </div>
  );
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-2 last:border-0 last:pb-0">
      <span className="shrink-0 text-xs text-slate-400">{label}</span>
      <span className="min-w-0 text-right text-xs font-semibold text-slate-700">{value}</span>
    </div>
  );
}

function providerModelOptions(providers: ModelProvider[], capability: ProviderCapability): ProviderModelOption[] {
  return providers
    .filter((provider) => provider.is_enabled && (provider.capabilities ?? []).includes(capability))
    .flatMap((provider) => {
      const configs = provider.model_configs?.length
        ? provider.model_configs.filter((model) => model.type === capability)
        : provider.models.map((id): ProviderModelConfig => ({ id, display_name: id, type: capability }));
      return configs.map((model) => ({
        value: `${provider.id}::${model.id}`,
        providerId: provider.id,
        providerName: provider.name,
        modelId: model.id,
        label: `${model.display_name || model.id} · ${provider.name}`,
        detail: `${model.id}${model.dimension ? ` · ${model.dimension} dim` : ""}`,
        dimension: model.dimension,
      }));
    });
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-fuchsia-300 focus:ring-2 focus:ring-fuchsia-100 disabled:bg-slate-50 disabled:text-slate-400";
const outlineButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50";
const primarySmallButton = "inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
