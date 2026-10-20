import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { humanize } from "@/lib/format";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("terminal-panel min-w-0", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div className="min-w-0">
            {title && (
              <h2 className="text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-[11px] text-muted-foreground">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeading({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  valueClassName,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  valueClassName?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[9px] font-bold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn("mt-1 truncate font-display text-xl font-bold tabular-nums", valueClassName)}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

const BADGE_TONES = {
  neutral: "border-border text-muted-foreground",
  bull: "border-bull/40 text-bull bg-bull/5",
  bear: "border-bear/40 text-bear bg-bear/5",
  amber: "border-primary/40 text-primary bg-primary/5",
} as const;

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof BADGE_TONES;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.12em]",
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function DirectionBadge({ direction }: { direction: "long" | "short" }) {
  return <Badge tone={direction === "long" ? "bull" : "bear"}>{direction}</Badge>;
}

export function EventBadge({ type }: { type: string }) {
  return (
    <Badge tone="amber" className="normal-case tracking-normal">
      {humanize(type)}
    </Badge>
  );
}

export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 border border-dashed border-border px-4 py-10 text-center">
      <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </div>
      {children && (
        <div className="max-w-md text-xs leading-relaxed text-muted-foreground">{children}</div>
      )}
      {action}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="border border-bear/40 bg-bear/5 px-3 py-2 text-xs text-bear">
      {error instanceof Error ? error.message : "Something went wrong"}
    </div>
  );
}

export function Th({
  children,
  right,
  className,
}: {
  children?: ReactNode;
  right?: boolean;
  className?: string;
}) {
  return (
    <th
      className={cn(
        "whitespace-nowrap border-b border-border px-2 py-2 text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground",
        right ? "text-right" : "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  right,
  className,
  title,
}: {
  children?: ReactNode;
  right?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <td
      title={title}
      className={cn(
        "whitespace-nowrap border-b border-border/60 px-2 py-2 text-xs tabular-nums",
        right && "text-right",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function TableWrap({ children }: { children: ReactNode }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full border-collapse">{children}</table>
    </div>
  );
}

/** Horizontal bar centered at zero, for signal z-scores. */
export function ZBar({ value, max = 3 }: { value: number | null | undefined; max?: number }) {
  const v = Math.max(-max, Math.min(max, value ?? 0));
  const width = (Math.abs(v) / max) * 50;
  return (
    <div className="relative h-1.5 w-20 bg-muted" title={value == null ? "—" : value.toFixed(2)}>
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div
        className={cn("absolute top-0 h-full", v >= 0 ? "bg-bull" : "bg-bear")}
        style={{ left: v >= 0 ? "50%" : `${50 - width}%`, width: `${width}%` }}
      />
    </div>
  );
}

/** Evidence strength from a t-stat: makes "is this real?" visible at a glance. */
export function Reliability({ t, n }: { t: number | null | undefined; n?: number }) {
  const abs = Math.abs(t ?? 0);
  const label =
    n != null && n < 8
      ? "thin"
      : abs >= 3
        ? "strong"
        : abs >= 2
          ? "solid"
          : abs >= 1
            ? "weak"
            : "noise";
  const toneName = label === "strong" || label === "solid" ? "amber" : "neutral";
  return <Badge tone={toneName}>{label}</Badge>;
}
