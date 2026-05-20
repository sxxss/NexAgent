import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="relative px-5 pb-4 pt-5 md:px-8 md:pt-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="relative min-w-0 pl-4">
          <span className="brand-gradient absolute left-0 top-1.5 h-[calc(100%-0.5rem)] w-[3px] rounded-full" aria-hidden />
          {eyebrow ? (
            <p className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-[0.18em] text-gradient">
              <span className="brand-gradient inline-block h-1.5 w-1.5 rounded-full" aria-hidden />
              {eyebrow}
            </p>
          ) : null}
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 md:text-3xl">{title}</h1>
          {description ? (
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
