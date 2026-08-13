export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorPoint {
  time: number;
  value: number;
}

export interface BollingerResult {
  upper: IndicatorPoint[];
  middle: IndicatorPoint[];
  lower: IndicatorPoint[];
}

export interface MacdResult {
  line: IndicatorPoint[];
  signal: IndicatorPoint[];
  histogram: (IndicatorPoint & { color: string })[];
}

export interface SRLevel {
  price: number;
  type: "support" | "resistance";
  strength: number;
}

export interface SignalScore {
  overall: "STRONG BUY" | "BUY" | "NEUTRAL" | "SELL" | "STRONG SELL";
  score: number;
  rsi: number | null;
  rsiLabel: string;
  macdCross: "bullish" | "bearish" | "neutral";
  trend: "uptrend" | "downtrend" | "sideways";
  bollingerPos: "near upper" | "near lower" | "middle";
  volumeTrend: "above avg" | "below avg";
  atr: number | null;
  atrPct: number | null;
}

export function sma(closes: number[], period: number, times: number[]): IndicatorPoint[] {
  const result: IndicatorPoint[] = [];
  for (let i = period - 1; i < closes.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    result.push({ time: times[i], value: sum / period });
  }
  return result;
}

export function ema(closes: number[], period: number, times: number[]): IndicatorPoint[] {
  if (closes.length < period) return [];
  const result: IndicatorPoint[] = [];
  const k = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < period; i++) sum += closes[i];
  let prev = sum / period;
  result.push({ time: times[period - 1], value: prev });
  for (let i = period; i < closes.length; i++) {
    prev = closes[i] * k + prev * (1 - k);
    result.push({ time: times[i], value: prev });
  }
  return result;
}

export function bollingerBands(
  closes: number[],
  times: number[],
  period = 20,
  stdDev = 2,
): BollingerResult {
  const upper: IndicatorPoint[] = [];
  const middle: IndicatorPoint[] = [];
  const lower: IndicatorPoint[] = [];
  for (let i = period - 1; i < closes.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    const mean = sum / period;
    let sqSum = 0;
    for (let j = i - period + 1; j <= i; j++) sqSum += (closes[j] - mean) ** 2;
    const sd = Math.sqrt(sqSum / period);
    middle.push({ time: times[i], value: mean });
    upper.push({ time: times[i], value: mean + stdDev * sd });
    lower.push({ time: times[i], value: mean - stdDev * sd });
  }
  return { upper, middle, lower };
}

export function rsi(closes: number[], times: number[], period = 14): IndicatorPoint[] {
  if (closes.length < period + 1) return [];
  const result: IndicatorPoint[] = [];
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    gains.push(delta > 0 ? delta : 0);
    losses.push(delta < 0 ? -delta : 0);
  }
  let avgGain = 0,
    avgLoss = 0;
  for (let i = 0; i < period; i++) {
    avgGain += gains[i];
    avgLoss += losses[i];
  }
  avgGain /= period;
  avgLoss /= period;
  const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  result.push({ time: times[period], value: 100 - 100 / (1 + rs) });
  for (let i = period; i < gains.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period;
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
    const rs2 = avgLoss === 0 ? 100 : avgGain / avgLoss;
    result.push({ time: times[i + 1], value: 100 - 100 / (1 + rs2) });
  }
  return result;
}

export function macd(closes: number[], times: number[]): MacdResult {
  const ema12 = ema(closes, 12, times);
  const ema26 = ema(closes, 26, times);
  const offset = ema26.length > 0 ? times.indexOf(ema26[0].time) : -1;
  if (offset < 0 || ema12.length === 0) return { line: [], signal: [], histogram: [] };

  const macdLine: IndicatorPoint[] = [];
  const e12Map = new Map(ema12.map((p) => [p.time, p.value]));
  for (const p of ema26) {
    const e12 = e12Map.get(p.time);
    if (e12 !== undefined) macdLine.push({ time: p.time, value: e12 - p.value });
  }

  const signalLine = ema(
    macdLine.map((p) => p.value),
    9,
    macdLine.map((p) => p.time),
  );

  const sigMap = new Map(signalLine.map((p) => [p.time, p.value]));
  const histogram: (IndicatorPoint & { color: string })[] = [];
  for (const p of macdLine) {
    const sig = sigMap.get(p.time);
    if (sig !== undefined) {
      const v = p.value - sig;
      histogram.push({ time: p.time, value: v, color: v >= 0 ? "#10b981" : "#ef4444" });
    }
  }

  return { line: macdLine, signal: signalLine, histogram };
}

export function atr(candles: Candle[], period = 14): number[] {
  if (candles.length < period + 1) return [];
  const trs: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const prev = candles[i - 1].close;
    trs.push(
      Math.max(
        candles[i].high - candles[i].low,
        Math.abs(candles[i].high - prev),
        Math.abs(candles[i].low - prev),
      ),
    );
  }
  const result: number[] = [];
  let sum = 0;
  for (let i = 0; i < period; i++) sum += trs[i];
  result.push(sum / period);
  for (let i = period; i < trs.length; i++) {
    result.push((result[result.length - 1] * (period - 1) + trs[i]) / period);
  }
  return result;
}

export function detectSupportResistance(candles: Candle[], lookback = 5): SRLevel[] {
  const levels: SRLevel[] = [];
  const lastPrice = candles[candles.length - 1]?.close ?? 0;
  for (let i = lookback; i < candles.length - lookback; i++) {
    let isHigh = true,
      isLow = true;
    for (let j = 1; j <= lookback; j++) {
      if (candles[i].high <= candles[i - j].high || candles[i].high <= candles[i + j].high)
        isHigh = false;
      if (candles[i].low >= candles[i - j].low || candles[i].low >= candles[i + j].low)
        isLow = false;
    }
    if (isHigh) {
      levels.push({
        price: candles[i].high,
        type: candles[i].high > lastPrice ? "resistance" : "support",
        strength: 1,
      });
    }
    if (isLow) {
      levels.push({
        price: candles[i].low,
        type: candles[i].low < lastPrice ? "support" : "resistance",
        strength: 1,
      });
    }
  }

  const clustered: SRLevel[] = [];
  const threshold = lastPrice * 0.005;
  const used = new Set<number>();
  for (let i = 0; i < levels.length; i++) {
    if (used.has(i)) continue;
    let sum = levels[i].price;
    let count = 1;
    const type = levels[i].type;
    for (let j = i + 1; j < levels.length; j++) {
      if (used.has(j)) continue;
      if (Math.abs(levels[j].price - levels[i].price) < threshold) {
        sum += levels[j].price;
        count++;
        used.add(j);
      }
    }
    used.add(i);
    clustered.push({ price: sum / count, type, strength: count });
  }

  return clustered.sort((a, b) => b.strength - a.strength).slice(0, 6);
}

export function scoreSignals(candles: Candle[]): SignalScore {
  const closes = candles.map((c) => c.close);
  const times = candles.map((c) => c.time);
  const n = closes.length;
  const lastPrice = closes[n - 1] ?? 0;

  const sma20 = sma(closes, 20, times);
  const sma50 = sma(closes, 50, times);
  const rsiData = rsi(closes, times);
  const macdData = macd(closes, times);
  const bb = bollingerBands(closes, times);
  const atrData = atr(candles);

  const lastSma20 = sma20.length > 0 ? sma20[sma20.length - 1].value : null;
  const lastSma50 = sma50.length > 0 ? sma50[sma50.length - 1].value : null;
  const lastRsi = rsiData.length > 0 ? rsiData[rsiData.length - 1].value : null;
  const lastMacd = macdData.line.length > 0 ? macdData.line[macdData.line.length - 1].value : null;
  const lastSignal =
    macdData.signal.length > 0 ? macdData.signal[macdData.signal.length - 1].value : null;
  const lastBBUpper = bb.upper.length > 0 ? bb.upper[bb.upper.length - 1].value : null;
  const lastBBLower = bb.lower.length > 0 ? bb.lower[bb.lower.length - 1].value : null;
  const lastAtr = atrData.length > 0 ? atrData[atrData.length - 1] : null;

  let trend: "uptrend" | "downtrend" | "sideways" = "sideways";
  if (lastSma20 && lastSma50) {
    if (lastPrice > lastSma20 && lastSma20 > lastSma50) trend = "uptrend";
    else if (lastPrice < lastSma20 && lastSma20 < lastSma50) trend = "downtrend";
  }

  let macdCross: "bullish" | "bearish" | "neutral" = "neutral";
  if (lastMacd !== null && lastSignal !== null) {
    macdCross = lastMacd > lastSignal ? "bullish" : lastMacd < lastSignal ? "bearish" : "neutral";
  }

  let rsiLabel = "neutral";
  if (lastRsi !== null) {
    if (lastRsi > 70) rsiLabel = "overbought";
    else if (lastRsi < 30) rsiLabel = "oversold";
    else if (lastRsi > 60) rsiLabel = "strong";
    else if (lastRsi < 40) rsiLabel = "weak";
  }

  let bollingerPos: "near upper" | "near lower" | "middle" = "middle";
  if (lastBBUpper && lastBBLower) {
    const range = lastBBUpper - lastBBLower;
    if (lastPrice > lastBBUpper - range * 0.15) bollingerPos = "near upper";
    else if (lastPrice < lastBBLower + range * 0.15) bollingerPos = "near lower";
  }

  const avgVol =
    candles.slice(-20).reduce((s, c) => s + c.volume, 0) / Math.min(20, candles.length);
  const recentVol =
    candles.slice(-5).reduce((s, c) => s + c.volume, 0) / Math.min(5, candles.length);
  const volumeTrend: "above avg" | "below avg" = recentVol > avgVol ? "above avg" : "below avg";

  let score = 0;
  if (trend === "uptrend") score += 2;
  else if (trend === "downtrend") score -= 2;
  if (macdCross === "bullish") score += 1;
  else if (macdCross === "bearish") score -= 1;
  if (lastRsi !== null) {
    if (lastRsi < 35) score += 1;
    else if (lastRsi > 65) score -= 1;
  }
  if (bollingerPos === "near lower") score += 1;
  else if (bollingerPos === "near upper") score -= 1;
  if (volumeTrend === "above avg" && trend === "uptrend") score += 1;
  else if (volumeTrend === "above avg" && trend === "downtrend") score -= 1;

  let overall: SignalScore["overall"];
  if (score >= 4) overall = "STRONG BUY";
  else if (score >= 2) overall = "BUY";
  else if (score <= -4) overall = "STRONG SELL";
  else if (score <= -2) overall = "SELL";
  else overall = "NEUTRAL";

  return {
    overall,
    score,
    rsi: lastRsi,
    rsiLabel,
    macdCross,
    trend,
    bollingerPos,
    volumeTrend,
    atr: lastAtr,
    atrPct: lastAtr && lastPrice ? (lastAtr / lastPrice) * 100 : null,
  };
}

export function projectCone(
  lastTime: number,
  lastPrice: number,
  atrValue: number,
  direction: number,
  bars: number,
  barIntervalSeconds: number,
): { upper: IndicatorPoint[]; middle: IndicatorPoint[]; lower: IndicatorPoint[] } {
  const upper: IndicatorPoint[] = [];
  const middle: IndicatorPoint[] = [];
  const lower: IndicatorPoint[] = [];
  const bias = direction * atrValue * 0.3;
  for (let i = 0; i <= bars; i++) {
    const t = lastTime + i * barIntervalSeconds;
    const spread = atrValue * Math.sqrt(i) * 0.8;
    const mid = lastPrice + bias * i;
    upper.push({ time: t, value: mid + spread });
    middle.push({ time: t, value: mid });
    lower.push({ time: t, value: mid - spread });
  }
  return { upper, middle, lower };
}

// ── Chart Pattern Detection ──

export type PatternType =
  | "ascending channel"
  | "descending channel"
  | "ascending triangle"
  | "descending triangle"
  | "symmetrical triangle"
  | "rising wedge"
  | "falling wedge"
  | "bull flag"
  | "bear flag";

export interface Trendline {
  startTime: number;
  startPrice: number;
  endTime: number;
  endPrice: number;
  touches: number;
}

export interface ChartPattern {
  type: PatternType;
  upper: Trendline;
  lower: Trendline;
  breakout: "up" | "down" | "either";
  target: number;
  confidence: number;
  startTime: number;
  endTime: number;
}

interface SwingPoint {
  index: number;
  time: number;
  price: number;
  type: "high" | "low";
}

function findSwingPoints(candles: Candle[], lookback = 3): SwingPoint[] {
  const points: SwingPoint[] = [];
  for (let i = lookback; i < candles.length - lookback; i++) {
    let isHigh = true,
      isLow = true;
    for (let j = 1; j <= lookback; j++) {
      if (candles[i].high <= candles[i - j].high || candles[i].high <= candles[i + j].high)
        isHigh = false;
      if (candles[i].low >= candles[i - j].low || candles[i].low >= candles[i + j].low)
        isLow = false;
    }
    if (isHigh)
      points.push({ index: i, time: candles[i].time, price: candles[i].high, type: "high" });
    if (isLow) points.push({ index: i, time: candles[i].time, price: candles[i].low, type: "low" });
  }
  return points;
}

function fitTrendline(points: SwingPoint[], tolerance = 0.005): Trendline | null {
  if (points.length < 2) return null;

  let bestLine: Trendline | null = null;
  let bestTouches = 0;

  for (let i = 0; i < points.length - 1; i++) {
    for (let j = i + 1; j < points.length; j++) {
      const p1 = points[i],
        p2 = points[j];
      if (p2.index === p1.index) continue;
      const slope = (p2.price - p1.price) / (p2.index - p1.index);

      let touches = 0;
      let firstTouch = p1,
        lastTouch = p2;
      for (const p of points) {
        if (p.type !== p1.type) continue;
        const expected = p1.price + slope * (p.index - p1.index);
        if (expected !== 0 && Math.abs(p.price - expected) / expected < tolerance) {
          touches++;
          if (p.index < firstTouch.index) firstTouch = p;
          if (p.index > lastTouch.index) lastTouch = p;
        }
      }

      if (touches >= 2 && touches > bestTouches) {
        bestTouches = touches;
        bestLine = {
          startTime: firstTouch.time,
          startPrice: firstTouch.price,
          endTime: lastTouch.time,
          endPrice: lastTouch.price,
          touches,
        };
      }
    }
  }

  return bestLine;
}

function classifyPattern(
  upper: Trendline,
  lower: Trendline,
  candles: Candle[],
): ChartPattern | null {
  const duration = upper.endTime - upper.startTime;
  if (duration <= 0) return null;

  const upperSlope = (upper.endPrice - upper.startPrice) / duration;
  const lowerSlope = (lower.endPrice - lower.startPrice) / duration;
  const avgPrice = (upper.startPrice + upper.endPrice + lower.startPrice + lower.endPrice) / 4;
  const normalizedUpper = (upperSlope / avgPrice) * duration;
  const normalizedLower = (lowerSlope / avgPrice) * duration;

  const startWidth = (upper.startPrice - lower.startPrice) / avgPrice;
  const endWidth = (upper.endPrice - lower.endPrice) / avgPrice;
  const widthChange = endWidth - startWidth;

  const threshold = 0.002;
  const upperFlat = Math.abs(normalizedUpper) < threshold;
  const lowerFlat = Math.abs(normalizedLower) < threshold;

  let type: PatternType;
  let breakout: "up" | "down" | "either";
  let confidence: number;

  const prePattern = candles.slice(
    Math.max(0, candles.length - 60),
    Math.max(0, candles.length - 30),
  );
  const preReturn =
    prePattern.length > 1
      ? (prePattern[prePattern.length - 1].close - prePattern[0].close) / prePattern[0].close
      : 0;
  const isStrongPriorMove = Math.abs(preReturn) > 0.05;

  if (widthChange < -0.01) {
    if (normalizedUpper > threshold && normalizedLower > threshold) {
      type = "rising wedge";
      breakout = "down";
      confidence = Math.min(0.8, 0.4 + Math.abs(widthChange) * 5);
    } else if (normalizedUpper < -threshold && normalizedLower < -threshold) {
      type = "falling wedge";
      breakout = "up";
      confidence = Math.min(0.8, 0.4 + Math.abs(widthChange) * 5);
    } else if (upperFlat && normalizedLower > threshold) {
      type = "ascending triangle";
      breakout = "up";
      confidence = Math.min(0.75, 0.45 + upper.touches * 0.1);
    } else if (lowerFlat && normalizedUpper < -threshold) {
      type = "descending triangle";
      breakout = "down";
      confidence = Math.min(0.75, 0.45 + lower.touches * 0.1);
    } else {
      type = "symmetrical triangle";
      breakout = "either";
      confidence = Math.min(0.6, 0.3 + Math.abs(widthChange) * 4);
    }
  } else if (Math.abs(widthChange) < 0.01 && Math.abs(normalizedUpper) > threshold) {
    if (isStrongPriorMove && preReturn > 0) {
      type = "bull flag";
      breakout = "up";
      confidence = Math.min(0.7, 0.5 + Math.abs(preReturn));
    } else if (isStrongPriorMove && preReturn < 0) {
      type = "bear flag";
      breakout = "down";
      confidence = Math.min(0.7, 0.5 + Math.abs(preReturn));
    } else if (normalizedUpper > 0) {
      type = "ascending channel";
      breakout = "up";
      confidence = 0.55;
    } else {
      type = "descending channel";
      breakout = "down";
      confidence = 0.55;
    }
  } else {
    return null;
  }

  const patternHeight = Math.abs(upper.startPrice - lower.startPrice);
  const lastPrice = candles[candles.length - 1].close;
  let target: number;
  if (breakout === "up") {
    target = upper.endPrice + patternHeight;
  } else if (breakout === "down") {
    target = lower.endPrice - patternHeight;
  } else {
    target = lastPrice;
  }

  const avgTouches = (upper.touches + lower.touches) / 2;
  confidence = Math.min(0.9, confidence + (avgTouches - 2) * 0.05);

  return {
    type,
    upper,
    lower,
    breakout,
    target,
    confidence,
    startTime: upper.startTime,
    endTime: upper.endTime,
  };
}

export function detectPatterns(candles: Candle[]): ChartPattern[] {
  if (candles.length < 20) return [];

  const allSwings = findSwingPoints(candles, 3);
  const highs = allSwings.filter((p) => p.type === "high");
  const lows = allSwings.filter((p) => p.type === "low");

  const cutoff = candles[Math.floor(candles.length * 0.6)]?.time ?? 0;
  const recentHighs = highs.filter((p) => p.time >= cutoff);
  const recentLows = lows.filter((p) => p.time >= cutoff);

  if (recentHighs.length < 2 || recentLows.length < 2) return [];

  const upperLine = fitTrendline(recentHighs);
  const lowerLine = fitTrendline(recentLows);

  if (!upperLine || !lowerLine) return [];

  const pattern = classifyPattern(upperLine, lowerLine, candles);
  return pattern ? [pattern] : [];
}
