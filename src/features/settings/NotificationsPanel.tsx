import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Dices, Send } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge, ErrorNote, Loading, Panel, Segmented } from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

const KEYS = [
  "ntfy_server",
  "notify_news_level",
  "notify_move_sigma",
  "notify_calls",
  "notify_exits",
  "notify_auto_analyst",
  "public_url",
] as const;

function randomTopic(): string {
  const bytes = new Uint8Array(9);
  crypto.getRandomValues(bytes);
  return `nexus-${Array.from(bytes, (b) => b.toString(36).padStart(2, "0"))
    .join("")
    .slice(0, 14)}`;
}

/** Phone alerts through ntfy: breaking news, abnormal moves, AI buy/sell calls, stops hit. */
export function NotificationsPanel() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const log = useQuery({
    queryKey: ["notifications"],
    queryFn: api.notifications,
    refetchInterval: 60_000,
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const [topic, setTopic] = useState("");

  useEffect(() => {
    if (settings.data) {
      setValues(Object.fromEntries(KEYS.map((key) => [key, settings.data.values[key] ?? ""])));
    }
  }, [settings.data]);
  useEffect(() => {
    if (log.data?.topic) setTopic(log.data.topic);
  }, [log.data?.topic]);

  const save = useMutation({
    mutationFn: () => api.saveSettings(values, topic.trim() ? { ntfy_topic: topic.trim() } : {}),
    onSuccess: () => {
      toast.success("Notification settings saved");
      void client.invalidateQueries({ queryKey: ["settings"] });
      void client.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const test = useMutation({
    mutationFn: async () => {
      await api.saveSettings(values, topic.trim() ? { ntfy_topic: topic.trim() } : {});
      return api.testNotification();
    },
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: ["notifications"] });
      if (result.ok) toast.success("Sent. Check your phone.");
      else toast.error(result.error ?? "ntfy did not accept the message");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (settings.isLoading || log.isLoading) return <Loading />;
  if (settings.error) return <ErrorNote error={settings.error} />;
  const set = (key: string, value: string) =>
    setValues((current) => ({ ...current, [key]: value }));
  const on = (key: string) => (values[key] ?? "").toLowerCase() === "true";
  const server = (values.ntfy_server || "https://ntfy.sh").replace(/\/$/, "");
  const subscribeUrl = topic.trim() ? `${server}/${topic.trim()}` : null;
  const envTopic = settings.data?.secrets.ntfy_topic?.source === "env";

  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <BellRing className="h-4 w-4 text-primary" /> Phone alerts
          {log.data?.enabled ? <Badge tone="bull">on</Badge> : <Badge>off</Badge>}
        </span>
      }
      subtitle="Push notifications through ntfy: top breaking news, unusual moves on what you watch or hold, every AI buy/sell call, and stops or targets hit. Big events also start a focused AI research run."
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <ol className="space-y-1.5 text-[13px] leading-relaxed text-muted-foreground">
            <li>
              1. Install <span className="text-foreground">ntfy</span> on your phone (
              <a
                className="text-primary hover:underline"
                href="https://play.google.com/store/apps/details?id=io.heckel.ntfy"
                target="_blank"
                rel="noreferrer"
              >
                Android
              </a>{" "}
              ·{" "}
              <a
                className="text-primary hover:underline"
                href="https://apps.apple.com/app/ntfy/id1625396347"
                target="_blank"
                rel="noreferrer"
              >
                iPhone
              </a>
              ).
            </li>
            <li>2. Pick a topic below (long and random: anyone who knows it can read it).</li>
            <li>3. In the app, tap + and subscribe to the same topic. Then send a test.</li>
          </ol>

          <Field
            label="Topic"
            hint={
              envTopic
                ? "Set by the NTFY_TOPIC environment variable"
                : subscribeUrl
                  ? `Subscribe to: ${subscribeUrl}`
                  : "Not set: no notifications are sent"
            }
          >
            <div className="flex gap-2">
              <input
                className="terminal-input font-mono"
                value={topic}
                disabled={envTopic}
                placeholder="nexus-…"
                autoComplete="off"
                onChange={(event) => setTopic(event.target.value.replace(/[^\w-]/g, ""))}
              />
              <button
                type="button"
                className="secondary-button shrink-0"
                disabled={envTopic}
                onClick={() => setTopic(randomTopic())}
                title="Generate a random topic"
              >
                <Dices className="h-4 w-4" />
                <span className="hidden sm:inline">Generate</span>
              </button>
            </div>
          </Field>

          <Field label="Breaking news">
            <Segmented
              value={values.notify_news_level || "3"}
              onChange={(value) => set("notify_news_level", value)}
              options={[
                { value: "3", label: "Top stories" },
                { value: "2", label: "Top + major" },
                { value: "0", label: "Only mine" },
              ]}
            />
            <Hint>
              Major news about an asset you watch, hold or the AI has called is always sent.
            </Hint>
          </Field>

          <Field label="Price moves">
            <Segmented
              value={values.notify_move_sigma || "3"}
              onChange={(value) => set("notify_move_sigma", value)}
              options={[
                { value: "2", label: "Sensitive" },
                { value: "3", label: "Big" },
                { value: "4", label: "Extreme" },
                { value: "0", label: "Off" },
              ]}
            />
            <Hint>
              Sensitive, big, extreme = 2, 3, 4× the asset&apos;s own typical daily move (σ), so 3%
              on SPY counts but 3% on a small crypto does not. Watchlist, positions, open AI calls
              and the market gauges.
            </Hint>
          </Field>

          <div className="flex flex-wrap gap-2">
            <Toggle on={on("notify_calls")} onChange={(v) => set("notify_calls", String(v))}>
              AI buy/sell calls
            </Toggle>
            <Toggle on={on("notify_exits")} onChange={(v) => set("notify_exits", String(v))}>
              Stops & targets hit
            </Toggle>
            <Toggle
              on={on("notify_auto_analyst")}
              onChange={(v) => set("notify_auto_analyst", String(v))}
            >
              AI researches big events
            </Toggle>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="App link"
              hint="The site you open (your Vercel URL), so a tap opens the asset."
            >
              <input
                className="terminal-input"
                value={values.public_url ?? ""}
                placeholder={log.data?.public_url ?? "https://your-app.vercel.app"}
                onChange={(event) => set("public_url", event.target.value)}
              />
            </Field>
            <Field label="ntfy server" hint="Self-hosted? Put its URL here.">
              <input
                className="terminal-input"
                value={values.ntfy_server ?? ""}
                onChange={(event) => set("ntfy_server", event.target.value)}
              />
            </Field>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="primary-button"
              disabled={save.isPending}
              onClick={() => save.mutate()}
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={test.isPending || (!topic.trim() && !envTopic)}
              onClick={() => test.mutate()}
            >
              <Send className="h-4 w-4" />
              {test.isPending ? "Sending…" : "Send test"}
            </button>
          </div>
        </div>

        <div className="min-w-0">
          <div className="mb-2 text-[11px] font-bold text-muted-foreground">Recently sent</div>
          {log.data?.items.length ? (
            <div className="max-h-[460px] space-y-0 overflow-y-auto">
              {log.data.items.map((item) => (
                <div key={item.id} className="border-b border-row-line py-2.5">
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{item.kind}</span>
                    <span>·</span>
                    <span title={new Date(item.created_at).toLocaleString()}>
                      {ago(item.created_at)}
                    </span>
                    {item.status !== "sent" && (
                      <Badge
                        tone={item.status === "error" ? "bear" : "neutral"}
                        className="ml-auto"
                      >
                        {item.status}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-[13px] font-medium">{item.title}</div>
                  <div className="mt-0.5 line-clamp-3 whitespace-pre-line text-xs text-muted-foreground">
                    {item.error ?? item.message}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Nothing sent yet. Moves are checked every 3 minutes, the wire about every minute.
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <span className="mb-1 block text-[11px] font-bold text-muted-foreground">{label}</span>
      {children}
      {hint && <Hint>{hint}</Hint>}
    </div>
  );
}

function Hint({ children }: { children: ReactNode }) {
  return <span className="mt-1 block text-xs text-muted-foreground">{children}</span>;
}

function Toggle({
  on,
  onChange,
  children,
}: {
  on: boolean;
  onChange: (value: boolean) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={cn("secondary-button", on && "!border-strong !bg-accent !text-foreground")}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", on ? "bg-bull" : "bg-muted-foreground")} />
      {children}
    </button>
  );
}
