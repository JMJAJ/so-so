import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Markdown } from "@/features/shell/Markdown";
import {
  Badge,
  ErrorNote,
  Loading,
  PageHeading,
  Panel,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { ago, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

const SECRET_LABELS: Record<string, string> = {
  anthropic_api_key: "Anthropic API key",
  openai_api_key: "OpenAI API key",
  openrouter_api_key: "OpenRouter API key",
  nvidia_api_key: "NVIDIA NIM API key (free tier)",
  finnhub_api_key: "Finnhub API key (optional, company news)",
};

export default function SettingsView() {
  return (
    <div className="space-y-4">
      <PageHeading
        title="Settings & system"
        subtitle="AI provider, risk, universe and the background jobs that keep the research current."
      />
      <SettingsForm />
      <JobsPanel />
      <RunsPanel />
      <LogsPanel />
    </div>
  );
}

function SettingsForm() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [values, setValues] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  useEffect(() => {
    if (settings.data) setValues(settings.data.values);
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      api.saveSettings(
        values,
        Object.fromEntries(Object.entries(secrets).filter(([, v]) => v !== "")),
      ),
    onSuccess: () => {
      toast.success("Settings saved");
      setSecrets({});
      void client.invalidateQueries();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const test = useMutation({
    mutationFn: api.testLlm,
    onSuccess: (result) =>
      result.ok
        ? toast.success(`${result.provider} · ${result.model} answered in ${result.latency_ms} ms`)
        : toast.error(result.error ?? "LLM test failed"),
  });

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorNote error={settings.error} />;
  const data = settings.data!;
  const set = (key: string, value: string) =>
    setValues((current) => ({ ...current, [key]: value }));
  const provider = values.llm_provider ?? "anthropic";
  const enabled = (values.enabled_classes ?? "").split(",").filter(Boolean);

  return (
    <form
      className="grid gap-4 xl:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <Panel title="AI model">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Provider">
            <select
              className="terminal-select"
              value={provider}
              onChange={(event) => {
                const next = event.target.value;
                set("llm_provider", next);
                set("llm_model", data.providers[next]?.default_model ?? "");
                set(
                  "llm_fast_model",
                  data.providers[next]?.fast_model ??
                    (next === "anthropic" ? "claude-haiku-5-5" : ""),
                );
              }}
            >
              {Object.entries(data.providers).map(([key, meta]) => (
                <option key={key} value={key}>
                  {meta.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Analyst / chat model">
            <input
              className="terminal-input"
              value={values.llm_model ?? ""}
              onChange={(e) => set("llm_model", e.target.value)}
            />
          </Field>
          <Field
            label="Fast model (headline tagging)"
            hint={provider === "anthropic" ? "e.g. claude-haiku-5-5" : "blank = same as main model"}
          >
            <input
              className="terminal-input"
              value={values.llm_fast_model ?? ""}
              onChange={(e) => set("llm_fast_model", e.target.value)}
            />
          </Field>
          <Field
            label="Base URL override"
            hint={data.providers[provider]?.base_url ?? "SDK default"}
          >
            <input
              className="terminal-input"
              value={values.llm_base_url ?? ""}
              onChange={(e) => set("llm_base_url", e.target.value)}
              placeholder="optional"
            />
          </Field>
        </div>
        <div className="mt-4 space-y-3">
          {Object.entries(SECRET_LABELS).map(([key, label]) => {
            const state = data.secrets[key];
            return (
              <Field
                key={key}
                label={label}
                hint={
                  state?.set
                    ? `set${state.source === "env" ? " via environment" : ""}${state.hint ? ` (${state.hint})` : ""}`
                    : "not set"
                }
              >
                <input
                  className="terminal-input"
                  type="password"
                  autoComplete="off"
                  placeholder={state?.set ? "•••••••• (leave blank to keep)" : ""}
                  value={secrets[key] ?? ""}
                  onChange={(e) => setSecrets((current) => ({ ...current, [key]: e.target.value }))}
                />
              </Field>
            );
          })}
          <p className="text-[10px] text-muted-foreground">
            Keys are stored encrypted in the local database. Environment variables (.env) take
            precedence.
          </p>
        </div>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="secondary-button"
            onClick={() => test.mutate()}
            disabled={test.isPending}
          >
            {test.isPending ? "Testing…" : "Test connection"}
          </button>
        </div>
      </Panel>

      <Panel title="Paper trading & research">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Autopilot" hint="Open a paper position for every recommendation">
            <select
              className="terminal-select"
              value={values.autopilot}
              onChange={(e) => set("autopilot", e.target.value)}
            >
              <option value="true">On</option>
              <option value="false">Off (track calls only)</option>
            </select>
          </Field>
          <Field label="Risk per trade" hint="Fraction of equity lost if the stop is hit">
            <input
              className="terminal-input"
              type="number"
              step="0.0025"
              min="0.001"
              max="0.05"
              value={values.risk_per_trade ?? ""}
              onChange={(e) => set("risk_per_trade", e.target.value)}
            />
          </Field>
          <Field label="Max positions">
            <input
              className="terminal-input"
              type="number"
              min="1"
              max="50"
              value={values.max_positions ?? ""}
              onChange={(e) => set("max_positions", e.target.value)}
            />
          </Field>
          <Field label="Max gross exposure" hint="× equity">
            <input
              className="terminal-input"
              type="number"
              step="0.1"
              min="0.1"
              max="3"
              value={values.max_exposure ?? ""}
              onChange={(e) => set("max_exposure", e.target.value)}
            />
          </Field>
          <Field label="Analyst shortlist size">
            <input
              className="terminal-input"
              type="number"
              min="3"
              max="40"
              value={values.analyst_shortlist ?? ""}
              onChange={(e) => set("analyst_shortlist", e.target.value)}
            />
          </Field>
          <Field label="Max new calls per run">
            <input
              className="terminal-input"
              type="number"
              min="0"
              max="15"
              value={values.analyst_max_recs ?? ""}
              onChange={(e) => set("analyst_max_recs", e.target.value)}
            />
          </Field>
          <Field label="Minimum probability" hint="Calls below this are rejected">
            <input
              className="terminal-input"
              type="number"
              step="0.01"
              min="0.5"
              max="0.9"
              value={values.min_probability ?? ""}
              onChange={(e) => set("min_probability", e.target.value)}
            />
          </Field>
          <Field label="GDELT history (days)" hint="Geopolitical backfill, ~4 MB/day download">
            <input
              className="terminal-input"
              type="number"
              min="30"
              max="3650"
              value={values.gdelt_backfill_days ?? ""}
              onChange={(e) => set("gdelt_backfill_days", e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-4">
          <div className="mb-1.5 text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
            Asset classes the AI may recommend
          </div>
          <div className="flex flex-wrap gap-2">
            {data.asset_classes.map((cls) => {
              const on = enabled.includes(cls);
              return (
                <button
                  type="button"
                  key={cls}
                  className={cn("secondary-button", on && "!border-primary !text-primary")}
                  onClick={() =>
                    set(
                      "enabled_classes",
                      (on ? enabled.filter((c) => c !== cls) : [...enabled, cls]).join(","),
                    )
                  }
                >
                  {cls}
                </button>
              );
            })}
          </div>
        </div>
        <div className="mt-6 flex justify-end">
          <button className="primary-button" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save settings"}
          </button>
        </div>
      </Panel>
    </form>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[9px] font-bold uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[10px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

function JobsPanel() {
  const client = useQueryClient();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 5_000 });
  const run = useMutation({
    mutationFn: api.runJob,
    onSuccess: (result) => {
      toast.success(`Started ${result.started}`);
      void client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <Panel title="Background jobs" subtitle="Scheduled automatically (UTC). Run any of them now.">
      {jobs.isLoading ? (
        <Loading />
      ) : (
        <TableWrap>
          <thead>
            <tr>
              <Th>Job</Th>
              <Th>Status</Th>
              <Th>Last run</Th>
              <Th>Next</Th>
              <Th>Detail</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {(jobs.data ?? []).map((job) => (
              <tr key={job.name}>
                <Td>
                  <div className="font-bold">{humanize(job.name)}</div>
                  <div className="max-w-[280px] whitespace-normal text-[10px] text-muted-foreground">
                    {job.description}
                  </div>
                </Td>
                <Td>
                  {job.running ? (
                    <Badge tone="amber">running</Badge>
                  ) : (
                    <Badge
                      tone={
                        job.last_status === "ok"
                          ? "bull"
                          : job.last_status === "error"
                            ? "bear"
                            : "neutral"
                      }
                    >
                      {job.last_status ?? "never"}
                    </Badge>
                  )}
                </Td>
                <Td className="text-[11px]">{ago(job.last_finished)}</Td>
                <Td className="text-[11px]">{job.next_run ? ago(job.next_run) : "—"}</Td>
                <Td
                  className="max-w-[320px] truncate text-[10px] text-muted-foreground"
                  title={job.last_error ?? job.last_summary ?? ""}
                >
                  {job.running
                    ? job.progress
                    : job.last_status === "error"
                      ? job.last_error?.split("\n")[0]
                      : job.last_summary}
                </Td>
                <Td>
                  <button
                    className="icon-button"
                    disabled={job.running || run.isPending}
                    onClick={() => run.mutate(job.name)}
                    aria-label={`Run ${job.name}`}
                  >
                    <Play className="h-3 w-3" />
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Panel>
  );
}

function RunsPanel() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 30_000 });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Analyst runs">
      {runs.isLoading ? (
        <Loading />
      ) : !runs.data?.length ? (
        <div className="text-xs text-muted-foreground">No analyst runs yet.</div>
      ) : (
        <ul className="space-y-2">
          {runs.data.map((run) => (
            <li key={run.id} className="border border-border">
              <button
                className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-xs"
                onClick={() => setOpen(open === run.id ? null : run.id)}
              >
                <Badge
                  tone={
                    run.status === "completed" ? "bull" : run.status === "failed" ? "bear" : "amber"
                  }
                >
                  {run.status}
                </Badge>
                <span>{new Date(run.started_at).toLocaleString()}</span>
                <span className="text-muted-foreground">{run.id}</span>
              </button>
              {open === run.id && (
                <div className="border-t border-border px-3 py-3">
                  {run.error ? (
                    <div className="text-xs text-bear">{run.error}</div>
                  ) : (
                    <Markdown text={run.summary ?? "(no summary)"} />
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function LogsPanel() {
  const logs = useQuery({ queryKey: ["logs"], queryFn: api.logs, refetchInterval: 15_000 });
  return (
    <Panel title="System log">
      <div className="max-h-72 overflow-y-auto font-mono text-[10px] leading-relaxed">
        {(logs.data ?? []).map((row) => (
          <div key={row.id} className="flex gap-2">
            <span className="shrink-0 text-muted-foreground">
              {row.created_at.slice(5, 19).replace("T", " ")}
            </span>
            <span
              className={cn(
                "w-10 shrink-0 uppercase",
                row.level === "error"
                  ? "text-bear"
                  : row.level === "warn"
                    ? "text-primary"
                    : "text-muted-foreground",
              )}
            >
              {row.level}
            </span>
            <span className="w-20 shrink-0 text-muted-foreground">{row.kind}</span>
            <span className="min-w-0 break-words">{row.message}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
