import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Briefcase,
  Globe,
  LineChart,
  Loader2,
  MessageSquare,
  Newspaper,
  Settings,
  Target,
  Telescope,
} from "lucide-react";
import { lazy, Suspense, type ComponentType } from "react";

import ChatDrawer from "@/features/chat/ChatDrawer";
import { MarketChip } from "@/features/markets/MarketChip";
import { useChat } from "@/features/chat/chat-context";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useNav, type View } from "@/lib/nav";
import type { SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Loading } from "./ui";

const VIEWS: Record<
  View,
  { label: string; icon: ComponentType<{ className?: string }>; component: ComponentType }
> = {
  today: {
    label: "Today",
    icon: Activity,
    component: lazy(() => import("@/features/today/TodayView")),
  },
  chat: {
    label: "AI chat",
    icon: MessageSquare,
    component: lazy(() => import("@/features/chat/ChatView")),
  },
  ideas: {
    label: "Screener",
    icon: Telescope,
    component: lazy(() => import("@/features/ideas/IdeasView")),
  },
  asset: {
    label: "Asset",
    icon: LineChart,
    component: lazy(() => import("@/features/asset/AssetView")),
  },
  news: {
    label: "News & events",
    icon: Newspaper,
    component: lazy(() => import("@/features/news/NewsView")),
  },
  portfolio: {
    label: "Portfolio",
    icon: Briefcase,
    component: lazy(() => import("@/features/portfolio/PortfolioView")),
  },
  markets: {
    label: "Market hours",
    icon: Globe,
    component: lazy(() => import("@/features/markets/MarketsView")),
  },
  record: {
    label: "Track record",
    icon: Target,
    component: lazy(() => import("@/features/record/TrackRecordView")),
  },
  settings: {
    label: "Settings",
    icon: Settings,
    component: lazy(() => import("@/features/settings/SettingsView")),
  },
};

export default function AppShell() {
  const { view, go } = useNav();
  const chat = useChat();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 10_000,
    retry: false,
  });
  const Current = VIEWS[view].component;
  const drawerOpen = chat.open && view !== "chat";

  return (
    <div className={cn("min-h-screen transition-[padding]", drawerOpen && "sm:pr-[460px]")}>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-52 flex-col border-r border-border bg-background/95 lg:flex">
        <Brand />
        <nav className="flex-1 space-y-0.5 px-2 py-3">
          {(Object.keys(VIEWS) as View[]).map((key) => {
            const Icon = VIEWS[key].icon;
            return (
              <button
                key={key}
                onClick={() => go(key)}
                className={cn(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left text-[11px] font-bold uppercase tracking-[0.12em] transition-colors",
                  view === key
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent/40 hover:text-foreground",
                )}
              >
                <Icon className="h-3.5 w-3.5" /> {VIEWS[key].label}
              </button>
            );
          })}
        </nav>
        <SystemFooter status={status.data} />
      </aside>

      <div className="lg:pl-52">
        <header className="sticky top-0 z-20 flex items-center gap-2 border-b border-border bg-background/90 px-4 py-2 backdrop-blur">
          <div className="lg:hidden">
            <Brand compact />
          </div>
          <nav className="flex min-w-0 flex-1 gap-1 overflow-x-auto lg:hidden">
            {(Object.keys(VIEWS) as View[]).map((key) => {
              const Icon = VIEWS[key].icon;
              return (
                <button
                  key={key}
                  onClick={() => go(key)}
                  className={cn(
                    "icon-button shrink-0",
                    view === key && "!border-primary !text-primary",
                  )}
                  aria-label={VIEWS[key].label}
                >
                  <Icon className="h-3.5 w-3.5" />
                </button>
              );
            })}
          </nav>
          <div className="hidden flex-1 lg:block">
            <BootstrapBanner status={status.data} />
          </div>
          {!status.error && (
            <MarketChip marketId="nyse" className="hidden shrink-0 md:inline-flex" />
          )}
          {status.error ? (
            <span className="text-[10px] font-bold uppercase tracking-[0.15em] text-bear">
              backend offline
            </span>
          ) : status.data?.analyst_running ? (
            <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.15em] text-primary">
              <Loader2 className="h-3 w-3 animate-spin" /> analyst researching
            </span>
          ) : null}
          {view !== "chat" && (
            <button
              className={cn(
                "primary-button inline-flex items-center gap-1.5",
                drawerOpen && "!bg-primary/25",
              )}
              onClick={() => chat.setOpen(!chat.open)}
            >
              <MessageSquare className="h-3.5 w-3.5" /> Ask AI
            </button>
          )}
        </header>
        <main className="mx-auto max-w-[1600px] px-4 py-5">
          <div className="mb-3 lg:hidden">
            <BootstrapBanner status={status.data} />
          </div>
          {status.error ? (
            <Offline />
          ) : (
            <Suspense fallback={<Loading />}>
              <Current />
            </Suspense>
          )}
        </main>
      </div>
      <ChatDrawer />
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={cn("flex items-center gap-2", compact ? "" : "border-b border-border px-4 py-4")}
    >
      <BarChart3 className="h-4 w-4 text-primary" />
      <div>
        <div className="font-display text-sm font-bold tracking-[0.25em]">NEXUS</div>
        {!compact && (
          <div className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
            evidence-based research
          </div>
        )}
      </div>
    </div>
  );
}

function SystemFooter({ status }: { status?: SystemStatus }) {
  if (!status) return null;
  const c = status.coverage;
  return (
    <div className="space-y-1 border-t border-border px-4 py-3 text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
      <div className="flex justify-between">
        <span>LLM</span>
        <span className={status.llm.key_set ? "text-bull" : "text-bear"}>
          {status.llm.provider}
        </span>
      </div>
      <div className="truncate normal-case tracking-normal">{status.llm.model}</div>
      <div className="flex justify-between">
        <span>Prices</span>
        <span>{c.last_bar ?? "—"}</span>
      </div>
      <div className="flex justify-between">
        <span>Events</span>
        <span>{c.events.toLocaleString()}</span>
      </div>
      <div className="flex justify-between">
        <span>Headlines</span>
        <span>{c.news.toLocaleString()}</span>
      </div>
      <div className="flex justify-between">
        <span>GDELT days</span>
        <span>{c.gdelt_days}</span>
      </div>
      <div className="flex justify-between">
        <span>Autopilot</span>
        <span className={status.autopilot ? "text-primary" : ""}>
          {status.autopilot ? "on" : "off"}
        </span>
      </div>
    </div>
  );
}

function BootstrapBanner({ status }: { status?: SystemStatus }) {
  const running = status?.jobs.filter((job) => job.running) ?? [];
  if (status && !status.has_data) {
    const init = status.jobs.find((job) => job.name === "init");
    return (
      <div className="flex items-center gap-2 border border-primary/40 bg-primary/5 px-3 py-1.5 text-[11px]">
        <Loader2 className="h-3 w-3 animate-spin text-primary" />
        <span>
          First run: downloading 10 years of history and building event studies (10–20 min).{" "}
          <span className="text-muted-foreground">
            {init?.progress ??
              (init?.last_status === "error" ? "Bootstrap failed — see Settings → jobs." : "")}
          </span>
        </span>
      </div>
    );
  }
  if (running.length) {
    return (
      <div className="truncate text-[10px] text-muted-foreground">
        {running.map((job) => `${job.name}: ${job.progress ?? "running"}`).join(" · ")}
      </div>
    );
  }
  const news = status?.jobs.find((job) => job.name === "news");
  return news ? (
    <div className="text-[10px] text-muted-foreground">news updated {ago(news.last_finished)}</div>
  ) : null;
}

function Offline() {
  return (
    <div className="terminal-panel mx-auto mt-10 max-w-lg p-6 text-center">
      <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-bear">
        Backend offline
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
        Start the Python server:{" "}
        <code className="text-primary">cd server && python -m uvicorn main:app --port 8000</code>,
        or run <code className="text-primary">.\start-nexus.ps1</code> from the project root.
      </p>
    </div>
  );
}
