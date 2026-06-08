"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  Code2,
  Edit3,
  FileArchive,
  FileText,
  Folder,
  GitBranch,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import {
  createCustomSkill,
  fetchInstalledMCP,
  fetchSkillHistory,
  fetchRemoteSkillList,
  fetchSkillFileContent,
  fetchSkillRegistry,
  fetchSkills,
  fetchTools,
  installRemoteSkill,
  installSkill,
  testSkill,
  uninstallSkill,
  updateSkill,
  uploadSkill,
  type RemoteSkillCandidate,
  type SkillFileContent,
  type SkillHistoryRecord,
  type SkillInfo,
  type SkillIssue,
  type ToolInfo,
  type MCPServer,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type SkillForm = {
  id: string;
  name: string;
  description: string;
  tags: string;
  required_mcp_ids: string;
  required_tools: string;
  content: string;
  force: boolean;
};

type RemoteForm = {
  source: string;
  id: string;
  subdir: string;
  branch: string;
  force: boolean;
};

type UploadForm = {
  id: string;
  file: File | null;
  force: boolean;
};

type SkillTestState = {
  ok: boolean;
  message: string;
  content_hash?: string;
  issues?: SkillIssue[];
};

type InstallMode = "manual" | "remote" | "upload";

type SkillFile = { path: string; size: number; kind: string; text: boolean };

type FileTreeNode = {
  name: string;
  path: string;
  children: Map<string, FileTreeNode>;
  file?: SkillFile;
};

const emptySkillForm: SkillForm = {
  id: "",
  name: "",
  description: "",
  tags: "",
  required_mcp_ids: "",
  required_tools: "",
  content: "",
  force: false,
};

const emptyRemoteForm: RemoteForm = {
  source: "",
  id: "",
  subdir: "",
  branch: "main",
  force: false,
};

const emptyUploadForm: UploadForm = {
  id: "",
  file: null,
  force: false,
};

export default function SkillsPage() {
  const queryClient = useQueryClient();
  const [skillForm, setSkillForm] = useState<SkillForm>(emptySkillForm);
  const [remoteForm, setRemoteForm] = useState<RemoteForm>(emptyRemoteForm);
  const [uploadForm, setUploadForm] = useState<UploadForm>(emptyUploadForm);
  const [remoteCandidates, setRemoteCandidates] = useState<RemoteSkillCandidate[]>([]);
  const [selectedRemoteKeys, setSelectedRemoteKeys] = useState<string[]>([]);
  const [installMode, setInstallMode] = useState<InstallMode>("manual");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<SkillInfo | null>(null);
  const [error, setError] = useState("");
  const [results, setResults] = useState<Record<string, SkillTestState | { ok: false; message: string }>>({});

  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: fetchSkills });
  const registryQuery = useQuery({ queryKey: ["skill-registry"], queryFn: fetchSkillRegistry });
  const toolsQuery = useQuery({ queryKey: ["tools"], queryFn: fetchTools });
  const mcpQuery = useQuery({ queryKey: ["mcp-installed"], queryFn: fetchInstalledMCP });
  const skills = useMemo(() => skillsQuery.data ?? [], [skillsQuery.data]);
  const registry = useMemo(() => registryQuery.data ?? [], [registryQuery.data]);
  const toolOptions = useMemo(() => toolsQuery.data ?? [], [toolsQuery.data]);
  const mcpOptions = useMemo(() => mcpQuery.data ?? [], [mcpQuery.data]);
  const installedIds = useMemo(() => new Set(skills.map((skill) => skill.id || skill.name)), [skills]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["skills"] });
    void queryClient.invalidateQueries({ queryKey: ["skill-registry"] });
    void queryClient.invalidateQueries({ queryKey: ["tools"] });
    void queryClient.invalidateQueries({ queryKey: ["mcp-installed"] });
  };

  const resetDialog = () => {
    setDialogOpen(false);
    setReplaceTarget(null);
    setInstallMode("manual");
    setSkillForm(emptySkillForm);
    setRemoteForm(emptyRemoteForm);
    setUploadForm(emptyUploadForm);
    setRemoteCandidates([]);
    setSelectedRemoteKeys([]);
    setError("");
  };

  const openAddDialog = () => {
    resetDialog();
    setDialogOpen(true);
  };

  const openReplaceDialog = (skill: SkillInfo) => {
    const id = skill.id || skill.name;
    setSelectedSkill(null);
    setReplaceTarget(skill);
    setInstallMode("upload");
    setSkillForm({
      id,
      name: skill.name,
      description: skill.description || "",
      tags: (skill.tags ?? []).join(", "),
      required_mcp_ids: (skill.required_mcp_ids ?? []).join(", "),
      required_tools: (skill.required_tools ?? []).join(", "),
      content: skill.content ?? skill.content_preview ?? "",
      force: true,
    });
    setRemoteForm({ ...emptyRemoteForm, id, force: true });
    setUploadForm({ ...emptyUploadForm, id, force: true });
    setRemoteCandidates([]);
    setSelectedRemoteKeys([]);
    setError("");
    setDialogOpen(true);
  };

  const manualMutation = useMutation({
    mutationFn: () => {
      const targetId = replaceTarget ? replaceTarget.id || replaceTarget.name : "";
      const payload = {
        name: skillForm.name.trim(),
        description: skillForm.description.trim(),
        version: "0.1.0",
        tags: csv(skillForm.tags),
        required_mcp_ids: csv(skillForm.required_mcp_ids),
        required_tools: csv(skillForm.required_tools),
        content: skillForm.content,
        force: Boolean(targetId),
      };
      return targetId
        ? createCustomSkill({ id: targetId, ...payload })
        : createCustomSkill({ id: skillForm.id.trim(), ...payload });
    },
    onSuccess: () => {
      resetDialog();
      refresh();
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  const remoteMutation = useMutation({
    mutationFn: async () => {
      const targetId = replaceTarget ? replaceTarget.id || replaceTarget.name : "";
      const selected = remoteCandidates.filter((item) => selectedRemoteKeys.includes(remoteCandidateKey(item)));
      if (targetId && selected.length > 1) throw new Error("替换单个 Skill 时只能选择一个远程 Skill。");
      if (selected.length) {
        return Promise.all(
          selected.map((item) =>
            installRemoteSkill({
              source: remoteForm.source.trim(),
              id: targetId || item.id,
              subdir: item.subdir,
              branch: remoteForm.branch.trim() || "main",
              force: Boolean(targetId),
            }),
          ),
        );
      }
      return installRemoteSkill({
        source: remoteForm.source.trim(),
        id: targetId || remoteForm.id.trim() || undefined,
        subdir: remoteForm.subdir.trim() || undefined,
        branch: remoteForm.branch.trim() || "main",
        force: Boolean(targetId),
      });
    },
    onSuccess: () => {
      resetDialog();
      refresh();
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  const discoverRemoteMutation = useMutation({
    mutationFn: () => fetchRemoteSkillList({ source: remoteForm.source.trim(), branch: remoteForm.branch.trim() || "main" }),
    onSuccess: (items) => {
      setRemoteCandidates(items);
      setSelectedRemoteKeys(items.length === 1 ? [remoteCandidateKey(items[0])] : []);
      if (items.length === 1) {
        setRemoteForm((prev) => ({ ...prev, id: items[0].id, subdir: items[0].subdir }));
      }
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  const uploadMutation = useMutation({
    mutationFn: () => {
      const targetId = replaceTarget ? replaceTarget.id || replaceTarget.name : "";
      if (!uploadForm.file) throw new Error("请选择 .zip、.skill 或 .md 文件");
      return uploadSkill(uploadForm.file, { id: targetId || uploadForm.id.trim() || undefined, force: Boolean(targetId) });
    },
    onSuccess: () => {
      resetDialog();
      refresh();
    },
    onError: (err) => setError(err instanceof Error ? err.message : String(err)),
  });

  const runTest = async (id: string) => {
    try {
      const result = await testSkill(id);
      setResults((prev) => ({ ...prev, [id]: result }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [id]: { ok: false, message: err instanceof Error ? err.message : String(err) } }));
    }
  };

  const submit = () => {
    setError("");
    if (!replaceTarget) {
      const conflict = findAddConflict(installMode, skillForm, remoteForm, uploadForm, remoteCandidates, selectedRemoteKeys, skills);
      if (conflict) {
        setError(`已存在同名 Skill：${conflict.name}（${conflict.id || conflict.name}）。请使用该 Skill 卡片上的 Replace 进行替换。`);
        return;
      }
    }
    if (installMode === "manual") manualMutation.mutate();
    if (installMode === "remote") remoteMutation.mutate();
    if (installMode === "upload") uploadMutation.mutate();
  };

  const toggleRemoteCandidate = (item: RemoteSkillCandidate) => {
    const key = remoteCandidateKey(item);
    setSelectedRemoteKeys((prev) => {
      if (replaceTarget) return prev.includes(key) ? [] : [key];
      return prev.includes(key) ? prev.filter((value) => value !== key) : [...prev, key];
    });
    setRemoteForm((prev) => ({ ...prev, id: item.id, subdir: item.subdir }));
  };

  const pending = manualMutation.isPending || remoteMutation.isPending || uploadMutation.isPending;
  const replaceTargetId = replaceTarget ? replaceTarget.id || replaceTarget.name : "";

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <PageHeader
        eyebrow="Skills"
        title="Skills 能力库"
        description="管理可注入 Agent 的技能包，支持依赖检查、目录资源、远程仓库列表和文件安装。"
        actions={
          <>
            <Link href="/creator?type=skill" className="inline-flex h-9 items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs font-semibold text-sky-700 hover:bg-sky-100">
              <Sparkles size={14} />
              AI 创建
            </Link>
            <Button size="sm" onClick={openAddDialog}>
              <Plus size={14} />
              新增 Skill
            </Button>
            <button type="button" onClick={refresh} className={outlineButton}>
              <RefreshCw size={14} className={skillsQuery.isFetching ? "animate-spin" : ""} />
              刷新
            </button>
          </>
        }
      />

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {skills.map((skill) => {
            const id = skill.id || skill.name;
            return (
              <SkillCard
                key={id}
                skill={skill}
                result={results[id]}
                onView={() => setSelectedSkill(skill)}
                onReplace={() => openReplaceDialog(skill)}
                onTest={() => void runTest(id)}
                onDelete={() => void uninstallSkill(id).then(refresh)}
              />
            );
          })}
        </section>

        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-slate-950">内置模板</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {registry.map((item) => {
              const installed = installedIds.has(item.id);
              return (
              <Card key={item.id} className="flex h-full flex-col">
                <CardContent className="flex flex-1 flex-col p-5">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500"><Code2 size={18} /></div>
                    <div className="min-w-0 flex-1">
                      <h3 className="truncate text-sm font-semibold text-slate-950">{item.name}</h3>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{item.description}</p>
                    </div>
                  </div>
                  {item.tags.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {item.tags.slice(0, 4).map((tag) => <Tag key={tag}>{tag}</Tag>)}
                    </div>
                  ) : null}
                  <IssueBadge issues={item.issues ?? []} />
                  <button type="button" disabled={installed} onClick={() => void installSkill(item.id).then(refresh)} className="mt-auto inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                    {installed ? <><CheckCircle size={13} />已安装</> : <><Plus size={13} />安装</>}
                  </button>
                </CardContent>
              </Card>
              );
            })}
          </div>
        </section>
      </main>

      <Dialog
        open={dialogOpen}
        onClose={resetDialog}
        title={replaceTarget ? `替换 ${replaceTarget.name}` : "新增 Skill"}
        description={replaceTarget ? `将新内容写入 ${replaceTargetId}，原 Skill 会被替换。` : "可以手动创建，也可以从远程仓库列表或上传的 zip/md 文件安装。"}
        className="max-w-4xl"
        contentClassName="min-h-[620px] px-5 py-5"
      >
        <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 p-1">
          <div className="grid grid-cols-3 gap-1">
            <ModeButton active={installMode === "manual"} onClick={() => setInstallMode("manual")} icon={<Edit3 size={14} />} label="手动" />
            <ModeButton active={installMode === "remote"} onClick={() => setInstallMode("remote")} icon={<GitBranch size={14} />} label="远程仓库" />
            <ModeButton active={installMode === "upload"} onClick={() => setInstallMode("upload")} icon={<Upload size={14} />} label="上传文件" />
          </div>
        </div>

        <div key={`${replaceTargetId || "create"}-${installMode}`} className="skill-panel-enter min-h-[430px] rounded-xl border border-slate-200 bg-white p-4 shadow-xs">
          {installMode === "manual" ? (
            <ManualSkillForm
              form={skillForm}
              setForm={setSkillForm}
              lockedId={Boolean(replaceTarget)}
              toolOptions={toolOptions}
              mcpOptions={mcpOptions}
            />
          ) : null}
          {installMode === "remote" ? (
            <RemoteSkillForm
              form={remoteForm}
              setForm={setRemoteForm}
              candidates={remoteCandidates}
              selectedKeys={selectedRemoteKeys}
              isDiscovering={discoverRemoteMutation.isPending}
              replacing={Boolean(replaceTarget)}
              onDiscover={() => {
                setError("");
                discoverRemoteMutation.mutate();
              }}
            onSelect={toggleRemoteCandidate}
            onSelectAll={() => {
              if (replaceTarget) setSelectedRemoteKeys(remoteCandidates[0] ? [remoteCandidateKey(remoteCandidates[0])] : []);
              else setSelectedRemoteKeys(remoteCandidates.map(remoteCandidateKey));
            }}
            onClearSelection={() => setSelectedRemoteKeys([])}
          />
          ) : null}
          {installMode === "upload" ? <UploadSkillForm form={uploadForm} setForm={setUploadForm} replacing={Boolean(replaceTarget)} /> : null}
        </div>

        {error ? <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div> : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={resetDialog}>取消</Button>
          <Button type="button" size="sm" disabled={pending} onClick={submit}>
            {pending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {replaceTarget ? "替换" : installMode === "remote" && selectedRemoteKeys.length > 1 ? `安装 ${selectedRemoteKeys.length} 个` : "保存"}
          </Button>
        </div>
      </Dialog>

      {selectedSkill ? (
        <SkillDetailOverlay
          skill={selectedSkill}
          toolOptions={toolOptions}
          mcpOptions={mcpOptions}
          onClose={() => setSelectedSkill(null)}
          onReplace={() => openReplaceDialog(selectedSkill)}
          onSaved={(skill) => {
            setSelectedSkill(skill);
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function ManualSkillForm({
  form,
  setForm,
  lockedId,
  toolOptions,
  mcpOptions,
}: {
  form: SkillForm;
  setForm: (form: SkillForm) => void;
  lockedId?: boolean;
  toolOptions: ToolInfo[];
  mcpOptions: MCPServer[];
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Skill ID" required hint="用于安装目录和运行时引用，建议使用小写短横线。">
          <input className={inputClass} placeholder="csv-profiler" value={form.id} disabled={lockedId} onChange={(event) => setForm({ ...form, id: event.target.value })} />
        </Field>
        <Field label="名称" required>
          <input className={inputClass} placeholder="CSV Profiler" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        </Field>
      </div>
      <Field label="描述">
        <textarea className={`${inputClass} min-h-20 resize-none`} placeholder="这个 Skill 适合处理什么任务" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
      </Field>
      <Field label="SKILL.md 内容" required>
        <textarea className={`${inputClass} min-h-56 resize-none font-mono text-xs`} placeholder="写入 Skill 的使用说明、约束、工作流和示例。" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} />
      </Field>
      <AdvancedSection>
        <Field label="Tags" hint="多个标签用英文逗号分隔。">
          <input className={inputClass} placeholder="data,csv,analysis" value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} />
        </Field>
        <DependencyPicker
          label="依赖工具"
          hint="只有没有这些工具就无法运行时才选择。普通提示型 Skill 保持为空。"
          emptyLabel="不声明工具硬依赖"
          selected={csv(form.required_tools)}
          options={toolOptions.map((tool) => ({
            id: tool.name,
            label: tool.name,
            description: tool.description,
            meta: tool.category,
            disabled: tool.available === false || tool.enabled === false,
          }))}
          onChange={(items) => setForm({ ...form, required_tools: items.join(", ") })}
        />
        <DependencyPicker
          label="依赖 MCP"
          hint="只有 Skill 必须绑定某个 MCP 服务时才选择；工具名不要写在这里。"
          emptyLabel="不声明 MCP 硬依赖"
          selected={csv(form.required_mcp_ids)}
          options={mcpOptions.map((mcp) => ({
            id: mcp.id,
            label: mcp.name || mcp.id,
            description: mcp.description,
            meta: mcp.id,
            disabled: !mcp.is_enabled,
          }))}
          onChange={(items) => setForm({ ...form, required_mcp_ids: items.join(", ") })}
        />
      </AdvancedSection>
    </div>
  );
}

function RemoteSkillForm({
  form,
  setForm,
  candidates,
  selectedKeys,
  isDiscovering,
  onDiscover,
  onSelect,
  onSelectAll,
  onClearSelection,
  replacing,
}: {
  form: RemoteForm;
  setForm: (form: RemoteForm) => void;
  candidates: RemoteSkillCandidate[];
  selectedKeys: string[];
  isDiscovering: boolean;
  onDiscover: () => void;
  onSelect: (item: RemoteSkillCandidate) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  replacing?: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-sky-100 bg-sky-50/60 px-3 py-2 text-xs leading-5 text-sky-800 transition-colors duration-200">
        输入仓库后先获取 Skill 列表，可一次选择多个安装；单个 raw SKILL.md URL 仍可直接安装。
      </div>
      <Field label="远程来源" required hint="支持 GitHub owner/repo、GitHub URL、zip URL 或 raw SKILL.md URL。">
        <input className={inputClass} placeholder="owner/repo 或 https://github.com/owner/repo" value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <Field label="分支">
          <input className={inputClass} placeholder="main" value={form.branch} onChange={(event) => setForm({ ...form, branch: event.target.value })} />
        </Field>
        <div className="flex items-end">
          <button type="button" disabled={!form.source.trim() || isDiscovering} onClick={onDiscover} className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-sky-200 bg-white px-3 text-xs font-semibold text-sky-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-sky-50 hover:shadow disabled:translate-y-0 disabled:opacity-50">
            {isDiscovering ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            获取列表
          </button>
        </div>
      </div>
      <AdvancedSection>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="安装 ID" hint="只在直接安装单个 Skill 或需要覆盖默认 ID 时填写。">
            <input className={inputClass} placeholder="可选" value={form.id} disabled={replacing} onChange={(event) => setForm({ ...form, id: event.target.value })} />
          </Field>
          <Field label="Skill 子目录" hint="获取列表后通常不需要手动填写。">
            <input className={inputClass} placeholder="skills/public/deep-research" value={form.subdir} onChange={(event) => setForm({ ...form, subdir: event.target.value })} />
          </Field>
        </div>
      </AdvancedSection>
      {candidates.length ? (
        <div className="skill-panel-enter rounded-xl border border-slate-200 bg-slate-50 p-2 shadow-inner transition-all duration-200">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-semibold text-slate-600">
              已发现 {candidates.length} 个 Skill，已选择 {selectedKeys.length} 个
            </span>
            <div className="flex gap-1">
              {!replacing ? <button type="button" onClick={onSelectAll} className="h-7 rounded-md px-2 text-[11px] font-semibold text-sky-700 hover:bg-sky-50">全选</button> : null}
              <button type="button" onClick={onClearSelection} className="h-7 rounded-md px-2 text-[11px] font-semibold text-slate-500 hover:bg-white">清空</button>
            </div>
          </div>
          <div className="max-h-72 space-y-2 overflow-auto">
          {candidates.map((item) => {
            const selected = selectedKeys.includes(remoteCandidateKey(item));
            return (
              <button
                key={`${item.subdir}-${item.id}`}
                type="button"
                onClick={() => onSelect(item)}
                className={`w-full rounded-lg border px-3 py-2 text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm ${selected ? "border-sky-300 bg-sky-50 shadow-sm" : "border-slate-200 bg-white hover:bg-slate-50"}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="inline-flex min-w-0 items-center gap-2 truncate text-xs font-semibold text-slate-900">
                    <span className={`h-3.5 w-3.5 rounded border ${selected ? "border-sky-500 bg-sky-500" : "border-slate-300 bg-white"}`} />
                    {item.name}
                  </span>
                  <span className="shrink-0 text-[10px] text-slate-500">{item.file_count} files</span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{item.description || item.subdir || item.id}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  <Tag>{item.id}</Tag>
                  {item.subdir ? <Tag>{item.subdir}</Tag> : null}
                </div>
              </button>
            );
          })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function UploadSkillForm({ form, setForm, replacing }: { form: UploadForm; setForm: (form: UploadForm) => void; replacing?: boolean }) {
  return (
    <div className="space-y-4">
      <Field label="Skill 文件" required hint="支持 .zip、.skill、.md 或 .markdown。">
        <label className="group flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-7 text-center text-sm text-slate-600 transition-all duration-200 hover:-translate-y-0.5 hover:border-sky-300 hover:bg-sky-50/60 hover:text-sky-700">
          <FileArchive size={24} className="transition-transform duration-200 group-hover:scale-105" />
          <span className="font-medium">{form.file ? form.file.name : "选择 .zip、.skill、.md 或 .markdown 文件"}</span>
          <span className="text-xs text-slate-400">点击选择本地文件</span>
          <input
            className="hidden"
            type="file"
            accept=".zip,.skill,.md,.markdown,text/markdown,application/zip"
            onChange={(event) => setForm({ ...form, file: event.target.files?.[0] ?? null })}
          />
        </label>
      </Field>
      <AdvancedSection>
        <Field label="安装 ID" hint="上传单个 md 时建议填写；zip 会优先使用包内元数据。">
          <input className={inputClass} placeholder="可选" value={form.id} disabled={replacing} onChange={(event) => setForm({ ...form, id: event.target.value })} />
        </Field>
      </AdvancedSection>
    </div>
  );
}

function SkillCard({
  skill,
  result,
  onView,
  onReplace,
  onTest,
  onDelete,
}: {
  skill: SkillInfo;
  result?: SkillTestState | { ok: false; message: string };
  onView: () => void;
  onReplace: () => void;
  onTest: () => void;
  onDelete: () => void;
}) {
  const issues = dedupeIssues([...(skill.issues ?? []), ...(result && "issues" in result ? result.issues ?? [] : [])]);
  const bundledFiles = skill.files?.filter((file) => file.kind !== "entry") ?? [];

  return (
    <Card className="flex h-full flex-col">
      <CardContent className="flex flex-1 flex-col p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-700"><Wrench size={18} /></div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-sm font-semibold text-slate-950">{skill.name}</h2>
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{skill.description || "未填写描述"}</p>
          </div>
        </div>

        {(skill.tags ?? []).length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(skill.tags ?? []).slice(0, 4).map((tag) => <Tag key={tag}>{tag}</Tag>)}
          </div>
        ) : null}

        {(skill.required_mcp_ids?.length || skill.required_tools?.length || bundledFiles.length) ? (
          <div className="mt-3 space-y-1.5 border-t border-slate-100 pt-3">
            <DependencyLine label="MCP" items={skill.required_mcp_ids ?? []} max={4} />
            <DependencyLine label="Tools" items={skill.required_tools ?? []} max={4} />
            {bundledFiles.length ? (
              <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                <span className="shrink-0">Files</span>
                <Tag>{bundledFiles.length} 个捆绑文件</Tag>
              </div>
            ) : null}
          </div>
        ) : null}

        <IssueBadge issues={issues} />
        {result ? <SkillTestResult result={result} /> : null}

        <div className="mt-auto flex items-center gap-1.5 border-t border-slate-100 pt-4">
          <button type="button" onClick={onView} className={`${outlineButton} flex-1 justify-center px-1`}><Code2 size={13} />详情</button>
          <button type="button" onClick={onReplace} className={`${outlineButton} flex-1 justify-center px-1`}><RefreshCw size={13} />替换</button>
          <button type="button" onClick={onTest} className={`${outlineButton} flex-1 justify-center px-1`}><CheckCircle size={13} />测试</button>
          <button type="button" onClick={onDelete} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-rose-200 text-rose-600 transition hover:bg-rose-50" title="删除 Skill"><Trash2 size={13} /></button>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillDetailOverlay({
  skill,
  toolOptions,
  mcpOptions,
  onClose,
  onReplace,
  onSaved,
}: {
  skill: SkillInfo;
  toolOptions: ToolInfo[];
  mcpOptions: MCPServer[];
  onClose: () => void;
  onReplace: () => void;
  onSaved: (skill: SkillInfo) => void;
}) {
  const queryClient = useQueryClient();
  const files = useMemo<SkillFile[]>(
    () =>
      skill.files?.length
        ? skill.files
        : [{ path: "SKILL.md", size: skill.content?.length ?? 0, kind: "entry", text: true }],
    [skill.content?.length, skill.files],
  );
  const [activePath, setActivePath] = useState(files[0]?.path ?? "SKILL.md");
  const [detailMode, setDetailMode] = useState<"files" | "edit" | "history">("files");
  const [viewMode, setViewMode] = useState<"rendered" | "source">("rendered");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(() => new Set(buildDefaultExpandedFolders(files)));
  const [editForm, setEditForm] = useState<SkillForm>({
    id: skill.id || skill.name,
    name: skill.name,
    description: skill.description || "",
    tags: (skill.tags ?? []).join(", "),
    required_mcp_ids: (skill.required_mcp_ids ?? []).join(", "),
    required_tools: (skill.required_tools ?? []).join(", "),
    content: skill.content ?? skill.content_preview ?? "",
    force: false,
  });
  const [editError, setEditError] = useState("");
  const fileTree = useMemo(() => buildFileTree(files), [files]);
  const skillId = skill.id || skill.name;
  const updateMutation = useMutation({
    mutationFn: () =>
      updateSkill(skillId, {
        name: editForm.name.trim(),
        description: editForm.description.trim(),
        version: "0.1.0",
        tags: csv(editForm.tags),
        required_mcp_ids: csv(editForm.required_mcp_ids),
        required_tools: csv(editForm.required_tools),
        content: editForm.content,
      }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      void queryClient.invalidateQueries({ queryKey: ["skill-registry"] });
      setEditError("");
      setDetailMode("files");
      onSaved(updated);
    },
    onError: (err) => setEditError(err instanceof Error ? err.message : String(err)),
  });
  const fileQuery = useQuery<SkillFileContent>({
    queryKey: ["skill-file", skillId, activePath],
    queryFn: () => fetchSkillFileContent(skillId, activePath),
    enabled: !!activePath,
    placeholderData: (previousData) => previousData,
  });
  const historyQuery = useQuery<SkillHistoryRecord[]>({
    queryKey: ["skill-history", skillId],
    queryFn: () => fetchSkillHistory(skillId),
    enabled: detailMode === "history",
  });
  const fileContent = fileQuery.data;
  const isMarkdown = fileContent?.markdown || activePath.endsWith(".md") || activePath.endsWith(".markdown");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-950">{skill.name}</h2>
            <p className="mt-1 text-xs text-slate-500">{skill.description || skill.id}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
              <button type="button" onClick={() => setDetailMode("files")} className={detailMode === "files" ? activeSegment : inactiveSegment}>文件</button>
              <button type="button" onClick={() => setDetailMode("history")} className={detailMode === "history" ? activeSegment : inactiveSegment}>历史</button>
              <button type="button" onClick={() => setDetailMode("edit")} className={detailMode === "edit" ? activeSegment : inactiveSegment}>编辑</button>
            </div>
            <Button size="sm" variant="outline" onClick={onReplace}><RefreshCw size={14} />替换</Button>
            <Button size="sm" variant="outline" onClick={onClose}>关闭</Button>
          </div>
        </div>
        <div className="grid min-h-0 flex-1 gap-0 overflow-hidden lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="space-y-4 overflow-y-auto border-r border-slate-100 bg-slate-50 p-4 text-xs">
            <div>
              <p className="font-semibold text-slate-700">元数据</p>
              <div className="mt-2 space-y-1 text-slate-500">
                <p>ID: {skill.id || skill.name}</p>
                {skill.content_hash ? <p>Hash: {skill.content_hash.slice(0, 16)}</p> : null}
              </div>
            </div>
            <DependencyLine label="Tags" items={skill.tags ?? []} />
            <DependencyLine label="MCP" items={skill.required_mcp_ids ?? []} />
            <DependencyLine label="Tools" items={skill.required_tools ?? []} />
            {skill.issues?.length ? (
              <div>
                <p className="font-semibold text-slate-700">依赖问题</p>
                <IssueList issues={skill.issues} />
              </div>
            ) : null}
            <div>
              <p className="font-semibold text-slate-700">文件</p>
              <div className="mt-2 rounded-xl border border-slate-200 bg-white p-1.5">
                <FileTreeView
                  nodes={Array.from(fileTree.children.values())}
                  activePath={activePath}
                  expandedFolders={expandedFolders}
                  onToggleFolder={(path) => {
                    setExpandedFolders((prev) => {
                      const next = new Set(prev);
                      if (next.has(path)) next.delete(path);
                      else next.add(path);
                      return next;
                    });
                  }}
                  onSelectFile={(file) => {
                    setActivePath(file.path);
                    setViewMode(file.path.endsWith(".md") || file.path.endsWith(".markdown") ? "rendered" : "source");
                  }}
                />
              </div>
            </div>
          </aside>
          {detailMode === "edit" ? (
            <section key="edit" className="skill-panel-enter min-h-0 overflow-y-auto p-5">
              <ManualSkillForm
                form={editForm}
                setForm={setEditForm}
                lockedId
                toolOptions={toolOptions}
                mcpOptions={mcpOptions}
              />
              {editError ? <div className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{editError}</div> : null}
              <div className="mt-5 flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => setDetailMode("files")}>取消</Button>
                <Button type="button" size="sm" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
                  {updateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Edit3 size={14} />}
                  保存修改
                </Button>
              </div>
            </section>
          ) : detailMode === "history" ? (
            <section key="history" className="skill-panel-enter min-h-0 overflow-y-auto p-5">
              <SkillHistoryPanel
                records={historyQuery.data ?? []}
                loading={historyQuery.isLoading || historyQuery.isFetching}
                error={historyQuery.error}
              />
            </section>
          ) : (
          <section key="files" className="skill-panel-enter flex min-h-0 flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <p className="truncate font-mono text-xs font-semibold text-slate-600">{activePath}</p>
                {fileQuery.isFetching ? <Loader2 size={13} className="shrink-0 animate-spin text-sky-600" /> : null}
              </div>
              {isMarkdown && fileContent?.text ? (
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
                  <button type="button" onClick={() => setViewMode("rendered")} className={viewMode === "rendered" ? activeSegment : inactiveSegment}>预览</button>
                  <button type="button" onClick={() => setViewMode("source")} className={viewMode === "source" ? activeSegment : inactiveSegment}>源码</button>
                </div>
              ) : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              <div key={`${activePath}-${viewMode}`} className="skill-panel-enter">
                {fileQuery.isLoading && !fileContent ? (
                  <div className="flex items-center gap-2 text-xs text-slate-500"><Loader2 size={14} className="animate-spin" />加载文件内容</div>
                ) : fileQuery.error && !fileContent ? (
                  <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{fileQuery.error instanceof Error ? fileQuery.error.message : String(fileQuery.error)}</div>
                ) : fileContent && !fileContent.text ? (
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">该文件不是文本文件，暂不支持预览。</div>
                ) : fileContent?.content ? (
                  viewMode === "rendered" && isMarkdown ? (
                    <div className="prose prose-sm max-w-none rounded-lg border border-slate-100 bg-white p-4 text-slate-700">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{fileContent.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <pre className="whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-100">{fileContent.content}</pre>
                  )
                ) : (
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">暂无可显示内容。</div>
                )}
                {fileContent?.truncated ? <p className="mt-2 text-xs text-amber-600">文件较大，已截断显示。</p> : null}
                  </div>
            </div>
          </section>
          )}
        </div>
      </div>
    </div>
  );
}

function SkillHistoryPanel({
  records,
  loading,
  error,
}: {
  records: SkillHistoryRecord[];
  loading: boolean;
  error: unknown;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500">
        <Loader2 size={14} className="animate-spin" />
        正在加载 Skill 修改历史
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-xl border border-rose-100 bg-rose-50 px-4 py-3 text-xs text-rose-700">
        {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }
  if (!records.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-xs text-slate-500">
        暂无修改历史。通过 AI 创建、编辑、替换或资源文件更新后会在这里记录。
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {records
        .slice()
        .reverse()
        .map((record, index) => (
          <div key={`${record.ts}-${index}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <Tag>{record.action}</Tag>
                {record.source ? <Tag>{record.source}</Tag> : null}
                {record.file_path ? <span className="truncate font-mono text-xs font-semibold text-slate-700">{record.file_path}</span> : null}
              </div>
              <span className="shrink-0 text-[11px] text-slate-400">{formatHistoryTime(record.ts)}</span>
            </div>
            {record.message ? <p className="mt-2 text-xs text-slate-600">{record.message}</p> : null}
            <div className="mt-3 grid gap-2 text-[11px] text-slate-500 sm:grid-cols-2">
              {record.replacements ? <HistoryMeta label="替换次数" value={String(record.replacements)} /> : null}
              {record.matches ? <HistoryMeta label="匹配数量" value={String(record.matches)} /> : null}
              {record.prev_hash ? <HistoryMeta label="修改前" value={record.prev_hash.slice(0, 12)} mono /> : null}
              {record.new_hash ? <HistoryMeta label="修改后" value={record.new_hash.slice(0, 12)} mono /> : null}
              {record.scanner?.decision ? <HistoryMeta label="扫描结果" value={record.scanner.decision} /> : null}
            </div>
            {record.scanner?.reason ? <p className="mt-2 text-[11px] text-amber-600">{record.scanner.reason}</p> : null}
          </div>
        ))}
    </div>
  );
}

function HistoryMeta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <span className="text-slate-400">{label}</span>
      <span className={`ml-2 font-semibold text-slate-700 ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function formatHistoryTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function FileTreeView({
  nodes,
  activePath,
  expandedFolders,
  onToggleFolder,
  onSelectFile,
  depth = 0,
}: {
  nodes: FileTreeNode[];
  activePath: string;
  expandedFolders: Set<string>;
  onToggleFolder: (path: string) => void;
  onSelectFile: (file: SkillFile) => void;
  depth?: number;
}) {
  return (
    <div className="space-y-0.5">
      {nodes
        .sort((left, right) => Number(Boolean(right.file)) - Number(Boolean(left.file)) || left.name.localeCompare(right.name))
        .map((node) => {
          const isFolder = !node.file;
          const expanded = expandedFolders.has(node.path);
          if (isFolder) {
            return (
              <div key={node.path}>
                <button
                  type="button"
                  onClick={() => onToggleFolder(node.path)}
                  className="flex h-8 w-full items-center gap-1.5 rounded-lg px-2 text-left text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100"
                  style={{ paddingLeft: 8 + depth * 14 }}
                >
                  {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <Folder size={14} className="text-slate-500" />
                  <span className="truncate">{node.name}</span>
                </button>
                {expanded ? (
                  <FileTreeView
                    nodes={Array.from(node.children.values())}
                    activePath={activePath}
                    expandedFolders={expandedFolders}
                    onToggleFolder={onToggleFolder}
                    onSelectFile={onSelectFile}
                    depth={depth + 1}
                  />
                ) : null}
              </div>
            );
          }
          const file = node.file;
          if (!file) return null;
          const selected = activePath === file.path;
          return (
            <button
              key={file.path}
              type="button"
              onClick={() => onSelectFile(file)}
              className={`flex h-8 w-full items-center gap-1.5 rounded-lg px-2 text-left text-xs transition-colors ${selected ? "bg-sky-50 font-semibold text-sky-700" : "text-slate-600 hover:bg-slate-100"}`}
              style={{ paddingLeft: 8 + depth * 14 }}
            >
              <FileText size={14} className={selected ? "text-sky-600" : "text-slate-400"} />
              <span className="truncate">{node.name}</span>
            </button>
          );
        })}
    </div>
  );
}

function SkillTestResult({ result }: { result: SkillTestState | { ok: false; message: string } }) {
  return (
    <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${result.ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
      <div className="flex items-center gap-2">
        {result.ok ? <CheckCircle size={13} /> : <AlertCircle size={13} />}
        <span>{result.message}</span>
      </div>
    </div>
  );
}

const ISSUE_LABELS: Record<string, string> = {
  missing_tool_dependency: "缺少依赖工具",
  missing_mcp_dependency: "缺少依赖 MCP",
};

function IssueBadge({ issues }: { issues: SkillIssue[] }) {
  if (!issues.length) return null;
  const hasError = issues.some((issue) => issue.severity === "error");
  const tone = hasError ? "bg-rose-50 text-rose-600" : "bg-amber-50 text-amber-700";
  const label = issues.length > 1 ? `${issues.length} 个依赖问题` : ISSUE_LABELS[issues[0].code] ?? issues[0].code;
  return (
    <div
      className={`mt-3 inline-flex max-w-full items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold ${tone}`}
      title={issues.map((issue) => `${issue.code}: ${issue.message}${issue.fix ? `（${issue.fix}）` : ""}`).join("\n")}
    >
      <AlertCircle size={12} className="shrink-0" />
      <span className="truncate">{label}</span>
    </div>
  );
}

function IssueList({ issues }: { issues: SkillIssue[] }) {
  if (!issues.length) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {issues.map((issue, index) => (
        <div key={`${issue.code}-${index}`} className={`rounded-lg px-3 py-2 text-xs ${issue.severity === "error" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}>
          <p className="font-semibold">{issue.code}</p>
          <p className="mt-0.5">{issue.message}</p>
          {issue.fix ? <p className="mt-0.5 text-slate-500">{issue.fix}</p> : null}
        </div>
      ))}
    </div>
  );
}

function dedupeIssues(issues: SkillIssue[]) {
  const seen = new Set<string>();
  return issues.filter((issue) => {
    const key = `${issue.severity}:${issue.code}:${issue.message}:${issue.fix ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function DependencyLine({ label, items, max }: { label: string; items: string[]; max?: number }) {
  if (!items.length) return null;
  const limit = max ?? items.length;
  const shown = items.slice(0, limit);
  const overflow = items.length - shown.length;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
      <span className="shrink-0">{label}</span>
      {shown.map((item) => <Tag key={item}>{item}</Tag>)}
      {overflow > 0 ? <Tag>+{overflow}</Tag> : null}
    </div>
  );
}

type DependencyOption = {
  id: string;
  label: string;
  description?: string;
  meta?: string;
  disabled?: boolean;
};

function DependencyPicker({
  label,
  hint,
  emptyLabel,
  selected,
  options,
  onChange,
}: {
  label: string;
  hint: string;
  emptyLabel: string;
  selected: string[];
  options: DependencyOption[];
  onChange: (items: string[]) => void;
}) {
  const known = new Set(options.map((option) => option.id));
  const missing = selected
    .filter((item) => item && !known.has(item))
    .map((item) => ({
      id: item,
      label: item,
      description: "这个依赖没有出现在当前已注册列表里。",
      meta: "当前不可用",
      disabled: true,
    }));
  const merged = [...options, ...missing];
  const selectedSet = new Set(selected);

  const toggle = (id: string) => {
    const next = selectedSet.has(id)
      ? selected.filter((item) => item !== id)
      : [...selected, id];
    onChange(next);
  };

  return (
    <Field label={label} hint={hint}>
      <div className="rounded-xl border border-slate-200 bg-white p-2">
        {merged.length ? (
          <div className="grid max-h-52 gap-2 overflow-y-auto sm:grid-cols-2">
            {merged.map((option) => {
              const checked = selectedSet.has(option.id);
              const unavailable = option.disabled && !checked;
              return (
                <button
                  key={option.id}
                  type="button"
                  disabled={unavailable}
                  onClick={() => toggle(option.id)}
                  className={cn(
                    "min-w-0 rounded-lg border px-3 py-2 text-left transition-all duration-200",
                    checked
                      ? "border-sky-300 bg-sky-50 text-sky-900 shadow-sm"
                      : "border-slate-200 bg-white text-slate-700 hover:-translate-y-0.5 hover:bg-slate-50 hover:shadow-sm",
                    unavailable && "cursor-not-allowed opacity-45 hover:translate-y-0 hover:bg-white hover:shadow-none",
                  )}
                >
                  <span className="flex min-w-0 items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold">{option.label}</span>
                    <span
                      className={cn(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                        checked ? "border-sky-500 bg-sky-500 text-white" : "border-slate-300 bg-white",
                      )}
                    >
                      {checked ? <CheckCircle size={11} /> : null}
                    </span>
                  </span>
                  {option.description ? <span className="mt-1 block truncate text-[11px] text-slate-500">{option.description}</span> : null}
                  {option.meta ? <span className="mt-1 inline-flex rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">{option.meta}</span> : null}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-4 text-center text-xs text-slate-500">
            暂无可选项。
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
          {selected.length ? selected.map((item) => <Tag key={item}>{item}</Tag>) : <span className="text-[11px] text-slate-400">{emptyLabel}</span>}
        </div>
      </div>
    </Field>
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

function AdvancedSection({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70 transition-all duration-200">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-xs font-semibold text-slate-700 transition-colors duration-200 hover:bg-white/70"
      >
        <span>高级配置</span>
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400">
          依赖和安装选项
          <ChevronDown size={14} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </span>
      </button>
      <div className={`grid transition-all duration-200 ease-out ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
        <div className="overflow-hidden">
          <div className="space-y-3 border-t border-slate-200 px-3 py-3">{children}</div>
        </div>
      </div>
    </div>
  );
}

function ModeButton({ active, icon, label, onClick }: { active: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-10 items-center justify-center gap-1.5 rounded-lg px-2 text-xs font-semibold transition-all duration-200 hover:-translate-y-0.5 ${active ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-200" : "text-slate-500 hover:bg-white/70 hover:text-slate-800"}`}
    >
      {icon}
      {label}
    </button>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">{children}</span>;
}

function remoteCandidateKey(item: RemoteSkillCandidate) {
  return `${item.subdir}::${item.id}`;
}

function buildFileTree(files: SkillFile[]): FileTreeNode {
  const root: FileTreeNode = { name: "", path: "", children: new Map() };
  for (const file of files) {
    const parts = file.path.split("/").filter(Boolean);
    let current = root;
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join("/");
      const isFile = index === parts.length - 1;
      let node = current.children.get(part);
      if (!node) {
        node = { name: part, path, children: new Map() };
        current.children.set(part, node);
      }
      if (isFile) node.file = file;
      current = node;
    });
  }
  return root;
}

function buildDefaultExpandedFolders(files: SkillFile[]) {
  const folders = new Set<string>();
  for (const file of files) {
    const parts = file.path.split("/").filter(Boolean);
    for (let index = 1; index < parts.length; index += 1) {
      folders.add(parts.slice(0, index).join("/"));
    }
  }
  return Array.from(folders);
}

function findAddConflict(
  mode: InstallMode,
  skillForm: SkillForm,
  remoteForm: RemoteForm,
  uploadForm: UploadForm,
  remoteCandidates: RemoteSkillCandidate[],
  selectedRemoteKeys: string[],
  skills: SkillInfo[],
) {
  const findSkill = (id?: string, name?: string) => {
    const normalizedId = id?.trim().toLowerCase();
    const normalizedName = name?.trim().toLowerCase();
    if (!normalizedId && !normalizedName) return undefined;
    return skills.find((skill) => {
      const skillId = (skill.id || skill.name).toLowerCase();
      const skillName = skill.name.toLowerCase();
      return Boolean((normalizedId && skillId === normalizedId) || (normalizedName && skillName === normalizedName));
    });
  };

  if (mode === "manual") return findSkill(skillForm.id, skillForm.name);
  if (mode === "upload") return findSkill(uploadForm.id);
  const selected = remoteCandidates.filter((item) => selectedRemoteKeys.includes(remoteCandidateKey(item)));
  const candidates = selected.length ? selected : remoteForm.id ? [{ id: remoteForm.id, name: remoteForm.id }] : [];
  for (const item of candidates) {
    const conflict = findSkill(item.id, item.name);
    if (conflict) return conflict;
  }
  return undefined;
}

function csv(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

const inputClass = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100 disabled:bg-slate-100";
const outlineButton = "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const activeSegment = "h-7 rounded-md bg-slate-950 px-2.5 text-[11px] font-semibold text-white shadow-sm transition-all duration-200";
const inactiveSegment = "h-7 rounded-md px-2.5 text-[11px] font-semibold text-slate-500 transition-all duration-200 hover:bg-slate-50 hover:text-slate-800";
