import { CandlestickSeries, ColorType, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/terminal-api";
import type { TradeIdea } from "@/lib/terminal-types";

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export default function ResearchChart({ idea }: { idea: TradeIdea }) {
  const host = useRef<HTMLDivElement>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api<{ ohlcv: Candle[] }>(
      `/trade-ideas/ohlcv?symbol=${encodeURIComponent(idea.instrument_id ?? idea.symbol)}&period=auto&interval=1h`,
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
  }, [idea.instrument_id, idea.symbol]);

  useEffect(() => {
    if (!host.current || !candles.length) return;
    const chart = createChart(host.current, {
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "#0b0b0b" },
        textColor: "#8b8b82",
        fontFamily: "JetBrains Mono",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "#20201e" },
        horzLines: { color: "#20201e" },
      },
      rightPriceScale: { borderColor: "#292925" },
      timeScale: { borderColor: "#292925", timeVisible: true },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#27c977",
      downColor: "#ef4758",
      borderUpColor: "#27c977",
      borderDownColor: "#ef4758",
      wickUpColor: "#27c977",
      wickDownColor: "#ef4758",
    });
    series.setData(
      candles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    if (idea.stop_loss != null) {
      series.createPriceLine({
        price: idea.stop_loss,
        color: "#ef4758",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "LEGACY SL",
      });
    }
    if (idea.take_profit != null) {
      series.createPriceLine({
        price: idea.take_profit,
        color: "#27c977",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "LEGACY TP",
      });
    }
    series.createPriceLine({
      price: idea.entry_price,
      color: "#f3b61f",
      lineWidth: 1,
      lineStyle: 1,
      axisLabelVisible: true,
      title: "LEGACY ENTRY",
    });
    chart.timeScale().fitContent();
    const observer = new ResizeObserver(([entry]) => {
      if (entry) chart.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles, idea.entry_price, idea.stop_loss, idea.take_profit]);

  return (
    <div>
      {error ? (
        <div className="flex h-[420px] items-center justify-center p-6 text-center text-xs text-bear">
          {error}
        </div>
      ) : (
        <div ref={host} className="h-[420px] w-full" />
      )}
      <div className="border-t border-border p-4">
        <div className="text-[9px] font-bold uppercase tracking-[0.18em] text-primary">
          Historical note
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {idea.reasoning || "No reasoning was recorded."} This setup is preserved for audit and
          does not bypass the v2 proposal or risk workflow.
        </p>
      </div>
    </div>
  );
}
