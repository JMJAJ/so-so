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
        <header className="flex flex-wrap items-center justify-between gap-2 px-5 pt-4 pb-1">
          <div className="min-w-0">
            {title && <h2 className="text-base font-semibold text-foreground">{title}</h2>}
            {subtitle && (
              <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-muted-foreground">
                {subtitle}
              </p>
            )}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("p-5", bodyClassName)}>{children}</div>
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
        <h1 className="text-[28px] font-semibold leading-tight">{title}</h1>
        {subtitle && (
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
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
      <div className="text-xs font-semibold text-muted-foreground">{label}</div>
      <div
        className={cn("mt-1 truncate font-mono text-xl font-semibold tabular-nums", valueClassName)}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

const BADGE_TONES = {
  neutral: "border-border text-muted-foreground",
  bull: "border-[#1f3a27] text-bull bg-[#0f1a12]",
  bear: "border-[#3a2220] text-bear bg-[#1c1110]",
  amber: "border-[#3d3220] text-amber bg-[#1c170e]",
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
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-bold",
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
  return <Badge tone="neutral">{humanize(type)}</Badge>;
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
    <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border px-4 py-10 text-center">
      <div className="text-sm font-semibold text-muted-foreground">{title}</div>
      {children && (
        <div className="max-w-md text-sm leading-relaxed text-muted-foreground">{children}</div>
      )}
      {action}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin text-bull" /> {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  return (
    <div className="rounded-xl border border-[#3a2220] bg-[#1c1110] px-3 py-2 text-sm text-bear">
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
        "whitespace-nowrap border-b border-border px-2 py-2 text-xs font-semibold text-muted-foreground",
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
        "whitespace-nowrap border-b border-[#161916] px-2 py-2.5 text-[13px] tabular-nums",
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
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full border-collapse">{children}</table>
    </div>
  );
}

/** Horizontal bar centered at zero, for signal z-scores. */
export function ZBar({ value, max = 3 }: { value: number | null | undefined; max?: number }) {
  const v = Math.max(-max, Math.min(max, value ?? 0));
  const width = (Math.abs(v) / max) * 50;
  return (
    <div
      className="relative h-1.5 w-20 overflow-hidden rounded-full bg-muted"
      title={value == null ? "—" : value.toFixed(2)}
    >
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div
        className={cn("absolute top-0 h-full", v >= 0 ? "bg-bull" : "bg-bear")}
        style={{ left: v >= 0 ? "50%" : `${50 - width}%`, width: `${width}%` }}
      />
    </div>
  );
}

/** Is this effect real? "reliable" only when it survives the false-discovery correction
 * (q ≤ 0.10) and both halves of its history agree; otherwise it's labelled by why not. */
export function Reliability({
  t,
  n,
  q,
  stable,
  reliable,
}: {
  t: number | null | undefined;
  n?: number;
  q?: number | null;
  stable?: boolean;
  reliable?: boolean;
}) {
  const abs = Math.abs(t ?? 0);
  const label =
    n != null && n < 8
      ? "thin"
      : reliable
        ? "reliable"
        : reliable === false && stable === false
          ? "unstable"
          : q != null && q > 0.1
            ? "likely chance"
            : abs >= 2
              ? "unconfirmed"
              : "noise";
  const detail = [
    t != null ? `t ${t.toFixed(1)}` : null,
    n != null ? `n ${n}` : null,
    q != null ? `q ${q.toFixed(2)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span title={detail}>
      <Badge tone={label === "reliable" ? "bull" : "neutral"}>{label}</Badge>
    </span>
  );
}
