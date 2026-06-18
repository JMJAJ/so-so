import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { lovable } from "@/integrations/lovable/index";
import { toast } from "sonner";

export const Route = createFileRoute("/auth")({
  head: () => ({ meta: [{ title: "Sign in // NEXUS Terminal" }] }),
  component: AuthPage,
});

function AuthPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) navigate({ to: "/dashboard", replace: true });
    });
  }, [navigate]);

  const handleEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === "signup") {
        const { error } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: window.location.origin },
        });
        if (error) throw error;
        toast.success("Terminal access granted.");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      }
      navigate({ to: "/dashboard", replace: true });
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogle = async () => {
    const res = await lovable.auth.signInWithOAuth("google", { redirect_uri: window.location.origin });
    if (res.error) toast.error("Google sign-in failed.");
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        <Link to="/" className="mb-6 inline-block text-[10px] uppercase tracking-[0.3em] text-muted-foreground hover:text-primary">
          ← Back to terminal
        </Link>
        <div className="terminal-panel glow-amber rounded-sm p-7">
          <div className="flex items-center justify-between border-b border-border pb-3 text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
            <span>AUTH // SECURE_CHANNEL</span>
            <span className="text-bull">● 256-BIT</span>
          </div>
          <h1 className="mt-5 font-display text-2xl font-bold">
            {mode === "signin" ? "Access terminal" : "Provision terminal"}
          </h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {mode === "signin"
              ? "Authenticate to view your AI's live positions."
              : "A demo portfolio will seed on first login."}
          </p>

          <button
            onClick={handleGoogle}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-sm border border-border bg-card px-4 py-2.5 text-xs font-bold uppercase tracking-[0.2em] hover:border-primary/60"
          >
            <svg className="h-4 w-4" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16.1 19 13 24 13c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2c-2 1.5-4.5 2.4-7.2 2.4-5.3 0-9.7-3.3-11.3-8l-6.6 5.1C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.6l6.2 5.2C41 35 44 30 44 24c0-1.2-.1-2.3-.4-3.5z"/></svg>
            Continue with Google
          </button>

          <div className="my-5 flex items-center gap-3 text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
            <div className="h-px flex-1 bg-border" />OR<div className="h-px flex-1 bg-border" />
          </div>

          <form onSubmit={handleEmail} className="space-y-3">
            <Field label="EMAIL" type="email" value={email} onChange={setEmail} required />
            <Field label="PASSWORD" type="password" value={password} onChange={setPassword} required />
            <button
              type="submit"
              disabled={loading}
              className="mt-2 w-full rounded-sm bg-primary px-4 py-2.5 text-xs font-bold uppercase tracking-[0.25em] text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
            >
              {loading ? "Connecting…" : mode === "signin" ? "Authenticate →" : "Provision →"}
            </button>
          </form>

          <button
            onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
            className="mt-5 w-full text-center text-[11px] uppercase tracking-[0.2em] text-muted-foreground hover:text-primary"
          >
            {mode === "signin" ? "No terminal? Provision one →" : "Existing terminal? Sign in →"}
          </button>
        </div>
      </div>
    </main>
  );
}

function Field({ label, type, value, onChange, required }: { label: string; type: string; value: string; onChange: (v: string) => void; required?: boolean }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-sm border border-border bg-input/40 px-3 py-2 text-sm text-foreground outline-none transition focus:border-primary focus:bg-input/70"
      />
    </label>
  );
}
