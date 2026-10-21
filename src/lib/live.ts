import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

/** A change notification from /api/live (see server/nexus/live.py). */
interface LiveEvent {
  seq: number;
  topic: string;
  at?: string;
  name?: string;
  status?: string;
}

/** Which cached queries each kind of change makes stale (by query-key prefix). */
const TOPIC_KEYS: Record<string, string[]> = {
  quotes: ["portfolio", "dashboard", "asset", "intraday", "universe", "briefs"],
  portfolio: ["portfolio", "dashboard", "status", "track-record"],
  recommendations: ["dashboard", "portfolio", "track-record", "briefs", "skills"],
  news: ["news", "events", "dashboard", "status"],
  settings: ["settings", "status"],
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
};

const DEBOUNCE_MS = 400;

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
      setState({ connected: true, lastEventAt: Date.now() });
      invalidate(keysFor(event));
    };
    return () => source.close();
  }, [client]);

  return state;
}
