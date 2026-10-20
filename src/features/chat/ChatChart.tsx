import { BarChart, FanChart, LineChart, chartColors } from "@/features/charts/svg";
import { money, num, pct, price } from "@/lib/format";
import type { ChatChart as ChatChartData } from "@/lib/types";

const SERIES_COLORS = [
  chartColors.AMBER,
  "var(--chart-4)",
  "var(--chart-5)",
  chartColors.BULL,
  chartColors.BEAR,
  chartColors.MUTED,
];
const LEVEL_COLORS = { amber: chartColors.AMBER, bull: chartColors.BULL, bear: chartColors.BEAR };

export function ChatChart({ chart }: { chart: ChatChartData }) {
  return (
    <figure className="border border-border bg-background/60 p-3">
      <figcaption className="mb-2 text-[10px] font-bold uppercase tracking-[0.15em] text-primary">
        {chart.title}
      </figcaption>
      {chart.kind === "line" && (
        <LineChart
          height={190}
          zero={chart.format === "pct"}
          format={chart.format === "pct" ? (v) => pct(v, 0) : (v) => price(v)}
          series={chart.series.map((s, i) => ({
            ...s,
            color: SERIES_COLORS[i % SERIES_COLORS.length],
          }))}
          levels={chart.levels.map((level) => ({ ...level, color: LEVEL_COLORS[level.tone] }))}
          markers={chart.markers}
        />
      )}
      {chart.kind === "fan" && <FanChart fan={chart.fan} horizon={chart.horizon} />}
      {chart.kind === "bar" && (
        <BarChart
          bars={chart.bars}
          format={(v) =>
            chart.format === "pct" ? pct(v) : chart.format === "money" ? money(v) : num(v)
          }
        />
      )}
      {"note" in chart && chart.note && (
        <p className="mt-2 text-[10px] text-muted-foreground">{chart.note}</p>
      )}
      {chart.kind === "line" && chart.markers.length > 0 && (
        <p className="mt-1 text-[10px] text-muted-foreground">
          Amber ticks: events (hover for details).
        </p>
      )}
    </figure>
  );
}
