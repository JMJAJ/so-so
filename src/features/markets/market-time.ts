import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { MarketStatus } from "@/lib/types";

/** East-to-west by opening time, then the round-the-clock markets. */
export const MARKET_ORDER = [
  "asx",
  "tse",
  "hkex",
  "sse",
  "nse",
  "xetra",
  "euronext",
  "lse",
  "nyse",
  "tsx",
  "forex",
  "cme",
  "crypto",
];

export const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function useMarkets() {
  return useQuery({ queryKey: ["markets"], queryFn: api.markets, refetchInterval: 60_000 });
}

/** Current time, re-rendering every `ms`. */
export function useNow(ms = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

type Span = [number, number];

export function spans(pairs: Array<[string, string]>): Span[] {
  return pairs.map(([a, b]) => [Date.parse(a), Date.parse(b)]);
}

/** Live state from the session intervals, so countdowns stay right between refetches. */
export function liveState(market: MarketStatus, now: number) {
  const regular = spans(market.intervals);
  const current = regular.find(([a, b]) => a <= now && now < b);
  const next = regular.find(([a]) => a > now);
  const extended = spans(market.extended_intervals).some(([a, b]) => a <= now && now < b);
  return { open: Boolean(current), current, next, extended };
}

/** All regular sessions on the market's local trading day of `ref` (two for lunch-break markets). */
export function tradingDay(market: MarketStatus, ref: Span | undefined): Span[] {
  if (!ref) return [];
  const day = (t: number) => dateKey(t, market.tz);
  const key = day(ref[0]);
  return spans(market.intervals).filter(([a]) => day(a) === key);
}

export function dateKey(t: number, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, dateStyle: "short" }).format(t);
}

export function clock(t: number, timeZone?: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(t);
}

/** "15:30", or "Thu 15:30" when it isn't today in that time zone. */
export function clockWithDay(t: number, now: number, timeZone?: string): string {
  const time = clock(t, timeZone);
  if (dateKey(t, timeZone) === dateKey(now, timeZone)) return time;
  const day = new Intl.DateTimeFormat(undefined, { timeZone, weekday: "short" }).format(t);
  return `${day} ${time}`;
}

export function rangeText(day: Span[], timeZone?: string): string {
  return day.map(([a, b]) => `${clock(a, timeZone)}–${clock(b, timeZone)}`).join(", ");
}

export function tzAbbr(t: number, timeZone?: string): string {
  const part = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" })
    .formatToParts(t)
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? "";
}

export function countdown(ms: number): string {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  const d = Math.floor(minutes / 1440);
  const h = Math.floor((minutes % 1440) / 60);
  const m = minutes % 60;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}m`;
}

/** "closes in 2h 05m" / "opens in 3h 10m (15:30)". */
export function changeText(market: MarketStatus, now: number): string {
  const { current, next } = liveState(market, now);
  if (current) {
    if (market.kind === "crypto") return "never closes";
    return `closes in ${countdown(current[1] - now)}`;
  }
  return next ? `opens in ${countdown(next[0] - now)} (${clockWithDay(next[0], now)})` : "closed";
}
