import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/components/AppProviders";
import { Sidebar } from "@/components/Sidebar";

const chunkRecoveryScript = `
(() => {
  const key = "nexagent:early-chunk-reload";
  const reloadWindowMs = 60000;
  const isChunkMessage = (value) => {
    const message = String(value || "");
    return message.includes("ChunkLoadError") || message.includes("Failed to load chunk") || message.includes("/_next/static/");
  };
  const reloadOnce = () => {
    const href = window.location.href;
    const now = Date.now();
    try {
      const marker = JSON.parse(window.sessionStorage.getItem(key) || "{}");
      if (marker.href === href && marker.ts && now - marker.ts < reloadWindowMs) return;
      window.sessionStorage.setItem(key, JSON.stringify({ href, ts: now }));
    } catch {}
    const reload = () => window.location.reload();
    if (window.caches?.keys) {
      window.caches.keys()
        .then((keys) => Promise.all(keys.map((cacheKey) => window.caches.delete(cacheKey))))
        .finally(reload);
      return;
    }
    reload();
  };
  window.addEventListener("error", (event) => {
    const target = event.target;
    const assetUrl = target && (target.src || target.href);
    if (isChunkMessage(assetUrl) || isChunkMessage(event.message) || isChunkMessage(event.error?.message)) {
      event.preventDefault();
      reloadOnce();
    }
  }, true);
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const message = reason?.message || reason;
    if (isChunkMessage(message)) {
      event.preventDefault();
      reloadOnce();
    }
  });
})();
`;

export const metadata: Metadata = {
  title: "NexAgent - Agent Workbench",
  description: "面向 Agent 开发、知识检索、MCP 扩展和自动化任务的本地工作台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: chunkRecoveryScript }} />
      </head>
      <body className="h-full text-slate-950 antialiased">
        <AppProviders>
          <div className="app-shell flex h-full overflow-hidden">
            <Sidebar />
            <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden px-3 py-3 md:px-4 md:py-4">
              <div className="min-h-0 flex-1 overflow-hidden rounded-[24px] border border-white/70 bg-white/45 shadow-[0_22px_72px_rgba(86,104,136,0.13)] backdrop-blur-xl">
                {children}
              </div>
            </main>
          </div>
        </AppProviders>
      </body>
    </html>
  );
}
