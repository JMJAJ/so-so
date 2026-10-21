import type { QueryClient, QueryKey } from "@tanstack/react-query";
import {
  Activity,
  Briefcase,
  FileText,
  Globe,
  LineChart,
  MessageSquare,
  Newspaper,
  Settings,
  Target,
  Telescope,
} from "lucide-react";
import { lazy, type ComponentType } from "react";

import { api } from "@/lib/api";
import type { View } from "@/lib/nav";

type Module = { default: ComponentType };
type Warm = Array<[QueryKey, () => Promise<unknown>]>;

interface ViewDef {
  label: string;
  icon: ComponentType<{ className?: string }>;
  load: () => Promise<Module>;
  /** The queries the view runs on open, with the same keys and defaults, so they can be warmed. */
  data: Warm;
}

const DEFS: Record<View, ViewDef> = {
  today: {
    label: "Today",
    icon: Activity,
    load: () => import("@/features/today/TodayView"),
    data: [[["dashboard"], api.dashboard]],
  },
  chat: {
    label: "AI chat",
    icon: MessageSquare,
    load: () => import("@/features/chat/ChatView"),
    data: [[["conversations"], api.conversations]],
  },
  briefs: {
    label: "Market briefs",
    icon: FileText,
    load: () => import("@/features/briefs/BriefsView"),
    data: [[["briefs"], api.briefs]],
  },
  ideas: {
    label: "Screener",
    icon: Telescope,
    load: () => import("@/features/ideas/IdeasView"),
    data: [
      [["forecasts"], () => api.forecasts()],
      [["models"], api.models],
    ],
  },
  asset: {
    label: "Asset",
    icon: LineChart,
    load: () => import("@/features/asset/AssetView"),
    data: [],
  },
  news: {
    label: "News & events",
    icon: Newspaper,
    load: () => import("@/features/news/NewsView"),
    data: [
      [["news", 3, 1, ""], () => api.news({ days: 3, min_magnitude: 1 })],
      [["news-categories"], api.newsCategories],
    ],
  },
  portfolio: {
    label: "Portfolio",
    icon: Briefcase,
    load: () => import("@/features/portfolio/PortfolioView"),
    data: [[["portfolio"], api.portfolio]],
  },
  markets: {
    label: "Market hours",
    icon: Globe,
    load: () => import("@/features/markets/MarketsView"),
    data: [[["markets"], api.markets]],
  },
  record: {
    label: "Track record",
    icon: Target,
    load: () => import("@/features/record/TrackRecordView"),
    data: [
      [["track-record"], api.trackRecord],
      [["models"], api.models],
      [["skills"], api.skills],
    ],
  },
  settings: {
    label: "Settings",
    icon: Settings,
    load: () => import("@/features/settings/SettingsView"),
    data: [
      [["settings"], api.settings],
      [["jobs"], api.jobs],
    ],
  },
};

export const VIEWS = {} as Record<View, ViewDef & { component: ComponentType }>;
for (const key of Object.keys(DEFS) as View[]) {
  VIEWS[key] = { ...DEFS[key], component: lazy(DEFS[key].load) };
}

const loaded = new Set<View>();

/** Load a view's code and data before it is opened (hover, or idle time after startup).
 * Code loads once; data is fetched only when the cached copy is missing or stale. */
export async function warmView(client: QueryClient, view: View): Promise<void> {
  const def = DEFS[view];
  const code = loaded.has(view)
    ? Promise.resolve()
    : def.load().then(
        () => void loaded.add(view),
        () => undefined,
      );
  await Promise.all([
    code,
    ...def.data.map(([queryKey, queryFn]) =>
      client.prefetchQuery({ queryKey, queryFn, staleTime: 60_000 }),
    ),
  ]);
}

/** Warm every view one after another, so the backend serves them without a burst. */
export async function warmAll(client: QueryClient, current: View): Promise<void> {
  for (const view of Object.keys(DEFS) as View[]) {
    if (view !== current) await warmView(client, view);
  }
}
