import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Sparkline, chartColors } from "@/features/charts/svg";
import { RecCard } from "@/features/recs/RecCard";
import { Markdown } from "@/features/shell/Markdown";
import {
  Badge,
  Empty,
  ErrorNote,
  EventBadge,
  Loading,
  PageHeading,
  Panel,
  Reliability,
  Stat,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago, humanize, money, num, pct, price, shortDate, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import type { Dashboard, Forecast, MarketEvent, NewsItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function TodayView() {
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
    refetchInterval: 60_000,
  });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });

  if (dashboard.isLoading) return <Loading label="Loading dashboard" />;
  if (dashboard.error) return <ErrorNote error={dashboard.error} />;
  const data = dashboard.data as Dashboard;

  return (
    <div className="space-y-4">
      <PageHeading
        title="Today"
        subtitle="What the evidence says right now: market regime, the AI's open calls and how they're doing, and the events that historically move markets."
      />
      <BalanceHero data={data} />
      <RegimeStrip data={data} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <AnalystPanel data={data} running={status.data?.analyst_running ?? false} />
          <Panel
            title="Open AI calls"
            subtitle="Each is tracked on its own path to stop, target or horizon, whether or not it was traded."
          >
            {data.open_recommendations.length === 0 ? (
              <Empty title="No open calls">
                Run the analyst, or ask the chat to investigate something with /recommend.
              </Empty>
            ) : (
              <div className="space-y-2">
                {data.open_recommendations.map((rec) => (
                  <RecCard key={rec.id} rec={rec} compact />
                ))}
              </div>
            )}
          </Panel>
        </div>
        <div className="min-w-0 space-y-4">
          <IdeasPanel ideas={data.ideas} />
          <EventsPanel events={data.key_events} />
          <HeadlinesPanel items={data.headlines} />
        </div>
      </div>
    </div>
  );
}

/** Revolut-style balance header: one big number, what changed, and the equity curve. */
function BalanceHero({ data }: { data: Dashboard }) {
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const curve = (portfolio.data?.equity_curve ?? []).map((point) => point.equity);
  const p = data.portfolio;
  const facts: Array<{ label: string; value: string; hint: string; className?: string }> = [
    {
      label: "Open P&L",
      value: money(p.unrealized, true),
      hint: `${p.open_count} open · ${p.pending_count} pending`,
      className: tone(p.unrealized),
    },
    {
      label: "Realised",
      value: money(p.realized, true),
      hint: `${num(p.exposure_pct, 0)}% of equity exposed`,
      className: tone(p.realized),
    },
    {
      label: "AI hit rate",
      value: data.track.n ? pct(data.track.hit_rate ?? null, 0, false) : "—",
      hint: data.track.n ? `${data.track.n} closed calls` : "No closed calls yet",
    },
    {
      label: "Calibration",
      value: data.track.n ? num(data.track.brier ?? null, 3) : "—",
      hint: "Brier · 0.25 = coin flip",
    },
  ];
  return (
    <section className="terminal-panel overflow-hidden">
      <div className="flex flex-wrap items-end justify-between gap-6 px-6 pt-6">
        <div className="min-w-0">
          <div className="text-sm text-muted-foreground">Paper balance</div>
          <div className="mt-1 font-mono text-[40px] font-semibold leading-none tracking-tight sm:text-[48px]">
            {money(p.equity)}
          </div>
          <div className={cn("mt-2 text-sm font-medium", tone(p.return_pct))}>
            {pct(p.return_pct / 100, 2)} all time
          </div>
        </div>
        <div className="grid w-full grid-cols-2 gap-x-8 gap-y-4 sm:w-auto sm:grid-cols-4">
          {facts.map((fact) => (
            <div key={fact.label} className="min-w-0">
              <div className="text-xs text-muted-foreground">{fact.label}</div>
              <div className={cn("mt-0.5 font-mono text-base font-semibold", fact.className)}>
                {fact.value}
              </div>
              <div className="truncate text-[11px] text-muted-foreground">{fact.hint}</div>
            </div>
          ))}
        </div>
      </div>
      <EquityArea values={curve} up={(p.return_pct ?? 0) >= 0} />
    </section>
  );
}

function EquityArea({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return <div className="h-6" />;
  const width = 1000;
  const height = 110;
  // At least 1% of equity tall, so a flat account looks flat instead of a cliff.
  const mid = (Math.min(...values) + Math.max(...values)) / 2;
  const span = Math.max(Math.max(...values) - Math.min(...values), Math.abs(mid) * 0.01, 1e-9);
  const lo = mid - span / 2;
  const points = values.map((v, i) => [
    (i / (values.length - 1)) * width,
    height - 6 - ((v - lo) / span) * (height - 18),
  ]);
  const line = points
    .map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join("");
  const color = up ? "var(--color-bull)" : "var(--color-bear)";
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="mt-4 block h-[110px] w-full"
      role="img"
      aria-label="Paper equity over time"
    >
      <defs>
        <linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line}L${width},${height}L0,${height}Z`} fill="url(#equity-fill)" />
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function RegimeStrip({ data }: { data: Dashboard }) {
  const regime = data.regime?.current;
  if (!regime) return null;
  const history = data.regime?.history ?? [];
  const riskTone =
    regime.risk === "risk-on" ? "bull" : regime.risk === "risk-off" ? "bear" : "amber";
  const cells: Array<{
    label: string;
    value: string;
    spark?: Array<number | null>;
    className?: string;
  }> = [
    {
      label: "VIX",
      value: `${num(regime.vix, 1)} · p${Math.round((regime.vix_percentile ?? 0) * 100)}`,
      spark: history.map((h) => h.vix),
    },
    { label: "S&P 60d", value: pct(regime.spy_ret_60d), className: tone(regime.spy_ret_60d) },
    { label: "S&P drawdown", value: pct(regime.spy_drawdown), spark: history.map((h) => h.spy_dd) },
    {
      label: "Curve 10y–3m",
      value: `${num(regime.curve_10y_3m, 2)}%`,
      spark: history.map((h) => h.curve),
      className: regime.curve_inverted ? "text-bear" : "",
    },
    {
      label: "10Y yield",
      value: `${num(regime.us10y, 2)}% (${regime.us10y_chg_60d != null && regime.us10y_chg_60d > 0 ? "+" : ""}${num(regime.us10y_chg_60d, 2)})`,
    },
    {
      label: "Dollar 60d",
      value: pct(regime.dollar_ret_60d),
      className: tone(regime.dollar_ret_60d),
    },
    { label: "Oil 60d", value: pct(regime.oil_ret_60d), className: tone(regime.oil_ret_60d) },
    { label: "HY spread", value: `${num(regime.hy_spread, 2)}%` },
    {
      label: "Conflict news",
      value:
        regime.conflict_z == null
          ? "—"
          : `${regime.conflict_z > 0 ? "+" : ""}${num(regime.conflict_z, 1)}σ`,
      spark: history.map((h) => h.conflict_z),
    },
  ];
  return (
    <section className="terminal-panel flex flex-wrap items-stretch">
      <div className="flex min-w-[140px] flex-col justify-center border-r border-border px-4 py-3">
        <div className="text-[11px] font-bold text-muted-foreground">Regime</div>
        <Badge tone={riskTone} className="mt-1 self-start text-[11px]">
          {regime.risk}
        </Badge>
        <div className="mt-1 text-xs text-muted-foreground">
          as of {shortDate(data.regime?.as_of)}
        </div>
      </div>
      {cells.map((cell) => (
        <div
          key={cell.label}
          className="min-w-[120px] flex-1 border-r border-border/60 px-3 py-2.5 last:border-r-0"
        >
          <div className="text-[11px] text-muted-foreground">{cell.label}</div>
          <div className={cn("text-sm font-bold tabular-nums", cell.className)}>{cell.value}</div>
          {cell.spark && <Sparkline values={cell.spark.slice(-120)} color={chartColors.MUTED} />}
        </div>
      ))}
    </section>
  );
}

function AnalystPanel({ data, running }: { data: Dashboard; running: boolean }) {
  const client = useQueryClient();
  const [focus, setFocus] = useState("");
  const run = useMutation({
    mutationFn: () => api.runAnalyst(focus),
    onSuccess: () => {
      toast.success("Analyst started. New calls appear here when it finishes (a few minutes).");
      void client.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const brief = data.brief;
  return (
    <Panel
      title="AI market brief"
      subtitle={
        brief
          ? `${brief.status} · ${ago(brief.finished_at ?? brief.started_at)}`
          : "The analyst runs automatically after the US close on weekdays."
      }
      actions={
        <form
          className="flex gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            run.mutate();
          }}
        >
          <input
            className="terminal-input !min-h-0 w-40 !py-1.5 text-[11px]"
            placeholder="Optional focus…"
            value={focus}
            onChange={(event) => setFocus(event.target.value)}
          />
          <button
            className="primary-button inline-flex items-center gap-1.5"
            disabled={running || run.isPending}
          >
            {running ? <Bot className="h-3 w-3 animate-pulse" /> : <Play className="h-3 w-3" />}
            {running ? "Researching" : "Run analyst"}
          </button>
        </form>
      }
    >
      {brief?.summary ? (
        <div className="max-h-[420px] overflow-y-auto pr-1">
          <Markdown text={brief.summary} />
        </div>
      ) : brief?.error ? (
        <div className="text-xs text-bear">Last run failed: {brief.error}</div>
      ) : (
        <Empty title="No brief yet">Configure an LLM in Settings, then run the analyst.</Empty>
      )}
    </Panel>
  );
}

function IdeasPanel({ ideas }: { ideas: Forecast[] }) {
  const { openAsset, go } = useNav();
  return (
    <Panel
      title="Where the evidence is strongest"
      subtitle="Ranked by validated forecast, or by event + analog evidence where no model edge exists."
      actions={
        <button className="secondary-button" onClick={() => go("ideas")}>
          Screener
        </button>
      }
    >
      {ideas.length === 0 ? (
        <Empty title="No forecasts yet">
          History is still loading. This fills in after the first bootstrap.
        </Empty>
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>Asset</Th>
              <Th right>Price</Th>
              <Th right>E[20d]</Th>
              <Th right>P(up)</Th>
              <Th>Drivers</Th>
            </tr>
          </thead>
          <tbody>
            {ideas.slice(0, 10).map((idea) => (
              <tr
                key={idea.instrument_id}
                className="cursor-pointer hover:bg-accent/30"
                onClick={() => openAsset(idea.instrument_id)}
              >
                <Td>
                  <span className="font-bold">{idea.symbol}</span>{" "}
                  <span className="text-xs text-muted-foreground">{idea.asset_class}</span>
                </Td>
                <Td right>{price(idea.price)}</Td>
                <Td right className={tone(idea.expected_return)}>
                  {pct(idea.expected_return)}
                  {!idea.model_has_edge && (
                    <span
                      className="ml-1 text-[11px] text-muted-foreground"
                      title="No validated model edge"
                    >
                      *
                    </span>
                  )}
                </Td>
                <Td right>{pct(idea.prob_up, 0, false)}</Td>
                <Td className="max-w-[180px] truncate text-xs text-muted-foreground">
                  {driverText(idea)}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        * asset class has no validated model edge; the number is just the base rate.
      </p>
    </Panel>
  );
}

export function driverText(idea: Forecast): string {
  const parts: string[] = [];
  const s = idea.signals;
  if (Math.abs(s.event ?? 0) > 0.3) parts.push(`events ${(s.event ?? 0) > 0 ? "▲" : "▼"}`);
  if (Math.abs(s.analog ?? 0) > 0.3) parts.push(`analogs ${(s.analog ?? 0) > 0 ? "▲" : "▼"}`);
  if (Math.abs(s.momentum ?? 0) > 1) parts.push(`momentum ${(s.momentum ?? 0) > 0 ? "▲" : "▼"}`);
  if (idea.news_flow) parts.push(`news ${idea.news_flow > 0 ? "▲" : "▼"}`);
  if (idea.recent_events.length) parts.push(humanize(idea.recent_events[0]));
  return parts.join(" · ") || "—";
}

function EventsPanel({ events }: { events: MarketEvent[] }) {
  const { go, openAsset } = useNav();
  return (
    <Panel
      title="Events that historically move markets"
      subtitle="Detected in the last 10 days, with what followed past occurrences (20 sessions)."
      actions={
        <button className="secondary-button" onClick={() => go("news")}>
          All events
        </button>
      }
    >
      {events.length === 0 ? (
        <Empty title="Quiet">No market-moving events detected in the last 10 days.</Empty>
      ) : (
        <ul className="space-y-2.5">
          {events.map((event) => (
            <li key={event.id} className="border-b border-border/50 pb-2 last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <EventBadge type={event.type} />
                <span className="text-xs text-muted-foreground">{shortDate(event.date)}</span>
              </div>
              <div className="mt-1 text-xs">{event.title}</div>
              {event.impact && (
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>
                    Past {event.impact.n}×, {event.impact_on?.split(":")[1]?.toUpperCase()} next
                    20d: avg{" "}
                    <span className={tone(event.impact.mean)}>{pct(event.impact.mean)}</span>, up{" "}
                    {pct(event.impact.hit_rate, 0, false)} of the time
                  </span>
                  <Reliability
                    t={event.impact.t_stat}
                    n={event.impact.n}
                    q={event.impact.q_value}
                    stable={event.impact.stable}
                    reliable={event.impact.reliable}
                  />
                </div>
              )}
              {event.most_affected && event.most_affected.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {event.most_affected.slice(0, 5).map((asset) => (
                    <button
                      key={asset.instrument_id}
                      onClick={() => openAsset(asset.instrument_id)}
                      className="rounded-lg border border-border px-1.5 py-0.5 text-xs hover:border-strong"
                      title={`edge ${pct(asset.edge)} · t=${asset.t_stat.toFixed(1)} · n=${asset.n}`}
                    >
                      {asset.symbol} <span className={tone(asset.edge)}>{pct(asset.edge, 1)}</span>
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function HeadlinesPanel({
  items,
  title = "Market-moving headlines",
}: {
  items: NewsItem[];
  title?: string;
}) {
  const { openAsset } = useNav();
  return (
    <Panel
      title={title}
      subtitle="Classified by the AI into event categories with measurable history."
    >
      {items.length === 0 ? (
        <Empty title="No classified headlines">
          Headlines are fetched every 30 minutes and classified by the fast LLM.
        </Empty>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <li key={item.id} className="border-b border-border/50 pb-2 last:border-0">
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                {item.category && item.category !== "other" && <EventBadge type={item.category} />}
                {item.direction ? (
                  <span className={tone(item.direction)}>
                    {item.direction > 0 ? "▲ bullish" : "▼ bearish"}
                  </span>
                ) : null}
                {item.magnitude ? <span>{"●".repeat(item.magnitude)}</span> : null}
                <span>
                  {item.source} · {ago(item.published_at)}
                </span>
              </div>
              <a
                href={item.url ?? undefined}
                target="_blank"
                rel="noreferrer"
                className="mt-0.5 block text-xs hover:text-bull"
              >
                {item.title}
              </a>
              {(item.affected.length > 0 || item.historical_analogs.length > 0) && (
                <div className="mt-1 flex flex-wrap gap-1 text-xs">
                  {item.affected.map((id) => (
                    <button
                      key={id}
                      className="rounded-lg border border-border px-1 hover:border-strong"
                      onClick={() => openAsset(id)}
                    >
                      {id.split(":")[1]?.toUpperCase()}
                    </button>
                  ))}
                  {item.historical_analogs.length > 0 && (
                    <span className="text-muted-foreground">
                      history: {item.historical_analogs.map(humanize).join(", ")}
                    </span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
