import { useQuery } from "@tanstack/react-query";
import { Loader2, Menu, MessageSquare, PanelRight, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { MarketChip } from "@/features/markets/MarketChip";
import { api } from "@/lib/api";
import { ago, price } from "@/lib/format";
import type { LiveState } from "@/lib/live";
import { useNav, type View } from "@/lib/nav";
import type { SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { AccountSwitcher } from "./AccountSwitcher";
import { CORE_TAPE, useWatchQuotes } from "./RightRail";
import { VIEWS } from "./views";

export function TopBar({
  status,
  offline,
  live,
  chatOpen,
  onChat,
  onMenu,
  railOpen,
  onRail,
}: {
  status?: SystemStatus;
  offline: boolean;
  live: LiveState;
  chatOpen: boolean;
  onChat?: () => void;
  onMenu: () => void;
  railOpen: boolean;
  onRail: () => void;
}) {
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearching((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/90 backdrop-blur">
      <div className="flex h-14 items-center gap-2 px-3 lg:px-5">
        <button className="icon-button lg:hidden" onClick={onMenu} aria-label="Open menu">
          <Menu className="h-4 w-4" />
        </button>
        <button
          onClick={() => setSearching(true)}
          className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-full border border-border bg-raised px-3.5 text-left text-[13px] text-muted-foreground transition-colors hover:border-strong sm:min-w-[240px] sm:max-w-[360px]"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span className="truncate">Search symbols, pages…</span>
          <kbd className="ml-auto hidden rounded-md border border-border px-1.5 font-mono text-[10px] sm:inline">
            Ctrl K
          </kbd>
        </button>
        <div className="hidden min-w-0 flex-1 2xl:block">
          <JobLine status={status} />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {status?.analyst_running && (
            <span className="hidden items-center gap-1.5 text-xs font-medium text-primary md:flex">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Analyst researching
            </span>
          )}
          <div className="hidden md:block">
            <AccountSwitcher />
          </div>
          {!offline && <MarketChip marketId="nyse" className="hidden shrink-0 2xl:inline-flex" />}
          <LiveDot live={live} offline={offline} />
          <button
            className={cn("icon-button hidden xl:inline-flex", railOpen && "!text-foreground")}
            onClick={onRail}
            aria-label={railOpen ? "Hide watchlist" : "Show watchlist"}
            title={railOpen ? "Hide watchlist and live wire" : "Show watchlist and live wire"}
          >
            <PanelRight className="h-4 w-4" />
          </button>
          {onChat && (
            <button
              className={cn("primary-button", chatOpen && "!bg-primary-strong")}
              onClick={onChat}
            >
              <MessageSquare className="h-4 w-4" />
              <span className="hidden sm:inline">Ask AI</span>
            </button>
          )}
        </div>
      </div>
      {!offline && <TickerTape />}
      <SearchDialog open={searching} onOpenChange={setSearching} />
    </header>
  );
}

function JobLine({ status }: { status?: SystemStatus }) {
  const running = status?.jobs.filter((job) => job.running && job.name !== "wire") ?? [];
  if (running.length) {
    return (
      <div className="truncate text-xs text-muted-foreground">
        {running.map((job) => `${job.name}: ${job.progress ?? "running"}`).join(" · ")}
      </div>
    );
  }
  const news = status?.jobs.find((job) => job.name === "news");
  return news?.last_finished ? (
    <div className="truncate text-xs text-muted-foreground">
      Wire polling about every minute · headlines classified {ago(news.last_finished)}
    </div>
  ) : null;
}

function LiveDot({ live, offline }: { live: LiveState; offline: boolean }) {
  const on = live.connected && !offline;
  const last = live.lastEventAt
    ? ` (last update ${new Date(live.lastEventAt).toLocaleTimeString()})`
    : "";
  return (
    <span
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3 text-xs font-medium",
        on ? "border-bull-line bg-bull-soft text-bull" : "border-border text-muted-foreground",
      )}
      title={
        on
          ? `Live: pages refresh as soon as data changes${last}`
          : offline
            ? "Backend offline"
            : "Reconnecting to live updates; pages still refresh on a timer"
      }
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", on ? "pulse-dot bg-bull" : "bg-bear")} />
      <span className="hidden sm:inline">{on ? "Live" : offline ? "Offline" : "Reconnecting"}</span>
    </span>
  );
}

/** Scrolling quotes for the watchlist, like a trading floor ticker. */
function TickerTape() {
  const { rows } = useWatchQuotes(CORE_TAPE);
  const { openAsset } = useNav();
  const items = useMemo(() => rows.filter((item) => item.quote?.price != null), [rows]);
  if (items.length === 0) return null;
  const row = (suffix: string) =>
    items.map((item) => {
      const change = item.quote?.change_pct;
      return (
        <button
          key={item.id + suffix}
          data-asset={item.id}
          onClick={() => openAsset(item.id)}
          className="flex shrink-0 items-center gap-2 px-4 text-xs hover:text-foreground"
        >
          <span className="font-semibold text-foreground">{item.symbol}</span>
          <span className="font-mono text-muted-foreground">{price(item.quote?.price)}</span>
          <span
            className={cn(
              "font-mono",
              change == null ? "text-muted-foreground" : change >= 0 ? "text-bull" : "text-bear",
            )}
          >
            {change == null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
          </span>
        </button>
      );
    });
  return (
    <div className="group relative h-8 overflow-hidden border-t border-border">
      <div className="ticker-scroll flex h-full w-max items-center group-hover:[animation-play-state:paused]">
        {row("a")}
        {row("b")}
      </div>
    </div>
  );
}

function SearchDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { go, openAsset } = useNav();
  const universe = useQuery({
    queryKey: ["universe"],
    queryFn: api.universe,
    staleTime: 30_000,
    enabled: open,
  });
  const pick = (action: () => void) => {
    onOpenChange(false);
    action();
  };
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Symbol, company or page…" />
      <CommandList className="max-h-[420px]">
        <CommandEmpty>{universe.isLoading ? "Loading…" : "No match"}</CommandEmpty>
        <CommandGroup heading="Symbols">
          {(universe.data ?? []).map((item) => (
            <CommandItem
              key={item.id}
              value={`${item.symbol} ${item.name} ${item.asset_class}`}
              data-asset={item.id}
              onSelect={() => pick(() => openAsset(item.id))}
              className="flex items-center gap-3"
            >
              <span className="w-16 shrink-0 font-semibold">{item.symbol}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.name}</span>
              <span className="text-[11px] text-muted-foreground">{item.asset_class}</span>
              <span className="w-20 text-right font-mono text-xs">{price(item.quote?.price)}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Pages">
          {(Object.keys(VIEWS) as View[])
            .filter((key) => key !== "asset")
            .map((key) => {
              const Icon = VIEWS[key].icon;
              return (
                <CommandItem
                  key={key}
                  value={VIEWS[key].label}
                  onSelect={() => pick(() => go(key))}
                >
                  <Icon className="mr-2 h-4 w-4" />
                  {VIEWS[key].label}
                </CommandItem>
              );
            })}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
