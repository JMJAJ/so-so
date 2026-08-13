import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  LineStyle,
  createChart,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/terminal-api";
import type { Position, Proposal } from "@/lib/terminal-types";

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface PositionChartProps {
  position: Position;
  proposal?: Proposal;
}

export default function PositionChart({ position, proposal }: PositionChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCandles([]);
    api<{ ohlcv: Candle[] }>(
      `/trade-ideas/ohlcv?symbol=${encodeURIComponent(position.instrument_id ?? position.pair)}&period=60d&interval=1h`,
      undefined,
      controller.signal,
    )
      .then((result) => {
        setCandles(result.ohlcv);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === "AbortError") return;
        setError(requestError instanceof Error ? requestError.message : "History unavailable");
      });
    return () => controller.abort();
  }, [position.instrument_id, position.pair]);

  useEffect(() => {
    if (!host.current || !candles.length) return;
    const chart = createChart(host.current, {
      height: 440,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0b0b" },
        textColor: "#8b8b82",
        fontFamily: "JetBrains Mono",
        fontSize: 10,
      },
      grid: { vertLines: { color: "#20201e" }, horzLines: { color: "#20201e" } },
      rightPriceScale: { borderColor: "#292925" },
      timeScale: { borderColor: "#292925", timeVisible: true, secondsVisible: false },
    });
    const price = chart.addSeries(CandlestickSeries, {
      upColor: "#27c977",
      downColor: "#ef4758",
      borderUpColor: "#27c977",
      borderDownColor: "#ef4758",
      wickUpColor: "#27c977",
      wickDownColor: "#ef4758",
    });
    price.setData(
      candles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    price.createPriceLine({
      price: position.entry_price,
      color: "#f3b61f",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "ENTRY",
    });
    price.createPriceLine({
      price: position.current_price,
      color: "#d9d9d4",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "MARK",
    });
    if (position.stop_loss != null) {
      price.createPriceLine({
        price: position.stop_loss,
        color: "#ef4758",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "STOP",
      });
    }
    if (position.take_profit != null) {
      price.createPriceLine({
        price: position.take_profit,
        color: "#27c977",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: "TARGET",
      });
    }
    if (proposal?.take_profit != null) {
      const last = candles.at(-1);
      const previous = candles.at(-2);
      if (last) {
        const step = Math.max(3600, last.time - (previous?.time ?? last.time - 3600));
        const scenario = chart.addSeries(LineSeries, {
          color: "#f3b61f",
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          crosshairMarkerVisible: false,
          lastValueVisible: false,
          priceLineVisible: false,
          title: "AI SCENARIO",
        });
        scenario.setData([
          { time: last.time as UTCTimestamp, value: position.current_price },
          {
            time: (last.time + step * 10) as UTCTimestamp,
            value: proposal.take_profit,
          },
        ]);
      }
    }
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(([entry]) => {
      if (entry) chart.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles, position, proposal]);

  if (error) {
    return (
      <div className="flex h-[440px] items-center justify-center p-6 text-center text-xs text-bear">
        {error}
      </div>
    );
  }
  if (!candles.length) {
    return (
      <div className="flex h-[440px] items-center justify-center text-xs text-muted-foreground">
        Loading price history...
      </div>
    );
  }
  return (
    <div ref={host} className="h-[440px] w-full" aria-label={`${position.pair} position chart`} />
  );
}
