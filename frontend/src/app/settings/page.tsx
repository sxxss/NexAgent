"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  Edit3,
  Eye,
  EyeOff,
  Globe2,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  Wifi,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  createProvider,
  deleteProvider,
  fetchProviderModels,
  fetchProviders,
  fetchSearchConfig,
  testSearchConfig,
  updateProvider,
  updateSearchConfig,
  type ModelProvider,
  type ProviderCapability,
  type ProviderCreateBody,
  type ProviderModelConfig,
  type SearchConfig,
  type SearchProviderId,
  type SearchServiceId,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ProviderForm = {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  models_endpoint: string;
  api_key: string;
  capabilities: ProviderCapability[];
  default_models: ProviderModelConfig[];
  is_enabled: boolean;
  is_default: boolean;
};

type ProviderTemplate = Omit<ProviderForm, "api_key" | "is_default" | "default_models"> & {
  icon: string;
  models: ProviderModelConfig[];
};

type ProviderView = {
  key: string;
  provider?: ModelProvider;
  template?: ProviderTemplate;
  name: string;
  id: string;
  provider_type: string;
  base_url: string;
  capabilities: ProviderCapability[];
  models: ProviderModelConfig[];
  is_enabled: boolean;
  is_default: boolean;
  api_key_configured: boolean;
  created: boolean;
};

type SettingsTab = "models" | "search";

type SearchForm = {
  provider: SearchProviderId;
  preferred_provider: SearchServiceId;
  enabled_providers: SearchServiceId[];
  max_results: string;
  fetch_max_chars: string;
  tavily_api_key: string;
  provider_keys: Record<string, string>;
  provider_base_urls: Record<string, string>;
};

const CAPABILITIES: Array<{ value: ProviderCapability; label: string; tone: string }> = [
  { value: "chat", label: "Chat", tone: "bg-sky-50 text-sky-700" },
  { value: "embedding", label: "Embedding", tone: "bg-emerald-50 text-emerald-700" },
  { value: "rerank", label: "Rerank", tone: "bg-amber-50 text-amber-700" },
];

const DEFAULT_SEARCH_PROVIDERS: SearchConfig["providers"] = [
  {
    id: "duckduckgo",
    name: "DuckDuckGo / DDGS",
    recommended: false,
    requires_api_key: false,
    requires_base_url: false,
    description: "免 API Key 的开发兜底方案，稳定性受本机网络和搜索服务限制。",
    capabilities: ["web_search", "web_fetch"],
    enabled: true,
    configured: true,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "tavily",
    name: "Tavily",
    recommended: true,
    requires_api_key: true,
    requires_base_url: false,
    description: "面向 Agent 的结构化联网搜索，适合生产环境和深度研究。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "brave",
    name: "Brave Search",
    recommended: true,
    requires_api_key: true,
    requires_base_url: false,
    description: "通用 Web 搜索 API，适合作为生产环境的稳定联网搜索服务。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "serpapi",
    name: "SerpAPI",
    recommended: false,
    requires_api_key: true,
    requires_base_url: false,
    description: "聚合搜索结果 API，适合需要 Google 风格搜索结果的场景。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "bing",
    name: "Bing Web Search",
    recommended: false,
    requires_api_key: true,
    requires_base_url: false,
    description: "微软 Bing 官方搜索 API，适合企业订阅和稳定联网搜索。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "exa",
    name: "Exa",
    recommended: false,
    requires_api_key: true,
    requires_base_url: false,
    description: "面向 AI 应用的语义搜索，适合研究型查询和内容发现。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
  {
    id: "searxng",
    name: "SearxNG",
    recommended: false,
    requires_api_key: false,
    requires_base_url: true,
    description: "自托管元搜索服务，适合私有化部署和可控联网能力。",
    capabilities: ["web_search", "web_fetch"],
    enabled: false,
    configured: false,
    api_key_configured: false,
    base_url: "",
  },
];

const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  template("siliconflow-cn", "SiliconFlow", "https://api.siliconflow.cn/v1", ["chat", "embedding", "rerank"], [
    model("deepseek-ai/DeepSeek-V3.2", "chat"),
    model("Qwen/Qwen3-Embedding-0.6B", "embedding", { dimension: 1024, batch_size: 32 }),
    model("BAAI/bge-reranker-v2-m3", "rerank", { batch_size: 16 }),
  ]),
  template("dashscope", "DashScope", "https://dashscope.aliyuncs.com/compatible-mode/v1", ["chat", "embedding", "rerank"], [
    model("qwen-plus", "chat"),
    model("text-embedding-v4", "embedding", { dimension: 1024 }),
    model("gte-rerank-v2", "rerank"),
  ]),
  template("alibaba-coding-plan", "Aliyun Coding Plan (International)", "https://coding-intl.dashscope.aliyuncs.com/compatible-mode/v1", ["chat"], []),
  template("alibaba-coding-plan-cn", "Aliyun Coding Plan", "https://coding.dashscope.aliyuncs.com/compatible-mode/v1", ["chat"], []),
  template("deepseek", "DeepSeek", "https://api.deepseek.com", ["chat"], [model("deepseek-chat", "chat"), model("deepseek-reasoner", "chat")]),
  template("minimax", "MiniMax (International)", "https://api.minimax.io/v1", ["chat"], []),
  template("minimax-cn", "MiniMax", "https://api.minimaxi.com/v1", ["chat"], []),
  template("modelscope", "ModelScope", "https://api-inference.modelscope.cn/v1", ["chat", "embedding", "rerank"], []),
  template("moonshotai", "Moonshot (International)", "https://api.moonshot.ai/v1", ["chat"], []),
  template("moonshotai-cn", "Moonshot", "https://api.moonshot.cn/v1", ["chat"], [model("moonshot-v1-8k", "chat")]),
  template("openai", "OpenAI", "https://api.openai.com/v1", ["chat", "embedding"], [model("gpt-4o-mini", "chat"), model("text-embedding-3-small", "embedding", { dimension: 1536 })]),
  template("opencode", "OpenCode", "https://opencode.ai/zen/v1", ["chat"], []),
  template("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", ["chat"], []),
  template("siliconflow", "SiliconFlow (International)", "https://api.siliconflow.com/v1", ["chat", "embedding", "rerank"], []),
  template("zai", "Zhipu (Z.AI)", "https://api.z.ai/api/paas/v4", ["chat", "embedding"], [model("glm-4.5", "chat")]),
  template("zai-coding-plan", "Zhipu Coding Plan (Z.AI)", "https://api.z.ai/api/coding/paas/v4", ["chat"], []),
  template("zhipuai", "Zhipu (BigModel)", "https://open.bigmodel.cn/api/paas/v4", ["chat", "embedding"], []),
  template("zhipuai-coding-plan", "Zhipu Coding Plan (BigModel)", "https://open.bigmodel.cn/api/coding/paas/v4", ["chat"], []),
];

const EMPTY_FORM: ProviderForm = {
  id: "",
  name: "",
  provider_type: "openai",
  base_url: "",
  models_endpoint: "/models",
  api_key: "",
  capabilities: ["chat"],
  default_models: [],
  is_enabled: true,
  is_default: false,
};

const EMPTY_MODEL: ProviderModelConfig = {
  id: "",
  display_name: "",
  type: "chat",
  protocol_override: "",
  base_url_override: "",
  context_window: null,
  dimension: null,
  batch_size: null,
  input_price_per_1m: null,
  output_price_per_1m: null,
  currency: "USD",
};

const MASKED_API_KEY = "••••••••••••••••";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<SettingsTab>("models");
  const [keyword, setKeyword] = useState("");
  const [providerModalOpen, setProviderModalOpen] = useState(false);
  const [modelManagerOpen, setModelManagerOpen] = useState(false);
  const [modelEditorOpen, setModelEditorOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ModelProvider | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider | null>(null);
  const [form, setForm] = useState<ProviderForm>(EMPTY_FORM);
  const [modelDrafts, setModelDrafts] = useState<ProviderModelConfig[]>([]);
  const [remoteModels, setRemoteModels] = useState<ProviderModelConfig[]>([]);
  const [remoteFilter, setRemoteFilter] = useState<"all" | ProviderCapability>("all");
  const [remoteKeyword, setRemoteKeyword] = useState("");
  const [editingModelIndex, setEditingModelIndex] = useState<number | null>(null);
  const [modelForm, setModelForm] = useState<ProviderModelConfig>(EMPTY_MODEL);
  const [showApiKey, setShowApiKey] = useState(false);
  const [remoteError, setRemoteError] = useState("");
  const [searchFormPatch, setSearchFormPatch] = useState<Partial<SearchForm>>({});
  const [searchTestResult, setSearchTestResult] = useState<{ ok: boolean; latency_ms: number; message: string } | null>(null);
  const [searchTestProvider, setSearchTestProvider] = useState<SearchProviderId | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab") ?? window.localStorage.getItem("nexagent.settings.tab");
    if (!isSettingsTab(tab)) return;
    const timer = window.setTimeout(() => setActiveTab(tab), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: fetchProviders });
  const searchConfigQuery = useQuery({ queryKey: ["search-config"], queryFn: fetchSearchConfig });
  const providers = useMemo(() => providersQuery.data ?? [], [providersQuery.data]);
  const providerViews = useMemo(() => buildProviderViews(providers), [providers]);
  const filteredViews = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return providerViews;
    return providerViews.filter((item) =>
      [item.name, item.id, item.provider_type, item.base_url]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(q)),
    );
  }, [keyword, providerViews]);

  const enabledCount = providers.filter((provider) => provider.is_enabled).length;
  const modelCount = providers.reduce((total, provider) => total + getProviderModels(provider).length, 0);

  const baseSearchForm = useMemo<SearchForm>(() => {
    const config = searchConfigQuery.data;
    const providers = config?.providers ?? DEFAULT_SEARCH_PROVIDERS;
    return {
      provider: config?.provider ?? "auto",
      preferred_provider: config?.preferred_provider ?? "duckduckgo",
      enabled_providers: config?.enabled_providers ?? ["duckduckgo"],
      max_results: String(config?.max_results ?? 5),
      fetch_max_chars: String(config?.fetch_max_chars ?? 12000),
      tavily_api_key: config?.tavily_api_key_configured ? MASKED_API_KEY : "",
      provider_keys: Object.fromEntries(
        providers
          .filter((provider) => provider.requires_api_key)
          .map((provider) => [provider.id, provider.api_key_configured ? MASKED_API_KEY : ""]),
      ),
      provider_base_urls: Object.fromEntries(
        providers
          .filter((provider) => provider.requires_base_url)
          .map((provider) => [provider.id, provider.base_url ?? ""]),
      ),
    };
  }, [searchConfigQuery.data]);
  const searchForm = useMemo<SearchForm>(() => ({ ...baseSearchForm, ...searchFormPatch }), [baseSearchForm, searchFormPatch]);

  const saveProviderMutation = useMutation({
    mutationFn: async () => {
      const modelConfigs = editingProvider ? getProviderModels(editingProvider) : form.default_models;
      const body: ProviderCreateBody = {
        name: form.name.trim(),
        provider_type: form.provider_type,
        base_url: form.base_url.trim(),
        models_endpoint: form.models_endpoint.trim() || "/models",
        api_key: form.api_key === MASKED_API_KEY ? "" : form.api_key,
        capabilities: form.capabilities,
        models: modelConfigs.map((item) => item.id),
        model_configs: modelConfigs,
        is_enabled: form.is_enabled,
        is_default: form.is_default,
      };
      if (editingProvider) {
        const updateBody: Partial<ProviderCreateBody> = { ...body };
        if (!form.api_key || form.api_key === MASKED_API_KEY) delete updateBody.api_key;
        return updateProvider(editingProvider.id, updateBody);
      }
      return createProvider({ ...body, id: form.id.trim() || undefined });
    },
    onSuccess: async () => {
      closeProviderModal();
      await invalidateProviderData(queryClient);
    },
  });

  const saveModelsMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProvider) throw new Error("No provider selected");
      return updateProvider(selectedProvider.id, {
        models: modelDrafts.map((item) => item.id),
        model_configs: modelDrafts,
      });
    },
    onSuccess: async (provider) => {
      setSelectedProvider(provider);
      setModelDrafts(getProviderModels(provider));
      await invalidateProviderData(queryClient);
    },
  });

  const remoteModelsMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProvider) return { models: [] };
      return fetchProviderModels(selectedProvider.id);
    },
    onSuccess: (result) => {
      setRemoteError(result.warning ?? "");
      setRemoteModels(result.models);
    },
    onError: (error) => {
      setRemoteError(error instanceof Error ? error.message : String(error));
    },
  });

  const saveSearchMutation = useMutation({
    mutationFn: (override?: Partial<SearchForm>) => {
      const nextForm = { ...searchForm, ...override };
      const body: Parameters<typeof updateSearchConfig>[0] = {
        provider: nextForm.provider,
        preferred_provider: nextForm.preferred_provider,
        enabled_providers: nextForm.enabled_providers,
        max_results: clampNumber(nextForm.max_results, 1, 20, 5),
        fetch_max_chars: clampNumber(nextForm.fetch_max_chars, 1000, 50000, 12000),
        providers: buildSearchProviderUpdates(nextForm, searchConfigQuery.data?.providers ?? DEFAULT_SEARCH_PROVIDERS),
      };
      if (nextForm.tavily_api_key !== MASKED_API_KEY) {
        body.tavily_api_key = nextForm.tavily_api_key;
      }
      return updateSearchConfig(body);
    },
    onSuccess: async () => {
      setSearchTestResult(null);
      setSearchFormPatch({});
      await queryClient.invalidateQueries({ queryKey: ["search-config"] });
      await queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  const testSearchMutation = useMutation({
    mutationFn: (override?: Partial<SearchForm>) => {
      const nextForm = { ...searchForm, ...override };
      const body: Parameters<typeof testSearchConfig>[0] = {
        mode: "search",
        query: "NexAgent Agent framework latest news",
        provider: nextForm.provider,
        preferred_provider: nextForm.preferred_provider,
        enabled_providers: nextForm.enabled_providers,
        max_results: clampNumber(nextForm.max_results, 1, 20, 5),
        fetch_max_chars: clampNumber(nextForm.fetch_max_chars, 1000, 50000, 12000),
        providers: buildSearchProviderUpdates(nextForm, searchConfigQuery.data?.providers ?? DEFAULT_SEARCH_PROVIDERS),
      };
      if (nextForm.tavily_api_key && nextForm.tavily_api_key !== MASKED_API_KEY) {
        body.tavily_api_key = nextForm.tavily_api_key;
      }
      return testSearchConfig(body);
    },
    onMutate: (override) => {
      const nextForm = { ...searchForm, ...override };
      setSearchTestProvider(nextForm.provider);
      setSearchTestResult(null);
    },
    onSuccess: setSearchTestResult,
  });

  const openCreateProvider = (templateItem?: ProviderTemplate) => {
    setEditingProvider(null);
    setForm(templateItem ? formFromTemplate(templateItem) : EMPTY_FORM);
    setShowApiKey(false);
    setProviderModalOpen(true);
  };

  const openEditProvider = (provider: ModelProvider) => {
    setEditingProvider(provider);
    setForm(formFromProvider(provider));
    setShowApiKey(false);
    setProviderModalOpen(true);
  };

  const closeProviderModal = () => {
    setProviderModalOpen(false);
    setEditingProvider(null);
    setShowApiKey(false);
    setForm(EMPTY_FORM);
  };

  const openModelManager = (provider: ModelProvider) => {
    setSelectedProvider(provider);
    setModelDrafts(getProviderModels(provider));
    setRemoteModels([]);
    setRemoteError("");
    setRemoteFilter("all");
    setRemoteKeyword("");
    setModelManagerOpen(true);
  };

  const closeModelManager = () => {
    setModelManagerOpen(false);
    setSelectedProvider(null);
    setModelDrafts([]);
    setRemoteModels([]);
    setRemoteError("");
  };

  const openModelEditor = (index: number | null, modelConfig?: ProviderModelConfig) => {
    setEditingModelIndex(index);
    setModelForm(modelConfig ? normalizeModel(modelConfig) : EMPTY_MODEL);
    setModelEditorOpen(true);
  };

  const saveModelEditor = () => {
    const normalized = normalizeModel(modelForm);
    if (!normalized.id.trim()) return;
    setModelDrafts((items) => {
      if (editingModelIndex === null) return mergeModelConfig(items, normalized);
      return items.map((item, index) => (index === editingModelIndex ? normalized : item));
    });
    setModelEditorOpen(false);
  };

  const addRemoteModel = (item: ProviderModelConfig) => {
    setModelDrafts((items) => mergeModelConfig(items, item));
  };

  const removeModel = (id: string) => {
    setModelDrafts((items) => items.filter((item) => item.id !== id));
  };

  const remoteVisible = useMemo(() => {
    const existing = new Set(modelDrafts.map((item) => item.id));
    const q = remoteKeyword.trim().toLowerCase();
    return remoteModels.filter((item) => {
      if (remoteFilter !== "all" && item.type !== remoteFilter) return false;
      if (q && !item.id.toLowerCase().includes(q) && !(item.display_name || "").toLowerCase().includes(q)) return false;
      return true;
    }).map((item) => ({ ...item, added: existing.has(item.id) }));
  }, [modelDrafts, remoteFilter, remoteKeyword, remoteModels]);

  const switchSettingsTab = (tab: SettingsTab) => {
    setActiveTab(tab);
    window.localStorage.setItem("nexagent.settings.tab", tab);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    window.history.replaceState({}, "", `${url.pathname}?${url.searchParams.toString()}${url.hash}`);
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-[#fbfbfa]">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-950">模型与搜索配置</h1>
            <p className="mt-1 text-sm text-slate-500">统一管理模型供应商、联网搜索供应商和 Agent 外部信息能力。</p>
            <div className="mt-4 inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1 text-sm font-semibold">
              <button
                type="button"
                onClick={() => switchSettingsTab("models")}
                className={cn(
                  "rounded-lg px-3 py-1.5 transition",
                  activeTab === "models" ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800",
                )}
              >
                模型供应商
              </button>
              <button
                type="button"
                onClick={() => switchSettingsTab("search")}
                className={cn(
                  "rounded-lg px-3 py-1.5 transition",
                  activeTab === "search" ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800",
                )}
              >
                搜索服务
              </button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {activeTab === "models" ? (
              <>
                <StatPill value={providerViews.length} label="个供应商" />
                <StatPill value={enabledCount} label="个启用" />
                <StatPill value={modelCount} label="个模型" />
              </>
            ) : (
              <>
                <StatPill value={searchConfigQuery.data?.providers.length ?? 2} label="个搜索供应商" />
                <StatPill value={searchConfigQuery.data?.providers.filter((provider) => provider.enabled).length ?? 1} label="个启用" />
              </>
            )}
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {activeTab === "models" ? (
          <>
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <label className="flex h-10 w-full max-w-sm items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 shadow-sm">
                <Search size={16} className="text-slate-400" />
                <input
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  placeholder="搜索供应商..."
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400"
                />
              </label>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => openCreateProvider()} className={primaryButtonClass}>
                  <Plus size={16} />
                  新增供应商
                </button>
                <button
                  type="button"
                  onClick={() => void invalidateProviderData(queryClient)}
                  className={iconButtonClass}
                  title="刷新"
                >
                  <RefreshCw size={16} className={providersQuery.isFetching ? "animate-spin" : ""} />
                </button>
              </div>
            </div>

            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {filteredViews.map((item) => (
                <ProviderCard
                  key={item.key}
                  item={item}
                  onCreate={() => item.template && openCreateProvider(item.template)}
                  onEdit={() => item.provider && openEditProvider(item.provider)}
                  onManage={() => item.provider && openModelManager(item.provider)}
                  onToggle={() => item.provider && void updateProvider(item.provider.id, { is_enabled: !item.provider.is_enabled }).then(() => invalidateProviderData(queryClient))}
                  onDefault={() => item.provider && void updateProvider(item.provider.id, { is_default: true, is_enabled: true }).then(() => invalidateProviderData(queryClient))}
                  onDelete={() => item.provider && void deleteProvider(item.provider.id).then(() => invalidateProviderData(queryClient))}
                />
              ))}
            </section>
          </>
        ) : (
          <SearchSettingsPanel
            config={searchConfigQuery.data}
            form={searchForm}
            loading={searchConfigQuery.isFetching}
            saving={saveSearchMutation.isPending}
            testing={testSearchMutation.isPending}
            testProvider={searchTestProvider}
            testResult={searchTestResult}
            onFormChange={setSearchFormPatch}
            onSave={(override) => saveSearchMutation.mutate(override)}
            onTest={(override) => testSearchMutation.mutate(override)}
            onRefresh={() => void queryClient.invalidateQueries({ queryKey: ["search-config"] })}
          />
        )}
      </main>

      {activeTab === "models" ? (
        <>
          <ProviderModal
            open={providerModalOpen}
            editing={!!editingProvider}
            form={form}
            saving={saveProviderMutation.isPending}
            showApiKey={showApiKey}
            onShowApiKey={setShowApiKey}
            onChange={setForm}
            onClose={closeProviderModal}
            onSubmit={() => saveProviderMutation.mutate()}
          />

          <ModelManagerModal
            open={modelManagerOpen}
            provider={selectedProvider}
            modelDrafts={modelDrafts}
            remoteModels={remoteVisible}
            remoteFilter={remoteFilter}
            remoteKeyword={remoteKeyword}
            remoteLoading={remoteModelsMutation.isPending}
            remoteError={remoteError}
            saving={saveModelsMutation.isPending}
            onClose={closeModelManager}
            onFetchRemote={() => remoteModelsMutation.mutate()}
            onRemoteFilter={setRemoteFilter}
            onRemoteKeyword={setRemoteKeyword}
            onAddRemote={addRemoteModel}
            onAddManual={() => openModelEditor(null)}
            onEditModel={(index, item) => openModelEditor(index, item)}
            onRemoveModel={removeModel}
            onSave={() => saveModelsMutation.mutate()}
          />

          <ModelEditorModal
            open={modelEditorOpen}
            modelForm={modelForm}
            onChange={setModelForm}
            onClose={() => setModelEditorOpen(false)}
            onSubmit={saveModelEditor}
          />
        </>
      ) : null}
    </div>
  );
}

function SearchSettingsPanel({
  config,
  form,
  loading,
  saving,
  testing,
  testProvider,
  testResult,
  onFormChange,
  onSave,
  onTest,
  onRefresh,
}: {
  config?: SearchConfig;
  form: SearchForm;
  loading: boolean;
  saving: boolean;
  testing: boolean;
  testProvider: SearchProviderId | null;
  testResult: { ok: boolean; latency_ms: number; message: string } | null;
  onFormChange: (value: Partial<SearchForm>) => void;
  onSave: (override?: Partial<SearchForm>) => void;
  onTest: (override?: Partial<SearchForm>) => void;
  onRefresh: () => void;
}) {
  const effective = config?.effective_provider ?? "";
  const providers = config?.providers ?? DEFAULT_SEARCH_PROVIDERS;
  const testKey = testProvider ?? "";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#6d5cf0]">Web Search Runtime</p>
          <h2 className="mt-2 text-xl font-bold text-slate-950">搜索服务</h2>
          <p className="mt-1 text-sm text-slate-500">
            Agent 统一调用 web_search 和 web_fetch，底层供应商在这里切换。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onRefresh} className={iconButtonClass} title="刷新">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <SearchStrategyPanel
        form={form}
        providers={providers}
        effective={effective}
        onFormChange={onFormChange}
        onSave={onSave}
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {providers.map((provider) => (
          <SearchProviderCard
            key={provider.id}
            provider={provider}
            form={form}
            selected={form.provider === provider.id}
            effective={effective === provider.id}
            saving={saving}
            testing={testing && testKey === provider.id}
            testResult={testKey === provider.id ? testResult : null}
            onFormChange={onFormChange}
            onSave={onSave}
            onTest={onTest}
          />
        ))}
      </section>
    </div>
  );
}

function SearchStrategyPanel({
  form,
  providers,
  effective,
  onFormChange,
  onSave,
}: {
  form: SearchForm;
  providers: SearchConfig["providers"];
  effective: SearchServiceId | "";
  onFormChange: (value: Partial<SearchForm>) => void;
  onSave: (override?: Partial<SearchForm>) => void;
}) {
  const enabledProviders = providers.filter(
    (provider) => form.enabled_providers.includes(provider.id) && isSearchProviderConfigured(provider, form),
  );
  const selectableProviders = enabledProviders.length ? enabledProviders : providers.filter((provider) => provider.id === "duckduckgo");
  const manualProvider = form.provider === "auto" ? form.preferred_provider : form.provider;
  const selectedProvider = selectableProviders.find((provider) => provider.id === manualProvider) ?? selectableProviders[0];
  const [pickerOpen, setPickerOpen] = useState(false);
  const selectProvider = (providerId: SearchServiceId) => {
    setPickerOpen(false);
    onFormChange(form.provider === "auto" ? { ...form, preferred_provider: providerId } : { ...form, provider: providerId });
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-bold text-slate-950">服务商选择策略</h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">
            Auto 会优先使用指定服务商，失败后按已启用服务继续降级；手动模式只调用选中的服务商。
          </p>
          <p className="mt-2 text-xs font-semibold text-slate-400">
            当前实际服务：{effective ? providers.find((provider) => provider.id === effective)?.name ?? effective : "暂无可用服务"}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <div className="inline-flex h-10 rounded-xl border border-slate-200 bg-slate-50 p-1 text-sm font-semibold">
            <button
              type="button"
              onClick={() => onFormChange({ ...form, provider: "auto" })}
              className={cn("rounded-lg px-4 transition", form.provider === "auto" ? "bg-white text-[#6d5cf0] shadow-sm" : "text-slate-500 hover:text-slate-800")}
            >
              Auto
            </button>
            <button
              type="button"
              onClick={() => onFormChange({ ...form, provider: manualProvider })}
              className={cn("rounded-lg px-4 transition", form.provider !== "auto" ? "bg-white text-[#6d5cf0] shadow-sm" : "text-slate-500 hover:text-slate-800")}
            >
              手动
            </button>
          </div>
          <div className="relative">
            <button
              type="button"
              onClick={() => setPickerOpen((open) => !open)}
              className="inline-flex h-10 min-w-48 items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
            >
              <span className="truncate">{selectedProvider?.name ?? "选择服务商"}</span>
              <ChevronDown size={16} className={cn("text-slate-400 transition", pickerOpen && "rotate-180")} />
            </button>
            {pickerOpen ? (
              <div className="absolute right-0 top-12 z-20 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-[0_18px_42px_rgba(15,23,42,0.16)]">
                {selectableProviders.map((provider) => (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => selectProvider(provider.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition",
                      selectedProvider?.id === provider.id
                        ? "bg-[#efeafe] font-semibold text-[#6d5cf0]"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                    )}
                  >
                    <span className="truncate">{provider.name}</span>
                    {selectedProvider?.id === provider.id ? <Check size={15} /> : null}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <button type="button" onClick={() => onSave()} className={primaryButtonClass}>
            <Check size={16} />
            保存策略
          </button>
        </div>
      </div>
    </section>
  );
}

function SearchProviderCard({
  provider,
  form,
  selected,
  effective,
  saving,
  testing,
  testResult,
  onFormChange,
  onSave,
  onTest,
}: {
  provider: SearchConfig["providers"][number];
  form: SearchForm;
  selected: boolean;
  effective: boolean;
  saving: boolean;
  testing: boolean;
  testResult: { ok: boolean; latency_ms: number; message: string } | null;
  onFormChange: (value: Partial<SearchForm>) => void;
  onSave: (override?: Partial<SearchForm>) => void;
  onTest: (override?: Partial<SearchForm>) => void;
}) {
  const enabled = form.enabled_providers.includes(provider.id);
  const keyValue = form.provider_keys[provider.id] ?? "";
  const baseUrlValue = form.provider_base_urls[provider.id] ?? "";
  const configuredByForm = isSearchProviderConfigured(provider, form);
  const canEnable = provider.id === "duckduckgo" || configuredByForm;
  const update = (patch: Partial<SearchForm>) => onFormChange({ ...form, ...patch });
  const setEnabled = (next: boolean) => {
    const enabledProviders = new Set(form.enabled_providers);
    if (next && canEnable) enabledProviders.add(provider.id);
    if (!next && provider.id !== "duckduckgo") enabledProviders.delete(provider.id);
    update({ enabled_providers: Array.from(enabledProviders) as SearchServiceId[] });
  };
  const setProviderKey = (value: string) => {
    update({ provider_keys: { ...form.provider_keys, [provider.id]: value } });
  };
  const setProviderBaseUrl = (value: string) => {
    update({ provider_base_urls: { ...form.provider_base_urls, [provider.id]: value } });
  };
  const saveOverride = (): Partial<SearchForm> => ({
    provider: selected ? provider.id : form.provider,
    enabled_providers: form.enabled_providers,
    provider_keys: form.provider_keys,
    provider_base_urls: form.provider_base_urls,
  });

  return (
    <div className={cn(searchCardClass, selected || effective ? activeSearchCardClass : "border-slate-200", !enabled && "bg-white/75")}>
      <SearchCardHeader
        icon={provider.id === "tavily" ? Wifi : Globe2}
        title={provider.name}
        badge={provider.recommended ? "推荐" : provider.id === "duckduckgo" ? "默认兜底" : "可选"}
        active={effective}
        enabled={enabled}
        configured={configuredByForm}
        description={provider.description}
      />

      <div className="mt-4 flex min-h-8 flex-wrap gap-2">
        {provider.capabilities.map((item) => (
          <span key={item} className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-600">
            {item}
          </span>
        ))}
      </div>

      <div className="mt-5 min-h-[150px] space-y-4">
        <SharedSearchFields form={form} onChange={update} />
        {provider.requires_api_key ? (
          <Field label={`${provider.name} API Key`}>
            <div className="relative">
              <KeyRound size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="password"
                value={keyValue}
                onChange={(event) => setProviderKey(event.target.value)}
                placeholder={provider.api_key_configured ? MASKED_API_KEY : "输入 API Key 后可启用"}
                className={cn(inputClass, "pl-9")}
              />
            </div>
          </Field>
        ) : null}
        {provider.requires_base_url ? (
          <Field label={`${provider.name} Base URL`}>
            <input
              value={baseUrlValue}
              onChange={(event) => setProviderBaseUrl(event.target.value)}
              placeholder="https://search.example.com"
              className={inputClass}
            />
          </Field>
        ) : null}
      </div>

      {testResult ? <SearchTestResult result={testResult} /> : null}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-5">
        <button
          type="button"
          onClick={() => setEnabled(!enabled)}
          disabled={provider.id === "duckduckgo" || (!enabled && !canEnable)}
          className={cn(
            "inline-flex h-10 items-center justify-center rounded-xl border px-4 text-sm font-semibold transition disabled:opacity-50",
            enabled ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50",
          )}
        >
          {enabled ? "已启用" : canEnable ? "启用" : "待配置"}
        </button>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={() => onSave(saveOverride())} disabled={saving} className={outlineButtonClass}>
          {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
          保存
          </button>
          <button
            type="button"
            onClick={() => onTest({ provider: provider.id, enabled_providers: [provider.id], provider_keys: form.provider_keys, provider_base_urls: form.provider_base_urls })}
            disabled={testing || !canEnable}
            className={primaryButtonClass}
          >
            {testing ? <Loader2 size={16} className="animate-spin" /> : <Wifi size={16} />}
            测试
          </button>
        </div>
      </div>
    </div>
  );
}

function SearchCardHeader({
  icon: Icon,
  title,
  badge,
  active,
  enabled,
  configured,
  description,
}: {
  icon: LucideIcon;
  title: string;
  badge: string;
  active: boolean;
  enabled: boolean;
  configured: boolean;
  description: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#efeafe] text-[#6d5cf0]">
            <Icon size={20} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate font-bold text-slate-950">{title}</h3>
              <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-700">{badge}</span>
            </div>
            <p className="mt-1 text-xs text-slate-500">{active ? "当前调用" : enabled ? "已启用" : configured ? "未启用" : "待配置"}</p>
          </div>
        </div>
        <p className="mt-4 min-h-[48px] text-sm leading-6 text-slate-500">{description}</p>
      </div>
      <span
        className={cn(
          "inline-flex h-7 shrink-0 items-center rounded-md px-2 text-xs font-bold",
          active
            ? "bg-[#efeafe] text-[#6d5cf0]"
            : enabled
              ? "bg-emerald-50 text-emerald-700"
              : configured
                ? "bg-slate-100 text-slate-500"
                : "bg-amber-50 text-amber-700",
        )}
      >
        {active ? "Active" : enabled ? "Enabled" : configured ? "Idle" : "Config"}
      </span>
    </div>
  );
}

function SharedSearchFields({ form, onChange }: { form: SearchForm; onChange: (patch: Partial<SearchForm>) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="搜索结果数">
        <input
          type="number"
          min={1}
          max={20}
          value={form.max_results}
          onChange={(event) => onChange({ max_results: event.target.value })}
          className={inputClass}
        />
      </Field>
      <Field label="网页抓取长度">
        <input
          type="number"
          min={1000}
          max={50000}
          value={form.fetch_max_chars}
          onChange={(event) => onChange({ fetch_max_chars: event.target.value })}
          className={inputClass}
        />
      </Field>
    </div>
  );
}

function SearchTestResult({ result }: { result: { ok: boolean; latency_ms: number; message: string } }) {
  return (
    <div
      className={cn(
        "mt-5 rounded-xl border px-3 py-3 text-xs leading-5",
        result.ok ? "border-emerald-100 bg-emerald-50 text-emerald-700" : "border-amber-100 bg-amber-50 text-amber-800",
      )}
    >
      <div className="mb-1 font-bold">{result.ok ? "测试通过" : "测试未通过"} · {result.latency_ms}ms</div>
      <div className="max-h-32 overflow-auto whitespace-pre-wrap">{result.message}</div>
    </div>
  );
}

function ProviderCard({
  item,
  onCreate,
  onEdit,
  onManage,
  onToggle,
  onDefault,
  onDelete,
}: {
  item: ProviderView;
  onCreate: () => void;
  onEdit: () => void;
  onManage: () => void;
  onToggle: () => void;
  onDefault: () => void;
  onDelete: () => void;
}) {
  const inactive = !item.is_enabled;
  return (
    <article
      className={cn(
        "group overflow-hidden rounded-xl border bg-white transition",
        inactive
          ? "border-slate-100 bg-white/70 opacity-70 grayscale hover:opacity-90"
          : "border-slate-200 shadow-sm hover:-translate-y-0.5 hover:shadow-[0_18px_36px_rgba(15,23,42,0.08)]",
      )}
    >
      <div className="p-5">
        <div className="flex items-start gap-3">
          <ProviderLogo name={item.name} enabled={item.is_enabled} />
          <div className="min-w-0 flex-1">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-bold text-slate-800">{item.name}</h2>
                <p className="truncate font-mono text-xs text-slate-400">{item.id}</p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <span className={cn("inline-flex h-7 min-w-[58px] shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 text-xs font-semibold", item.is_enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>
                  {item.is_enabled ? "已启用" : "未启用"}
                </span>
                <span className={cn("h-2 w-2 shrink-0 rounded-full", item.is_enabled ? "bg-emerald-500" : "bg-slate-200")} />
              </div>
            </div>
          </div>
        </div>

        <div className="mt-5 space-y-2 text-sm">
          <InfoLine label="Base URL" value={item.base_url || "-"} />
          <InfoLine label="类型" value={item.provider_type || "openai"} />
          <InfoLine label="已启用" value={`${item.models.length} 个模型`} />
        </div>

        <div className="mt-4 flex flex-wrap gap-1.5">
          {item.capabilities.map((capability) => (
            <CapabilityBadge key={capability} capability={capability} />
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2 border-t border-slate-100 bg-slate-50/80 px-5 py-3">
        {item.created ? (
          <>
            <button type="button" onClick={onManage} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-[#9a3fc4] hover:bg-white">
              <Settings2 size={14} />
              管理模型
            </button>
            <button type="button" onClick={onEdit} className={cn(miniButtonClass, "ml-auto")} title="编辑供应商">
              <Edit3 size={14} />
            </button>
            <button type="button" onClick={onToggle} className={miniButtonClass} title={item.is_enabled ? "停用供应商" : "启用供应商"}>
              {item.is_enabled ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            <button type="button" onClick={onDefault} disabled={item.is_default} className={miniButtonClass} title={item.is_default ? "默认供应商" : "设为默认"}>
              <Check size={14} />
            </button>
            <button type="button" onClick={onDelete} className={cn(miniButtonClass, "hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600")} title="删除供应商">
              <Trash2 size={14} />
            </button>
          </>
        ) : (
          <button type="button" onClick={onCreate} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-semibold text-[#9a3fc4] hover:bg-white">
            <Plus size={14} />
            配置并启用
          </button>
        )}
      </div>
    </article>
  );
}

function ProviderModal({
  open,
  editing,
  form,
  saving,
  showApiKey,
  onShowApiKey,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  editing: boolean;
  form: ProviderForm;
  saving: boolean;
  showApiKey: boolean;
  onShowApiKey: (value: boolean) => void;
  onChange: (value: ProviderForm) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const update = (patch: Partial<ProviderForm>) => onChange({ ...form, ...patch });
  const canRevealApiKey = form.api_key !== MASKED_API_KEY;
  return (
    <Modal open={open} onClose={onClose} width="max-w-2xl">
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <ModalHeader title={editing ? "编辑供应商" : "新增供应商"} onClose={onClose} />
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Provider ID">
            <input
              value={form.id}
              onChange={(event) => update({ id: slugify(event.target.value) })}
              disabled={editing}
              placeholder="my-provider"
              className={inputClass}
            />
          </Field>
          <Field label="展示名称">
            <input value={form.name} onChange={(event) => update({ name: event.target.value })} placeholder="My Provider" className={inputClass} />
          </Field>
          <Field label="Base URL">
            <input value={form.base_url} onChange={(event) => update({ base_url: event.target.value })} placeholder="https://api.example.com/v1" className={inputClass} />
          </Field>
          <Field label="Provider Type">
            <select value={form.provider_type} onChange={(event) => update({ provider_type: event.target.value })} className={inputClass}>
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
              <option value="google">google</option>
              <option value="ollama">ollama</option>
              <option value="custom">custom</option>
            </select>
          </Field>
          <Field label="API Key">
            <div className="relative">
              <input
                value={form.api_key}
                onChange={(event) => update({ api_key: event.target.value })}
                onFocus={() => {
                  if (form.api_key === MASKED_API_KEY) update({ api_key: "" });
                }}
                type={showApiKey ? "text" : "password"}
                placeholder={editing ? "已配置时留空表示不修改" : ""}
                className={cn(inputClass, "pr-10")}
              />
              <button
                type="button"
                disabled={!canRevealApiKey}
                onClick={() => {
                  if (canRevealApiKey) onShowApiKey(!showApiKey);
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
                title={canRevealApiKey ? (showApiKey ? "隐藏 API Key" : "显示 API Key") : "已保存的 API Key 不会回传，重新输入后可显示/隐藏。"}
              >
                {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {form.api_key === MASKED_API_KEY ? (
              <p className="mt-1 text-xs font-normal text-slate-400">出于安全考虑，已保存的 API Key 不会回传到前端；点击输入框重新输入后可显示/隐藏。</p>
            ) : null}
          </Field>
          <Field label="模型列表路径">
            <input value={form.models_endpoint} onChange={(event) => update({ models_endpoint: event.target.value })} placeholder="/models" className={inputClass} />
            <p className="mt-1 text-xs font-normal text-slate-400">用于拉取远程模型列表，默认拼接为 Base URL + /models。/model 这类单模型查询接口不能用于拉取列表。</p>
          </Field>
        </div>

        <section>
          <div className="mb-2 text-sm font-semibold text-slate-700">能力</div>
          <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-2">
            {CAPABILITIES.map((item) => {
              const active = form.capabilities.includes(item.value);
              return (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => update({ capabilities: toggleCapability(form.capabilities, item.value) })}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold transition",
                    active ? "bg-[#b14fd6] text-white" : "bg-slate-50 text-slate-500 hover:bg-slate-100",
                  )}
                >
                  {active ? <Check size={14} /> : <Plus size={14} />}
                  {item.label}
                </button>
              );
            })}
          </div>
        </section>

        <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 p-3">
          <div>
            <div className="text-sm font-semibold text-slate-700">状态</div>
            <div className="text-xs text-slate-400">启用后模型会进入首页模型选择列表。</div>
          </div>
          <button type="button" onClick={() => update({ is_enabled: !form.is_enabled })} className={cn(switchClass, form.is_enabled && "bg-[#b14fd6]")}>
            <span className={cn("h-5 w-5 rounded-full bg-white shadow transition", form.is_enabled && "translate-x-5")} />
          </button>
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={outlineButtonClass}>取消</button>
          <button type="submit" disabled={saving || !form.name.trim()} className={primaryButtonClass}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            确认
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ModelManagerModal({
  open,
  provider,
  modelDrafts,
  remoteModels,
  remoteFilter,
  remoteKeyword,
  remoteLoading,
  remoteError,
  saving,
  onClose,
  onFetchRemote,
  onRemoteFilter,
  onRemoteKeyword,
  onAddRemote,
  onAddManual,
  onEditModel,
  onRemoveModel,
  onSave,
}: {
  open: boolean;
  provider: ModelProvider | null;
  modelDrafts: ProviderModelConfig[];
  remoteModels: Array<ProviderModelConfig & { added?: boolean }>;
  remoteFilter: "all" | ProviderCapability;
  remoteKeyword: string;
  remoteLoading: boolean;
  remoteError: string;
  saving: boolean;
  onClose: () => void;
  onFetchRemote: () => void;
  onRemoteFilter: (value: "all" | ProviderCapability) => void;
  onRemoteKeyword: (value: string) => void;
  onAddRemote: (model: ProviderModelConfig) => void;
  onAddManual: () => void;
  onEditModel: (index: number, model: ProviderModelConfig) => void;
  onRemoveModel: (id: string) => void;
  onSave: () => void;
}) {
  const counts = countModels(remoteModels);
  return (
    <Modal open={open} onClose={onClose} width="max-w-5xl">
      <div className="space-y-6">
        <ModalHeader title={provider ? `${provider.name} - 模型配置` : "模型配置"} onClose={onClose} />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-700">已启用模型 ({modelDrafts.length})</div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onFetchRemote} className={primaryButtonClass} disabled={remoteLoading}>
              {remoteLoading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              获取远程模型
            </button>
            <button type="button" onClick={onAddManual} className={outlineButtonClass}>
              <Plus size={16} />
              手动添加
            </button>
          </div>
        </div>

        <div className="overflow-hidden rounded-xl border border-slate-200">
          <div className="grid grid-cols-[minmax(220px,1fr)_110px_110px_110px_130px_96px] bg-slate-50 px-4 py-3 text-xs font-semibold text-slate-400">
            <span>模型</span>
            <span>类型</span>
            <span>上下文</span>
            <span>维度</span>
            <span>价格 / 1M</span>
            <span className="text-right">操作</span>
          </div>
          <div className="max-h-80 overflow-y-auto bg-white">
            {modelDrafts.length ? modelDrafts.map((item, index) => (
              <div key={item.id} className="grid grid-cols-[minmax(220px,1fr)_110px_110px_110px_130px_96px] items-center border-t border-slate-100 px-4 py-3 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-semibold text-slate-800">{item.display_name || item.id}</div>
                  <div className="truncate font-mono text-xs text-slate-400">{item.id}</div>
                </div>
                <CapabilityBadge capability={item.type} />
                <span className="text-slate-500">{item.context_window || "-"}</span>
                <span className="text-slate-500">{item.dimension || "-"}</span>
                <span className="font-mono text-xs text-slate-500">{priceSummary(item)}</span>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => onEditModel(index, item)} className={miniButtonClass} title="模型参数">
                    <Settings2 size={14} />
                  </button>
                  <button type="button" onClick={() => onRemoveModel(item.id)} className={cn(miniButtonClass, "border-rose-200 text-rose-500 hover:bg-rose-50")} title="删除模型">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )) : (
              <div className="px-4 py-8 text-center text-sm text-slate-400">还没有启用模型，可以拉取远程模型或手动添加。</div>
            )}
          </div>
        </div>

        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm font-semibold text-slate-700">远端候选模型 ({remoteModels.length})</div>
            <label className="flex h-9 w-64 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3">
              <Search size={15} className="text-slate-400" />
              <input value={remoteKeyword} onChange={(event) => onRemoteKeyword(event.target.value)} placeholder="搜索模型..." className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
            </label>
            <div className="flex rounded-xl bg-slate-100 p-1 text-sm">
              <Segment active={remoteFilter === "all"} onClick={() => onRemoteFilter("all")}>全部 {counts.all}</Segment>
              <Segment active={remoteFilter === "chat"} onClick={() => onRemoteFilter("chat")}>Chat {counts.chat}</Segment>
              <Segment active={remoteFilter === "embedding"} onClick={() => onRemoteFilter("embedding")}>Embedding {counts.embedding}</Segment>
              <Segment active={remoteFilter === "rerank"} onClick={() => onRemoteFilter("rerank")}>Rerank {counts.rerank}</Segment>
            </div>
          </div>
          {remoteError ? <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-600">{remoteError}</div> : null}
          <div className="max-h-80 overflow-y-auto rounded-xl border border-slate-200 bg-white">
            {remoteModels.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onAddRemote(item)}
                disabled={item.added}
                className="grid w-full grid-cols-[minmax(220px,1fr)_110px_110px_48px] items-center border-b border-slate-100 px-4 py-3 text-left text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-55"
              >
                <span className="truncate font-semibold text-slate-800">{item.id}</span>
                <CapabilityBadge capability={item.type} />
                <span className="text-slate-400">{item.dimension || item.context_window || "N/A"}</span>
                <span className="ml-auto flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 bg-white">
                  {item.added ? <CheckCircle2 size={15} className="text-slate-400" /> : <Plus size={15} />}
                </span>
              </button>
            ))}
            {!remoteModels.length ? <div className="px-4 py-8 text-center text-sm text-slate-400">点击“获取远程模型”后会显示候选模型。</div> : null}
          </div>
        </section>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={outlineButtonClass}>关闭</button>
          <button type="button" onClick={onSave} disabled={saving} className={primaryButtonClass}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
            保存模型
          </button>
        </div>
      </div>
    </Modal>
  );
}

function ModelEditorModal({
  open,
  modelForm,
  onChange,
  onClose,
  onSubmit,
}: {
  open: boolean;
  modelForm: ProviderModelConfig;
  onChange: (value: ProviderModelConfig) => void;
  onClose: () => void;
  onSubmit: () => void;
}) {
  const update = (patch: Partial<ProviderModelConfig>) => onChange({ ...modelForm, ...patch });
  return (
    <Modal open={open} onClose={onClose} width="max-w-2xl">
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <ModalHeader title="模型配置" onClose={onClose} />
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-xs font-semibold text-slate-400">模型 ID</div>
          <input value={modelForm.id} onChange={(event) => update({ id: event.target.value, display_name: modelForm.display_name || event.target.value })} className="mt-2 w-full bg-transparent font-mono text-sm text-slate-800 outline-none" placeholder="provider/model-id" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="展示名称">
            <input value={modelForm.display_name || ""} onChange={(event) => update({ display_name: event.target.value })} className={inputClass} />
          </Field>
          <Field label="模型类型">
            <select value={modelForm.type} onChange={(event) => update({ type: event.target.value as ProviderCapability })} className={inputClass}>
              <option value="chat">chat</option>
              <option value="embedding">embedding</option>
              <option value="rerank">rerank</option>
            </select>
          </Field>
          <Field label="协议覆盖">
            <input value={modelForm.protocol_override || ""} onChange={(event) => update({ protocol_override: event.target.value })} placeholder="可选" className={inputClass} />
          </Field>
          <Field label="Base URL 覆盖">
            <input value={modelForm.base_url_override || ""} onChange={(event) => update({ base_url_override: event.target.value })} placeholder="可选" className={inputClass} />
          </Field>
          {modelForm.type === "chat" ? (
            <Field label="上下文">
              <input value={modelForm.context_window ?? ""} onChange={(event) => update({ context_window: toNumber(event.target.value) })} type="number" placeholder="可选" className={inputClass} />
            </Field>
          ) : null}
          {modelForm.type === "embedding" ? (
            <>
              <Field label="维度">
                <input value={modelForm.dimension ?? ""} onChange={(event) => update({ dimension: toNumber(event.target.value) })} type="number" className={inputClass} />
              </Field>
              <Field label="Batch Size">
                <input value={modelForm.batch_size ?? ""} onChange={(event) => update({ batch_size: toNumber(event.target.value) })} type="number" className={inputClass} />
              </Field>
            </>
          ) : null}
          {modelForm.type === "rerank" ? (
            <Field label="Batch Size">
              <input value={modelForm.batch_size ?? ""} onChange={(event) => update({ batch_size: toNumber(event.target.value) })} type="number" className={inputClass} />
            </Field>
          ) : null}
          <Field label="输入价格 / 1M tokens">
            <input value={modelForm.input_price_per_1m ?? ""} onChange={(event) => update({ input_price_per_1m: toNumber(event.target.value) })} type="number" min={0} step="0.000001" placeholder="例如 0.2" className={inputClass} />
          </Field>
          <Field label="输出价格 / 1M tokens">
            <input value={modelForm.output_price_per_1m ?? ""} onChange={(event) => update({ output_price_per_1m: toNumber(event.target.value) })} type="number" min={0} step="0.000001" placeholder="例如 0.6" className={inputClass} />
          </Field>
          <Field label="计价货币">
            <select value={modelForm.currency || "USD"} onChange={(event) => update({ currency: event.target.value })} className={inputClass}>
              <option value="USD">USD</option>
              <option value="CNY">CNY</option>
              <option value="EUR">EUR</option>
              <option value="JPY">JPY</option>
            </select>
          </Field>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={outlineButtonClass}>取消</button>
          <button type="submit" disabled={!modelForm.id.trim()} className={primaryButtonClass}>确定</button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ open, onClose, width, children }: { open: boolean; onClose: () => void; width: string; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="关闭弹窗" onClick={onClose} className="absolute inset-0 bg-black/45" />
      <div className={cn("relative z-10 max-h-[92vh] w-full overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl", width)}>
        {children}
      </div>
    </div>
  );
}

function ModalHeader({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-xl font-bold text-slate-950">{title}</h2>
      <button type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700">
        <X size={20} />
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm font-semibold text-slate-600">
      {label}
      <div className="mt-2">{children}</div>
    </label>
  );
}

function Segment({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn("rounded-lg px-3 py-1.5 font-medium transition", active ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800")}>
      {children}
    </button>
  );
}

function ProviderLogo({ name, enabled }: { name: string; enabled: boolean }) {
  return (
    <div className={cn("flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border text-base font-black", enabled ? "border-slate-100 bg-white text-[#6c4df6] shadow-sm" : "border-slate-100 bg-slate-50 text-slate-300")}>
      {name.slice(0, 1).toUpperCase()}
    </div>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[78px_minmax(0,1fr)] gap-3">
      <span className="text-slate-400">{label}</span>
      <span className="truncate font-medium text-slate-600">{value}</span>
    </div>
  );
}

function CapabilityBadge({ capability }: { capability: ProviderCapability }) {
  const config = CAPABILITIES.find((item) => item.value === capability) ?? CAPABILITIES[0];
  return <span className={cn("inline-flex w-fit items-center rounded-md px-2 py-1 text-xs font-semibold", config.tone)}>{config.label}</span>;
}

function StatPill({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-500 shadow-sm">
      <span className="text-slate-900">{value}</span> {label}
    </div>
  );
}

function buildProviderViews(providers: ModelProvider[]): ProviderView[] {
  const byTemplateId = new Map(PROVIDER_TEMPLATES.map((item) => [item.id, item]));
  const usedTemplateIds = new Set<string>();
  const existing = providers.map((provider) => {
    const templateItem = findTemplate(provider);
    if (templateItem) usedTemplateIds.add(templateItem.id);
    return toProviderView(provider, templateItem);
  });
  const missing = PROVIDER_TEMPLATES
    .filter((item) => !usedTemplateIds.has(item.id) && !providers.some((provider) => provider.id === item.id || byTemplateId.get(provider.id)?.id === item.id))
    .map((item) => toTemplateView(item));
  return [...existing, ...missing].sort((a, b) => Number(b.is_enabled) - Number(a.is_enabled) || a.name.localeCompare(b.name));
}

function toProviderView(provider: ModelProvider, templateItem?: ProviderTemplate): ProviderView {
  return {
    key: `provider-${provider.id}`,
    provider,
    template: templateItem,
    name: provider.name,
    id: provider.id,
    provider_type: provider.provider_type,
    base_url: provider.base_url || "",
    capabilities: normalizeCapabilities(provider.capabilities ?? templateItem?.capabilities),
    models: getProviderModels(provider),
    is_enabled: provider.is_enabled,
    is_default: provider.is_default,
    api_key_configured: provider.api_key_configured,
    created: true,
  };
}

function toTemplateView(item: ProviderTemplate): ProviderView {
  return {
    key: `template-${item.id}`,
    template: item,
    name: item.name,
    id: item.id,
    provider_type: item.provider_type,
    base_url: item.base_url,
    capabilities: item.capabilities,
    models: [],
    is_enabled: false,
    is_default: false,
    api_key_configured: false,
    created: false,
  };
}

function formFromTemplate(item: ProviderTemplate): ProviderForm {
  return {
    id: item.id,
    name: item.name,
    provider_type: item.provider_type,
    base_url: item.base_url,
    models_endpoint: item.models_endpoint,
    api_key: "",
    capabilities: item.capabilities,
    default_models: item.models,
    is_enabled: item.is_enabled,
    is_default: false,
  };
}

function formFromProvider(provider: ModelProvider): ProviderForm {
  return {
    id: provider.id,
    name: provider.name,
    provider_type: provider.provider_type || "openai",
    base_url: provider.base_url || "",
    models_endpoint: provider.models_endpoint || "/models",
    api_key: provider.api_key_configured ? MASKED_API_KEY : "",
    capabilities: normalizeCapabilities(provider.capabilities),
    default_models: getProviderModels(provider),
    is_enabled: provider.is_enabled,
    is_default: provider.is_default,
  };
}

function getProviderModels(provider: ModelProvider): ProviderModelConfig[] {
  if (provider.model_configs?.length) return provider.model_configs.map(normalizeModel);
  return (provider.models ?? []).map((id) => inferModelConfig(id));
}

function findTemplate(provider: ModelProvider) {
  return PROVIDER_TEMPLATES.find((item) => item.id === provider.id || item.name === provider.name || item.base_url === provider.base_url);
}

function template(id: string, name: string, baseUrl: string, capabilities: ProviderCapability[], models: ProviderModelConfig[]): ProviderTemplate {
  return {
    id,
    icon: name.slice(0, 1),
    name,
    provider_type: "openai",
    base_url: baseUrl,
    models_endpoint: "/models",
    capabilities,
    models,
    is_enabled: false,
  };
}

function model(id: string, type: ProviderCapability, patch: Partial<ProviderModelConfig> = {}): ProviderModelConfig {
  return normalizeModel({ id, display_name: id, type, ...patch });
}

function inferModelConfig(id: string): ProviderModelConfig {
  const lower = id.toLowerCase();
  if (lower.includes("rerank")) return model(id, "rerank", { batch_size: 16 });
  if (lower.includes("embed") || lower.includes("bge-m3") || lower.includes("text-embedding")) {
    return model(id, "embedding", { dimension: lower.includes("3-large") ? 3072 : 1024, batch_size: 32 });
  }
  return model(id, "chat");
}

function normalizeModel(item: ProviderModelConfig): ProviderModelConfig {
  return {
    id: item.id,
    display_name: item.display_name || item.id,
    type: item.type || "chat",
    protocol_override: item.protocol_override || "",
    base_url_override: item.base_url_override || "",
    context_window: item.context_window ?? null,
    dimension: item.dimension ?? null,
    batch_size: item.batch_size ?? null,
    input_price_per_1m: item.input_price_per_1m ?? null,
    output_price_per_1m: item.output_price_per_1m ?? null,
    currency: item.currency || "USD",
  };
}

function priceSummary(item: ProviderModelConfig) {
  const input = item.input_price_per_1m ?? 0;
  const output = item.output_price_per_1m ?? 0;
  if (!input && !output) return "-";
  return `${item.currency || "USD"} ${input}/${output}`;
}

function normalizeCapabilities(value?: ProviderCapability[]) {
  const values = (value?.length ? value : ["chat"]).filter((item): item is ProviderCapability => ["chat", "embedding", "rerank"].includes(item));
  return Array.from(new Set(values));
}

function isSettingsTab(value: string | null): value is SettingsTab {
  return value === "models" || value === "search";
}

function toggleCapability(values: ProviderCapability[], capability: ProviderCapability) {
  if (values.includes(capability)) {
    const next = values.filter((item) => item !== capability);
    return next.length ? next : values;
  }
  return [...values, capability];
}

function mergeModelConfig(items: ProviderModelConfig[], item: ProviderModelConfig) {
  const normalized = normalizeModel(item);
  if (items.some((existing) => existing.id === normalized.id)) return items.map((existing) => existing.id === normalized.id ? normalized : existing);
  return [...items, normalized];
}

function countModels(items: ProviderModelConfig[]) {
  return {
    all: items.length,
    chat: items.filter((item) => item.type === "chat").length,
    embedding: items.filter((item) => item.type === "embedding").length,
    rerank: items.filter((item) => item.type === "rerank").length,
  };
}

function buildSearchProviderUpdates(form: SearchForm, providers: SearchConfig["providers"]) {
  return Object.fromEntries(
    providers.map((provider) => [
      provider.id,
      {
        enabled: form.enabled_providers.includes(provider.id),
        api_key: form.provider_keys[provider.id],
        base_url: form.provider_base_urls[provider.id],
      },
    ]),
  );
}

function isSearchProviderConfigured(provider: SearchConfig["providers"][number], form: SearchForm) {
  if (provider.id === "duckduckgo") return true;
  if (provider.requires_api_key) {
    const key = form.provider_keys[provider.id] ?? "";
    return Boolean((key && key !== MASKED_API_KEY) || provider.api_key_configured);
  }
  if (provider.requires_base_url) {
    return Boolean(form.provider_base_urls[provider.id] || provider.base_url);
  }
  return true;
}

function toNumber(value: string) {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function clampNumber(value: string, min: number, max: number, fallback: number) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9-_]/g, "-").replace(/-+/g, "-");
}

async function invalidateProviderData(queryClient: ReturnType<typeof useQueryClient>) {
  await queryClient.invalidateQueries({ queryKey: ["providers"] });
  await queryClient.invalidateQueries({ queryKey: ["models"] });
}

const inputClass = "h-10 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-[#b14fd6] focus:ring-4 focus:ring-[#b14fd6]/10 disabled:bg-slate-50 disabled:text-slate-400";
const primaryButtonClass = "inline-flex h-10 items-center justify-center gap-2 rounded-xl bg-[#b14fd6] px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-[#287da8] disabled:opacity-50";
const outlineButtonClass = "inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50";
const iconButtonClass = "flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-600 shadow-sm transition hover:bg-slate-50";
const miniButtonClass = "flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 hover:text-slate-800 disabled:bg-emerald-50 disabled:text-emerald-600";
const switchClass = "flex h-6 w-11 items-center rounded-full bg-slate-300 p-0.5 transition";
const searchCardClass = "flex h-full min-h-[430px] flex-col rounded-2xl border bg-white p-5 shadow-sm transition";
const activeSearchCardClass = "border-[#6d5cf0] shadow-[0_14px_32px_rgba(109,92,240,0.12)]";
