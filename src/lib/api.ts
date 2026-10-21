import type {
  AssetDetail,
  ChatEvent,
  ChatMessage,
  Dashboard,
  EventStudyDetail,
  Forecast,
  Instrument,
  JobStatus,
  MarketEvent,
  MarketsOverview,
  ModelSummary,
  NewsItem,
  Portfolio,
  Recommendation,
  Run,
  Settings,
  SystemStatus,
  TrackRecord,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") message = payload.detail;
      else if (payload.detail) message = JSON.stringify(payload.detail);
    } catch {
      // Non-JSON error body: keep the status text.
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

const qs = (params: Record<string, string | number | undefined | null>) => {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== "",
  );
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
};

export const api = {
  status: () => fetchJson<SystemStatus>("/status"),
  dashboard: () => fetchJson<Dashboard>("/dashboard"),
  universe: () => fetchJson<Instrument[]>("/universe"),
  markets: () => fetchJson<MarketsOverview>("/markets"),
  forecasts: (assetClass?: string) =>
    fetchJson<Forecast[]>(`/forecasts${qs({ asset_class: assetClass })}`),
  asset: (id: string, years = 2) =>
    fetchJson<AssetDetail>(`/assets/${encodeURIComponent(id)}${qs({ years })}`),
  eventStudy: (id: string, eventType: string) =>
    fetchJson<EventStudyDetail>(
      `/assets/${encodeURIComponent(id)}/event-study${qs({ event_type: eventType })}`,
    ),
  events: (days = 30, eventType?: string) =>
    fetchJson<MarketEvent[]>(`/events${qs({ days, event_type: eventType })}`),
  eventTypes: () =>
    fetchJson<
      Array<{
        type: string;
        label: string;
        scope: string;
        n: number;
        first: string | null;
        last: string | null;
        most_affected: MarketEvent["most_affected"];
      }>
    >("/event-types"),
  news: (params: {
    instrument?: string;
    category?: string;
    days?: number;
    min_magnitude?: number;
  }) => fetchJson<NewsItem[]>(`/news${qs(params)}`),
  newsCategories: () =>
    fetchJson<Array<{ category: string; maps_to: string[] }>>("/news-categories"),
  recommendations: (status?: string) =>
    fetchJson<Recommendation[]>(`/recommendations${qs({ status })}`),
  recommendation: (id: string) => fetchJson<Recommendation>(`/recommendations/${id}`),
  cancelRecommendation: (id: string) =>
    fetchJson<Recommendation>(`/recommendations/${id}/cancel`, send("POST")),
  createRecommendation: (body: Record<string, unknown>) =>
    fetchJson<Recommendation>("/recommendations", send("POST", body)),
  portfolio: () => fetchJson<Portfolio>("/portfolio"),
  closePosition: (id: string) =>
    fetchJson<Record<string, unknown>>(`/positions/${id}/close`, send("POST")),
  trackRecord: () => fetchJson<TrackRecord>("/track-record"),
  models: () => fetchJson<ModelSummary[]>("/models"),
  runAnalyst: (focus?: string) =>
    fetchJson<{ started: boolean }>("/analyst/run", send("POST", { focus: focus || null })),
  runs: () => fetchJson<Run[]>("/runs"),
  run: (id: string) =>
    fetchJson<
      Run & { transcript: Array<Record<string, unknown>>; recommendations: Recommendation[] }
    >(`/runs/${id}`),
  jobs: () => fetchJson<JobStatus[]>("/jobs"),
  runJob: (name: string) => fetchJson<{ started: string }>(`/jobs/${name}/run`, send("POST")),
  settings: () => fetchJson<Settings>("/settings"),
  saveSettings: (values: Record<string, string>, secrets: Record<string, string>) =>
    fetchJson<Settings>("/settings", send("PUT", { values, secrets })),
  testLlm: () =>
    fetchJson<{
      ok: boolean;
      reply?: string;
      error?: string;
      provider?: string;
      model?: string;
      latency_ms: number;
    }>("/llm/test", send("POST")),
  conversations: () => fetchJson<Array<{ id: string; title: string; updated_at: string }>>("/chat"),
  conversation: (id: string) =>
    fetchJson<{
      id: string;
      messages: ChatMessage[];
    }>(`/chat/${id}`),
  deleteConversation: (id: string) =>
    fetchJson<{ deleted: boolean }>(`/chat/${id}`, send("DELETE")),
  logs: () =>
    fetchJson<
      Array<{ id: number; created_at: string; level: string; kind: string; message: string }>
    >("/logs"),
};

/** POST a chat message and stream server-sent events back. */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    ...send("POST", { message, conversation_id: conversationId }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as ChatEvent);
          } catch {
            // Ignore a malformed frame rather than abort the stream.
          }
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
