import { useQuery } from "@tanstack/react-query";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useTheme } from "@/lib/theme";

import { chartPalette } from "./palette";

import { Empty, Loading } from "@/features/shell/ui";
import { api } from "@/lib/api";
import type { IntradaySpan, Recommendation } from "@/lib/types";

/** lightweight-charts draws UTC; shift so the axis reads in the viewer's local time. */
const local = (t: number) => (t - new Date(t * 1000).getTimezoneOffset() * 60) as UTCTimestamp;

/**
 * Intraday candles (pre/after-market included) that update in place: refetched every 20s
 * and whenever the live stream reports a new quote, without resetting zoom or scroll.
 */
export default function IntradayChart({
  instrumentId,
  span,
  recommendations,
  height = 420,
}: {
  instrumentId: string;
  span: IntradaySpan;
  recommendations: Recommendation[];
  height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  const chart = useRef<IChartApi | null>(null);
  const candles = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const fitted = useRef(false);
  const query = useQuery({
    queryKey: ["intraday", instrumentId, span],
    queryFn: () => api.intraday(instrumentId, span),
    refetchInterval: 20_000,
  });
  const bars = query.data?.bars;
  const hasBars = Boolean(bars?.length);
  // Primitive deps: the asset query refetches often, which must not rebuild the chart.
  const openRec = recommendations.find((rec) => rec.status === "open");
  const [entry, stop, target] = [openRec?.entry_price, openRec?.stop, openRec?.target];

  useEffect(() => {
    if (!host.current || !hasBars) return;
    const COLORS = chartPalette();
    const instance = createChart(host.current, {
      height,
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor: COLORS.text,
        fontFamily: "JetBrains Mono",
        fontSize: 10,
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: { borderColor: COLORS.border, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    candles.current = instance.addSeries(CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderUpColor: COLORS.up,
      borderDownColor: COLORS.down,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
    });
    volume.current = instance.addSeries(HistogramSeries, {
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
      color: COLORS.volume,
    });
    instance.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    if (entry != null && stop != null && target != null) {
      const line = (price: number, color: string, title: string) =>
        candles.current?.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title,
        });
      line(entry, COLORS.amber, "ENTRY");
      line(stop, COLORS.down, "STOP");
      line(target, COLORS.up, "TARGET");
    }
    chart.current = instance;
    fitted.current = false;
    return () => {
      instance.remove();
      chart.current = candles.current = volume.current = null;
    };
  }, [hasBars, instrumentId, span, entry, stop, target, height, theme]);

  useEffect(() => {
    if (!bars?.length || !candles.current || !volume.current) return;
    const COLORS = chartPalette();
    const rows = bars.filter((bar) => bar.c != null);
    candles.current.setData(
      rows.map((bar) => ({
        time: local(bar.t),
        open: bar.o ?? bar.c!,
        high: bar.h ?? bar.c!,
        low: bar.l ?? bar.c!,
        close: bar.c!,
      })),
    );
    volume.current.setData(
      rows.map((bar) => ({
        time: local(bar.t),
        value: bar.v ?? 0,
        color: (bar.c ?? 0) >= (bar.o ?? 0) ? COLORS.upSoft : COLORS.downSoft,
      })),
    );
    if (!fitted.current) {
      chart.current?.timeScale().fitContent();
      fitted.current = true;
    }
  }, [bars, theme]);

  if (query.isLoading) return <Loading />;
  if (!hasBars) return <Empty title="No intraday data for this market right now" />;
  return <div ref={host} className="w-full" style={{ height }} />;
}
