import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, MessageSquare, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { useChat } from "@/features/chat/chat-context";
import { Badge } from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago, pct, price } from "@/lib/format";
import type { Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The open AI call on an instrument: the one green card on a screen. */
export function AiCallCard({ rec, symbol }: { rec: Recommendation | undefined; symbol: string }) {
  const { ask } = useChat();
  const client = useQueryClient();
  const trade = useMutation({
    mutationFn: () => api.tradeRecommendation(rec!.id),
    onSuccess: () => {
      toast.success(`Paper order placed for ${symbol}`);
      void client.invalidateQueries();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (!rec) {
    return (
      <section className="terminal-panel flex flex-col gap-3 p-5">
        <div className="flex items-center gap-3">
          <Bot className="h-5 w-5 text-muted-foreground" />
          <div>
            <h2 className="text-base font-semibold">No open AI call on {symbol}</h2>
            <p className="text-xs text-muted-foreground">
              The AI records a call only when the evidence clears the gate.
            </p>
          </div>
        </div>
        <button className="primary-button" onClick={() => ask(`/recommend ${symbol}`, true)}>
          <Sparkles className="h-4 w-4" /> Ask the AI for a call
        </button>
      </section>
    );
  }

  const override = rec.evidence.some((e) => e.type === "gate_override");
  return (
    <section aria-label="AI call" className="accent-card flex flex-col">
      <div className="flex items-center gap-3 border-b border-white/15 px-5 py-4">
        <Bot className="h-6 w-6" />
        <div className="min-w-0">
          <div className="text-base font-bold">
            AI call · {rec.direction === "long" ? "Long" : "Short"} {rec.symbol}
          </div>
          <div className="text-xs text-white/75">
            Opened {ago(rec.created_at)} · {rec.horizon_days} sessions
          </div>
        </div>
        <span className="ml-auto rounded-md bg-black/20 px-2 py-1 text-[11px] font-bold">
          {override ? "Gate overridden" : "Gate passed"}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 px-5 pt-4">
        {(
          [
            ["Entry", rec.entry_price],
            ["Stop", rec.stop],
            ["Target", rec.target],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5 rounded-xl bg-black/20 px-3 py-2.5">
            <span className="text-[11px] text-white/75">{label}</span>
            <span className="font-mono text-[15px] font-semibold">{price(value)}</span>
          </div>
        ))}
      </div>
      <div className="flex items-end justify-between gap-3 px-5 py-4">
        <div className="flex flex-col">
          <span className="text-[11px] text-white/75">Win probability (computed)</span>
          <span className="font-mono text-3xl font-semibold">{pct(rec.probability, 0, false)}</span>
          {rec.size_tier && (
            <span className="text-[11px] text-white/75">
              Size: {rec.size_tier.replace("_", " ")} ({pct(rec.risk_mult ?? 1, 0, false)} of risk
              budget)
            </span>
          )}
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[11px] text-white/75">
            {rec.status === "open" && rec.mark_return != null ? "Now" : "Expected value"}
          </span>
          <span className="font-mono text-lg font-semibold">
            {rec.status === "open" && rec.mark_return != null
              ? pct(rec.mark_return)
              : `${pct(rec.expected_return)} / trade`}
          </span>
        </div>
      </div>
      <div className="flex gap-2 px-5 pb-5">
        {rec.traded ? (
          <span className="flex min-h-11 flex-1 items-center justify-center rounded-xl bg-black/20 text-sm font-bold">
            In this account
          </span>
        ) : (
          <button
            className="min-h-11 flex-1 rounded-xl bg-white text-sm font-bold text-primary-strong disabled:opacity-60"
            disabled={trade.isPending}
            onClick={() => trade.mutate()}
          >
            {trade.isPending ? "Placing…" : "Place paper order"}
          </button>
        )}
        <button
          className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-xl border border-white/35 text-sm font-semibold"
          onClick={() => ask(`/why ${rec.symbol}`, true)}
        >
          <MessageSquare className="h-4 w-4" /> Ask why
        </button>
      </div>
    </section>
  );
}

const STEP_NAMES: Record<string, string> = {
  news: "News",
  event_study: "Event study",
  events: "Event study",
  event: "Event study",
  analogs: "Analogs",
  quant: "Quant model",
  model: "Quant model",
  correlation: "Lead-lag drivers",
  correlations: "Lead-lag drivers",
  technical: "Technicals",
  calibration: "Probability engine",
  shock_reaction: "Shock reaction",
  sizing: "Position size",
  gate_override: "Gate",
};

/** The call's evidence trail, in the order the AI used it, ending at the gate. */
export function EvidenceSteps({ rec }: { rec: Recommendation }) {
  const steps = rec.evidence.map((item) => {
    const kind = String(item.type ?? "other");
    const off = kind === "gate_override";
    return {
      title: STEP_NAMES[kind] ?? kind.replace(/_/g, " "),
      detail: item.summary,
      status: off ? "override" : kind === "calibration" ? pct(rec.probability, 0, false) : "used",
      off,
    };
  });
  if (!rec.evidence.some((e) => e.type === "gate_override")) {
    steps.push({
      title: "Gate",
      detail: "Expected value positive and probability above the minimum",
      status: "passed",
      off: false,
    });
  }
  return (
    <section aria-label="How the AI got here" className="terminal-panel p-5">
      <h2 className="mb-3 text-[15px] font-semibold">How the AI got here</h2>
      <ol className="flex flex-col">
        {steps.map((step, index) => (
          <li key={index} className="grid grid-cols-[34px_minmax(0,1fr)_auto] gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  "grid h-[34px] w-[34px] place-items-center rounded-[10px] border bg-raised text-[13px] font-bold",
                  step.off ? "border-bear-line text-bear" : "border-bull-line text-bull",
                )}
              >
                {step.title.charAt(0)}
              </span>
              {index < steps.length - 1 && <span className="min-h-4 w-px flex-1 bg-bull-line" />}
            </div>
            <div className="flex flex-col gap-0.5 pb-4">
              <span className="text-sm font-semibold">{step.title}</span>
              <span className="text-xs leading-relaxed text-muted-foreground">{step.detail}</span>
            </div>
            <span className="self-start">
              <Badge tone={step.off ? "bear" : "bull"}>{step.status}</Badge>
            </span>
          </li>
        ))}
      </ol>
      {rec.skills && rec.skills.length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          Skills loaded: {rec.skills.map((tag) => tag.replace("@", " v")).join(", ")}
        </p>
      )}
    </section>
  );
}
