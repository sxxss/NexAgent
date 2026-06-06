"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronDown, FlaskConical, GitBranch, RotateCcw, Search, Send, Square, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessageBubble, type Message } from "@/components/chat/MessageBubble";
import { ResearchProgress, type ResearchStepState } from "@/components/research/ResearchProgress";
import { Card, CardContent } from "@/components/ui/card";
import { fetchModels, streamChat, type Model } from "@/lib/api";
import { cn } from "@/lib/utils";

let idSeed = 0;
const uid = () => `research-${++idSeed}`;

const EXAMPLES = [
  "调研本地 Agent 系统在企业知识管理中的落地路径，并给出架构建议。",
  "比较 RAG、知识图谱和微调在企业私有知识问答中的优缺点。",
  "分析多阶段研究流程如何和本地知识库结合，形成可复用产品能力。",
  "为这个项目设计一个从 Demo 到可开源产品的三个月路线图。",
];

const FLOW = [
  { label: "Planner", desc: "生成研究计划", icon: GitBranch },
  { label: "Researcher", desc: "检索网页与知识库", icon: Search },
  { label: "Synthesizer", desc: "合并证据与结论", icon: BookOpen },
  { label: "Writer", desc: "输出结构化报告", icon: FlaskConical },
] as const;

function modelLabel(model: Model) {
  const label = model.display_name || model.model || model.name;
  return model.provider_name ? `${label} · ${model.provider_name}` : label;
}

export default function ResearchPage() {
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: fetchModels });
  const models = useMemo(() => modelsQuery.data ?? [], [modelsQuery.data]);
  const [selectedModel, setSelectedModel] = useState("");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [threadId, setThreadId] = useState<string>();
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [planSteps, setPlanSteps] = useState<ResearchStepState[]>([]);
  const [isWriting, setIsWriting] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, planSteps, isWriting]);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) setShowModelPicker(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectedModelExists = !selectedModel || models.some((model) => model.name === selectedModel);
  const selectedModelName = selectedModelExists ? selectedModel : "";
  const selectedModelObj = models.find((item) => item.name === selectedModelName);
  const hasContent = messages.length > 0;

  const reset = () => {
    setMessages([]);
    setThreadId(undefined);
    setQuery("");
    setPlanSteps([]);
    setIsWriting(false);
    setIsDone(false);
    setRunning(false);
  };

  const startResearch = useCallback(
    async (incoming?: string) => {
      const text = (incoming ?? query).trim();
      if (!text || running) return;
      setQuery("");
      setRunning(true);
      setPlanSteps([]);
      setIsWriting(false);
      setIsDone(false);

      const assistantId = uid();
      setMessages((prev) => [...prev, { id: uid(), role: "user", content: text }, { id: assistantId, role: "assistant", content: "", isStreaming: true }]);

      try {
        for await (const chunk of streamChat({ message: text, thread_id: threadId, model: selectedModelName || undefined, agent: "deep_research", reasoning_mode: "deep" })) {
          if (chunk.status === "plan" && chunk.steps) {
            setPlanSteps(chunk.steps.map((step, index) => ({ step, status: index === 0 ? "active" : "pending" })));
          } else if (chunk.status === "research_step" && chunk.step != null) {
            const stepIndex = chunk.step - 1;
            setPlanSteps((prev) => prev.map((item, index) => ({ ...item, status: index < stepIndex ? "done" : index === stepIndex ? "active" : "pending" })));
          } else if (chunk.status === "writing") {
            setPlanSteps((prev) => prev.map((item) => ({ ...item, status: "done" })));
            setIsWriting(true);
          } else if (chunk.status === "loading" && chunk.content) {
            setMessages((prev) => prev.map((item) => (item.id === assistantId ? { ...item, content: item.content + chunk.content } : item)));
          } else if (chunk.status === "tool_call") {
            setMessages((prev) => [...prev, { id: uid(), role: "tool", content: JSON.stringify(chunk.input ?? ""), toolName: chunk.tool }]);
          } else if (chunk.status === "finished") {
            setThreadId(chunk.thread_id);
            setMessages((prev) => prev.map((item) => (item.id === assistantId ? { ...item, isStreaming: false } : item)));
            setPlanSteps((prev) => prev.map((item) => ({ ...item, status: "done" })));
            setIsWriting(false);
            setIsDone(true);
          } else if (chunk.status === "error") {
            setMessages((prev) => prev.map((item) => (item.id === assistantId ? { ...item, content: `研究失败：${chunk.error ?? "未知错误"}`, isStreaming: false } : item)));
          }
        }
      } catch (error) {
        setMessages((prev) => prev.map((item) => (item.id === assistantId ? { ...item, content: `连接失败：${error instanceof Error ? error.message : "请检查后端服务"}`, isStreaming: false } : item)));
      } finally {
        setRunning(false);
      }
    },
    [query, running, selectedModelName, threadId],
  );

  return (
    <div className="flex h-full min-w-0 flex-col bg-slate-100">
      <header className="border-b border-slate-200 bg-white px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-700"><FlaskConical size={19} /></div>
          <div className="min-w-0"><h1 className="text-sm font-semibold text-slate-950">深度研究</h1><p className="mt-0.5 truncate text-xs text-slate-500">Planner / Researcher / Synthesizer / Writer</p></div>
          <div className="ml-auto flex items-center gap-2">
            <div className="relative" ref={pickerRef}>
              <button type="button" onClick={() => setShowModelPicker((value) => !value)} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <Zap size={14} className="text-amber-600" /><span>{selectedModelObj ? modelLabel(selectedModelObj) : "系统默认模型"}</span><ChevronDown size={13} className="text-slate-400" />
              </button>
              {showModelPicker ? <div className="absolute right-0 top-full z-40 mt-2 min-w-72 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
                <button type="button" onClick={() => { setSelectedModel(""); setShowModelPicker(false); }} className={cn("block w-full px-3 py-2 text-left text-sm hover:bg-slate-50", !selectedModelName && "bg-amber-50 text-amber-800")}>系统默认模型</button>
                {models.map((model) => <button key={model.name} type="button" onClick={() => { setSelectedModel(model.name); setShowModelPicker(false); }} className={cn("block w-full px-3 py-2 text-left text-sm hover:bg-slate-50", selectedModelName === model.name && "bg-amber-50 text-amber-800")}>{modelLabel(model)}</button>)}
              </div> : null}
            </div>
            {hasContent ? <button type="button" onClick={reset} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"><RotateCcw size={13} />重置</button> : null}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!hasContent ? (
          <div className="mx-auto flex max-w-6xl flex-col gap-5 px-6 py-8">
            <Card><CardContent className="p-6"><p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">Research Console</p><h2 className="mt-3 max-w-3xl text-3xl font-semibold tracking-tight text-slate-950">让 Agent 先规划，再检索，最后写出可交付报告。</h2><p className="mt-4 max-w-3xl text-sm leading-6 text-slate-600">适合调研、方案设计、技术选型和复杂问题分析。研究过程中会展示计划步骤、工具调用和最终报告。</p></CardContent></Card>
            <section className="grid gap-4 md:grid-cols-4">{FLOW.map(({ label, desc, icon: Icon }, index) => <Card key={label}><CardContent className="p-5"><div className="flex items-center justify-between"><Icon size={18} className="text-indigo-700" /><span className="font-mono text-xs text-slate-400">0{index + 1}</span></div><p className="mt-4 text-sm font-semibold text-slate-950">{label}</p><p className="mt-1 text-xs text-slate-500">{desc}</p></CardContent></Card>)}</section>
            <section className="grid gap-3 md:grid-cols-2">{EXAMPLES.map((item) => <button key={item} type="button" onClick={() => void startResearch(item)} className="rounded-xl border border-slate-200 bg-white p-4 text-left text-sm leading-6 text-slate-700 shadow-sm hover:border-indigo-300 hover:shadow-md">{item}</button>)}</section>
          </div>
        ) : (
          <div className="mx-auto grid max-w-6xl gap-4 px-6 py-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            <Card className="min-w-0 py-3">{messages.map((message) => <MessageBubble key={message.id} message={message} />)}<div ref={bottomRef} className="h-4" /></Card>
            <aside><ResearchProgress steps={planSteps} isWriting={isWriting} isDone={isDone} /></aside>
          </div>
        )}
      </div>

      <footer className="border-t border-slate-200 bg-white p-4">
        <div className="mx-auto flex max-w-4xl items-end gap-2">
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void startResearch(); } }} placeholder="输入研究主题..." className="min-h-12 flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100" />
          <button type="button" disabled={!query.trim() || running} onClick={() => void startResearch()} className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-slate-950 text-white hover:bg-slate-800 disabled:opacity-50">{running ? <Square size={15} /> : <Send size={15} />}</button>
        </div>
      </footer>
    </div>
  );
}
