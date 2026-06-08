"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const CHUNK_RELOAD_KEY = "nexagent:chunk-reload";
const CHUNK_RELOAD_WINDOW_MS = 60_000;

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 20_000,
            retry: 1,
          },
        },
      }),
  );

  useEffect(() => {
    const reloadForChunkError = () => {
      const now = Date.now();
      const href = window.location.href;
      try {
        const marker = sessionStorage.getItem(CHUNK_RELOAD_KEY);
        if (marker) {
          const parsed = JSON.parse(marker) as { href?: string; ts?: number };
          if (parsed.href === href && parsed.ts && now - parsed.ts < CHUNK_RELOAD_WINDOW_MS) {
            return;
          }
        }
        sessionStorage.setItem(CHUNK_RELOAD_KEY, JSON.stringify({ href, ts: now }));
      } catch {
        // Session storage can be blocked; reloading once is still the best recovery path.
      }
      window.location.reload();
    };

    const isChunkError = (value: unknown) => {
      const message = value instanceof Error ? value.message : String(value ?? "");
      return message.includes("ChunkLoadError") || message.includes("Failed to load chunk") || message.includes("/_next/static/chunks/");
    };

    const handleError = (event: ErrorEvent) => {
      if (isChunkError(event.error) || isChunkError(event.message)) {
        event.preventDefault();
        reloadForChunkError();
      }
    };

    const handleRejection = (event: PromiseRejectionEvent) => {
      if (isChunkError(event.reason)) {
        event.preventDefault();
        reloadForChunkError();
      }
    };

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("nexagent-theme");
    const theme = saved === "dark" ? "dark" : "light";
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
