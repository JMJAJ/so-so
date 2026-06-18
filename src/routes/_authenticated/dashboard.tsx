import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, LogOut, Wallet, TrendingUp, Brain, AlertTriangle, Power,
  Gauge, Layers, ArrowUpRight, ArrowDownRight, ShieldAlert, LineChart as LineIcon,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/_authenticated/dashboard")({
  head: () => ({ meta: [{ title: "Terminal // NEXUS" }] }),
  component: Dashboard,
});

type AssetClass = "forex" | "stock" | "crypto";
type Position = {
  id: string; pair: string; asset_class: AssetClass; side: "long" | "short";
  size: number; entry_price: number; current_price: number;
  pnl: number; pnl_pct: number; opened_at: string; confidence: number;
};
type Trade = {
  id: string; pair: string; side: string; size: number;
  entry_price: number; exit_price: number; pnl: number; closed_at: string;
};
type AiLog = {
  id: string; level: string; action: string;
  pair: string | null; message: string; created_at: string;
};

const STARTING_EQUITY = 100_000;
const fmt = (n: number, d = 2) =>
  n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPx = (n: number) => (n >= 1000 ? fmt(n, 2) : fmt(n, 4));
const signed = (n: number, d = 2) => `${n >= 0 ? "+" : ""}${fmt(n, d)}`;

function Dashboard() {
  const navigate = useNavigate();
  const [now, setNow] = useState(() => new Date());
  const [assetFilter, setAssetFilter] = useState<"all" | AssetClass>("all");
  useEffect(() => {
    const i = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(i);
  }, []);

  const positionsQ = useQuery({
    queryKey: ["positions"],
    queryFn: async (): Promise<Position[]> => {
      const { data, error } = await supabase
        .from("positions").select("*").order("opened_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Position[];
    },
  });
  const tradesQ = useQuery({
    queryKey: ["trades"],
    queryFn: async (): Promise<Trade[]> => {
      const { data, error } = await supabase
        .from("trades").select("*").order("closed_at", { ascending: true });
      if (error) throw error;
      return (data ?? []) as Trade[];
    },
  });
  const logsQ = useQuery({
    queryKey: ["ai_logs"],
    queryFn: async (): Promise<AiLog[]> => {
      const { data, error } = await supabase
        .from("ai_logs").select("*").order("created_at", { ascending: false }).limit(30);
      if (error) throw error;
      return (data ?? []) as AiLog[];
    },
  });

  const positions = positionsQ.data ?? [];
  const trades = tradesQ.data ?? [];
  const logs = logsQ.data ?? [];

  // ───────────── Aggregates ─────────────
  const totals = useMemo(() => {
    const openPnl = positions.reduce((a, p) => a + Number(p.pnl), 0);
    const realized = trades.reduce((a, t) => a + Number(t.pnl), 0);
    const exposure = positions.reduce(
      (a, p) => a + Math.abs(Number(p.size) * Number(p.current_price)),
      0,
    );
    const wins = trades.filter((t) => Number(t.pnl) > 0).length;
    const losses = trades.filter((t) => Number(t.pnl) < 0).length;
    const winRate = trades.length ? (wins / trades.length) * 100 : 0;
    const equity = STARTING_EQUITY + realized + openPnl;
    const leverage = exposure / Math.max(equity, 1);
    const avgWin = wins
      ? trades.filter((t) => t.pnl > 0).reduce((a, t) => a + t.pnl, 0) / wins
      : 0;
    const avgLoss = losses
      ? Math.abs(trades.filter((t) => t.pnl < 0).reduce((a, t) => a + t.pnl, 0) / losses)
      : 0;
    return {
      openPnl, realized, exposure, winRate, equity, leverage,
      openCount: positions.length, wins, losses, avgWin, avgLoss,
    };
  }, [positions, trades]);

  // Equity curve from trade history
  const equitySeries = useMemo(() => {
    let eq = STARTING_EQUITY;
    const pts = [{ t: trades[0] ? new Date(trades[0].closed_at).getTime() : Date.now(), eq }];
    trades.forEach((t) => {
      eq += Number(t.pnl);
      pts.push({ t: new Date(t.closed_at).getTime(), eq });
    });
    pts.push({ t: Date.now(), eq: eq + totals.openPnl });
    return pts;
  }, [trades, totals.openPnl]);

  // Max drawdown on equity series
  const drawdown = useMemo(() => {
    let peak = -Infinity, maxDd = 0;
    equitySeries.forEach((p) => {
      peak = Math.max(peak, p.eq);
      maxDd = Math.min(maxDd, (p.eq - peak) / peak);
    });
    return maxDd * 100;
  }, [equitySeries]);

  // Daily realized P&L
  const dailyPnl = useMemo(() => {
    const map = new Map<string, number>();
    trades.forEach((t) => {
      const d = new Date(t.closed_at).toISOString().slice(0, 10);
      map.set(d, (map.get(d) ?? 0) + Number(t.pnl));
    });
    return Array.from(map.entries())
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([d, v]) => ({ d, v }));
  }, [trades]);

  // Exposure by asset class
  const byAsset = useMemo(() => {
    const m = new Map<AssetClass, { exposure: number; pnl: number; count: number }>();
    positions.forEach((p) => {
      const cur = m.get(p.asset_class) ?? { exposure: 0, pnl: 0, count: 0 };
      cur.exposure += Math.abs(Number(p.size) * Number(p.current_price));
      cur.pnl += Number(p.pnl);
      cur.count += 1;
      m.set(p.asset_class, cur);
    });
    const total = Array.from(m.values()).reduce((a, b) => a + b.exposure, 0) || 1;
    return (["forex", "stock", "crypto"] as AssetClass[])
      .map((k) => ({ k, ...(m.get(k) ?? { exposure: 0, pnl: 0, count: 0 }), pct: ((m.get(k)?.exposure ?? 0) / total) * 100 }));
  }, [positions]);

  // Allocation by base currency / ticker
  const allocation = useMemo(() => {
    const map = new Map<string, number>();
    positions.forEach((p) => {
      const value = Math.abs(Number(p.size) * Number(p.current_price));
      const key = p.pair.includes("/") ? p.pair.split("/")[0] : p.pair;
      map.set(key, (map.get(key) ?? 0) + value);
    });
    const total = Array.from(map.values()).reduce((a, b) => a + b, 0) || 1;
    return Array.from(map.entries())
      .map(([k, v]) => ({ ccy: k, value: v, pct: (v / total) * 100 }))
      .sort((a, b) => b.pct - a.pct);
  }, [positions]);

  const winners = useMemo(
    () => [...positions].sort((a, b) => Number(b.pnl) - Number(a.pnl)).slice(0, 3),
    [positions],
  );
  const losers = useMemo(
    () => [...positions].sort((a, b) => Number(a.pnl) - Number(b.pnl)).slice(0, 3),
    [positions],
  );

  const filteredPositions = useMemo(
    () => (assetFilter === "all" ? positions : positions.filter((p) => p.asset_class === assetFilter)),
    [positions, assetFilter],
  );

  const signOut = async () => {
    await supabase.auth.signOut();
    navigate({ to: "/auth", replace: true });
  };

  return (
    <main className="min-h-screen pb-12">
      {/* TOP BAR */}
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
              <span><span className="text-bull">●</span> AI ACTIVE</span>
              <span>SESSION: NY/LON</span>
              <span>{now.toUTCString().slice(17, 25)} UTC</span>
              <span>EQUITY ${fmt(totals.equity, 0)}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] text-bear hover:border-bear/60">
              <Power className="h-3 w-3" /> Halt AI
            </button>
            <button onClick={signOut} className="flex items-center gap-2 rounded-sm border border-border bg-card px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] hover:border-primary/60">
              <LogOut className="h-3 w-3" /> Sign out
            </button>
          </div>
        </div>
      </header>

      {/* KPI ROW */}
      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 py-4 md:grid-cols-3 lg:grid-cols-6">
        <Kpi icon={Wallet} label="Equity" value={`$${fmt(totals.equity, 0)}`}
             sub={`start $${fmt(STARTING_EQUITY, 0)}`} />
        <Kpi icon={TrendingUp} label="Unrealized P&L"
             value={`${signed(totals.openPnl)} $`} tone={totals.openPnl >= 0 ? "bull" : "bear"} />
        <Kpi icon={Activity} label="Realized (all)"
             value={`${signed(totals.realized)} $`} tone={totals.realized >= 0 ? "bull" : "bear"} />
        <Kpi icon={Layers} label="Exposure" value={`$${fmt(totals.exposure, 0)}`}
             sub={`${totals.openCount} positions`} />
        <Kpi icon={Gauge} label="Leverage" value={`${totals.leverage.toFixed(2)}x`}
             tone={totals.leverage > 2 ? "bear" : undefined} />
        <Kpi icon={ShieldAlert} label="Max drawdown"
             value={`${drawdown.toFixed(2)}%`} tone="bear" />
      </section>

      {/* EQUITY + DAILY PNL */}
      <section className="mx-auto grid max-w-[1600px] gap-3 px-4 lg:grid-cols-[2fr_1fr]">
        <Panel title="EQUITY CURVE" sub={`since inception · ${signed(totals.equity - STARTING_EQUITY)} $`}>
          <EquityChart data={equitySeries} />
        </Panel>
        <Panel title="DAILY P&L" sub={`${dailyPnl.length} sessions`}>
          <DailyPnlChart data={dailyPnl} />
        </Panel>
      </section>

      {/* ALLOCATION ROW */}
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
            {allocation.length === 0 && (
              <div className="col-span-2 py-6 text-center text-xs text-muted-foreground">No allocation yet.</div>
            )}
          </div>
        </Panel>

        <Panel title="PERFORMANCE" sub="closed trades">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <Metric label="Win rate" value={`${totals.winRate.toFixed(0)}%`}
                    tone={totals.winRate >= 50 ? "bull" : "bear"} />
            <Metric label="Trades" value={String(trades.length)} />
            <Metric label="Wins" value={String(totals.wins)} tone="bull" />
            <Metric label="Losses" value={String(totals.losses)} tone="bear" />
            <Metric label="Avg win" value={`$${fmt(totals.avgWin)}`} tone="bull" />
            <Metric label="Avg loss" value={`-$${fmt(totals.avgLoss)}`} tone="bear" />
            <Metric label="Profit factor"
                    value={totals.avgLoss > 0
                      ? (totals.avgWin * totals.wins / (totals.avgLoss * Math.max(totals.losses, 1))).toFixed(2)
                      : "∞"}
                    tone="bull" />
            <Metric label="Net P&L" value={`${signed(totals.realized)} $`}
                    tone={totals.realized >= 0 ? "bull" : "bear"} />
          </div>
        </Panel>
      </section>

      {/* WINNERS / LOSERS */}
      <section className="mx-auto mt-3 grid max-w-[1600px] gap-3 px-4 lg:grid-cols-2">
        <Panel title="TOP WINNERS" sub="open positions">
          <MoverList rows={winners} icon={ArrowUpRight} tone="bull" />
        </Panel>
        <Panel title="TOP LOSERS" sub="open positions">
          <MoverList rows={losers} icon={ArrowDownRight} tone="bear" />
        </Panel>
      </section>

      {/* POSITIONS TABLE */}
      <section className="mx-auto mt-3 max-w-[1600px] px-4">
        <Panel
          title="OPEN POSITIONS"
          sub={`${filteredPositions.length} shown`}
          right={
            <div className="flex items-center gap-1">
              {(["all", "forex", "stock", "crypto"] as const).map((k) => (
                <button
                  key={k}
                  onClick={() => setAssetFilter(k)}
                  className={`rounded-sm border px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest transition ${
                    assetFilter === k
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40"
                  }`}
                >{k}</button>
              ))}
            </div>
          }
        >
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
                {positionsQ.isLoading && (
                  <tr><td colSpan={10} className="py-10 text-center text-muted-foreground">Loading market feed…</td></tr>
                )}
                {filteredPositions.map((p) => {
                  const notional = Math.abs(Number(p.size) * Number(p.current_price));
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
                      <Td right muted>{fmt(Number(p.size), p.asset_class === "crypto" ? 4 : 0)}</Td>
                      <Td right muted>{fmtPx(Number(p.entry_price))}</Td>
                      <Td right>{fmtPx(Number(p.current_price))}</Td>
                      <Td right tone={Number(p.pnl) >= 0 ? "bull" : "bear"}>{signed(Number(p.pnl))}</Td>
                      <Td right tone={Number(p.pnl_pct) >= 0 ? "bull" : "bear"}>{signed(Number(p.pnl_pct))}%</Td>
                      <Td right muted>${fmt(notional, 0)}</Td>
                      <td className="py-2.5 pr-2 text-right">
                        <ConfBar value={Number(p.confidence)} />
                      </td>
                      <Td right muted>{formatDistanceToNow(new Date(p.opened_at))}</Td>
                    </tr>
                  );
                })}
                {!positionsQ.isLoading && filteredPositions.length === 0 && (
                  <tr><td colSpan={10} className="py-10 text-center text-muted-foreground">No positions in this asset class.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>

      {/* AI LOG + RECENT TRADES */}
      <section className="mx-auto mt-3 grid max-w-[1600px] gap-3 px-4 lg:grid-cols-2">
        <Panel title="AI DECISION LOG" sub="last 30 events">
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
            {logs.length === 0 && !logsQ.isLoading && (
              <div className="py-6 text-center text-xs text-muted-foreground">No AI activity yet.</div>
            )}
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
                    <Td right muted>{fmtPx(Number(t.entry_price))}</Td>
                    <Td right>{fmtPx(Number(t.exit_price))}</Td>
                    <Td right tone={Number(t.pnl) >= 0 ? "bull" : "bear"}>{signed(Number(t.pnl))}</Td>
                    <Td right muted>{formatDistanceToNow(new Date(t.closed_at))}</Td>
                  </tr>
                ))}
                {trades.length === 0 && (
                  <tr><td colSpan={6} className="py-6 text-center text-muted-foreground">No closed trades.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </section>
    </main>
  );
}

/* ──────────────── UI primitives ──────────────── */

function Panel({
  title, sub, right, children,
}: { title: string; sub?: string; right?: React.ReactNode; children: React.ReactNode }) {
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

function Kpi({
  icon: Icon, label, value, tone, sub,
}: { icon: typeof Activity; label: string; value: string; tone?: "bull" | "bear"; sub?: string }) {
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
  return (
    <th className={`py-2 ${right ? "pr-2 text-right" : "pl-0 text-left"} font-normal`}>{children}</th>
  );
}
function Td({
  children, right, muted, tone,
}: { children: React.ReactNode; right?: boolean; muted?: boolean; tone?: "bull" | "bear" }) {
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

function MoverList({
  rows, icon: Icon, tone,
}: { rows: Position[]; icon: typeof ArrowUpRight; tone: "bull" | "bear" }) {
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
            <span className="text-muted-foreground">{fmtPx(Number(p.current_price))}</span>
            <span className={`font-bold ${toneCls}`}>{signed(Number(p.pnl))} $</span>
            <span className={`text-[10px] ${toneCls}`}>{signed(Number(p.pnl_pct))}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ──────────────── Charts (inline SVG, no deps) ──────────────── */

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
