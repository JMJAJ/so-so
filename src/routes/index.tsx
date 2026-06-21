import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, useCallback } from "react";
import React from "react";
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, AreaSeries } from "lightweight-charts";
import {
  sma as calcSma, ema as calcEma, bollingerBands as calcBB,
  rsi as calcRsi, macd as calcMacd, detectSupportResistance,
  scoreSignals, projectCone, detectPatterns,
  type Candle, type SignalScore, type ChartPattern,
} from "@/lib/indicators";
import {
  Activity, Wallet, TrendingUp, AlertTriangle, Power,
  Gauge, Layers, ArrowUpRight, ArrowDownRight, ShieldAlert, Download,
  LayoutDashboard, BarChart3, X, Settings, Target,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({ meta: [{ title: "NEXUS // AI Trading Terminal" }] }),
  component: Dashboard,
});

type AssetClass = "forex" | "stock" | "crypto" | "cfd" | "futures";

interface Position {
  id: string; pair: string; asset_class: AssetClass; side: "long" | "short";
  size: number; entry_price: number; current_price: number;
  pnl: number; pnl_pct: number; opened_at: string; confidence: number;
  notional: number;
}
interface Trade {
  id: string; pair: string; side: "long" | "short"; size: number;
  entry_price: number; exit_price: number; pnl: number; closed_at: string;
}
interface AiLog {
  id: string; level: "info" | "warn" | "error"; action: string;
  pair: string | null; message: string; created_at: string;
}
interface Portfolio {
  starting_equity: number; equity: number; open_pnl: number; realized: number;
  exposure: number; leverage: number; open_count: number;
  win_rate: number; wins: number; losses: number;
  avg_win: number; avg_loss: number; profit_factor: number;
  max_drawdown: number;
  equity_series: { t: string; eq: number }[];
  daily_pnl: { d: string; v: number }[];
  by_asset: { k: AssetClass; exposure: number; pnl: number; count: number; pct: number }[];
  allocation: { ccy: string; value: number; pct: number }[];
  winners: Position[]; losers: Position[];
}
interface AgentStatus {
  running: boolean; model: string; cycle_count: number;
  last_cycle: string | null; last_error: string | null;
  interval_seconds: number;
}
interface WatchlistItem {
  pair: string; asset_class: AssetClass;
  price: number | null; change_pct: number | null;
}
interface TradeIdea {
  id: string; symbol: string; asset_class: AssetClass; side: "long" | "short";
  entry_price: number; stop_loss: number | null; take_profit: number | null;
  confidence: number | null; reasoning: string | null; status: "active" | "closed";
  created_at: string; closed_at: string | null; outcome_pnl: number | null;
}

const fmt = (n: number | null | undefined, d = 2) =>
  (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPx = (n: number) => (n >= 1000 ? fmt(n, 2) : fmt(n, 4));
const signed = (n: number | null | undefined, d = 2) => `${(n ?? 0) > 0 ? "+" : ""}${fmt(Object.is(n, -0) ? 0 : (n ?? 0), d)}`;

const API = "/api";
const POLL_MS = 10_000;

const ASSET_CLASS_ORDER: AssetClass[] = ["forex", "stock", "cfd", "crypto", "futures"];
const ASSET_COLOR: Record<AssetClass, string> = {
  forex: "bg-primary", stock: "bg-chart-2", crypto: "bg-chart-5", cfd: "bg-chart-3", futures: "bg-chart-4",
};

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}${url}`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function Dashboard() {
  const [now, setNow] = useState(() => new Date());
  const [assetFilter, setAssetFilter] = useState<"all" | AssetClass>("all");
  const [live, setLive] = useState(false);
  const [view, setView] = useState<"dashboard" | "assets" | "ideas">("dashboard");
  const [showSettings, setShowSettings] = useState(false);
  const [navigateToSymbol, setNavigateToSymbol] = useState<string | null>(null);

  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [logs, setLogs] = useState<AiLog[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [currency, setCurrency] = useState("USD");
  const [fxRate, setFxRate] = useState(1);

  const refresh = useCallback(async () => {
    const [pos, tr, lg, pf, ag, wl, cfg] = await Promise.all([
      fetchJson<Position[]>("/positions"),
      fetchJson<Trade[]>("/trades"),
      fetchJson<AiLog[]>("/logs?limit=20"),
      fetchJson<Portfolio>("/portfolio"),
      fetchJson<AgentStatus>("/agent/status"),
      fetchJson<WatchlistItem[]>("/watchlist"),
      fetchJson<{ starting_equity: number; display_currency: string; fx_rate: number }>("/config"),
    ]);
    if (pos && pf) {
      setPositions(pos);
      setTrades(tr ?? []);
      setLogs(lg ?? []);
      setPortfolio(pf);
      setAgentStatus(ag ?? null);
      if (wl) setWatchlist(wl);
      if (cfg) { setCurrency(cfg.display_currency); setFxRate(cfg.fx_rate); }
      setLive(true);
    } else {
      setLive(false);
    }
  }, []);

  const exportSnapshot = useCallback(() => {
    const snapshot = {
      exported_at: new Date().toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      portfolio, positions, trades, logs, agentStatus, watchlist,
    };
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `nexus-snapshot-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [portfolio, positions, trades, logs, agentStatus, watchlist]);

  useEffect(() => {
    refresh();
    const i = setInterval(() => { refresh(); setNow(new Date()); }, POLL_MS);
    return () => clearInterval(i);
  }, [refresh]);

  const t = portfolio;
  const startingEquity = t?.starting_equity ?? 100_000;

  const filteredPositions = assetFilter === "all"
    ? positions
    : positions.filter((p) => p.asset_class === assetFilter);

  return (
    <main className="flex min-h-screen">
      {/* ── Sidebar ── */}
      <nav className="sticky top-0 flex h-screen w-14 shrink-0 flex-col items-center gap-1 border-r border-border bg-card/50 py-3">
        <span className="mb-4 font-display text-xs font-bold tracking-tight text-primary">N</span>
        <NavBtn active={view === "dashboard"} onClick={() => setView("dashboard")} icon={LayoutDashboard} label="Dashboard" />
        <NavBtn active={view === "assets"} onClick={() => setView("assets")} icon={BarChart3} label="Assets" />
        <NavBtn active={view === "ideas"} onClick={() => setView("ideas")} icon={Target} label="Trade Ideas" />
      </nav>

      {/* ── Main content ── */}
      <div className="flex-1 pb-12">
        <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
          <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-2.5">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-bull" />
                <span className="font-display text-sm font-bold tracking-tight">NEXUS</span>
                <span className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">// {view === "dashboard" ? "AI TRADING TERMINAL" : "MARKET WATCH"}</span>
              </div>
              <div className="hidden h-4 w-px bg-border md:block" />
              <div className="hidden items-center gap-3 text-[10px] uppercase tracking-[0.25em] text-muted-foreground md:flex">
                <span className={live ? "text-bull" : "text-bear"}>● {live ? "LIVE DATA" : "OFFLINE"}</span>
                <span>{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
                {t && <span>EQUITY {currency === "CZK" ? "Kč" : "$"}{fmt((t.equity) * fxRate, 0)}</span>}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="hidden items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-muted-foreground md:flex">
                <span className={agentStatus?.running ? "text-bull" : "text-muted-foreground"}>
                  ● {agentStatus?.running ? "AI RUNNING" : "AI IDLE"}
                </span>
                {agentStatus?.last_cycle && <span>cycles: {agentStatus.cycle_count}</span>}
                <span className="font-mono text-[9px]">{agentStatus?.model}</span>
              </div>
              {agentStatus?.running ? (
                <button onClick={() => fetch(`${API}/agent/stop`, { method: "POST" }).then(refresh)}
                  className="flex items-center gap-2 rounded-sm border border-bear/60 bg-card px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-bear transition hover:bg-bear/10">
                  <Power className="h-3 w-3" /> Stop AI
                </button>
              ) : (
                <button onClick={() => fetch(`${API}/agent/start?interval=120`, { method: "POST" }).then(refresh)}
                  className="flex items-center gap-2 rounded-sm border border-bull/60 bg-bull/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-bull transition hover:border-bull">
                  <Activity className="h-3 w-3" /> Start AI
                </button>
              )}
              <button onClick={() => fetch(`${API}/agent/trigger`, { method: "POST" })}
                className="rounded-sm border border-border px-2 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground transition hover:border-primary hover:text-primary">
                Trigger
              </button>
              <button onClick={exportSnapshot}
                className="flex items-center gap-1.5 rounded-sm border border-border px-2 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground transition hover:border-primary hover:text-primary">
                <Download className="h-3 w-3" /> Export
              </button>
              <button onClick={() => setShowSettings(true)}
                className="flex items-center gap-1.5 rounded-sm border border-border px-2 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground transition hover:border-primary hover:text-primary">
                <Settings className="h-3 w-3" /> Settings
              </button>
            </div>
          </div>
        </header>

        {view === "dashboard" ? (
          <DashboardView t={t} startingEquity={startingEquity} positions={positions} trades={trades} logs={logs}
            filteredPositions={filteredPositions} assetFilter={assetFilter} setAssetFilter={setAssetFilter}
            agentStatus={agentStatus} refresh={refresh} fx={fxRate} csym={currency === "CZK" ? "Kč" : "$"}
            onNavigateToChart={(symbol: string) => { setNavigateToSymbol(symbol); setView("ideas"); }} />
        ) : view === "assets" ? (
          <AssetsView watchlist={watchlist} positions={positions} refresh={refresh} fx={fxRate} csym={currency === "CZK" ? "Kč" : "$"} />
        ) : (
          <TradeIdeasView initialSymbol={navigateToSymbol} onClearSymbol={() => setNavigateToSymbol(null)} />
        )}

        {agentStatus?.last_error && (
          <div className="fixed bottom-4 left-1/2 z-40 -translate-x-1/2 rounded-sm border border-bear/60 bg-bear/10 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.3em] text-bear">
            <AlertTriangle className="mr-2 inline h-3 w-3" /> {agentStatus.last_error}
          </div>
        )}

        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} refresh={refresh} />
        )}
      </div>
    </main>
  );
}

/* ──────────────── Nav button ──────────────── */

function NavBtn({ active, onClick, icon: Icon, label }:
  { active: boolean; onClick: () => void; icon: typeof LayoutDashboard; label: string }) {
  return (
    <button onClick={onClick} title={label}
      className={`group flex h-10 w-10 items-center justify-center rounded-sm transition ${
        active ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-card hover:text-foreground"
      }`}>
      <Icon className="h-4 w-4" strokeWidth={1.5} />
    </button>
  );
}

/* ──────────────── Dashboard View ──────────────── */

function DashboardView({ t, startingEquity, positions, trades, logs, filteredPositions,
  assetFilter, setAssetFilter, agentStatus, refresh, fx, csym, onNavigateToChart }: {
  t: Portfolio | null; startingEquity: number; positions: Position[]; trades: Trade[]; logs: AiLog[];
  filteredPositions: Position[]; assetFilter: "all" | AssetClass;
  setAssetFilter: (v: "all" | AssetClass) => void; agentStatus: AgentStatus | null;
  refresh: () => void; fx: number; csym: string;
  onNavigateToChart?: (symbol: string) => void;
}) {
  const cfmt = (n: number, d = 2) => fmt(n * fx, d);
  const csigned = (n: number, d = 2) => `${n >= 0 ? "+" : ""}${cfmt(n, d)}`;
  return (
    <>
      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 py-4 grid-cols-3 lg:grid-cols-6">
        <Kpi icon={Wallet}      label="Equity"          value={`${csym}${cfmt(t?.equity ?? startingEquity, 0)}`} sub={`start ${csym}${cfmt(startingEquity, 0)}`} />
        <Kpi icon={TrendingUp}  label="Unrealized P&L"  value={`${csigned(t?.open_pnl ?? 0)} ${csym}`} tone={(t?.open_pnl ?? 0) >= 0 ? "bull" : "bear"} />
        <Kpi icon={Activity}    label="Realized (all)"  value={`${csigned(t?.realized ?? 0)} ${csym}`} tone={(t?.realized ?? 0) >= 0 ? "bull" : "bear"} />
        <Kpi icon={Layers}      label="Exposure"        value={`${csym}${cfmt(t?.exposure ?? 0, 0)}`} sub={`${t?.open_count ?? 0} positions`} />
        <Kpi icon={Gauge}       label="Leverage"        value={`${(t?.leverage ?? 0).toFixed(2)}x`} tone={(t?.leverage ?? 0) > 2 ? "bear" : undefined} />
        <Kpi icon={ShieldAlert} label="Max drawdown"    value={`${(t?.max_drawdown ?? 0).toFixed(2)}%`} tone="bear" />
      </section>

      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 lg:grid-cols-[3fr_1fr]">
        <div className="flex flex-col gap-3">
          <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
            <Panel title="EQUITY CURVE" sub={`since inception · ${csigned((t?.equity ?? startingEquity) - startingEquity)} ${csym}`}>
              <EquityChart data={t?.equity_series ?? []} fx={fx} csym={csym} />
            </Panel>
            <Panel title="DAILY P&L" sub={`${(t?.daily_pnl ?? []).length} sessions`}>
              <DailyPnlChart data={t?.daily_pnl ?? []} />
            </Panel>
          </div>

          <div className="grid gap-3 grid-cols-3">
            <Panel title="ASSET CLASS" sub="exposure split">
              <div className="space-y-3">
                {(t?.by_asset ?? []).map((a) => (
                  <div key={a.k}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2">
                        <span className={`inline-block h-2 w-2 rounded-sm ${ASSET_COLOR[a.k] ?? "bg-primary"}`} />
                        <span className="font-bold uppercase">{a.k}</span>
                        <span className="text-[10px] text-muted-foreground">{a.count} pos</span>
                      </span>
                      <span className="tabular-nums text-muted-foreground">{a.pct.toFixed(1)}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-sm bg-secondary">
                      <div className={`h-full transition-all ${ASSET_COLOR[a.k] ?? "bg-primary"}`} style={{ width: `${a.pct}%` }} />
                    </div>
                    <div className="mt-0.5 flex justify-between text-[10px] tabular-nums text-muted-foreground">
                      <span>{csym}{cfmt(a.exposure, 0)}</span>
                      <span className={a.pnl >= 0 ? "text-bull" : "text-bear"}>{csigned(a.pnl)} {csym}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="ALLOCATION" sub="by symbol / base ccy">
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {(t?.allocation ?? []).map((a) => (
                  <div key={a.ccy}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold">{a.ccy}</span>
                      <span className="tabular-nums text-muted-foreground">{a.pct.toFixed(1)}%</span>
                    </div>
                    <div className="mt-1 h-1 overflow-hidden rounded-sm bg-secondary">
                      <div className="h-full bg-primary" style={{ width: `${a.pct}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="PERFORMANCE" sub="closed trades">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <Metric label="Win rate"      value={`${(t?.win_rate ?? 0).toFixed(0)}%`} tone={(t?.win_rate ?? 0) >= 50 ? "bull" : "bear"} />
                <Metric label="Trades"        value={String(trades.length)} />
                <Metric label="Wins"          value={String(t?.wins ?? 0)}   tone="bull" />
                <Metric label="Losses"        value={String(t?.losses ?? 0)} tone="bear" />
                <Metric label="Avg win"       value={`${csym}${cfmt(t?.avg_win ?? 0)}`} tone="bull" />
                <Metric label="Avg loss"      value={`-${csym}${cfmt(t?.avg_loss ?? 0)}`} tone="bear" />
                <Metric label="Profit factor"
                        value={t && t.avg_loss > 0
                          ? t.profit_factor === Infinity ? "∞" : t.profit_factor.toFixed(2)
                          : "∞"} tone="bull" />
                <Metric label="Net P&L" value={`${csigned(t?.realized ?? 0)} ${csym}`}
                        tone={(t?.realized ?? 0) >= 0 ? "bull" : "bear"} />
              </div>
            </Panel>
          </div>

          <Panel
            title="OPEN POSITIONS"
            sub={`${filteredPositions.length} shown`}
            right={
              <div className="flex items-center gap-1">
                {(["all", ...ASSET_CLASS_ORDER] as const).map((k) => (
                  <button key={k} onClick={() => setAssetFilter(k)}
                    className={`rounded-sm border px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest transition ${
                      assetFilter === k
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/40"
                    }`}>{k}</button>
                ))}
              </div>
            }>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                    <Th>Symbol</Th><Th>Side</Th><Th right>Size</Th><Th right>Entry</Th>
                    <Th right>Mark</Th><Th right>P&L $</Th><Th right>P&L %</Th>
                    <Th right>Notional</Th><Th right>Conf</Th><Th right>Age</Th><Th />
                  </tr>
                </thead>
                <tbody>
                  {filteredPositions.map((p) => (
                    <tr key={p.id} className="border-b border-border/40 transition hover:bg-card/50">
                      <td className="py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block h-1.5 w-1.5 rounded-full ${ASSET_COLOR[p.asset_class] ?? "bg-primary"}`} />
                          {onNavigateToChart ? (
                            <button onClick={() => onNavigateToChart(p.pair)} className="font-bold text-primary hover:text-primary/80 transition">{p.pair}</button>
                          ) : (
                            <span className="font-bold">{p.pair}</span>
                          )}
                          <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{p.asset_class}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                          p.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"
                        }`}>{p.side}</span>
                      </td>
                      <Td right muted>{fmt(p.size, p.asset_class === "stock" ? 0 : p.size < 1 ? 4 : 2)}</Td>
                      <Td right muted>{fmtPx(p.entry_price)}</Td>
                      <Td right>{fmtPx(p.current_price)}</Td>
                      <Td right tone={p.pnl >= 0 ? "bull" : "bear"}>{csigned(p.pnl)}</Td>
                      <Td right tone={p.pnl_pct >= 0 ? "bull" : "bear"}>{signed(p.pnl_pct)}%</Td>
                      <Td right muted>{csym}{cfmt(p.notional, 0)}</Td>
                      <td className="py-2.5 pr-2 text-right"><ConfBar value={p.confidence} /></td>
                      <Td right muted>{formatDistanceToNow(new Date(p.opened_at))}</Td>
                      <td className="py-2.5">
                        <button onClick={() => fetch(`${API}/positions/${p.id}`, { method: "DELETE" }).then(refresh)}
                          className="rounded-sm border border-bear/40 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-bear/70 transition hover:border-bear hover:bg-bear/10 hover:text-bear">
                          Close
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-3">
          <Panel title="AI DECISION LOG" sub={`last ${logs.length} events`}
            right={
              logs.length > 0 && (
                <button onClick={() => fetch(`${API}/logs`, { method: "DELETE" }).then(refresh)}
                  className="rounded-sm border border-border px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground transition hover:border-bear hover:text-bear">
                  Clear
                </button>
              )
            }>
            <div className="max-h-[320px] space-y-1 overflow-y-auto pr-1">
              {logs.length === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">No events yet. Start the AI to begin trading.</div>
              )}
              {logs.map((l) => (
                <div key={l.id} className="grid grid-cols-[auto_1fr_auto] items-start gap-2 border-b border-border/40 py-2 text-xs">
                  <span className={`shrink-0 rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
                    l.level === "error" ? "bg-bear/15 text-bear"
                      : l.level === "warn" ? "bg-primary/15 text-primary"
                      : "bg-bull/15 text-bull"
                  }`}>{l.action}</span>
                  <div className="min-w-0">
                    {l.pair && onNavigateToChart ? (
                      <button onClick={() => onNavigateToChart(l.pair!)}
                        className="mr-1 font-bold text-primary hover:text-primary/80 transition">{l.pair}</button>
                    ) : l.pair ? (
                      <span className="mr-1 font-bold">{l.pair}</span>
                    ) : null}
                    <span className="text-foreground/90">{l.message}</span>
                  </div>
                  <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                    {formatDistanceToNow(new Date(l.created_at))}
                  </span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="RECENT TRADES" sub={`${trades.length} closed`}>
            <div className="max-h-[260px] overflow-y-auto pr-1">
              {trades.length === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">No closed trades yet.</div>
              )}
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                    <Th>Symbol</Th><Th>Side</Th><Th right>P&L</Th><Th right>Closed</Th>
                  </tr>
                </thead>
                <tbody>
                  {[...trades].reverse().slice(0, 5).map((tr) => (
                    <tr key={tr.id} className="border-b border-border/40">
                      <td className="py-2 font-bold">{tr.pair}</td>
                      <td>
                        <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                          tr.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"
                        }`}>{tr.side}</span>
                      </td>
                      <Td right tone={tr.pnl >= 0 ? "bull" : "bear"}>{csigned(tr.pnl)}</Td>
                      <Td right muted>{formatDistanceToNow(new Date(tr.closed_at))}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="TOP MOVERS" sub="open positions">
            <div className="space-y-3">
              <div>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-bull">▲ Winners</div>
                <MoverList rows={t?.winners ?? []} icon={ArrowUpRight} tone="bull" fx={fx} csym={csym} />
              </div>
              <div>
                <div className="mb-1 text-[10px] font-bold uppercase tracking-widest text-bear">▼ Losers</div>
                <MoverList rows={t?.losers ?? []} icon={ArrowDownRight} tone="bear" fx={fx} csym={csym} />
              </div>
            </div>
          </Panel>
          <WhalePanel />
        </div>
      </section>
    </>
  );
}

/* ──────────────── Trade Ideas View ──────────────── */

function TradeIdeasView({ initialSymbol, onClearSymbol }: { initialSymbol: string | null; onClearSymbol: () => void }) {
  const [ideas, setIdeas] = useState<TradeIdea[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [selectedIdea, setSelectedIdea] = useState<TradeIdea | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [chartData, setChartData] = useState<any[]>([]);
  const [annotations, setAnnotations] = useState<any[]>([]);
  const [drawMode, setDrawMode] = useState<string | null>(null);
  const [drawStart, setDrawStart] = useState<any>(null);
  const [chartInterval, setChartInterval] = useState("15m");
  const [searchQuery, setSearchQuery] = useState("");
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [textAnnotationInput, setTextAnnotationInput] = useState("");
  const [pendingTextPoint, setPendingTextPoint] = useState<{ price: number; time: any } | null>(null);
  const [signalScore, setSignalScore] = useState<SignalScore | null>(null);
  const [detectedPatterns, setDetectedPatterns] = useState<ChartPattern[]>([]);
  const [chartTradeModal, setChartTradeModal] = useState<{ side: "long" | "short"; sl: number | null; tp: number | null } | null>(null);
  const chartRef = React.useRef<HTMLDivElement>(null);
  const chartInstanceRef = React.useRef<any>(null);
  const seriesRef = React.useRef<any>(null);

  useEffect(() => {
    fetchJson<TradeIdea[]>("/trade-ideas").then((data) => {
      if (data) setIdeas(data);
    });
    fetchJson("/trade-ideas/stats").then((data) => {
      if (data) setStats(data);
    });
    fetchJson<WatchlistItem[]>("/watchlist").then((data) => {
      if (data) setWatchlist(data);
    });
  }, []);

  // Handle navigation from log click
  useEffect(() => {
    if (initialSymbol) {
      setSelectedSymbol(initialSymbol);
      setSelectedIdea(null);
      onClearSymbol();
    }
  }, [initialSymbol]);

  // Load chart data when symbol or idea changes
  useEffect(() => {
    const symbol = selectedIdea?.symbol || selectedSymbol;
    if (!symbol) return;

    fetchJson<{ symbol: string; ohlcv: any[] }>(`/trade-ideas/ohlcv?symbol=${encodeURIComponent(symbol)}&interval=${chartInterval}&period=auto`)
      .then((data) => {
        if (data && data.ohlcv) {
          setChartData(data.ohlcv);
        }
      });
    
    fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(symbol)}`).then((data) => {
      if (data) setAnnotations(data);
    });
  }, [selectedIdea, selectedSymbol, chartInterval]);

  // Render chart
  useEffect(() => {
    if (!chartRef.current || chartData.length === 0) return;

    const candles: Candle[] = chartData
      .map((d: any) => ({
        time: d.time, open: d.open, high: d.high, low: d.low, close: d.close, volume: d.volume ?? 0,
      }))
      .sort((a, b) => a.time - b.time);
    const closes = candles.map((c) => c.close);
    const times = candles.map((c) => c.time);

    // Compute signals
    const signals = scoreSignals(candles);
    setSignalScore(signals);

    // Compute indicators
    const sma20Data = calcSma(closes, 20, times);
    const sma50Data = calcSma(closes, 50, times);
    const ema200Data = closes.length >= 200 ? calcEma(closes, 200, times) : [];
    const bbData = calcBB(closes, times, 20, 2);
    const rsiData = calcRsi(closes, times);
    const macdData = calcMacd(closes, times);
    const srLevels = detectSupportResistance(candles);

    // Chart setup
    const chart = createChart(chartRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#9ca3af', fontSize: 11 },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      width: chartRef.current.clientWidth,
      height: 700,
      crosshair: { mode: 1 },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
    });

    // ── Main pane: candlesticks ──
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#ef4444',
      borderDownColor: '#ef4444', borderUpColor: '#10b981',
      wickDownColor: '#ef4444', wickUpColor: '#10b981',
    });
    series.setData(candles as any);
    seriesRef.current = series;

    // ── Moving averages ──
    if (sma20Data.length > 0) {
      const s = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, lineStyle: 0, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      s.setData(sma20Data as any);
    }
    if (sma50Data.length > 0) {
      const s = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1, lineStyle: 0, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      s.setData(sma50Data as any);
    }
    if (ema200Data.length > 0) {
      const s = chart.addSeries(LineSeries, { color: '#a855f7', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      s.setData(ema200Data as any);
    }

    // ── Bollinger Bands ──
    if (bbData.upper.length > 0) {
      const upperSeries = chart.addSeries(LineSeries, { color: 'rgba(156,163,175,0.4)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      upperSeries.setData(bbData.upper as any);
      const lowerSeries = chart.addSeries(LineSeries, { color: 'rgba(156,163,175,0.4)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      lowerSeries.setData(bbData.lower as any);
    }

    // ── Support / Resistance ──
    srLevels.forEach((lvl) => {
      series.createPriceLine({
        price: lvl.price,
        color: lvl.type === 'support' ? '#10b981' : '#ef4444',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: lvl.type === 'support' ? `S ${lvl.price.toFixed(2)}` : `R ${lvl.price.toFixed(2)}`,
      });
    });

    // ── Prediction cone ──
    const lastCandle = candles[candles.length - 1];
    const atrVal = signals.atr ?? (lastCandle.close * 0.01);
    const direction = signals.score >= 2 ? 1 : signals.score <= -2 ? -1 : 0;
    if (direction !== 0 && times.length > 1) {
      const barInterval = times.length > 1 ? times[1] - times[0] : 900;
      const cone = projectCone(lastCandle.time, lastCandle.close, atrVal, direction, 12, barInterval);
      const coneColor = direction > 0 ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)';
      const coneUpper = chart.addSeries(AreaSeries, {
        topColor: coneColor, bottomColor: 'transparent',
        lineColor: direction > 0 ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)',
        lineWidth: 1, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      coneUpper.setData(cone.upper as any);
      const coneLower = chart.addSeries(LineSeries, {
        color: direction > 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)',
        lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      coneLower.setData(cone.lower as any);
    }

    // ── Chart Patterns ──
    const patterns = detectPatterns(candles);
    setDetectedPatterns(patterns);
    const priceMin = Math.min(...candles.map((c) => c.low));
    const priceMax = Math.max(...candles.map((c) => c.high));
    const priceRange = priceMax - priceMin;
    patterns.forEach((p) => {
      // Skip patterns with prices outside a reasonable range
      const allPrices = [p.upper.startPrice, p.upper.endPrice, p.lower.startPrice, p.lower.endPrice];
      if (allPrices.some((pr) => pr < priceMin - priceRange || pr > priceMax + priceRange)) return;

      const color = p.breakout === 'up' ? '#10b981' : p.breakout === 'down' ? '#ef4444' : '#f59e0b';

      // Solid trendlines between swing points
      const upperTrend = chart.addSeries(LineSeries, {
        color, lineWidth: 2, lineStyle: 0, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      upperTrend.setData([
        { time: p.upper.startTime, value: p.upper.startPrice },
        { time: p.upper.endTime, value: p.upper.endPrice },
      ] as any);
      const lowerTrend = chart.addSeries(LineSeries, {
        color, lineWidth: 2, lineStyle: 0, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      lowerTrend.setData([
        { time: p.lower.startTime, value: p.lower.startPrice },
        { time: p.lower.endTime, value: p.lower.endPrice },
      ] as any);

      // Project trendlines forward 10 bars
      const barInterval = times.length > 1 ? times[1] - times[0] : 900;
      const fwdBars = 10;

      const upperDuration = p.upper.endTime - p.upper.startTime;
      const upperSlopePerBar = upperDuration > 0 ? (p.upper.endPrice - p.upper.startPrice) / (upperDuration / barInterval) : 0;
      const fwdUpperTime = p.upper.endTime + fwdBars * barInterval;
      const fwdUpperPrice = p.upper.endPrice + upperSlopePerBar * fwdBars;

      const lowerDuration = p.lower.endTime - p.lower.startTime;
      const lowerSlopePerBar = lowerDuration > 0 ? (p.lower.endPrice - p.lower.startPrice) / (lowerDuration / barInterval) : 0;
      const fwdLowerTime = p.lower.endTime + fwdBars * barInterval;
      const fwdLowerPrice = p.lower.endPrice + lowerSlopePerBar * fwdBars;

      // Dashed forward extensions
      const upperFwd = chart.addSeries(LineSeries, {
        color: color === '#10b981' ? 'rgba(16,185,129,0.8)' : color === '#ef4444' ? 'rgba(239,68,68,0.8)' : 'rgba(245,158,11,0.8)',
        lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      upperFwd.setData([
        { time: p.upper.endTime, value: p.upper.endPrice },
        { time: fwdUpperTime, value: fwdUpperPrice },
      ] as any);
      const lowerFwd = chart.addSeries(LineSeries, {
        color: color === '#10b981' ? 'rgba(16,185,129,0.8)' : color === '#ef4444' ? 'rgba(239,68,68,0.8)' : 'rgba(245,158,11,0.8)',
        lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      lowerFwd.setData([
        { time: p.lower.endTime, value: p.lower.endPrice },
        { time: fwdLowerTime, value: fwdLowerPrice },
      ] as any);

      // Midline projection showing expected breakout direction
      const midStartTime = Math.max(p.upper.endTime, p.lower.endTime);
      const midStartPrice = (p.upper.endPrice + p.lower.endPrice) / 2;
      const midEndTime = Math.max(fwdUpperTime, fwdLowerTime);
      const midEndPrice = (fwdUpperPrice + fwdLowerPrice) / 2;
      const midFwd = chart.addSeries(LineSeries, {
        color: p.breakout === 'up' ? 'rgba(16,185,129,0.9)' : p.breakout === 'down' ? 'rgba(239,68,68,0.9)' : 'rgba(245,158,11,0.9)',
        lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false,
      });
      midFwd.setData([
        { time: midStartTime, value: midStartPrice },
        { time: midEndTime, value: midEndPrice },
      ] as any);

      // Projected breakout target line
      if (p.breakout !== 'either' && p.target > priceMin - priceRange && p.target < priceMax + priceRange) {
        series.createPriceLine({
          price: p.target,
          color,
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: `Target ${p.target.toFixed(2)}`,
        });
      }
    });

    // ── Trade idea lines ──
    if (selectedIdea) {
      series.createPriceLine({ price: selectedIdea.entry_price, color: '#3b82f6', lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title: 'Entry' });
      if (selectedIdea.stop_loss) series.createPriceLine({ price: selectedIdea.stop_loss, color: '#ef4444', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: 'SL' });
      if (selectedIdea.take_profit) series.createPriceLine({ price: selectedIdea.take_profit, color: '#10b981', lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: 'TP' });
    }

    // ── Annotations ──
    annotations.forEach((ann) => {
      if (ann.type === 'hline' && ann.data.price) {
        series.createPriceLine({ price: ann.data.price, color: ann.color || '#fbbf24', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: ann.data.label || '' });
      } else if (ann.type === 'trendline' && ann.data.start && ann.data.end) {
        const trendline = chart.addSeries(LineSeries, { color: ann.color || '#a78bfa', lineWidth: 2, lineStyle: 0, crosshairMarkerVisible: false });
        trendline.setData([
          { time: ann.data.start.time, value: ann.data.start.price },
          { time: ann.data.end.time, value: ann.data.end.price },
        ]);
      } else if (ann.type === 'zone' && ann.data.top && ann.data.bottom) {
        series.createPriceLine({ price: ann.data.top, color: ann.color || '#3b82f6', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
        series.createPriceLine({ price: ann.data.bottom, color: ann.color || '#3b82f6', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
      } else if (ann.type === 'text' && ann.data.price && ann.data.time) {
        series.createPriceLine({ price: ann.data.price, color: '#fbbf24', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: ann.data.text || 'Note' });
      }
    });

    // ── Volume pane ──
    const volumePane = chart.addPane();
    volumePane.setStretchFactor(0.15);
    const volumeSeries = volumePane.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
    });
    volumeSeries.setData(candles.map((c) => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(16,185,129,0.5)' : 'rgba(239,68,68,0.5)',
    })) as any);

    // ── RSI pane ──
    if (rsiData.length > 0) {
      const rsiPane = chart.addPane();
      rsiPane.setStretchFactor(0.15);
      const rsiSeries = rsiPane.addSeries(LineSeries, {
        color: '#a78bfa', lineWidth: 1, crosshairMarkerVisible: false,
        priceLineVisible: false, lastValueVisible: true,
      });
      rsiSeries.setData(rsiData as any);
      // Overbought / oversold reference lines
      const ob = rsiPane.addSeries(LineSeries, { color: 'rgba(239,68,68,0.3)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      ob.setData(rsiData.map((p) => ({ time: p.time, value: 70 })) as any);
      const os = rsiPane.addSeries(LineSeries, { color: 'rgba(16,185,129,0.3)', lineWidth: 1, lineStyle: 2, crosshairMarkerVisible: false, priceLineVisible: false, lastValueVisible: false });
      os.setData(rsiData.map((p) => ({ time: p.time, value: 30 })) as any);
    }

    // ── MACD pane ──
    if (macdData.line.length > 0) {
      const macdPane = chart.addPane();
      macdPane.setStretchFactor(0.15);
      const macdLine = macdPane.addSeries(LineSeries, {
        color: '#3b82f6', lineWidth: 1, crosshairMarkerVisible: false,
        priceLineVisible: false, lastValueVisible: true,
      });
      macdLine.setData(macdData.line as any);
      if (macdData.signal.length > 0) {
        const sigLine = macdPane.addSeries(LineSeries, {
          color: '#f97316', lineWidth: 1, crosshairMarkerVisible: false,
          priceLineVisible: false, lastValueVisible: false,
        });
        sigLine.setData(macdData.signal as any);
      }
      if (macdData.histogram.length > 0) {
        const histSeries = macdPane.addSeries(HistogramSeries, {
          priceLineVisible: false, lastValueVisible: false,
        });
        histSeries.setData(macdData.histogram as any);
      }
    }

    // ── Drawing tools click handler ──
    if (drawMode) {
      chart.subscribeClick((param) => {
        if (!param.point || !param.seriesData) return;
        const barData = param.seriesData.get(series) as any;
        const price = barData?.close;
        const time = param.time;
        if (price === undefined || !time) return;

        const symbol = selectedIdea?.symbol || selectedSymbol;
        if (!symbol) return;

        if (drawMode === 'hline') {
          fetch(`${API}/annotations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, type: 'hline', data: { price }, color: '#fbbf24' }),
          }).then(() => {
            fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(symbol)}`).then((data) => {
              if (data) setAnnotations(data);
            });
          });
          setDrawMode(null);
        } else if (drawMode === 'trendline') {
          if (!drawStart) {
            setDrawStart({ price, time });
          } else {
            fetch(`${API}/annotations`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                symbol, type: 'trendline',
                data: { start: drawStart, end: { price, time } },
                color: '#a78bfa',
              }),
            }).then(() => {
              fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(symbol)}`).then((data) => {
                if (data) setAnnotations(data);
              });
            });
            setDrawStart(null);
            setDrawMode(null);
          }
        } else if (drawMode === 'zone') {
          if (!drawStart) {
            setDrawStart({ price });
          } else {
            const top = Math.max(drawStart.price, price);
            const bottom = Math.min(drawStart.price, price);
            fetch(`${API}/annotations`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                symbol, type: 'zone',
                data: { top, bottom },
                color: '#3b82f6',
              }),
            }).then(() => {
              fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(symbol)}`).then((data) => {
                if (data) setAnnotations(data);
              });
            });
            setDrawStart(null);
            setDrawMode(null);
          }
        } else if (drawMode === 'text') {
          setPendingTextPoint({ price, time });
          setDrawMode(null);
        }
      });
    }

    chart.timeScale().fitContent();
    chartInstanceRef.current = chart;

    const handleResize = () => {
      if (chartRef.current) chart.applyOptions({ width: chartRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }
    };
  }, [chartData, selectedIdea, annotations, drawMode]);

  const activeIdeas = ideas.filter(i => i.status === 'active');
  const closedIdeas = ideas.filter(i => i.status === 'closed');
  const currentSymbol = selectedIdea?.symbol || selectedSymbol;

  const deleteAnnotation = (annId: string) => {
    fetch(`${API}/annotations/${annId}`, { method: 'DELETE' }).then(() => {
      if (currentSymbol) {
        fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(currentSymbol)}`).then((data) => {
          if (data) setAnnotations(data);
        });
      }
    });
  };

  return (
    <section className="mx-auto max-w-[1600px] px-4 py-4">
      {/* Stats bar */}
      {stats && stats.total > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
          {[
            { label: "TOTAL", value: stats.total },
            { label: "ACTIVE", value: stats.active },
            { label: "CLOSED", value: stats.closed },
            { label: "WIN RATE", value: `${stats.win_rate.toFixed(0)}%` },
            { label: "WINS", value: stats.wins, tone: "bull" },
            { label: "LOSSES", value: stats.losses, tone: "bear" },
            { label: "AVG P&L", value: `${signed(stats.avg_pnl)}%`, tone: stats.avg_pnl >= 0 ? "bull" : "bear" },
            { label: "TP/SL", value: `${stats.hit_tp}/${stats.hit_sl}` },
          ].map((s) => (
            <div key={s.label} className="rounded-sm border border-border bg-card px-3 py-2">
              <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-muted-foreground">{s.label}</div>
              <div className={`text-sm font-bold tabular-nums ${s.tone === "bull" ? "text-bull" : s.tone === "bear" ? "text-bear" : "text-foreground"}`}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        {/* Left sidebar */}
        <div className="flex flex-col gap-4">
          {/* Search bar */}
          <div className="rounded-sm border border-border bg-card p-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value.toUpperCase())}
              placeholder="Search assets..."
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none"
            />
            {searchQuery && watchlist.length > 0 && (
              <div className="mt-2 max-h-[200px] overflow-y-auto space-y-1">
                {watchlist
                  .filter((w) => w.pair.toUpperCase().includes(searchQuery))
                  .slice(0, 10)
                  .map((w) => (
                    <button key={w.pair} onClick={() => { setSelectedSymbol(w.pair); setSelectedIdea(null); setSearchQuery(""); }}
                      className={`w-full rounded-sm border px-2 py-1.5 text-left text-xs transition ${selectedSymbol === w.pair ? 'border-primary bg-primary/10' : 'border-border/50 hover:border-primary/50'}`}>
                      <span className="font-bold">{w.pair}</span>
                      <span className="ml-2 text-muted-foreground">{w.asset_class}</span>
                      {w.price && <span className="ml-2 tabular-nums text-muted-foreground">{fmtPx(w.price)}</span>}
                    </button>
                  ))}
              </div>
            )}
          </div>

          {/* Active Ideas */}
          <div className="rounded-sm border border-border bg-card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-foreground">
              Active Ideas ({activeIdeas.length})
            </h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {activeIdeas.map((idea) => (
                <div key={idea.id} className={`rounded-sm border p-3 text-left transition ${selectedIdea?.id === idea.id ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/50'}`}>
                  <button onClick={() => { setSelectedIdea(idea); setSelectedSymbol(null); }} className="w-full text-left">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-bold">{idea.symbol}</span>
                      <span className={`text-xs font-bold uppercase ${idea.side === 'long' ? 'text-bull' : 'text-bear'}`}>{idea.side}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">Entry: {fmtPx(idea.entry_price)}</div>
                    {idea.stop_loss && <div className="text-xs text-bear">SL: {fmtPx(idea.stop_loss)}</div>}
                    {idea.take_profit && <div className="text-xs text-bull">TP: {fmtPx(idea.take_profit)}</div>}
                  </button>
                  <button onClick={(e) => { e.stopPropagation(); fetch(`${API}/trade-ideas/${idea.id}/close`, { method: 'PUT' }).then(() => { fetchJson<TradeIdea[]>("/trade-ideas").then((data) => { if (data) setIdeas(data); }); }); }}
                    className="mt-2 w-full rounded-sm border border-bear/40 px-2 py-1 text-[9px] font-bold uppercase tracking-wider text-bear/70 transition hover:border-bear hover:bg-bear/10 hover:text-bear">
                    Delete
                  </button>
                </div>
              ))}
              {activeIdeas.length === 0 && <div className="text-xs text-muted-foreground">No active ideas</div>}
            </div>
          </div>

          {closedIdeas.length > 0 && (
            <div className="flex flex-1 flex-col rounded-sm border border-border bg-card p-4">
              <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">Closed ({Math.min(closedIdeas.length, 10)})</h3>
              <div className="flex-1 space-y-2 overflow-y-auto">
                {closedIdeas.slice(0, 10).map((idea) => (
                  <button key={idea.id} onClick={() => { setSelectedIdea(idea); setSelectedSymbol(null); }}
                    className={`w-full rounded-sm border p-2 text-left transition opacity-60 hover:opacity-100 ${selectedIdea?.id === idea.id ? 'border-primary bg-primary/10' : 'border-border hover:border-primary/50'}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold">{idea.symbol}</span>
                      {idea.outcome_pnl !== null && (
                        <span className={`text-xs font-bold ${idea.outcome_pnl >= 0 ? 'text-bull' : 'text-bear'}`}>{signed(idea.outcome_pnl)}%</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Chart area */}
        <div className="rounded-sm border border-border bg-card p-4">
          {currentSymbol ? (
            <>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-bold">{currentSymbol}</h2>
                  {selectedIdea && (
                    <div className="text-xs text-muted-foreground">{selectedIdea.side.toUpperCase()} • {selectedIdea.asset_class}</div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {selectedIdea && (
                    <div className="text-right text-xs">
                      <div className="text-muted-foreground">Created {formatDistanceToNow(new Date(selectedIdea.created_at))} ago</div>
                      {selectedIdea.confidence && <div className="text-primary">Confidence: {(selectedIdea.confidence * 100).toFixed(0)}%</div>}
                    </div>
                  )}
                </div>
              </div>

              {/* Toolbar */}
              <div className="mb-2 flex flex-wrap items-center gap-2 border-b border-border pb-2">
                {/* Interval selector */}
                <select value={chartInterval} onChange={(e) => setChartInterval(e.target.value)}
                  className="rounded-sm border border-border bg-background px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground focus:border-primary focus:outline-none">
                  <option value="1m">1m</option>
                  <option value="5m">5m</option>
                  <option value="15m">15m</option>
                  <option value="30m">30m</option>
                  <option value="1h">1H</option>
                  <option value="1d">1D</option>
                </select>

                <div className="h-4 w-px bg-border" />

                {/* Drawing tools */}
                {(['hline', 'trendline', 'zone', 'text'] as const).map((tool) => (
                  <button key={tool} onClick={() => { setDrawMode(drawMode === tool ? null : tool); setDrawStart(null); }}
                    className={`rounded-sm border px-3 py-1 text-[10px] font-bold uppercase tracking-widest transition ${drawMode === tool ? 'border-primary bg-primary/20 text-primary' : 'border-border text-muted-foreground hover:border-primary/50'}`}>
                    {tool === 'hline' ? 'H-Line' : tool === 'trendline' ? 'Trend' : tool === 'zone' ? 'Zone' : 'Text'}
                  </button>
                ))}
                <span className={`text-[10px] self-center ${drawMode ? 'text-primary' : 'text-muted-foreground'}`}>
                  {drawMode === 'hline' && 'Click chart to place line'}
                  {drawMode === 'trendline' && (drawStart ? 'Click end point' : 'Click start point')}
                  {drawMode === 'zone' && (drawStart ? 'Click second price level' : 'Click first price level')}
                  {drawMode === 'text' && 'Click chart to place text note'}
                </span>
                <div className="ml-auto flex gap-2">
                  {/* Buy button with auto-filled SL/TP from patterns */}
                  <button onClick={() => {
                    if (!currentSymbol) return;
                    const pattern = detectedPatterns[0];
                    const latestIdea = ideas.find((i) => i.symbol === currentSymbol && i.status === 'active');
                    const side = (pattern?.breakout === 'down' ? 'short' : pattern?.breakout === 'up' ? 'long' : latestIdea?.side ?? 'long') as "long" | "short";
                    const sl = pattern && pattern.breakout !== 'either'
                      ? (side === 'long' ? pattern.lower.endPrice : pattern.upper.endPrice)
                      : latestIdea?.stop_loss ?? null;
                    const tp = pattern && pattern.breakout !== 'either'
                      ? pattern.target
                      : latestIdea?.take_profit ?? null;
                    setChartTradeModal({ side, sl, tp });
                  }}
                    className="rounded-sm border border-blue-500/60 bg-blue-500/15 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-blue-400 transition hover:border-blue-400 hover:bg-blue-500/25">
                    Buy
                  </button>
                  {/* Scalp idea button */}
                  <button onClick={(e) => {
                    if (!currentSymbol) return;
                    const btn = e.currentTarget;
                    btn.disabled = true; btn.textContent = "AI thinking...";
                    fetch(`${API}/trade-ideas/generate?symbol=${encodeURIComponent(currentSymbol)}&timeframe=scalp`, {
                      method: 'POST',
                    }).then((res) => res.json()).then((data) => {
                      btn.disabled = false; btn.textContent = "Scalp";
                      fetchJson<TradeIdea[]>("/trade-ideas").then((newIdeas) => {
                        if (newIdeas) {
                          setIdeas(newIdeas);
                          const latest = newIdeas.find((i) => i.symbol === currentSymbol && i.status === 'active');
                          if (latest) setSelectedIdea(latest);
                        }
                      });
                      fetchJson<{ symbol: string; ohlcv: any[] }>(`/trade-ideas/ohlcv?symbol=${encodeURIComponent(currentSymbol)}&interval=${chartInterval}&period=auto`)
                        .then((d) => { if (d?.ohlcv) setChartData(d.ohlcv); });
                      if (data.status === "no_setup") {
                        alert(`AI couldn't find a scalp setup: ${data.reason}`);
                      } else if (data.detail) {
                        alert(`Error: ${data.detail}`);
                      }
                    }).catch(() => {
                      btn.disabled = false; btn.textContent = "Scalp";
                      alert("Failed to generate idea");
                    });
                  }}
                    className="rounded-sm border border-primary/50 bg-primary/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-primary transition hover:border-primary hover:bg-primary/20">
                    Scalp
                  </button>
                  {/* Swing idea button */}
                  <button onClick={(e) => {
                    if (!currentSymbol) return;
                    const btn = e.currentTarget;
                    btn.disabled = true; btn.textContent = "AI thinking...";
                    fetch(`${API}/trade-ideas/generate?symbol=${encodeURIComponent(currentSymbol)}&timeframe=swing`, {
                      method: 'POST',
                    }).then((res) => res.json()).then((data) => {
                      btn.disabled = false; btn.textContent = "Swing";
                      fetchJson<TradeIdea[]>("/trade-ideas").then((newIdeas) => {
                        if (newIdeas) {
                          setIdeas(newIdeas);
                          const latest = newIdeas.find((i) => i.symbol === currentSymbol && i.status === 'active');
                          if (latest) setSelectedIdea(latest);
                        }
                      });
                      fetchJson<{ symbol: string; ohlcv: any[] }>(`/trade-ideas/ohlcv?symbol=${encodeURIComponent(currentSymbol)}&interval=${chartInterval}&period=auto`)
                        .then((d) => { if (d?.ohlcv) setChartData(d.ohlcv); });
                      if (data.status === "no_setup") {
                        alert(`AI couldn't find a swing setup: ${data.reason}`);
                      } else if (data.detail) {
                        alert(`Error: ${data.detail}`);
                      }
                    }).catch(() => {
                      btn.disabled = false; btn.textContent = "Swing";
                      alert("Failed to generate idea");
                    });
                  }}
                    className="rounded-sm border border-bull/50 bg-bull/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-bull transition hover:border-bull hover:bg-bull/20">
                    Swing
                  </button>
                  <button onClick={() => {
                    if (!chartRef.current) return;
                    const canvas = chartRef.current.querySelector('canvas');
                    if (canvas) {
                      const link = document.createElement('a');
                      link.download = `${currentSymbol}-chart.png`;
                      link.href = canvas.toDataURL();
                      link.click();
                    }
                  }}
                    className="rounded-sm border border-border px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground transition hover:border-primary hover:text-primary">
                    Export
                  </button>
                </div>
              </div>

              {/* Signal summary bar */}
              {signalScore && (
                <div className="mb-2 flex flex-wrap items-center gap-3 rounded-sm border border-border/60 bg-background/40 px-3 py-2 text-[10px]">
                  <span className={`font-bold uppercase tracking-widest ${
                    signalScore.overall.includes('BUY') ? 'text-bull'
                      : signalScore.overall.includes('SELL') ? 'text-bear'
                        : 'text-muted-foreground'
                  }`}>{signalScore.overall}</span>
                  <span className="h-3 w-px bg-border" />
                  <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3 rounded" style={{ background: '#f59e0b' }} /> <span className="text-muted-foreground">SMA20</span></span>
                  <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3 rounded" style={{ background: '#3b82f6' }} /> <span className="text-muted-foreground">SMA50</span></span>
                  <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3 rounded border-b border-dashed" style={{ borderColor: '#a855f7' }} /> <span className="text-muted-foreground">EMA200</span></span>
                  <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3 rounded border-b border-dashed" style={{ borderColor: '#9ca3af' }} /> <span className="text-muted-foreground">BB</span></span>
                  <span className="ml-auto flex items-center gap-3">
                    <span className="text-muted-foreground">RSI <span className={`font-bold tabular-nums ${signalScore.rsi && signalScore.rsi > 70 ? 'text-bear' : signalScore.rsi && signalScore.rsi < 30 ? 'text-bull' : 'text-foreground'}`}>{signalScore.rsi?.toFixed(0) ?? '—'}</span><span className="ml-1 text-[9px]">{signalScore.rsiLabel}</span></span>
                    <span className="text-muted-foreground">MACD <span className={`font-bold ${signalScore.macdCross === 'bullish' ? 'text-bull' : signalScore.macdCross === 'bearish' ? 'text-bear' : 'text-foreground'}`}>{signalScore.macdCross}</span></span>
                    <span className="text-muted-foreground">Trend <span className={`font-bold ${signalScore.trend === 'uptrend' ? 'text-bull' : signalScore.trend === 'downtrend' ? 'text-bear' : 'text-foreground'}`}>{signalScore.trend}</span></span>
                    <span className="text-muted-foreground">BB <span className="font-bold">{signalScore.bollingerPos}</span></span>
                    <span className="text-muted-foreground">Vol <span className="font-bold">{signalScore.volumeTrend}</span></span>
                    {signalScore.atrPct && <span className="text-muted-foreground">ATR <span className="font-bold tabular-nums">{signalScore.atrPct.toFixed(2)}%</span></span>}
                  </span>
                  {detectedPatterns.length > 0 && detectedPatterns.map((p, i) => (
                    <span key={i} className="flex items-center gap-2 rounded-sm border border-border/50 px-2 py-0.5">
                      <span className={`font-bold uppercase ${p.breakout === 'up' ? 'text-bull' : p.breakout === 'down' ? 'text-bear' : 'text-primary'}`}>{p.type}</span>
                      <span className={`font-bold ${p.breakout === 'up' ? 'text-bull' : p.breakout === 'down' ? 'text-bear' : 'text-primary'}`}>
                        {p.breakout === 'up' ? '▲' : p.breakout === 'down' ? '▼' : '◆'} {p.breakout}
                      </span>
                      <span className="text-muted-foreground">{(p.confidence * 100).toFixed(0)}%</span>
                      {p.breakout !== 'either' && <span className="tabular-nums text-foreground">@ {fmtPx(p.target)}</span>}
                    </span>
                  ))}
                </div>
              )}

              {pendingTextPoint && (
                <div className="mb-2 flex items-center gap-2 rounded-sm border border-primary/50 bg-primary/5 px-3 py-2">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-primary">Text:</span>
                  <input
                    type="text"
                    value={textAnnotationInput}
                    onChange={(e) => setTextAnnotationInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && textAnnotationInput.trim()) {
                        const sym = selectedIdea?.symbol || selectedSymbol;
                        if (!sym) return;
                        fetch(`${API}/annotations`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            symbol: sym, type: 'text',
                            data: { price: pendingTextPoint.price, time: pendingTextPoint.time, text: textAnnotationInput.trim() },
                            color: '#fbbf24',
                          }),
                        }).then(() => {
                          fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(sym)}`).then((data) => {
                            if (data) setAnnotations(data);
                          });
                        });
                        setTextAnnotationInput("");
                        setPendingTextPoint(null);
                      }
                    }}
                    placeholder="Type annotation and press Enter..."
                    autoFocus
                    className="flex-1 rounded-sm border border-border bg-background px-2 py-1 text-xs font-mono focus:border-primary focus:outline-none"
                  />
                  <button
                    onClick={() => {
                      const sym = selectedIdea?.symbol || selectedSymbol;
                      if (!sym || !textAnnotationInput.trim()) return;
                      fetch(`${API}/annotations`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          symbol: sym, type: 'text',
                          data: { price: pendingTextPoint.price, time: pendingTextPoint.time, text: textAnnotationInput.trim() },
                          color: '#fbbf24',
                        }),
                      }).then(() => {
                        fetchJson<any[]>(`/annotations?symbol=${encodeURIComponent(sym)}`).then((data) => {
                          if (data) setAnnotations(data);
                        });
                      });
                      setTextAnnotationInput("");
                      setPendingTextPoint(null);
                    }}
                    className="rounded-sm border border-primary/50 bg-primary/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-primary transition hover:border-primary">
                    Add
                  </button>
                  <button
                    onClick={() => { setPendingTextPoint(null); setTextAnnotationInput(""); }}
                    className="rounded-sm border border-border px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground transition hover:border-bear hover:text-bear">
                    Cancel
                  </button>
                </div>
              )}
              <div ref={chartRef} className="w-full" />

              {/* Annotations list */}
              {annotations.length > 0 && (
                <div className="mt-3 border-t border-border pt-3">
                  <h4 className="mb-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Annotations ({annotations.length})</h4>
                  <div className="space-y-1 max-h-[120px] overflow-y-auto">
                    {annotations.map((ann) => (
                      <div key={ann.id} className="flex items-center justify-between rounded-sm border border-border/50 px-2 py-1 text-xs">
                        <span>
                          <span className="font-bold uppercase text-muted-foreground">{ann.type}</span>
                          {ann.data.price && <span className="ml-2">{fmtPx(ann.data.price)}</span>}
                          {ann.data.label && <span className="ml-2 text-muted-foreground">{ann.data.label}</span>}
                        </span>
                        <button onClick={() => deleteAnnotation(ann.id)} className="text-bear/60 hover:text-bear">×</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedIdea?.reasoning && (
                <div className="mt-4 rounded-sm border border-border bg-background/50 p-3">
                  <h4 className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">Reasoning</h4>
                  <p className="text-xs text-foreground">{selectedIdea.reasoning}</p>
                </div>
              )}

              {/* Pattern predictions */}
              {detectedPatterns.length > 0 && (
                <div className="mt-4 rounded-sm border border-border bg-background/50 p-4">
                  <h4 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">
                    Pattern Analysis & Predicted Outcome
                  </h4>
                  <div className="space-y-3">
                    {detectedPatterns.map((p, i) => {
                      const isBullish = p.breakout === 'up';
                      const isBearish = p.breakout === 'down';
                      return (
                        <div key={i} className="rounded-sm border border-border/60 p-3">
                          <div className="mb-2 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                              <span className={`rounded-sm px-2 py-0.5 text-xs font-bold uppercase ${
                                isBullish ? 'bg-bull/15 text-bull' : isBearish ? 'bg-bear/15 text-bear' : 'bg-primary/15 text-primary'
                              }`}>
                                {p.type}
                              </span>
                              <span className={`text-xs font-bold ${
                                isBullish ? 'text-bull' : isBearish ? 'text-bear' : 'text-primary'
                              }`}>
                                {isBullish ? '▲ BULLISH BREAKOUT' : isBearish ? '▼ BEARISH BREAKOUT' : '◆ EITHER DIRECTION'}
                              </span>
                            </div>
                            <span className="text-xs tabular-nums text-muted-foreground">
                              Confidence: <span className="font-bold text-foreground">{(p.confidence * 100).toFixed(0)}%</span>
                            </span>
                          </div>
                          <div className="grid grid-cols-3 gap-3 text-xs">
                            <div>
                              <div className="text-[9px] uppercase tracking-widest text-muted-foreground">Upper Bound</div>
                              <div className="font-bold tabular-nums">{fmtPx(p.upper.endPrice)}</div>
                            </div>
                            <div>
                              <div className="text-[9px] uppercase tracking-widest text-muted-foreground">Lower Bound</div>
                              <div className="font-bold tabular-nums">{fmtPx(p.lower.endPrice)}</div>
                            </div>
                            <div>
                              <div className="text-[9px] uppercase tracking-widest text-muted-foreground">Target</div>
                              <div className={`font-bold tabular-nums ${isBullish ? 'text-bull' : isBearish ? 'text-bear' : 'text-primary'}`}>
                                {p.breakout !== 'either' ? fmtPx(p.target) : '—'}
                              </div>
                            </div>
                          </div>
                          <div className="mt-2 text-xs text-muted-foreground">
                            {isBullish && `Price is consolidating in a ${p.type}. Most likely outcome: breakout above ${fmtPx(p.upper.endPrice)} targeting ${fmtPx(p.target)} (${p.confidence >= 0.6 ? 'high' : 'moderate'} probability).`}
                            {isBearish && `Price is consolidating in a ${p.type}. Most likely outcome: breakdown below ${fmtPx(p.lower.endPrice)} targeting ${fmtPx(p.target)} (${p.confidence >= 0.6 ? 'high' : 'moderate'} probability).`}
                            {!isBullish && !isBearish && `Price is in a ${p.type} formation. Breakout could go either direction — wait for confirmation before entering.`}
                          </div>
                          {p.breakout !== 'either' && currentSymbol && (
                            <button onClick={() => {
                              const lastBar = chartData[chartData.length - 1] as any;
                              const entry = lastBar?.close ?? 0;
                              const patternSide = p.breakout === 'up' ? 'long' : 'short';
                              const sl = patternSide === 'long' ? p.lower.endPrice : p.upper.endPrice;
                              const tp = p.target;
                              fetch(`${API}/trade-ideas`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                  symbol: currentSymbol,
                                  asset_class: selectedIdea?.asset_class ?? watchlist.find((w) => w.pair === currentSymbol)?.asset_class ?? 'stock',
                                  side: patternSide,
                                  entry_price: entry,
                                  stop_loss: sl,
                                  take_profit: tp,
                                  confidence: p.confidence,
                                  reasoning: `Pattern: ${p.type}, ${p.breakout} breakout, confidence ${(p.confidence * 100).toFixed(0)}%`,
                                }),
                              }).then(() => {
                                fetchJson<TradeIdea[]>("/trade-ideas").then((data) => {
                                  if (data) setIdeas(data);
                                });
                              });
                            }}
                              className={`mt-3 w-full rounded-sm border py-2 text-[10px] font-bold uppercase tracking-widest transition ${
                                isBullish
                                  ? 'border-bull/50 bg-bull/10 text-bull hover:border-bull hover:bg-bull/20'
                                  : 'border-bear/50 bg-bear/10 text-bear hover:border-bear hover:bg-bear/20'
                              }`}>
                              Trade This Pattern
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex h-[500px] items-center justify-center text-muted-foreground">
              Select a trade idea or click a symbol in the log to view the chart
            </div>
          )}
        </div>
      </div>

      {chartTradeModal && currentSymbol && (
        <TradeModal
          pair={currentSymbol}
          assetClass={(selectedIdea?.asset_class ?? watchlist.find((w) => w.pair === currentSymbol)?.asset_class ?? "stock") as AssetClass}
          onClose={() => setChartTradeModal(null)}
          refresh={() => { fetchJson<TradeIdea[]>("/trade-ideas").then((data) => { if (data) setIdeas(data); }); }}
          initialSide={chartTradeModal.side}
          initialSL={chartTradeModal.sl}
          initialTP={chartTradeModal.tp}
        />
      )}

      {/* Analytics section */}
      {stats && stats.closed > 0 && (
        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          {/* By Asset Class */}
          <div className="rounded-sm border border-border bg-card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">By Asset Class</h3>
            <div className="space-y-2">
              {stats.by_asset.map((a: any) => (
                <div key={a.asset_class} className="flex items-center justify-between text-xs">
                  <span className="font-bold uppercase">{a.asset_class}</span>
                  <div className="flex items-center gap-3 tabular-nums">
                    <span className="text-muted-foreground">{a.total} trades</span>
                    <span className={a.wins / a.total >= 0.5 ? 'text-bull' : 'text-bear'}>{((a.wins / a.total) * 100).toFixed(0)}% WR</span>
                    <span className={(a.avg_pnl ?? 0) >= 0 ? 'text-bull' : 'text-bear'}>{signed(a.avg_pnl ?? 0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* By Side */}
          <div className="rounded-sm border border-border bg-card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">By Side</h3>
            <div className="space-y-2">
              {stats.by_side.map((s: any) => (
                <div key={s.side} className="flex items-center justify-between text-xs">
                  <span className={`font-bold uppercase ${s.side === 'long' ? 'text-bull' : 'text-bear'}`}>{s.side}</span>
                  <div className="flex items-center gap-3 tabular-nums">
                    <span className="text-muted-foreground">{s.total} trades</span>
                    <span>{((s.wins / s.total) * 100).toFixed(0)}% WR</span>
                    <span className={(s.avg_pnl ?? 0) >= 0 ? 'text-bull' : 'text-bear'}>{signed(s.avg_pnl ?? 0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Performance */}
          <div className="rounded-sm border border-border bg-card p-4">
            <h3 className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-muted-foreground">Recent Results</h3>
            <div className="space-y-1 max-h-[200px] overflow-y-auto">
              {stats.recent.map((r: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-xs border-b border-border/30 py-1">
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{r.symbol}</span>
                    <span className={`text-[9px] font-bold uppercase ${r.side === 'long' ? 'text-bull' : 'text-bear'}`}>{r.side}</span>
                  </div>
                  <span className={`font-bold tabular-nums ${r.outcome_pnl >= 0 ? 'text-bull' : 'text-bear'}`}>{signed(r.outcome_pnl)}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/* ──────────────── Assets View ──────────────── */

function AssetsView({ watchlist, positions, refresh, fx, csym }:
  { watchlist: WatchlistItem[]; positions: Position[]; refresh: () => void; fx: number; csym: string }) {
  const [filter, setFilter] = useState<"all" | AssetClass>("all");
  const [tradeModal, setTradeModal] = useState<{ pair: string; assetClass: AssetClass } | null>(null);

  const filtered = filter === "all" ? watchlist : watchlist.filter((w) => w.asset_class === filter);
  const grouped = ASSET_CLASS_ORDER.map((ac) => ({
    cls: ac,
    items: filtered.filter((w) => w.asset_class === ac),
  })).filter((g) => g.items.length > 0);

  return (
    <section className="mx-auto max-w-[1600px] px-4 py-4">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {(["all", ...ASSET_CLASS_ORDER] as const).map((k) => {
            const count = k === "all" ? watchlist.length : watchlist.filter((w) => w.asset_class === k).length;
            return (
              <button key={k} onClick={() => setFilter(k)}
                className={`rounded-sm border px-3 py-1 text-[10px] font-bold uppercase tracking-widest transition ${
                  filter === k
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:border-primary/40"
                }`}>
                {k} <span className="ml-1 text-muted-foreground/60">{count}</span>
              </button>
            );
          })}
        </div>
        <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{filtered.length} instruments</span>
      </div>

      <div className="flex flex-col gap-6">
        {grouped.map((g) => (
          <div key={g.cls}>
            <div className="mb-2 flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-sm ${ASSET_COLOR[g.cls]}`} />
              <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">// {g.cls.toUpperCase()}</span>
              <span className="text-[10px] text-muted-foreground">{g.items.length} instruments</span>
            </div>
            <div className="terminal-panel overflow-hidden rounded-sm">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                    <Th>Symbol</Th><Th right>Price</Th><Th right>Change</Th>
                    <Th right>Open Pos</Th><Th right>Unrealized</Th><Th />
                  </tr>
                </thead>
                <tbody>
                  {g.items.map((w) => {
                    const openPos = positions.filter((p) => p.pair === w.pair);
                    const totalPnl = openPos.reduce((s, p) => s + p.pnl, 0);
                    return (
                      <tr key={w.pair} className="border-b border-border/40 transition hover:bg-card/50">
                        <td className="py-3 pl-4">
                          <span className="font-bold">{w.pair}</span>
                        </td>
                        <Td right>{w.price !== null ? fmtPx(w.price) : "—"}</Td>
                        <Td right tone={w.change_pct !== null ? (w.change_pct >= 0 ? "bull" : "bear") : undefined}>
                          {w.change_pct !== null ? `${w.change_pct >= 0 ? "+" : ""}${w.change_pct.toFixed(2)}%` : "—"}
                        </Td>
                        <Td right muted>{openPos.length > 0 ? `${openPos.length} pos` : "—"}</Td>
                        <Td right tone={totalPnl !== 0 ? (totalPnl >= 0 ? "bull" : "bear") : undefined}>
                          {openPos.length > 0 ? `${signed(totalPnl * fx)} ${csym}` : "—"}
                        </Td>
                        <td className="py-3 pr-4 text-right">
                          <div className="flex justify-end gap-1">
                            <button onClick={() => setTradeModal({ pair: w.pair, assetClass: w.asset_class })}
                              className="rounded-sm border border-bull/50 bg-bull/10 px-2.5 py-1 text-[9px] font-bold uppercase tracking-wider text-bull transition hover:border-bull hover:bg-bull/20">
                              Buy
                            </button>
                            <button onClick={() => setTradeModal({ pair: w.pair, assetClass: w.asset_class })}
                              className="rounded-sm border border-bear/50 bg-bear/10 px-2.5 py-1 text-[9px] font-bold uppercase tracking-wider text-bear transition hover:border-bear hover:bg-bear/20">
                              Sell
                            </button>
                            {openPos.length > 0 && (
                              <button
                                onClick={async () => {
                                  for (const p of openPos) {
                                    await fetch(`${API}/positions/${p.id}`, { method: "DELETE" });
                                  }
                                  refresh();
                                }}
                                className="rounded-sm border border-border px-2.5 py-1 text-[9px] font-bold uppercase tracking-wider text-muted-foreground transition hover:border-primary hover:text-primary">
                                Close All
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>

      {tradeModal && (
        <TradeModal pair={tradeModal.pair} assetClass={tradeModal.assetClass}
          onClose={() => setTradeModal(null)} refresh={refresh} />
      )}
    </section>
  );
}

/* ──────────────── Trade Modal ──────────────── */

function TradeModal({ pair, assetClass, onClose, refresh, initialSide, initialSL, initialTP }:
  { pair: string; assetClass: AssetClass; onClose: () => void; refresh: () => void;
    initialSide?: "long" | "short"; initialSL?: number | null; initialTP?: number | null }) {
  const [side, setSide] = useState<"long" | "short">(initialSide ?? "long");
  const [size, setSize] = useState("");
  const [confidence, setConfidence] = useState("0.75");
  const [submitting, setSubmitting] = useState(false);

  const [stopLoss, setStopLoss] = useState<number | null>(initialSL ?? null);
  const [takeProfit, setTakeProfit] = useState<number | null>(initialTP ?? null);

  const defaults: Record<AssetClass, string> = { forex: "100000", stock: "50", crypto: "1", cfd: "5", futures: "5" };
  useEffect(() => { setSize(defaults[assetClass]); }, [assetClass]);

  const submit = async (orderSide: "long" | "short") => {
    setSide(orderSide);
    setSubmitting(true);
    const res = await fetch(`${API}/positions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pair, asset_class: assetClass, side: orderSide,
        size: parseFloat(size), confidence: parseFloat(confidence),
      }),
    });
    setSubmitting(false);
    if (res.ok) { onClose(); refresh(); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="terminal-panel w-full max-w-md rounded-sm" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">// NEW POSITION</span>
            <span className="font-display text-sm font-bold">{pair}</span>
            <span className={`rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase ${
              ASSET_COLOR[assetClass] ? `bg-primary/10 text-primary` : "bg-primary/10 text-primary"
            }`}>{assetClass}</span>
          </div>
          <button onClick={onClose} className="text-muted-foreground transition hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>

        <div className="space-y-4 p-4">
          <div>
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              Size {assetClass === "forex" ? "(units)" : assetClass === "crypto" ? "(coins)" : assetClass === "cfd" ? "(contracts)" : "(shares)"}
            </label>
            <input type="number" value={size} onChange={(e) => setSize(e.target.value)} step="any"
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm font-bold tabular-nums text-foreground outline-none transition focus:border-primary" />
          </div>

          <div>
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Confidence (0-1)</label>
            <input type="number" value={confidence} onChange={(e) => setConfidence(e.target.value)} min="0" max="1" step="0.05"
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm font-bold tabular-nums text-foreground outline-none transition focus:border-primary" />
          </div>

          {(stopLoss || takeProfit) && (
            <div className="rounded-sm border border-border/60 bg-background/40 p-3">
              <div className="mb-2 text-center text-[9px] font-bold uppercase tracking-[0.2em] text-muted-foreground">AI Predicted Levels</div>
              <div className="flex items-center justify-center gap-3">
                <div className="text-center">
                  <div className="text-[9px] uppercase tracking-widest text-bear">Stop Loss</div>
                  <div className="text-sm font-bold tabular-nums text-bear">{stopLoss ? fmtPx(stopLoss) : '—'}</div>
                </div>
                <button onClick={() => { const tmp = stopLoss; setStopLoss(takeProfit); setTakeProfit(tmp); }}
                  className="rounded-sm border border-border px-2 py-1 text-[10px] font-bold text-muted-foreground transition hover:border-primary hover:text-primary"
                  title="Swap SL and TP">
                  ⇄
                </button>
                <div className="text-center">
                  <div className="text-[9px] uppercase tracking-widest text-bull">Take Profit</div>
                  <div className="text-sm font-bold tabular-nums text-bull">{takeProfit ? fmtPx(takeProfit) : '—'}</div>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => submit("short")} disabled={submitting || !size}
              className="rounded-sm border border-bear bg-bear/15 py-2.5 text-xs font-bold uppercase tracking-[0.2em] text-bear transition hover:bg-bear/25 disabled:opacity-40">
              {submitting ? "..." : `Sell ${pair}`}
            </button>
            <button onClick={() => submit("long")} disabled={submitting || !size}
              className="rounded-sm border border-bull bg-bull/15 py-2.5 text-xs font-bold uppercase tracking-[0.2em] text-bull transition hover:bg-bull/25 disabled:opacity-40">
              {submitting ? "..." : `Buy ${pair}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ──────────────── UI primitives ──────────────── */

function Panel({ title, sub, right, children }:
  { title: string; sub?: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="terminal-panel rounded-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">// {title}</span>
          {sub && <span className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">{sub}</span>}
        </div>
        {right ?? <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-bull" />}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function Kpi({ icon: Icon, label, value, tone, sub }:
  { icon: typeof Activity; label: string; value: string; tone?: "bull" | "bear"; sub?: string }) {
  const toneCls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-foreground";
  return (
    <div className="terminal-panel rounded-sm p-4">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
        <span>{label}</span>
        <Icon className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
      </div>
      <div className={`mt-2 font-display text-2xl font-bold tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="mt-1 text-[10px] uppercase tracking-widest text-muted-foreground">{sub}</div>}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "bull" | "bear" }) {
  const toneCls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "";
  return (
    <div className="rounded-sm border border-border/60 bg-background/40 px-3 py-2">
      <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">{label}</div>
      <div className={`mt-1 font-display text-base font-bold tabular-nums ${toneCls}`}>{value}</div>
    </div>
  );
}

function Th({ children, right }: { children?: React.ReactNode; right?: boolean }) {
  return <th className={`py-2 ${right ? "pr-2 text-right" : "pl-0 text-left"} font-normal`}>{children}</th>;
}
function Td({ children, right, muted, tone }:
  { children: React.ReactNode; right?: boolean; muted?: boolean; tone?: "bull" | "bear" }) {
  const toneCls = tone === "bull" ? "text-bull font-bold"
    : tone === "bear" ? "text-bear font-bold"
    : muted ? "text-muted-foreground" : "";
  return <td className={`py-2.5 tabular-nums ${right ? "pr-2 text-right" : ""} ${toneCls}`}>{children}</td>;
}
function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="inline-flex items-center gap-2">
      <div className="h-1 w-12 overflow-hidden rounded-sm bg-secondary">
        <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-muted-foreground">{pct}</span>
    </div>
  );
}

function WhalePanel() {
  const [whales, setWhales] = useState<any[]>([]);
  useEffect(() => {
    const load = () => fetchJson<any[]>("/whales").then((data) => { if (data) setWhales(data); });
    load();
    const i = setInterval(load, 120_000);
    return () => clearInterval(i);
  }, []);
  return (
    <Panel title="WHALE ACTIVITY" sub={`${whales.length} signals`}>
      <div className="max-h-[280px] space-y-1.5 overflow-y-auto pr-1">
        {whales.length === 0 && (
          <div className="py-6 text-center text-xs text-muted-foreground">No whale signals detected.</div>
        )}
        {whales.map((w, i) => (
          <div key={i} className="flex items-start gap-2 border-b border-border/40 py-2 text-xs">
            <span className={`shrink-0 rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
              w.type === 'btc_transfer' ? 'bg-primary/15 text-primary'
                : w.signal === 'accumulation' || w.direction === 'surge' ? 'bg-bull/15 text-bull'
                  : 'bg-bear/15 text-bear'
            }`}>
              {w.type === 'btc_transfer' ? 'WHALE'
                : w.signal === 'accumulation' ? 'BUY'
                  : w.signal === 'distribution' ? 'SELL'
                    : w.direction === 'surge' ? 'PUMP' : 'DUMP'}
            </span>
            <div className="min-w-0">
              {w.type === 'btc_transfer' && (
                <span className="text-foreground/90">{w.amount.toFixed(0)} BTC moved</span>
              )}
              {w.type?.includes('volume_spike') && (
                <span className="text-foreground/90">
                  <span className="font-bold">{w.symbol}</span> {w.volume_ratio}x vol, {w.price_change_pct >= 0 ? '+' : ''}{w.price_change_pct?.toFixed(1)}%
                </span>
              )}
              {w.type === 'large_move' && (
                <span className="text-foreground/90">
                  <span className="font-bold">{w.symbol}</span> {w.change_pct >= 0 ? '+' : ''}{w.change_pct?.toFixed(1)}% in 24h
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function MoverList({ rows, icon: Icon, tone, fx, csym }:
  { rows: Position[]; icon: typeof ArrowUpRight; tone: "bull" | "bear"; fx: number; csym: string }) {
  if (rows.length === 0)
    return <div className="py-4 text-center text-xs text-muted-foreground">No positions.</div>;
  const toneCls = tone === "bull" ? "text-bull" : "text-bear";
  return (
    <div className="space-y-1">
      {rows.map((p) => (
        <div key={p.id} className="flex items-center justify-between border-b border-border/40 py-2 text-xs">
          <div className="flex items-center gap-2">
            <Icon className={`h-3.5 w-3.5 ${toneCls}`} />
            <span className="font-bold">{p.pair}</span>
            <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{p.asset_class}</span>
          </div>
          <div className="flex items-center gap-4 tabular-nums">
            <span className="text-muted-foreground">{fmtPx(p.current_price)}</span>
            <span className={`font-bold ${toneCls}`}>{signed(p.pnl * fx)} {csym}</span>
            <span className={`text-[10px] ${toneCls}`}>{signed(p.pnl_pct)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────────────── Charts ──────────────── */

function EquityChart({ data, fx, csym }: { data: { t: string; eq: number }[]; fx: number; csym: string }) {
  if (data.length < 2)
    return <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">Waiting for data...</div>;
  const W = 720, H = 220, P = 24;
  const xs = data.map((d) => +new Date(d.t)), ys = data.map((d) => d.eq);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const sx = (t: number) => P + ((t - xmin) / Math.max(xmax - xmin, 1)) * (W - 2 * P);
  const sy = (v: number) => H - P - ((v - ymin) / Math.max(ymax - ymin, 1)) * (H - 2 * P);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${sx(+new Date(d.t)).toFixed(1)},${sy(d.eq).toFixed(1)}`).join(" ");
  const area = `${path} L${sx(xmax).toFixed(1)},${H - P} L${sx(xmin).toFixed(1)},${H - P} Z`;
  const last = data[data.length - 1].eq, first = data[0].eq;
  const tone = last >= first ? "var(--color-bull)" : "var(--color-bear)";
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[220px] w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={P} x2={W - P} y1={P + f * (H - 2 * P)} y2={P + f * (H - 2 * P)}
                stroke="currentColor" className="text-border" strokeDasharray="2 4" />
        ))}
        <path d={area} fill={tone} opacity="0.12" />
        <path d={path} fill="none" stroke={tone} strokeWidth="1.5" />
      </svg>
      <div className="absolute right-3 top-2 text-right">
        <div className="text-[10px] uppercase tracking-widest text-muted-foreground">Last</div>
        <div className="font-display text-sm font-bold tabular-nums">{csym}{fmt(last * fx, 0)}</div>
      </div>
      <div className="absolute left-3 bottom-2 text-[10px] uppercase tracking-widest text-muted-foreground">
        Range {csym}{fmt(ymin * fx, 0)} – {csym}{fmt(ymax * fx, 0)}
      </div>
    </div>
  );
}

function DailyPnlChart({ data }: { data: { d: string; v: number }[] }) {
  if (data.length === 0)
    return <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">No daily data.</div>;
  const W = 360, H = 220, P = 24;
  const max = Math.max(...data.map((d) => Math.abs(d.v)), 1);
  const bw = (W - 2 * P) / data.length;
  const zero = H / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[220px] w-full">
      <line x1={P} x2={W - P} y1={zero} y2={zero} stroke="currentColor" className="text-border" />
      {data.map((d, i) => {
        const h = ((Math.abs(d.v) / max) * (H - 2 * P)) / 2;
        const x = P + i * bw + bw * 0.15;
        const w = bw * 0.7;
        const y = d.v >= 0 ? zero - h : zero;
        return (
          <rect key={d.d} x={x} y={y} width={w} height={h}
                fill={d.v >= 0 ? "var(--color-bull)" : "var(--color-bear)"} opacity="0.85" />
        );
      })}
    </svg>
  );
}

/* ──────────────── Settings Modal ──────────────── */

interface ProviderInfo {
  name: string;
  needs_key: boolean;
  models: string[];
}

function SettingsModal({ onClose, refresh }: { onClose: () => void; refresh: () => void }) {
  const [providers, setProviders] = useState<Record<string, ProviderInfo>>({});
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [numCtx, setNumCtx] = useState(8192);
  const [dynamicModels, setDynamicModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [equity, setEquity] = useState("100000");
  const [displayCurrency, setDisplayCurrency] = useState("USD");
  const [riskProfile, setRiskProfile] = useState("moderate");
  const [allowedClasses, setAllowedClasses] = useState<string[]>(["forex", "stock", "crypto", "cfd", "futures"]);
  const [exposureLimit, setExposureLimit] = useState(80);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      fetchJson<Record<string, ProviderInfo>>("/llm/providers"),
      fetchJson<{ provider: string; model: string; api_key: string; num_ctx: number }>("/llm/config"),
      fetchJson<{ starting_equity: number; display_currency: string; risk_profile: string; allowed_asset_classes: string; exposure_limit: number }>("/config"),
    ]).then(([provs, config, portfolioConfig]) => {
      if (provs) setProviders(provs);
      if (config) {
        setProvider(config.provider);
        setModel(config.model);
        if (config.num_ctx) setNumCtx(config.num_ctx);
      }
      if (portfolioConfig) {
        setEquity(String(portfolioConfig.starting_equity));
        setDisplayCurrency(portfolioConfig.display_currency || "USD");
        setRiskProfile(portfolioConfig.risk_profile || "moderate");
        if (portfolioConfig.allowed_asset_classes) {
          setAllowedClasses(portfolioConfig.allowed_asset_classes.split(",").map((s: string) => s.trim()));
        }
        if (portfolioConfig.exposure_limit !== undefined) {
          setExposureLimit(portfolioConfig.exposure_limit);
        }
      }
    });
  }, []);

  const currentProvider = providers[provider];
  const models = currentProvider?.models ?? [];

  const handleProviderChange = (newProvider: string) => {
    setProvider(newProvider);
    setModel("");
    if (newProvider === "lmstudio") {
      setLoadingModels(true);
      fetchJson<{ models: string[]; error?: string }>("/llm/lmstudio/models").then((res) => {
        setDynamicModels(res?.models ?? []);
        setLoadingModels(false);
      });
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const llmBody: Record<string, any> = { provider, model, num_ctx: numCtx };
      if (apiKey) llmBody.api_key = apiKey;
      await Promise.all([
        fetch(`${API}/llm/config`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(llmBody),
        }),
        fetch(`${API}/config`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ starting_equity: parseFloat(equity) || 100000, display_currency: displayCurrency, risk_profile: riskProfile, allowed_asset_classes: allowedClasses.join(","), exposure_limit: exposureLimit }),
        }),
      ]);
      setSaved(true);
      refresh();
      setTimeout(() => onClose(), 1000);
    } catch {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md rounded-sm border border-border bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-display text-sm font-bold uppercase tracking-[0.2em]">Settings</h2>
          <button onClick={onClose} className="text-muted-foreground transition hover:text-foreground"><X className="h-4 w-4" /></button>
        </div>

        <div className="space-y-4">
          <div className="pb-3 border-b border-border">
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Starting Equity</label>
            <input type="number" value={equity} onChange={(e) => setEquity(e.target.value)}
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none" />
          </div>

          <div className="pb-3 border-b border-border">
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Display Currency</label>
            <div className="flex gap-2">
              {(["USD", "CZK"] as const).map((c) => (
                <button key={c} onClick={() => setDisplayCurrency(c)}
                  className={`flex-1 rounded-sm border px-3 py-2 text-xs font-bold uppercase tracking-widest transition ${
                    displayCurrency === c
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40"
                  }`}>{c === "USD" ? "$ USD" : "Kč CZK"}</button>
              ))}
            </div>
          </div>

          <div className="pb-3 border-b border-border">
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Risk Profile</label>
            <div className="flex gap-2">
              {([
                { key: "conservative", label: "Safe", color: "bordersky-400" },
                { key: "moderate", label: "Moderate", color: "border-primary" },
                { key: "aggressive", label: "Aggressive", color: "border-bear" },
              ] as const).map((p) => (
                <button key={p.key} onClick={() => setRiskProfile(p.key)}
                  className={`flex-1 rounded-sm border px-2 py-2 text-[10px] font-bold uppercase tracking-widest transition ${
                    riskProfile === p.key
                      ? `${p.color} bg-primary/10 text-foreground`
                      : "border-border text-muted-foreground hover:border-primary/40"
                  }`}>{p.label}</button>
              ))}
            </div>
            <p className="mt-1 text-[9px] text-muted-foreground">
              {riskProfile === "conservative" && "Max 2 trades/cycle, tight stops, 50% max exposure"}
              {riskProfile === "moderate" && "Max 3 trades/cycle, balanced stops, 80% max exposure"}
              {riskProfile === "aggressive" && "Max 5 trades/cycle, wide stops, 95% max exposure"}
            </p>
          </div>

          <div className="pb-3 border-b border-border">
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Trade Assets</label>
            <div className="flex flex-wrap gap-2">
              {(["forex", "stock", "crypto", "cfd", "futures"] as const).map((ac) => (
                <button key={ac} onClick={() => {
                  setAllowedClasses(prev => prev.includes(ac) ? prev.filter(c => c !== ac) : [...prev, ac]);
                }}
                  className={`rounded-sm border px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest transition ${
                    allowedClasses.includes(ac)
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground/40 hover:border-primary/40"
                  }`}>{ac}</button>
              ))}
            </div>
            <p className="mt-1 text-[9px] text-muted-foreground">AI will only trade selected asset classes</p>
          </div>

          <div className="pb-3 border-b border-border">
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
              Max Exposure: {exposureLimit >= 999 ? "Unlimited" : `${exposureLimit}%`}
            </label>
            <input type="range" min={50} max={1000} step={10} value={exposureLimit}
              onChange={(e) => setExposureLimit(Number(e.target.value))}
              className="w-full accent-primary" />
            <div className="flex justify-between text-[9px] text-muted-foreground mt-1">
              <span>50% (safe)</span>
              <span>80% (default)</span>
              <span>Unlimited</span>
            </div>
          </div>

          <div className="pt-1">
            <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">AI Model</span>
          </div>

          <div>
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Provider</label>
            <select value={provider} onChange={(e) => handleProviderChange(e.target.value)}
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none">
              <option value="">Select provider...</option>
              {Object.entries(providers).map(([key, info]) => (
                <option key={key} value={key}>{info.name}{info.needs_key ? " (API key required)" : " (free)"}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Model</label>
            <select value={model} onChange={(e) => setModel(e.target.value)}
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none">
              <option value="">Select model...</option>
              {models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          {currentProvider?.needs_key && (
            <div>
              <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">API Key</label>
              <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste your API key here..."
                className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none" />
              <p className="mt-1 text-[10px] text-muted-foreground">Leave empty to keep existing key</p>
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Context Length</label>
            <select value={numCtx} onChange={(e) => setNumCtx(Number(e.target.value))}
              className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono focus:border-primary focus:outline-none">
              <option value={4096}>4,096 tokens</option>
              <option value={8192}>8,192 tokens</option>
              <option value={16384}>16,384 tokens</option>
              <option value={32768}>32,768 tokens</option>
              <option value={65536}>65,536 tokens</option>
            </select>
            <p className="mt-1 text-[10px] text-muted-foreground">Must match or be less than your model's loaded context. Ollama only.</p>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button onClick={onClose}
            className="rounded-sm border border-border px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground transition hover:border-primary hover:text-primary">
            Cancel
          </button>
          <button onClick={handleSave} disabled={!provider || !model || saving}
            className="rounded-sm border border-bull/60 bg-bull/10 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-bull transition hover:border-bull disabled:opacity-40">
            {saved ? "Saved!" : saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
