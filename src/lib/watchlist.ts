import { useCallback, useEffect, useState } from "react";

/** The viewer's watchlist: instrument ids kept in this browser (a per-viewer convenience).
 * Held positions are shown alongside it by the watchlist panel, so they need not be added. */
const STORAGE_KEY = "nexus.watchlist";
const DEFAULT = ["etf:spy", "etf:qqq", "stock:nvda", "stock:aapl", "crypto:btc", "commodity:gold"];

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === "string")
      : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

function write(ids: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch {
    // Storage blocked: the change lasts for this visit only.
  }
  window.dispatchEvent(new CustomEvent("nexus-watchlist"));
}

export function useWatchlist() {
  const [ids, setIds] = useState<string[]>(read);
  useEffect(() => {
    const onChange = () => setIds(read());
    window.addEventListener("nexus-watchlist", onChange);
    return () => window.removeEventListener("nexus-watchlist", onChange);
  }, []);
  const toggle = useCallback((id: string) => {
    const current = read();
    write(current.includes(id) ? current.filter((v) => v !== id) : [...current, id]);
  }, []);
  return { ids, has: (id: string) => ids.includes(id), toggle };
}
