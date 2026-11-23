import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

import { api } from "./api";

/** The watchlist lives on the server, so the phone and the desktop show the same list and
 * push alerts (nexus/notify.py) watch it. Held positions are shown alongside it by the
 * watchlist panel, so they need not be added. */
const LEGACY_KEY = "nexus.watchlist";
const MIGRATED_KEY = "nexus.watchlist.migrated";

/** Lists starred before the watchlist moved to the server are merged into it once. */
function takeLegacy(): string[] {
  try {
    if (window.localStorage.getItem(MIGRATED_KEY)) return [];
    window.localStorage.setItem(MIGRATED_KEY, "1");
    const parsed: unknown = JSON.parse(window.localStorage.getItem(LEGACY_KEY) ?? "null");
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function useWatchlist() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist, staleTime: 60_000 });
  const ids = query.data?.ids ?? [];

  const save = useMutation({
    mutationFn: api.saveWatchlist,
    onMutate: (next: string[]) => {
      const previous = client.getQueryData<{ ids: string[] }>(["watchlist"]);
      client.setQueryData(["watchlist"], { ids: next });
      return { previous };
    },
    onError: (_error, _next, context) => {
      if (context?.previous) client.setQueryData(["watchlist"], context.previous);
    },
    onSuccess: (data) => client.setQueryData(["watchlist"], data),
  });

  const { mutate } = save;
  useEffect(() => {
    if (!query.data) return;
    const legacy = takeLegacy().filter((id) => !query.data.ids.includes(id));
    if (legacy.length) mutate([...query.data.ids, ...legacy]);
  }, [query.data, mutate]);

  const toggle = useCallback(
    (id: string) => {
      const current = client.getQueryData<{ ids: string[] }>(["watchlist"])?.ids ?? [];
      mutate(current.includes(id) ? current.filter((v) => v !== id) : [...current, id]);
    },
    [client, mutate],
  );
  return { ids, has: (id: string) => ids.includes(id), toggle };
}
