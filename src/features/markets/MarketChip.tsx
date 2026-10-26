import { Badge } from "@/features/shell/ui";
import { useNav } from "@/lib/nav";
import type { MarketStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  changeText,
  dateKey,
  liveState,
  rangeText,
  tradingDay,
  useMarkets,
  useNow,
} from "./market-time";

function phaseLabel(
  market: MarketStatus,
  now: number,
): { text: string; tone: "bull" | "amber" | "neutral" } {
  const { open, extended, next } = liveState(market, now);
  if (open) return { text: "open", tone: "bull" };
  const opensToday = next !== undefined && dateKey(next[0], market.tz) === dateKey(now, market.tz);
  if (extended) return { text: opensToday ? "pre-market" : "after-hours", tone: "amber" };
  if (market.phase === "lunch break") return { text: "lunch break", tone: "amber" };
  return { text: "closed", tone: "neutral" };
}

export function MarketPhase({ market, now }: { market: MarketStatus; now: number }) {
  const phase = phaseLabel(market, now);
  return <Badge tone={phase.tone}>{phase.text}</Badge>;
}

/** One market's state: name, open/closed, countdown, and (in `detail`) its hours in both time zones. */
export function MarketChip({
  marketId,
  detail = false,
  className,
}: {
  marketId: string | undefined;
  detail?: boolean;
  className?: string;
}) {
  const markets = useMarkets();
  const now = useNow();
  const { go } = useNav();
  const market = markets.data?.markets.find((m) => m.id === marketId);
  if (!market) return null;
  const { current, next } = liveState(market, now);
  const day = tradingDay(market, current ?? next);
  const roundTheClock = market.kind !== "exchange";
  return (
    <button
      onClick={() => go("markets")}
      title="Global market hours"
      className={cn(
        "inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-left text-xs text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      <span className="font-bold text-foreground">{market.name}</span>
      <MarketPhase market={market} now={now} />
      <span>{changeText(market, now)}</span>
      {detail && !roundTheClock && day.length > 0 && (
        <span>
          · {current ? "today" : "next"} {rangeText(day, market.tz)} {market.tz_abbr} ={" "}
          <span className="text-foreground">{rangeText(day)}</span> your time
        </span>
      )}
      {detail && roundTheClock && market.note && <span>· {market.note}</span>}
    </button>
  );
}
