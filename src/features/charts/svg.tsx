import { useMemo, useState } from "react";

import { pct } from "@/lib/format";
import type { AnalogResult } from "@/lib/types";

const AMBER = "var(--color-primary)";
const BULL = "var(--color-bull)";
const BEAR = "var(--color-bear)";
const MUTED = "var(--color-muted-foreground)";
const GRID = "var(--color-border)";

function scale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (value: number) => r0 + ((value - d0) / span) * (r1 - r0);
}

/** Analog fan: percentile bands of forward paths after the most similar past states. */
export function FanChart({
  fan,
  horizon,
}: {
  fan: NonNullable<AnalogResult["fan"]>;
  horizon: number;
}) {
  const width = 560;
  const height = 220;
  const pad = { l: 44, r: 12, t: 12, b: 22 };
  const [hover, setHover] = useState<number | null>(null);
  const values = fan.flatMap((row) => [row.p10, row.p90]);
  const y = scale([Math.min(...values, 0), Math.max(...values, 0)], [height - pad.b, pad.t]);
  const x = scale([0, fan.length - 1], [pad.l, width - pad.r]);
  const band = (lo: "p10" | "p25", hi: "p75" | "p90") =>
    `${fan.map((row, i) => `${i ? "L" : "M"}${x(i)},${y(row[hi])}`).join(" ")} ${fan
      .slice()
      .reverse()
      .map((row, i) => `L${x(fan.length - 1 - i)},${y(row[lo])}`)
      .join(" ")} Z`;
  const median = fan.map((row, i) => `${i ? "L" : "M"}${x(i)},${y(row.p50)}`).join(" ");
  const ticks = [Math.min(...values), 0, Math.max(...values)];
  const active = hover != null ? fan[hover] : fan[Math.min(horizon, fan.length - 1)];
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label="Forward return distribution after historical analogs"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - box.left) / box.width) * width;
          setHover(
            Math.max(
              0,
              Math.min(
                fan.length - 1,
                Math.round(((px - pad.l) / (width - pad.l - pad.r)) * (fan.length - 1)),
              ),
            ),
          );
        }}
      >
        {ticks.map((tick, i) => (
          <g key={i}>
            <line
              x1={pad.l}
              x2={width - pad.r}
              y1={y(tick)}
              y2={y(tick)}
              stroke={GRID}
              strokeDasharray={tick === 0 ? "" : "2 3"}
            />
            <text x={pad.l - 6} y={y(tick) + 3} textAnchor="end" fontSize="9" fill={MUTED}>
              {pct(tick, 0)}
            </text>
          </g>
        ))}
        <path d={band("p10", "p90")} fill={AMBER} opacity={0.1} />
        <path d={band("p25", "p75")} fill={AMBER} opacity={0.2} />
        <path d={median} fill="none" stroke={AMBER} strokeWidth={1.5} />
        <line
          x1={x(horizon)}
          x2={x(horizon)}
          y1={pad.t}
          y2={height - pad.b}
          stroke={MUTED}
          strokeDasharray="3 3"
        />
        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} stroke={MUTED} />
        )}
        <text x={pad.l} y={height - 6} fontSize="9" fill={MUTED}>
          day 0
        </text>
        <text x={width - pad.r} y={height - 6} fontSize="9" fill={MUTED} textAnchor="end">
          +{fan.length - 1} sessions
        </text>
      </svg>
      {active && (
        <div className="mt-1 flex flex-wrap gap-x-4 text-[10px] text-muted-foreground">
          <span>day {active.day}</span>
          <span>p10 {pct(active.p10)}</span>
          <span>p25 {pct(active.p25)}</span>
          <span className="text-primary">median {pct(active.p50)}</span>
          <span>p75 {pct(active.p75)}</span>
          <span>p90 {pct(active.p90)}</span>
        </div>
      )}
    </div>
  );
}

export interface Series {
  name: string;
  color: string;
  points: Array<{ x: string; y: number | null }>;
}

/** Multi-line chart over a shared date axis. */
export function LineChart({
  series,
  height = 200,
  format = (v: number) => v.toFixed(1),
  zero = false,
}: {
  series: Series[];
  height?: number;
  format?: (value: number) => string;
  zero?: boolean;
}) {
  const width = 600;
  const pad = { l: 46, r: 10, t: 10, b: 20 };
  const dates = useMemo(
    () => Array.from(new Set(series.flatMap((s) => s.points.map((p) => p.x)))).sort(),
    [series],
  );
  const values = series.flatMap((s) =>
    s.points.map((p) => p.y).filter((v): v is number => v != null),
  );
  if (dates.length < 2 || values.length < 2) {
    return (
      <div className="py-8 text-center text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        Not enough data yet
      </div>
    );
  }
  const lo = Math.min(...values, ...(zero ? [0] : []));
  const hi = Math.max(...values, ...(zero ? [0] : []));
  const y = scale([lo, hi], [height - pad.b, pad.t]);
  const index = new Map(dates.map((d, i) => [d, i]));
  const x = scale([0, dates.length - 1], [pad.l, width - pad.r]);
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        role="img"
        aria-label={series.map((s) => s.name).join(" vs ")}
      >
        {[lo, (lo + hi) / 2, hi].map((tick, i) => (
          <g key={i}>
            <line
              x1={pad.l}
              x2={width - pad.r}
              y1={y(tick)}
              y2={y(tick)}
              stroke={GRID}
              strokeDasharray="2 3"
            />
            <text x={pad.l - 6} y={y(tick) + 3} textAnchor="end" fontSize="9" fill={MUTED}>
              {format(tick)}
            </text>
          </g>
        ))}
        {zero && lo < 0 && hi > 0 && (
          <line x1={pad.l} x2={width - pad.r} y1={y(0)} y2={y(0)} stroke={MUTED} />
        )}
        {series.map((s) => {
          const d = s.points
            .filter((p) => p.y != null)
            .map((p, i) => `${i ? "L" : "M"}${x(index.get(p.x) ?? 0)},${y(p.y as number)}`)
            .join(" ");
          return <path key={s.name} d={d} fill="none" stroke={s.color} strokeWidth={1.4} />;
        })}
        <text x={pad.l} y={height - 5} fontSize="9" fill={MUTED}>
          {dates[0]}
        </text>
        <text x={width - pad.r} y={height - 5} fontSize="9" fill={MUTED} textAnchor="end">
          {dates[dates.length - 1]}
        </text>
      </svg>
      <div className="mt-1 flex flex-wrap gap-4 text-[10px] text-muted-foreground">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-3" style={{ background: s.color }} /> {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Stated probability vs realized hit rate. On the diagonal = calibrated. */
export function CalibrationChart({
  rows,
}: {
  rows: Array<{ bucket: string; n: number; stated: number; realized: number }>;
}) {
  const size = 240;
  const pad = 30;
  const s = scale([0.4, 1], [size - pad, pad]);
  const sx = scale([0.4, 1], [pad, size - pad]);
  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="w-full max-w-[280px]"
      role="img"
      aria-label="Calibration chart"
    >
      <rect
        x={pad}
        y={pad}
        width={size - pad * 2}
        height={size - pad * 2}
        fill="none"
        stroke={GRID}
      />
      <line x1={sx(0.4)} y1={s(0.4)} x2={sx(1)} y2={s(1)} stroke={MUTED} strokeDasharray="3 3" />
      {[0.5, 0.75, 1].map((tick) => (
        <g key={tick}>
          <text x={sx(tick)} y={size - pad + 12} fontSize="8" textAnchor="middle" fill={MUTED}>
            {Math.round(tick * 100)}%
          </text>
          <text x={pad - 4} y={s(tick) + 3} fontSize="8" textAnchor="end" fill={MUTED}>
            {Math.round(tick * 100)}%
          </text>
        </g>
      ))}
      <text x={size / 2} y={size - 4} fontSize="8" textAnchor="middle" fill={MUTED}>
        stated probability
      </text>
      {rows.map((row) => (
        <circle
          key={row.bucket}
          cx={sx(Math.max(0.4, row.stated))}
          cy={s(Math.max(0.4, Math.min(1, row.realized)))}
          r={Math.min(10, 3 + Math.sqrt(row.n))}
          fill={row.realized >= row.stated ? BULL : BEAR}
          opacity={0.75}
        >
          <title>{`${row.bucket}: stated ${Math.round(row.stated * 100)}% → realized ${Math.round(row.realized * 100)}% (n=${row.n})`}</title>
        </circle>
      ))}
    </svg>
  );
}

/** Tiny sparkline for regime strip values. */
export function Sparkline({
  values,
  color = AMBER,
}: {
  values: Array<number | null>;
  color?: string;
}) {
  const clean = values.filter((v): v is number => v != null);
  if (clean.length < 2) return null;
  const width = 90;
  const height = 22;
  const y = scale([Math.min(...clean), Math.max(...clean)], [height - 2, 2]);
  const x = scale([0, values.length - 1], [0, width]);
  const d = values
    .map((v, i) => (v == null ? null : `${x(i)},${y(v)}`))
    .filter(Boolean)
    .map((point, i) => `${i ? "L" : "M"}${point}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-5 w-[90px]" aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}

export const chartColors = { AMBER, BULL, BEAR, MUTED };
