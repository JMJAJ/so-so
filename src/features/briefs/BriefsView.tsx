import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { RecCard } from "@/features/recs/RecCard";
import { Markdown } from "@/features/shell/Markdown";
import { Badge, Empty, ErrorNote, Loading, PageHeading, Panel, Stat } from "@/features/shell/ui";
import { api } from "@/lib/api";
import { pct, tone } from "@/lib/format";
import type { Brief, Recommendation } from "@/lib/types";
import { cn } from "@/lib/utils";

function result(rec: Recommendation): number | null {
  return rec.status === "closed" ? rec.realized_return : rec.mark_return;
}

function average(values: Array<number | null>): number | null {
  const nums = values.filter((v): v is number => v != null);
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
}

function when(iso: string) {
  const d = new Date(iso);
  return {
    day: d.toLocaleDateString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
    time: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }),
  };
}

export default function BriefsView() {
  const client = useQueryClient();
  const briefs = useQuery({ queryKey: ["briefs"], queryFn: api.briefs, refetchInterval: 120_000 });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const [selected, setSelected] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () => api.runAnalyst(),
    onSuccess: () => {
      toast.success("Analyst started; the brief appears here when it finishes");
      void client.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (error) => toast.error(String(error)),
  });

  if (briefs.isLoading) return <Loading />;
  if (briefs.error) return <ErrorNote error={briefs.error} />;
  const list = briefs.data ?? [];
  const current = list.find((b) => b.id === selected) ?? list[0];
  const calls = list.flatMap((b) => b.recommendations);
  const closed = calls.filter((r) => r.status === "closed" && r.realized_return != null);
  const running = status.data?.analyst_running ?? false;

  return (
    <div className="space-y-4">
      <PageHeading
        title="Market briefs"
        subtitle="The AI analyst's daily brief (22:30 UTC, every day): what matters this week, the calls it recorded and the ideas it rejected. Each call shows how it is doing now, or how it ended."
        actions={
          <button
            className="primary-button"
            disabled={running || run.isPending}
            onClick={() => run.mutate()}
          >
            {running ? "Analyst researching…" : "Write a brief now"}
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          [
            "Briefs",
            String(list.length),
            list.length ? `since ${when(list.at(-1)!.started_at).day}` : "",
          ],
          [
            "Calls made",
            String(calls.length),
            `${calls.filter((r) => r.status === "open").length} open`,
          ],
          [
            "Closed calls won",
            closed.length
              ? pct(
                  closed.filter((r) => (r.realized_return ?? 0) > 0).length / closed.length,
                  0,
                  false,
                )
              : "—",
            `${closed.length} closed`,
          ],
          ["Avg call result", pct(average(calls.map(result))), "open marks + closed results"],
        ].map(([label, value, hint]) => (
          <div key={label} className="terminal-panel p-3">
            <Stat label={label} value={value} hint={hint} />
          </div>
        ))}
      </div>

      {!current ? (
        <Empty title="No briefs yet">
          The analyst writes one every day at 22:30 UTC, or press “Write a brief now”.
        </Empty>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
          <Panel title="By day" bodyClassName="p-0">
            <ul className="max-h-[70vh] overflow-y-auto">
              {list.map((brief) => (
                <BriefRow
                  key={brief.id}
                  brief={brief}
                  active={brief.id === current.id}
                  onClick={() => setSelected(brief.id)}
                />
              ))}
            </ul>
          </Panel>
          <BriefDetail brief={current} />
        </div>
      )}
    </div>
  );
}

function BriefRow({
  brief,
  active,
  onClick,
}: {
  brief: Brief;
  active: boolean;
  onClick: () => void;
}) {
  const { day, time } = when(brief.started_at);
  const avg = average(brief.recommendations.map(result));
  return (
    <li>
      <button
        onClick={onClick}
        className={cn(
          "flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2.5 text-left text-[11px] hover:bg-accent/30",
          active && "bg-accent",
        )}
      >
        <span>
          <span className={cn("block font-bold", active && "text-foreground")}>{day}</span>
          <span className="text-xs text-muted-foreground">
            {time} · {brief.recommendations.length} call
            {brief.recommendations.length === 1 ? "" : "s"}
          </span>
        </span>
        {brief.status !== "completed" ? (
          <Badge tone={brief.status === "failed" ? "bear" : "amber"}>{brief.status}</Badge>
        ) : (
          <span className={cn("font-bold", tone(avg))}>{avg != null ? pct(avg) : ""}</span>
        )}
      </button>
    </li>
  );
}

function BriefDetail({ brief }: { brief: Brief }) {
  const { day, time } = when(brief.started_at);
  return (
    <div className="min-w-0 space-y-4">
      <Panel
        title={`${day} · ${time}`}
        actions={
          <Badge tone={brief.status === "completed" ? "bull" : "amber"}>{brief.status}</Badge>
        }
      >
        {brief.summary ? (
          <div className="text-[12px] leading-relaxed">
            <Markdown text={brief.summary} />
          </div>
        ) : brief.error ? (
          <p className="text-[12px] text-bear">{brief.error}</p>
        ) : (
          <Empty title="Still researching" />
        )}
      </Panel>
      {brief.recommendations.length > 0 && (
        <Panel
          title="Calls from this brief"
          subtitle="Live mark while open, realized result once closed."
        >
          <div className="space-y-2">
            {brief.recommendations.map((rec) => (
              <RecCard key={rec.id} rec={rec} compact />
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
