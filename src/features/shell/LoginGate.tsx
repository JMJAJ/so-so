import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { api } from "@/lib/api";

/** Shows a password screen when the backend requires login (NEXUS_PASSWORD is set). */
export function LoginGate({ children }: { children: ReactNode }) {
  const status = useQuery({
    queryKey: ["auth"],
    queryFn: api.authStatus,
    retry: false,
    staleTime: Infinity,
  });
  // Spinner only before the first answer: refetches must never unmount the app.
  if (status.data === undefined && status.error === null) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-bull" />
      </div>
    );
  }
  // Backend unreachable: let the shell show its own "backend offline" state.
  if (status.error || !status.data?.required || status.data.authenticated) return <>{children}</>;
  return <LoginScreen />;
}

function LoginScreen() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="terminal-panel w-full max-w-sm space-y-4 p-6">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-foreground" />
          <span className="font-display text-sm font-bold ">NEXUS</span>
        </div>
        <label className="block space-y-1.5">
          <span className="text-xs font-bold text-muted-foreground">Password</span>
          <input
            className="terminal-input w-full"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="text-[11px] text-bear">{error}</p>}
        <button className="primary-button w-full" disabled={busy || !password}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
