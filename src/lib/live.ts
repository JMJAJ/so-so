import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import type { NewsAlert } from "./types";

/** A change notification from /api/live (see server/nexus/live.py). */
interface LiveEvent {
  seq: number;
  topic: string;
  at?: string;
  name?: string;
  status?: string;
  alert?: NewsAlert;
}

/** Which cached queries each kind of change makes stale (by query-key prefix). */
const TOPIC_KEYS: Record<string, string[]> = {
  quotes: ["portfolio", "dashboard", "asset", "intraday", "universe", "briefs", "quotes"],
  portfolio: ["portfolio", "dashboard", "status", "track-record", "accounts", "portfolio-sim"],
  recommendations: ["dashboard", "portfolio", "track-record", "briefs", "skills", "simulate"],
  news: ["news", "events", "dashboard", "status"],
  alert: ["alerts", "news"],
  settings: ["settings", "status", "notifications"],
  watchlist: ["watchlist", "quotes"],
  logs: ["logs"],
  progress: ["status", "jobs"],
};

/** Extra refreshes when a job finishes, by job name. "*" refreshes everything. */
const JOB_KEYS: Record<string, string[]> = {
  init: ["*"],
  daily: ["*"],
  research: ["*"],
  analyst: ["dashboard", "portfolio", "track-record", "runs", "forecasts", "briefs"],
  news: ["news", "events", "dashboard"],
  news_backfill: ["news", "events", "dashboard"],
  monitor: ["portfolio", "dashboard"],
  gdelt_backfill: ["events"],
  sim_check: ["sim-check", "simulate", "portfolio-sim"],
  watch: ["notifications"],
};

const DEBOUNCE_MS = 400;
const TOAST_WINDOW_MS = 30_000;
const TOASTS_PER_WINDOW = 3;
const recentToasts: number[] = [];

function watched(): string[] {
  try {
    return JSON.parse(window.localStorage.getItem("nexus.watchlist") ?? "[]") as string[];
  } catch {
    return [];
  }
}

/** Interrupt only for what matters: top-level stories, or level-2 news on a watched asset.
 * At most a few per half minute, so a busy news hour doesn't bury the screen. */
function announce(alert: NewsAlert): void {
  const mine = watched();
  const relevant =
    alert.level >= 3 || (alert.level >= 2 && alert.tickers.some((t) => mine.includes(t)));
  if (!relevant) return;
  const now = Date.now();
  while (recentToasts.length && now - recentToasts[0] > TOAST_WINDOW_MS) recentToasts.shift();
  if (recentToasts.length >= TOASTS_PER_WINDOW) return;
  recentToasts.push(now);
  const moves = Object.entries(alert.moves ?? {})
    .filter(([, m]) => m.change_pct != null)
    .map(
      ([id, m]) =>
        `${id.split(":")[1]?.toUpperCase()} ${m.change_pct! >= 0 ? "+" : ""}${m.change_pct!.toFixed(1)}% today`,
    );
  toast(alert.title, {
    description: [alert.source, ...moves].filter(Boolean).join(" · "),
    duration: 12_000,
    action: alert.url
      ? { label: "Read", onClick: () => window.open(alert.url!, "_blank", "noopener") }
      : undefined,
  });
}

function keysFor(event: LiveEvent): string[] {
  if (event.topic === "job") {
    const base = ["status", "jobs", "runs", "logs"];
    return event.status === "running" ? base : [...base, ...(JOB_KEYS[event.name ?? ""] ?? [])];
  }
  return TOPIC_KEYS[event.topic] ?? [];
}

function scheduler(client: QueryClient) {
  const pending = new Set<string>();
  let timer: number | undefined;
  return (keys: string[]) => {
    keys.forEach((key) => pending.add(key));
    if (timer !== undefined) return;
    timer = window.setTimeout(() => {
      timer = undefined;
      if (pending.has("*")) {
        // Everything except the login check, which only changes on login/logout.
        void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "auth" });
      } else {
        for (const key of pending) void client.invalidateQueries({ queryKey: [key] });
      }
      pending.clear();
    }, DEBOUNCE_MS);
  };
}

export type LiveState = { connected: boolean; lastEventAt: number | null };

/** Subscribe to server change notifications and refetch whatever they touch. Mount once. */
export function useLiveUpdates(): LiveState {
  const client = useQueryClient();
  const [state, setState] = useState<LiveState>({ connected: false, lastEventAt: null });

  useEffect(() => {
    const invalidate = scheduler(client);
    const source = new EventSource("/api/live");
    source.onopen = () => {
      setState((s) => ({ ...s, connected: true }));
      // Anything may have changed while we were disconnected.
      invalidate(["*"]);
    };
    source.onerror = () => setState((s) => ({ ...s, connected: false }));
    source.onmessage = (message) => {
      const event = JSON.parse(message.data as string) as LiveEvent;
      if (event.topic === "hello") return;
      if (event.topic === "alert" && event.alert) announce(event.alert);
      setState({ connected: true, lastEventAt: Date.now() });
      invalidate(keysFor(event));
    };
    return () => source.close();
  }, [client]);

  return state;
}
