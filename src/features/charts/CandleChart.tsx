import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { AssetDetail, Recommendation } from "@/lib/types";

const COLORS = {
  bg: "#0d0d0d",
  text: "#8b8b82",
  grid: "#1c1c1a",
  up: "#27c977",
  down: "#ef4758",
  amber: "#f3b61f",
  muted: "#6b6b66",
};

export default function CandleChart({
  bars,
  events,
  recommendations,
  showMacro = false,
  height = 420,
}: {
  bars: AssetDetail["bars"];
  events: AssetDetail["events"];
  recommendations: Recommendation[];
  showMacro?: boolean;
  height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current || bars.length === 0) return;
    const chart = createChart(host.current, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor: COLORS.text,
        fontFamily: "JetBrains Mono",
        fontSize: 10,
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: "#292925" },
      timeScale: { borderColor: "#292925" },
      crosshair: { mode: 0 },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderUpColor: COLORS.up,
      borderDownColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
    });
    const rows = bars.filter((bar) => bar.c != null);
    candles.setData(
      rows.map((bar) => ({
        time: bar.t as Time,
        open: bar.o ?? bar.c,
        high: bar.h ?? bar.c,
        low: bar.l ?? bar.c,
        close: bar.c,
      })),
    );
    if (rows.some((bar) => bar.v)) {
      const volume = chart.addSeries(HistogramSeries, {
        priceScaleId: "vol",
        priceFormat: { type: "volume" },
        color: "#2a2a27",
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volume.setData(rows.map((bar) => ({ time: bar.t as Time, value: bar.v ?? 0 })));
    }

    const firstDate = rows[0]?.t ?? "";
    const tradingDays = new Set(rows.map((bar) => bar.t));
    const markers: SeriesMarker<Time>[] = events
      .filter((event) => event.date >= firstDate && tradingDays.has(event.date))
      .filter((event) => showMacro || event.instrument_id != null)
      .map((event) => {
        const own = event.instrument_id != null;
        // Own events (earnings) get a labelled arrow; macro events stay unlabelled dots to avoid clutter.
        return own
          ? {
              time: event.date as Time,
              position: "belowBar",
              color: event.type.endsWith("beat") ? COLORS.up : COLORS.down,
              shape: event.type.endsWith("beat") ? "arrowUp" : "arrowDown",
              text: event.type.endsWith("beat") ? "beat" : "miss",
            }
          : {
              time: event.date as Time,
              position: "aboveBar",
              color: COLORS.amber,
              shape: "circle",
              size: 0.5,
            };
      });
    for (const rec of recommendations) {
      const day = rec.created_at.slice(0, 10);
      const snapped = rows.find((bar) => bar.t >= day)?.t;
      if (snapped) {
        markers.push({
          time: snapped as Time,
          position: rec.direction === "long" ? "belowBar" : "aboveBar",
          color: COLORS.amber,
          shape: rec.direction === "long" ? "arrowUp" : "arrowDown",
          text: `AI ${rec.direction}`,
        });
      }
    }
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    createSeriesMarkers(candles, markers);

    const open = recommendations.find((rec) => rec.status === "open");
    if (open) {
      const line = (price: number, color: string, title: string, style = LineStyle.Dashed) =>
        candles.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: style,
          axisLabelVisible: true,
          title,
        });
      line(open.entry_price, COLORS.amber, "ENTRY");
      line(open.stop, COLORS.down, "STOP");
      line(open.target, COLORS.up, "TARGET");
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, events, recommendations, showMacro, height]);

  return <div ref={host} className="w-full" style={{ height }} />;
}
