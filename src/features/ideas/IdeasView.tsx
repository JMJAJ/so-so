import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { driverText } from "@/features/today/TodayView";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeading,
  Panel,
  Td,
  Th,
  TableWrap,
  ZBar,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { pct, price, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { SIGNALS, type Forecast, type SignalName } from "@/lib/types";
import { cn } from "@/lib/utils";

type SortKey = "interest" | "expected_return" | "prob_up" | SignalName | "news_flow";
const CLASSES = ["all", "stock", "etf", "crypto", "forex", "commodity"] as const;

function interest(row: Forecast): number {
  const news = 0.15 * Math.abs(row.news_flow || 0);
  if (row.model_has_edge) return Math.abs(row.score ?? 0) + news;
  return 0.5 * (Math.abs(row.signals.analog ?? 0) + Math.abs(row.signals.event ?? 0)) + news;
}

export default function IdeasView() {
  const { openAsset } = useNav();
  const [assetClass, setAssetClass] = useState<(typeof CLASSES)[number]>("all");
  const [direction, setDirection] = useState<"both" | "long" | "short">("both");
  const [sort, setSort] = useState<SortKey>("interest");
  const [query, setQuery] = useState("");
  const forecasts = useQuery({
    queryKey: ["forecasts"],
    queryFn: () => api.forecasts(),
    refetchInterval: 300_000,
  });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });

  const rows = useMemo(() => {
    let list = forecasts.data ?? [];
    if (assetClass !== "all") list = list.filter((row) => row.asset_class === assetClass);
    if (direction === "long") list = list.filter((row) => (row.expected_return ?? 0) > 0);
    if (direction === "short") list = list.filter((row) => (row.expected_return ?? 0) < 0);
    if (query) {
      const q = query.toLowerCase();
      list = list.filter(
        (row) =>
          row.symbol.toLowerCase().includes(q) ||
          row.name.toLowerCase().includes(q) ||
          row.sector.toLowerCase().includes(q),
      );
    }
    const value = (row: Forecast): number => {
      if (sort === "interest") return interest(row);
      if (sort === "expected_return") return row.expected_return ?? 0;
      if (sort === "prob_up") return row.prob_up ?? 0;
      if (sort === "news_flow") return Math.abs(row.news_flow);
      return Math.abs(row.signals[sort] ?? 0);
    };
    return [...list].sort((a, b) => value(b) - value(a));
  }, [forecasts.data, assetClass, direction, query, sort]);

  const edgeByClass = new Map(
    (models.data ?? []).map((model) => [model.asset_class, model.has_edge]),
  );

  return (
    <div className="space-y-4">
      <PageHeading
        title="Screener"
        subtitle="Every tradable instrument with today's signals (z-scores, + = bullish) and the 20-session forecast. Click a row for the full evidence: event history, analogs, correlations and news."
      />
      <div className="flex flex-wrap gap-2">
        {CLASSES.map((value) => (
          <button
            key={value}
            onClick={() => setAssetClass(value)}
            className={cn(
              "secondary-button",
              assetClass === value && "!border-strong !bg-accent !text-foreground",
            )}
          >
            {value}
            {value !== "all" && edgeByClass.has(value) && (
              <span
                className={cn(
                  "ml-1.5",
                  edgeByClass.get(value) ? "text-bull" : "text-muted-foreground",
                )}
              >
                {edgeByClass.get(value) ? "●" : "○"}
              </span>
            )}
          </button>
        ))}
        <select
          className="terminal-select !w-auto !min-h-0 !py-1.5"
          value={direction}
          onChange={(event) => setDirection(event.target.value as typeof direction)}
        >
          <option value="both">Long & short</option>
          <option value="long">Long only</option>
          <option value="short">Short only</option>
        </select>
        <input
          className="terminal-input !w-48 !min-h-0 !py-1.5"
          placeholder="Search symbol / sector"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        ● = the quant model has a validated walk-forward edge for that class; ○ = it doesn't
        (forecast = base rate).
      </p>
      <Panel bodyClassName="p-0 sm:p-4">
        {forecasts.isLoading ? (
          <Loading />
        ) : forecasts.error ? (
          <ErrorNote error={forecasts.error} />
        ) : rows.length === 0 ? (
          <Empty title="No rows">Nothing matches, or forecasts haven't been computed yet.</Empty>
        ) : (
          <TableWrap>
            <thead>
              <tr>
                <Th>Asset</Th>
                <Th right>Price</Th>
                <SortTh
                  label="E[20d]"
                  active={sort === "expected_return"}
                  onClick={() => setSort("expected_return")}
                />
                <SortTh
                  label="P(up)"
                  active={sort === "prob_up"}
                  onClick={() => setSort("prob_up")}
                />
                {SIGNALS.map((name) => (
                  <SortTh
                    key={name}
                    label={name}
                    active={sort === name}
                    onClick={() => setSort(name)}
                  />
                ))}
                <SortTh
                  label="News"
                  active={sort === "news_flow"}
                  onClick={() => setSort("news_flow")}
                />
                <SortTh
                  label="Drivers"
                  active={sort === "interest"}
                  onClick={() => setSort("interest")}
                />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.instrument_id}
                  className="cursor-pointer hover:bg-accent/30"
                  data-asset={row.instrument_id}
                  onClick={() => openAsset(row.instrument_id)}
                >
                  <Td>
                    <div className="font-bold">{row.symbol}</div>
                    <div className="max-w-[140px] truncate text-xs text-muted-foreground">
                      {row.name}
                    </div>
                  </Td>
                  <Td right>
                    {price(row.price)}
                    {row.stale_days > 3 && <Badge className="ml-1">stale</Badge>}
                  </Td>
                  <Td right className={tone(row.expected_return)}>
                    {pct(row.expected_return)}
                  </Td>
                  <Td right>{pct(row.prob_up, 0, false)}</Td>
                  {SIGNALS.map((name) => (
                    <Td key={name}>
                      <ZBar value={row.signals[name]} />
                    </Td>
                  ))}
                  <Td right className={tone(row.news_flow)}>
                    {row.news_count
                      ? `${row.news_flow > 0 ? "+" : ""}${row.news_flow} (${row.news_count})`
                      : "—"}
                  </Td>
                  <Td className="max-w-[220px] truncate text-xs text-muted-foreground">
                    {driverText(row)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

function SortTh({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Th>
      <button
        onClick={onClick}
        className={cn(" ", active ? "text-foreground" : "hover:text-foreground")}
      >
        {label}
        {active ? " ↓" : ""}
      </button>
    </Th>
  );
}
