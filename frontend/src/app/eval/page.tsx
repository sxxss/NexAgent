"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle,
  ChevronDown,
  Clock,
  Database,
  FlaskConical,
  Layers,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import {
  createEvalSuite,
  deleteEvalSuite,
  fetchEvalResults,
  fetchEvalSuites,
  fetchKBQueryConfig,
  fetchKBs,
  fetchModels,
  generateEvalSuiteDraft,
  runEvalSuite,
  type EvalGenerationDiagnostic,
  type EvalResult,
  type EvalSample,
  type EvalScores,
  type EvalSuite,
  type EvalSuiteDraft,
  type EvalType,
  type KBMeta,
  type Model,
  type RetrievalConfig,
  type RetrievalMode,
} from "@/lib/api";
import { cn, formatDate } from "@/lib/utils";

type KBKind = "milvus" | "lightrag" | "mixed" | "none";

interface SuiteForm {
  name: string;
  type: EvalType;
  agent: string;
  model: string;
  kbIds: string[];
  tags: string;
  retrievalOverrideEnabled: boolean;
  retrievalConfig: RetrievalConfig;
  samples: EvalSample[];
}

interface GenerateForm {
  name: string;
  source: "knowledge" | "recent_logs" | "manual";
  count: number;
  kbIds: string[];
  topic: string;
  model: string;
  tags: string;
  retrievalOverrideEnabled: boolean;
  retrievalConfig: RetrievalConfig;
}

const evalTypes: { value: EvalType; label: string; hint: string; icon: LucideIcon; advanced?: boolean }[] = [
  { value: "rag", label: "RAG", hint: "评估知识库召回、证据与答案质量", icon: Database },
  { value: "agent", label: "Agent", hint: "高级：评估 Agent 输出稳定性", icon: FlaskConical, advanced: true },
  { value: "tool", label: "Tool", hint: "高级：评估工具调用是否符合预期", icon: Layers, advanced: true },
  { value: "task", label: "Task", hint: "高级：评估长任务完成状态", icon: Clock, advanced: true },
];

const milvusModes = [
  { value: "vector", label: "向量检索" },
  { value: "keyword", label: "关键词检索" },
  { value: "hybrid", label: "混合检索" },
];

const lightragModes = [
  { value: "lightrag_local", label: "Local 图谱上下文" },
  { value: "lightrag_global", label: "Global 全局社区" },
  { value: "lightrag_hybrid", label: "Hybrid 图谱混合" },
];

const defaultMilvusConfig: RetrievalConfig = {
  mode: "hybrid",
  search_mode: "hybrid",
  recall_top_k: 30,
  final_top_k: 10,
  similarity_threshold: 0,
  vector_weight: 0.7,
  keyword_weight: 0.3,
  bm25_weight: 0.3,
  bm25_top_k: 30,
  use_reranker: false,
};

const defaultLightRagConfig: RetrievalConfig = {
  mode: "lightrag_hybrid",
  search_mode: "lightrag_hybrid",
  recall_top_k: 30,
  final_top_k: 10,
  graph_depth: 2,
  graph_limit: 80,
};

const emptySample = (): EvalSample => ({
  id: `sample-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
  query: "",
  expected: "",
  expected_answer: "",
  expected_sources: [],
  expected_tools: [],
  tags: [],
  difficulty: "normal",
  notes: "",
});

const emptyForm = (): SuiteForm => ({
  name: "",
  type: "rag",
  agent: "chatbot",
  model: "",
  kbIds: [],
  tags: "",
  retrievalOverrideEnabled: false,
  retrievalConfig: defaultMilvusConfig,
  samples: [emptySample()],
});

const emptyGenerateForm = (): GenerateForm => ({
  name: "",
  source: "knowledge",
  count: 5,
  kbIds: [],
  topic: "",
  model: "",
  tags: "generated",
  retrievalOverrideEnabled: false,
  retrievalConfig: defaultMilvusConfig,
});

export default function EvalPage() {
  const queryClient = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [showGenerate, setShowGenerate] = useState(false);
  const [form, setForm] = useState<SuiteForm>(() => emptyForm());
  const [generateForm, setGenerateForm] = useState<GenerateForm>(() => emptyGenerateForm());
  const [bulkText, setBulkText] = useState("");
  const [draftSuite, setDraftSuite] = useState<EvalSuiteDraft | null>(null);
  const [diagnostics, setDiagnostics] = useState<EvalGenerationDiagnostic[]>([]);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const [runErrors, setRunErrors] = useState<Record<string, string>>({});
  const [detailResult, setDetailResult] = useState<EvalResult | null>(null);
  const [tagFilter, setTagFilter] = useState("");

  const suitesQuery = useQuery({ queryKey: ["eval-suites", tagFilter], queryFn: () => fetchEvalSuites(tagFilter || undefined) });
  const resultsQuery = useQuery({ queryKey: ["eval-results"], queryFn: () => fetchEvalResults() });
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const kbsQuery = useQuery({ queryKey: ["kbs"], queryFn: fetchKBs });

  const suites = useMemo(() => suitesQuery.data ?? [], [suitesQuery.data]);
  const results = useMemo(() => resultsQuery.data ?? [], [resultsQuery.data]);
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const selectedKbs = useMemo(() => kbs.filter((kb) => form.kbIds.includes(kb.kb_id)), [form.kbIds, kbs]);
  const generateKbs = useMemo(() => kbs.filter((kb) => generateForm.kbIds.includes(kb.kb_id)), [generateForm.kbIds, kbs]);
  const kbKind = inferKbKind(selectedKbs);
  const generateKbKind = inferKbKind(generateKbs);

  const singleKbConfigQuery = useQuery({
    queryKey: ["kb-query-config", form.kbIds[0]],
    enabled: form.kbIds.length === 1,
    queryFn: () => fetchKBQueryConfig(form.kbIds[0]),
  });

  const latestBySuite = useMemo(() => {
    const map = new Map<string, EvalResult>();
    for (const result of results) {
      const key = result.suite_id || result.test_id;
      if (!map.has(key)) map.set(key, result);
    }
    return map;
  }, [results]);
  const tags = useMemo(() => Array.from(new Set(suites.flatMap((suite) => suite.tags))).sort(), [suites]);
  const passed = results.filter((result) => result.passed === true).length;
  const failed = results.filter((result) => result.passed === false).length;
  const scored = passed + failed;
  const formErrors = validateSuiteForm(form, selectedKbs);
  const generateErrors = validateGenerateForm(generateForm, generateKbs);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["eval-suites"] });
    void queryClient.invalidateQueries({ queryKey: ["eval-results"] });
  };

  const createMutation = useMutation({
    mutationFn: () => createEvalSuite(formToPayload(form, selectedKbs)),
    onSuccess: () => {
      setShowCreate(false);
      setForm(emptyForm());
      setBulkText("");
      refresh();
    },
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateEvalSuiteDraft({
        name: generateForm.name || "AI 生成评估集",
        source: generateForm.source,
        type: "rag",
        count: generateForm.count,
        kb_ids: generateForm.kbIds,
        model: generateForm.model,
        tags: splitList(generateForm.tags),
        topic: generateForm.topic,
        retrieval_override_enabled: generateForm.retrievalOverrideEnabled && generateKbKind !== "mixed",
        retrieval_config: generateForm.retrievalOverrideEnabled && generateKbKind !== "mixed" ? cleanConfigForKind(generateForm.retrievalConfig, generateKbKind) : {},
      }),
    onSuccess: (result) => {
      setDraftSuite(result.suite);
      setDiagnostics(result.diagnostics ?? []);
    },
  });

  const saveDraftMutation = useMutation({
    mutationFn: () => {
      if (!draftSuite) throw new Error("没有可保存的草稿。");
      return createEvalSuite({
        name: draftSuite.name,
        type: draftSuite.type,
        agent: draftSuite.agent,
        model: draftSuite.model,
        kb_ids: draftSuite.kb_ids,
        retrieval_override_enabled: Boolean(draftSuite.retrieval_override_enabled),
        retrieval_config: draftSuite.retrieval_config ?? {},
        samples: draftSuite.samples,
        generation_source: draftSuite.generation_source,
        generated_by_ai: true,
        tags: draftSuite.tags,
      });
    },
    onSuccess: () => {
      setShowGenerate(false);
      setDraftSuite(null);
      setDiagnostics([]);
      setGenerateForm(emptyGenerateForm());
      refresh();
    },
  });

  const runOne = async (suite: EvalSuite) => {
    setRunningIds((prev) => new Set(prev).add(suite.id));
    setRunErrors((prev) => ({ ...prev, [suite.id]: "" }));
    try {
      await runEvalSuite(suite.id, suite.model || undefined);
      refresh();
    } catch (error) {
      setRunErrors((prev) => ({ ...prev, [suite.id]: errorMessage(error) }));
    } finally {
      setRunningIds((prev) => {
        const next = new Set(prev);
        next.delete(suite.id);
        return next;
      });
    }
  };

  const runAllMutation = useMutation({
    mutationFn: async () => {
      for (const suite of suites) await runEvalSuite(suite.id, suite.model || undefined);
    },
    onSuccess: refresh,
  });

  const applyKbDefaults = () => {
    const cfg = singleKbConfigQuery.data?.effective_config;
    if (cfg) setForm((prev) => ({ ...prev, retrievalConfig: cfg }));
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Evaluation"
        title="评估系统"
        description="用评估集批量验证知识库召回、证据引用和答案一致性。"
        actions={
          <>
            <SelectBox value={tagFilter} placeholder="全部标签" options={[{ value: "", label: "全部标签" }, ...tags.map((tag) => ({ value: tag, label: tag }))]} onChange={setTagFilter} className="w-36" />
            <button type="button" onClick={refresh} className={outlineButton}>
              <RefreshCw size={14} className={suitesQuery.isFetching || resultsQuery.isFetching ? "animate-spin" : ""} />
              刷新
            </button>
            <button type="button" disabled={runAllMutation.isPending || suites.length === 0} onClick={() => runAllMutation.mutate()} className={outlineButton}>
              {runAllMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              运行全部
            </button>
            <button type="button" onClick={() => setShowGenerate(true)} className={outlineButton}>
              <Sparkles size={14} />
              AI 生成
            </button>
            <button type="button" onClick={() => setShowCreate(true)} className={primaryHeaderButton}>
              <Plus size={14} />
              新建评估集
            </button>
          </>
        }
      />

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="grid gap-4 md:grid-cols-4">
          <Stat label="评估集" value={suites.length} icon={FlaskConical} />
          <Stat label="样本数" value={suites.reduce((sum, suite) => sum + suite.samples.length, 0)} icon={Database} />
          <Stat label="通过率" value={scored ? `${Math.round((passed / scored) * 100)}%` : "-"} icon={CheckCircle} />
          <Stat label="失败" value={failed} icon={XCircle} />
        </div>

        <section className="mt-5 space-y-3">
          <MetricExplanation />
          {suites.length === 0 ? (
            <EmptyState onCreate={() => setShowCreate(true)} onGenerate={() => setShowGenerate(true)} />
          ) : (
            suites.map((suite) => (
              <SuiteRow
                key={suite.id}
                suite={suite}
                kbs={kbs}
                result={latestBySuite.get(suite.id)}
                running={runningIds.has(suite.id)}
                runError={runErrors[suite.id]}
                onRun={() => void runOne(suite)}
                onDelete={() => void deleteEvalSuite(suite.id).then(refresh)}
                onDetails={(result) => setDetailResult(result)}
              />
            ))
          )}
        </section>
      </main>

      <Dialog open={showCreate} onClose={() => setShowCreate(false)} title="新建评估集" description="一个评估集包含多条样本，默认使用知识库自己的检索策略。" className="max-w-[1180px]" contentClassName="max-h-none overflow-hidden p-0">
        <div className="grid h-[calc(100vh-10rem)] min-h-0 gap-5 overflow-hidden p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-h-0 space-y-5 overflow-y-auto pr-1">
            <FormSection title="基础信息" description="主路径是 RAG 评估；Agent、Tool、Task 保留为高级实验能力。">
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_520px]">
                <Field label="名称" required>
                  <input className={inputClass} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：产品文档 RAG 回归集" />
                </Field>
                <Field label="类型" required>
                  <TypeSelector value={form.type} onChange={(type) => setForm({ ...form, type })} />
                </Field>
              </div>
              <Field label="标签">
                <input className={inputClass} value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder="smoke, rag, release-guard" />
              </Field>
            </FormSection>

            <FormSection title="知识库范围" description="Milvus 与 LightRAG 使用不同策略。混合选择时会分别使用各知识库默认策略。">
              <KnowledgeSelector value={form.kbIds} required={form.type === "rag"} kbs={kbs} onChange={(kbIds) => setForm({ ...form, kbIds, retrievalOverrideEnabled: false, retrievalConfig: configForKind(inferKbKind(kbs.filter((kb) => kbIds.includes(kb.kb_id)))) })} />
              <KbStrategyNotice kind={kbKind} selected={selectedKbs} />
            </FormSection>

            <FormSection title="样本数据" description="每条样本包含测试问题、期望答案和可选来源。支持手动维护或批量导入。">
              <SampleEditor samples={form.samples} onChange={(samples) => setForm({ ...form, samples })} />
              <BulkImport value={bulkText} onChange={setBulkText} onImport={() => setForm({ ...form, samples: [...form.samples.filter((sample) => sample.query.trim()), ...parseBulkSamples(bulkText)] })} />
            </FormSection>

            <FormSection title="运行配置">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Agent">
                  <SelectBox value={form.agent} options={[{ value: "chatbot", label: "智能对话" }, { value: "deep_research", label: "深度研究" }]} onChange={(agent) => setForm({ ...form, agent })} />
                </Field>
                <Field label="模型">
                  <ModelSelect value={form.model} onChange={(model) => setForm({ ...form, model })} models={modelsQuery.data ?? []} />
                </Field>
              </div>
            </FormSection>

            <FormSection title="高级配置" description="默认跟随知识库配置。只有做策略对比时才打开覆盖。">
              <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                <span>
                  <span className="block font-semibold">覆盖知识库检索策略</span>
                  <span className="text-xs text-slate-400">混合 Milvus 和 LightRAG 时不能统一覆盖。</span>
                </span>
                <input type="checkbox" checked={form.retrievalOverrideEnabled} disabled={kbKind === "mixed" || kbKind === "none"} onChange={(event) => setForm({ ...form, retrievalOverrideEnabled: event.target.checked })} />
              </label>
              {form.retrievalOverrideEnabled ? (
                <RetrievalConfigEditor kind={kbKind} value={form.retrievalConfig} onChange={(retrievalConfig) => setForm({ ...form, retrievalConfig })} onUseKbDefault={applyKbDefaults} />
              ) : (
                <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">运行时会记录实际检索配置，但不会在评估集里覆盖知识库默认值。</p>
              )}
            </FormSection>

            {formErrors.length ? <ErrorList items={formErrors} /> : null}
          </div>

          <aside className="min-h-0 space-y-3 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <SuitePreview form={form} selectedKbs={selectedKbs} />
            <button type="button" disabled={formErrors.length > 0 || createMutation.isPending} onClick={() => createMutation.mutate()} className={primaryButton}>
              {createMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
              创建评估集
            </button>
          </aside>
        </div>
      </Dialog>

      <Dialog open={showGenerate} onClose={() => setShowGenerate(false)} title="AI 生成评估集草稿" description="从可用知识库片段生成多条样本，确认和编辑后再保存。" className="max-w-[1280px]" contentClassName="max-h-none overflow-hidden p-0">
        <div className="grid h-[calc(100vh-10rem)] min-h-0 gap-5 overflow-hidden p-5 lg:grid-cols-[380px_minmax(0,1fr)]">
          <div className="min-h-0 space-y-4 overflow-y-auto pr-1">
            <FormSection title="生成设置">
              <Field label="评估集名称">
                <input className={inputClass} value={generateForm.name} onChange={(event) => setGenerateForm({ ...generateForm, name: event.target.value })} placeholder="例如：核心知识库回归集" />
              </Field>
              <Field label="来源">
                <SelectBox value={generateForm.source} options={[{ value: "knowledge", label: "知识库片段" }, { value: "recent_logs", label: "最近调用日志" }, { value: "manual", label: "手动主题" }]} onChange={(source) => setGenerateForm({ ...generateForm, source: source as GenerateForm["source"] })} />
              </Field>
              <Field label="数量">
                <input className={inputClass} type="number" min={1} max={20} value={generateForm.count} onChange={(event) => setGenerateForm({ ...generateForm, count: Number(event.target.value) })} />
              </Field>
              <Field label="主题">
                <textarea className={`${inputClass} min-h-20 resize-none`} value={generateForm.topic} onChange={(event) => setGenerateForm({ ...generateForm, topic: event.target.value })} placeholder="可选。作为抽样偏好，不会因为没有匹配而直接失败。" />
              </Field>
              <Field label="模型">
                <ModelSelect value={generateForm.model} onChange={(model) => setGenerateForm({ ...generateForm, model })} models={modelsQuery.data ?? []} />
              </Field>
            </FormSection>

            <FormSection title="知识库范围">
              <KnowledgeSelector value={generateForm.kbIds} required={generateForm.source === "knowledge"} kbs={kbs} onChange={(kbIds) => setGenerateForm({ ...generateForm, kbIds, retrievalOverrideEnabled: false, retrievalConfig: configForKind(inferKbKind(kbs.filter((kb) => kbIds.includes(kb.kb_id)))) })} />
              <KbStrategyNotice kind={generateKbKind} selected={generateKbs} />
            </FormSection>

            <FormSection title="高级：检索策略覆盖" description="默认跟随知识库自己的检索配置。只有需要生成特定策略的评估集时才打开。">
              <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                <span>
                  <span className="block font-semibold">覆盖知识库默认检索配置</span>
                  <span className="text-xs text-slate-400">混合 Milvus 和 LightRAG 时会使用各自默认策略。</span>
                </span>
                <input type="checkbox" checked={generateForm.retrievalOverrideEnabled} disabled={generateKbKind === "mixed" || generateKbKind === "none"} onChange={(event) => setGenerateForm({ ...generateForm, retrievalOverrideEnabled: event.target.checked })} />
              </label>
              {generateForm.retrievalOverrideEnabled ? (
                <RetrievalConfigEditor kind={generateKbKind} value={generateForm.retrievalConfig} onChange={(retrievalConfig) => setGenerateForm({ ...generateForm, retrievalConfig })} />
              ) : (
                <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">生成草稿会记录实际策略，但不覆盖知识库默认配置。</p>
              )}
            </FormSection>

            <DiagnosticsPanel diagnostics={diagnostics} />
            {generateErrors.length ? <ErrorList items={generateErrors} /> : null}
            {generateMutation.error ? <ErrorList items={[errorMessage(generateMutation.error)]} /> : null}
            <button type="button" disabled={generateErrors.length > 0 || generateMutation.isPending} onClick={() => generateMutation.mutate()} className={primaryButton}>
              {generateMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {draftSuite ? "重新生成草稿" : "生成草稿"}
            </button>
          </div>

          <div className="min-h-0 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">草稿预览</h3>
                <p className="text-xs text-slate-500">保存前可以编辑每条样本；生成失败不会清空已有草稿。</p>
              </div>
              <button type="button" disabled={!draftSuite || saveDraftMutation.isPending} onClick={() => saveDraftMutation.mutate()} className={outlineButton}>
                {saveDraftMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                保存评估集
              </button>
            </div>
            {!draftSuite ? (
              <div className="flex h-[520px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white text-center">
                <Sparkles size={28} className="text-slate-300" />
                <p className="mt-3 text-sm font-semibold text-slate-600">还没有生成草稿</p>
                <p className="mt-1 text-xs text-slate-400">选择来源和知识库后点击生成。</p>
              </div>
            ) : (
              <div className="max-h-[calc(78vh-130px)] space-y-3 overflow-auto pr-1">
                <input className={inputClass} value={draftSuite.name} onChange={(event) => setDraftSuite({ ...draftSuite, name: event.target.value })} />
                <SampleEditor samples={draftSuite.samples} onChange={(samples) => setDraftSuite({ ...draftSuite, samples })} compact />
              </div>
            )}
          </div>
        </div>
      </Dialog>

      <ResultDialogV2 result={detailResult} onClose={() => setDetailResult(null)} results={results.filter((item) => item.suite_id && item.suite_id === detailResult?.suite_id)} suites={suites} kbs={kbs} />
    </div>
  );
}

function SuiteRow({ suite, kbs, result, running, runError, onRun, onDelete, onDetails }: { suite: EvalSuite; kbs: KBMeta[]; result?: EvalResult; running: boolean; runError?: string; onRun: () => void; onDelete: () => void; onDetails: (result: EvalResult) => void }) {
  const suiteKbs = resolveSuiteKbs(suite, kbs);
  const summaryScores = (result?.metrics ?? result?.scores) as EvalScores | undefined;
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <ResultIcon result={result} running={running} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-sm font-semibold text-slate-900">{suite.name}</h2>
              <Badge variant="info">{typeLabel(suite.type)}</Badge>
              <Badge variant="secondary">{suite.samples.length} samples</Badge>
              {suite.retrieval_override_enabled ? <Badge variant="warning">覆盖检索</Badge> : <Badge variant="success">跟随知识库</Badge>}
              {suite.generated_by_ai ? <Badge variant="violet">AI 生成</Badge> : null}
              {suite.tags.map((tag, index) => <span key={`${tag}-${index}`} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">{tag}</span>)}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {suiteKbs.length ? suiteKbs.slice(0, 4).map((kb) => (
                <span key={kb.kb_id} className="inline-flex max-w-[220px] items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600" title={kb.name}>
                  <Database size={12} />
                  <span className="truncate">{kb.name}</span>
                  <span className="text-slate-400">{kb.kb_type}</span>
                </span>
              )) : <span className="rounded-full bg-rose-50 px-2.5 py-1 text-[11px] font-semibold text-rose-600">未绑定知识库</span>}
              {suiteKbs.length > 4 ? <span className="text-[11px] text-slate-400">+{suiteKbs.length - 4}</span> : null}
            </div>
            <p className="mt-2 truncate text-xs text-slate-500">{suite.samples[0]?.query || "暂无样本"}</p>
            {result ? (
              <p className="mt-1 text-xs text-slate-400">{formatDate(result.timestamp)} / {result.latency_ms}ms / {result.judge_reason || "暂无评分说明"}</p>
            ) : null}
          </div>
          {runError ? <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs font-semibold text-rose-700 xl:max-w-xs">{runError}</p> : null}
          <details className="text-xs text-slate-500 xl:w-44">
            <summary className="cursor-pointer font-semibold text-slate-600">指标说明</summary>
            <MetricHelpCompact />
          </details>
          <ScorePills scores={summaryScores} />
          <button type="button" onClick={onRun} disabled={running} className={outlineButton}>{running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}运行</button>
          <button type="button" onClick={() => result && onDetails(result)} disabled={!result} className={outlineButton}>详情</button>
          <button type="button" onClick={onDelete} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-rose-50 hover:text-rose-600"><Trash2 size={14} /></button>
        </div>
      </CardContent>
    </Card>
  );
}

function ResultDialogV2({ result, results, suites, kbs, onClose }: { result: EvalResult | null; results: EvalResult[]; suites: EvalSuite[]; kbs: KBMeta[]; onClose: () => void }) {
  const visibleResults = results.length ? results : result ? [result] : [];
  const summary = summarizeResults(visibleResults);
  const suite = result ? suites.find((item) => item.id === result.suite_id || item.id === result.test_id) : undefined;
  const suiteKbs = suite ? resolveSuiteKbs(suite, kbs) : [];
  return (
    <Dialog open={Boolean(result)} onClose={onClose} title="评估结果详情" description="查看评分、证据、错误和样本级评估数据。" className="max-w-[1180px]" contentClassName="p-0">
      {!result ? null : (
        <div className="max-h-[78vh] space-y-5 overflow-y-auto p-6">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">{suite?.name || "评估结果"}</p>
                <p className="mt-1 text-xs text-slate-500">{suite?.retrieval_override_enabled ? "使用评估集覆盖检索策略" : "使用知识库默认检索策略"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {suiteKbs.length ? suiteKbs.map((kb) => <Badge key={kb.kb_id} variant={kb.kb_type === "lightrag" ? "violet" : "info"}>{kb.name} · {kb.kb_type}</Badge>) : <Badge variant="warning">未解析到知识库</Badge>}
              </div>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-5">
            <MetricCard label="样本数" value={summary.total} />
            <MetricCard label="通过率" value={summary.total ? `${Math.round(summary.passRate * 100)}%` : "-"} />
            <MetricCard label="平均耗时" value={`${summary.avgLatency}ms`} />
            <MetricCard label="Recall@5" value={formatScore(summary.metrics["recall@5"])} />
            <MetricCard label="答案匹配" value={formatScore(summary.metrics.answer_match)} />
          </div>

          {summary.warnings.length ? <WarningList warnings={summary.warnings} /> : null}

          <div className="rounded-2xl border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">样本明细</div>
            <div className="divide-y divide-slate-100">
              {visibleResults.map((item, index) => (
                <div key={item.run_id || `${item.sample_id || "sample"}-${index}`} className="grid gap-3 p-4 lg:grid-cols-[1fr_1fr]">
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-slate-900">{item.query}</p>
                    {item.error ? <p className="rounded-lg bg-rose-50 p-2 text-xs text-rose-700">{friendlyEvalError(item.error)}</p> : null}
                    <DetailBlock title="实际回答" value={item.actual_answer || item.response || "(empty)"} />
                    <DetailBlock title="期望来源" value={(item.gold_source_ids ?? []).join(", ") || "未配置"} />
                    <DetailBlock title="已检索来源" value={(item.retrieved_source_ids ?? []).join(", ") || "暂无"} />
                  </div>
                  <div className="space-y-2">
                    <ScoreGrid scores={(item.metrics ?? item.scores) as EvalScores} />
                    <MetricStrip metrics={(item.metrics ?? item.scores) as Record<string, number | null | undefined> | undefined} />
                    <EvidenceList evidence={(item.retrieved_chunks ?? item.evidence ?? []).slice(0, 5)} />
                    <DetailBlock title="检索策略" value={formatRetrievalConfig(item.retrieval_config)} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function ResultDialog({ result, results, onClose }: { result: EvalResult | null; results: EvalResult[]; onClose: () => void }) {
  const visibleResults = results.length ? results : result ? [result] : [];
  const summary = summarizeResults(visibleResults);
  return (
    <Dialog open={Boolean(result)} onClose={onClose} title="评估结果详情" description="查看评分、证据、错误和原始运行数据。" className="max-w-[1180px]">
      {!result ? null : (
        <div className="max-h-[78vh] space-y-5 overflow-y-auto">
          <div className="grid gap-3 md:grid-cols-5">
            <MetricCard label="样本数" value={summary.total} />
            <MetricCard label="通过率" value={summary.total ? `${Math.round(summary.passRate * 100)}%` : "-"} />
            <MetricCard label="平均耗时" value={`${summary.avgLatency}ms`} />
            <MetricCard label="RAG 命中" value={formatScore(summary.scores.rag_hit_rate)} />
            <MetricCard label="答案匹配" value={formatScore(summary.scores.answer_match)} />
          </div>

          {summary.warnings.length ? <ErrorList items={summary.warnings.map((item) => item.message || item.code)} /> : null}

          <div className="rounded-2xl border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-900">样本明细</div>
            <div className="divide-y divide-slate-100">
              {visibleResults.map((item) => (
                <div key={item.run_id} className="grid gap-3 p-4 lg:grid-cols-[1fr_1fr]">
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-slate-900">{item.query}</p>
                    {item.error ? <p className="rounded-lg bg-rose-50 p-2 text-xs text-rose-700">{item.error}</p> : null}
                    <DetailBlock title="实际回答" value={item.response || "(empty)"} />
                  </div>
                  <div className="space-y-2">
                    <ScoreGrid scores={item.scores} />
                    <DetailBlock title="证据" value={JSON.stringify((item.evidence ?? []).slice(0, 5), null, 2)} />
                    <DetailBlock title="检索配置" value={JSON.stringify(item.retrieval_config ?? {}, null, 2)} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <details className="rounded-2xl border border-slate-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">原始 JSON</summary>
            <pre className={`${detailBox} mt-3`}>{JSON.stringify(visibleResults, null, 2)}</pre>
          </details>
        </div>
      )}
    </Dialog>
  );
}

function SampleEditor({ samples, onChange, compact = false }: { samples: EvalSample[]; onChange: (samples: EvalSample[]) => void; compact?: boolean }) {
  const update = (index: number, patch: Partial<EvalSample>) => onChange(samples.map((sample, i) => (i === index ? { ...sample, ...patch } : sample)));
  return (
    <div className="space-y-3">
      {samples.map((sample, index) => (
        <div key={sample.id || index} className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500">样本 {index + 1}</span>
            <button type="button" onClick={() => onChange(samples.filter((_, i) => i !== index))} disabled={samples.length === 1} className="text-slate-300 hover:text-rose-500 disabled:opacity-30"><X size={14} /></button>
          </div>
          <div className="grid gap-2">
            <textarea className={`${inputClass} min-h-16 resize-none`} value={sample.query} onChange={(event) => update(index, { query: event.target.value })} placeholder="测试问题 *" />
            <textarea className={`${inputClass} min-h-16 resize-none`} value={sample.expected_answer || sample.expected || ""} onChange={(event) => update(index, { expected: event.target.value, expected_answer: event.target.value })} placeholder="期望答案 *" />
            {!compact ? (
              <div className="grid gap-2 sm:grid-cols-3">
                <input className={inputClass} value={(sample.expected_sources ?? []).join(", ")} onChange={(event) => update(index, { expected_sources: splitList(event.target.value) })} placeholder="期望来源" />
                <input className={inputClass} value={(sample.tags ?? []).join(", ")} onChange={(event) => update(index, { tags: splitList(event.target.value) })} placeholder="样本标签" />
                <input className={inputClass} value={sample.notes ?? ""} onChange={(event) => update(index, { notes: event.target.value })} placeholder="备注" />
              </div>
            ) : null}
          </div>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...samples, emptySample()])} className={outlineButton}><Plus size={14} />添加样本</button>
    </div>
  );
}

function BulkImport({ value, onChange, onImport }: { value: string; onChange: (value: string) => void; onImport: () => void }) {
  return (
    <details className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <summary className="cursor-pointer text-xs font-semibold text-slate-600">批量导入样本</summary>
      <textarea className={`${inputClass} mt-3 min-h-28 resize-none font-mono text-xs`} value={value} onChange={(event) => onChange(event.target.value)} placeholder="支持 JSON 数组，或每行一条：问题 | 期望答案 | 来源1,来源2" />
      <button type="button" onClick={onImport} disabled={!value.trim()} className="mt-2 inline-flex h-8 items-center rounded-lg bg-slate-900 px-3 text-xs font-semibold text-white disabled:opacity-40">导入</button>
    </details>
  );
}

function RetrievalConfigEditor({ kind, value, onChange, onUseKbDefault }: { kind: KBKind; value: RetrievalConfig; onChange: (value: RetrievalConfig) => void; onUseKbDefault?: () => void }) {
  if (kind === "mixed") return <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">混合 Milvus 和 LightRAG 时不能使用统一覆盖配置。</p>;
  if (kind === "none") return <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">先选择知识库后再配置检索策略。</p>;
  const modes = kind === "lightrag" ? lightragModes : milvusModes;
  const setNumber = (key: keyof RetrievalConfig, next: number) => onChange({ ...value, [key]: next });
  return (
    <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-slate-600">{kind === "lightrag" ? "图谱上下文策略" : "Milvus 检索策略"}</p>
        {onUseKbDefault ? <button type="button" onClick={onUseKbDefault} className="text-xs font-semibold text-indigo-600 hover:text-indigo-700">使用知识库默认值</button> : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="检索模式"><SelectBox value={String(value.search_mode || value.mode || modes[0].value)} options={modes} onChange={(mode) => onChange({ ...value, mode: mode as RetrievalMode, search_mode: mode as RetrievalMode })} /></Field>
        <Field label="召回 Top K"><input className={inputClass} type="number" min={1} max={200} value={value.recall_top_k ?? 30} onChange={(event) => setNumber("recall_top_k", Number(event.target.value))} /></Field>
        <Field label="最终 Top K"><input className={inputClass} type="number" min={1} max={100} value={value.final_top_k ?? 10} onChange={(event) => setNumber("final_top_k", Number(event.target.value))} /></Field>
      </div>
      {kind === "milvus" ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <Field label="相似度阈值"><input className={inputClass} type="number" min={0} max={1} step={0.05} value={value.similarity_threshold ?? 0} onChange={(event) => setNumber("similarity_threshold", Number(event.target.value))} /></Field>
          <Field label="向量权重"><input className={inputClass} type="number" min={0} max={1} step={0.05} value={value.vector_weight ?? 0.7} onChange={(event) => setNumber("vector_weight", Number(event.target.value))} /></Field>
          <Field label="关键词权重"><input className={inputClass} type="number" min={0} max={1} step={0.05} value={value.bm25_weight ?? value.keyword_weight ?? 0.3} onChange={(event) => onChange({ ...value, keyword_weight: Number(event.target.value), bm25_weight: Number(event.target.value) })} /></Field>
          <Field label="BM25 Top K"><input className={inputClass} type="number" min={1} max={200} value={value.bm25_top_k ?? 30} onChange={(event) => setNumber("bm25_top_k", Number(event.target.value))} /></Field>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="图谱深度"><input className={inputClass} type="number" min={1} max={5} value={Number(value.graph_depth ?? 2)} onChange={(event) => onChange({ ...value, graph_depth: Number(event.target.value) })} /></Field>
          <Field label="节点限制"><input className={inputClass} type="number" min={10} max={300} value={Number(value.graph_limit ?? 80)} onChange={(event) => onChange({ ...value, graph_limit: Number(event.target.value) })} /></Field>
        </div>
      )}
    </div>
  );
}

function TypeSelector({ value, onChange }: { value: EvalType; onChange: (value: EvalType) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {evalTypes.map((item) => {
        const Icon = item.icon;
        const selected = value === item.value;
        return (
          <button key={item.value} type="button" onClick={() => onChange(item.value)} className={cn("rounded-xl border p-3 text-left transition", selected ? "border-indigo-300 bg-indigo-50 text-indigo-700" : "border-slate-200 bg-white text-slate-600 hover:border-slate-300")}>
            <div className="flex items-center gap-2 text-sm font-semibold"><Icon size={15} />{item.label}{item.advanced ? <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">高级</span> : null}</div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-400">{item.hint}</p>
          </button>
        );
      })}
    </div>
  );
}

function ModelSelect({ value, onChange, models }: { value: string; onChange: (value: string) => void; models: Model[] }) {
  const options = [{ value: "", label: "默认模型" }, ...models.map((model) => ({ value: model.name, label: `${model.display_name || model.name}${model.provider_name || model.provider ? ` · ${model.provider_name || model.provider}` : ""}` }))];
  return <SelectBox value={value} options={options} onChange={onChange} searchable />;
}

function SelectBox({ value, options, onChange, placeholder = "请选择", className, searchable = false }: { value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; placeholder?: string; className?: string; searchable?: boolean }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selected = options.find((item) => item.value === value);
  const filtered = searchable && query ? options.filter((item) => item.label.toLowerCase().includes(query.toLowerCase())) : options;
  return (
    <div className={cn("relative", className)}>
      <button type="button" onClick={() => setOpen((next) => !next)} className="flex h-10 w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-3 text-left text-sm text-slate-700 outline-none transition hover:border-slate-300 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100">
        <span className="truncate">{selected?.label || placeholder}</span>
        <ChevronDown size={15} className={cn("text-slate-400 transition", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="absolute z-40 mt-2 w-full rounded-xl border border-slate-200 bg-white p-1 shadow-xl">
          {searchable ? <div className="relative m-1"><Search size={14} className="absolute left-2 top-2.5 text-slate-300" /><input className="h-9 w-full rounded-lg border border-slate-100 pl-7 pr-2 text-sm outline-none focus:border-indigo-200" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索" /></div> : null}
          <div className="max-h-60 overflow-auto">
            {filtered.length ? filtered.map((item) => (
              <button key={item.value || "__empty"} type="button" onClick={() => { onChange(item.value); setOpen(false); setQuery(""); }} className={cn("flex w-full items-center rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50", item.value === value ? "bg-indigo-50 text-indigo-700" : "text-slate-600")}>
                <span className="truncate">{item.label}</span>
                {item.value === value ? <CheckCircle size={14} className="ml-auto" /> : null}
              </button>
            )) : <p className="px-3 py-4 text-center text-xs text-slate-400">没有可选项</p>}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function KnowledgeSelector({ value, kbs, required, onChange }: { value: string[]; kbs: KBMeta[]; required?: boolean; onChange: (value: string[]) => void }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
      <p className="mb-2 text-xs font-semibold text-slate-600">知识库范围 {required ? <span className="text-rose-500">*</span> : null}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {kbs.map((kb) => (
          <label key={kb.kb_id} className="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm text-slate-600 shadow-sm">
            <input type="checkbox" checked={value.includes(kb.kb_id)} onChange={(event) => onChange(event.target.checked ? [...value, kb.kb_id] : value.filter((id) => id !== kb.kb_id))} />
            <span className="truncate">{kb.name}</span>
            <span className="ml-auto text-[10px] font-semibold uppercase text-slate-300">{kb.kb_type}</span>
          </label>
        ))}
        {kbs.length === 0 ? <p className="text-xs text-slate-400">暂无知识库。</p> : null}
      </div>
    </div>
  );
}

function KbStrategyNotice({ kind, selected }: { kind: KBKind; selected: KBMeta[] }) {
  if (!selected.length) return <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">请选择要评估的知识库。</p>;
  if (kind === "milvus") return <p className="rounded-xl bg-sky-50 px-3 py-2 text-xs text-sky-700">Milvus 使用向量、关键词或混合检索，可选 rerank。</p>;
  if (kind === "lightrag") return <p className="rounded-xl bg-indigo-50 px-3 py-2 text-xs text-indigo-700">LightRAG 使用图谱上下文策略，不显示 BM25 和向量权重。</p>;
  return <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">已混合选择 Milvus 和 LightRAG，将分别使用各知识库默认策略。</p>;
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: EvalGenerationDiagnostic[] }) {
  if (!diagnostics.length) return null;
  return (
    <FormSection title="生成诊断">
      <div className="space-y-2">
        {diagnostics.map((item) => (
          <div key={item.kb_id} className="rounded-xl border border-slate-200 bg-white p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-slate-700">{item.name}</span>
              <Badge variant={item.status === "ready" ? "success" : "warning"}>{item.chunks} chunks</Badge>
            </div>
            <p className="mt-1 text-slate-400">{item.source || "无可用来源"}</p>
            {item.warnings?.map((warning, index) => <p key={`${item.kb_id || item.name}-warning-${index}`} className="mt-1 text-amber-600">{warning}</p>)}
          </div>
        ))}
      </div>
    </FormSection>
  );
}

function SuitePreview({ form, selectedKbs }: { form: SuiteForm; selectedKbs: KBMeta[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-500">Suite Preview</p>
      <h3 className="mt-2 text-lg font-semibold text-slate-950">{form.name || "未命名评估集"}</h3>
      <div className="mt-4 space-y-3 text-sm text-slate-600">
        <PreviewLine label="类型" value={typeLabel(form.type)} />
        <PreviewLine label="样本" value={`${form.samples.filter((sample) => sample.query.trim()).length}/${form.samples.length}`} />
        <PreviewLine label="知识库" value={selectedKbs.length ? selectedKbs.map((kb) => kb.name).join(", ") : "未选择"} />
        <PreviewLine label="检索" value={form.retrievalOverrideEnabled ? "评估集覆盖" : "跟随知识库默认"} />
      </div>
    </div>
  );
}

function PreviewLine({ label, value }: { label: string; value: string }) {
  return <div className="flex gap-3"><span className="w-16 shrink-0 text-slate-400">{label}</span><span className="min-w-0 flex-1 break-words font-medium text-slate-700">{value}</span></div>;
}

function EmptyState({ onCreate, onGenerate }: { onCreate: () => void; onGenerate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-white py-20 text-center">
      <FlaskConical size={32} className="text-slate-300" />
      <p className="mt-4 text-sm font-semibold text-slate-700">还没有评估集</p>
      <p className="mt-1 text-xs text-slate-400">可以手动创建，也可以从知识库生成草稿。</p>
      <div className="mt-4 flex gap-2"><button type="button" onClick={onCreate} className={outlineButton}>新建评估集</button><button type="button" onClick={onGenerate} className={outlineButton}>AI 生成</button></div>
    </div>
  );
}

function MetricExplanation() {
  return (
    <details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <summary className="cursor-pointer text-sm font-semibold text-slate-900">指标与期望来源说明</summary>
      <div className="mt-3 grid gap-3 text-xs leading-5 text-slate-600 md:grid-cols-2 lg:grid-cols-3">
        <p><span className="font-semibold text-slate-800">期望来源</span>：样本中人工或 AI 指定的 gold chunk/source/file id，用来判断检索是否命中正确资料。</p>
        <p><span className="font-semibold text-slate-800">Recall@K</span>：前 K 条检索结果中命中了多少期望来源，衡量“有没有找回来”。</p>
        <p><span className="font-semibold text-slate-800">Precision@K</span>：前 K 条检索结果里有多少是期望来源，衡量“结果是否干净”。</p>
        <p><span className="font-semibold text-slate-800">F1@K</span>：Recall 与 Precision 的平衡值，适合看整体检索质量。</p>
        <p><span className="font-semibold text-slate-800">引用准确率</span>：答案引用的证据 ID 是否存在于本次检索 evidence。</p>
        <p><span className="font-semibold text-slate-800">答案匹配度</span>：先用规则匹配期望答案关键词或子串；LLM Judge 后续可作为可选增强。</p>
      </div>
    </details>
  );
}

function MetricHelpCompact() {
  return (
    <div className="mt-2 space-y-1 rounded-xl border border-slate-200 bg-slate-50 p-3 leading-5">
      <p><span className="font-semibold">期望来源</span>：用于判断检索是否命中正确资料的 gold chunk/source/file id。</p>
      <p><span className="font-semibold">Recall@K</span>：前 K 条结果命中了多少期望来源。</p>
      <p><span className="font-semibold">Precision@K</span>：前 K 条结果中有多少是期望来源。</p>
      <p><span className="font-semibold">F1@K</span>：Recall 和 Precision 的平衡值。</p>
      <p><span className="font-semibold">答案匹配</span>：规则匹配期望答案关键词或子串。</p>
    </div>
  );
}

function FormSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"><div className="mb-3"><h3 className="text-sm font-semibold text-slate-900">{title}</h3>{description ? <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p> : null}</div><div className="space-y-3">{children}</div></section>;
}

function Field({ label, required, hint, children }: { label: string; required?: boolean; hint?: string; children: ReactNode }) {
  return <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">{label} {required ? <span className="text-rose-500">*</span> : null}</span>{children}{hint ? <span className="block text-[11px] leading-4 text-slate-400">{hint}</span> : null}</label>;
}

function ErrorList({ items }: { items: string[] }) {
  return <div className="rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-700">{items.map((item, index) => <p key={`${item}-${index}`}>· {item}</p>)}</div>;
}

function DetailBlock({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-500">{title}</p>
      <div className="max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-700">
        {value}
      </div>
    </div>
  );
}

function WarningList({ warnings }: { warnings: Array<{ code?: string; message?: string; action?: string }> }) {
  return (
    <div className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
      {warnings.map((item, index) => (
        <p key={`${item.code || item.message || "warning"}-${index}`}>· {friendlyWarning(item)}</p>
      ))}
    </div>
  );
}

function EvidenceList({ evidence }: { evidence: Array<Record<string, unknown>> }) {
  if (!evidence.length) {
    return <DetailBlock title="证据 Chunk" value="暂无证据。"/>;
  }
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-500">证据 Chunk</p>
      <div className="space-y-2">
        {evidence.map((item, index) => {
          const metadata = isRecord(item.metadata) ? item.metadata : {};
          const title = String(item.source || item.file_id || item.id || metadata.source || metadata.file_id || `Chunk ${index + 1}`);
          const content = String(item.content || item.text || metadata.content || "");
          return (
            <details key={`${String(item.id || metadata.id || title)}-${index}`} className="rounded-xl border border-slate-200 bg-white p-3">
              <summary className="cursor-pointer text-xs font-semibold text-slate-700">{title}</summary>
              <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-600">{content || "无内容预览。"}</p>
              {Object.keys(metadata).length ? (
                <p className="mt-2 break-words rounded-lg bg-slate-50 p-2 text-[11px] text-slate-400">{formatObjectInline(metadata)}</p>
              ) : null}
            </details>
          );
        })}
      </div>
    </div>
  );
}

function ScoreGrid({ scores }: { scores?: EvalScores }) {
  const items = [["RAG 命中", scores?.rag_hit_rate], ["引用准确", scores?.citation_accuracy], ["答案匹配", scores?.answer_match]] as const;
  return <div className="grid gap-2 sm:grid-cols-3">{items.map(([label, score]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-400">{label}</p><p className="mt-1 text-lg font-semibold text-slate-900">{formatScore(score)}</p></div>)}</div>;
}

function MetricStrip({ metrics }: { metrics?: Record<string, number | null | undefined> }) {
  const items = [
    ["Recall@1", metrics?.["recall@1"]],
    ["Recall@3", metrics?.["recall@3"]],
    ["Recall@5", metrics?.["recall@5"]],
    ["F1@5", metrics?.["f1@5"]],
  ] as const;
  if (!items.some(([, value]) => typeof value === "number")) return null;
  return (
    <div className="grid gap-2 sm:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-lg border border-slate-200 bg-white p-2">
          <p className="text-[11px] text-slate-400">{label}</p>
          <p className="mt-1 text-sm font-semibold text-slate-800">{formatScore(value)}</p>
        </div>
      ))}
    </div>
  );
}

function ScorePills({ scores }: { scores?: EvalScores }) {
  if (!scores) return <span className="hidden text-xs text-slate-400 xl:inline">未运行</span>;
  const items = [["RAG", scores.rag_hit_rate], ["引用", scores.citation_accuracy], ["答案", scores.answer_match]] as const;
  return <div className="hidden max-w-[260px] flex-wrap justify-end gap-1 xl:flex">{items.map(([label, score]) => score == null ? null : <span key={label} className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", score >= 0.7 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>{label} {Math.round(score * 100)}%</span>)}</div>;
}

function ResultIcon({ result, running }: { result?: EvalResult; running: boolean }) {
  if (running) return <Loader2 size={18} className="animate-spin text-sky-600" />;
  if (!result) return <Clock size={18} className="text-slate-300" />;
  if (result.passed === true) return <CheckCircle size={18} className="text-sky-600" />;
  if (result.passed === false) return <XCircle size={18} className="text-rose-600" />;
  return <Clock size={18} className="text-slate-300" />;
}

function Stat({ label, value, icon: Icon }: { label: string; value: string | number; icon: LucideIcon }) {
  return <Card><CardContent className="p-5"><div className="flex items-center gap-2 text-sm text-slate-500"><Icon size={16} />{label}</div><p className="mt-2 text-3xl font-semibold text-slate-950">{value}</p></CardContent></Card>;
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-2xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-400">{label}</p><p className="mt-2 text-2xl font-semibold text-slate-950">{value}</p></div>;
}

function formToPayload(form: SuiteForm, selectedKbs: KBMeta[]) {
  const kind = inferKbKind(selectedKbs);
  return {
    name: form.name,
    type: form.type,
    agent: form.agent,
    model: form.model,
    kb_ids: form.kbIds,
    retrieval_override_enabled: form.retrievalOverrideEnabled && kind !== "mixed",
    retrieval_config: form.retrievalOverrideEnabled && kind !== "mixed" ? cleanConfigForKind(form.retrievalConfig, kind) : {},
    samples: form.samples.map((sample) => ({ ...sample, expected_answer: sample.expected_answer || sample.expected || "", expected: sample.expected_answer || sample.expected || "" })),
    tags: splitList(form.tags),
  };
}

function validateSuiteForm(form: SuiteForm, selectedKbs: KBMeta[]) {
  const errors: string[] = [];
  if (!form.name.trim()) errors.push("名称为必填。");
  if (form.type === "rag" && selectedKbs.length === 0) errors.push("RAG 评估集至少选择一个知识库。");
  if (!form.samples.length) errors.push("评估集至少需要一条样本。");
  form.samples.forEach((sample, index) => {
    if (!sample.query.trim()) errors.push(`样本 ${index + 1} 的问题为必填。`);
    if (form.type === "rag" && !(sample.expected_answer || sample.expected || "").trim()) errors.push(`样本 ${index + 1} 的期望答案为必填。`);
  });
  if (form.retrievalOverrideEnabled && inferKbKind(selectedKbs) === "mixed") errors.push("混合类型知识库不能使用统一检索覆盖。");
  return errors;
}

function validateGenerateForm(form: GenerateForm, selectedKbs: KBMeta[]) {
  const errors: string[] = [];
  if (form.source === "knowledge" && selectedKbs.length === 0) errors.push("从知识库生成时至少选择一个知识库。");
  if (form.count < 1 || form.count > 20) errors.push("生成数量需要在 1 到 20 之间。");
  if (form.retrievalOverrideEnabled && inferKbKind(selectedKbs) === "mixed") errors.push("混合类型知识库不能使用统一检索覆盖。");
  return errors;
}

function parseBulkSamples(text: string): EvalSample[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => ({ ...emptySample(), query: String(item.query || item.question || ""), expected: String(item.expected_answer || item.expected || ""), expected_answer: String(item.expected_answer || item.expected || ""), expected_sources: Array.isArray(item.expected_sources) ? item.expected_sources.map(String) : splitList(String(item.expected_sources || "")), tags: Array.isArray(item.tags) ? item.tags.map(String) : splitList(String(item.tags || "")), notes: String(item.notes || "") })).filter((sample) => sample.query.trim());
    }
  } catch {
    // fall through
  }
  return trimmed.split(/\n+/).map((line) => {
    const [query, expected = "", sources = ""] = line.split("|").map((part) => part.trim());
    return { ...emptySample(), query, expected, expected_answer: expected, expected_sources: splitList(sources) };
  }).filter((sample) => sample.query.trim());
}

function inferKbKind(kbs: KBMeta[]): KBKind {
  if (!kbs.length) return "none";
  const types = new Set(kbs.map((kb) => kb.kb_type));
  if (types.size > 1) return "mixed";
  return types.has("lightrag") ? "lightrag" : "milvus";
}

function resolveSuiteKbs(suite: EvalSuite, kbs: KBMeta[]) {
  const byId = new Map(kbs.map((kb) => [kb.kb_id, kb]));
  return (suite.kb_ids ?? [])
    .map((kbId) => byId.get(kbId) ?? { kb_id: kbId, name: kbId, kb_type: "milvus" as const, description: "", chunk_size: 0, chunk_overlap: 0, created_at: "", updated_at: "", embed_info: { model: "", dimension: 0 } })
    .filter(Boolean);
}

function configForKind(kind: KBKind): RetrievalConfig {
  if (kind === "lightrag") return defaultLightRagConfig;
  return defaultMilvusConfig;
}

function cleanConfigForKind(config: RetrievalConfig, kind: KBKind): RetrievalConfig {
  if (kind === "lightrag") {
    return {
      mode: (config.mode || config.search_mode || "lightrag_hybrid") as RetrievalMode,
      search_mode: (config.search_mode || config.mode || "lightrag_hybrid") as RetrievalMode,
      recall_top_k: config.recall_top_k,
      final_top_k: config.final_top_k,
      graph_depth: config.graph_depth,
      graph_limit: config.graph_limit,
    };
  }
  return config;
}

function summarizeResults(results: EvalResult[]) {
  const total = results.length;
  const passed = results.filter((item) => item.passed === true).length;
  const avgLatency = total ? Math.round(results.reduce((sum, item) => sum + (item.latency_ms || 0), 0) / total) : 0;
  const scoreKeys: (keyof EvalScores)[] = ["rag_hit_rate", "citation_accuracy", "answer_match"];
  const scores: EvalScores = {};
  for (const key of scoreKeys) {
    const values = results.map((item) => (item.metrics ?? item.scores)?.[key]).filter((value): value is number => typeof value === "number");
    scores[key] = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }
  const metricKeys = ["recall@1", "recall@3", "recall@5", "recall@10", "precision@1", "precision@3", "precision@5", "precision@10", "f1@1", "f1@3", "f1@5", "f1@10"];
  const metrics: Record<string, number | null | undefined> & EvalScores = { ...scores };
  for (const key of metricKeys) {
    const values = results.map((item) => item.metrics?.[key]).filter((value): value is number => typeof value === "number");
    metrics[key] = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }
  const seenWarnings = new Set<string>();
  const warnings = results.flatMap((item) => item.retrieval_warnings ?? []).filter((item, index) => {
    const key = `${item.code || "warning"}:${item.message || ""}:${item.action || ""}:${index}`;
    if (seenWarnings.has(key)) return false;
    seenWarnings.add(key);
    return true;
  });
  return { total, passed, passRate: total ? passed / total : 0, avgLatency, scores, metrics, warnings };
}

function splitList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function typeLabel(type?: EvalType) {
  return evalTypes.find((item) => item.value === type)?.label ?? "RAG";
}

function formatScore(score?: number | null) {
  return score == null ? "-" : `${Math.round(score * 100)}%`;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "操作失败";
}

function friendlyEvalError(error: string) {
  if (/collection not found/i.test(error)) return "Milvus collection 不存在，请先重新入库后再运行评估。";
  if (/no source material|no usable chunks|indexed chunks/i.test(error)) return "该知识库没有可用于评估的内容，请先完成入库或重新生成索引。";
  if (/model|chat|completion|timeout/i.test(error)) return "模型调用失败或超时，请检查模型配置后重试。";
  return error || "评估失败。";
}

function friendlyWarning(item: { code?: string; message?: string; action?: string }) {
  const code = item.code || "";
  if (code.includes("milvus_collection_missing")) return "Milvus collection 缺失，已使用本地内容降级检索。";
  if (code.includes("native_bm25_unavailable")) return "当前知识库未启用原生 BM25，已使用本地关键词检索降级。";
  if (code.includes("degraded")) return "检索使用了降级路径，建议检查索引状态。";
  return item.message || item.action || "检索过程存在警告。";
}

function formatRetrievalConfig(config?: RetrievalConfig) {
  if (!config || Object.keys(config).length === 0) return "使用知识库默认检索策略。";
  const entries = Object.entries(config)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .slice(0, 12)
    .map(([key, value]) => `${key}: ${String(value)}`);
  return entries.length ? entries.join("\n") : "使用知识库默认检索策略。";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function formatObjectInline(value: Record<string, unknown>) {
  const entries = Object.entries(value)
    .filter(([, item]) => item !== undefined && item !== null && item !== "")
    .slice(0, 8)
    .map(([key, item]) => `${key}: ${String(item)}`);
  return entries.join(" · ") || "无 metadata";
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-50 disabled:text-slate-400";
const outlineButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const primaryHeaderButton = "inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white hover:bg-slate-800";
const primaryButton = "inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50";
const detailBox = "max-h-64 overflow-auto rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-100";
