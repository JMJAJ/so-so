import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { CalibrationChart } from "@/features/charts/svg";
import { RecCard } from "@/features/recs/RecCard";
import { Markdown } from "@/features/shell/Markdown";
import { SimCheckPanel } from "@/features/sim/SimPanels";
import {
  Badge,
  Empty,
  ErrorNote,
  Loading,
  PageHeading,
  Panel,
  Stat,
  Td,
  Th,
  TableWrap,
} from "@/features/shell/ui";
import { api } from "@/lib/api";
import { humanize, num, pct, tone } from "@/lib/format";
import type { ModelSummary, RecordStats, TrackRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function TrackRecordView() {
  const record = useQuery({
    queryKey: ["track-record"],
    queryFn: api.trackRecord,
    refetchInterval: 120_000,
  });
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const [group, setGroup] = useState<
    | "by_evidence"
    | "by_skill"
    | "by_asset_class"
    | "by_confidence"
    | "by_direction"
    | "by_source"
    | "by_exit"
  >("by_evidence");

  if (record.isLoading) return <Loading />;
  if (record.error) return <ErrorNote error={record.error} />;
  const data = record.data!;
  const o = data.overall;

  return (
    <div className="space-y-4">
      <PageHeading
        title="Track record"
        subtitle="Is the AI actually right? Every recommendation is scored on its own path (stop, target or horizon) and compared with its benchmark. A Brier score below 0.25 beats a coin flip; dots on the diagonal mean the stated probabilities can be trusted."
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        {[
          ["Closed calls", o.n ? String(o.n) : "0", `${data.open.n} still open`],
          [
            "Hit rate",
            pct(o.hit_rate ?? null, 0, false),
            o.avg_probability ? `stated avg ${pct(o.avg_probability, 0, false)}` : "",
          ],
          [
            "Avg return",
            pct(o.avg_return ?? null),
            o.t_stat != null ? `t = ${num(o.t_stat, 1)}` : "",
          ],
          ["Avg excess", pct(o.avg_excess ?? null), "vs benchmark (longs)"],
          ["Brier", o.brier != null ? num(o.brier, 3) : "—", "0.25 = coin flip"],
          [
            "Best / worst",
            o.best != null ? `${pct(o.best, 0)} / ${pct(o.worst ?? null, 0)}` : "—",
            "",
          ],
        ].map(([label, value, hint]) => (
          <div key={label} className="terminal-panel p-3">
            <Stat label={label} value={value} hint={hint} />
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Panel title="Calibration" subtitle="Stated probability vs how often calls actually won.">
          {data.calibration.length ? (
            <CalibrationChart rows={data.calibration} />
          ) : (
            <Empty title="Needs closed calls" />
          )}
        </Panel>
        <Panel
          title="What works"
          actions={(
            [
              "by_evidence",
              "by_skill",
              "by_asset_class",
              "by_confidence",
              "by_direction",
              "by_source",
              "by_exit",
            ] as const
          ).map((key) => (
            <button
              key={key}
              className={cn(
                "secondary-button !px-2 !py-1",
                group === key && "!border-[#2f352f] !bg-accent !text-foreground",
              )}
              onClick={() => setGroup(key)}
            >
              {key.replace("by_", "")}
            </button>
          ))}
        >
          <BreakdownTable rows={data[group]} />
          <pre className="mt-3 whitespace-pre-wrap border-t border-border pt-3 text-[11px] leading-relaxed text-muted-foreground">
            {data.lessons}
          </pre>
        </Panel>
      </div>

      <SkillsPanel record={data} />

      <ReplayPanel record={data} />

      <SimCheckPanel />

      <Panel
        title="Quant model validation"
        subtitle="Walk-forward, out-of-sample: each year is predicted by a model fit only on earlier data, with signals chosen by their own past significance. IC = rank correlation between forecast and the realized 20-session return."
      >
        {models.isLoading ? <Loading /> : <ModelTable models={models.data ?? []} />}
      </Panel>

      <Panel title="Every closed call">
        {data.recent.length === 0 ? (
          <Empty title="Nothing closed yet">
            Calls close at their stop, target or horizon (5–40 sessions). Check back in a few weeks.
          </Empty>
        ) : (
          <div className="space-y-2">
            {data.recent.map((rec) => (
              <RecCard key={rec.id} rec={rec} compact />
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function SkillsPanel({ record }: { record: TrackRecord }) {
  const skills = useQuery({ queryKey: ["skills"], queryFn: api.skills });
  const [shown, setShown] = useState<string | null>(null);
  const body = useQuery({
    queryKey: ["skill", shown],
    queryFn: () => api.skill(shown as string),
    enabled: Boolean(shown),
  });
  const early = record.early_closes;
  return (
    <Panel
      title="AI skills"
      subtitle="Playbooks the AI loads before a task. Every call records which skills (and versions) were loaded, so this shows whether a skill actually improves results. Generated skills are rebuilt from the data."
    >
      {skills.isLoading ? (
        <Loading />
      ) : (
        <div className="space-y-4">
          <TableWrap>
            <thead>
              <tr>
                <Th>Skill</Th>
                <Th>Use when</Th>
                <Th right>Closed calls</Th>
                <Th right>Hit rate</Th>
                <Th right>Avg return</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {(skills.data ?? []).map((skill) => {
                const stats = Object.values(skill.stats);
                const n = stats.reduce((sum, s) => sum + (s.n ?? 0), 0);
                const latest = Object.entries(skill.stats).at(-1)?.[1];
                return (
                  <tr key={skill.name}>
                    <Td>
                      <div className="font-bold">{skill.name}</div>
                      <div className="max-w-[340px] whitespace-normal text-xs text-muted-foreground">
                        {skill.description}
                      </div>
                    </Td>
                    <Td className="min-w-[180px] max-w-[240px] whitespace-normal text-xs text-muted-foreground">
                      {skill.when}
                    </Td>
                    <Td right>{n}</Td>
                    <Td right>{pct(latest?.hit_rate ?? null, 0, false)}</Td>
                    <Td right className={tone(latest?.avg_return)}>
                      {pct(latest?.avg_return ?? null)}
                    </Td>
                    <Td>
                      <button
                        className="secondary-button !px-2 !py-1"
                        onClick={() => setShown(shown === skill.name ? null : skill.name)}
                      >
                        {shown === skill.name ? "hide" : "read"}
                      </button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableWrap>
          {shown && (
            <div className="rounded-lg min-w-0 overflow-hidden break-words border border-border p-3 text-[12px]">
              {body.data ? (
                <>
                  <div className="mb-2 text-xs text-foreground">
                    {body.data.name} · version {body.data.version}
                  </div>
                  <Markdown text={body.data.body} />
                </>
              ) : (
                <Loading />
              )}
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">
            AI early closes: {early.n} so far
            {early.scored > 0 && early.avg_saved != null
              ? `; ${early.helped} of ${early.scored} beat holding, ${pct(early.avg_saved)} per call vs holding.`
              : "; none scored against holding yet."}
          </p>
        </div>
      )}
    </Panel>
  );
}

function ReplayPanel({ record }: { record: TrackRecord }) {
  const replay = record.replay;
  const cal = record.probability_calibration;
  return (
    <Panel
      title="Point-in-time replay"
      subtitle="The evidence engine run on past dates using only what was known then: event history whose outcomes had already played out, a 2×ATR stop and 3×ATR target. It tests the evidence, not the AI's judgement, and sets how much new probabilities are trusted."
    >
      {!replay || !replay.calls ? (
        <Empty title="No replay yet">Runs with the weekly research job.</Empty>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat
              label="Calls"
              value={String(replay.calls)}
              hint={replay.period ? `${replay.period[0]} → ${replay.period[1]}` : ""}
            />
            <Stat
              label="Hit rate"
              value={pct(replay.hit_rate ?? null, 0, false)}
              hint={`stated avg ${pct(replay.avg_probability ?? null, 0, false)}`}
            />
            <Stat
              label="Avg return"
              value={pct(replay.avg_return ?? null)}
              hint={replay.t_stat != null ? `t = ${num(replay.t_stat, 1)}` : ""}
            />
            <Stat label="Brier" value={num(replay.brier ?? null, 3)} hint="0.25 = coin flip" />
            <Stat
              label="Evidence trust k"
              value={cal ? num(cal.k, 2) : "—"}
              hint="0 = ignore evidence, 1 = take it at face value"
            />
          </div>
          {cal && <p className="text-[11px] text-muted-foreground">{cal.basis}</p>}
          <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
            {replay.calibration?.length ? <CalibrationChart rows={replay.calibration} /> : <span />}
            <TableWrap>
              <thead>
                <tr>
                  <Th>Event</Th>
                  <Th right>Calls</Th>
                  <Th right>Hit rate</Th>
                  <Th right>Avg return</Th>
                </tr>
              </thead>
              <tbody>
                {(replay.by_event_type ?? []).map((row) => (
                  <tr key={row.event_type}>
                    <Td>{humanize(row.event_type)}</Td>
                    <Td right>{row.n}</Td>
                    <Td right>{pct(row.hit_rate, 0, false)}</Td>
                    <Td right className={tone(row.avg_return)}>
                      {pct(row.avg_return)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          </div>
        </div>
      )}
    </Panel>
  );
}

function BreakdownTable({ rows }: { rows: Record<string, RecordStats> }) {
  const entries = Object.entries(rows);
  if (!entries.length) return <Empty title="No data yet" />;
  return (
    <TableWrap>
      <thead>
        <tr>
          <Th>Group</Th>
          <Th right>n</Th>
          <Th right>Hit</Th>
          <Th right>Avg</Th>
          <Th right>Excess</Th>
          <Th right>Brier</Th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([name, stats]) => (
          <tr key={name}>
            <Td>{humanize(name)}</Td>
            <Td right>{stats.n}</Td>
            <Td right>{pct(stats.hit_rate ?? null, 0, false)}</Td>
            <Td right className={tone(stats.avg_return)}>
              {pct(stats.avg_return ?? null)}
            </Td>
            <Td right className={tone(stats.avg_excess)}>
              {pct(stats.avg_excess ?? null)}
            </Td>
            <Td right>{stats.brier != null ? num(stats.brier, 3) : "—"}</Td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  );
}

function ModelTable({ models }: { models: ModelSummary[] }) {
  if (!models.length)
    return (
      <Empty title="Backtest has not run yet">It runs during bootstrap and every Saturday.</Empty>
    );
  return (
    <div className="space-y-4">
      {models.map((model) => {
        const wf = model.walk_forward;
        return (
          <div key={model.asset_class} className="rounded-lg border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-sm font-bold ">{model.asset_class}</span>
              <Badge tone={model.has_edge ? "bull" : "neutral"}>
                {model.has_edge ? "validated edge" : "no reliable edge"}
              </Badge>
              {wf && (
                <span className="text-[11px] text-muted-foreground">
                  OOS IC <span className={tone(wf.ic)}>{wf.ic.toFixed(3)}</span> (t{" "}
                  {wf.t_stat.toFixed(1)}, n {wf.n}) · top–bottom quintile{" "}
                  <span className={tone(wf.long_short)}>{pct(wf.long_short)}</span> · {wf.period[0]}{" "}
                  → {wf.period[1]}
                </span>
              )}
            </div>
            {wf && (
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {Object.entries(wf.ic_by_year).map(([year, ic]) => (
                  <span
                    key={year}
                    className="rounded-lg border border-border px-1.5 py-0.5 tabular-nums"
                  >
                    {year} <span className={tone(ic)}>{ic.toFixed(2)}</span>
                  </span>
                ))}
              </div>
            )}
            {model.signals && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                {Object.entries(model.signals).map(([name, stats]) => (
                  <span
                    key={name}
                    className={cn(
                      Math.abs(stats.t_stat) >= 2 ? "text-foreground" : "text-muted-foreground",
                    )}
                  >
                    {name}: IC <span className={tone(stats.ic)}>{stats.ic.toFixed(3)}</span> (t{" "}
                    {stats.t_stat.toFixed(1)})
                  </span>
                ))}
              </div>
            )}
            {model.reason && (
              <div className="mt-1 text-xs text-muted-foreground">{model.reason}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
