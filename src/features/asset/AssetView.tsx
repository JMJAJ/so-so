import { useQuery } from "@tanstack/react-query";
import { MessageSquare, Sparkles } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";

import { FanChart } from "@/features/charts/svg";
import { useChat } from "@/features/chat/chat-context";
import { RecCard } from "@/features/recs/RecCard";
import { HeadlinesPanel } from "@/features/today/TodayView";
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
  ZBar,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago, humanize, pct, price, shortDate, signed, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { SIGNALS, type AssetDetail, type Instrument } from "@/lib/types";
import { cn } from "@/lib/utils";

const CandleChart = lazy(() => import("@/features/charts/CandleChart"));

export default function AssetView() {
  const { params, openAsset } = useNav();
  const id = params.id;
  const [years, setYears] = useState(2);
  const detail = useQuery({
    queryKey: ["asset", id, years],
    queryFn: () => api.asset(id as string, years),
    enabled: Boolean(id),
    staleTime: 60_000,
  });

  return (
    <div className="space-y-4">
      <InstrumentPicker onPick={openAsset} current={id} />
      {!id ? (
        <Empty title="Pick an instrument">
          Search above, or click any asset in Today or the Screener.
        </Empty>
      ) : detail.isLoading ? (
        <Loading label="Computing evidence" />
      ) : detail.error ? (
        <ErrorNote error={detail.error} />
      ) : detail.data ? (
        <AssetBody data={detail.data} years={years} setYears={setYears} />
      ) : null}
    </div>
  );
}

function InstrumentPicker({ onPick, current }: { onPick: (id: string) => void; current?: string }) {
  const universe = useQuery({
    queryKey: ["universe"],
    queryFn: api.universe,
    staleTime: 3_600_000,
  });
  const [query, setQuery] = useState("");
  const matches = useMemo(() => {
    if (!query) return [];
    const q = query.toLowerCase();
    return (universe.data ?? [])
      .filter(
        (item: Instrument) =>
          item.symbol.toLowerCase().includes(q) ||
          item.name.toLowerCase().includes(q) ||
          item.id.includes(q),
      )
      .slice(0, 8);
  }, [query, universe.data]);
  return (
    <div className="relative max-w-md">
      <input
        className="terminal-input"
        placeholder={
          current
            ? `Viewing ${current} — search another…`
            : "Search 150 instruments: AAPL, gold, EUR/USD, bitcoin…"
        }
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && matches[0]) {
            onPick(matches[0].id);
            setQuery("");
          }
        }}
      />
      {matches.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full border border-border bg-card shadow-xl">
          {matches.map((item) => (
            <li key={item.id}>
              <button
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-accent/40"
                onClick={() => {
                  onPick(item.id);
                  setQuery("");
                }}
              >
                <span>
                  <span className="font-bold">{item.symbol}</span>{" "}
                  <span className="text-muted-foreground">{item.name}</span>
                </span>
                <Badge>{item.asset_class}</Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssetBody({
  data,
  years,
  setYears,
}: {
  data: AssetDetail;
  years: number;
  setYears: (years: number) => void;
}) {
  const [showMacro, setShowMacro] = useState(false);
  const { ask } = useChat();
  const item = data.instrument;
  const last = data.bars.at(-1);
  const prev = data.bars.at(-2);
  const quotePrice = data.quote?.price ?? last?.c ?? null;
  const change =
    data.quote?.change_pct != null
      ? data.quote.change_pct / 100
      : last && prev
        ? last.c / prev.c - 1
        : null;

  return (
    <>
      <PageHeading
        title={`${item.symbol} · ${item.name}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge>{item.asset_class}</Badge>
            {item.sector && <Badge>{item.sector}</Badge>}
            <span className="font-display text-lg font-bold text-foreground">
              {price(quotePrice)}
            </span>
            <span className={tone(change)}>{pct(change, 2)}</span>
            <span>
              {data.quote?.as_of
                ? `quote ${ago(data.quote.as_of)}${data.quote.stale ? " (stale)" : ""}`
                : ""}
            </span>
            {item.benchmark_id && (
              <span>· measured vs {item.benchmark_id.split(":")[1].toUpperCase()}</span>
            )}
          </span>
        }
        actions={
          <>
            <button
              className="secondary-button inline-flex items-center gap-1.5"
              onClick={() => ask(`/why ${item.symbol}`, true)}
            >
              <MessageSquare className="h-3 w-3" /> Ask AI why
            </button>
            {item.tradable && (
              <button
                className="primary-button inline-flex items-center gap-1.5"
                onClick={() => ask(`/recommend ${item.symbol}`, true)}
              >
                <Sparkles className="h-3 w-3" /> AI: recommend?
              </button>
            )}
          </>
        }
      />
      <Panel
        title="Price & events"
        subtitle="Arrows: this asset's earnings beats/misses. Amber dots (toggle): macro and market events. AI calls are marked on the day they were made."
        actions={[
          <button
            key="macro"
            className={cn(
              "secondary-button !px-2 !py-1",
              showMacro && "!border-primary !text-primary",
            )}
            onClick={() => setShowMacro((v) => !v)}
          >
            macro events
          </button>,
          ...[1, 2, 5, 10].map((value) => (
            <button
              key={value}
              className={cn(
                "secondary-button !px-2 !py-1",
                years === value && "!border-primary !text-primary",
              )}
              onClick={() => setYears(value)}
            >
              {value}y
            </button>
          )),
        ]}
        bodyClassName="p-2"
      >
        {data.bars.length ? (
          <Suspense fallback={<Loading />}>
            <CandleChart
              bars={data.bars}
              events={data.events}
              recommendations={data.recommendations}
              showMacro={showMacro}
            />
          </Suspense>
        ) : (
          <Empty title="No price history" />
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <ForecastPanel data={data} />
        <AnalogPanel data={data} />
      </div>
      <EventPanel data={data} />
      <div className="grid gap-4 xl:grid-cols-2">
        <CorrelationPanel data={data} />
        <HeadlinesPanel items={data.news} title={`${item.symbol} headlines (21 days)`} />
      </div>
      {data.recommendations.length > 0 && (
        <Panel title={`AI calls on ${item.symbol}`}>
          <div className="space-y-2">
            {data.recommendations.map((rec) => (
              <RecCard key={rec.id} rec={rec} compact />
            ))}
          </div>
        </Panel>
      )}
    </>
  );
}

function ForecastPanel({ data }: { data: AssetDetail }) {
  const f = data.forecast;
  const t = data.technicals ?? {};
  return (
    <Panel
      title="Quant forecast · next 20 sessions"
      subtitle={
        f?.model_has_edge
          ? "Model validated walk-forward for this asset class."
          : "No validated model edge for this asset class: the forecast is the historical base rate. Weigh the event and analog evidence instead."
      }
    >
      {!f ? (
        <Empty title="No forecast" />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label="Expected"
              value={pct(f.expected_return)}
              valueClassName={tone(f.expected_return)}
            />
            <Stat label="P(up)" value={pct(f.prob_up, 0, false)} />
            <Stat label="1σ move" value={pct(f.sigma, 1, false)} />
            <Stat
              label="Model edge"
              value={f.model_has_edge ? "yes" : "no"}
              valueClassName={f.model_has_edge ? "text-bull" : "text-muted-foreground"}
            />
          </div>
          <div className="space-y-1.5">
            {SIGNALS.map((name) => (
              <div key={name} className="flex items-center gap-3 text-[11px]">
                <span className="w-20 uppercase tracking-wider text-muted-foreground">{name}</span>
                <ZBar value={f.signals[name]} />
                <span className="w-12 text-right tabular-nums">{signed(f.signals[name])}</span>
                {f.contributions[name] != null && (
                  <span className="text-[10px] text-muted-foreground">
                    contrib {pct(f.contributions[name], 2)}
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2 border-t border-border pt-3 text-[11px] sm:grid-cols-6">
            {[
              ["5d", pct(t.ret_5d)],
              ["20d", pct(t.ret_20d)],
              ["60d", pct(t.ret_60d)],
              ["RSI", t.rsi_14 != null ? t.rsi_14.toFixed(0) : "—"],
              ["vs 200d", pct(t.dist_sma200)],
              ["from high", pct(t.dist_high_252)],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">
                  {label}
                </div>
                <div className="tabular-nums">{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

function AnalogPanel({ data }: { data: AssetDetail }) {
  const a = data.analogs;
  return (
    <Panel
      title="Historical analogs"
      subtitle="The 20 past dates whose asset + macro state looked most like today, and what this asset did next."
    >
      {!a || !a.fan ? (
        <Empty title="Not enough history" />
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat
              label={`Mean ${a.horizon}d`}
              value={pct(a.mean_return)}
              valueClassName={tone(a.mean_return)}
            />
            <Stat
              label="Median"
              value={pct(a.median_return)}
              valueClassName={tone(a.median_return)}
            />
            <Stat label="Up share" value={pct(a.hit_rate, 0, false)} />
            <Stat
              label="Dispersion"
              value={pct(a.dispersion, 1, false)}
              hint={a.mean_excess != null ? `excess ${pct(a.mean_excess)}` : undefined}
            />
          </div>
          <FanChart fan={a.fan} horizon={a.horizon} />
          <details className="text-[11px]">
            <summary className="cursor-pointer text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
              Analog dates
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {a.analogs.map((row) => (
                <span key={row.date} className="border border-border px-1.5 py-0.5 tabular-nums">
                  {row.date} <span className={tone(row.fwd_return)}>{pct(row.fwd_return)}</span>
                </span>
              ))}
            </div>
          </details>
        </div>
      )}
    </Panel>
  );
}

function EventPanel({ data }: { data: AssetDetail }) {
  const [selected, setSelected] = useState<string | null>(null);
  const effects = data.event_effects;
  const study = useQuery({
    queryKey: ["event-study", data.instrument.id, selected],
    queryFn: () => api.eventStudy(data.instrument.id, selected as string),
    enabled: Boolean(selected),
  });
  return (
    <Panel
      title="What events did to this asset before"
      subtitle="Returns after the reaction-day close (what you could have captured after the news), vs the asset's normal return over the same period. |t| < 2 is noise."
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
            Live: events in the last 10 days
          </h3>
          {effects.active_events_last_10d.length === 0 ? (
            <Empty title="None" />
          ) : (
            <ul className="space-y-2">
              {effects.active_events_last_10d.map((event) => (
                <li key={`${event.type}-${event.date}`} className="border-b border-border/50 pb-2">
                  <button
                    className="flex flex-wrap items-center gap-2 text-left"
                    onClick={() => setSelected(event.type)}
                  >
                    <EventBadge type={event.type} />
                    <span className="text-[10px] text-muted-foreground">
                      {shortDate(event.date)}
                    </span>
                  </button>
                  <div className="mt-0.5 text-xs">{event.title}</div>
                  {event.history ? (
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                      <span>
                        next 20d avg{" "}
                        <span className={tone(event.history.mean)}>{pct(event.history.mean)}</span>{" "}
                        (edge{" "}
                        <span className={tone(event.history.edge)}>{pct(event.history.edge)}</span>
                        ), up {pct(event.history.hit_rate, 0, false)}, n={event.history.n}
                        {event.pooled ? " · pooled across asset class" : ""}
                      </span>
                      <Reliability t={event.history.t_stat} n={event.history.n} />
                    </div>
                  ) : (
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      No reliable history for this asset.
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
            Most reliable event effects (20 sessions)
          </h3>
          {effects.most_reliable_event_effects.length === 0 ? (
            <Empty title="No event type passes |t| ≥ 2">
              Nothing in the event history moves this asset reliably.
            </Empty>
          ) : (
            <TableWrap>
              <thead>
                <tr>
                  <Th>Event</Th>
                  <Th right>n</Th>
                  <Th right>Avg</Th>
                  <Th right>Edge</Th>
                  <Th right>Up</Th>
                  <Th right>t</Th>
                </tr>
              </thead>
              <tbody>
                {effects.most_reliable_event_effects.map((row) => (
                  <tr
                    key={row.event_type}
                    className={cn(
                      "cursor-pointer hover:bg-accent/30",
                      selected === row.event_type && "bg-accent/40",
                    )}
                    onClick={() => setSelected(row.event_type)}
                  >
                    <Td className="max-w-[200px] truncate">{humanize(row.event_type)}</Td>
                    <Td right>{row.n}</Td>
                    <Td right className={tone(row.mean)}>
                      {pct(row.mean)}
                    </Td>
                    <Td right className={tone(row.edge)}>
                      {pct(row.edge)}
                    </Td>
                    <Td right>{pct(row.hit_rate, 0, false)}</Td>
                    <Td right>{row.t_stat.toFixed(1)}</Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
        </div>
      </div>
      {selected && (
        <div className="mt-4 border-t border-border pt-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-[10px] font-bold uppercase tracking-[0.15em] text-primary">
              Every past {humanize(selected)} → {data.instrument.symbol}{" "}
              {study.data?.measure ? `(${study.data.measure})` : ""}
            </h3>
            <button className="secondary-button !py-1" onClick={() => setSelected(null)}>
              Close
            </button>
          </div>
          {study.isLoading ? (
            <Loading />
          ) : study.data ? (
            <>
              {study.data.impact && (
                <div className="mb-3 flex flex-wrap gap-2 text-[10px]">
                  {Object.entries(study.data.impact.horizons).map(([h, stats]) => (
                    <span key={h} className="border border-border px-2 py-1">
                      {h === "0" ? "reaction day" : `${h}d`}:{" "}
                      <span className={tone(stats.mean)}>{pct(stats.mean)}</span> · edge{" "}
                      <span className={tone(stats.edge)}>{pct(stats.edge)}</span> · t{" "}
                      {stats.t_stat.toFixed(1)} · n {stats.n}
                    </span>
                  ))}
                </div>
              )}
              <TableWrap>
                <thead>
                  <tr>
                    <Th>Date</Th>
                    <Th>Event</Th>
                    <Th right>Day 0</Th>
                    <Th right>5d</Th>
                    <Th right>10d</Th>
                    <Th right>20d</Th>
                    <Th right>40d</Th>
                  </tr>
                </thead>
                <tbody>
                  {study.data.rows.map((row) => (
                    <tr key={`${row.date}-${row.title}`}>
                      <Td>{row.date}</Td>
                      <Td className="max-w-[320px] truncate text-[11px]">{row.title}</Td>
                      {["r0", "r5", "r10", "r20", "r40"].map((key) => (
                        <Td key={key} right className={tone(row[key] as number | null)}>
                          {pct(row[key] as number | null)}
                        </Td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            </>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

function CorrelationPanel({ data }: { data: AssetDetail }) {
  const { openAsset } = useNav();
  const { peers, lead_lag } = data.correlations;
  return (
    <Panel
      title="Co-movement & drivers"
      subtitle="1-year daily correlations, plus drivers whose weekly change has predicted this asset's next 20 sessions (non-overlapping, significant only)."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {(["positive", "negative"] as const).map((side) => (
          <div key={side}>
            <h3 className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
              {side === "positive" ? "Moves with" : "Moves against"}
            </h3>
            <ul className="space-y-1">
              {peers[side].slice(0, 6).map((peer) => (
                <li key={peer.instrument_id} className="flex items-center justify-between text-xs">
                  <button
                    className="hover:text-primary"
                    onClick={() => openAsset(peer.instrument_id)}
                  >
                    {peer.symbol}
                  </button>
                  <span className="tabular-nums text-muted-foreground">
                    {peer.corr_1y.toFixed(2)}
                    {peer.corr_60d != null && (
                      <span className="ml-2 text-[10px]">60d {peer.corr_60d.toFixed(2)}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <h3 className="mb-1.5 mt-4 text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
        Lead-lag drivers
      </h3>
      {lead_lag.length === 0 ? (
        <div className="text-xs text-muted-foreground">
          No driver passes the significance threshold.
        </div>
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>Driver</Th>
              <Th right>Corr</Th>
              <Th right>n</Th>
              <Th right>Now (z)</Th>
              <Th>Implies</Th>
            </tr>
          </thead>
          <tbody>
            {lead_lag.map((row) => (
              <tr key={row.driver}>
                <Td>{row.name}</Td>
                <Td right className={tone(row.corr)}>
                  {row.corr.toFixed(2)}
                </Td>
                <Td right>{row.n}</Td>
                <Td right>{row.latest_z != null ? signed(row.latest_z, 1) : "—"}</Td>
                <Td className={tone(row.implied_direction)}>
                  {row.implied_direction > 0
                    ? "▲ up"
                    : row.implied_direction < 0
                      ? "▼ down"
                      : "neutral"}
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Panel>
  );
}
