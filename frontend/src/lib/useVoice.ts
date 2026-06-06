"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { synthesizeSpeech, transcribeAudio } from "@/lib/api";

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

/** Push-to-talk recorder: records mic audio, sends it for transcription. */
export function useVoiceRecorder(onTranscribed: (text: string) => void) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const supported = typeof navigator !== "undefined" && !!navigator.mediaDevices && typeof MediaRecorder !== "undefined";

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!supported) {
      setError("当前浏览器不支持录音");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stopTracks();
        const type = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type });
        chunksRef.current = [];
        if (blob.size === 0) return;
        setBusy(true);
        try {
          const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
          const text = await transcribeAudio(blob, `recording.${ext}`);
          if (text.trim()) onTranscribed(text.trim());
          else setError("没有识别到语音内容");
        } catch (err) {
          setError(err instanceof Error ? err.message : "语音识别失败");
        } finally {
          setBusy(false);
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (err) {
      stopTracks();
      setError(err instanceof Error ? err.message : "无法访问麦克风");
    }
  }, [supported, onTranscribed, stopTracks]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    recorderRef.current = null;
    setRecording(false);
  }, []);

  const toggle = useCallback(() => {
    if (recording) stop();
    else void start();
  }, [recording, start, stop]);

  useEffect(
    () => () => {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      stopTracks();
    },
    [stopTracks],
  );

  return { recording, busy, error, supported, toggle, start, stop };
}

// Ensures only one TTS clip plays across the whole page.
let activeStopper: (() => void) | null = null;

/** Plays synthesized speech for a given message, one at a time. */
export function useTtsPlayer() {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    cleanup();
    setPlayingId(null);
  }, [cleanup]);

  const play = useCallback(
    async (id: string, text: string) => {
      setError(null);
      if (playingId === id) {
        stop();
        return;
      }
      // Stop whatever is currently playing elsewhere on the page, then claim it.
      activeStopper?.();
      activeStopper = stop;
      cleanup();
      setLoadingId(id);
      try {
        const { url } = await synthesizeSpeech(text);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => {
          setPlayingId(null);
          cleanup();
        };
        audio.onerror = () => {
          setPlayingId(null);
          setError("音频播放失败");
          cleanup();
        };
        await audio.play();
        setPlayingId(id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "语音合成失败");
        setPlayingId(null);
      } finally {
        setLoadingId(null);
      }
    },
    [playingId, stop, cleanup],
  );

  useEffect(() => () => cleanup(), [cleanup]);

  return { playingId, loadingId, error, play, stop };
}
