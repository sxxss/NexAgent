"use client";

import { Loader2, Mic, PhoneOff, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { voiceCallWsUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

type CallStatus = "connecting" | "ready" | "listening" | "thinking" | "speaking" | "error" | "closed";
type Line = { role: "user" | "assistant"; text: string };

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

const STATUS_LABEL: Record<CallStatus, string> = {
  connecting: "正在连接...",
  ready: "已就绪，按住麦克风说话",
  listening: "正在聆听...",
  thinking: "思考中...",
  speaking: "正在回答...",
  error: "连接出错",
  closed: "通话已结束",
};

export function VoiceCallOverlay({
  onClose,
  agent,
  threadId,
  model,
}: {
  onClose: () => void;
  agent: string;
  threadId?: string;
  model?: string;
}) {
  const [status, setStatus] = useState<CallStatus>("connecting");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const pendingAudioRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const fmtRef = useRef("webm");

  const cleanupAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
  }, []);

  const hangUp = useCallback(() => {
    try {
      wsRef.current?.send(JSON.stringify({ type: "bye" }));
    } catch {
      /* noop */
    }
    wsRef.current?.close();
    wsRef.current = null;
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    cleanupAudio();
  }, [cleanupAudio]);

  useEffect(() => {
    const url = voiceCallWsUrl();
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "start", agent, thread_id: threadId, model }));
    };
    ws.onmessage = (event) => {
      if (typeof event.data !== "string") {
        // Binary audio for the pending audio_start.
        if (pendingAudioRef.current) {
          pendingAudioRef.current = false;
          const blob = new Blob([event.data], { type: "audio/mpeg" });
          cleanupAudio();
          const audio = new Audio(URL.createObjectURL(blob));
          audioRef.current = audio;
          setStatus("speaking");
          audio.onended = () => setStatus("ready");
          audio.onerror = () => setStatus("ready");
          void audio.play().catch(() => setStatus("ready"));
        }
        return;
      }
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (msg.type) {
        case "ready":
          setStatus("ready");
          break;
        case "transcript":
          setLines((prev) => [...prev, { role: "user", text: String(msg.text ?? "") }]);
          setStatus("thinking");
          break;
        case "reply":
          setLines((prev) => [...prev, { role: "assistant", text: String(msg.text ?? "") }]);
          break;
        case "audio_start":
          pendingAudioRef.current = true;
          break;
        case "audio_end":
          break;
        case "error":
          setError(String(msg.message ?? "出错了"));
          setStatus("ready");
          break;
      }
    };
    ws.onerror = () => {
      setStatus("error");
      setError("WebSocket 连接失败");
    };
    ws.onclose = () => setStatus((s) => (s === "error" ? s : "closed"));

    return () => hangUp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startTalking = useCallback(async () => {
    if (status === "listening" || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      fmtRef.current = mimeType.includes("ogg") ? "ogg" : mimeType.includes("mp4") ? "mp4" : "webm";
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN && blob.size > 0) {
          ws.send(JSON.stringify({ type: "utterance", format: fmtRef.current }));
          blob.arrayBuffer().then((buf) => ws.send(buf));
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setStatus("listening");
      setError(null);
    } catch {
      setError("无法访问麦克风");
    }
  }, [status]);

  const stopTalking = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") recorderRef.current.stop();
    recorderRef.current = null;
    setRecording(false);
  }, []);

  const busy = status === "thinking" || status === "speaking";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="relative flex h-[560px] w-full max-w-md flex-col overflow-hidden rounded-3xl border border-white/80 bg-white shadow-[0_30px_90px_rgba(39,56,87,0.28)]">
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h3 className="text-sm font-bold text-slate-900">语音通话</h3>
            <p className="text-xs text-slate-500">{STATUS_LABEL[status]}</p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X size={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
          {lines.length === 0 ? (
            <div className="mt-10 text-center text-sm text-slate-400">按住下方麦克风开始说话</div>
          ) : (
            lines.map((line, i) => (
              <div key={i} className={cn("flex", line.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[80%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                    line.role === "user" ? "bg-[#4f46e5] text-white" : "bg-slate-100 text-slate-800",
                  )}
                >
                  {line.text}
                </div>
              </div>
            ))
          )}
        </div>

        {error ? <div className="px-5 pb-1 text-center text-xs text-rose-500">{error}</div> : null}

        <footer className="flex flex-col items-center gap-3 border-t border-slate-100 px-5 py-5">
          <button
            type="button"
            disabled={status === "connecting" || busy}
            onMouseDown={() => void startTalking()}
            onMouseUp={stopTalking}
            onMouseLeave={() => recording && stopTalking()}
            onTouchStart={(e) => {
              e.preventDefault();
              void startTalking();
            }}
            onTouchEnd={(e) => {
              e.preventDefault();
              stopTalking();
            }}
            className={cn(
              "flex h-20 w-20 items-center justify-center rounded-full text-white shadow-lg transition active:scale-95 disabled:opacity-40",
              recording ? "animate-pulse bg-rose-500" : "bg-[#4f46e5] hover:brightness-110",
            )}
          >
            {busy ? <Loader2 size={28} className="animate-spin" /> : <Mic size={28} />}
          </button>
          <span className="text-xs text-slate-400">{recording ? "松开结束" : "按住说话"}</span>

          <button
            type="button"
            onClick={() => {
              hangUp();
              onClose();
            }}
            className="mt-1 inline-flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs font-semibold text-rose-600 hover:bg-rose-100"
          >
            <PhoneOff size={14} />
            挂断
          </button>
        </footer>
      </div>
    </div>
  );
}
