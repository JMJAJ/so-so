import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { MessageSquare, Sparkles, Star } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";

import { FanChart } from "@/features/charts/svg";
import { useChat } from "@/features/chat/chat-context";
import { AiCallCard, EvidenceSteps } from "@/features/recs/AiCallCard";
import { RecCard } from "@/features/recs/RecCard";
import { AssetSimulationPanel } from "@/features/sim/SimPanels";
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
import { MarketChip } from "@/features/markets/MarketChip";
import { api } from "@/lib/api";
import { ago, humanize, pct, price, shortDate, signed, tone } from "@/lib/format";
import { useWatchlist } from "@/lib/watchlist";
import { useNav } from "@/lib/nav";
import { SIGNALS, type AssetDetail, type Instrument, type IntradaySpan } from "@/lib/types";
import { cn } from "@/lib/utils";

const CandleChart = lazy(() => import("@/features/charts/CandleChart"));
const IntradayChart = lazy(() => import("@/features/charts/IntradayChart"));
const SPANS: Array<[IntradaySpan, string]> = [
  ["1d", "1D"],
  ["5d", "5D"],
  ["1mo", "1M"],
];

export default function AssetView() {
  const { params, openAsset } = useNav();
  const id = params.id;
  const [years, setYears] = useState(2);
  const detail = useQuery({
    queryKey: ["asset", id, years],
    queryFn: () => api.asset(id as string, years),
    enabled: Boolean(id),
    staleTime: 60_000,
    // A range change keeps the page up; a different asset still shows the loader.
    placeholderData: (previous) =>
      previous && previous.instrument.id === id ? keepPreviousData(previous) : undefined,
    // Right after a restart the forecast scan runs in the background: check back soon for it
    // (for two minutes only, since research-only indices never get one).
    refetchInterval: (query) =>
      query.state.data && !query.state.data.forecast && query.state.dataUpdateCount < 12
        ? 10_000
        : 60_000,
  });

  return (
    <div className="space-y-5">
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
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-xl border border-border bg-popover">
          {matches.map((item) => (
            <li key={item.id}>
              <button
                className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm hover:bg-accent"
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
  const [span, setSpan] = useState<IntradaySpan | null>(item.tradable ? "1d" : null);
  const last = data.bars.at(-1);
  const prev = data.bars.at(-2);
  const quotePrice = data.quote?.price ?? last?.c ?? null;
  // Change today comes from the live quote (previous close from Yahoo when our bars lag).
  // Two stored bars are only a stand-in when there is no quote at all; otherwise their
  // difference could be weeks old and labelled as today.
  const change =
    data.quote?.change_pct != null
      ? data.quote.change_pct / 100
      : data.quote?.price == null && last && prev
        ? last.c / prev.c - 1
        : null;
  const barDay = last?.t?.slice(0, 10);
  const quoteDay = data.quote?.as_of?.slice(0, 10);
  const barIsOld = Boolean(barDay && quoteDay && barDay < quoteDay);

  const openCall = data.recommendations.find((rec) => rec.status === "open");
  const ranges: Array<{ key: string; label: string; active: boolean; pick: () => void }> = [
    ...SPANS.map(([value, label]) => ({
      key: value,
      label,
      active: span === value,
      pick: () => setSpan(value),
    })),
    ...[1, 2, 5, 10].map((value) => ({
      key: `${value}y`,
      label: `${value}Y`,
      active: !span && years === value,
      pick: () => {
        setSpan(null);
        setYears(value);
      },
    })),
  ];

  return (
    <>
      <div className="flex flex-wrap items-start gap-3">
        <div className="mr-auto min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold leading-tight tracking-tight">
              {item.symbol} <span className="font-normal text-muted-foreground">{item.name}</span>
            </h1>
            <WatchStar id={item.id} />
            <Badge>{item.asset_class}</Badge>
            {item.sector && <Badge>{item.sector}</Badge>}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            {item.benchmark_id
              ? `Measured against ${item.benchmark_id.split(":")[1].toUpperCase()}`
              : "Its own benchmark"}
          </div>
        </div>
        <button className="secondary-button" onClick={() => ask(`/why ${item.symbol}`, true)}>
          <MessageSquare className="h-4 w-4" /> Ask AI why
        </button>
        {item.tradable && (
          <button className="primary-button" onClick={() => ask(`/recommend ${item.symbol}`, true)}>
            <Sparkles className="h-4 w-4" /> AI: recommend?
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-[40px] font-semibold leading-none">
            {price(quotePrice)}
          </span>
          <span className={cn("font-mono text-[15px] font-semibold", tone(change))}>
            {pct(change, 2)}
          </span>
        </div>
        {last && (
          <div
            className="flex gap-4 pb-1 font-mono text-[13px] text-muted-foreground"
            title={
              barIsOld
                ? "Last stored daily bar; today's bar arrives after the daily refresh"
                : "Daily bar"
            }
          >
            {barIsOld && <span className="font-sans">{barDay}</span>}
            <span>
              O <span className="text-foreground">{price(last.o)}</span>
            </span>
            <span>
              H <span className="text-foreground">{price(last.h)}</span>
            </span>
            <span>
              L <span className="text-foreground">{price(last.l)}</span>
            </span>
            <span>
              C <span className="text-foreground">{price(last.c)}</span>
            </span>
          </div>
        )}
        <span className="pb-1 text-xs text-muted-foreground">
          {data.quote?.as_of
            ? `Quote ${ago(data.quote.as_of)}${data.quote.stale ? " (stale)" : ""}`
            : ""}
        </span>
        {item.tradable && <MarketChip marketId={item.market} detail className="pb-1" />}
      </div>

      {/* Columns size to their own content (no stretching), so the chart panel never grows
          empty space to match the taller right column; the simulation fills the left one. */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px] xl:items-start">
        <div className="flex min-w-0 flex-col gap-4">
          <Panel
            title={span ? "Live price" : "Price & events"}
            subtitle={
              span
                ? "Intraday candles in your time, pre- and after-market included. Dashed lines: the open AI call's entry, stop and target."
                : "Arrows: this asset's earnings beats and misses. Dots (toggle): macro and market events. AI calls are marked on the day they were made."
            }
            actions={
              <>
                {!span && (
                  <button
                    className={cn(
                      "secondary-button !min-h-9",
                      showMacro && "!border-bull-line !text-bull",
                    )}
                    onClick={() => setShowMacro((v) => !v)}
                  >
                    Macro events
                  </button>
                )}
                <div
                  role="tablist"
                  aria-label="Chart range"
                  className="flex gap-0.5 rounded-xl border border-border bg-input p-1"
                >
                  {ranges.map((range) => (
                    <button
                      key={range.key}
                      role="tab"
                      aria-selected={range.active}
                      onClick={range.pick}
                      className={cn(
                        "min-h-8 rounded-lg px-2.5 text-xs font-semibold",
                        range.active
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {range.label}
                    </button>
                  ))}
                </div>
              </>
            }
            bodyClassName="p-3"
          >
            {span ? (
              <Suspense fallback={<Loading />}>
                <IntradayChart
                  instrumentId={item.id}
                  span={span}
                  recommendations={data.recommendations}
                />
              </Suspense>
            ) : data.bars.length ? (
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
          <AssetSimulationPanel instrumentId={item.id} symbol={item.symbol} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {item.tradable && <AiCallCard rec={openCall} symbol={item.symbol} />}
          {openCall && <EvidenceSteps rec={openCall} />}
          <ForecastPanel data={data} />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <AnalogPanel data={data} />
        <CorrelationPanel data={data} />
      </div>
      <EventPanel data={data} />
      <HeadlinesPanel items={data.news} title={`${item.symbol} headlines (21 days)`} />
      {data.recommendations.length > 0 && (
        <Panel title={`All AI calls on ${item.symbol}`}>
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
                <span className="w-20 text-muted-foreground">{name}</span>
                <ZBar value={f.signals[name]} />
                <span className="w-12 text-right tabular-nums">{signed(f.signals[name])}</span>
                {f.contributions[name] != null && (
                  <span className="text-xs text-muted-foreground">
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
                <div className="text-[11px] text-muted-foreground">{label}</div>
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
            <summary className="cursor-pointer text-xs text-muted-foreground">Analog dates</summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {a.analogs.map((row) => (
                <span
                  key={row.date}
                  className="rounded-lg border border-border px-1.5 py-0.5 tabular-nums"
                >
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
          <h3 className="mb-2 text-xs font-bold text-muted-foreground">
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
                    <span className="text-xs text-muted-foreground">{shortDate(event.date)}</span>
                  </button>
                  <div className="mt-0.5 text-xs">{event.title}</div>
                  {event.history ? (
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>
                        next 20d avg{" "}
                        <span className={tone(event.history.mean)}>{pct(event.history.mean)}</span>{" "}
                        (edge{" "}
                        <span className={tone(event.history.edge)}>{pct(event.history.edge)}</span>
                        ), up {pct(event.history.hit_rate, 0, false)}, n={event.history.n}
                        {event.pooled ? " · pooled across asset class" : ""}
                      </span>
                      <Reliability
                        t={event.history.t_stat}
                        n={event.history.n}
                        q={event.history.q_value}
                        stable={event.history.stable}
                        reliable={event.history.reliable}
                      />
                    </div>
                  ) : (
                    <div className="mt-1 text-xs text-muted-foreground">
                      No reliable history for this asset.
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-xs font-bold text-muted-foreground">
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
            <h3 className="text-xs font-bold text-foreground">
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
                <div className="mb-3 flex flex-wrap gap-2 text-xs">
                  {Object.entries(study.data.impact.horizons).map(([h, stats]) => (
                    <span key={h} className="rounded-lg border border-border px-2 py-1">
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
            <h3 className="mb-1.5 text-xs font-bold text-muted-foreground">
              {side === "positive" ? "Moves with" : "Moves against"}
            </h3>
            <ul className="space-y-1">
              {peers[side].slice(0, 6).map((peer) => (
                <li key={peer.instrument_id} className="flex items-center justify-between text-xs">
                  <button className="hover:text-bull" onClick={() => openAsset(peer.instrument_id)}>
                    {peer.symbol}
                  </button>
                  <span className="tabular-nums text-muted-foreground">
                    {peer.corr_1y.toFixed(2)}
                    {peer.corr_60d != null && (
                      <span className="ml-2 text-xs">60d {peer.corr_60d.toFixed(2)}</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <h3 className="mb-1.5 mt-4 text-xs font-bold text-muted-foreground">Lead-lag drivers</h3>
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

function WatchStar({ id }: { id: string }) {
  const { has, toggle } = useWatchlist();
  const on = has(id);
  return (
    <button
      className={cn("icon-button !min-h-8 !min-w-8 !p-1.5", on && "!text-amber")}
      onClick={() => toggle(id)}
      aria-pressed={on}
      title={on ? "Remove from watchlist" : "Add to watchlist"}
    >
      <Star className={cn("h-4 w-4", on && "fill-current")} />
    </button>
  );
}
