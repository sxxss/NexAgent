import * as React from "react";
import { cn } from "@/lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "glass" | "raised" | "subtle";
}

export function Card({ className, variant = "default", ...props }: CardProps) {
  return (
    <section
      className={cn(
        "overflow-hidden rounded-2xl border transition",
        variant === "default" && "border-white/80 bg-white/86 shadow-[0_14px_36px_rgba(83,101,132,0.10)]",
        variant === "raised" && "border-white bg-white shadow-[0_18px_48px_rgba(83,101,132,0.14)]",
        variant === "glass" && "border-white/75 bg-white/58 shadow-[0_18px_48px_rgba(83,101,132,0.12)] backdrop-blur-xl",
        variant === "subtle" && "border-slate-200/70 bg-slate-50/80",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-b border-slate-100/90 px-5 py-4", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-sm font-semibold tracking-tight text-slate-900", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-t border-slate-100/90 px-5 py-4", className)} {...props} />;
}
