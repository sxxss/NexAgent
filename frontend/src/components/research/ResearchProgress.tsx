"use client";
import { cn } from "@/lib/utils";
import { CheckCircle, Loader2, Circle, Globe, Pen } from "lucide-react";
import type { PlanStep } from "@/lib/api";

export type StepStatus = "pending" | "active" | "done";

export interface ResearchStepState {
  step: PlanStep;
  status: StepStatus;
}

interface ResearchProgressProps {
  steps: ResearchStepState[];
  isWriting: boolean;
  isDone: boolean;
}

export function ResearchProgress({ steps, isWriting, isDone }: ResearchProgressProps) {
  if (steps.length === 0) return null;

  return (
    <div className="rounded-2xl border border-violet-100 bg-violet-50/50 p-4 dark:border-violet-900/30 dark:bg-violet-900/10">
      {/* Header */}
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-500">
          <Globe size={12} className="text-white" />
        </div>
        <span className="text-xs font-semibold text-violet-700 dark:text-violet-300">
          深度研究进度
        </span>
        <span className="ml-auto text-[10px] text-violet-400">
          {steps.filter((s) => s.status === "done").length} / {steps.length} 步完成
        </span>
      </div>

      {/* Steps */}
      <div className="space-y-1.5">
        {steps.map((s) => (
          <StepRow key={s.step.id} stepState={s} />
        ))}

        {/* Writing step */}
        <div className={cn(
          "flex items-center gap-2.5 rounded-lg px-3 py-2 transition-all",
          isDone
            ? "bg-green-50 dark:bg-green-900/20"
            : isWriting
              ? "bg-white shadow-sm dark:bg-zinc-800"
              : "opacity-40"
        )}>
          <StatusIcon status={isDone ? "done" : isWriting ? "active" : "pending"} />
          <Pen size={12} className={cn(
            "shrink-0",
            isDone ? "text-green-500" : isWriting ? "text-violet-500" : "text-zinc-300"
          )} />
          <span className={cn(
            "text-xs font-medium",
            isDone ? "text-green-700 dark:text-green-400"
              : isWriting ? "text-zinc-800 dark:text-zinc-200"
              : "text-zinc-400"
          )}>
            {isDone ? "报告已生成" : isWriting ? "正在撰写报告…" : "撰写最终报告"}
          </span>
          {isWriting && !isDone && (
            <Loader2 size={11} className="ml-auto animate-spin text-violet-400" />
          )}
        </div>
      </div>
    </div>
  );
}

function StepRow({ stepState }: { stepState: ResearchStepState }) {
  const { step, status } = stepState;
  const isActive = status === "active";
  const isDone = status === "done";

  return (
    <div className={cn(
      "flex items-start gap-2.5 rounded-lg px-3 py-2 transition-all",
      isDone
        ? "bg-green-50/60 dark:bg-green-900/10"
        : isActive
          ? "bg-white shadow-sm dark:bg-zinc-800"
          : "opacity-50"
    )}>
      <StatusIcon status={status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className={cn(
            "text-xs font-medium",
            isDone ? "text-green-700 dark:text-green-400"
              : isActive ? "text-zinc-800 dark:text-zinc-200"
              : "text-zinc-400"
          )}>
            {step.title}
          </span>
          {isActive && (
            <Loader2 size={10} className="animate-spin text-violet-400" />
          )}
        </div>
        {(isActive || isDone) && step.description && (
          <p className="mt-0.5 text-[10px] text-zinc-400 line-clamp-1">{step.description}</p>
        )}
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: StepStatus }) {
  if (status === "done") {
    return <CheckCircle size={14} className="mt-0.5 shrink-0 text-green-500" />;
  }
  if (status === "active") {
    return (
      <div className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border-2 border-violet-400 bg-violet-100 dark:bg-violet-900/40">
        <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500" />
      </div>
    );
  }
  return <Circle size={14} className="mt-0.5 shrink-0 text-zinc-300 dark:text-zinc-600" />;
}
