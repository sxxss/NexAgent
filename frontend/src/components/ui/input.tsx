import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "flex h-10 w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm",
      "text-zinc-900 placeholder:text-zinc-400 transition-colors",
      "hover:border-zinc-300",
      "focus:outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100",
      "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-zinc-50",
      "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500",
      "dark:hover:border-zinc-600",
      "dark:focus:border-indigo-500 dark:focus:ring-indigo-900/30 dark:disabled:bg-zinc-900",
      className
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "flex w-full rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-sm",
      "text-zinc-900 placeholder:text-zinc-400 resize-none transition-colors",
      "hover:border-zinc-300",
      "focus:outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100",
      "disabled:cursor-not-allowed disabled:opacity-50",
      "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500",
      "dark:hover:border-zinc-600",
      "dark:focus:border-indigo-500 dark:focus:ring-indigo-900/30",
      className
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
