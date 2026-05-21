import { cn } from "@/lib/utils";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "teal" | "success" | "warning" | "error" | "info" | "violet" | "secondary";
  className?: string;
  dot?: boolean;
}

const VARIANT_STYLES: Record<string, string> = {
  default: "bg-slate-100 text-slate-700 border-slate-200/60",
  teal: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200/60",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200/60",
  warning: "bg-amber-50 text-amber-700 border-amber-200/60",
  error: "bg-rose-50 text-rose-700 border-rose-200/60",
  info: "bg-sky-50 text-sky-700 border-sky-200/60",
  violet: "bg-violet-50 text-violet-700 border-violet-200/60",
  secondary: "bg-slate-50 text-slate-500 border-slate-200/40",
};

const DOT_STYLES: Record<string, string> = {
  default: "bg-slate-500",
  teal: "bg-fuchsia-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-rose-500",
  info: "bg-sky-500",
  violet: "bg-violet-500",
  secondary: "bg-slate-400",
};

export function Badge({ children, variant = "default", dot = false, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        VARIANT_STYLES[variant] ?? VARIANT_STYLES.default,
        className,
      )}
    >
      {dot && (
        <span
          className={cn("h-1.5 w-1.5 rounded-full", DOT_STYLES[variant] ?? DOT_STYLES.default)}
        />
      )}
      {children}
    </span>
  );
}
