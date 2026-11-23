import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Radio, Star } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { ago, price } from "@/lib/format";
import { useNav } from "@/lib/nav";
import type { NewsAlert } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useWatchlist } from "@/lib/watchlist";

/** Market context every page benefits from: the indices the tape always shows. */
export const CORE_TAPE = [
  "etf:spy",
  "etf:qqq",
  "index:vix",
  "index:tnx",
  "crypto:btc",
  "commodity:wti",
  "commodity:gold",
  "forex:eurusd",
];

/** Quotes for the watchlist plus held positions plus `extra`, refreshed every 30 s. */
export function useWatchQuotes(extra: string[] = []) {
  const { ids } = useWatchlist();
  const portfolio = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    staleTime: 30_000,
  });
  const held = useMemo(
    () => (portfolio.data?.positions ?? []).map((p) => p.instrument_id),
    [portfolio.data],
  );
  const all = useMemo(() => [...new Set([...ids, ...held, ...extra])], [ids, held, extra]);
  const quotes = useQuery({
    queryKey: ["quotes", all.join(",")],
    queryFn: () => api.quotes(all),
    enabled: all.length > 0,
    refetchInterval: 30_000,
    staleTime: 15_000,
    placeholderData: (previous) => previous,
  });
  return { rows: quotes.data ?? [], held: new Set(held), watched: ids, loading: quotes.isLoading };
}

export function RightRail() {
  return (
    <aside className="flex h-full w-[320px] flex-col border-l border-border bg-sidebar">
      <Watchlist />
      <LiveWire />
    </aside>
  );
}

function Watchlist() {
  const { rows, held, loading } = useWatchQuotes();
  const { openAsset, view, params } = useNav();
  const { toggle } = useWatchlist();
  return (
    <section className="flex max-h-[46%] min-h-0 flex-col border-b border-border">
      <header className="flex h-11 shrink-0 items-center justify-between px-4">
        <h2 className="text-[13px] font-semibold">Watchlist</h2>
        <span className="text-[11px] text-muted-foreground">
          Star a symbol on its page to add it
        </span>
      </header>
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 px-4 pb-1 text-[11px] text-muted-foreground">
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="w-14 text-right">Chg</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-2">
        {loading && <div className="px-4 py-3 text-xs text-muted-foreground">Loading quotes…</div>}
        {rows.map((row) => {
          const change = row.quote?.change_pct;
          const active = view === "asset" && params.id === row.id;
          return (
            <div
              key={row.id}
              className={cn(
                "group grid cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-x-3 px-4 py-1.5 hover:bg-accent/60",
                active && "bg-accent",
              )}
              onClick={() => openAsset(row.id)}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-[13px] font-semibold">{row.symbol}</span>
                {held.has(row.id) && (
                  <span className="rounded bg-primary-soft px-1 text-[10px] font-medium text-primary">
                    held
                  </span>
                )}
                <button
                  className="ml-auto hidden text-muted-foreground hover:text-foreground group-hover:block"
                  title="Remove from watchlist"
                  onClick={(event) => {
                    event.stopPropagation();
                    toggle(row.id);
                  }}
                >
                  <Star className="h-3 w-3 fill-current" />
                </button>
              </div>
              <span className="text-right font-mono text-xs">{price(row.quote?.price)}</span>
              <span
                className={cn(
                  "w-14 rounded px-1 text-right font-mono text-xs",
                  change == null
                    ? "text-muted-foreground"
                    : change >= 0
                      ? "text-bull"
                      : "text-bear",
                )}
              >
                {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function LiveWire() {
  const [level, setLevel] = useState(2);
  const alerts = useQuery({
    queryKey: ["alerts", "rail", level],
    queryFn: () => api.newsAlerts({ minutes: 24 * 60, min_level: level, limit: 60 }),
    refetchInterval: 60_000,
  });
  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-11 shrink-0 items-center justify-between px-4">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold">
          <Radio className="h-3.5 w-3.5 text-bear" /> Live wire
        </h2>
        <div className="segmented !p-0.5">
          {[
            [3, "Top"],
            [2, "Major"],
            [1, "All"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={level === value}
              onClick={() => setLevel(value as number)}
              className="!px-2 !py-0.5 !text-[11px]"
            >
              {label}
            </button>
          ))}
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {alerts.data?.length === 0 && (
          <div className="px-4 py-6 text-xs leading-relaxed text-muted-foreground">
            No alerts in the last 24 hours at this level. The wire polls about 50 sources roughly
            every minute.
          </div>
        )}
        {alerts.data?.map((alert) => (
          <AlertRow key={alert.id} alert={alert} />
        ))}
      </div>
    </section>
  );
}

export function AlertRow({ alert, wide = false }: { alert: NewsAlert; wide?: boolean }) {
  const { openAsset } = useNav();
  const moves = Object.entries(alert.moves ?? {}).filter(([, m]) => m.change_pct != null);
  return (
    <article className={cn("border-b border-row-line px-4 py-3", wide && "px-0")}>
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            alert.level >= 3 ? "bg-bear" : alert.level === 2 ? "bg-amber" : "bg-muted-foreground",
          )}
        />
        <span className="truncate">{alert.source}</span>
        <span>·</span>
        <span className="shrink-0" title={new Date(alert.published_at).toLocaleString()}>
          {ago(alert.published_at)}
        </span>
        {(alert.follow_ups ?? 0) > 0 && (
          <span className="ml-auto shrink-0" title="Other outlets carrying the same story">
            +{alert.follow_ups} sources
          </span>
        )}
      </div>
      <a
        href={alert.url ?? undefined}
        target="_blank"
        rel="noreferrer"
        className={cn(
          "mt-1 block font-medium leading-snug hover:text-primary",
          wide ? "text-sm" : "text-[13px]",
        )}
      >
        {alert.title}
        {alert.url && <ExternalLink className="ml-1 inline h-3 w-3 opacity-50" />}
      </a>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {alert.kinds.map((kind) => (
          <span
            key={kind}
            className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground"
          >
            {kind.replace("-", " ")}
          </span>
        ))}
        {alert.tickers
          .filter((t) => !t.startsWith("index:"))
          .slice(0, 4)
          .map((id) => {
            const move = moves.find(([m]) => m === id)?.[1]?.change_pct;
            return (
              <button
                key={id}
                onClick={() => openAsset(id)}
                className="rounded-full border border-border px-2 py-0.5 font-mono text-[10px] hover:border-strong"
                title="Move today when the alert fired"
              >
                {id.split(":")[1]?.toUpperCase()}
                {move != null && (
                  <span className={cn("ml-1", move >= 0 ? "text-bull" : "text-bear")}>
                    {move >= 0 ? "+" : ""}
                    {move.toFixed(1)}%
                  </span>
                )}
              </button>
            );
          })}
      </div>
    </article>
  );
}
