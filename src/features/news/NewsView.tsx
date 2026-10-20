import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { HeadlinesPanel } from "@/features/today/TodayView";
import {
  Badge,
  Empty,
  ErrorNote,
  EventBadge,
  Loading,
  PageHeading,
  Panel,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { humanize, pct, shortDate, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { cn } from "@/lib/utils";

type Tab = "headlines" | "events" | "library";

export default function NewsView() {
  const [tab, setTab] = useState<Tab>("headlines");
  return (
    <div className="space-y-4">
      <PageHeading
        title="News & events"
        subtitle="Headlines are classified into event categories. Structured events (earnings surprises, Fed moves, macro surprises, market shocks, geopolitical spikes) carry years of history, so the system can measure what each kind of event did to every asset."
      />
      <div className="flex gap-2">
        {(["headlines", "events", "library"] as Tab[]).map((value) => (
          <button
            key={value}
            className={cn("secondary-button", tab === value && "!border-primary !text-primary")}
            onClick={() => setTab(value)}
          >
            {value === "library" ? "event library" : value === "events" ? "detected events" : value}
          </button>
        ))}
      </div>
      {tab === "headlines" && <Headlines />}
      {tab === "events" && <DetectedEvents />}
      {tab === "library" && <EventLibrary />}
    </div>
  );
}

function Headlines() {
  const [days, setDays] = useState(3);
  const [magnitude, setMagnitude] = useState(1);
  const [category, setCategory] = useState("");
  const categories = useQuery({
    queryKey: ["news-categories"],
    queryFn: api.newsCategories,
    staleTime: Infinity,
  });
  const news = useQuery({
    queryKey: ["news", days, magnitude, category],
    queryFn: () => api.news({ days, min_magnitude: magnitude, category: category || undefined }),
    refetchInterval: 120_000,
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <select
          className="terminal-select !w-auto !min-h-0 !py-1.5"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {[1, 3, 7, 30].map((d) => (
            <option key={d} value={d}>
              Last {d} day{d > 1 ? "s" : ""}
            </option>
          ))}
        </select>
        <select
          className="terminal-select !w-auto !min-h-0 !py-1.5"
          value={magnitude}
          onChange={(e) => setMagnitude(Number(e.target.value))}
        >
          <option value={1}>All magnitudes</option>
          <option value={2}>Notable+</option>
          <option value={3}>Major only</option>
        </select>
        <select
          className="terminal-select !w-auto !min-h-0 !py-1.5"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {(categories.data ?? []).map((row) => (
            <option key={row.category} value={row.category}>
              {humanize(row.category)}
            </option>
          ))}
        </select>
      </div>
      {news.isLoading ? (
        <Loading />
      ) : news.error ? (
        <ErrorNote error={news.error} />
      ) : (
        <HeadlinesPanel items={news.data ?? []} title={`${news.data?.length ?? 0} headlines`} />
      )}
    </div>
  );
}

function DetectedEvents() {
  const [days, setDays] = useState(90);
  const events = useQuery({ queryKey: ["events", days], queryFn: () => api.events(days) });
  const { openAsset } = useNav();
  return (
    <Panel
      title="Detected events"
      actions={
        <select
          className="terminal-select !w-auto !min-h-0 !py-1"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {[30, 90, 365, 1825].map((d) => (
            <option key={d} value={d}>
              Last {d >= 365 ? `${d / 365}y` : `${d}d`}
            </option>
          ))}
        </select>
      }
    >
      {events.isLoading ? (
        <Loading />
      ) : !events.data?.length ? (
        <Empty title="No events in this window" />
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>Date</Th>
              <Th>Type</Th>
              <Th>Asset</Th>
              <Th>Detail</Th>
              <Th>Source</Th>
            </tr>
          </thead>
          <tbody>
            {events.data.map((event) => (
              <tr key={event.id}>
                <Td>{event.date}</Td>
                <Td>
                  <EventBadge type={event.type} />
                </Td>
                <Td>
                  {event.instrument_id ? (
                    <button
                      className="hover:text-primary"
                      onClick={() => openAsset(event.instrument_id as string)}
                    >
                      {event.instrument_id.split(":")[1].toUpperCase()}
                    </button>
                  ) : (
                    <span className="text-muted-foreground">market</span>
                  )}
                </Td>
                <Td className="max-w-[420px] truncate text-[11px]">{event.title}</Td>
                <Td className="text-[10px] text-muted-foreground">{event.source}</Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Panel>
  );
}

function EventLibrary() {
  const types = useQuery({ queryKey: ["event-types"], queryFn: api.eventTypes });
  const { openAsset } = useNav();
  if (types.isLoading) return <Loading />;
  if (types.error) return <ErrorNote error={types.error} />;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {(types.data ?? []).map((type) => (
        <Panel key={type.type} title={humanize(type.type)} subtitle={type.label}>
          <div className="flex flex-wrap gap-2 text-[10px] text-muted-foreground">
            <Badge>{type.scope}</Badge>
            <span>{type.n} occurrences</span>
            {type.first && (
              <span>
                {shortDate(type.first)} → {shortDate(type.last)}
              </span>
            )}
          </div>
          <div className="mt-3 text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
            Most reliably affected (20d)
          </div>
          {type.most_affected && type.most_affected.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {type.most_affected.map((asset) => (
                <li key={asset.instrument_id} className="flex items-center justify-between text-xs">
                  <button
                    className="hover:text-primary"
                    onClick={() => openAsset(asset.instrument_id)}
                  >
                    {asset.symbol}
                  </button>
                  <span className="tabular-nums text-[11px]">
                    <span className={tone(asset.edge)}>{pct(asset.edge)}</span>
                    <span className="ml-2 text-muted-foreground">
                      up {pct(asset.hit_rate, 0, false)} · t {asset.t_stat.toFixed(1)} · n {asset.n}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-1 text-[11px] text-muted-foreground">
              {type.n
                ? "No asset with n ≥ 8."
                : "No occurrences yet (GDELT history may still be backfilling)."}
            </div>
          )}
        </Panel>
      ))}
    </div>
  );
}
