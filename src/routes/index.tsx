import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  Activity, Wallet, TrendingUp, AlertTriangle, Power,
  Gauge, Layers, ArrowUpRight, ArrowDownRight, ShieldAlert,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({ meta: [{ title: "NEXUS // AI Trading Terminal" }] }),
  component: Dashboard,
});

type AssetClass = "forex" | "stock" | "crypto";
type Position = {
  id: string; pair: string; asset_class: AssetClass; side: "long" | "short";
  size: number; entry_price: number; current_price: number;
  pnl: number; pnl_pct: number; opened_at: string; confidence: number;
};
type Trade = {
  id: string; pair: string; side: "long" | "short"; size: number;
  entry_price: number; exit_price: number; pnl: number; closed_at: string;
};
type AiLog = {
  id: string; level: "info" | "warn" | "error"; action: string;
  pair: string | null; message: string; created_at: string;
};

const STARTING_EQUITY = 100_000;
const fmt = (n: number, d = 2) =>
  n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPx = (n: number) => (n >= 1000 ? fmt(n, 2) : fmt(n, 4));
const signed = (n: number, d = 2) => `${n >= 0 ? "+" : ""}${fmt(n, d)}`;

// ────────── Mock seed (deterministic-ish) ──────────
const SEED_POSITIONS: Omit<Position, "current_price" | "pnl" | "pnl_pct">[] = [
  { id: "p1", pair: "EUR/USD", asset_class: "forex", side: "long",  size: 250_000, entry_price: 1.0824, opened_at: hoursAgo(6),  confidence: 0.82 },
  { id: "p2", pair: "GBP/JPY", asset_class: "forex", side: "short", size: 120_000, entry_price: 198.42, opened_at: hoursAgo(14), confidence: 0.61 },
  { id: "p3", pair: "USD/CHF", asset_class: "forex", side: "long",  size: 180_000, entry_price: 0.8932, opened_at: hoursAgo(3),  confidence: 0.74 },
  { id: "p4", pair: "AUD/USD", asset_class: "forex", side: "short", size: 200_000, entry_price: 0.6612, opened_at: hoursAgo(22), confidence: 0.55 },
  { id: "p5", pair: "NVDA",    asset_class: "stock", side: "long",  size: 80,      entry_price: 138.20, opened_at: hoursAgo(28), confidence: 0.88 },
  { id: "p6", pair: "AAPL",    asset_class: "stock", side: "long",  size: 150,     entry_price: 224.50, opened_at: hoursAgo(40), confidence: 0.71 },
  { id: "p7", pair: "TSLA",    asset_class: "stock", side: "short", size: 60,      entry_price: 248.10, opened_at: hoursAgo(9),  confidence: 0.66 },
  { id: "p8", pair: "MSFT",    asset_class: "stock", side: "long",  size: 50,      entry_price: 432.90, opened_at: hoursAgo(54), confidence: 0.79 },
  { id: "p9", pair: "SPY",     asset_class: "stock", side: "long",  size: 90,      entry_price: 558.40, opened_at: hoursAgo(72), confidence: 0.69 },
  { id: "p10",pair: "BTC/USD", asset_class: "crypto",side: "long",  size: 0.85,    entry_price: 64_120, opened_at: hoursAgo(18), confidence: 0.76 },
  { id: "p11",pair: "ETH/USD", asset_class: "crypto",side: "long",  size: 12,      entry_price: 3_280,  opened_at: hoursAgo(31), confidence: 0.62 },
];

const SEED_TRADES: Trade[] = Array.from({ length: 22 }).map((_, i) => {
  const pairs = ["EUR/USD","GBP/USD","NVDA","AAPL","BTC/USD","TSLA","USD/JPY","ETH/USD","SPY","AMD","MSFT"];
  const pair = pairs[i % pairs.length];
  const side: "long" | "short" = i % 3 === 0 ? "short" : "long";
  const entry = pair.includes("/") ? 1 + Math.random() * 200 : 50 + Math.random() * 500;
  const drift = (Math.random() - 0.42) * entry * 0.04;
  const exit = entry + drift;
  const size = pair.includes("/") ? (pair.startsWith("BTC") ? 0.5 : 100_000) : 50;
  const pnl = (side === "long" ? exit - entry : entry - exit) * size;
  return {
    id: `t${i}`, pair, side, size,
    entry_price: entry, exit_price: exit, pnl,
    closed_at: daysAgo(22 - i),
  };
});

const SEED_LOGS: AiLog[] = [
  log(0,  "info",  "OPEN",   "EUR/USD", "Momentum + ECB hawkish tone. Entered long 250k @ 1.0824."),
  log(2,  "info",  "SIGNAL", "NVDA",    "Earnings drift + options flow bullish. Confidence 0.88."),
  log(5,  "warn",  "RISK",   null,      "Portfolio leverage approaching 2.1x. Trimming non-core size."),
  log(11, "info",  "REBAL",  null,      "Rebalanced FX vs equities to 45/45/10 target."),
  log(18, "info",  "OPEN",   "BTC/USD", "Breakout above 63.8k confirmed. Long 0.85 BTC @ 64,120."),
  log(25, "error", "ABORT",  "AUD/USD", "Iron ore data adverse. Aborted planned long."),
  log(33, "info",  "CLOSE",  "USD/JPY", "Closed +312 USD. Realized at session high."),
  log(48, "info",  "HOLD",   "MSFT",    "Conviction unchanged. Hold through cloud event."),
  log(62, "warn",  "DRAW",   null,      "Drawdown -1.2% intraday. Tightened stops 25 bps."),
  log(80, "info",  "OPEN",   "ETH/USD", "Mean-reversion long 12 ETH @ 3,280."),
  log(120,"info",  "SIGNAL", "TSLA",    "Delivery miss probability 64%. Initiated short hedge."),
  log(160,"info",  "REBAL",  null,      "Increased USD exposure +6% (DXY breakout)."),
  log(220,"info",  "CLOSE",  "AMD",     "Realized +$487 on AMD long. Target hit."),
  log(310,"warn",  "RISK",   null,      "Correlation spike between NVDA/AMD detected."),
  log(420,"info",  "OPEN",   "SPY",     "Index trend filter ON. Long SPY 90 sh @ 558.40."),
];

function hoursAgo(h: number) { return new Date(Date.now() - h * 3600_000).toISOString(); }
function daysAgo(d: number) { return new Date(Date.now() - d * 86400_000 + Math.random() * 3600_000).toISOString(); }
function log(minAgo: number, level: AiLog["level"], action: string, pair: string | null, message: string): AiLog {
  return { id: `l${Math.random().toString(36).slice(2,8)}`, level, action, pair, message,
           created_at: new Date(Date.now() - minAgo * 60_000).toISOString() };
}

function Dashboard() {
  const [now, setNow] = useState(() => new Date());
  const [assetFilter, setAssetFilter] = useState<"all" | AssetClass>("all");
  const [aiActive, setAiActive] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const i = setInterval(() => { setNow(new Date()); setTick((t) => t + 1); }, 2000);
    return () => clearInterval(i);
  }, []);

  // live mock prices that drift from seed entry
  const positions = useMemo<Position[]>(() => {
    return SEED_POSITIONS.map((p) => {
      // deterministic + tick-based wobble
      const seed = (p.id.charCodeAt(1) || 1) + tick * 0.6;
      const drift = Math.sin(seed * 0.37) * 0.012 + Math.cos(seed * 0.13) * 0.006;
      const current = p.entry_price * (1 + drift);
      const dir = p.side === "long" ? 1 : -1;
      const pnl = (current - p.entry_price) * p.size * dir;
      const pnlPct = ((current - p.entry_price) / p.entry_price) * 100 * dir;
      return { ...p, current_price: current, pnl, pnl_pct: pnlPct };
    });
  }, [tick]);

  const trades = SEED_TRADES;
  const logs = SEED_LOGS;

  const totals = useMemo(() => {
    const openPnl = positions.reduce((a, p) => a + p.pnl, 0);
    const realized = trades.reduce((a, t) => a + t.pnl, 0);
    const exposure = positions.reduce((a, p) => a + Math.abs(p.size * p.current_price), 0);
    const wins = trades.filter((t) => t.pnl > 0).length;
    const losses = trades.filter((t) => t.pnl < 0).length;
    const winRate = trades.length ? (wins / trades.length) * 100 : 0;
    const equity = STARTING_EQUITY + realized + openPnl;
    const leverage = exposure / Math.max(equity, 1);
    const avgWin = wins ? trades.filter((t) => t.pnl > 0).reduce((a, t) => a + t.pnl, 0) / wins : 0;
    const avgLoss = losses ? Math.abs(trades.filter((t) => t.pnl < 0).reduce((a, t) => a + t.pnl, 0) / losses) : 0;
    return { openPnl, realized, exposure, winRate, equity, leverage,
             openCount: positions.length, wins, losses, avgWin, avgLoss };
  }, [positions, trades]);

  const equitySeries = useMemo(() => {
    let eq = STARTING_EQUITY;
    const sorted = [...trades].sort((a, b) => +new Date(a.closed_at) - +new Date(b.closed_at));
    const pts = [{ t: sorted[0] ? +new Date(sorted[0].closed_at) : Date.now(), eq }];
    sorted.forEach((t) => { eq += t.pnl; pts.push({ t: +new Date(t.closed_at), eq }); });
    pts.push({ t: Date.now(), eq: eq + totals.openPnl });
    return pts;
  }, [trades, totals.openPnl]);

  const drawdown = useMemo(() => {
    let peak = -Infinity, maxDd = 0;
    equitySeries.forEach((p) => {
      peak = Math.max(peak, p.eq);
      maxDd = Math.min(maxDd, (p.eq - peak) / peak);
    });
    return maxDd * 100;
  }, [equitySeries]);

  const dailyPnl = useMemo(() => {
    const map = new Map<string, number>();
    trades.forEach((t) => {
      const d = new Date(t.closed_at).toISOString().slice(0, 10);
      map.set(d, (map.get(d) ?? 0) + t.pnl);
    });
    return Array.from(map.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([d, v]) => ({ d, v }));
  }, [trades]);

  const byAsset = useMemo(() => {
    const m = new Map<AssetClass, { exposure: number; pnl: number; count: number }>();
    positions.forEach((p) => {
      const cur = m.get(p.asset_class) ?? { exposure: 0, pnl: 0, count: 0 };
      cur.exposure += Math.abs(p.size * p.current_price);
      cur.pnl += p.pnl;
      cur.count += 1;
      m.set(p.asset_class, cur);
    });
    const total = Array.from(m.values()).reduce((a, b) => a + b.exposure, 0) || 1;
    return (["forex", "stock", "crypto"] as AssetClass[])
      .map((k) => ({ k, ...(m.get(k) ?? { exposure: 0, pnl: 0, count: 0 }),
                     pct: ((m.get(k)?.exposure ?? 0) / total) * 100 }));
  }, [positions]);

  const allocation = useMemo(() => {
    const map = new Map<string, number>();
    positions.forEach((p) => {
      const value = Math.abs(p.size * p.current_price);
      const key = p.pair.includes("/") ? p.pair.split("/")[0] : p.pair;
      map.set(key, (map.get(key) ?? 0) + value);
    });
    const total = Array.from(map.values()).reduce((a, b) => a + b, 0) || 1;
    return Array.from(map.entries())
      .map(([k, v]) => ({ ccy: k, value: v, pct: (v / total) * 100 }))
      .sort((a, b) => b.pct - a.pct);
  }, [positions]);

  const winners = useMemo(() => [...positions].sort((a, b) => b.pnl - a.pnl).slice(0, 3), [positions]);
  const losers  = useMemo(() => [...positions].sort((a, b) => a.pnl - b.pnl).slice(0, 3), [positions]);

  const filteredPositions = useMemo(
    () => (assetFilter === "all" ? positions : positions.filter((p) => p.asset_class === assetFilter)),
    [positions, assetFilter],
  );

  return (
    <main className="min-h-screen pb-12">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-2.5">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-bull" />
              <span className="font-display text-sm font-bold tracking-tight">NEXUS</span>
              <span className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">// AI TRADING TERMINAL</span>
            </div>
            <div className="hidden h-4 w-px bg-border md:block" />
            <div className="hidden items-center gap-3 text-[10px] uppercase tracking-[0.25em] text-muted-foreground md:flex">
              <span>
                <span className={aiActive ? "text-bull" : "text-bear"}>●</span> AI {aiActive ? "ACTIVE" : "HALTED"}
              </span>
              <span>SESSION: NY/LON</span>
              <span>{now.toUTCString().slice(17, 25)} UTC</span>
              <span>EQUITY ${fmt(totals.equity, 0)}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAiActive((v) => !v)}
              className={`flex items-center gap-2 rounded-sm border px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] transition ${
                aiActive
                  ? "border-border bg-card text-bear hover:border-bear/60"
                  : "border-bull/60 bg-bull/10 text-bull hover:border-bull"
              }`}
            >
              {aiActive ? <><Power className="h-3 w-3" /> Halt AI</> : <><Activity className="h-3 w-3" /> Resume AI</>}
            </button>
          </div>
        </div>
      </header>

      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 py-4 md:grid-cols-3 lg:grid-cols-6">
        <Kpi icon={Wallet}      label="Equity"          value={`$${fmt(totals.equity, 0)}`} sub={`start $${fmt(STARTING_EQUITY, 0)}`} />
        <Kpi icon={TrendingUp}  label="Unrealized P&L"  value={`${signed(totals.openPnl)} $`} tone={totals.openPnl >= 0 ? "bull" : "bear"} />
        <Kpi icon={Activity}    label="Realized (all)"  value={`${signed(totals.realized)} $`} tone={totals.realized >= 0 ? "bull" : "bear"} />
        <Kpi icon={Layers}      label="Exposure"        value={`$${fmt(totals.exposure, 0)}`} sub={`${totals.openCount} positions`} />
        <Kpi icon={Gauge}       label="Leverage"        value={`${totals.leverage.toFixed(2)}x`} tone={totals.leverage > 2 ? "bear" : undefined} />
        <Kpi icon={ShieldAlert} label="Max drawdown"    value={`${drawdown.toFixed(2)}%`} tone="bear" />
      </section>

      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 lg:grid-cols-[2fr_1fr]">
        <Panel title="EQUITY CURVE" sub={`since inception · ${signed(totals.equity - STARTING_EQUITY)} $`}>
          <EquityChart data={equitySeries} />
        </Panel>
        <Panel title="DAILY P&L" sub={`${dailyPnl.length} sessions`}>
          <DailyPnlChart data={dailyPnl} />
        </Panel>
      </section>

      <section className="mx-auto mt-3 grid max-w-[1600px] gap-3 px-4 lg:grid-cols-3">
        <Panel title="ASSET CLASS" sub="exposure split">
          <div className="space-y-3">
            {byAsset.map((a) => (
              <div key={a.k}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2">
                    <span className={`inline-block h-2 w-2 rounded-sm ${
                      a.k === "forex" ? "bg-primary" : a.k === "stock" ? "bg-chart-2" : "bg-chart-5"
                    }`} />
                    <span className="font-bold uppercase">{a.k}</span>
                    <span className="text-[10px] text-muted-foreground">{a.count} pos</span>
                  </span>
                  <span className="tabular-nums text-muted-foreground">{a.pct.toFixed(1)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-sm bg-secondary">
                  <div className={`h-full transition-all ${
                    a.k === "forex" ? "bg-primary" : a.k === "stock" ? "bg-chart-2" : "bg-chart-5"
                  }`} style={{ width: `${a.pct}%` }} />
                </div>
                <div className="mt-0.5 flex justify-between text-[10px] tabular-nums text-muted-foreground">
                  <span>${fmt(a.exposure, 0)}</span>
                  <span className={a.pnl >= 0 ? "text-bull" : "text-bear"}>{signed(a.pnl)} $</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="ALLOCATION" sub="by symbol / base ccy">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {allocation.map((a) => (
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
            <Metric label="Win rate"      value={`${totals.winRate.toFixed(0)}%`} tone={totals.winRate >= 50 ? "bull" : "bear"} />
            <Metric label="Trades"        value={String(trades.length)} />
            <Metric label="Wins"          value={String(totals.wins)}   tone="bull" />
            <Metric label="Losses"        value={String(totals.losses)} tone="bear" />
            <Metric label="Avg win"       value={`$${fmt(totals.avgWin)}`} tone="bull" />
            <Metric label="Avg loss"      value={`-$${fmt(totals.avgLoss)}`} tone="bear" />
            <Metric label="Profit factor"
                    value={totals.avgLoss > 0
                      ? (totals.avgWin * totals.wins / (totals.avgLoss * Math.max(totals.losses, 1))).toFixed(2)
                      : "∞"} tone="bull" />
            <Metric label="Net P&L" value={`${signed(totals.realized)} $`}
                    tone={totals.realized >= 0 ? "bull" : "bear"} />
          </div>
        </Panel>
      </section>

      <section className="mx-auto mt-3 grid max-w-[1600px] gap-3 px-4 lg:grid-cols-2">
        <Panel title="TOP WINNERS" sub="open positions">
          <MoverList rows={winners} icon={ArrowUpRight} tone="bull" />
        </Panel>
        <Panel title="TOP LOSERS" sub="open positions">
          <MoverList rows={losers} icon={ArrowDownRight} tone="bear" />
        </Panel>
      </section>

      <section className="mx-auto mt-3 max-w-[1600px] px-4">
        <Panel
          title="OPEN POSITIONS"
          sub={`${filteredPositions.length} shown`}
          right={
            <div className="flex items-center gap-1">
              {(["all", "forex", "stock", "crypto"] as const).map((k) => (
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
                  <Th right>Notional</Th><Th right>Conf</Th><Th right>Age</Th>
                </tr>
              </thead>
              <tbody>
                {filteredPositions.map((p) => {
                  const notional = Math.abs(p.size * p.current_price);
                  return (
                    <tr key={p.id} className="border-b border-border/40 transition hover:bg-card/50">
                      <td className="py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block h-1.5 w-1.5 rounded-full ${
                            p.asset_class === "crypto" ? "bg-chart-5"
                              : p.asset_class === "stock" ? "bg-chart-2" : "bg-primary"
                          }`} />
                          <span className="font-bold">{p.pair}</span>
                          <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{p.asset_class}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                          p.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"
                        }`}>{p.side}</span>
                      </td>
                      <Td right muted>{fmt(p.size, p.asset_class === "crypto" ? 4 : 0)}</Td>
                      <Td right muted>{fmtPx(p.entry_price)}</Td>
                      <Td right>{fmtPx(p.current_price)}</Td>
                      <Td right tone={p.pnl >= 0 ? "bull" : "bear"}>{signed(p.pnl)}</Td>
                      <Td right tone={p.pnl_pct >= 0 ? "bull" : "bear"}>{signed(p.pnl_pct)}%</Td>
                      <Td right muted>${fmt(notional, 0)}</Td>
                      <td className="py-2.5 pr-2 text-right"><ConfBar value={p.confidence} /></td>
                      <Td right muted>{formatDistanceToNow(new Date(p.opened_at))}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>

      <section className="mx-auto mt-3 grid max-w-[1600px] gap-3 px-4 lg:grid-cols-2">
        <Panel title="AI DECISION LOG" sub={`last ${logs.length} events`}>
          <div className="max-h-[420px] space-y-1 overflow-y-auto pr-1">
            {logs.map((l) => (
              <div key={l.id} className="grid grid-cols-[auto_auto_1fr_auto] items-start gap-3 border-b border-border/40 py-2 text-xs">
                <span className="font-mono text-[10px] text-muted-foreground">
                  {new Date(l.created_at).toLocaleTimeString("en-GB", { hour12: false })}
                </span>
                <span className={`rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
                  l.level === "error" ? "bg-bear/15 text-bear"
                    : l.level === "warn" ? "bg-primary/15 text-primary"
                    : "bg-bull/15 text-bull"
                }`}>{l.action}</span>
                <div className="min-w-0">
                  {l.pair && <span className="mr-2 font-bold">{l.pair}</span>}
                  <span className="text-foreground/90">{l.message}</span>
                </div>
                <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                  {formatDistanceToNow(new Date(l.created_at))}
                </span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="RECENT TRADES" sub="closed positions">
          <div className="max-h-[420px] overflow-y-auto pr-1">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                  <Th>Symbol</Th><Th>Side</Th><Th right>Entry</Th><Th right>Exit</Th>
                  <Th right>P&L</Th><Th right>Closed</Th>
                </tr>
              </thead>
              <tbody>
                {[...trades].reverse().map((t) => (
                  <tr key={t.id} className="border-b border-border/40">
                    <td className="py-2 font-bold">{t.pair}</td>
                    <td>
                      <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                        t.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"
                      }`}>{t.side}</span>
                    </td>
                    <Td right muted>{fmtPx(t.entry_price)}</Td>
                    <Td right>{fmtPx(t.exit_price)}</Td>
                    <Td right tone={t.pnl >= 0 ? "bull" : "bear"}>{signed(t.pnl)}</Td>
                    <Td right muted>{formatDistanceToNow(new Date(t.closed_at))}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>

      {!aiActive && (
        <div className="fixed bottom-4 left-1/2 z-40 -translate-x-1/2 rounded-sm border border-bear/60 bg-bear/10 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.3em] text-bear">
          <AlertTriangle className="mr-2 inline h-3 w-3" /> AI halted — no new positions will be opened
        </div>
      )}
    </main>
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

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
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

function MoverList({ rows, icon: Icon, tone }:
  { rows: Position[]; icon: typeof ArrowUpRight; tone: "bull" | "bear" }) {
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
            <span className={`font-bold ${toneCls}`}>{signed(p.pnl)} $</span>
            <span className={`text-[10px] ${toneCls}`}>{signed(p.pnl_pct)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────────────── Charts ──────────────── */

function EquityChart({ data }: { data: { t: number; eq: number }[] }) {
  if (data.length < 2)
    return <div className="flex h-[220px] items-center justify-center text-xs text-muted-foreground">Not enough data.</div>;
  const W = 720, H = 220, P = 24;
  const xs = data.map((d) => d.t), ys = data.map((d) => d.eq);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const sx = (t: number) => P + ((t - xmin) / Math.max(xmax - xmin, 1)) * (W - 2 * P);
  const sy = (v: number) => H - P - ((v - ymin) / Math.max(ymax - ymin, 1)) * (H - 2 * P);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${sx(d.t).toFixed(1)},${sy(d.eq).toFixed(1)}`).join(" ");
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
        <div className="font-display text-sm font-bold tabular-nums">${fmt(last, 0)}</div>
      </div>
      <div className="absolute left-3 bottom-2 text-[10px] uppercase tracking-widest text-muted-foreground">
        Range ${fmt(ymin, 0)} – ${fmt(ymax, 0)}
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
