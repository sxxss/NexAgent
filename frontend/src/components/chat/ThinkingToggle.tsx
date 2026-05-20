"use client";

import { Brain, ChevronDown, Gauge, Rocket, Sparkles, Zap } from "lucide-react";
import type { ComponentType } from "react";
import type { ReasoningMode } from "@/lib/api";
import { cn } from "@/lib/utils";

const MODES: Array<{
  id: ReasoningMode;
  label: string;
  desc: string;
  icon: ComponentType<{ size?: number; className?: string }>;
}> = [
  {
    id: "fast",
    label: "快速",
    desc: "优先低延迟和直接输出；保留工具与 Agent 调用能力，但默认尽量少用额外步骤。",
    icon: Zap,
  },
  {
    id: "balanced",
    label: "思考",
    desc: "增加轻量意图判断和一致性检查；在需要补充信息或分工时可调用已配置资源。",
    icon: Gauge,
  },
  {
    id: "deep",
    label: "Pro",
    desc: "启用计划倾向；更主动拆解目标、选择工具，并验证关键结论后再输出。",
    icon: Brain,
  },
  {
    id: "ultra",
    label: "Ultra",
    desc: "面向高复杂度任务；在 Pro 基础上提高任务拆分、多 Agent 协作和交叉验证倾向。",
    icon: Rocket,
  },
];

interface ThinkingToggleProps {
  mode: ReasoningMode;
  supportedModes: ReasoningMode[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onModeChange: (mode: ReasoningMode) => void;
}

export function ThinkingToggle({
  mode,
  supportedModes,
  open,
  onOpenChange,
  onModeChange,
}: ThinkingToggleProps) {
  const active = MODES.find((item) => item.id === mode) ?? MODES[1];
  const ActiveIcon = active.icon;

  return (
    <>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        title="思考模式"
        className={cn(
          "flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-semibold shadow-sm transition",
          "border-slate-200 bg-white/80 text-slate-700 hover:border-[#d8cdfa] hover:bg-white hover:text-[#4733c9]",
        )}
      >
        <ActiveIcon size={14} className="text-[#6d5cf0]" />
        {active.label}
        <ChevronDown size={13} className="text-slate-400" />
      </button>

      {open ? (
        <div
          className="absolute right-0 top-full z-40 mt-2 w-84 overflow-hidden rounded-2xl border border-slate-200 bg-white animate-slide-down"
          style={{ boxShadow: "var(--shadow-picker)" }}
        >
          <div className="border-b border-slate-100 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles size={15} className="text-[#6d5cf0]" />
              思考模式
            </div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              选择 Agent 的执行策略。资源是否可用由右侧配置决定，这里只调整规划深度和调用倾向。
            </p>
          </div>
          <div className="grid gap-1 p-2">
            {MODES.map((item) => {
              const Icon = item.icon;
              const supported = supportedModes.includes(item.id);
              return (
                <button
                  key={item.id}
                  type="button"
                  disabled={!supported}
                  onClick={() => {
                    onModeChange(item.id);
                    if (item.id === "fast" || item.id === "balanced") onOpenChange(false);
                  }}
                  className={cn(
                    "flex items-start gap-3 rounded-xl px-3 py-2.5 text-left transition",
                    supported ? "hover:bg-slate-50" : "cursor-not-allowed opacity-40",
                    mode === item.id && supported && "bg-[#efeafe] text-[#4733c9]",
                  )}
                >
                  <Icon size={16} className="mt-0.5 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">{item.label}</span>
                    <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                      {supported ? item.desc : "当前模型不可用该模式"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </>
  );
}
