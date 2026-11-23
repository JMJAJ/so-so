import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type View =
  | "today"
  | "chat"
  | "briefs"
  | "ideas"
  | "asset"
  | "news"
  | "portfolio"
  | "markets"
  | "record"
  | "settings";
export const VIEWS: View[] = [
  "today",
  "chat",
  "briefs",
  "ideas",
  "asset",
  "news",
  "portfolio",
  "markets",
  "record",
  "settings",
];

interface NavState {
  view: View;
  params: Record<string, string>;
}

interface NavContextValue extends NavState {
  go: (view: View, params?: Record<string, string>) => void;
  openAsset: (instrumentId: string) => void;
}

const NavContext = createContext<NavContextValue | null>(null);

function readLocation(): NavState {
  const search = new URLSearchParams(window.location.search);
  const view = (search.get("v") as View) || "today";
  const params: Record<string, string> = {};
  search.forEach((value, key) => {
    if (key !== "v") params[key] = value;
  });
  return { view: VIEWS.includes(view) ? view : "today", params };
}

export function NavProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<NavState>(readLocation);

  useEffect(() => {
    const onPop = () => setState(readLocation());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((view: View, params: Record<string, string> = {}) => {
    const search = new URLSearchParams({ v: view, ...params });
    window.history.pushState(null, "", `/?${search}`);
    setState({ view, params });
    document.getElementById("main")?.scrollTo({ top: 0 });
  }, []);

  const openAsset = useCallback((instrumentId: string) => go("asset", { id: instrumentId }), [go]);

  return <NavContext.Provider value={{ ...state, go, openAsset }}>{children}</NavContext.Provider>;
}

export function useNav(): NavContextValue {
  const value = useContext(NavContext);
  if (!value) throw new Error("useNav must be used inside NavProvider");
  return value;
}
