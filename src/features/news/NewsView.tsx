import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AlertRow } from "@/features/shell/RightRail";
import { HeadlinesPanel } from "@/features/today/TodayView";
import {
  Badge,
  Empty,
  ErrorNote,
  EventBadge,
  Loading,
  PageHeading,
  Panel,
  Segmented,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { humanize, pct, shortDate, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import { cn } from "@/lib/utils";

type Tab = "wire" | "headlines" | "events" | "library";

const TABS: Array<{ value: Tab; label: string }> = [
  { value: "wire", label: "Live wire" },
  { value: "headlines", label: "Headlines" },
  { value: "events", label: "Detected events" },
  { value: "library", label: "Event library" },
];

export default function NewsView() {
  const [tab, setTab] = useState<Tab>("wire");
  return (
    <div className="space-y-4">
      <PageHeading
        title="News & events"
        subtitle="Headlines are classified into event categories. Structured events (earnings surprises, Fed moves, macro surprises, market shocks, geopolitical spikes) carry years of history, so the system can measure what each kind of event did to every asset."
      />
      <Segmented
        value={tab}
        options={TABS}
        onChange={setTab}
        className="max-w-full overflow-x-auto"
      />
      {tab === "wire" && <LiveWireTab />}
      {tab === "headlines" && <Headlines />}
      {tab === "events" && <DetectedEvents />}
      {tab === "library" && <EventLibrary />}
    </div>
  );
}

function LiveWireTab() {
  const [level, setLevel] = useState(2);
  const [hours, setHours] = useState(24);
  const alerts = useQuery({
    queryKey: ["alerts", "page", level, hours],
    queryFn: () => api.newsAlerts({ minutes: hours * 60, min_level: level, limit: 200 }),
    refetchInterval: 60_000,
  });
  const sources = useQuery({
    queryKey: ["alerts", "sources"],
    queryFn: api.newsSources,
    refetchInterval: 60_000,
  });
  const healthy = (sources.data ?? []).filter((s) => !s.error && s.last).length;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Panel
        title="Breaking news"
        subtitle="High-impact headlines (CEO changes, deals, guidance, regulators, central banks, wars) within about a minute of publication, one row per story. The coloured figure on each symbol is how far it had already moved when the alert fired: by the time free feeds carry a story, much of the move is usually priced in."
        actions={
          <>
            <Segmented
              value={level}
              onChange={setLevel}
              options={[
                { value: 3, label: "Top" },
                { value: 2, label: "Major" },
                { value: 1, label: "All" },
              ]}
            />
            <select
              className="terminal-select !w-auto"
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
            >
              {[1, 6, 24, 72, 168].map((h) => (
                <option key={h} value={h}>
                  Last {h < 24 ? `${h}h` : `${h / 24}d`}
                </option>
              ))}
            </select>
          </>
        }
      >
        {alerts.isLoading && <Loading />}
        {alerts.error && <ErrorNote error={alerts.error} />}
        {alerts.data?.length === 0 && (
          <Empty title="No alerts in this window">
            The wire polls about 50 sources roughly every minute. Lower the level or widen the
            window.
          </Empty>
        )}
        <div className="-mt-2">
          {alerts.data?.map((alert) => (
            <AlertRow key={alert.id} alert={alert} wide />
          ))}
        </div>
      </Panel>
      <Panel
        title="Sources"
        subtitle={
          sources.data
            ? `${healthy} of ${sources.data.length} feeds healthy. Failing feeds back off and retry by themselves.`
            : undefined
        }
      >
        <ul className="-my-1 max-h-[640px] space-y-0.5 overflow-y-auto text-xs">
          {(sources.data ?? []).map((source) => (
            <li
              key={source.name}
              className="flex items-center gap-2 py-1"
              title={source.error ?? `every ${source.every}s`}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  source.error ? "bg-bear" : source.last ? "bg-bull" : "bg-muted-foreground",
                )}
              />
              <span className="min-w-0 flex-1 truncate">{source.name}</span>
              <span className="text-muted-foreground">{source.group}</span>
            </li>
          ))}
        </ul>
      </Panel>
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
                      className="hover:text-bull"
                      data-asset={event.instrument_id}
                      onClick={() => openAsset(event.instrument_id as string)}
                    >
                      {event.instrument_id.split(":")[1].toUpperCase()}
                    </button>
                  ) : (
                    <span className="text-muted-foreground">market</span>
                  )}
                </Td>
                <Td className="max-w-[420px] truncate text-[11px]">{event.title}</Td>
                <Td className="text-xs text-muted-foreground">{event.source}</Td>
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
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge>{type.scope}</Badge>
            <span>{type.n} occurrences</span>
            {type.first && (
              <span>
                {shortDate(type.first)} → {shortDate(type.last)}
              </span>
            )}
          </div>
          <div className="mt-3 text-[11px] font-bold text-muted-foreground">
            Most reliably affected (20d)
          </div>
          {type.most_affected && type.most_affected.length > 0 ? (
            <ul className="mt-1 space-y-1">
              {type.most_affected.map((asset) => (
                <li key={asset.instrument_id} className="flex items-center justify-between text-xs">
                  <button
                    className="hover:text-bull"
                    data-asset={asset.instrument_id}
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
