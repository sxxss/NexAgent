"use client";

import { CornerDownLeft, Send, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  isStreaming: boolean;
  disabled?: boolean;
}

export function ChatInput({ value, onChange, onSend, onStop, isStreaming, disabled }: ChatInputProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [value]);

  const canSend = !isStreaming && !!value.trim() && !disabled;

  return (
    <div className="input-glow rounded-2xl border border-white/85 bg-white/88 shadow-[0_18px_42px_rgba(83,101,132,0.12)] backdrop-blur">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        disabled={disabled || isStreaming}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (canSend) onSend();
          }
        }}
        placeholder="输入任务、问题，或交给 Agent 处理的目标..."
        className={cn(
          "max-h-44 min-h-14 w-full resize-none bg-transparent px-4 py-4",
          "text-sm leading-6 text-slate-900 outline-none",
          "placeholder:text-slate-400",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-3">
        <ChatInputHint />
        <button
          type="button"
          disabled={!isStreaming && !canSend}
          onClick={() => {
            if (isStreaming) onStop?.();
            else onSend();
          }}
          className={cn(
            "inline-flex h-9 items-center gap-2 rounded-xl px-3.5 text-xs font-semibold transition active:scale-[0.97]",
            "disabled:cursor-not-allowed disabled:opacity-40",
            isStreaming ? "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50" : "bg-[#6d5cf0] text-white",
          )}
        >
          {isStreaming ? (
            <>
              <Square size={12} fill="currentColor" />
              停止
            </>
          ) : (
            <>
              <Send size={13} />
              发送
            </>
          )}
        </button>
      </div>
    </div>
  );
}

export function ChatInputHint() {
  return (
    <div className="flex items-center gap-1.5 text-xs text-slate-400">
      <kbd className="flex h-4 items-center justify-center rounded border border-slate-200 bg-slate-50 px-1 text-[10px] font-medium">
        <CornerDownLeft size={9} />
      </kbd>
      <span>发送</span>
      <span className="text-slate-300">/</span>
      <span>Shift+Enter 换行</span>
    </div>
  );
}
