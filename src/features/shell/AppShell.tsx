import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Briefcase, Loader2, MessageSquare, Newspaper, Telescope } from "lucide-react";
import { Suspense, useEffect, useState } from "react";

import ChatDrawer from "@/features/chat/ChatDrawer";
import { useChat } from "@/features/chat/chat-context";
import { api } from "@/lib/api";
import { useLiveUpdates } from "@/lib/live";
import { useNav, type View } from "@/lib/nav";
import type { SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { RightRail } from "./RightRail";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Loading } from "./ui";
import { VIEWS, warmAll } from "./views";

function usePersistentFlag(key: string, initial: boolean) {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored == null ? initial : stored === "1";
    } catch {
      return initial;
    }
  });
  const update = (next: boolean) => {
    setValue(next);
    try {
      window.localStorage.setItem(key, next ? "1" : "0");
    } catch {
      // Storage blocked: the layout choice lasts for this visit.
    }
  };
  return [value, update] as const;
}

/** Workspace layout: sidebar | (top bar + page) | watchlist and live wire; chat slides over. */
export default function AppShell() {
  const { view } = useNav();
  const chat = useChat();
  const client = useQueryClient();
  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    // Changes arrive over the live stream; polling is only a fallback. While the server is
    // unreachable (a Render restart takes about a minute), check every 5 s instead.
    refetchInterval: (query) => (query.state.error ? 5_000 : 30_000),
    retry: false,
  });
  const live = useLiveUpdates();
  const [collapsed, setCollapsed] = usePersistentFlag("nexus.sidebar-collapsed", false);
  const [railOpen, setRailOpen] = usePersistentFlag("nexus.rail-open", true);
  const [menuOpen, setMenuOpen] = useState(false);

  // Once the current page has loaded, fetch every other page's code and data in the background
  // so switching pages shows content immediately.
  useEffect(() => {
    const timer = window.setTimeout(() => void warmAll(client, view), 1500);
    return () => window.clearTimeout(timer);
    // Only on first load: later switches warm on hover.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const Current = VIEWS[view].component;
  const drawerOpen = chat.open && view !== "chat";
  const offline = Boolean(status.error);
  // Never reached the server: nothing to show. Lost it after loading: keep the page and its
  // cached data on screen and say we're reconnecting, instead of blanking everything.
  const neverConnected = offline && !status.data;
  const showRail = railOpen && !drawerOpen && view !== "chat" && !offline;

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar
        status={status.data}
        collapsed={collapsed}
        onCollapse={() => setCollapsed(!collapsed)}
        className="hidden shrink-0 lg:flex"
      />

      {menuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            className="absolute inset-0 bg-black/50"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
          />
          <Sidebar
            status={status.data}
            collapsed={false}
            onNavigate={() => setMenuOpen(false)}
            className="relative z-10 shadow-2xl"
          />
        </div>
      )}

      <div
        className={cn(
          "flex min-w-0 flex-1 flex-col transition-[padding]",
          drawerOpen && "sm:pr-[460px]",
        )}
      >
        <TopBar
          status={status.data}
          offline={offline}
          live={live}
          chatOpen={drawerOpen}
          onChat={view !== "chat" ? () => chat.setOpen(!chat.open) : undefined}
          onMenu={() => setMenuOpen(true)}
          railOpen={railOpen}
          onRail={() => setRailOpen(!railOpen)}
        />
        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1 overflow-y-auto" id="main">
            <div className="mx-auto max-w-[1480px] px-4 pt-5 pb-24 lg:px-7 lg:pb-10">
              <BootstrapBanner status={status.data} />
              {offline && !neverConnected && <Reconnecting since={status.dataUpdatedAt} />}
              {neverConnected ? (
                <Offline />
              ) : (
                <Suspense fallback={<Loading />}>
                  <Current />
                </Suspense>
              )}
            </div>
          </main>
          {showRail && (
            <div className="hidden shrink-0 xl:block">
              <RightRail />
            </div>
          )}
        </div>
      </div>
      <MobileTabs />
      <ChatDrawer />
    </div>
  );
}

const MOBILE_TABS: Array<{ view: View; label: string; icon: typeof Activity }> = [
  { view: "today", label: "Home", icon: Activity },
  { view: "ideas", label: "Screener", icon: Telescope },
  { view: "news", label: "News", icon: Newspaper },
  { view: "portfolio", label: "Portfolio", icon: Briefcase },
  { view: "chat", label: "AI", icon: MessageSquare },
];

/** Phone navigation, app style: the five most used pages; the rest are in the menu. */
function MobileTabs() {
  const { view, go } = useNav();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
    >
      {MOBILE_TABS.map(({ view: key, label, icon: Icon }) => (
        <button
          key={key}
          onClick={() => go(key)}
          aria-current={view === key ? "page" : undefined}
          className={cn(
            "flex h-14 flex-col items-center justify-center gap-1 text-[10px] font-medium",
            view === key ? "text-primary" : "text-muted-foreground",
          )}
        >
          <Icon className="h-5 w-5" />
          {label}
        </button>
      ))}
    </nav>
  );
}

function BootstrapBanner({ status }: { status?: SystemStatus }) {
  if (!status || status.has_data) return null;
  const init = status.jobs.find((job) => job.name === "init");
  return (
    <div className="mb-4 flex items-center gap-2 rounded-2xl border border-primary/30 bg-primary-soft px-4 py-3 text-sm">
      <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
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

function Reconnecting({ since }: { since: number }) {
  return (
    <div className="mb-4 flex items-center gap-2 rounded-2xl border border-amber-line bg-amber-soft px-4 py-2.5 text-sm text-amber">
      <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
      <span>
        Reconnecting to the server. Showing data from{" "}
        {since ? new Date(since).toLocaleTimeString() : "earlier"}; it refreshes by itself when the
        server is back (a restart takes about a minute).
      </span>
    </div>
  );
}

function Offline() {
  return (
    <div className="terminal-panel mx-auto mt-10 max-w-lg p-6 text-center">
      <div className="text-base font-semibold text-bear">Backend offline</div>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        Start the Python server:{" "}
        <code className="font-mono text-primary">
          cd server && python -m uvicorn main:app --port 8000
        </code>
        , or run <code className="font-mono text-primary">.\start-nexus.ps1</code> from the project
        root.
      </p>
    </div>
  );
}
