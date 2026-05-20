"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bot,
  Boxes,
  Brain,
  Database,
  Activity,
  LayoutDashboard,
  MessageSquare,
  Send,
  Settings,
  Sparkles,
  Wrench,
  Zap,
} from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "对话", icon: MessageSquare, exact: true },
  { href: "/dashboard", label: "洞察", icon: LayoutDashboard },
  { href: "/agents", label: "Agent", icon: Bot },
  { href: "/knowledge", label: "知识库", icon: Database },
  { href: "/memory", label: "记忆", icon: Brain },
  { href: "/mcp", label: "MCP", icon: Boxes },
  { href: "/skills", label: "Skills", icon: Wrench },
  { href: "/channels", label: "渠道", icon: Send },
  { href: "/eval", label: "评估", icon: BarChart3 },
  { href: "/diagnostics", label: "诊断", icon: Activity },
  { href: "/creator", label: "创建", icon: Sparkles },
  { href: "/settings", label: "设置", icon: Settings },
];

export function Sidebar() {
  const path = usePathname();

  return (
    <aside className="relative z-20 hidden w-[78px] shrink-0 items-center justify-center px-3 py-4 md:flex">
      <div className="flex max-h-full w-[58px] flex-col items-center rounded-[28px] border border-white/75 bg-white/78 px-1.5 py-3 shadow-[0_18px_44px_rgba(80,96,128,0.16)] backdrop-blur-xl">
        <Link
          href="/"
          className="brand-gradient mb-4 flex h-10 w-10 items-center justify-center rounded-2xl text-white shadow-[0_10px_22px_rgba(109,92,240,0.4)] transition-transform duration-200 hover:scale-105 hover:rotate-3"
          title="NexAgent"
          aria-label="NexAgent"
        >
          <Zap size={17} className="drop-shadow" />
        </Link>

        <nav className="no-scrollbar min-h-0 flex-1 space-y-1.5 overflow-y-auto py-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon, exact }) => {
            const active = exact ? path === href : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                title={label}
                aria-label={label}
                className={cn(
                  "group relative flex h-10 w-10 items-center justify-center rounded-xl text-slate-500 transition-all duration-200",
                  "hover:bg-violet-50 hover:text-violet-700",
                  active && "nav-item-active bg-[#efeafe] text-[#6d5cf0] shadow-[0_8px_16px_rgba(109,92,240,0.18)]",
                )}
              >
                {active && (
                  <span className="brand-gradient absolute -left-[7px] top-1/2 h-5 w-1 -translate-y-1/2 rounded-full" aria-hidden />
                )}
                <Icon size={17} className={cn("transition-transform duration-200", active && "scale-105")} />
                <span className="pointer-events-none absolute left-[48px] z-30 translate-x-0 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 opacity-0 shadow-lg transition-all duration-150 group-hover:translate-x-1 group-hover:opacity-100">
                  {label}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="mt-3 border-t border-slate-200/70 pt-2">
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
