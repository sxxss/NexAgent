"use client";
import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  title?: string;
  description?: string;
  className?: string;
  contentClassName?: string;
}

export function Dialog({ open, onClose, children, title, description, className, contentClassName }: DialogProps) {
  React.useEffect(() => {
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    if (open) document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog panel */}
      <div
        className={cn(
          "relative z-10 w-full max-w-md overflow-hidden rounded-2xl shadow-2xl",
          "dialog-pop-in border border-zinc-200 bg-white transition-all duration-200 ease-out dark:border-zinc-700 dark:bg-zinc-900",
          className,
        )}
      >
        {/* Header */}
        {title && (
          <div className="flex items-start justify-between border-b border-zinc-100 px-6 py-4 dark:border-zinc-800">
            <div>
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
              {description && (
                <p className="mt-0.5 text-xs text-zinc-500">{description}</p>
              )}
            </div>
            <button
              type="button"
              aria-label="关闭"
              title="关闭"
              onClick={onClose}
              className="ml-3 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
            >
              <X size={15} />
            </button>
          </div>
        )}

        {/* Content */}
        <div className={cn("max-h-[80vh] overflow-y-auto px-6 py-5", contentClassName)}>
          {children}
        </div>
      </div>
    </div>
  );
}
