"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Bot,
  Boxes,
  Brain,
  Database,
  Activity,
  LayoutDashboard,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
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

const STORAGE_KEY = "nexagent.sidebar.collapsed";

export function Sidebar() {
  const path = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  };

  return (
    <aside
      className={cn(
        "relative z-20 hidden shrink-0 p-3 transition-[width] duration-300 ease-in-out md:block",
        collapsed ? "w-[80px]" : "w-[220px]",
      )}
    >
      <div className="flex h-full flex-col rounded-3xl border border-white/75 bg-white/78 px-2.5 py-3 shadow-[0_18px_44px_rgba(80,96,128,0.16)] backdrop-blur-xl">
        {/* 顶部品牌区 */}
        <div className={cn("flex items-center gap-2.5 px-1 pb-3", collapsed && "justify-center")}>
          <Link
            href="/"
            className="brand-gradient flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl text-white shadow-[0_10px_22px_rgba(79,70,229,0.4)] transition-transform duration-200 hover:scale-105 hover:rotate-3"
            title="NexAgent"
            aria-label="NexAgent"
          >
            <Zap size={17} className="drop-shadow" />
          </Link>
          {!collapsed && (
            <div className="min-w-0 flex-1 overflow-hidden">
              <p className="truncate text-sm font-bold tracking-tight text-slate-800">NexAgent</p>
              <p className="truncate text-[11px] text-slate-400">Agent Workbench</p>
            </div>
          )}
        </div>

        <div className="mb-2 h-px bg-slate-200/70" />

        {/* 导航 */}
        <nav className="no-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto py-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon, exact }) => {
            const active = exact ? path === href : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                aria-label={label}
                className={cn(
                  "group relative flex h-10 items-center rounded-xl text-slate-500 transition-all duration-200",
                  collapsed ? "justify-center px-0" : "gap-3 px-3",
                  "hover:bg-indigo-50 hover:text-indigo-700",
                  active && "nav-item-active bg-[#eef2ff] text-[#4f46e5] shadow-[0_8px_16px_rgba(79,70,229,0.18)]",
                )}
              >
                {active && (
                  <span
                    className="brand-gradient absolute -left-[9px] top-1/2 h-5 w-1 -translate-y-1/2 rounded-full"
                    aria-hidden
                  />
                )}
                <Icon size={18} className={cn("shrink-0 transition-transform duration-200", active && "scale-105")} />
                {!collapsed && <span className="truncate text-sm font-medium">{label}</span>}
                {collapsed && (
                  <span className="pointer-events-none absolute left-[52px] z-30 whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 opacity-0 shadow-lg transition-all duration-150 group-hover:translate-x-1 group-hover:opacity-100">
                    {label}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* 底部:折叠按钮 + 主题切换 */}
        <div className="mt-2 space-y-1 border-t border-slate-200/70 pt-2">
          <button
            type="button"
            onClick={toggle}
            title={collapsed ? "展开导航" : "收起导航"}
            aria-label={collapsed ? "展开导航" : "收起导航"}
            className={cn(
              "flex h-10 w-full items-center rounded-xl text-slate-500 transition-colors hover:bg-indigo-50 hover:text-indigo-700",
              collapsed ? "justify-center px-0" : "gap-3 px-3",
            )}
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            {!collapsed && <span className="text-sm font-medium">收起</span>}
          </button>
          <div className={cn("flex", collapsed ? "justify-center" : "px-1")}>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </aside>
  );
}
