import { useMemo, useState } from "react";

import {
  Empty,
  ErrorNote,
  Loading,
  PageHeading,
  Panel,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import type { MarketStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { MarketPhase } from "./MarketChip";
import {
  changeText,
  clock,
  LOCAL_TZ,
  liveState,
  MARKET_ORDER,
  rangeText,
  spans,
  tradingDay,
  tzAbbr,
  useMarkets,
  useNow,
} from "./market-time";

const HOUR = 3_600_000;
const SLOT = 15 * 60_000;
const TRADES_HERE: Record<string, string> = {
  nyse: "US stocks & ETFs",
  forex: "FX pairs",
  cme: "Commodities",
  crypto: "Crypto",
};

function localMidnight(now: number, offsetDays: number): number {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + offsetDays);
  return d.getTime();
}

export default function MarketsView() {
  const markets = useMarkets();
  const now = useNow(15_000);
  const [offset, setOffset] = useState(0);

  const ordered = useMemo(() => {
    const list = markets.data?.markets ?? [];
    return [...list].sort((a, b) => MARKET_ORDER.indexOf(a.id) - MARKET_ORDER.indexOf(b.id));
  }, [markets.data]);

  if (markets.isLoading) return <Loading />;
  if (markets.error) return <ErrorNote error={markets.error} />;
  if (!ordered.length) return <Empty title="No market data" />;

  const start = localMidnight(now, offset);
  const end = localMidnight(now, offset + 1);
  const nyse = ordered.find((m) => m.id === "nyse");

  return (
    <div className="space-y-4">
      <PageHeading
        title="Market hours"
        subtitle={
          <>
            When each market trades, in its own time and yours ({LOCAL_TZ}, {tzAbbr(now)} — now{" "}
            <span className="text-foreground">{clock(now)}</span>). Daylight saving is applied per
            market. US holidays and early closes are included; other exchanges' holidays are not
            (marked *).
          </>
        }
      />

      <Panel
        title="24 hours, your time"
        subtitle="Solid bars are regular sessions, faint bars US pre-market and after-hours. The bottom strip counts how many stock exchanges are open at once."
        actions={[
          ["Yesterday", -1],
          ["Today", 0],
          ["Tomorrow", 1],
        ].map(([label, value]) => (
          <button
            key={label}
            className={cn(
              "secondary-button !px-2 !py-1",
              offset === value && "!border-strong !bg-accent !text-foreground",
            )}
            onClick={() => setOffset(value as number)}
          >
            {label}
          </button>
        ))}
      >
        <Timeline markets={ordered} start={start} end={end} now={now} />
      </Panel>

      <Panel title="Every market" bodyClassName="p-0">
        <TableWrap>
          <thead>
            <tr>
              <Th>Market</Th>
              <Th>Their time</Th>
              <Th>Status</Th>
              <Th>Hours, their time</Th>
              <Th>Hours, your time</Th>
              <Th>Next change</Th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((m) => {
              const { current, next } = liveState(m, now);
              const day = tradingDay(m, current ?? next);
              const allDay = m.kind !== "exchange";
              return (
                <tr key={m.id}>
                  <Td>
                    <div className="font-bold">
                      {m.name}
                      {!m.holidays_known && <span className="text-muted-foreground">*</span>}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {TRADES_HERE[m.id] ? `NEXUS: ${TRADES_HERE[m.id]}` : m.city}
                    </div>
                  </Td>
                  <Td>
                    {clock(now, m.tz)}{" "}
                    <span className="text-muted-foreground">
                      {new Intl.DateTimeFormat(undefined, {
                        timeZone: m.tz,
                        weekday: "short",
                      }).format(now)}{" "}
                      {tzAbbr(now, m.tz)}
                    </span>
                  </Td>
                  <Td>
                    <MarketPhase market={m} now={now} />
                  </Td>
                  <Td>
                    {allDay ? (
                      <span className="block max-w-[260px] whitespace-normal text-muted-foreground">
                        {m.note || "24/7"}
                      </span>
                    ) : (
                      <>
                        {rangeText(day, m.tz)}{" "}
                        <span className="text-muted-foreground">
                          {tzAbbr(day[0]?.[0] ?? now, m.tz)}
                        </span>
                      </>
                    )}
                  </Td>
                  <Td>{allDay ? "—" : rangeText(day)}</Td>
                  <Td>{changeText(m, now)}</Td>
                </tr>
              );
            })}
          </tbody>
        </TableWrap>
      </Panel>

      {nyse && <Overlaps markets={ordered} anchor={nyse} start={start} end={end} />}
    </div>
  );
}

function clip([a, b]: [number, number], start: number, end: number): [number, number] | null {
  const lo = Math.max(a, start);
  const hi = Math.min(b, end);
  return hi > lo ? [lo, hi] : null;
}

function Timeline({
  markets,
  start,
  end,
  now,
}: {
  markets: MarketStatus[];
  start: number;
  end: number;
  now: number;
}) {
  const width = end - start;
  const pos = (t: number) => `${((t - start) / width) * 100}%`;
  const size = (a: number, b: number) => `${((b - a) / width) * 100}%`;
  const hours = Array.from({ length: Math.round(width / HOUR) + 1 }, (_, i) => start + i * HOUR);
  const exchanges = markets.filter((m) => m.kind === "exchange");
  const slots = Array.from({ length: Math.ceil(width / SLOT) }, (_, i) => {
    const t = start + i * SLOT + SLOT / 2;
    return exchanges.filter((m) => spans(m.intervals).some(([a, b]) => a <= t && t < b)).length;
  });
  const peak = Math.max(1, ...slots);
  const showNow = now >= start && now < end;

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[720px]">
        <div className="relative ml-40 h-5 text-[11px] text-muted-foreground">
          {hours
            .filter((_, i) => i % 3 === 0 && i < hours.length - 1)
            .map((t) => (
              <span key={t} className="absolute -translate-x-1/2" style={{ left: pos(t) }}>
                {clock(t)}
              </span>
            ))}
        </div>
        <div className="relative">
          {markets.map((m) => {
            const regular = spans(m.intervals)
              .map((s) => clip(s, start, end))
              .filter(Boolean) as Array<[number, number]>;
            const extended = spans(m.extended_intervals)
              .map((s) => clip(s, start, end))
              .filter(Boolean) as Array<[number, number]>;
            return (
              <div key={m.id} className="flex h-7 items-center border-t border-border/50">
                <div className="w-40 shrink-0 truncate pr-2 text-xs font-bold ">{m.name}</div>
                <div className="relative h-4 flex-1 bg-accent/10">
                  {extended.map(([a, b]) => (
                    <div
                      key={`x${a}`}
                      className="absolute inset-y-1 bg-bull/15"
                      style={{ left: pos(a), width: size(a, b) }}
                    />
                  ))}
                  {regular.map(([a, b]) => (
                    <div
                      key={a}
                      title={`${clock(a)}–${clock(b)} your time · ${clock(a, m.tz)}–${clock(b, m.tz)} ${tzAbbr(a, m.tz)}`}
                      className={cn(
                        "absolute inset-y-0",
                        m.kind === "exchange" ? "bg-bull/60" : "bg-bull/25",
                      )}
                      style={{ left: pos(a), width: size(a, b) }}
                    />
                  ))}
                </div>
              </div>
            );
          })}
          <div className="flex h-7 items-center border-t border-border">
            <div className="w-40 shrink-0 pr-2 text-xs text-muted-foreground">Exchanges open</div>
            <div className="relative flex h-4 flex-1">
              {slots.map((count, i) => (
                <div
                  key={i}
                  className="h-full flex-1 bg-primary"
                  style={{ opacity: count ? 0.15 + 0.85 * (count / peak) : 0.04 }}
                  title={`${clock(start + i * SLOT)}: ${count} open`}
                />
              ))}
            </div>
          </div>
          {showNow && (
            <div className="pointer-events-none absolute inset-y-0 left-40 right-0">
              <div className="absolute inset-y-0 w-px bg-primary" style={{ left: pos(now) }}>
                <span className="absolute -top-1 left-1 bg-background px-1 text-[11px] font-bold text-foreground">
                  now
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Overlaps({
  markets,
  anchor,
  start,
  end,
}: {
  markets: MarketStatus[];
  anchor: MarketStatus;
  start: number;
  end: number;
}) {
  const anchorSpans = spans(anchor.intervals);
  const rows = markets
    .filter((m) => m.id !== anchor.id && m.kind === "exchange")
    .map((m) => {
      const shared: Array<[number, number]> = [];
      for (const s of spans(m.intervals)) {
        for (const t of anchorSpans) {
          const both = clip([Math.max(s[0], t[0]), Math.min(s[1], t[1])], start, end);
          if (both) shared.push(both);
        }
      }
      return { market: m, shared };
    });
  return (
    <Panel
      title={`Overlap with ${anchor.name}`}
      subtitle="Hours when both are trading on the selected day, your time. News from one market moves the other most in these windows."
    >
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(({ market, shared }) => (
          <div
            key={market.id}
            className="rounded-lg flex items-baseline justify-between gap-2 border border-border px-3 py-2 text-[11px]"
          >
            <span className="font-bold">{market.name}</span>
            <span className={shared.length ? "text-foreground" : "text-muted-foreground"}>
              {shared.length ? rangeText(shared) : "no overlap"}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
