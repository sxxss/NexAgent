"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Eye,
  FileText,
  Layers,
  ListChecks,
  Loader2,
  Network,
  Play,
  RefreshCw,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  cancelTask,
  compileWikiKb,
  deleteFile,
  fetchFiles,
  fetchIngestionJobs,
  fetchKBQueryConfig,
  fetchKBs,
  fetchKnowledgeGraphSummary,
  fetchParsedFilePreview,
  fetchProviders,
  processAllFiles,
  processFileAsync,
  retryIngestionJob,
  searchKBWithConfig,
  testProviderModel,
  updateKBModelConfig,
  updateKBQueryConfig,
  uploadFile,
  type FileMeta,
  type IngestionJob,
  type KBMeta,
  type KnowledgeGraphSummary,
  type KnowledgeQueryConfigResponse,
  type ModelProbeResult,
  type ParsedFilePreview,
  type ProviderCapability,
  type ProviderModelConfig,
  type ModelProvider,
  type RetrievalConfig,
  type RetrievalMode,
  type SearchResult,
  type SearchWarning,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { WikiWorkbench, type WikiResourceContext } from "@/components/wiki/WikiWorkbench";
import { cn, formatBytes, formatDate } from "@/lib/utils";

interface ProviderModelOption {
  value: string;
  providerId: string;
  providerName: string;
  modelId: string;
  label: string;
  detail: string;
  dimension?: number | null;
}

interface UploadResult {
  filename: string;
  status: "success" | "error";
  message: string;
  fileId?: string;
}

const statusMap: Record<FileMeta["status"], { label: string; variant: "secondary" | "info" | "success" | "warning" | "error"; icon: LucideIcon }> = {
  uploaded: { label: "待处理", variant: "secondary", icon: Clock },
  parsing: { label: "解析中", variant: "warning", icon: Loader2 },
  parsed: { label: "待入库", variant: "info", icon: CheckCircle },
  parse_error: { label: "解析失败", variant: "error", icon: AlertCircle },
  indexing: { label: "入库中", variant: "warning", icon: Loader2 },
  indexed: { label: "可检索", variant: "success", icon: CheckCircle },
  index_error: { label: "入库失败", variant: "error", icon: AlertCircle },
  graphing: { label: "图谱构建中", variant: "warning", icon: Loader2 },
  graph_indexed: { label: "图谱可用", variant: "success", icon: CheckCircle },
  error_graphing: { label: "图谱失败", variant: "error", icon: AlertCircle },
  indexed_with_graph_degraded: { label: "降级可检索", variant: "warning", icon: AlertCircle },
};

export default function KBDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [kb, setKb] = useState<KBMeta | null>(null);
  const [files, setFiles] = useState<FileMeta[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [queryConfigMeta, setQueryConfigMeta] = useState<KnowledgeQueryConfigResponse | null>(null);
  const [queryConfig, setQueryConfig] = useState<RetrievalConfig>(defaultQueryConfig("milvus"));
  const [graphSummary, setGraphSummary] = useState<KnowledgeGraphSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [wikiCompiling, setWikiCompiling] = useState(false);
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([]);
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<ParsedFilePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searchWarnings, setSearchWarnings] = useState<SearchWarning[]>([]);
  const [searchError, setSearchError] = useState("");
  const [savingQueryConfig, setSavingQueryConfig] = useState(false);
  const [showWikiSettings, setShowWikiSettings] = useState(false);

  const [providers, setProviders] = useState<ModelProvider[]>([]);

  useEffect(() => {
    let mounted = true;
    fetchProviders().then((items) => {
      if (mounted) setProviders(items);
    });
    return () => { mounted = false; };
  }, []);

  const embeddingModels = useMemo(() => providerModelOptions(providers, "embedding"), [providers]);
  const chatModels = useMemo(() => providerModelOptions(providers, "chat"), [providers]);
  const rerankModels = useMemo(() => providerModelOptions(providers, "rerank"), [providers]);

  const loadData = useCallback(async () => {
    const [allKbs, fileList, jobList, config] = await Promise.all([fetchKBs(), fetchFiles(id), fetchIngestionJobs(id), fetchKBQueryConfig(id)]);
    const found = allKbs.find((item) => item.kb_id === id);
    if (!found) {
      router.push("/knowledge");
      return;
    }
    setKb(found);
    setFiles(fileList);
    setJobs(jobList);
    setQueryConfigMeta(config);
    setQueryConfig({ ...defaultQueryConfig(found.kb_type), ...(config.effective_config ?? config.query_config ?? {}) });
    if (found.kb_type === "lightrag") {
      const summary = await fetchKnowledgeGraphSummary(id);
      setGraphSummary(summary);
    } else {
      setGraphSummary(null);
    }
    setLoading(false);
  }, [id, router]);

  useEffect(() => { void loadData(); }, [loadData]);
  useEffect(() => {
    const hasRunningFiles = files.some((file) => file.progress?.is_running);
    const hasRunningJobs = jobs.some((job) => job.status === "queued" || job.status === "running");
    if (!hasRunningFiles && !hasRunningJobs) return;
    const timer = window.setInterval(() => { void loadData(); }, 1500);
    return () => window.clearInterval(timer);
  }, [files, jobs, loadData]);

  const setProcessing = (fileId: string, on: boolean) => {
    setProcessingIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(fileId);
      else next.delete(fileId);
      return next;
    });
  };

  const handleUpload = async (fileList: FileList | null) => {
    if (!fileList?.length || uploading) return;
    const selectedFiles = Array.from(fileList);
    const nextResults: UploadResult[] = [];
    setUploadResults([]);
    setUploading(true);
    try {
      for (const file of selectedFiles) {
        try {
          const uploaded = await uploadFile(id, file);
          nextResults.push({ filename: file.name, status: "success", message: "Uploaded", fileId: uploaded.file_id });
        } catch (error) {
          nextResults.push({ filename: file.name, status: "error", message: error instanceof Error ? error.message : "Upload failed" });
        }
        setUploadResults([...nextResults]);
      }
      await loadData();
    } catch (error) {
      alert(error instanceof Error ? error.message : "上传失败");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
      setUploading(false);
    }
  };

  const handleProcess = async (fileId: string) => {
    setProcessing(fileId, true);
    try {
      await processFileAsync(id, fileId);
      await loadData();
    } catch (error) {
      alert(error instanceof Error ? error.message : "加入处理队列失败");
    } finally {
      setProcessing(fileId, false);
    }
  };

  const handleProcessAll = async () => {
    setUploading(true);
    try {
      const result = await processAllFiles(id);
      if (!result.task && !result.job && result.message) alert(result.message);
      await loadData();
    } catch (error) {
      alert(error instanceof Error ? error.message : "批量处理失败");
    } finally {
      setUploading(false);
    }
  };

  const handleWikiCompile = async (body: { force?: boolean; retry_failed?: boolean } = {}) => {
    setWikiCompiling(true);
    try {
      const result = await compileWikiKb(id, body);
      if (!result.task_id && result.message) alert(result.message);
      await loadData();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Wiki 编译失败");
    } finally {
      setWikiCompiling(false);
    }
  };

  const handleWikiRetryFailedCompile = async () => {
    await handleWikiCompile({ retry_failed: true, force: true });
  };

  const handlePreview = async (fileId: string) => {
    setPreviewLoading(true);
    try {
      setPreview(await fetchParsedFilePreview(id, fileId));
    } catch (error) {
      alert(error instanceof Error ? error.message : "预览失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDelete = async (fileId: string, filename: string) => {
    if (!confirm(`确认删除「${filename}」？`)) return;
    await deleteFile(id, fileId);
    await loadData();
  };

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setSearched(false);
    setResults([]);
    setSearchWarnings([]);
    setSearchError("");
    try {
      const response = await searchKBWithConfig(id, query, queryConfig);
      setResults(response.results);
      setSearchWarnings(response.warnings ?? []);
      setSearched(true);
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "检索失败");
      setSearched(true);
    } finally {
      setSearching(false);
    }
  };

  const handleSaveQueryConfig = async () => {
    setSavingQueryConfig(true);
    try {
      const next = await updateKBQueryConfig(id, queryConfig);
      setQueryConfigMeta(next);
      setQueryConfig({ ...defaultQueryConfig(kb?.kb_type ?? "milvus"), ...(next.effective_config ?? next.query_config ?? {}) });
    } catch (error) {
      alert(error instanceof Error ? error.message : "保存检索配置失败");
    } finally {
      setSavingQueryConfig(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-100">
        <div className="flex items-center gap-3 rounded-xl bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
          <Loader2 size={16} className="animate-spin text-sky-600" />
          加载知识库...
        </div>
      </div>
    );
  }
  if (!kb) return null;

  const isWiki = kb.kb_type === "wiki";
  const isMilvus = kb.kb_type === "milvus";
  const indexedCount = files.filter((file) => file.status === "indexed").length;
  const pendingCount = files.filter((file) =>
    ["uploaded", "parsed", "parse_error", "index_error", "error_graphing", "indexed_with_graph_degraded"].includes(file.status),
  ).length;
  const activeJob = jobs.find((job) => job.status === "queued" || job.status === "running");

  if (isWiki) {
    return (
      <div className="h-full min-w-0 bg-slate-50 p-2 lg:p-3">
        <WikiWorkbench
          kb={kb}
          files={files}
          reload={loadData}
          sidebar={
            <div className={wikiSidebar}>
              <WikiCompactHeader
                kb={kb}
                fileCount={files.length}
                indexedCount={indexedCount}
                activeJob={activeJob}
                onBack={() => router.push("/knowledge")}
                onOpenGraph={() => router.push(`/knowledge/${id}/wiki/graph`)}
                onSettings={() => setShowWikiSettings(true)}
                onRefresh={() => void loadData()}
              />
            </div>
          }
          resources={({ filters, setFilters, candidateCount, needsReviewCount }: WikiResourceContext) => {
            const activeSourceFileId = filters.source_file_id;
            const failedSourceCount = files.filter(isFailedWikiSource).length;
            const llmLabel = wikiLlmStatusLabel(kb);
            const llmTitle = wikiFullLlmLabel(kb);
            const compileStatus = wikiCompileStatus(files, activeJob, candidateCount);
            const applyWikiStatusFilter = (status: string) => {
              setFilters({ ...filters, status: filters.status === status ? "" : status });
            };
            const onToggleSourceFilter = (fileId: string) => {
              setFilters({ ...filters, source_file_id: activeSourceFileId === fileId ? "" : fileId });
            };
            return (
              <WikiSourceSection
                files={files}
                uploading={uploading}
                pendingCount={pendingCount}
                inputRef={fileInputRef}
                uploadResults={uploadResults}
                processingIds={processingIds}
                compiling={wikiCompiling}
                activeSourceFileId={activeSourceFileId}
                preview={preview}
                previewLoading={previewLoading}
                jobs={jobs.slice(0, 6)}
                llmLabel={llmLabel}
                indexedCount={indexedCount}
                compileStatus={compileStatus}
                candidateCount={candidateCount}
                needsReviewCount={needsReviewCount}
                failedSourceCount={failedSourceCount}
                activeStatus={filters.status}
                llmTitle={llmTitle}
                onUpload={handleUpload}
                onProcessAll={handleProcessAll}
                onCompileWiki={() => handleWikiCompile()}
                onForceCompileWiki={() => handleWikiCompile({ force: true })}
                onStatusFilter={applyWikiStatusFilter}
                onRetryFailed={handleWikiRetryFailedCompile}
                onRetry={(jobId) => void retryIngestionJob(jobId).then(loadData)}
                onCancel={(taskId) => void cancelTask(taskId).then(loadData)}
                onToggleSourceFilter={onToggleSourceFilter}
                onProcess={handleProcess}
                onPreview={handlePreview}
                onDelete={handleDelete}
                onClosePreview={() => setPreview(null)}
              />
            );
          }}
        />
        <WikiLlmSettingsDialog
          open={showWikiSettings}
          kb={kb}
          chatModels={chatModels}
          onClose={() => setShowWikiSettings(false)}
          onSaved={async () => {
            setShowWikiSettings(false);
            await loadData();
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mb-3 flex items-center gap-1.5 text-xs text-slate-400">
          <button onClick={() => router.push("/knowledge")} className="hover:text-slate-600">知识库</button>
          <ChevronRight size={11} />
          <span className="text-slate-600">{kb.name}</span>
        </div>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", isMilvus ? "bg-sky-50 text-sky-700" : "bg-indigo-50 text-indigo-700")}>
              {isMilvus ? <Layers size={19} /> : <Network size={19} />}
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-950">{kb.name}</h1>
              <p className="mt-1 text-sm text-slate-500">{kb.description || "未填写描述"}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge variant={isMilvus ? "teal" : "violet"}>{isMilvus ? "向量 RAG" : "LightRAG 图谱"}</Badge>
                <Badge variant="secondary">{files.length} 个文件</Badge>
                <Badge variant="success">{indexedCount} 已入库</Badge>
                {kb.extra?.requires_reindex ? <Badge variant="warning">索引需重建</Badge> : null}
                {activeJob ? <Badge variant="info">处理中 {taskCompleted(activeJob) + taskFailed(activeJob)}/{activeJob.total_steps}</Badge> : null}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleProcessAll} disabled={!pendingCount || uploading} className={cn(outlineButton, pendingCount && "border-sky-200 text-sky-700")}>
              <ListChecks size={14} />
              处理待入库 {pendingCount || ""}
            </button>
            {!isMilvus ? (
              <button type="button" onClick={() => router.push(`/knowledge/${id}/graph`)} className={cn(outlineButton, "border-indigo-200 text-indigo-700")}>
                <Network size={14} />
                图谱浏览
              </button>
            ) : null}
            <button type="button" onClick={() => router.push("/knowledge")} className={outlineButton}><ArrowLeft size={14} />返回</button>
            <button type="button" onClick={() => void loadData()} className={iconButton}><RefreshCw size={14} /></button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className={cn("grid gap-6", isMilvus ? "xl:grid-cols-[minmax(0,1.2fr)_minmax(420px,0.8fr)]" : "xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.72fr)]")}>
          <section className="space-y-4">
            <FileUploadCard uploading={uploading} inputRef={fileInputRef} onUpload={handleUpload} />
            <UploadResultList results={uploadResults} />
            <FileList files={files} processingIds={processingIds} onProcess={handleProcess} onPreview={handlePreview} onDelete={handleDelete} />
            {preview || previewLoading ? <PreviewPanel preview={preview} loading={previewLoading} onClose={() => setPreview(null)} /> : null}
            {jobs.length ? <JobHistory jobs={jobs.slice(0, 5)} onRetry={(jobId) => void retryIngestionJob(jobId).then(loadData)} onCancel={(taskId) => void cancelTask(taskId).then(loadData)} /> : null}
          </section>

          <aside className="space-y-4">
            <ModelAndRetrievalPanel
              kb={kb}
              queryConfig={queryConfig}
              queryConfigMeta={queryConfigMeta}
              embeddingModels={embeddingModels}
              chatModels={chatModels}
              rerankModels={rerankModels}
              onKbUpdated={(next) => setKb(next)}
              onQueryConfigChange={setQueryConfig}
              onQueryConfigSaved={handleSaveQueryConfig}
              savingQueryConfig={savingQueryConfig}
            />
            <SearchPanel
              query={query}
              setQuery={setQuery}
              indexedCount={indexedCount}
              searching={searching}
              searched={searched}
              searchError={searchError}
              searchWarnings={searchWarnings}
              results={results}
              onSearch={handleSearch}
            />
            {!isMilvus ? <GraphOverviewCard kbId={id} summary={graphSummary} indexedCount={indexedCount} /> : null}
          </aside>
        </div>
      </main>
    </div>
  );
}

function FileUploadCard({ uploading, inputRef, onUpload }: { uploading: boolean; inputRef: React.RefObject<HTMLInputElement | null>; onUpload: (files: FileList | null) => void }) {
  const [dragging, setDragging] = useState(false);
  return (
    <div
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); if (!uploading) onUpload(event.dataTransfer.files); }}
      onClick={() => { if (!uploading) inputRef.current?.click(); }}
      className={cn("flex flex-col items-center justify-center rounded-2xl border-2 border-dashed bg-white py-12 text-center transition", uploading ? "cursor-wait opacity-80" : "cursor-pointer", dragging ? "border-sky-300 bg-sky-50" : "border-slate-200 hover:border-sky-200 hover:bg-sky-50/30")}
    >
      <input ref={inputRef} type="file" multiple disabled={uploading} className="hidden" accept=".pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.markdown,.html,.htm,.csv,.json,.xlsx" onChange={(event) => onUpload(event.target.files)} />
      {uploading ? <Loader2 size={24} className="animate-spin text-sky-600" /> : <Upload size={24} className="text-slate-300" />}
      <p className="mt-3 text-sm font-semibold text-slate-700">{uploading ? "上传中..." : "点击上传或拖拽文件到此处"}</p>
      <p className="mt-1 text-xs text-slate-400">支持 PDF、DOCX、PPTX、TXT、Markdown、HTML、CSV、JSON、XLSX</p>
    </div>
  );
}

function UploadResultList({ results }: { results: UploadResult[] }) {
  if (!results.length) return null;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="space-y-2">
        {results.map((result, index) => (
          <div
            key={`${result.filename}-${index}`}
            className={cn(
              "flex min-w-0 items-start gap-3 rounded-xl px-3 py-2 text-xs",
              result.status === "success" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
            )}
          >
            {result.status === "success" ? <CheckCircle size={14} className="mt-0.5 shrink-0" /> : <AlertCircle size={14} className="mt-0.5 shrink-0" />}
            <div className="min-w-0">
              <p className="truncate font-semibold">{result.filename}</p>
              <p className="mt-0.5 break-words opacity-90">{result.message}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WikiCompactHeader({
  kb,
  fileCount,
  indexedCount,
  activeJob,
  onBack,
  onOpenGraph,
  onSettings,
  onRefresh,
}: {
  kb: KBMeta;
  fileCount: number;
  indexedCount: number;
  activeJob?: IngestionJob;
  onBack: () => void;
  onOpenGraph: () => void;
  onSettings: () => void;
  onRefresh: () => void;
}) {
  return (
    <section className={wikiCompactKnowledgeCard}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <button type="button" onClick={onBack} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800" title="返回知识库">
              <ArrowLeft size={16} />
            </button>
            <h1 className="truncate text-lg font-bold text-slate-950">{kb.name}</h1>
          </div>
          <p className="mt-1 truncate text-xs text-slate-500">{kb.description || "未填写描述"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button type="button" onClick={onOpenGraph} className={wikiIconButton} title="图谱浏览"><Network size={14} /></button>
          <button type="button" onClick={onSettings} className={wikiIconButton} title="知识库设置"><SlidersHorizontal size={14} /></button>
          <button type="button" onClick={onRefresh} className={wikiIconButton} title="刷新"><RefreshCw size={14} /></button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Badge variant="teal">Wiki 知识库</Badge>
        <Badge variant="secondary">{fileCount} 个文件</Badge>
        <Badge variant="success">{indexedCount} 已编译</Badge>
        {activeJob ? <Badge variant="info">处理中 {taskCompleted(activeJob) + taskFailed(activeJob)}/{activeJob.total_steps}</Badge> : null}
      </div>
    </section>
  );
}

function WikiLlmSettingsDialog({
  open,
  kb,
  chatModels,
  onClose,
  onSaved,
}: {
  open: boolean;
  kb: KBMeta;
  chatModels: ProviderModelOption[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [llmModel, setLlmModel] = useState(kbLlmModelValue(kb));
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [probeResult, setProbeResult] = useState<ModelProbeResult | null>(null);
  const [probeError, setProbeError] = useState("");
  const [error, setError] = useState("");
  const selectedLLM = chatModels.find((item) => item.value === llmModel);

  useEffect(() => {
    if (!open) return;
    setLlmModel(kbLlmModelValue(kb));
    setProbeResult(null);
    setProbeError("");
    setError("");
  }, [kb, open]);

  const testModel = async () => {
    if (!selectedLLM) return;
    setTesting(true);
    setProbeResult(null);
    setProbeError("");
    try {
      const result = await testProviderModel({
        provider_id: selectedLLM.providerId,
        model_id: selectedLLM.modelId,
        capability: "chat",
        sample_text: "NexAgent wiki model test",
      });
      setProbeResult(result);
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "模型检测失败");
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await updateKBModelConfig(kb.kb_id, { llm_model: llmModel });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Wiki LLM 配置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Wiki 知识库设置" description="配置用于页面编译、主题抽取和对话沉淀的 LLM。">
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">{kb.name}</p>
              <p className="mt-1 text-xs text-slate-500">Wiki 不需要 Embedding；文件内容会编译为页面、双链和关系图。</p>
            </div>
            <Badge variant="teal">Wiki</Badge>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <Field label="LLM 模型">
              <ModelPicker
                value={llmModel}
                options={chatModels}
                placeholder={kb.llm_info?.model || "选择 LLM 模型"}
                onChange={(option) => {
                  setLlmModel(option.value);
                  setProbeResult(null);
                  setProbeError("");
                }}
              />
            </Field>
            <button
              type="button"
              className={cn(outlineButton, "mt-6 justify-center")}
              disabled={!selectedLLM || testing}
              onClick={() => void testModel()}
            >
              {testing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              检测模型
            </button>
          </div>
          <ProbeNotice result={probeResult} error={probeError} />
        </div>

        {error ? <div className="rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-700">{error}</div> : null}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={outlineButton}>取消</button>
          <button type="button" onClick={() => void save()} disabled={saving || !llmModel} className={primarySmallButton}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存设置
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function WikiSourceToolbar({
  uploading,
  compiling,
  pendingCount,
  inputRef,
  onUpload,
  onProcessAll,
  onCompileWiki,
  onForceCompileWiki,
  files,
  jobs,
  onRetry,
  onCancel,
}: {
  uploading: boolean;
  compiling: boolean;
  pendingCount: number;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onUpload: (files: FileList | null) => void;
  onProcessAll: () => void;
  onCompileWiki: () => Promise<void>;
  onForceCompileWiki: () => Promise<void>;
  files: FileMeta[];
  jobs: IngestionJob[];
  onRetry: (jobId: string) => void;
  onCancel: (taskId: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 bg-white px-3 py-2">
      <WikiQuickUpload
        uploading={uploading}
        compiling={compiling}
        pendingCount={pendingCount}
        inputRef={inputRef}
        onUpload={onUpload}
        onProcessAll={onProcessAll}
        onCompileWiki={onCompileWiki}
        onForceCompileWiki={onForceCompileWiki}
      />
      <WikiTaskQueue jobs={jobs} files={files} onRetry={onRetry} onCancel={onCancel} />
    </div>
  );
}

function WikiSourceSection({
  files,
  uploading,
  pendingCount,
  inputRef,
  uploadResults,
  processingIds,
  compiling,
  activeSourceFileId,
  preview,
  previewLoading,
  jobs,
  llmLabel,
  llmTitle,
  indexedCount,
  compileStatus,
  candidateCount,
  needsReviewCount,
  failedSourceCount,
  activeStatus,
  onUpload,
  onProcessAll,
  onCompileWiki,
  onForceCompileWiki,
  onStatusFilter,
  onRetryFailed,
  onRetry,
  onCancel,
  onToggleSourceFilter,
  onProcess,
  onPreview,
  onDelete,
  onClosePreview,
}: {
  files: FileMeta[];
  uploading: boolean;
  pendingCount: number;
  inputRef: React.RefObject<HTMLInputElement | null>;
  uploadResults: UploadResult[];
  processingIds: Set<string>;
  compiling: boolean;
  activeSourceFileId: string;
  preview: ParsedFilePreview | null;
  previewLoading: boolean;
  jobs: IngestionJob[];
  llmLabel: string;
  llmTitle: string;
  indexedCount: number;
  compileStatus: { label: string; variant: "secondary" | "info" | "success" | "warning" | "error" };
  candidateCount: number;
  needsReviewCount: number;
  failedSourceCount: number;
  activeStatus: string;
  onUpload: (files: FileList | null) => void;
  onProcessAll: () => void;
  onCompileWiki: () => Promise<void>;
  onForceCompileWiki: () => Promise<void>;
  onStatusFilter: (status: string) => void;
  onRetryFailed: () => void;
  onRetry: (jobId: string) => void;
  onCancel: (taskId: string) => void;
  onToggleSourceFilter: (fileId: string) => void;
  onProcess: (fileId: string) => void;
  onPreview: (fileId: string) => void;
  onDelete: (fileId: string, filename: string) => void;
  onClosePreview: () => void;
}) {
  return (
    <section className="flex min-h-0 flex-col bg-white">
      <WikiSourceToolbar
        uploading={uploading}
        compiling={compiling}
        pendingCount={pendingCount}
        inputRef={inputRef}
        onUpload={onUpload}
        onProcessAll={onProcessAll}
        onCompileWiki={onCompileWiki}
        onForceCompileWiki={onForceCompileWiki}
        files={files}
        jobs={jobs}
        onRetry={onRetry}
        onCancel={onCancel}
      />
      <WikiStatusStrip
        llmLabel={llmLabel}
        llmTitle={llmTitle}
        indexedCount={indexedCount}
        fileCount={files.length}
        compileStatus={compileStatus}
        candidateCount={candidateCount}
        needsReviewCount={needsReviewCount}
        failedSourceCount={failedSourceCount}
        activeStatus={activeStatus}
        onStatusFilter={onStatusFilter}
        onRetryFailed={onRetryFailed}
        disabled={uploading}
      />
      <UploadResultList results={uploadResults} />
      <WikiFileList
        files={files}
        processingIds={processingIds}
        activeSourceFileId={activeSourceFileId}
        onToggleSourceFilter={onToggleSourceFilter}
        onProcess={onProcess}
        onPreview={onPreview}
        onDelete={onDelete}
      />
      {preview || previewLoading ? <PreviewPanel preview={preview} loading={previewLoading} onClose={onClosePreview} /> : null}
    </section>
  );
}

function WikiStatusStrip({
  llmLabel,
  llmTitle,
  indexedCount,
  fileCount,
  compileStatus,
  candidateCount,
  needsReviewCount,
  failedSourceCount,
  activeStatus,
  onStatusFilter,
  onRetryFailed,
  disabled,
}: {
  llmLabel: string;
  llmTitle: string;
  indexedCount: number;
  fileCount: number;
  compileStatus: { label: string; variant: "secondary" | "info" | "success" | "warning" | "error" };
  candidateCount: number;
  needsReviewCount: number;
  failedSourceCount: number;
  activeStatus: string;
  onStatusFilter: (status: string) => void;
  onRetryFailed: () => void;
  disabled: boolean;
}) {
  return (
    <div className={wikiStatusStrip}>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        <span className="min-w-0 shrink-0 max-w-full" title={llmTitle || llmLabel}>
          <Badge variant="info" className={wikiLlmStatusBadge}>{llmLabel}</Badge>
        </span>
        <Badge variant="secondary">{indexedCount}/{fileCount} 已编译</Badge>
        <Badge variant={compileStatus.variant}>{compileStatus.label}</Badge>
        {candidateCount ? <Badge variant="warning">{candidateCount} 个候选待处理</Badge> : null}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        <button type="button" onClick={() => onStatusFilter("pending_candidate")} className={cn(wikiQuickFilterButton, activeStatus === "pending_candidate" && wikiQuickFilterActive)}>
          候选 {candidateCount}
        </button>
        <button type="button" onClick={() => onStatusFilter("needs_review")} className={cn(wikiQuickFilterButton, activeStatus === "needs_review" && wikiQuickFilterActive)}>
          待复核 {needsReviewCount}
        </button>
        <button type="button" onClick={onRetryFailed} disabled={!failedSourceCount || disabled} className={wikiQuickFilterButton}>
          失败来源 {failedSourceCount}
        </button>
      </div>
    </div>
  );
}

function WikiQuickUpload({
  uploading,
  compiling,
  pendingCount,
  inputRef,
  onUpload,
  onProcessAll,
  onCompileWiki,
  onForceCompileWiki,
}: {
  uploading: boolean;
  compiling: boolean;
  pendingCount: number;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onUpload: (files: FileList | null) => void;
  onProcessAll: () => void;
  onCompileWiki: () => Promise<void>;
  onForceCompileWiki: () => Promise<void>;
}) {
  const [dragging, setDragging] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  return (
    <>
      <div className="flex min-w-0 items-center gap-1.5">
        <button
          type="button"
          onClick={() => setShowUpload(true)}
          disabled={uploading}
          className={wikiUploadDialogTrigger}
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          上传
        </button>
        <button
          type="button"
          onClick={() => void onCompileWiki()}
          disabled={compiling || uploading}
          className={wikiToolbarIconButton}
          title="重新编译 Wiki"
        >
          {compiling ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        </button>
        <button
          type="button"
          onClick={() => void onForceCompileWiki()}
          disabled={compiling || uploading}
          className={cn(wikiToolbarIconButton, "px-2")}
          title="强制重编译 Wiki"
        >
          强制
        </button>
        <button
          type="button"
          onClick={onProcessAll}
          disabled={!pendingCount || uploading}
          className={cn(wikiToolbarIconButton, "border-amber-200 text-amber-800")}
          title={pendingCount ? `编译 ${pendingCount} 个待处理素材` : "没有待编译素材"}
        >
          <ListChecks size={14} />
          {pendingCount ? <span className="text-[11px]">{pendingCount}</span> : null}
        </button>
      </div>
      <Dialog open={showUpload} onClose={() => setShowUpload(false)} title="上传文件" description="选择或拖拽文件到 Wiki 素材库。">
        <div
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            if (!uploading) {
              onUpload(event.dataTransfer.files);
              setShowUpload(false);
            }
          }}
          onClick={() => { if (!uploading) inputRef.current?.click(); }}
          className={cn(uploadDialogDropzone, uploading ? "cursor-wait opacity-80" : "cursor-pointer", dragging ? "border-sky-300 bg-sky-50" : "border-slate-200 bg-white hover:border-sky-200")}
        >
          <input ref={inputRef} type="file" multiple disabled={uploading} className="hidden" accept=".pdf,.docx,.doc,.pptx,.ppt,.txt,.md,.markdown,.html,.htm,.csv,.json,.xlsx" onChange={(event) => { onUpload(event.target.files); setShowUpload(false); }} />
          {uploading ? <Loader2 size={24} className="animate-spin text-sky-600" /> : <Upload size={24} className="text-slate-300" />}
          <p className="mt-3 text-sm font-semibold text-slate-700">{uploading ? "上传中..." : "点击上传或拖拽文件到此处"}</p>
          <p className="mt-1 text-xs text-slate-400">支持 PDF、DOCX、PPTX、TXT、Markdown、HTML、CSV、JSON、XLSX</p>
        </div>
      </Dialog>
    </>
  );
}

function WikiFileList({
  files,
  processingIds,
  activeSourceFileId,
  onToggleSourceFilter,
  onProcess,
  onPreview,
  onDelete,
}: {
  files: FileMeta[];
  processingIds: Set<string>;
  activeSourceFileId: string;
  onToggleSourceFilter: (fileId: string) => void;
  onProcess: (fileId: string) => void;
  onPreview: (fileId: string) => void;
  onDelete: (fileId: string, filename: string) => void;
}) {
  if (!files.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center">
        <FileText size={24} className="mx-auto text-slate-300" />
        <p className="mt-3 text-sm font-semibold text-slate-600">还没有上传文件</p>
      </div>
    );
  }
  return (
    <section className="bg-white px-2 pb-2 pt-1.5">
      <div className={wikiSourcePanelHeader}>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900"><FileText size={14} />素材</h2>
        <span className="text-xs text-slate-400">{files.length} files</span>
      </div>
      <div className="max-h-[220px] space-y-1 overflow-auto">
        {files.map((file) => {
          const status = statusMap[file.status];
          const Icon = status.icon;
          const processing = processingIds.has(file.file_id) || file.progress?.is_running;
          const sourceLabel = sourceTypeLabel(file);
          const metaTitle = `${formatBytes(file.file_size)} · ${file.chunk_count || 0} chunks · ${formatDate(file.updated_at || file.created_at)}`;
          return (
            <div
              key={file.file_id}
              className={cn(
                wikiFileRow,
                activeSourceFileId === file.file_id ? "border-sky-200 bg-sky-50" : "border-transparent bg-slate-50 hover:border-slate-200",
              )}
            >
              <div className="flex min-w-0 items-start gap-1.5">
                <button type="button" onClick={() => onToggleSourceFilter(file.file_id)} className={wikiSourceItemMain} title={`${file.filename}\n${metaTitle}`}>
                  <span className={wikiSourceFileNameLine}>{file.filename}</span>
                  <span className={wikiSourceFileMetaLine}>
                    <span className="min-w-0 truncate">{formatBytes(file.file_size)} · {file.chunk_count || 0} chunks</span>
                    {sourceLabel ? <Badge variant="info" className="px-1.5 py-0 text-[10px]">{sourceLabel}</Badge> : null}
                    <span className={cn(sourceStatusPill, status.variant === "error" && "text-rose-700", status.variant === "success" && "text-emerald-700", status.variant === "warning" && "text-amber-700")}>
                      <Icon size={11} className={processing ? "animate-spin" : ""} />
                      {status.label}
                    </span>
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-0.5 pt-0.5">
                  <button type="button" onClick={() => onPreview(file.file_id)} className={wikiInlineIconButton} title="预览"><Eye size={13} /></button>
                  <button type="button" onClick={() => onProcess(file.file_id)} disabled={!file.progress?.can_process && !file.progress?.can_index} className={wikiInlineIconButton} title="处理"><Play size={13} /></button>
                  <button type="button" onClick={() => onDelete(file.file_id, file.filename)} className={cn(wikiInlineIconButton, "hover:text-rose-600")} title="删除"><Trash2 size={13} /></button>
                </div>
              </div>
              {file.error ? <p className="mt-2 break-words rounded-md bg-rose-50 px-2 py-1.5 text-[11px] leading-4 text-rose-700">{file.error}</p> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function sourceTypeLabel(file: FileMeta) {
  const sourceType = String(file.processing_params?.source_type || "");
  if (sourceType === "conversation_crystallize") return "沉淀";
  if (sourceType === "conversation_attachment") return "附件沉淀";
  return "";
}

function WikiTaskQueue({ jobs, files, onRetry, onCancel }: { jobs: IngestionJob[]; files: FileMeta[]; onRetry: (jobId: string) => void; onCancel: (taskId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [showAllJobs, setShowAllJobs] = useState(false);
  const currentFileIds = useMemo(() => new Set(files.map((file) => file.file_id)), [files]);
  const successTimesByFile = useMemo(() => successfulTaskFileTimes(jobs), [jobs]);
  const activeJobs = jobs.filter(isActiveTask);
  const historyJobs = jobs.filter((job) => !isActiveTask(job)).sort((left, right) => taskTimeValue(right) - taskTimeValue(left));
  const actionableHistoryJobs = historyJobs.filter((job) => !isObsoleteHistoryTask(job, currentFileIds, successTimesByFile));
  const priorityHistoryJobs = actionableHistoryJobs.filter((job) => job.status !== "completed").slice(0, 3);
  const visibleHistoryJobs = showAllJobs ? actionableHistoryJobs : priorityHistoryJobs;
  const visibleJobs = [...activeJobs, ...visibleHistoryJobs];
  const hiddenJobCount = Math.max(0, actionableHistoryJobs.length - priorityHistoryJobs.length);
  const displayCount = activeJobs.length || priorityHistoryJobs.length;
  return (
    <div className="relative shrink-0">
      <button type="button" onClick={() => setOpen((next) => !next)} className={taskQueueTrigger} title="任务队列">
        <ListChecks size={14} />
        <span className="min-w-4 text-center text-[11px]">{displayCount}</span>
        {activeJobs.length ? <span className="ml-0.5 h-2 w-2 rounded-full bg-sky-500" /> : null}
      </button>
      {open ? (
        <div className={taskQueuePopover}>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-900">任务队列</h2>
            <span className="text-xs text-slate-400">{activeJobs.length ? `${activeJobs.length} 活跃` : `${actionableHistoryJobs.length} 历史任务`}</span>
          </div>
          <div className="max-h-80 space-y-2 overflow-auto">
            {visibleJobs.length ? visibleJobs.map((job) => {
              const running = job.status === "queued" || job.status === "running";
              const retryable = !["queued", "running", "completed"].includes(job.status);
              const completed = taskCompleted(job);
              const failed = taskFailed(job);
              const total = Math.max(1, Number(job.total_steps || 1));
              const percent = Number(job.progress) > 0 ? Math.round(Number(job.progress)) : Math.min(100, Math.round(((completed + failed) / total) * 100));
              return (
                <div key={job.task_id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <span className="shrink-0 rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">{taskKindLabel(job.kind)}</span>
                        <p className="truncate font-mono text-[11px] font-semibold text-slate-500" title={job.task_id}>{shortTaskId(job.task_id)}</p>
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-400">{completed} 完成 / {failed} 失败 / {job.total_steps} 总计</p>
                      {job.current_step && job.current_step !== "done" ? <p className="mt-0.5 truncate text-[11px] text-slate-400">{job.current_step}</p> : null}
                    </div>
                    <Badge variant={running ? "info" : job.status === "completed" ? "success" : "error"}>{jobLabel(job.status)}</Badge>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <div className={cn("h-full rounded-full", failed ? "bg-rose-400" : running ? "bg-sky-500" : "bg-emerald-500")} style={{ width: `${percent}%` }} />
                  </div>
                  {retryable || running ? (
                    <div className="mt-2 flex justify-end gap-1">
                      {retryable ? <button className={tinyButton} onClick={() => onRetry(job.task_id)}>重试</button> : null}
                      {running ? <button className={tinyButton} onClick={() => onCancel(job.task_id)}>取消</button> : null}
                    </div>
                  ) : null}
                </div>
              );
            }) : <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-xs text-slate-400">暂无任务</div>}
          </div>
          {hiddenJobCount ? (
            <button type="button" onClick={() => setShowAllJobs((next) => !next)} className="mt-2 inline-flex h-8 w-full items-center justify-center rounded-lg border border-slate-200 bg-white text-xs font-semibold text-slate-500 hover:bg-slate-50">
              {showAllJobs ? "收起历史任务" : `展开历史任务 ${hiddenJobCount}`}
            </button>
          ) : null}
        </div>
      ) : null}
      </div>
  );
}

function taskTimeValue(job: IngestionJob): number {
  const value = job.updated_at ?? job.created_at ?? "";
  const rawTime = typeof value === "number" ? value : Number(value);
  if (Number.isFinite(rawTime) && rawTime > 0) return rawTime < 10000000000 ? rawTime * 1000 : rawTime;
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function taskFileIds(job: IngestionJob): string[] {
  const ids = new Set<string>();
  const addFileId = (value: unknown) => {
    if (typeof value === "string" && value.trim()) ids.add(value);
  };

  const metadataFileIds = job.metadata?.file_ids;
  if (Array.isArray(metadataFileIds)) metadataFileIds.forEach(addFileId);
  addFileId(job.metadata?.file_id);
  addFileId(job.result?.current_file_id);

  const items = job.result?.items;
  if (Array.isArray(items)) {
    items.forEach((item) => {
      if (item && typeof item === "object" && "file_id" in item) {
        addFileId((item as { file_id?: unknown }).file_id);
      }
    });
  }

  return [...ids];
}

function successfulTaskFileTimes(jobs: IngestionJob[]): Map<string, number> {
  const times = new Map<string, number>();
  jobs.forEach((job) => {
    if (job.status !== "completed") return;
    const time = taskTimeValue(job);
    taskFileIds(job).forEach((fileId) => {
      times.set(fileId, Math.max(times.get(fileId) ?? 0, time));
    });
  });
  return times;
}

function isObsoleteHistoryTask(job: IngestionJob, currentFileIds: Set<string>, successTimesByFile: Map<string, number>): boolean {
  if (isActiveTask(job) || job.status === "completed") return false;
  const fileIds = taskFileIds(job);
  if (!fileIds.length) return false;
  if (fileIds.every((fileId) => !currentFileIds.has(fileId))) return true;
  const taskTime = taskTimeValue(job);
  return fileIds.every((fileId) => (successTimesByFile.get(fileId) ?? 0) > taskTime);
}

function FileList({ files, processingIds, onProcess, onPreview, onDelete }: { files: FileMeta[]; processingIds: Set<string>; onProcess: (fileId: string) => void; onPreview: (fileId: string) => void; onDelete: (fileId: string, filename: string) => void }) {
  if (!files.length) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-12 text-center">
        <FileText size={26} className="mx-auto text-slate-300" />
        <p className="mt-3 text-sm font-semibold text-slate-600">还没有上传文件</p>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">文档管理</h2>
        <span className="text-xs text-slate-400">{files.length} files</span>
      </div>
      <div className="space-y-2">
        {files.map((file) => {
          const status = statusMap[file.status];
          const Icon = status.icon;
          const processing = processingIds.has(file.file_id) || file.progress?.is_running;
          return (
            <div key={file.file_id} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-3">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-slate-400"><FileText size={16} /></div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-slate-800">{file.filename}</p>
                  <p className="mt-0.5 text-xs text-slate-400">{formatBytes(file.file_size)} · {file.chunk_count || 0} chunks · {formatDate(file.updated_at || file.created_at)}</p>
                </div>
                <Badge variant={status.variant}><Icon size={12} className={processing ? "animate-spin" : ""} />{status.label}</Badge>
                <button type="button" onClick={() => onPreview(file.file_id)} className={iconButton} title="预览"><Eye size={14} /></button>
                <button type="button" onClick={() => onProcess(file.file_id)} disabled={!file.progress?.can_process && !file.progress?.can_index} className={iconButton} title="处理"><Play size={14} /></button>
                <button type="button" onClick={() => onDelete(file.file_id, file.filename)} className={cn(iconButton, "hover:text-rose-600")} title="删除"><Trash2 size={14} /></button>
              </div>
              {file.error ? <p className="mt-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{file.error}</p> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ModelAndRetrievalPanel({
  kb,
  queryConfig,
  queryConfigMeta,
  embeddingModels,
  chatModels,
  rerankModels,
  onKbUpdated,
  onQueryConfigChange,
  onQueryConfigSaved,
  savingQueryConfig,
}: {
  kb: KBMeta;
  queryConfig: RetrievalConfig;
  queryConfigMeta: KnowledgeQueryConfigResponse | null;
  embeddingModels: ProviderModelOption[];
  chatModels: ProviderModelOption[];
  rerankModels: ProviderModelOption[];
  onKbUpdated: (kb: KBMeta) => void;
  onQueryConfigChange: (config: RetrievalConfig) => void;
  onQueryConfigSaved: () => void;
  savingQueryConfig: boolean;
}) {
  const [embedModel, setEmbedModel] = useState(kb.embed_info?.model || "");
  const [embedDimension, setEmbedDimension] = useState(kb.embed_info?.dimension || 1024);
  const [llmModel, setLlmModel] = useState(kbLlmModelValue(kb));
  const [probeResult, setProbeResult] = useState<ModelProbeResult | null>(null);
  const [probeError, setProbeError] = useState("");
  const [savingModel, setSavingModel] = useState(false);
  const [testing, setTesting] = useState(false);
  const selectedEmbedding = embeddingModels.find((item) => item.value === embedModel);
  const selectedLLM = chatModels.find((item) => item.value === llmModel);
  const selectedReranker = rerankModels.find((item) => item.value === queryConfig.reranker_model);
  const availableModes = queryConfigMeta?.available_modes?.length
    ? queryConfigMeta.available_modes
    : kb.kb_type === "milvus" ? ["vector", "keyword", "hybrid"] : ["lightrag_local", "lightrag_global", "lightrag_hybrid"];
  const notice = indexNotice(kb);

  const saveModel = async () => {
    setSavingModel(true);
    try {
      const result = await updateKBModelConfig(kb.kb_id, {
        embed_model: embedModel,
        embed_dimension: embedDimension,
        llm_model: kb.kb_type === "lightrag" ? llmModel : undefined,
        use_reranker: Boolean(queryConfig.use_reranker),
        reranker_model: queryConfig.reranker_model || "",
      });
      onKbUpdated(result.kb);
      if (result.requires_reindex) {
        alert(`模型配置已更新，${result.indexed_files} 个已入库文件需要重新处理。`);
      }
    } catch (error) {
      alert(error instanceof Error ? error.message : "保存模型配置失败");
    } finally {
      setSavingModel(false);
    }
  };

  const testEmbedding = async () => {
    if (!selectedEmbedding) return;
    setTesting(true);
    setProbeError("");
    setProbeResult(null);
    try {
      const result = await testProviderModel({ provider_id: selectedEmbedding.providerId, model_id: selectedEmbedding.modelId, capability: "embedding" });
      setProbeResult(result);
      if (result.dimension) setEmbedDimension(result.dimension);
    } catch (error) {
      setProbeError(error instanceof Error ? error.message : "模型检测失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">模型与检索配置</h2>
          <p className="mt-1 text-xs text-slate-500">Embedding 变更不会静默重建索引；Rerank 和检索参数可立即生效。</p>
        </div>
        <button type="button" onClick={saveModel} disabled={savingModel} className={outlineButton}>{savingModel ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}保存模型</button>
      </div>
      <div className="space-y-3">
        <Field label="Embedding 模型">
          <ModelPicker value={embedModel} options={embeddingModels} placeholder={kb.embed_info?.model || "选择 Embedding 模型"} onChange={(option) => { setEmbedModel(option.value); setEmbedDimension(option.dimension || embedDimension); }} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <Field label="向量维度">
            <input className={inputClass} type="number" min={1} max={8192} value={embedDimension} onChange={(event) => setEmbedDimension(Number(event.target.value))} />
          </Field>
          <button type="button" className={cn(outlineButton, "mt-6 justify-center")} disabled={!selectedEmbedding || testing} onClick={testEmbedding}>
            {testing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            检测
          </button>
        </div>
        <ProbeNotice result={probeResult} error={probeError} />
        {kb.kb_type === "lightrag" ? (
          <Field label="LLM 模型">
            <ModelPicker
              value={llmModel}
              options={chatModels}
              placeholder={selectedLLM?.label || kb.llm_info?.model || "选择 LLM 模型"}
              onChange={(option) => setLlmModel(option.value)}
            />
          </Field>
        ) : null}
        {notice ? (
          <div className={cn("rounded-xl border p-3 text-xs leading-5", notice.variant === "warning" ? "border-amber-100 bg-amber-50 text-amber-700" : "border-sky-100 bg-sky-50 text-sky-700")}>
            {notice.message}
          </div>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="检索模式">
            <ModelessSelect
              value={String(queryConfig.search_mode || queryConfig.mode || "hybrid")}
              options={availableModes.map((mode) => ({ value: mode, label: retrievalModeLabel(mode) }))}
              onChange={(value) => onQueryConfigChange({ ...queryConfig, mode: value as RetrievalMode, search_mode: value as RetrievalMode })}
            />
          </Field>
          <NumberField label="返回数量" value={queryConfig.final_top_k ?? 5} min={1} max={50} onChange={(value) => onQueryConfigChange({ ...queryConfig, final_top_k: value })} />
          <NumberField label="召回数量" value={queryConfig.recall_top_k ?? 30} min={1} max={200} onChange={(value) => onQueryConfigChange({ ...queryConfig, recall_top_k: value })} />
          <NumberField label="相似度阈值" value={queryConfig.similarity_threshold ?? 0} min={0} max={1} step={0.05} onChange={(value) => onQueryConfigChange({ ...queryConfig, similarity_threshold: value })} />
          {kb.kb_type === "milvus" ? (
            <>
              <NumberField label="向量权重" value={queryConfig.vector_weight ?? 0.7} min={0} max={1} step={0.1} onChange={(value) => onQueryConfigChange({ ...queryConfig, vector_weight: value })} />
              <NumberField label="BM25 权重" value={queryConfig.bm25_weight ?? queryConfig.keyword_weight ?? 0.3} min={0} max={1} step={0.1} onChange={(value) => onQueryConfigChange({ ...queryConfig, bm25_weight: value, keyword_weight: value })} />
              <NumberField label="BM25 Top K" value={queryConfig.bm25_top_k ?? 30} min={1} max={200} onChange={(value) => onQueryConfigChange({ ...queryConfig, bm25_top_k: value })} />
              <NumberField label="BM25 Drop" value={queryConfig.bm25_drop_ratio_search ?? 0} min={0} max={1} step={0.05} onChange={(value) => onQueryConfigChange({ ...queryConfig, bm25_drop_ratio_search: value })} />
            </>
          ) : null}
        </div>
        <label className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <span>
            <span className="block text-sm font-semibold text-slate-800">启用 Rerank</span>
            <span className="text-xs text-slate-500">用于提升最终排序质量。</span>
          </span>
          <input type="checkbox" checked={Boolean(queryConfig.use_reranker)} onChange={(event) => onQueryConfigChange({ ...queryConfig, use_reranker: event.target.checked })} />
        </label>
        {queryConfig.use_reranker ? (
          <Field label="Rerank 模型">
            <ModelPicker value={String(queryConfig.reranker_model || "")} options={rerankModels} placeholder={selectedReranker?.label || "选择 Rerank 模型"} onChange={(option) => onQueryConfigChange({ ...queryConfig, reranker_model: option.value })} />
          </Field>
        ) : null}
        <button type="button" onClick={onQueryConfigSaved} disabled={savingQueryConfig} className={primaryButton}>
          {savingQueryConfig ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          保存默认检索配置
        </button>
      </div>
    </div>
  );
}

function SearchPanel({ query, setQuery, indexedCount, searching, searched, searchError, searchWarnings, results, onSearch }: { query: string; setQuery: (value: string) => void; indexedCount: number; searching: boolean; searched: boolean; searchError: string; searchWarnings: SearchWarning[]; results: SearchResult[]; onSearch: () => void }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-900">检索测试</h2>
      <p className="mt-1 text-xs text-slate-500">{indexedCount ? `已入库 ${indexedCount} 个文件，可测试当前检索配置。` : "需要至少 1 个已入库文件才能测试检索。"}</p>
      <div className="mt-3 flex gap-2">
        <Input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && onSearch()} placeholder="输入检索问题" disabled={indexedCount === 0} className="flex-1" />
        <button type="button" onClick={onSearch} disabled={!query.trim() || searching || indexedCount === 0} className={cn("flex h-10 w-10 items-center justify-center rounded-xl text-white", !query.trim() || indexedCount === 0 ? "bg-slate-200" : "bg-sky-600 hover:bg-sky-700")}>
          {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
        </button>
      </div>
      {searched ? (
        <div className="mt-4 space-y-2">
          {searchError ? <div className="rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-700">{searchError}</div> : null}
          {!searchError && searchWarnings.length ? (
            <div className="space-y-2 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
              {searchWarnings.map((warning, index) => (
                <div key={`${warning.code || warning.message}-${index}`} className="flex flex-wrap items-center gap-2">
                  <Badge variant="warning">降级检索</Badge>
                  <span>{friendlySearchWarning(warning)}</span>
                  {warning.action ? <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-amber-700">{friendlySearchAction(warning.action)}</span> : null}
                </div>
              ))}
            </div>
          ) : null}
          {!searchError && results.length === 0 ? <div className="rounded-xl bg-slate-50 p-4 text-center text-xs text-slate-400">未找到相关结果，尝试换个关键词或调整检索模式。</div> : null}
          {results.map((result, index) => (
            <div key={`${result.file_id}-${index}`} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="truncate font-mono text-xs text-slate-400">{result.source || result.file_id || "unknown"}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-slate-600">{Math.round(result.score * 100)}%</span>
              </div>
              <p className="line-clamp-4 text-xs leading-5 text-slate-700">{result.content}</p>
              {result.evidence?.metadata?.degraded ? <Badge variant="warning" className="mt-2">降级检索</Badge> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function friendlySearchWarning(warning: SearchWarning) {
  if (warning.code === "forced_local_fallback") return "当前配置使用本地 shadow 索引检索。";
  if (warning.code === "milvus_collection_missing") return "Milvus collection 不存在，当前使用本地 shadow 索引检索。";
  if (warning.code === "milvus_dependency_missing") return "Milvus 依赖缺失，已使用本地降级检索。";
  if (warning.code === "milvus_service_unavailable") return "Milvus 服务不可用，已使用本地降级检索。";
  if (warning.code === "native_bm25_unavailable") return "原生 BM25 不可用，已使用本地关键词检索。";
  if (warning.code === "embedding_failed") return "Embedding 入库失败，当前使用本地关键词索引检索。";
  return warning.message || warning.code || "检索使用了降级路径。";
}

function friendlySearchAction(action: string) {
  if (action === "reindex_recommended") return "建议重新入库";
  if (action === "check_milvus") return "检查 Milvus";
  if (action === "check_embedding") return "检查 Embedding";
  if (action === "install_dependency") return "安装依赖";
  return action;
}

function kbLlmModelValue(kb: KBMeta): string {
  const model = kb.llm_info?.model || "";
  const provider = kb.llm_info?.provider || "";
  if (provider && model && !model.includes("::")) return `${provider}::${model}`;
  return model;
}

function indexNotice(kb: KBMeta): { variant: "info" | "warning"; message: string } | null {
  const vectorIndex = (kb.extra?.vector_index ?? {}) as Record<string, unknown>;
  if (vectorIndex.status === "degraded" || vectorIndex.status === "forced_local") {
    const reason = String(vectorIndex.reason || "");
    if (reason === "embedding_failed") {
      return { variant: "warning", message: "Embedding 入库失败，当前只使用本地 shadow 索引检索。请检查 Embedding 配置后重新处理文件。" };
    }
    if (reason === "native_bm25_unavailable") {
      return { variant: "warning", message: "Milvus BM25 schema 不可用，当前使用本地 shadow 索引检索。需要重建 Milvus collection 后再重新处理文件。" };
    }
    if (vectorIndex.status === "forced_local") {
      return { variant: "info", message: "当前知识库使用本地 shadow 索引检索，不会写入 Milvus collection。" };
    }
    return { variant: "warning", message: "Milvus 后端未成功写入，当前使用本地 shadow 索引检索。请检查 Milvus 服务；恢复后重新处理文件即可启用向量/BM25 检索。" };
  }
  if (kb.extra?.requires_reindex) {
    return { variant: "warning", message: "当前模型或分块配置与已有索引不一致。请在文档列表中重新处理文件，确保索引和检索配置一致。" };
  }
  return null;
}

function GraphOverviewCard({ kbId, summary, indexedCount }: { kbId: string; summary: KnowledgeGraphSummary | null; indexedCount: number }) {
  const router = useRouter();
  const nodes = summary?.stats?.nodes ?? 0;
  const edges = summary?.stats?.edges ?? 0;
  const files = summary?.stats?.files?.length ?? indexedCount;
  return (
    <div className="rounded-2xl border border-indigo-100 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Network size={15} />图谱概览</h2>
          <p className="mt-1 text-xs text-slate-500">独立工作台中浏览实体、关系和邻域子图。</p>
        </div>
        <Badge variant="violet">LightRAG</Badge>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <GraphStat label="实体" value={nodes} />
        <GraphStat label="关系" value={edges} />
        <GraphStat label="来源" value={files} />
      </div>
      {summary?.updated_at ? <p className="mt-3 text-xs text-slate-400">更新于 {formatDate(summary.updated_at)}</p> : null}
      <button type="button" onClick={() => router.push(`/knowledge/${kbId}/graph`)} className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 text-sm font-semibold text-white transition hover:bg-indigo-700">
        <Network size={15} />
        打开图谱工作台
        <ChevronRight size={14} />
      </button>
    </div>
  );
}

function GraphStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2">
      <p className="text-lg font-bold text-slate-900">{value}</p>
      <p className="mt-0.5 text-[11px] font-semibold text-slate-400">{label}</p>
    </div>
  );
}

function PreviewPanel({ preview, loading, onClose }: { preview: ParsedFilePreview | null; loading: boolean; onClose: () => void }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-slate-800">{preview?.file.filename || "解析预览"}</p>
          <p className="text-xs text-slate-400">{preview ? `${preview.chars} chars${preview.truncated ? " · 已截断" : ""}` : "加载中..."}</p>
        </div>
        <button type="button" onClick={onClose} className={iconButton}><X size={14} /></button>
      </div>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs leading-5 text-slate-700">{loading ? "加载中..." : preview?.content}</pre>
    </div>
  );
}

function JobHistory({ jobs, onRetry, onCancel }: { jobs: IngestionJob[]; onRetry: (jobId: string) => void; onCancel: (taskId: string) => void }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">处理任务</h2>
      <div className="space-y-2">
        {jobs.map((job) => {
          const running = job.status === "queued" || job.status === "running";
          const retryable = !["queued", "running", "completed"].includes(job.status);
          return (
            <div key={job.task_id} className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs font-semibold text-slate-500">{job.task_id}</p>
                  <p className="text-xs text-slate-400">{taskCompleted(job)} 完成 / {taskFailed(job)} 失败 / {job.total_steps} 总计</p>
                </div>
                <div className="flex items-center gap-1">
                  <Badge variant={running ? "info" : job.status === "completed" ? "success" : "error"}>{jobLabel(job.status)}</Badge>
                  {retryable ? <button className={tinyButton} onClick={() => onRetry(job.task_id)}>重试</button> : null}
                  {running ? <button className={tinyButton} onClick={() => onCancel(job.task_id)}>取消</button> : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1"><span className="text-xs font-semibold text-slate-700">{label}</span>{children}</label>;
}

function NumberField({ label, value, min, max, step = 1, onChange }: { label: string; value?: number; min?: number; max?: number; step?: number; onChange: (value: number) => void }) {
  return (
    <Field label={label}>
      <input type="number" min={min} max={max} step={step} value={value ?? ""} onChange={(event) => onChange(Number(event.target.value))} className={inputClass} />
    </Field>
  );
}

function ModelessSelect({ value, options, onChange }: { value: string; options: { value: string; label: string }[]; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const selected = options.find((item) => item.value === value);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((next) => !next)} className="flex h-10 w-full items-center justify-between rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700">
        {selected?.label || value}
        <ChevronDown size={14} className={cn("text-slate-400 transition", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="absolute z-20 mt-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-xl">
          {options.map((option) => (
            <button key={option.value} type="button" onClick={() => { onChange(option.value); setOpen(false); }} className={cn("block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50", value === option.value && "bg-sky-50 text-sky-700")}>{option.label}</button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ModelPicker({ value, options, placeholder, onChange }: { value: string; options: ProviderModelOption[]; placeholder: string; onChange: (option: ProviderModelOption) => void }) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const selected = options.find((item) => item.value === value);
  const visible = options.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((next) => !next)} className="flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 text-left text-sm">
        <span className={cn("truncate", selected ? "font-semibold text-slate-800" : "text-slate-400")}>{selected?.label || placeholder}</span>
        <ChevronDown size={15} className={cn("shrink-0 text-slate-400 transition", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="absolute z-20 mt-2 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="border-b border-slate-100 p-2"><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="搜索模型或供应商" className="h-9 w-full rounded-lg bg-slate-50 px-3 text-sm outline-none" /></div>
          <div className="max-h-64 overflow-auto p-1">
            {visible.length ? visible.map((option) => (
              <button key={option.value} type="button" onClick={() => { onChange(option); setOpen(false); setFilter(""); }} className={cn("flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left hover:bg-slate-50", value === option.value && "bg-sky-50")}>
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[10px] font-bold text-slate-500">{option.providerName.slice(0, 1)}</span>
                <span className="min-w-0"><span className="block truncate text-sm font-semibold text-slate-800">{option.label}</span><span className="block truncate text-xs text-slate-400">{option.detail}</span></span>
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
  if (error || result?.ok === false) return <div className="rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-700">{error || result?.message || "模型检测失败"}</div>;
  if (!result) return null;
  return <div className="rounded-xl border border-emerald-100 bg-emerald-50 p-3 text-xs text-emerald-700">{result.message} {result.dimension ? `维度 ${result.dimension}，` : ""}耗时 {result.latency_ms}ms。</div>;
}

function defaultQueryConfig(kbType: KBMeta["kb_type"]): RetrievalConfig {
  if (kbType === "lightrag") return { mode: "lightrag_hybrid", search_mode: "lightrag_hybrid", final_top_k: 5, recall_top_k: 30, similarity_threshold: 0 };
  if (kbType === "wiki") return { mode: "wiki", search_mode: "wiki", final_top_k: 10, recall_top_k: 30, similarity_threshold: 0 };
  return { mode: "hybrid", search_mode: "hybrid", final_top_k: 5, recall_top_k: 30, similarity_threshold: 0, vector_weight: 0.7, keyword_weight: 0.3, bm25_weight: 0.3, bm25_top_k: 30, bm25_drop_ratio_search: 0, use_reranker: false };
}

function retrievalModeLabel(mode: string) {
  return {
    vector: "向量检索",
    keyword: "关键词 BM25",
    hybrid: "混合检索",
    lightrag_local: "LightRAG Local",
    lightrag_global: "LightRAG Global",
    lightrag_hybrid: "LightRAG Hybrid",
    wiki: "Wiki 检索",
  }[mode] ?? mode;
}

function providerModelOptions(providers: ModelProvider[], capability: ProviderCapability): ProviderModelOption[] {
  return providers
    .filter((provider) => provider.is_enabled && (provider.capabilities ?? []).includes(capability))
    .flatMap((provider) => {
      const configs = provider.model_configs?.length ? provider.model_configs.filter((model) => model.type === capability) : provider.models.map((id): ProviderModelConfig => ({ id, display_name: id, type: capability }));
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

function wikiLlmStatusLabel(kb: KBMeta) {
  const model = kb.llm_info?.model?.trim() || "";
  const provider = kb.llm_info?.provider?.trim() || "";
  const shortModel = compactModelName(model);
  if (shortModel && provider && !provider.startsWith("config-")) return `LLM ${shortModel} · ${provider}`;
  if (shortModel) return `LLM ${shortModel}`;
  if (provider && !provider.startsWith("config-")) return `LLM ${provider}`;
  return "LLM 未配置";
}

function wikiFullLlmLabel(kb: KBMeta) {
  const model = kb.llm_info?.model?.trim() || "";
  const provider = kb.llm_info?.provider?.trim() || "";
  if (model && provider) return ["LLM", `${provider}/${model}`].join(" ");
  if (model) return `LLM ${model}`;
  if (provider) return `LLM ${provider}`;
  return "";
}

function compactModelName(model: string) {
  return model.split("/").filter(Boolean).pop() || model;
}

function isFailedWikiSource(file: FileMeta) {
  const status = String(file.status || "").toLowerCase();
  return status.includes("error") || status.includes("failed");
}

function wikiCompileStatus(files: FileMeta[], activeJob: IngestionJob | undefined, candidateCount: number): { label: string; variant: "secondary" | "info" | "success" | "warning" | "error" } {
  if (activeJob && isActiveTask(activeJob)) {
    return { label: activeJob.kind === "wiki_repair" ? "AI 修复中" : "编译中", variant: "info" };
  }
  if (files.some(isFailedWikiSource)) return { label: "部分失败", variant: "error" };
  if (candidateCount) return { label: "候选待处理", variant: "warning" };
  if (!files.length) return { label: "未上传", variant: "secondary" };
  if (files.every((file) => file.status === "indexed")) return { label: "编译完成", variant: "success" };
  return { label: "待编译", variant: "warning" };
}

function taskCompleted(job: IngestionJob) {
  return Number(job.result?.completed ?? 0);
}

function taskFailed(job: IngestionJob) {
  return Number(job.result?.failed ?? 0);
}

function isActiveTask(job: IngestionJob) {
  return job.status === "queued" || job.status === "running";
}

function taskKindLabel(kind: string) {
  return {
    knowledge_ingestion: "文件处理",
    wiki_compile: "Wiki 编译",
    wiki_repair: "AI 修复",
  }[kind] ?? "任务";
}

function shortTaskId(taskId: string) {
  if (!taskId) return "unknown";
  return taskId.length > 18 ? `${taskId.slice(0, 8)}...${taskId.slice(-6)}` : taskId;
}

function jobLabel(status: string) {
  return { queued: "排队中", running: "运行中", completed: "完成", failed: "失败", interrupted: "已中断", cancelled: "已取消" }[status] ?? status;
}

const inputClass = "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none transition focus:border-sky-300 focus:ring-2 focus:ring-sky-100 disabled:bg-slate-50 disabled:text-slate-400";
const outlineButton = "inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50";
const primaryButton = "inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
const primarySmallButton = "inline-flex h-9 items-center gap-2 rounded-lg bg-slate-950 px-3 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
const iconButton = "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 disabled:opacity-40";
const wikiIconButton = "inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 disabled:opacity-40";
const wikiInlineIconButton = "inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-35";
const wikiUploadDialogTrigger = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-slate-950 px-2.5 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50";
const wikiToolbarIconButton = "inline-flex h-8 items-center justify-center gap-1 rounded-md border bg-white px-2 text-xs font-semibold transition hover:bg-slate-50 disabled:opacity-45";
const wikiCompactKnowledgeCard = "rounded-lg border border-slate-200 bg-white px-3 py-3 shadow-sm";
const wikiStatusStrip = "flex flex-wrap items-center justify-between gap-x-2 gap-y-1 border-t border-slate-100 bg-white px-2.5 py-1.5";
const wikiLlmStatusBadge = "max-w-[160px] truncate";
const wikiQuickFilterButton = "inline-flex h-7 items-center justify-center rounded-md border border-slate-200 bg-white px-2 text-[11px] font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-45";
const wikiQuickFilterActive = "border-sky-200 bg-sky-50 text-sky-700";
const taskQueueTrigger = "inline-flex h-8 items-center justify-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-50 disabled:opacity-45";
const wikiSidebar = "space-y-2";
const uploadDialogDropzone = "flex min-h-52 flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition";
const taskQueuePopover = "absolute right-0 z-30 mt-2 w-[288px] rounded-xl border border-slate-200 bg-white p-3 shadow-xl";
const wikiSourcePanelHeader = "mb-1 flex items-center justify-between gap-2 px-0.5";
const wikiFileRow = "rounded-md border px-1.5 py-1.5 transition";
const wikiSourceItemMain = "flex min-w-0 flex-1 flex-col items-start gap-1 rounded px-1.5 py-1 text-left";
const wikiSourceFileNameLine = "block w-full min-w-0 truncate text-sm font-medium text-slate-800";
const wikiSourceFileMetaLine = "flex w-full min-w-0 flex-wrap items-center gap-1 text-[11px] text-slate-400";
const sourceStatusPill = "inline-flex h-5 items-center gap-1 rounded bg-white px-1.5 text-[10px] font-semibold text-slate-500";
const tinyButton = "rounded-md bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 hover:bg-slate-100";
