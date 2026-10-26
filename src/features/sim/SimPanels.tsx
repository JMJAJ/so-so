import { useMutation, useQuery } from "@tanstack/react-query";
import { MessageSquare, Play } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { FanChart } from "@/features/charts/svg";
import { useChat } from "@/features/chat/chat-context";
import {
  Badge,
  DirectionBadge,
  Empty,
  ErrorNote,
  Loading,
  Panel,
  Stat,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { humanize, money, pct, tone } from "@/lib/format";
import { useNav } from "@/lib/nav";
import type { ScenarioPreset, SimCheckScore } from "@/lib/types";
import { cn } from "@/lib/utils";

const HORIZONS = [5, 10, 20, 40];

/** Dollar amounts with cents when the account is small enough for cents to matter. */
function cash(value: number | null | undefined, equity: number, signed = false) {
  return money(value, signed, equity < 5_000 ? 2 : 0);
}

function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
}: {
  options: Array<[T, string]>;
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex gap-0.5 rounded-xl border border-border bg-input p-1"
    >
      {options.map(([option, text]) => (
        <button
          key={String(option)}
          role="tab"
          aria-selected={option === value}
          onClick={() => onChange(option)}
          className={cn(
            "min-h-8 rounded-lg px-2.5 text-xs font-semibold",
            option === value
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

const horizonOptions = HORIZONS.map((h) => [h, `${h}d`] as [number, string]);

/** How often past outcomes landed inside the simulator's bands, replayed on past dates. */
export function HonestyBadge({ check }: { check: SimCheckScore | null | undefined }) {
  if (!check) {
    return (
      <span title="Run the simulation check on the Track record page">
        <Badge>Not checked on past dates yet</Badge>
      </span>
    );
  }
  const good = check.verdict === "ranges match reality";
  return (
    <span
      className="inline-flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
      title={`${check.verdict}. Checked on ${check.n} past dates (${check.scope ?? "all assets"}), ${check.horizon ?? ""} sessions ahead.`}
    >
      <Badge tone={good ? "bull" : "amber"}>Checked: {pct(check.in80, 0, false)} in 80% band</Badge>
      <span>
        {pct(check.in50, 0, false)} in 50% band · n={check.n}
        {check.scope ? ` · ${check.scope}` : ""}
      </span>
    </span>
  );
}

function OddsBar({ parts }: { parts: Array<{ label: string; value: number; className: string }> }) {
  return (
    <div className="space-y-1.5">
      <div className="flex h-2 overflow-hidden rounded-full bg-accent">
        {parts.map((part) => (
          <div
            key={part.label}
            className={part.className}
            style={{ width: `${Math.max(0, part.value) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {parts.map((part) => (
          <span key={part.label} className="inline-flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", part.className)} />
            {part.label}{" "}
            <span className="font-mono text-foreground">{pct(part.value, 0, false)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ── One asset ────────────────────────────────────────────────────────────────

export function AssetSimulationPanel({
  instrumentId,
  symbol,
}: {
  instrumentId: string;
  symbol: string;
}) {
  const { ask } = useChat();
  const [horizon, setHorizon] = useState(20);
  const [similar, setSimilar] = useState(false);
  const sim = useQuery({
    queryKey: ["simulate", instrumentId, horizon, similar],
    queryFn: () => api.simulateAsset(instrumentId, horizon, similar),
    staleTime: 5 * 60_000,
  });
  const data = sim.data;
  const last = data?.fan.at(-1);

  return (
    <Panel
      title={`Simulated next ${horizon} sessions`}
      subtitle="4,000 possible paths stitched from this asset's own history at today's volatility. The bands hold 50% and 80% of paths. A range of plausible outcomes, not a prediction."
      actions={
        <>
          <button
            className={cn("secondary-button !min-h-9", similar && "!border-[#1f3a27] !text-bull")}
            onClick={() => setSimilar((v) => !v)}
            title="Use only history from the past setups most like today"
          >
            Similar conditions
          </button>
          <Segmented
            label="Horizon"
            options={horizonOptions}
            value={horizon}
            onChange={setHorizon}
          />
        </>
      }
    >
      {sim.isLoading ? (
        <Loading label="Simulating paths" />
      ) : sim.error ? (
        <ErrorNote error={sim.error} />
      ) : data && last ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Stat label="Median" value={pct(last.p50)} valueClassName={tone(last.p50)} />
            <Stat
              label="80% range"
              value={
                <span className="text-base">
                  {pct(last.p10, 0)} to {pct(last.p90, 0)}
                </span>
              }
            />
            <Stat label="P(up)" value={pct(data.p_up, 0, false)} />
            <Stat
              label="5% worst case"
              value={pct(data.var95)}
              valueClassName="text-bear"
              hint={`avg of worst 5%: ${pct(data.cvar95)}`}
            />
            <Stat
              label="Typical dip"
              value={pct(data.typical_drawdown)}
              hint="median drop from a peak along the way"
            />
          </div>
          <FanChart
            fan={data.fan}
            horizon={data.horizon}
            levels={data.levels}
            height={200}
            label={`Simulated ${symbol} returns over the next ${data.horizon} sessions`}
          />
          {data.bracket && (
            <div className="space-y-2 rounded-xl border border-border p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-semibold text-foreground">
                  {data.bracket_source === "open AI call" ? "The open AI call" : "This bracket"}
                </span>
                <DirectionBadge direction={data.bracket.direction} />
                <span className="text-muted-foreground">
                  expected {pct(data.bracket.expected_return, 2)} per trade · profit in{" "}
                  {pct(data.bracket.p_profit, 0, false)} of paths
                </span>
              </div>
              <OddsBar
                parts={[
                  { label: "Target first", value: data.bracket.p_target, className: "bg-bull" },
                  { label: "Stop first", value: data.bracket.p_stop, className: "bg-bear" },
                  {
                    label: "Neither by the horizon",
                    value: data.bracket.p_neither,
                    className: "bg-muted-foreground/50",
                  },
                ]}
              />
              <p className="text-[11px] text-muted-foreground">{data.bracket.note}</p>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <HonestyBadge check={data.check} />
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-muted-foreground">
                Volatility {pct(data.vol_now, 0, false)} a year now vs{" "}
                {pct(data.vol_long, 0, false)} normal · {data.method.basis} · {data.method.drift}
              </span>
              <button
                className="secondary-button !min-h-8 !py-1"
                onClick={() => ask(`/simulate ${symbol} over ${horizon} sessions`, true)}
              >
                <MessageSquare className="h-3.5 w-3.5" /> Explain
              </button>
            </div>
          </div>
        </div>
      ) : (
        <Empty title="No simulation" />
      )}
    </Panel>
  );
}

// ── Whole account ────────────────────────────────────────────────────────────

export function PortfolioSimulationPanel() {
  const { openAsset } = useNav();
  const [horizon, setHorizon] = useState(20);
  const sim = useQuery({
    queryKey: ["portfolio-sim", horizon],
    queryFn: () => api.simulatePortfolio(horizon),
    staleTime: 5 * 60_000,
  });
  const data = sim.data;
  const last = data?.fan?.at(-1);

  return (
    <Panel
      title={`Account risk · next ${horizon} sessions`}
      subtitle="Every open position simulated together on the same historical days, so they move together the way they really do. Stops, targets and expiry are applied."
      actions={
        <Segmented label="Horizon" options={horizonOptions} value={horizon} onChange={setHorizon} />
      }
    >
      {sim.isLoading ? (
        <Loading label="Simulating the account" />
      ) : sim.error ? (
        <ErrorNote error={sim.error} />
      ) : !data || !data.fan || !last ? (
        <Empty title="Nothing to simulate">{data?.note ?? "Open a position first."}</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Stat
              label="Median outcome"
              value={cash(data.median_pnl, data.equity, true)}
              valueClassName={tone(data.median_pnl)}
              hint={pct(last.p50, 2)}
            />
            <Stat
              label="80% range"
              value={
                <span className="text-base">
                  {pct(last.p10, 1)} to {pct(last.p90, 1)}
                </span>
              }
            />
            <Stat label="Chance of a loss" value={pct(data.p_loss, 0, false)} />
            <Stat
              label="Lose more than 5%"
              value={pct(data.p_loss_5pct, 0, false)}
              valueClassName={(data.p_loss_5pct ?? 0) > 0.1 ? "text-bear" : undefined}
              hint={`more than 10%: ${pct(data.p_loss_10pct, 0, false)}`}
            />
            <Stat
              label="5% worst case"
              value={cash(data.var95, data.equity, true)}
              valueClassName="text-bear"
              hint={`avg of worst 5%: ${cash(data.cvar95, data.equity, true)}`}
            />
          </div>
          <FanChart
            fan={data.fan}
            horizon={data.horizon}
            height={190}
            label="Simulated change in account value"
          />
          <TableWrap>
            <thead>
              <tr>
                <Th>Position</Th>
                <Th right>Share of risk</Th>
                <Th right>Avg P&L</Th>
                <Th right>5% worst</Th>
                <Th right>Stop first</Th>
                <Th right>Target first</Th>
              </tr>
            </thead>
            <tbody>
              {[...data.positions]
                .sort((a, b) => (b.risk_share ?? 0) - (a.risk_share ?? 0))
                .map((row) => (
                  <tr key={`${row.symbol}-${row.side}`}>
                    <Td>
                      <button
                        className="inline-flex items-center gap-2 font-bold hover:text-bull"
                        onClick={() => row.instrument_id && openAsset(row.instrument_id)}
                      >
                        {row.symbol} <DirectionBadge direction={row.side} />
                      </button>
                    </Td>
                    {row.skipped ? (
                      <Td right className="text-muted-foreground" colSpan={5}>
                        {row.skipped}
                      </Td>
                    ) : (
                      <>
                        <Td right>
                          <span className="inline-flex items-center gap-2">
                            <span className="h-1.5 w-16 overflow-hidden rounded-full bg-accent">
                              <span
                                className="block h-full bg-primary"
                                style={{
                                  width: `${Math.min(100, Math.max(0, (row.risk_share ?? 0) * 100))}%`,
                                }}
                              />
                            </span>
                            {pct(row.risk_share, 0, false)}
                          </span>
                        </Td>
                        <Td right className={tone(row.mean_pnl)}>
                          {cash(row.mean_pnl, data.equity, true)}
                        </Td>
                        <Td right className="text-bear">
                          {cash(row.p5_pnl, data.equity, true)}
                        </Td>
                        <Td right>{pct(row.p_stop, 0, false)}</Td>
                        <Td right>{pct(row.p_target, 0, false)}</Td>
                      </>
                    )}
                  </tr>
                ))}
            </tbody>
          </TableWrap>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
            <HonestyBadge check={data.check} />
            <span className="text-[11px] text-muted-foreground">
              {data.note}
              {data.pending_skipped ? ` ${data.pending_skipped} pending.` : ""}
            </span>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── What-if scenarios ────────────────────────────────────────────────────────

interface ScenarioQuery {
  driver: string;
  move: number | null;
  window: number;
  label: string;
}

export function ScenarioPanel() {
  const { openAsset } = useNav();
  const presets = useQuery({
    queryKey: ["scenario-presets"],
    queryFn: api.scenarioPresets,
    staleTime: Infinity,
  });
  const [query, setQuery] = useState<ScenarioQuery | null>(null);
  const [horizon, setHorizon] = useState(20);
  const [driver, setDriver] = useState("");
  const [move, setMove] = useState("");
  const [window, setWindow] = useState("5");
  const result = useQuery({
    queryKey: ["scenario", query?.driver, query?.move, query?.window, horizon],
    queryFn: () => api.scenario(query!.driver, query!.move, query!.window, horizon),
    enabled: Boolean(query),
    staleTime: 10 * 60_000,
  });
  const eventTypes = presets.data?.event_types ?? [];

  const pick = (preset: ScenarioPreset) => {
    setQuery({
      driver: preset.driver,
      move: preset.move ?? null,
      window: preset.window ?? 5,
      label: preset.label,
    });
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const name = driver.trim();
    if (!name) return;
    const isEvent = eventTypes.includes(name);
    const value = Number.parseFloat(move);
    if (!isEvent && Number.isNaN(value)) {
      toast.error("Give a move in %, e.g. 10 or -5");
      return;
    }
    setQuery({
      driver: name,
      move: isEvent ? null : value / 100,
      window: Number.parseInt(window, 10) || 5,
      label: isEvent ? humanize(name) : `${name.toUpperCase()} ${value > 0 ? "+" : ""}${value}%`,
    });
  };

  const data = result.data;
  return (
    <Panel
      title="What if…"
      subtitle="Finds every past time this happened and shows what each market and your open positions did over the following sessions, against their normal return. Only rows marked reliable are evidence; the rest is noise-sized."
      actions={
        <Segmented label="Horizon" options={horizonOptions} value={horizon} onChange={setHorizon} />
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {(presets.data?.presets ?? []).map((preset) => (
            <button
              key={preset.id}
              onClick={() => pick(preset)}
              className={cn(
                "secondary-button !min-h-8 !py-1 text-xs",
                query?.label === preset.label && "!border-[#1f3a27] !text-bull",
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
          <label className="space-y-1">
            <span className="block text-xs font-semibold text-muted-foreground">
              Driver (symbol or event)
            </span>
            <input
              className="terminal-input w-44"
              list="scenario-events"
              placeholder="WTI, VIX, rate_hike…"
              value={driver}
              onChange={(e) => setDriver(e.target.value)}
            />
            <datalist id="scenario-events">
              {eventTypes.map((type) => (
                <option key={type} value={type} />
              ))}
            </datalist>
          </label>
          <label className="space-y-1">
            <span className="block text-xs font-semibold text-muted-foreground">Move %</span>
            <input
              className="terminal-input w-24 font-mono"
              inputMode="decimal"
              placeholder="10"
              value={move}
              onChange={(e) => setMove(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="block text-xs font-semibold text-muted-foreground">
              Within (sessions)
            </span>
            <input
              className="terminal-input w-24 font-mono"
              inputMode="numeric"
              value={window}
              onChange={(e) => setWindow(e.target.value)}
            />
          </label>
          <button type="submit" className="primary-button">
            <Play className="h-4 w-4" /> Run
          </button>
        </form>

        {!query ? (
          <Empty title="Pick a scenario">
            Or type your own: a symbol and a move, or an event type.
          </Empty>
        ) : result.isLoading ? (
          <Loading label="Searching history" />
        ) : result.error ? (
          <ErrorNote error={result.error} />
        ) : data ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span className="text-sm font-semibold text-foreground">{data.title}</span>
              <span>{data.occurrences} past occurrences</span>
              {data.now && <span>Now: {data.now}</span>}
              <Badge tone={data.reliable_count ? "bull" : "neutral"}>
                {data.reliable_count} reliable effect{data.reliable_count === 1 ? "" : "s"}
              </Badge>
              {data.account_effect != null && (
                <span>
                  Average effect on open positions:{" "}
                  <span className={cn("font-mono", tone(data.account_effect))}>
                    {money(data.account_effect, true, 2)}
                  </span>
                </span>
              )}
            </div>
            {data.assets.length === 0 ? (
              <Empty title="Not enough past occurrences to measure anything" />
            ) : (
              <TableWrap>
                <thead>
                  <tr>
                    <Th>Asset</Th>
                    <Th right>n</Th>
                    <Th right>Avg after</Th>
                    <Th right>vs normal</Th>
                    <Th right>Up</Th>
                    <Th right>t</Th>
                    <Th>Evidence</Th>
                    <Th right>Your position</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.assets.map((row) => (
                    <tr key={row.instrument_id} className={cn(!row.reliable && "opacity-70")}>
                      <Td>
                        <button
                          className="font-bold hover:text-bull"
                          onClick={() => openAsset(row.instrument_id)}
                        >
                          {row.symbol}
                        </button>
                      </Td>
                      <Td right>{row.n}</Td>
                      <Td right className={tone(row.mean)}>
                        {pct(row.mean)}
                      </Td>
                      <Td right className={tone(row.edge)}>
                        {pct(row.edge)}
                      </Td>
                      <Td right>{pct(row.hit_rate, 0, false)}</Td>
                      <Td right>{row.t_stat.toFixed(1)}</Td>
                      <Td>
                        {row.reliable ? (
                          <Badge tone="bull">reliable</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            {row.n < 8 ? "too few" : "noise"}
                          </span>
                        )}
                      </Td>
                      <Td right>
                        {row.position ? (
                          <span className="inline-flex items-center gap-2">
                            <DirectionBadge direction={row.position} />
                            <span className={cn("font-mono", tone(row.position_effect))}>
                              {money(row.position_effect, true, 2)}
                            </span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            )}
            <p className="text-[11px] text-muted-foreground">{data.note}</p>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}

// ── Honesty check ────────────────────────────────────────────────────────────

export function SimCheckPanel() {
  const check = useQuery({ queryKey: ["sim-check"], queryFn: () => api.simulationCheck(20) });
  const run = useMutation({
    mutationFn: () => api.runJob("sim_check"),
    onSuccess: () => toast.success("Simulation check started: about a minute"),
    onError: (error: Error) => toast.error(error.message),
  });
  const data = check.data;
  return (
    <Panel
      title="Simulation honesty check"
      subtitle="The price simulator replayed on past dates, using only the data known on each date. A trustworthy simulator has about 80% of real outcomes inside its 80% band and about 50% inside its 50% band. Brier vs base: below base would mean it also calls direction; equal means it shows range only."
      actions={
        <button
          className="secondary-button !min-h-9"
          onClick={() => run.mutate()}
          disabled={run.isPending}
        >
          <Play className="h-4 w-4" /> Run check
        </button>
      }
    >
      {check.isLoading ? (
        <Loading />
      ) : check.error ? (
        <ErrorNote error={check.error} />
      ) : !data?.overall ? (
        <Empty title="Not run yet">{data?.note}</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat
              label="Inside 80% band"
              value={pct(data.overall.in80, 0, false)}
              valueClassName={
                data.overall.verdict === "ranges match reality" ? "text-bull" : "text-amber"
              }
              hint="target 80%"
            />
            <Stat
              label="Inside 50% band"
              value={pct(data.overall.in50, 0, false)}
              hint="target 50%"
            />
            <Stat
              label="Brier P(up)"
              value={data.overall.brier.toFixed(3)}
              hint={`base rate ${data.overall.brier_base.toFixed(3)}`}
            />
            <Stat label="Past dates" value={String(data.n)} hint={`${data.from} → ${data.to}`} />
          </div>
          <TableWrap>
            <thead>
              <tr>
                <Th>Asset class</Th>
                <Th right>n</Th>
                <Th right>In 80% band</Th>
                <Th right>In 50% band</Th>
                <Th right>Brier / base</Th>
                <Th>Verdict</Th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_class).map(([name, row]) => (
                <tr key={name}>
                  <Td className="font-bold">{name}</Td>
                  <Td right>{row.n}</Td>
                  <Td right>{pct(row.in80, 0, false)}</Td>
                  <Td right>{pct(row.in50, 0, false)}</Td>
                  <Td right>
                    {row.brier.toFixed(3)} / {row.brier_base.toFixed(3)}
                  </Td>
                  <Td className="text-xs text-muted-foreground">{row.verdict}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </div>
      )}
    </Panel>
  );
}
