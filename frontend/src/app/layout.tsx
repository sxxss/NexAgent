import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/components/AppProviders";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "NexAgent - Agent Workbench",
  description: "面向 Agent 开发、知识检索、MCP 扩展和自动化任务的本地工作台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full" suppressHydrationWarning>
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
