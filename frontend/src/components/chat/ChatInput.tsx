"use client";

import { CornerDownLeft, Loader2, Mic, Send, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useVoiceRecorder } from "@/lib/useVoice";

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
  const voice = useVoiceRecorder((text) => {
    const prefix = value.trim();
    onChange(prefix ? `${prefix} ${text}` : text);
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 104)}px`;
  }, [value]);

  const canSend = !isStreaming && !!value.trim() && !disabled;

  return (
    <div className="input-glow overflow-hidden rounded-[18px] border border-white/70 bg-white/72 shadow-[0_12px_32px_rgba(83,101,132,0.13)] backdrop-blur-2xl">
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
          "max-h-24 min-h-8 w-full resize-none bg-transparent px-3.5 pt-2 pb-0",
          "text-sm leading-6 text-slate-900 outline-none",
          "placeholder:text-slate-400",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      />
      <div className="flex items-center justify-between gap-3 border-t border-white/50 bg-white/30 px-2.5 py-1.5">
        <div className="flex items-center gap-2">
          <ChatInputHint />
          {voice.error ? <span className="max-w-[180px] truncate text-[11px] text-rose-500">{voice.error}</span> : null}
        </div>
        <div className="flex items-center gap-2">
          {voice.supported ? (
            <button
              type="button"
              disabled={disabled || isStreaming || voice.busy}
              onClick={voice.toggle}
              title={voice.recording ? "停止录音并识别" : "按一下开始语音输入"}
              className={cn(
                "inline-flex h-7 w-7 items-center justify-center rounded-xl border transition active:scale-[0.97]",
                "disabled:cursor-not-allowed disabled:opacity-40",
                voice.recording
                  ? "animate-pulse border-rose-300 bg-rose-50 text-rose-500"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
              )}
            >
              {voice.busy ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
            </button>
          ) : null}
          <button
            type="button"
            disabled={!isStreaming && !canSend}
          onClick={() => {
            if (isStreaming) onStop?.();
            else onSend();
          }}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-xl px-2.5 text-xs font-semibold transition active:scale-[0.97]",
            "disabled:cursor-not-allowed disabled:opacity-40",
            isStreaming
              ? "border border-white/70 bg-white/70 text-slate-700 hover:bg-white"
              : "bg-[#4f46e5] text-white shadow-[0_10px_24px_rgba(79,70,229,0.22)]",
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
    </div>
  );
}

export function ChatInputHint() {
  return (
    <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
      <kbd className="flex h-4 items-center justify-center rounded border border-white/70 bg-white/55 px-1 text-[10px] font-medium">
        <CornerDownLeft size={9} />
      </kbd>
      <span>发送</span>
      <span className="text-slate-300">/</span>
      <span>Shift+Enter 换行</span>
    </div>
  );
}
