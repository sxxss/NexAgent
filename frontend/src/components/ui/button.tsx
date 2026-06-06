import * as React from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "primary" | "outline" | "ghost" | "destructive" | "secondary";
  size?: "default" | "sm" | "lg" | "icon" | "icon-sm";
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "relative inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
          "disabled:pointer-events-none disabled:opacity-50",
          "active:scale-[0.97]",
          // focus ring color
          (variant === "primary") && "focus-visible:ring-sky-400",
          (variant !== "primary") && "focus-visible:ring-slate-400",

          // Variants
          variant === "default" &&
            "border border-white/80 bg-white/86 text-slate-800 shadow-[0_8px_18px_rgba(83,101,132,0.10)] hover:bg-white",
          variant === "primary" &&
            "brand-gradient text-white shadow-[0_10px_24px_rgba(79,70,229,0.32)] hover:brightness-[1.06] hover:shadow-[0_12px_28px_rgba(79,70,229,0.4)]",
          variant === "outline" &&
            "border border-slate-200/80 bg-white/40 text-slate-700 hover:bg-white/80 hover:border-slate-300",
          variant === "ghost" &&
            "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
          variant === "destructive" &&
            "bg-rose-500 text-white shadow-sm hover:bg-rose-600",
          variant === "secondary" &&
            "bg-slate-100/80 text-slate-700 hover:bg-slate-200/80",

          // Sizes
          size === "default" && "h-10 px-4 py-2 text-sm",
          size === "sm" && "h-8 px-3 text-xs",
          size === "lg" && "h-11 px-6 text-sm",
          size === "icon" && "h-9 w-9 p-0",
          size === "icon-sm" && "h-8 w-8 p-0",

          className,
        )}
        style={
          undefined
        }
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
