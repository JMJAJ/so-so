import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Check,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Gauge,
  Heart,
  History,
  LayoutDashboard,
  LockKeyhole,
  Menu,
  Play,
  Power,
  RefreshCw,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Target,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { ApiError, terminalApi } from "@/lib/terminal-api";
import type {
  AgentMode,
  BootstrapData,
  Instrument,
  OrderPreview,
  Position,
  Proposal,
  Quote,
  RiskProfile,
  TradeIdea,
} from "@/lib/terminal-types";

const ResearchChart = lazy(() => import("./ResearchChart"));
const PositionChart = lazy(() => import("./PositionChart"));

type View = "overview" | "markets" | "charts" | "ideas" | "activity" | "settings";
const POLL_MS = 10_000;

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});
const compactCurrency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 });

function signed(value: number, suffix = ""): string {
  return `${value > 0 ? "+" : ""}${number.format(value)}${suffix}`;
}

function relativeTime(value: string | null): string {
  if (!value) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function initialView(): View {
  const value = new URLSearchParams(window.location.search).get("view");
  return value && ["overview", "markets", "charts", "ideas", "activity", "settings"].includes(value)
    ? (value as View)
    : "overview";
}

function useTerminalData() {
  const [data, setData] = useState<BootstrapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async (quiet = false) => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    if (!quiet) setRefreshing(true);
    try {
      const result = await terminalApi.bootstrap(next.signal);
      setData(result);
      setError(null);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(errorMessage(requestError));
    } finally {
      if (!quiet) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    let timer: number | undefined;
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(
        async () => {
          if (document.visibilityState === "visible") await refresh(true);
          schedule();
        },
        error ? 20_000 : POLL_MS,
      );
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      controller.current?.abort();
    };
  }, [error, refresh]);

  return { data, error, refreshing, refresh };
}

export default function TerminalApp() {
  const { data, error, refreshing, refresh } = useTerminalData();
  const [view, setViewState] = useState<View>(initialView);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [ticket, setTicket] = useState<Instrument | null>(null);

  useEffect(() => {
    const onPopState = () => setViewState(initialView());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const setView = (next: View) => {
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    window.history.pushState({}, "", url);
    setViewState(next);
    setMobileMenu(false);
  };

  const openPositionChart = (position: Position) => {
    const url = new URL(window.location.href);
    url.searchParams.set("view", "charts");
    url.searchParams.set("position", position.id);
    window.history.pushState({}, "", url);
    setViewState("charts");
    setMobileMenu(false);
  };

  const mutate = async (label: string, action: () => Promise<unknown>) => {
    try {
      await action();
      toast.success(label);
      await refresh(true);
    } catch (mutationError) {
      toast.error(errorMessage(mutationError));
    }
  };

  if (!data && !error) return <LoadingScreen />;
  if (!data)
    return <OfflineScreen error={error ?? "Backend unavailable"} retry={() => void refresh()} />;

  const nav = [
    { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
    { id: "markets" as const, label: "Markets", icon: BarChart3 },
    { id: "charts" as const, label: "Charts", icon: Activity },
    {
      id: "ideas" as const,
      label: "Ideas",
      icon: Sparkles,
      count: data.proposals.filter((item) => item.status === "pending").length,
    },
    { id: "activity" as const, label: "Activity", icon: History },
    { id: "settings" as const, label: "Settings", icon: Settings },
  ];

  return (
    <main className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-56 border-r border-border/80 bg-card/95 lg:flex lg:flex-col">
        <Brand />
        <nav className="flex-1 space-y-1 px-3 py-4" aria-label="Primary navigation">
          {nav.map((item) => (
            <NavItem
              key={item.id}
              active={view === item.id}
              onClick={() => setView(item.id)}
              {...item}
            />
          ))}
        </nav>
        <div className="border-t border-border p-4 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <div className="mb-2 flex items-center justify-between">
            <span>Quote source</span>
            <span className="text-foreground">YFinance</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Execution</span>
            <span className="text-primary">Paper only</span>
          </div>
        </div>
      </aside>

      <div className="min-w-0 lg:pl-56">
        <StatusHeader
          data={data}
          refreshing={refreshing}
          onRefresh={() => void refresh()}
          onMenu={() => setMobileMenu((value) => !value)}
          mutate={mutate}
        />
        {error && (
          <div className="border-b border-bear/30 bg-bear/10 px-4 py-2 text-xs text-bear lg:px-6">
            <AlertTriangle className="mr-2 inline h-3.5 w-3.5" /> Updates paused: {error}. Last good
            snapshot retained.
          </div>
        )}
        {mobileMenu && (
          <div className="border-b border-border bg-card px-3 py-3 lg:hidden">
            <div className="grid grid-cols-2 gap-2">
              {nav.map((item) => (
                <NavItem
                  key={item.id}
                  active={view === item.id}
                  onClick={() => setView(item.id)}
                  {...item}
                />
              ))}
            </div>
          </div>
        )}

        <div className="mx-auto max-w-[1600px] px-3 pb-24 pt-4 sm:px-5 lg:px-6 lg:pb-10">
          {view === "overview" && (
            <Overview data={data} mutate={mutate} onChart={openPositionChart} />
          )}
          {view === "markets" && <Markets data={data} onTrade={setTicket} />}
          {view === "charts" && <ChartsView data={data} />}
          {view === "ideas" && <Ideas data={data} mutate={mutate} />}
          {view === "activity" && <ActivityView data={data} />}
          {view === "settings" && <SettingsView data={data} mutate={mutate} />}
        </div>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-6 border-t border-border bg-card/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        {nav.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`relative flex min-h-16 flex-col items-center justify-center gap-1 text-[9px] font-bold uppercase tracking-wider ${view === item.id ? "text-primary" : "text-muted-foreground"}`}
            >
              <Icon className="h-4 w-4" />
              {item.label}
              {!!item.count && (
                <span className="absolute right-3 top-2 h-2 w-2 rounded-full bg-primary" />
              )}
            </button>
          );
        })}
      </nav>

      {ticket && (
        <OrderTicket
          instrument={ticket}
          quote={data.quotes[ticket.id]}
          onClose={() => setTicket(null)}
          onFilled={async () => {
            setTicket(null);
            await refresh(true);
          }}
        />
      )}
    </main>
  );
}

function Brand() {
  return (
    <div className="flex h-16 items-center gap-3 border-b border-border px-4">
      <div className="flex h-8 w-8 items-center justify-center border border-primary/60 bg-primary/10 font-display text-sm font-bold text-primary">
        N
      </div>
      <div>
        <div className="font-display text-sm font-bold tracking-tight">NEXUS</div>
        <div className="text-[9px] uppercase tracking-[0.24em] text-muted-foreground">
          Paper terminal
        </div>
      </div>
    </div>
  );
}

function NavItem({
  active,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof LayoutDashboard;
  label: string;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-sm px-3 py-2.5 text-left text-xs font-bold uppercase tracking-[0.14em] transition ${active ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
    >
      <Icon className="h-4 w-4" strokeWidth={1.7} />
      <span className="flex-1">{label}</span>
      {!!count && (
        <span className="rounded-full bg-primary px-1.5 py-0.5 text-[9px] text-primary-foreground">
          {count}
        </span>
      )}
    </button>
  );
}

function StatusHeader({
  data,
  refreshing,
  onRefresh,
  onMenu,
  mutate,
}: {
  data: BootstrapData;
  refreshing: boolean;
  onRefresh: () => void;
  onMenu: () => void;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
}) {
  const agent = data.agent;
  const stale = data.system.market_data.stale_count ?? 0;
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/95 backdrop-blur">
      <div className="flex min-h-16 items-center gap-2 px-3 sm:px-5 lg:px-6">
        <button
          onClick={onMenu}
          className="p-2 text-muted-foreground lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:gap-4">
          <span className="shrink-0 border border-primary/60 bg-primary/10 px-2 py-1 text-[9px] font-bold uppercase tracking-[0.2em] text-primary">
            Paper
          </span>
          <StatusDot
            ok={data.system.market_data.ok && stale === 0}
            label={stale ? `${stale} stale` : "quotes ready"}
          />
          <div className="hidden h-5 w-px bg-border sm:block" />
          <span className="hidden truncate text-[10px] uppercase tracking-[0.16em] text-muted-foreground sm:block">
            {agent.mode.replace("_", " ")} · {data.portfolio.risk_profile}
          </span>
        </div>

        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="icon-button"
          aria-label="Refresh terminal"
        >
          <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
        </button>
        <button
          onClick={() =>
            void mutate(
              agent.running ? "Agent stopped" : "Agent started",
              agent.running ? terminalApi.stopAgent : terminalApi.startAgent,
            )
          }
          disabled={agent.kill_switch}
          className={`hidden items-center gap-2 border px-3 py-2 text-[10px] font-bold uppercase tracking-wider sm:flex ${agent.running ? "border-bear/50 text-bear" : "border-bull/50 text-bull"} disabled:opacity-40`}
        >
          {agent.running ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
          {agent.running ? "Stop" : "Start AI"}
        </button>
        <button
          onClick={() => {
            const enabling = !agent.kill_switch;
            if (
              enabling &&
              !window.confirm("Engage the kill switch? Protective exits will remain active.")
            )
              return;
            void mutate(enabling ? "Kill switch engaged" : "Kill switch released", () =>
              terminalApi.setKillSwitch(enabling),
            );
          }}
          className={`flex items-center gap-2 border px-2.5 py-2 text-[10px] font-bold uppercase tracking-wider ${agent.kill_switch ? "border-bear bg-bear/15 text-bear" : "border-border text-muted-foreground hover:border-bear/60 hover:text-bear"}`}
          aria-label="Toggle kill switch"
        >
          <Power className="h-3.5 w-3.5" />
          <span className="hidden md:inline">{agent.kill_switch ? "Killed" : "Kill"}</span>
        </button>
      </div>
    </header>
  );
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`flex items-center gap-1.5 whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.14em] ${ok ? "text-bull" : "text-primary"}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-bull" : "bg-primary"}`} /> {label}
    </span>
  );
}

function Overview({
  data,
  mutate,
  onChart,
}: {
  data: BootstrapData;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
  onChart: (position: Position) => void;
}) {
  const portfolio = data.portfolio;
  const warnings = [
    ...data.positions
      .filter((position) => position.protection_status === "unprotected")
      .map((position) => `${position.pair} is unprotected`),
    ...(data.agent.kill_switch ? ["Kill switch is engaged"] : []),
    ...(data.system.market_data.stale_count
      ? [`${data.system.market_data.stale_count} quotes are stale`]
      : []),
  ];
  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Portfolio command"
        title="Overview"
        description="Account truth, active risk, and actions that need attention."
      />
      {warnings.length > 0 && (
        <section className="terminal-panel border-primary/30 bg-primary/[0.04] p-3 sm:p-4">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-primary">
                Risk attention
              </div>
              <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted-foreground">
                {warnings.map((warning) => (
                  <span key={warning}>{warning}</span>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
      <section className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="Equity"
          value={compactCurrency.format(portfolio.equity)}
          sub={`Start ${compactCurrency.format(portfolio.starting_equity)}`}
          icon={CircleDollarSign}
        />
        <Kpi
          label="Day P&L"
          value={currency.format(portfolio.day_pnl)}
          tone={portfolio.day_pnl >= 0 ? "bull" : "bear"}
          icon={portfolio.day_pnl >= 0 ? TrendingUp : TrendingDown}
        />
        <Kpi
          label="Unrealized"
          value={currency.format(portfolio.open_pnl)}
          tone={portfolio.open_pnl >= 0 ? "bull" : "bear"}
          icon={Activity}
        />
        <Kpi
          label="Available cash"
          value={compactCurrency.format(portfolio.cash)}
          tone={portfolio.cash < 0 ? "bear" : undefined}
          icon={CircleDollarSign}
        />
        <Kpi
          label="Exposure"
          value={`${portfolio.exposure_pct.toFixed(1)}%`}
          sub={compactCurrency.format(portfolio.gross_exposure)}
          icon={Gauge}
        />
        <Kpi
          label="Drawdown"
          value={`${portfolio.max_drawdown.toFixed(2)}%`}
          tone="bear"
          icon={ShieldAlert}
        />
      </section>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1.7fr)_minmax(300px,0.7fr)]">
        <Panel title="Equity curve" sub={`${portfolio.equity_series.length} ledger points`}>
          <EquityChart data={portfolio.equity_series} />
        </Panel>
        <Panel title="Risk budget" sub={`${portfolio.risk_profile} preset`}>
          <div className="space-y-5 p-4">
            <Progress
              label="Gross exposure"
              value={portfolio.risk_used_pct}
              display={`${portfolio.exposure_pct.toFixed(1)}% / ${(portfolio.risk_limits.max_exposure * 100).toFixed(0)}%`}
            />
            <Progress
              label="Open positions"
              value={(portfolio.open_count / portfolio.risk_limits.max_positions) * 100}
              display={`${portfolio.open_count} / ${portfolio.risk_limits.max_positions}`}
            />
            <div className="grid grid-cols-2 gap-2 text-xs">
              <MiniStat
                label="Risk / trade"
                value={`${(portfolio.risk_limits.risk_per_trade * 100).toFixed(1)}%`}
              />
              <MiniStat
                label="Daily cutoff"
                value={`${(portfolio.risk_limits.daily_loss * 100).toFixed(0)}%`}
              />
              <MiniStat label="Win rate" value={`${portfolio.win_rate.toFixed(0)}%`} />
              <MiniStat
                label="W / L / BE"
                value={`${portfolio.wins} / ${portfolio.losses} / ${portfolio.breakeven}`}
              />
            </div>
          </div>
        </Panel>
      </section>

      <PositionsPanel data={data} mutate={mutate} onChart={onChart} />
    </div>
  );
}

function PositionsPanel({
  data,
  mutate,
  onChart,
}: {
  data: BootstrapData;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
  onChart: (position: Position) => void;
}) {
  const close = (position: Position) => {
    if (!window.confirm(`Close the ${position.side} ${position.pair} paper position?`)) return;
    void mutate(`${position.pair} closed`, () => terminalApi.closePosition(position.id));
  };
  return (
    <Panel title="Open positions" sub={`${data.positions.length} active`}>
      {data.positions.length === 0 ? (
        <EmptyState
          icon={Target}
          title="No open positions"
          description="Preview an accuracy-gated market order to begin."
        />
      ) : (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[900px] text-xs">
              <thead>
                <tr>
                  <Th>Instrument</Th>
                  <Th>Side</Th>
                  <Th right>Quantity</Th>
                  <Th right>Entry</Th>
                  <Th right>Mark</Th>
                  <Th right>P&L</Th>
                  <Th right>Exposure</Th>
                  <Th>Protection</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {data.positions.map((position) => (
                  <tr key={position.id} className="border-t border-border/60 hover:bg-muted/40">
                    <Td>
                      <strong>{position.pair}</strong>
                      <span className="ml-2 text-[9px] uppercase text-muted-foreground">
                        {position.asset_class}
                      </span>
                    </Td>
                    <Td>
                      <SideBadge side={position.side} />
                    </Td>
                    <Td right>{number.format(position.size)}</Td>
                    <Td right>{number.format(position.entry_price)}</Td>
                    <Td right>{number.format(position.current_price)}</Td>
                    <Td right>
                      <Tone value={position.pnl}>
                        {currency.format(position.pnl)}{" "}
                        <span className="text-[9px]">({signed(position.pnl_pct, "%")})</span>
                      </Tone>
                    </Td>
                    <Td right>{compactCurrency.format(position.notional)}</Td>
                    <Td>
                      <ProtectionBadge position={position} />
                    </Td>
                    <Td right>
                      <div className="flex justify-end gap-2">
                        <button onClick={() => onChart(position)} className="secondary-button">
                          Graph
                        </button>
                        <button onClick={() => close(position)} className="danger-button">
                          Close
                        </button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-2 p-2 md:hidden">
            {data.positions.map((position) => (
              <article key={position.id} className="border border-border bg-background/40 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-bold">{position.pair}</div>
                    <div className="mt-1 flex gap-2">
                      <SideBadge side={position.side} />
                      <ProtectionBadge position={position} />
                    </div>
                  </div>
                  <Tone value={position.pnl}>
                    <div className="text-right font-bold">{currency.format(position.pnl)}</div>
                    <div className="text-[10px]">{signed(position.pnl_pct, "%")}</div>
                  </Tone>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] text-muted-foreground">
                  <div>
                    ENTRY
                    <strong className="mt-1 block text-xs text-foreground">
                      {number.format(position.entry_price)}
                    </strong>
                  </div>
                  <div>
                    MARK
                    <strong className="mt-1 block text-xs text-foreground">
                      {number.format(position.current_price)}
                    </strong>
                  </div>
                  <div>
                    EXPOSURE
                    <strong className="mt-1 block text-xs text-foreground">
                      {compactCurrency.format(position.notional)}
                    </strong>
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button onClick={() => close(position)} className="danger-button flex-1 py-2">
                    Close safely
                  </button>
                  {position.instrument_id && (
                    <button onClick={() => onChart(position)} className="secondary-button px-4">
                      Graph
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

function ChartsView({ data }: { data: BootstrapData }) {
  const [selectedPositionId, setSelectedPositionId] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("position"),
  );
  const selectedPosition =
    data.positions.find((position) => position.id === selectedPositionId) ??
    data.positions[0] ??
    null;
  const selectPosition = (position: Position) => {
    setSelectedPositionId(position.id);
    const url = new URL(window.location.href);
    url.searchParams.set("position", position.id);
    window.history.replaceState({}, "", url);
  };

  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Position intelligence"
        title="Charts"
        description="Live paper-position charts with recorded protection and clearly labeled AI scenarios."
      />
      {selectedPosition ? (
        <PositionGraphWorkspace
          position={selectedPosition}
          positions={data.positions}
          orders={data.orders}
          proposals={data.proposals}
          onSelect={selectPosition}
        />
      ) : (
        <Panel title="Position graphs" sub="No active assets">
          <EmptyState
            icon={Activity}
            title="No active charts"
            description="Open a paper position to monitor its price, stop, target, and AI scenario here."
          />
        </Panel>
      )}
    </div>
  );
}

function PositionGraphWorkspace({
  position,
  positions,
  orders,
  proposals,
  onSelect,
}: {
  position: Position;
  positions: Position[];
  orders: BootstrapData["orders"];
  proposals: Proposal[];
  onSelect: (position: Position) => void;
}) {
  const order = orders.find((item) => item.position_id === position.id);
  const proposal = order?.proposal_id
    ? proposals.find((item) => item.id === order.proposal_id)
    : undefined;
  const risk =
    position.stop_loss == null
      ? null
      : Math.abs(position.current_price - position.stop_loss) * position.size;
  const reward =
    position.take_profit == null
      ? null
      : Math.abs(position.take_profit - position.current_price) * position.size;
  return (
    <Panel
      title={`${position.pair} graph`}
      sub={proposal ? "Live price with AI scenario overlay" : "Live price and protected levels"}
    >
      <div className="flex gap-1 overflow-x-auto border-b border-border px-2 pt-2 sm:px-3">
        {positions.map((item) => (
          <Tab key={item.id} active={item.id === position.id} onClick={() => onSelect(item)}>
            {item.pair}
            <span className="ml-1.5 text-[9px] opacity-70">{item.side}</span>
          </Tab>
        ))}
      </div>
      <div className="grid gap-px border-b border-border bg-border sm:grid-cols-4">
        <MiniStat label="Entry" value={number.format(position.entry_price)} />
        <MiniStat label="Mark" value={number.format(position.current_price)} />
        <MiniStat label="Risk to stop" value={risk == null ? "Unbounded" : currency.format(risk)} />
        <MiniStat
          label="Upside to target"
          value={reward == null ? "No target" : currency.format(reward)}
        />
      </div>
      <Suspense
        fallback={
          <div className="flex h-[440px] items-center justify-center text-xs text-muted-foreground">
            Loading {position.pair} chart…
          </div>
        }
      >
        <PositionChart position={position} proposal={proposal} />
      </Suspense>
      <div className="border-t border-border p-4">
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-[10px] uppercase tracking-wider text-muted-foreground">
          <span className="text-primary">Amber: {proposal ? "AI scenario" : "entry"}</span>
          <span className="text-bull">Green: target</span>
          <span className="text-bear">Red: stop</span>
          <span>White: mark</span>
        </div>
        {proposal ? (
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            <strong className="text-foreground">
              AI scenario · {Math.round((proposal.confidence ?? 0) * 100)}% heuristic confidence.
            </strong>{" "}
            The amber path is a target-reaching scenario, not a price forecast or a guarantee.{" "}
            {proposal.rationale}
          </p>
        ) : (
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            This is a legacy position without a current validated AI scenario. The chart shows
            recorded entry and any active protection only.
          </p>
        )}
      </div>
    </Panel>
  );
}

function Markets({
  data,
  onTrade,
}: {
  data: BootstrapData;
  onTrade: (instrument: Instrument) => void;
}) {
  const [search, setSearch] = useState("");
  const [assetClass, setAssetClass] = useState("all");
  const [sort, setSort] = useState<"symbol" | "change">("symbol");
  const [favorites, setFavorites] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("nexus:favorites") ?? "[]") as string[];
    } catch {
      return [];
    }
  });
  const toggleFavorite = (id: string) => {
    setFavorites((current) => {
      const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
      localStorage.setItem("nexus:favorites", JSON.stringify(next));
      return next;
    });
  };
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return data.instruments
      .filter((instrument) => assetClass === "all" || instrument.asset_class === assetClass)
      .filter(
        (instrument) =>
          !term || `${instrument.symbol} ${instrument.name}`.toLowerCase().includes(term),
      )
      .sort((a, b) => {
        const favoriteDelta = Number(favorites.includes(b.id)) - Number(favorites.includes(a.id));
        if (favoriteDelta) return favoriteDelta;
        if (sort === "change")
          return (
            Math.abs(data.quotes[b.id]?.change_pct ?? -Infinity) -
            Math.abs(data.quotes[a.id]?.change_pct ?? -Infinity)
          );
        return a.symbol.localeCompare(b.symbol);
      });
  }, [assetClass, data.instruments, data.quotes, favorites, search, sort]);
  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Curated universe"
        title="Markets"
        description="Research every instrument; trade only those with verified paper-account economics."
      />
      <div className="terminal-panel flex flex-col gap-2 p-3 md:flex-row md:items-center">
        <label className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search symbol or name"
            className="terminal-input pl-9"
          />
        </label>
        <select
          value={assetClass}
          onChange={(event) => setAssetClass(event.target.value)}
          className="terminal-select md:w-44"
          aria-label="Filter asset class"
        >
          <option value="all">All asset classes</option>
          {(["forex", "stock", "crypto", "cfd", "futures"] as const).map((item) => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as "symbol" | "change")}
          className="terminal-select md:w-44"
          aria-label="Sort markets"
        >
          <option value="symbol">Sort: Symbol</option>
          <option value="change">Sort: Movement</option>
        </select>
      </div>
      <Panel title="Instrument board" sub={`${filtered.length} shown`}>
        <div className="divide-y divide-border/60">
          {filtered.map((instrument) => {
            const quote = data.quotes[instrument.id];
            return (
              <article
                key={instrument.id}
                className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 transition hover:bg-muted/40 sm:grid-cols-[auto_minmax(180px,1fr)_140px_120px_160px] sm:px-4"
              >
                <button
                  onClick={() => toggleFavorite(instrument.id)}
                  className="text-muted-foreground hover:text-bear"
                  aria-label={`${favorites.includes(instrument.id) ? "Remove" : "Add"} ${instrument.symbol} favorite`}
                >
                  <Heart
                    className={`h-4 w-4 ${favorites.includes(instrument.id) ? "fill-bear text-bear" : ""}`}
                  />
                </button>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong>{instrument.symbol}</strong>
                    <AssetBadge value={instrument.asset_class} />
                    {instrument.proxy && <Badge tone="warn">Proxy</Badge>}
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
                    {instrument.name}
                  </div>
                </div>
                <div className="text-right sm:text-left">
                  <div className="font-bold tabular-nums">
                    {quote?.price == null ? "—" : number.format(quote.price)}
                  </div>
                  <QuoteState quote={quote} />
                </div>
                <div className="hidden text-right sm:block">
                  <Tone value={quote?.change_pct ?? 0}>
                    {quote?.change_pct == null ? "—" : signed(quote.change_pct, "%")}
                  </Tone>
                </div>
                <div className="col-span-3 flex justify-end sm:col-span-1">
                  {instrument.eligibility === "trade_enabled" ? (
                    <button
                      onClick={() => onTrade(instrument)}
                      disabled={!quote || quote.stale || quote.market_status !== "open"}
                      className="primary-button w-full sm:w-auto"
                    >
                      Preview order
                    </button>
                  ) : (
                    <span className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
                      <LockKeyhole className="h-3 w-3" /> Research only
                    </span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

function Ideas({
  data,
  mutate,
}: {
  data: BootstrapData;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
}) {
  const [tab, setTab] = useState<"pending" | "history" | "legacy">("pending");
  const [selectedIdea, setSelectedIdea] = useState<TradeIdea | null>(null);
  const pending = data.proposals.filter((proposal) => proposal.status === "pending");
  const history = data.proposals.filter((proposal) => proposal.status !== "pending");
  const selectLegacy = (idea: TradeIdea) => {
    setSelectedIdea(idea);
    const url = new URL(window.location.href);
    url.searchParams.set("symbol", idea.symbol);
    window.history.replaceState({}, "", url);
  };
  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Human + machine"
        title="Ideas"
        description="AI output is a proposal until deterministic risk checks approve it."
      />
      <div className="flex gap-1 overflow-x-auto border-b border-border">
        <Tab active={tab === "pending"} onClick={() => setTab("pending")}>
          Pending <Count>{pending.length}</Count>
        </Tab>
        <Tab active={tab === "history"} onClick={() => setTab("history")}>
          Decision history <Count>{history.length}</Count>
        </Tab>
        <Tab active={tab === "legacy"} onClick={() => setTab("legacy")}>
          Legacy ideas <Count>{data.trade_ideas.length}</Count>
        </Tab>
      </div>
      {tab === "pending" &&
        (pending.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {pending.map((proposal) => (
              <ProposalCard key={proposal.id} proposal={proposal} mutate={mutate} />
            ))}
          </div>
        ) : (
          <Panel title="Proposal inbox">
            <EmptyState
              icon={Bot}
              title="No pending proposals"
              description="Run an advisory cycle when you want the AI to scan accuracy-gated markets."
            />
          </Panel>
        ))}
      {tab === "history" && (
        <Panel title="Proposal decisions" sub={`${history.length} records`}>
          <ProposalHistory proposals={history} />
        </Panel>
      )}
      {tab === "legacy" && (
        <div className="grid gap-3 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Panel title="Preserved legacy ideas" sub="Outcomes were not invented">
            <div className="max-h-[680px] divide-y divide-border/60 overflow-y-auto">
              {data.trade_ideas.map((idea) => (
                <button
                  key={idea.id}
                  onClick={() => selectLegacy(idea)}
                  className={`w-full p-3 text-left hover:bg-muted/40 ${selectedIdea?.id === idea.id ? "bg-primary/[0.07]" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong>{idea.symbol}</strong>
                    <ReviewBadge value={idea.review_state} />
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <SideBadge side={idea.side} />
                    <span className="text-[10px] text-muted-foreground">
                      Entry {number.format(idea.entry_price)}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </Panel>
          <Panel
            title={selectedIdea?.symbol ?? "Research chart"}
            sub={
              selectedIdea
                ? `${selectedIdea.review_state} legacy setup`
                : "Select a preserved setup"
            }
          >
            {selectedIdea ? (
              <Suspense
                fallback={
                  <div className="flex h-[420px] items-center justify-center text-xs text-muted-foreground">
                    Loading research workspace…
                  </div>
                }
              >
                <ResearchChart idea={selectedIdea} />
              </Suspense>
            ) : (
              <EmptyState
                icon={BarChart3}
                title="No setup selected"
                description="Review legacy setups without changing their recorded history."
              />
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  mutate,
}: {
  proposal: Proposal;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
}) {
  const approve = () => {
    if (
      !window.confirm(
        `Approve ${proposal.side} ${proposal.symbol}? The server will rerun every risk check before filling.`,
      )
    )
      return;
    void mutate(`${proposal.symbol} proposal approved`, () =>
      terminalApi.approveProposal(proposal.id),
    );
  };
  return (
    <article className="terminal-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <strong className="font-display text-lg">{proposal.symbol}</strong>
            <SideBadge side={proposal.side} />
          </div>
          <div className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            {relativeTime(proposal.created_at)} · {proposal.mode.replace("_", " ")}
          </div>
        </div>
        <div className="text-right text-xs">
          <span className="text-muted-foreground">Confidence</span>
          <strong className="block text-primary">
            {((proposal.confidence ?? 0) * 100).toFixed(0)}%
          </strong>
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-foreground/80">{proposal.rationale}</p>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <MiniStat
          label="Quantity"
          value={proposal.quantity == null ? "Missing" : number.format(proposal.quantity)}
        />
        <MiniStat
          label="Stop"
          value={proposal.stop_loss == null ? "Missing" : number.format(proposal.stop_loss)}
        />
        <MiniStat
          label="Target"
          value={proposal.take_profit == null ? "Missing" : number.format(proposal.take_profit)}
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <button
          onClick={() =>
            void mutate("Proposal rejected", () =>
              terminalApi.rejectProposal(proposal.id, "Rejected by operator"),
            )
          }
          className="secondary-button py-2.5"
        >
          Reject
        </button>
        <button onClick={approve} className="primary-button py-2.5">
          Approve + recheck
        </button>
      </div>
    </article>
  );
}

function ProposalHistory({ proposals }: { proposals: Proposal[] }) {
  if (!proposals.length)
    return (
      <EmptyState
        icon={History}
        title="No proposal decisions yet"
        description="Approved and rejected proposals will remain auditable here."
      />
    );
  return (
    <div className="divide-y divide-border/60">
      {proposals.map((proposal) => (
        <div
          key={proposal.id}
          className="grid gap-2 p-3 text-xs sm:grid-cols-[120px_100px_1fr_110px]"
        >
          <strong>{proposal.symbol}</strong>
          <SideBadge side={proposal.side} />
          <span className="truncate text-muted-foreground">
            {proposal.rejection_reason ?? proposal.rationale}
          </span>
          <Badge tone={proposal.status === "executed" ? "good" : "bad"}>{proposal.status}</Badge>
        </div>
      ))}
    </div>
  );
}

function ActivityView({ data }: { data: BootstrapData }) {
  const [tab, setTab] = useState<"orders" | "agent" | "system">("orders");
  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Immutable trail"
        title="Activity"
        description="Orders, agent runs, and system events remain separate and explainable."
      />
      <div className="flex gap-1 border-b border-border">
        <Tab active={tab === "orders"} onClick={() => setTab("orders")}>
          Orders
        </Tab>
        <Tab active={tab === "agent"} onClick={() => setTab("agent")}>
          Agent runs
        </Tab>
        <Tab active={tab === "system"} onClick={() => setTab("system")}>
          System log
        </Tab>
      </div>
      {tab === "orders" && (
        <Panel title="Order ledger" sub={`${data.orders.length} recent`}>
          <OrderLedger data={data} />
        </Panel>
      )}
      {tab === "agent" && (
        <Panel title="Agent runs" sub={`${data.agent_runs.length} recent`}>
          <AgentRuns data={data} />
        </Panel>
      )}
      {tab === "system" && (
        <Panel title="System events" sub={`${data.logs.length} recent`}>
          <SystemLog data={data} />
        </Panel>
      )}
    </div>
  );
}

function OrderLedger({ data }: { data: BootstrapData }) {
  if (!data.orders.length)
    return (
      <EmptyState
        icon={History}
        title="No v2 orders yet"
        description="Legacy trades are preserved separately; new fills will appear here."
      />
    );
  return (
    <div className="divide-y divide-border/60">
      {data.orders.map((order) => (
        <div
          key={order.id}
          className="grid gap-2 p-3 text-xs sm:grid-cols-[120px_80px_100px_1fr_120px]"
        >
          <strong>{order.symbol}</strong>
          <SideBadge side={order.side} />
          <Badge tone={order.status === "filled" ? "good" : "bad"}>{order.status}</Badge>
          <span className="truncate text-muted-foreground">
            {order.rejection_reason ??
              `${number.format(order.quantity)} @ ${number.format(order.fill_price ?? 0)} · ${order.source}`}
          </span>
          <span className="text-right text-muted-foreground">{relativeTime(order.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

function AgentRuns({ data }: { data: BootstrapData }) {
  if (!data.agent_runs.length)
    return (
      <EmptyState
        icon={Bot}
        title="No guarded cycles yet"
        description="Trigger an advisory scan when the LLM provider is ready."
      />
    );
  return (
    <div className="divide-y divide-border/60">
      {data.agent_runs.map((run) => (
        <div key={run.id} className="grid gap-2 p-3 text-xs sm:grid-cols-[120px_110px_1fr_120px]">
          <Badge tone={run.status === "completed" ? "good" : "bad"}>{run.status}</Badge>
          <span>{run.mode.replace("_", " ")}</span>
          <span className="text-muted-foreground">
            {run.error ?? `${run.proposal_count} proposals · ${run.executed_count} executed`}
          </span>
          <span className="text-right text-muted-foreground">
            {run.duration_ms == null ? "—" : `${run.duration_ms} ms`}
          </span>
        </div>
      ))}
    </div>
  );
}

function SystemLog({ data }: { data: BootstrapData }) {
  return (
    <div className="max-h-[650px] divide-y divide-border/60 overflow-y-auto">
      {data.logs.map((entry) => (
        <div key={entry.id} className="grid gap-2 p-3 text-xs sm:grid-cols-[100px_110px_1fr_100px]">
          <Badge
            tone={entry.level === "error" ? "bad" : entry.level === "warn" ? "warn" : "neutral"}
          >
            {entry.action}
          </Badge>
          <strong>{entry.pair ?? "SYSTEM"}</strong>
          <span className="text-foreground/80">{entry.message}</span>
          <span className="text-right text-muted-foreground">{relativeTime(entry.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

function SettingsView({
  data,
  mutate,
}: {
  data: BootstrapData;
  mutate: (label: string, action: () => Promise<unknown>) => Promise<void>;
}) {
  const [equity, setEquity] = useState(String(data.config.starting_equity));
  const [provider, setProvider] = useState(data.agent.provider);
  const [model, setModel] = useState(data.agent.model);
  const [apiKey, setApiKey] = useState("");
  return (
    <div className="space-y-4">
      <PageHeading
        eyebrow="Control plane"
        title="Settings"
        description="Risk presets are fixed guardrails. Configuration changes are explicit and auditable."
      />
      <div className="grid gap-3 xl:grid-cols-2">
        <Panel title="Paper account" sub="Local SQLite ledger">
          <div className="space-y-5 p-4">
            <Field label="Starting equity">
              <input
                type="number"
                value={equity}
                onChange={(event) => setEquity(event.target.value)}
                className="terminal-input"
              />
            </Field>
            <button
              onClick={() =>
                void mutate("Starting equity updated", () =>
                  terminalApi.updateConfig({ starting_equity: Number(equity) }),
                )
              }
              className="primary-button"
            >
              Save account value
            </button>
            <div className="border-t border-border pt-4 text-xs text-muted-foreground">
              <div className="flex items-center gap-2 text-bull">
                <ShieldCheck className="h-4 w-4" /> Migration backup ready
              </div>
              <div className="mt-2 break-all text-[10px]">
                {data.config.last_backup_path ??
                  "A backup will be created before the first legacy migration."}
              </div>
            </div>
          </div>
        </Panel>
        <Panel title="Risk preset" sub="Balanced is the new-account default">
          <div className="grid gap-2 p-4 sm:grid-cols-3">
            {(["conservative", "balanced", "aggressive"] as RiskProfile[]).map((profile) => (
              <button
                key={profile}
                onClick={() =>
                  void mutate(`${profile} risk preset selected`, () =>
                    terminalApi.updateAgent({ risk_profile: profile }),
                  )
                }
                className={`border p-3 text-left ${data.portfolio.risk_profile === profile ? "border-primary bg-primary/10" : "border-border hover:border-primary/40"}`}
              >
                <div className="text-xs font-bold uppercase text-foreground">{profile}</div>
                <div className="mt-2 text-[10px] leading-5 text-muted-foreground">
                  {profile === "conservative"
                    ? "0.5% risk · 2% cutoff · 50% exposure"
                    : profile === "balanced"
                      ? "1% risk · 3% cutoff · 80% exposure"
                      : "2% risk · 5% cutoff · 150% exposure"}
                </div>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="AI authority" sub="Agent never bypasses the execution engine">
          <div className="space-y-4 p-4">
            {(["advisory", "guarded_autopilot"] as AgentMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() =>
                  void mutate(`${mode.replace("_", " ")} selected`, () =>
                    terminalApi.updateAgent({ mode }),
                  )
                }
                className={`flex w-full items-start gap-3 border p-3 text-left ${data.agent.mode === mode ? "border-primary bg-primary/10" : "border-border"}`}
              >
                {mode === "advisory" ? (
                  <Bot className="h-5 w-5 text-primary" />
                ) : (
                  <Zap className="h-5 w-5 text-primary" />
                )}
                <span>
                  <strong className="block text-xs uppercase">{mode.replace("_", " ")}</strong>
                  <span className="mt-1 block text-[10px] leading-4 text-muted-foreground">
                    {mode === "advisory"
                      ? "Proposals wait for operator approval."
                      : "Valid proposals execute only after every hard risk check passes."}
                  </span>
                </span>
              </button>
            ))}
            <button
              onClick={() => void mutate("Agent cycle triggered", terminalApi.triggerAgent)}
              disabled={data.agent.kill_switch || data.agent.cycle_active}
              className="secondary-button w-full py-2.5"
            >
              Run one guarded scan
            </button>
          </div>
        </Panel>
        <Panel title="LLM provider" sub={`${data.agent.provider} · ${data.agent.model}`}>
          <div className="space-y-4 p-4">
            <Field label="Provider">
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                className="terminal-select"
              >
                <option value="ollama">Ollama</option>
                <option value="lmstudio">LM Studio</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Gemini</option>
                <option value="openrouter">OpenRouter</option>
                <option value="groq">Groq</option>
                <option value="deepseek">DeepSeek</option>
              </select>
            </Field>
            <Field label="Model">
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                className="terminal-input"
              />
            </Field>
            <Field label="API key">
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="Blank preserves the encrypted key"
                className="terminal-input"
              />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() =>
                  void mutate("LLM configuration saved", () =>
                    terminalApi.updateLlm({
                      provider,
                      model,
                      api_key: apiKey || null,
                      num_ctx: 8192,
                    }),
                  )
                }
                className="primary-button"
              >
                Save provider
              </button>
              <button
                onClick={() => void mutate("LLM provider responded", terminalApi.testLlm)}
                className="secondary-button"
              >
                Test connection
              </button>
            </div>
          </div>
        </Panel>
      </div>
      <Panel title="Setup status" sub="Local-only deployment">
        <div className="grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Health
            label="Backend"
            ok={data.system.backend.ok}
            detail={`v${data.system.backend.version}`}
          />
          <Health label="Database" ok={data.system.database.ok} detail="SQLite + WAL" />
          <Health label="Market data" ok={data.system.market_data.ok} detail="Delayed free feed" />
          <Health
            label="Autopilot"
            ok={data.system.autopilot_ready}
            detail={data.system.autopilot_ready ? "Ready" : "Needs attention"}
          />
        </div>
      </Panel>
    </div>
  );
}

function OrderTicket({
  instrument,
  quote,
  onClose,
  onFilled,
}: {
  instrument: Instrument;
  quote: Quote;
  onClose: () => void;
  onFilled: () => Promise<void>;
}) {
  const [side, setSide] = useState<"long" | "short">("long");
  const [quantity, setQuantity] = useState(instrument.asset_class === "forex" ? "1000" : "1");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [allowUnprotected, setAllowUnprotected] = useState(false);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const payload = useMemo(
    () => ({
      instrument_id: instrument.id,
      side,
      quantity: Number(quantity),
      stop_loss: stopLoss ? Number(stopLoss) : null,
      take_profit: takeProfit ? Number(takeProfit) : null,
      allow_unprotected: allowUnprotected,
    }),
    [allowUnprotected, instrument.id, quantity, side, stopLoss, takeProfit],
  );
  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      if (!Number.isFinite(payload.quantity) || payload.quantity <= 0) return;
      try {
        setPreview(await terminalApi.previewOrder(payload, controller.signal));
        setPreviewError(null);
      } catch (requestError) {
        if (!(requestError instanceof DOMException)) setPreviewError(errorMessage(requestError));
      }
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [payload]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const submit = async () => {
    if (!preview?.allowed) return;
    setBusy(true);
    try {
      await terminalApi.createOrder({ ...payload, idempotency_key: crypto.randomUUID() });
      toast.success(`${instrument.symbol} paper order filled`);
      await onFilled();
    } catch (requestError) {
      toast.error(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="order-ticket-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="max-h-[92vh] w-full overflow-y-auto border border-border bg-card shadow-2xl sm:max-w-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-4 py-3">
          <div>
            <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-primary">
              Paper order preview
            </div>
            <h2 id="order-ticket-title" className="mt-1 font-display text-lg font-bold">
              {instrument.symbol}{" "}
              <span className="text-xs font-normal text-muted-foreground">{instrument.name}</span>
            </h2>
          </div>
          <button onClick={onClose} className="icon-button" aria-label="Close order ticket">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 p-4">
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setSide("long")}
              className={`border py-2.5 text-xs font-bold uppercase ${side === "long" ? "border-bull bg-bull/15 text-bull" : "border-border text-muted-foreground"}`}
            >
              Long / Buy
            </button>
            <button
              onClick={() => setSide("short")}
              className={`border py-2.5 text-xs font-bold uppercase ${side === "short" ? "border-bear bg-bear/15 text-bear" : "border-border text-muted-foreground"}`}
            >
              Short / Sell
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Quantity">
              <input
                type="number"
                step="any"
                min="0"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="terminal-input"
              />
            </Field>
            <Field label="Stop loss">
              <input
                type="number"
                step="any"
                value={stopLoss}
                onChange={(event) => setStopLoss(event.target.value)}
                placeholder="Required for AI"
                className="terminal-input"
              />
            </Field>
            <Field label="Take profit">
              <input
                type="number"
                step="any"
                value={takeProfit}
                onChange={(event) => setTakeProfit(event.target.value)}
                placeholder="Optional manual"
                className="terminal-input"
              />
            </Field>
          </div>
          {!stopLoss && (
            <label className="flex cursor-pointer items-start gap-3 border border-primary/30 bg-primary/[0.04] p-3 text-xs">
              <input
                type="checkbox"
                checked={allowUnprotected}
                onChange={(event) => setAllowUnprotected(event.target.checked)}
                className="mt-0.5 accent-primary"
              />
              <span>
                <strong className="block text-primary">Allow an unprotected manual position</strong>
                <span className="mt-1 block text-muted-foreground">
                  This is never permitted in guarded autopilot mode.
                </span>
              </span>
            </label>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MiniStat
              label="Quote"
              value={quote?.price == null ? "—" : number.format(quote.price)}
            />
            <MiniStat
              label="Est. fill"
              value={preview?.estimated_fill == null ? "—" : number.format(preview.estimated_fill)}
            />
            <MiniStat
              label="Notional"
              value={preview?.notional == null ? "—" : compactCurrency.format(preview.notional)}
            />
            <MiniStat
              label="Risk to stop"
              value={
                preview?.risk_amount == null ? "Unbounded" : currency.format(preview.risk_amount)
              }
            />
            <MiniStat
              label="Est. costs"
              value={currency.format((preview?.fee ?? 0) + (preview?.estimated_exit_fee ?? 0))}
            />
            <MiniStat
              label="Slippage"
              value={preview?.slippage_bps == null ? "—" : `${preview.slippage_bps} bps / side`}
            />
          </div>
          {preview?.errors.length || previewError ? (
            <div className="space-y-1 border border-bear/40 bg-bear/10 p-3 text-xs text-bear">
              {previewError && <div>{previewError}</div>}
              {preview?.errors.map((issue) => (
                <div key={`${issue.code}-${issue.field}`}>
                  <AlertTriangle className="mr-1.5 inline h-3 w-3" />
                  {issue.message}
                </div>
              ))}
            </div>
          ) : null}
          {preview?.warnings.map((issue) => (
            <div
              key={issue.code}
              className="border border-primary/30 bg-primary/[0.04] p-3 text-xs text-primary"
            >
              {issue.message}
            </div>
          ))}
          <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
            <span>Resulting exposure</span>
            <strong className="text-foreground">
              {preview?.resulting_exposure_pct?.toFixed(1) ?? "—"}%
            </strong>
          </div>
          <button
            onClick={() => void submit()}
            disabled={!preview?.allowed || busy}
            className="primary-button w-full py-3 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy
              ? "Submitting…"
              : preview?.allowed
                ? "Confirm paper fill"
                : "Resolve validation issues"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="mb-1">
      <div className="text-[9px] font-bold uppercase tracking-[0.24em] text-primary">
        // {eyebrow}
      </div>
      <h1 className="mt-1 font-display text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
      <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">{description}</p>
    </header>
  );
}

function Panel({
  title,
  sub,
  children,
  right,
}: {
  title: string;
  sub?: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className="terminal-panel min-w-0">
      <div className="flex min-h-12 items-center justify-between gap-3 border-b border-border px-3 sm:px-4">
        <div className="min-w-0">
          <h2 className="truncate text-[10px] font-bold uppercase tracking-[0.2em] text-primary">
            // {title}
          </h2>
          {sub && (
            <p className="mt-0.5 truncate text-[9px] uppercase tracking-wider text-muted-foreground">
              {sub}
            </p>
          )}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "bull" | "bear";
  icon: typeof Activity;
}) {
  return (
    <article className="terminal-panel min-w-0 p-3 sm:p-4">
      <div className="flex items-center justify-between gap-2 text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground">
        <span className="truncate">{label}</span>
        <Icon className="h-3.5 w-3.5 shrink-0 text-primary" />
      </div>
      <div
        className={`mt-2 truncate font-display text-lg font-bold tabular-nums sm:text-xl ${tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : ""}`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 truncate text-[9px] uppercase text-muted-foreground">{sub}</div>}
    </article>
  );
}

function EquityChart({ data }: { data: Array<{ t: string; eq: number }> }) {
  if (data.length < 2)
    return (
      <EmptyState
        icon={TrendingUp}
        title="No equity history"
        description="The curve begins with the first paper fill."
      />
    );
  const width = 900,
    height = 260,
    pad = 24;
  const values = data.map((point) => point.eq),
    low = Math.min(...values),
    high = Math.max(...values);
  const x = (index: number) => pad + (index / Math.max(data.length - 1, 1)) * (width - pad * 2);
  const y = (value: number) =>
    height - pad - ((value - low) / Math.max(high - low, 1)) * (height - pad * 2);
  const path = data
    .map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.eq).toFixed(1)}`)
    .join(" ");
  const up = values.at(-1)! >= values[0];
  return (
    <div className="relative p-3">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-[220px] w-full sm:h-[260px]"
        role="img"
        aria-label="Portfolio equity curve"
      >
        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
          <line
            key={fraction}
            x1={pad}
            x2={width - pad}
            y1={pad + fraction * (height - pad * 2)}
            y2={pad + fraction * (height - pad * 2)}
            stroke="currentColor"
            className="text-border"
            strokeDasharray="3 5"
          />
        ))}
        <path
          d={`${path} L${x(data.length - 1)},${height - pad} L${x(0)},${height - pad} Z`}
          fill={up ? "var(--color-bull)" : "var(--color-bear)"}
          opacity=".08"
        />
        <path
          d={path}
          fill="none"
          stroke={up ? "var(--color-bull)" : "var(--color-bear)"}
          strokeWidth="2"
        />
      </svg>
      <div className="absolute right-5 top-5 text-right">
        <div className="text-[9px] uppercase text-muted-foreground">Current</div>
        <strong>{compactCurrency.format(values.at(-1)!)}</strong>
      </div>
      <div className="absolute bottom-5 left-5 text-[9px] text-muted-foreground">
        RANGE {compactCurrency.format(low)} — {compactCurrency.format(high)}
      </div>
    </div>
  );
}

function Progress({ label, value, display }: { label: string; value: number; display: string }) {
  const capped = Math.min(Math.max(value, 0), 100);
  return (
    <div>
      <div className="mb-2 flex justify-between text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>{label}</span>
        <strong className="text-foreground">{display}</strong>
      </div>
      <div className="h-2 overflow-hidden bg-secondary">
        <div
          className={`h-full ${value > 90 ? "bg-bear" : value > 70 ? "bg-primary" : "bg-bull"}`}
          style={{ width: `${capped}%` }}
        />
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-border/70 bg-background/40 p-2.5">
      <div className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 truncate font-bold tabular-nums">{value}</div>
    </div>
  );
}
function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof Target;
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center p-6 text-center">
      <Icon className="h-7 w-7 text-muted-foreground/60" />
      <strong className="mt-3 text-sm">{title}</strong>
      <p className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{description}</p>
    </div>
  );
}
function SideBadge({ side }: { side: "long" | "short" }) {
  return (
    <span
      className={`inline-flex border px-1.5 py-0.5 text-[9px] font-bold uppercase ${side === "long" ? "border-bull/40 bg-bull/10 text-bull" : "border-bear/40 bg-bear/10 text-bear"}`}
    >
      {side}
    </span>
  );
}
function AssetBadge({ value }: { value: string }) {
  return (
    <span className="text-[8px] font-bold uppercase tracking-wider text-muted-foreground">
      {value}
    </span>
  );
}
function ProtectionBadge({ position }: { position: Position }) {
  return position.protection_status === "protected" ? (
    <Badge tone="good">
      <ShieldCheck className="mr-1 h-3 w-3" /> Protected
    </Badge>
  ) : (
    <Badge tone="warn">
      <ShieldAlert className="mr-1 h-3 w-3" /> Unprotected
    </Badge>
  );
}
function ReviewBadge({ value }: { value: TradeIdea["review_state"] }) {
  const tone =
    value === "scored" || value === "valid" ? "good" : value === "unscored" ? "neutral" : "warn";
  return <Badge tone={tone}>{value.replace("_", " ")}</Badge>;
}
function Badge({
  tone,
  children,
}: {
  tone: "good" | "bad" | "warn" | "neutral";
  children: ReactNode;
}) {
  const styles =
    tone === "good"
      ? "border-bull/30 bg-bull/10 text-bull"
      : tone === "bad"
        ? "border-bear/30 bg-bear/10 text-bear"
        : tone === "warn"
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex w-fit items-center border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${styles}`}
    >
      {children}
    </span>
  );
}
function QuoteState({ quote }: { quote?: Quote }) {
  if (!quote) return <span className="text-[9px] text-bear">Unavailable</span>;
  return (
    <span
      className={`text-[9px] ${quote.stale ? "text-primary" : quote.market_status === "open" ? "text-bull" : "text-muted-foreground"}`}
    >
      {quote.stale
        ? "Stale quote"
        : quote.market_status === "open"
          ? "Delayed · open"
          : "Market closed"}
    </span>
  );
}
function Tone({ value, children }: { value: number; children: ReactNode }) {
  return (
    <span className={value > 0 ? "text-bull" : value < 0 ? "text-bear" : "text-muted-foreground"}>
      {children}
    </span>
  );
}
function Th({ children, right }: { children?: ReactNode; right?: boolean }) {
  return (
    <th
      className={`px-3 py-3 text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground ${right ? "text-right" : "text-left"}`}
    >
      {children}
    </th>
  );
}
function Td({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <td className={`px-3 py-3 tabular-nums ${right ? "text-right" : "text-left"}`}>{children}</td>
  );
}
function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`whitespace-nowrap border-b-2 px-3 py-2.5 text-[10px] font-bold uppercase tracking-wider ${active ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}
    >
      {children}
    </button>
  );
}
function Count({ children }: { children: ReactNode }) {
  return <span className="ml-1.5 text-muted-foreground">{children}</span>;
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[9px] font-bold uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}
function Health({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="flex items-center gap-3 border border-border p-3">
      {ok ? (
        <Check className="h-4 w-4 text-bull" />
      ) : (
        <AlertTriangle className="h-4 w-4 text-primary" />
      )}
      <div>
        <div className="text-xs font-bold">{label}</div>
        <div className="text-[9px] uppercase text-muted-foreground">{detail}</div>
      </div>
    </div>
  );
}
function LoadingScreen() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center border border-primary/50 bg-primary/10 font-display text-lg font-bold text-primary">
          N
        </div>
        <div className="mt-4 text-[10px] font-bold uppercase tracking-[0.28em] text-muted-foreground">
          Loading paper ledger
        </div>
      </div>
    </main>
  );
}
function OfflineScreen({ error, retry }: { error: string; retry: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="terminal-panel max-w-md p-6 text-center">
        <AlertTriangle className="mx-auto h-8 w-8 text-bear" />
        <h1 className="mt-4 font-display text-xl font-bold">Terminal backend unavailable</h1>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{error}</p>
        <p className="mt-3 text-[10px] text-muted-foreground">
          Run <code className="text-primary">.\start-nexus.ps1</code> from the project root.
        </p>
        <button onClick={retry} className="primary-button mt-5">
          Retry connection
        </button>
      </div>
    </main>
  );
}
