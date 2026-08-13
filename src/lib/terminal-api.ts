import type { BootstrapData, OrderPreview } from "./terminal-types";

const API = "/api";

interface ApiErrorPayload {
  detail?: string | { code?: string; message?: string };
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, signal });
  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      // The status text remains a useful fallback for non-JSON failures.
    }
    const detail = payload.detail;
    const code = typeof detail === "object" ? (detail.code ?? "request_failed") : "request_failed";
    const message =
      typeof detail === "object"
        ? (detail.message ?? response.statusText)
        : (detail ?? response.statusText);
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export const jsonRequest = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const terminalApi = {
  bootstrap: (signal?: AbortSignal) => api<BootstrapData>("/bootstrap", undefined, signal),
  previewOrder: (body: unknown, signal?: AbortSignal) =>
    api<OrderPreview>("/orders/preview", jsonRequest("POST", body), signal),
  createOrder: (body: unknown) =>
    api<Record<string, unknown>>("/orders", jsonRequest("POST", body)),
  closePosition: (id: string) =>
    api<Record<string, unknown>>(`/positions/${id}/close`, jsonRequest("POST")),
  protectPosition: (id: string, body: unknown) =>
    api<Record<string, unknown>>(`/positions/${id}/protection`, jsonRequest("PATCH", body)),
  approveProposal: (id: string) =>
    api<Record<string, unknown>>(`/proposals/${id}/approve`, jsonRequest("POST")),
  rejectProposal: (id: string, reason: string) =>
    api<Record<string, unknown>>(`/proposals/${id}/reject`, jsonRequest("POST", { reason })),
  updateAgent: (body: unknown) =>
    api<Record<string, unknown>>("/agent/config", jsonRequest("PUT", body)),
  setKillSwitch: (enabled: boolean) =>
    api<Record<string, unknown>>("/agent/kill-switch", jsonRequest("POST", { enabled })),
  startAgent: () => api<Record<string, unknown>>("/agent/start", jsonRequest("POST")),
  stopAgent: () => api<Record<string, unknown>>("/agent/stop", jsonRequest("POST")),
  triggerAgent: () => api<Record<string, unknown>>("/agent/trigger", jsonRequest("POST")),
  updateConfig: (body: unknown) =>
    api<Record<string, unknown>>("/config", jsonRequest("PUT", body)),
  updateLlm: (body: unknown) =>
    api<Record<string, unknown>>("/llm/config", jsonRequest("PUT", body)),
  testLlm: () => api<{ ok: boolean; latency_ms: number }>("/llm/test", jsonRequest("POST")),
};
