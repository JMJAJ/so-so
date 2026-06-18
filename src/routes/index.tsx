import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { Activity, TrendingUp, Brain, ShieldCheck } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "NEXUS // AI Trading Terminal" },
      { name: "description", content: "Autonomous AI trading terminal for forex and crypto. Live positions, P&L, and decision logs in one place." },
      { property: "og:title", content: "NEXUS // AI Trading Terminal" },
      { property: "og:description", content: "Autonomous AI trading terminal — live positions, P&L and AI decisions." },
    ],
  }),
  component: Landing,
});

const tickerData = [
  { p: "EUR/USD", v: "1.0871", d: 0.43 },
  { p: "GBP/JPY", v: "191.20", d: -0.65 },
  { p: "USD/CHF", v: "0.8795", d: -0.19 },
  { p: "AUD/USD", v: "0.6648", d: 0.54 },
  { p: "USD/JPY", v: "155.10", d: -0.70 },
  { p: "BTC/USD", v: "68950", d: 2.60 },
  { p: "ETH/USD", v: "3512", d: 2.69 },
  { p: "XAU/USD", v: "2358.80", d: 0.69 },
  { p: "NZD/USD", v: "0.6045", d: 0.12 },
  { p: "USD/CAD", v: "1.3640", d: -0.21 },
];

function Landing() {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) navigate({ to: "/dashboard", replace: true });
      else setChecking(false);
    });
  }, [navigate]);

  if (checking) return <BootScreen />;

  return (
    <main className="relative min-h-screen overflow-hidden">
      {/* Top status bar */}
      <div className="border-b border-border bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-2 text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-bull" />
            <span>LIVE FEED</span>
          </div>
          <div className="hidden md:block">NEXUS TERMINAL v4.2.1</div>
          <div>{new Date().toUTCString().slice(5, 22)} UTC</div>
        </div>
      </div>

      {/* Ticker */}
      <div className="overflow-hidden border-b border-border bg-card/60 py-2">
        <div className="ticker-scroll flex w-max gap-8 whitespace-nowrap text-xs">
          {[...tickerData, ...tickerData].map((t, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-muted-foreground">{t.p}</span>
              <span className="text-foreground">{t.v}</span>
              <span className={t.d >= 0 ? "text-bull" : "text-bear"}>
                {t.d >= 0 ? "▲" : "▼"} {Math.abs(t.d).toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Hero */}
      <section className="mx-auto grid max-w-7xl gap-10 px-4 py-16 md:grid-cols-[1.2fr_1fr] md:py-24">
        <div>
          <div className="inline-flex items-center gap-2 border border-border bg-card px-3 py-1 text-[10px] uppercase tracking-[0.25em] text-primary">
            <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-primary" />
            Autonomous · Always-on
          </div>
          <h1 className="mt-6 font-display text-5xl font-bold leading-[1.05] tracking-tight md:text-7xl">
            An AI that <span className="text-primary">trades</span><br />
            while you <span className="text-bull">sleep</span>.
          </h1>
          <p className="mt-6 max-w-xl text-sm leading-relaxed text-muted-foreground md:text-base">
            NEXUS scans forex and crypto markets 24/7, opens and closes positions on its own,
            and shows you every move — currency by currency — on one terminal.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              to="/auth"
              className="glow-amber rounded-sm bg-primary px-6 py-3 text-xs font-bold uppercase tracking-[0.2em] text-primary-foreground transition hover:bg-primary/90"
            >
              Open terminal →
            </Link>
            <a
              href="#capabilities"
              className="rounded-sm border border-border bg-card px-6 py-3 text-xs font-bold uppercase tracking-[0.2em] text-foreground hover:border-primary/60"
            >
              View capabilities
            </a>
          </div>

          <div className="mt-12 grid grid-cols-3 gap-4 border-t border-border pt-6 text-xs">
            <Stat label="Pairs tracked" value="187" />
            <Stat label="Avg latency" value="42ms" />
            <Stat label="Uptime" value="99.98%" />
          </div>
        </div>

        {/* Terminal preview card */}
        <div className="terminal-panel glow-amber relative overflow-hidden rounded-sm p-4">
          <div className="flex items-center justify-between border-b border-border pb-2 text-[10px] uppercase tracking-widest text-muted-foreground">
            <span>POSITIONS // LIVE</span>
            <span className="text-bull">● ONLINE</span>
          </div>
          <div className="mt-3 space-y-1.5 text-xs">
            {tickerData.slice(0, 7).map((t) => (
              <div key={t.p} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-border/60 py-1.5">
                <div className="flex items-center gap-2">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                  <span className="font-bold">{t.p}</span>
                </div>
                <span className="tabular-nums text-muted-foreground">{t.v}</span>
                <span className={`tabular-nums font-bold ${t.d >= 0 ? "text-bull" : "text-bear"}`}>
                  {t.d >= 0 ? "+" : ""}{t.d.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3 border-t border-border pt-2 text-[10px] uppercase tracking-widest text-muted-foreground">
            <span className="text-primary">AI</span> &nbsp;›&nbsp; Rebalancing JPY exposure ··· -12%
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section id="capabilities" className="border-t border-border bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-16">
          <div className="text-[10px] uppercase tracking-[0.3em] text-primary">// CAPABILITIES</div>
          <h2 className="mt-2 font-display text-3xl font-bold md:text-4xl">Built like a trading desk.</h2>
          <div className="mt-10 grid gap-4 md:grid-cols-4">
            <Cap icon={Activity} title="Live positions" body="Every open trade with entry, mark, and P&L in real time." />
            <Cap icon={TrendingUp} title="Allocation map" body="See exactly which currencies and assets the AI is holding." />
            <Cap icon={Brain}    title="Decision log" body="Every signal, open, hold, and close — with the AI's reasoning." />
            <Cap icon={ShieldCheck} title="Risk guardrails" body="Stops, spread filters, and exposure caps enforced server-side." />
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-6 text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
          <span>© NEXUS TERMINAL</span>
          <span>Not financial advice · Demo environment</span>
        </div>
      </footer>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-display text-2xl font-bold text-primary">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{label}</div>
    </div>
  );
}

function Cap({ icon: Icon, title, body }: { icon: typeof Activity; title: string; body: string }) {
  return (
    <div className="terminal-panel rounded-sm p-5">
      <Icon className="h-5 w-5 text-primary" strokeWidth={1.5} />
      <div className="mt-4 font-display text-base font-bold">{title}</div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

function BootScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-xs uppercase tracking-[0.3em] text-muted-foreground">
        <span className="pulse-dot mr-2 inline-block h-1.5 w-1.5 rounded-full bg-primary" />
        Booting terminal…
      </div>
    </div>
  );
}
