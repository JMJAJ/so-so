import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Markdown } from "@/features/shell/Markdown";
import { Badge, DirectionBadge } from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago, humanize, pct, price, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import type { Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

export function RecCard({ rec, compact = false }: { rec: Recommendation; compact?: boolean }) {
  const { openAsset } = useNav();
  const [open, setOpen] = useState(!compact);
  const client = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => api.cancelRecommendation(rec.id),
    onSuccess: () => {
      toast.success(`Cancelled ${rec.symbol}`);
      void client.invalidateQueries();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const ret = rec.status === "closed" ? rec.realized_return : rec.mark_return;
  const risk = Math.abs(rec.entry_price - rec.stop);
  const reward = Math.abs(rec.target - rec.entry_price);

  return (
    <article className="border border-border bg-background/40">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
        <button
          onClick={() => openAsset(rec.instrument_id)}
          className="font-display text-base font-bold hover:text-primary"
        >
          {rec.symbol}
        </button>
        <DirectionBadge direction={rec.direction} />
        <Badge>{rec.horizon_days} sessions</Badge>
        <Badge tone={rec.confidence === "high" ? "amber" : "neutral"}>{rec.confidence}</Badge>
        {rec.status !== "open" && <Badge>{rec.exit_reason ?? rec.status}</Badge>}
        <span className="ml-auto text-right">
          <span className={cn("font-display text-lg font-bold tabular-nums", tone(ret))}>
            {pct(ret)}
          </span>
          <span className="ml-2 text-[10px] text-muted-foreground">
            {rec.status === "closed" ? "realized" : "marked"}
          </span>
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 border-t border-border/60 px-3 py-2 text-[11px] sm:grid-cols-6">
        <Field label="Entry" value={price(rec.entry_price)} />
        <Field label="Stop" value={price(rec.stop)} className="text-bear" />
        <Field label="Target" value={price(rec.target)} className="text-bull" />
        <Field label="P(win)" value={`${Math.round(rec.probability * 100)}%`} />
        <Field label="R/R" value={risk ? (reward / risk).toFixed(1) : "—"} />
        <Field
          label={rec.status === "open" ? "Expires" : "Excess"}
          value={rec.status === "open" ? ago(rec.expires_at) : pct(rec.excess_return)}
        />
      </div>
      <div className="flex flex-wrap gap-1.5 border-t border-border/60 px-3 py-2">
        {rec.evidence.slice(0, open ? 20 : 3).map((item, index) => (
          <span
            key={index}
            className="inline-flex max-w-full items-start gap-1.5 border border-border px-1.5 py-1 text-[10px] leading-snug"
          >
            <span className="shrink-0 font-bold uppercase tracking-wider text-primary">
              {humanize(item.type)}
            </span>
            <span className="text-muted-foreground">{item.summary}</span>
          </span>
        ))}
      </div>
      {open && (
        <div className="space-y-2 border-t border-border/60 px-3 py-3">
          <Markdown text={rec.thesis} />
          {rec.catalysts.length > 0 && (
            <div className="text-[11px] text-muted-foreground">
              <span className="font-bold uppercase tracking-wider text-foreground">
                Catalysts:{" "}
              </span>
              {rec.catalysts.join(" · ")}
            </div>
          )}
          {rec.invalidation && (
            <div className="text-[11px] text-muted-foreground">
              <span className="font-bold uppercase tracking-wider text-foreground">Wrong if: </span>
              {rec.invalidation}
            </div>
          )}
          {rec.trade_note && (
            <div className="text-[11px] text-bear">Not traded: {rec.trade_note}</div>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-t border-border/60 px-3 py-1.5 text-[10px] text-muted-foreground">
        <span>
          {rec.source} · {ago(rec.created_at)}
          {rec.position_id ? " · paper position" : ""}
        </span>
        <span className="ml-auto flex gap-1">
          <button
            className="icon-button !p-1"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? "Collapse" : "Expand"}
          >
            {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          <button
            className="icon-button !p-1"
            onClick={() => openAsset(rec.instrument_id)}
            aria-label="Open asset"
          >
            <ExternalLink className="h-3 w-3" />
          </button>
          {rec.status === "open" && (
            <button
              className="icon-button !p-1 hover:!text-bear"
              disabled={cancel.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Cancel the ${rec.symbol} recommendation and close its paper position?`,
                  )
                )
                  cancel.mutate();
              }}
              aria-label="Cancel recommendation"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </span>
      </div>
    </article>
  );
}

function Field({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">{label}</div>
      <div className={cn("tabular-nums", className)}>{value}</div>
    </div>
  );
}
