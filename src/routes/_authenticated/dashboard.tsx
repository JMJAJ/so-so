import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useQuery } from "@tanstack/react-query";
import { Activity, LogOut, Wallet, TrendingUp, Brain, AlertTriangle, Power } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

export const Route = createFileRoute("/_authenticated/dashboard")({
  head: () => ({ meta: [{ title: "Terminal // NEXUS" }] }),
  component: Dashboard,
});

type Position = {
  id: string;
  pair: string;
  asset_class: string;
  side: "long" | "short";
  size: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  opened_at: string;
  confidence: number;
};
type Trade = { id: string; pair: string; side: string; size: number; entry_price: number; exit_price: number; pnl: number; closed_at: string };
type AiLog = { id: string; level: string; action: string; pair: string | null; message: string; created_at: string };

const fmt = (n: number, d = 2) => n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPx = (n: number) => (n >= 1000 ? fmt(n, 2) : fmt(n, 4));

function Dashboard() {
  const navigate = useNavigate();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const i = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(i); }, []);

  const positionsQ = useQuery({
    queryKey: ["positions"],
    queryFn: async (): Promise<Position[]> => {
      const { data, error } = await supabase.from("positions").select("*").order("opened_at", { ascending: false });
      if (error) throw error;
      return (data ?? []) as Position[];
    },
  });
  const tradesQ = useQuery({
    queryKey: ["trades"],
    queryFn: async (): Promise<Trade[]> => {
      const { data, error } = await supabase.from("trades").select("*").order("closed_at", { ascending: false }).limit(10);
      if (error) throw error;
      return (data ?? []) as Trade[];
    },
  });
  const logsQ = useQuery({
    queryKey: ["ai_logs"],
    queryFn: async (): Promise<AiLog[]> => {
      const { data, error } = await supabase.from("ai_logs").select("*").order("created_at", { ascending: false }).limit(20);
      if (error) throw error;
      return (data ?? []) as AiLog[];
    },
  });

  const positions = positionsQ.data ?? [];
  const trades = tradesQ.data ?? [];
  const logs = logsQ.data ?? [];

  const totals = useMemo(() => {
    const openPnl = positions.reduce((a, p) => a + Number(p.pnl), 0);
    const realized = trades.reduce((a, t) => a + Number(t.pnl), 0);
    const exposure = positions.reduce((a, p) => a + Number(p.size) * Number(p.current_price), 0);
    const wins = trades.filter((t) => t.pnl > 0).length;
    const winRate = trades.length ? (wins / trades.length) * 100 : 0;
    return { openPnl, realized, exposure, winRate, openCount: positions.length };
  }, [positions, trades]);

  // Allocation per quote currency
  const allocation = useMemo(() => {
    const map = new Map<string, number>();
    positions.forEach((p) => {
      const value = Math.abs(Number(p.size) * Number(p.current_price));
      const [base] = p.pair.split("/");
      map.set(base, (map.get(base) ?? 0) + value);
    });
    const total = Array.from(map.values()).reduce((a, b) => a + b, 0) || 1;
    return Array.from(map.entries())
      .map(([k, v]) => ({ ccy: k, value: v, pct: (v / total) * 100 }))
      .sort((a, b) => b.pct - a.pct);
  }, [positions]);

  const signOut = async () => {
    await supabase.auth.signOut();
    navigate({ to: "/auth", replace: true });
  };

  return (
    <main className="min-h-screen pb-12">
      {/* TOP BAR */}
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-4 py-2.5">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-bull" />
              <span className="font-display text-sm font-bold tracking-tight">NEXUS</span>
              <span className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">// TERMINAL</span>
            </div>
            <div className="hidden h-4 w-px bg-border md:block" />
            <div className="hidden items-center gap-3 text-[10px] uppercase tracking-[0.25em] text-muted-foreground md:flex">
              <span><span className="text-bull">●</span> AI ACTIVE</span>
              <span>SESSION: NY/LON</span>
              <span>{now.toUTCString().slice(17, 25)} UTC</span>
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
      <section className="mx-auto grid max-w-[1500px] gap-3 px-4 py-4 md:grid-cols-5">
        <Kpi icon={TrendingUp} label="Unrealized P&L" value={`${totals.openPnl >= 0 ? "+" : ""}$${fmt(totals.openPnl)}`} tone={totals.openPnl >= 0 ? "bull" : "bear"} />
        <Kpi icon={Activity}  label="Realized (7d)"  value={`${totals.realized >= 0 ? "+" : ""}$${fmt(totals.realized)}`} tone={totals.realized >= 0 ? "bull" : "bear"} />
        <Kpi icon={Wallet}    label="Exposure"       value={`$${fmt(totals.exposure, 0)}`} />
        <Kpi icon={Brain}     label="Open positions" value={String(totals.openCount)} />
        <Kpi icon={AlertTriangle} label="Win rate (7d)" value={`${totals.winRate.toFixed(0)}%`} tone={totals.winRate >= 50 ? "bull" : "bear"} />
      </section>

      {/* MAIN GRID */}
      <section className="mx-auto grid max-w-[1500px] gap-3 px-4 lg:grid-cols-[1fr_360px]">
        {/* LEFT: Positions */}
        <Panel title="OPEN POSITIONS" sub={`${positions.length} active`}>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                  <Th>Pair</Th><Th>Side</Th><Th right>Size</Th><Th right>Entry</Th><Th right>Mark</Th><Th right>P&L $</Th><Th right>P&L %</Th><Th right>Conf</Th><Th right>Age</Th>
                </tr>
              </thead>
              <tbody>
                {positionsQ.isLoading && (
                  <tr><td colSpan={9} className="py-10 text-center text-muted-foreground">Loading market feed…</td></tr>
                )}
                {positions.map((p) => (
                  <tr key={p.id} className="border-b border-border/40 transition hover:bg-card/50">
                    <td className="py-2.5">
                      <div className="flex items-center gap-2">
                        <span className={`inline-block h-1.5 w-1.5 rounded-full ${p.asset_class === "crypto" ? "bg-chart-5" : "bg-primary"}`} />
                        <span className="font-bold">{p.pair}</span>
                        <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{p.asset_class}</span>
                      </div>
                    </td>
                    <td><span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${p.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>{p.side}</span></td>
                    <Td right muted>{fmt(Number(p.size), p.asset_class === "crypto" ? 4 : 0)}</Td>
                    <Td right muted>{fmtPx(Number(p.entry_price))}</Td>
                    <Td right>{fmtPx(Number(p.current_price))}</Td>
                    <Td right tone={Number(p.pnl) >= 0 ? "bull" : "bear"}>{Number(p.pnl) >= 0 ? "+" : ""}{fmt(Number(p.pnl))}</Td>
                    <Td right tone={Number(p.pnl_pct) >= 0 ? "bull" : "bear"}>{Number(p.pnl_pct) >= 0 ? "+" : ""}{fmt(Number(p.pnl_pct))}%</Td>
                    <td className="py-2.5 pr-2 text-right">
                      <ConfBar value={Number(p.confidence)} />
                    </td>
                    <Td right muted>{formatDistanceToNow(new Date(p.opened_at))}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* RIGHT: Allocation */}
        <Panel title="ALLOCATION" sub="by base currency">
          <div className="space-y-2.5">
            {allocation.map((a) => (
              <div key={a.ccy}>
                <div className="mb-1 flex items-center justify-between text-xs">
                  <span className="font-bold">{a.ccy}</span>
                  <span className="tabular-nums text-muted-foreground">{a.pct.toFixed(1)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-sm bg-secondary">
                  <div className="h-full bg-primary transition-all" style={{ width: `${a.pct}%` }} />
                </div>
                <div className="mt-0.5 text-right text-[10px] tabular-nums text-muted-foreground">${fmt(a.value, 0)}</div>
              </div>
            ))}
            {allocation.length === 0 && <div className="py-6 text-center text-xs text-muted-foreground">No allocation yet.</div>}
          </div>
        </Panel>
      </section>

      {/* BOTTOM GRID */}
      <section className="mx-auto mt-3 grid max-w-[1500px] gap-3 px-4 lg:grid-cols-2">
        {/* AI Logs */}
        <Panel title="AI DECISION LOG" sub="last 20 events">
          <div className="space-y-1">
            {logs.map((l) => (
              <div key={l.id} className="grid grid-cols-[auto_auto_1fr_auto] items-start gap-3 border-b border-border/40 py-2 text-xs">
                <span className="font-mono text-[10px] text-muted-foreground">{new Date(l.created_at).toLocaleTimeString("en-GB", { hour12: false })}</span>
                <span className={`rounded-sm px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
                  l.level === "error" ? "bg-bear/15 text-bear" : l.level === "warn" ? "bg-primary/15 text-primary" : "bg-bull/15 text-bull"
                }`}>{l.action}</span>
                <div className="min-w-0">
                  {l.pair && <span className="mr-2 font-bold">{l.pair}</span>}
                  <span className="text-foreground/90">{l.message}</span>
                </div>
                <span className="text-[10px] text-muted-foreground">{formatDistanceToNow(new Date(l.created_at))}</span>
              </div>
            ))}
            {logs.length === 0 && !logsQ.isLoading && <div className="py-6 text-center text-xs text-muted-foreground">No AI activity yet.</div>}
          </div>
        </Panel>

        {/* Trade history */}
        <Panel title="RECENT TRADES" sub="closed positions">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                <Th>Pair</Th><Th>Side</Th><Th right>Entry</Th><Th right>Exit</Th><Th right>P&L</Th><Th right>Closed</Th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className="border-b border-border/40">
                  <td className="py-2 font-bold">{t.pair}</td>
                  <td><span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${t.side === "long" ? "bg-bull/15 text-bull" : "bg-bear/15 text-bear"}`}>{t.side}</span></td>
                  <Td right muted>{fmtPx(Number(t.entry_price))}</Td>
                  <Td right>{fmtPx(Number(t.exit_price))}</Td>
                  <Td right tone={Number(t.pnl) >= 0 ? "bull" : "bear"}>{Number(t.pnl) >= 0 ? "+" : ""}{fmt(Number(t.pnl))}</Td>
                  <Td right muted>{formatDistanceToNow(new Date(t.closed_at))}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </section>
    </main>
  );
}

function Panel({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <div className="terminal-panel rounded-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-primary">// {title}</span>
          {sub && <span className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">{sub}</span>}
        </div>
        <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-bull" />
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function Kpi({ icon: Icon, label, value, tone }: { icon: typeof Activity; label: string; value: string; tone?: "bull" | "bear" }) {
  const toneCls = tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-foreground";
  return (
    <div className="terminal-panel rounded-sm p-4">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
        <span>{label}</span>
        <Icon className="h-3.5 w-3.5 text-primary" strokeWidth={1.5} />
      </div>
      <div className={`mt-2 font-display text-2xl font-bold tabular-nums ${toneCls}`}>{value}</div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={`py-2 ${right ? "pr-2 text-right" : "pl-0 text-left"} font-normal`}>{children}</th>;
}
function Td({ children, right, muted, tone }: { children: React.ReactNode; right?: boolean; muted?: boolean; tone?: "bull" | "bear" }) {
  const toneCls = tone === "bull" ? "text-bull font-bold" : tone === "bear" ? "text-bear font-bold" : muted ? "text-muted-foreground" : "";
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
