import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Loader2, MessageSquare } from "lucide-react";
import { Suspense, useEffect } from "react";

import ChatDrawer from "@/features/chat/ChatDrawer";
import { MarketChip } from "@/features/markets/MarketChip";
import { useChat } from "@/features/chat/chat-context";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { useLiveUpdates, type LiveState } from "@/lib/live";
import { useNav, type View } from "@/lib/nav";
import type { SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { AccountSwitcher } from "./AccountSwitcher";
import { Loading } from "./ui";
import { VIEWS, warmAll, warmView } from "./views";

export default function AppShell() {
  const { view, go } = useNav();
  const chat = useChat();
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    // Changes arrive over the live stream; polling is only a fallback.
    refetchInterval: 30_000,
    retry: false,
  });
  const live = useLiveUpdates();
  const warm = (key: View) => void warmView(client, key);

  // Once the current tab has loaded, fetch every other tab's code and data in the background
  // so switching tabs shows content immediately.
  useEffect(() => {
    const timer = window.setTimeout(() => void warmAll(client, view), 1500);
    return () => window.clearTimeout(timer);
    // Only on first load: later tab switches warm on hover.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);
  const Current = VIEWS[view].component;
  const drawerOpen = chat.open && view !== "chat";

  return (
    <div className={cn("min-h-screen transition-[padding]", drawerOpen && "sm:pr-[460px]")}>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[88px] flex-col items-center gap-2.5 border-r border-border bg-background py-5 lg:flex">
        <Brand status={status.data} />
        <nav aria-label="Main" className="flex flex-1 flex-col items-center gap-2">
          {(Object.keys(VIEWS) as View[]).map((key) => {
            const Icon = VIEWS[key].icon;
            const active = view === key;
            return (
              <button
                key={key}
                onClick={() => go(key)}
                onMouseEnter={() => warm(key)}
                onFocus={() => warm(key)}
                aria-label={VIEWS[key].label}
                aria-current={active ? "page" : undefined}
                title={VIEWS[key].label}
                className={cn(
                  "grid h-12 w-12 place-items-center rounded-[14px] transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "bg-raised text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="h-5 w-5" />
              </button>
            );
          })}
        </nav>
      </aside>

      <div className="lg:pl-[88px]">
        <header className="sticky top-0 z-20 flex flex-wrap items-center gap-2.5 border-b border-border bg-background/95 px-4 py-3 backdrop-blur lg:px-7">
          <div className="lg:hidden">
            <Brand status={status.data} compact />
          </div>
          <nav aria-label="Main" className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto lg:hidden">
            {(Object.keys(VIEWS) as View[]).map((key) => {
              const Icon = VIEWS[key].icon;
              return (
                <button
                  key={key}
                  onClick={() => go(key)}
                  onTouchStart={() => warm(key)}
                  className={cn(
                    "icon-button shrink-0",
                    view === key && "!border-primary !bg-primary !text-primary-foreground",
                  )}
                  aria-label={VIEWS[key].label}
                >
                  <Icon className="h-4 w-4" />
                </button>
              );
            })}
          </nav>
          <div className="hidden min-w-0 flex-1 lg:block">
            <BootstrapBanner status={status.data} />
          </div>
          {status.data?.analyst_running && (
            <span className="flex items-center gap-1.5 text-xs font-semibold text-bull">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Analyst researching
            </span>
          )}
          <AccountSwitcher />
          {!status.error && (
            <MarketChip marketId="nyse" className="hidden shrink-0 md:inline-flex" />
          )}
          <LiveDot live={live} offline={Boolean(status.error)} />
          {view !== "chat" && (
            <button
              className={cn("primary-button", drawerOpen && "!bg-[#1e6e37]")}
              onClick={() => chat.setOpen(!chat.open)}
            >
              <MessageSquare className="h-4 w-4" /> Ask AI
            </button>
          )}
        </header>
        <main className="mx-auto max-w-[1600px] px-4 py-6 lg:px-7">
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

function LiveDot({ live, offline }: { live: LiveState; offline: boolean }) {
  const last = live.lastEventAt
    ? ` (last update ${new Date(live.lastEventAt).toLocaleTimeString()})`
    : "";
  const on = live.connected && !offline;
  return (
    <span
      className={cn(
        "inline-flex min-h-10 shrink-0 items-center gap-2 rounded-xl border px-3 text-xs font-semibold",
        on ? "border-[#1f3a27] bg-[#0f1a12] text-bull" : "border-border text-muted-foreground",
      )}
      title={
        on
          ? `Live: pages refresh as soon as data changes${last}`
          : offline
            ? "Backend offline"
            : "Reconnecting to live updates; pages still refresh on a timer"
      }
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", on ? "bg-bull" : "bg-bear")} />
      {on ? "Live" : offline ? "Backend offline" : "Reconnecting"}
    </span>
  );
}

function Brand({ status, compact = false }: { status?: SystemStatus; compact?: boolean }) {
  const llm = status ? `AI: ${status.llm.provider} · ${status.llm.model}` : "NEXUS";
  return (
    <div
      title={llm}
      className={cn(
        "grid place-items-center rounded-[14px] border-[1.5px] border-foreground",
        compact ? "h-10 w-10" : "mb-3 h-12 w-12",
      )}
    >
      <BarChart3 className="h-5 w-5" aria-label="NEXUS" />
    </div>
  );
}

function BootstrapBanner({ status }: { status?: SystemStatus }) {
  const running = status?.jobs.filter((job) => job.running) ?? [];
  if (status && !status.has_data) {
    const init = status.jobs.find((job) => job.name === "init");
    return (
      <div className="flex items-center gap-2 rounded-xl border border-[#1f3a27] bg-[#0f1a12] px-3 py-2 text-xs">
        <Loader2 className="h-3 w-3 animate-spin text-bull" />
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
      <div className="truncate text-xs text-muted-foreground">
        {running.map((job) => `${job.name}: ${job.progress ?? "running"}`).join(" · ")}
      </div>
    );
  }
  const news = status?.jobs.find((job) => job.name === "news");
  return news ? (
    <div className="text-xs text-muted-foreground">News updated {ago(news.last_finished)}</div>
  ) : null;
}

function Offline() {
  return (
    <div className="terminal-panel mx-auto mt-10 max-w-lg p-6 text-center">
      <div className="text-base font-bold text-bear">Backend offline</div>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        Start the Python server:{" "}
        <code className="font-mono text-bull">
          cd server && python -m uvicorn main:app --port 8000
        </code>
        , or run <code className="font-mono text-bull">.\start-nexus.ps1</code> from the project
        root.
      </p>
    </div>
  );
}
