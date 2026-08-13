"""
Training data generator — backtests historical OHLCV data to produce
labeled instruction/response pairs for LoRA fine-tuning.

Usage:
    cd server
    python training_data.py                    # generates training_data.jsonl
    python training_data.py --symbols 20       # limit symbols for testing
    python training_data.py --period 2y        # use 2 years of data

Output: training_data.jsonl (one JSON object per line, ready for fine-tuning)
"""

import json
import time
import sys
import os
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

from prices import pair_to_yfinance
from agent import WATCHLIST
import context as ctx


def compute_technicals_at(df: pd.DataFrame, idx: int) -> dict | None:
    """Compute technical indicators at a specific bar index using all prior data."""
    if idx < 50:
        return None

    subset = df.iloc[:idx + 1]
    close = subset["Close"]
    high = subset["High"]
    low = subset["Low"]
    price = float(close.iloc[-1])

    if pd.isna(price) or price <= 0:
        return None

    # SMA
    sma20 = float(close.iloc[-20:].mean()) if len(close) >= 20 else None
    sma50 = float(close.iloc[-50:].mean()) if len(close) >= 50 else None

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.iloc[-14:].mean() if len(gain) >= 14 else None
    avg_loss = loss.iloc[-14:].mean() if len(loss) >= 14 else None
    rsi_val = None
    if avg_gain is not None and avg_loss is not None and avg_loss > 0:
        rs = avg_gain / avg_loss
        rsi_val = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_val = float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else None
    macd_sig = float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else None

    # ATR
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_val = float(tr.iloc[-14:].mean()) if len(tr) >= 14 else None

    # Trend
    trend = "sideways"
    if sma20 and sma50:
        if price > sma20 > sma50:
            trend = "uptrend"
        elif price < sma20 < sma50:
            trend = "downtrend"

    # Returns
    n = len(close)
    ret_1w = ((price / float(close.iloc[-6])) - 1) * 100 if n >= 6 else None
    ret_1m = ((price / float(close.iloc[-22])) - 1) * 100 if n >= 22 else None

    # MACD cross
    macd_cross = "neutral"
    if macd_val is not None and macd_sig is not None:
        macd_cross = "bullish" if macd_val > macd_sig else "bearish"

    atr_pct = (atr_val / price * 100) if atr_val and price else None

    return {
        "price": price,
        "sma20": sma20,
        "sma50": sma50,
        "rsi": rsi_val,
        "macd": macd_val,
        "macd_signal": macd_sig,
        "macd_cross": macd_cross,
        "atr": atr_val,
        "atr_pct": atr_pct,
        "trend": trend,
        "ret_1w": ret_1w,
        "ret_1m": ret_1m,
    }


def simulate_trade(df: pd.DataFrame, entry_idx: int, side: str, atr_val: float, sl_mult: float = 1.5, tp_mult: float = 3.0) -> dict | None:
    """Simulate a trade from entry_idx forward. Returns outcome including timeouts."""
    entry_price = float(df["Close"].iloc[entry_idx])
    direction = 1 if side == "long" else -1

    if side == "long":
        sl = entry_price - (atr_val * sl_mult)
        tp = entry_price + (atr_val * tp_mult)
    else:
        sl = entry_price + (atr_val * sl_mult)
        tp = entry_price - (atr_val * tp_mult)

    # Walk forward to find SL or TP hit
    max_bars = 60
    for j in range(entry_idx + 1, min(entry_idx + max_bars, len(df))):
        bar_high = float(df["High"].iloc[j])
        bar_low = float(df["Low"].iloc[j])

        if side == "long":
            if bar_low <= sl:
                pnl_pct = ((sl - entry_price) / entry_price) * 100
                return {"side": side, "entry": entry_price, "exit": sl, "pnl_pct": pnl_pct, "outcome": "loss", "bars_held": j - entry_idx}
            if bar_high >= tp:
                pnl_pct = ((tp - entry_price) / entry_price) * 100
                return {"side": side, "entry": entry_price, "exit": tp, "pnl_pct": pnl_pct, "outcome": "win", "bars_held": j - entry_idx}
        else:
            if bar_high >= sl:
                pnl_pct = ((entry_price - sl) / entry_price) * 100
                return {"side": side, "entry": entry_price, "exit": sl, "pnl_pct": pnl_pct, "outcome": "loss", "bars_held": j - entry_idx}
            if bar_low <= tp:
                pnl_pct = ((entry_price - tp) / entry_price) * 100
                return {"side": side, "entry": entry_price, "exit": tp, "pnl_pct": pnl_pct, "outcome": "win", "bars_held": j - entry_idx}

    # Timeout — trade didn't hit SL or TP within window
    exit_price = float(df["Close"].iloc[min(entry_idx + max_bars - 1, len(df) - 1)])
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100 * direction
    return {"side": side, "entry": entry_price, "exit": exit_price, "pnl_pct": pnl_pct, "outcome": "timeout", "bars_held": max_bars}


def format_context(symbol: str, asset_class: str, tech: dict, date_str: str) -> str:
    """Format technical data into the same context string the agent sees."""
    parts = [f"=== {symbol} ({asset_class}) — {date_str} ==="]
    parts.append(f"  Price: ${tech['price']:.4f}" if tech["price"] < 1000 else f"  Price: ${tech['price']:,.2f}")

    if tech["trend"] != "sideways":
        parts.append(f"  Trend: {tech['trend']}")
    if tech["rsi"] is not None:
        rsi_label = ""
        if tech["rsi"] > 70:
            rsi_label = " OVERBOUGHT"
        elif tech["rsi"] < 30:
            rsi_label = " OVERSOLD"
        parts.append(f"  RSI: {tech['rsi']:.0f}{rsi_label}")
    if tech["macd_cross"] != "neutral":
        parts.append(f"  MACD: {tech['macd_cross']}")
    if tech["ret_1w"] is not None:
        parts.append(f"  1w return: {tech['ret_1w']:+.1f}%")
    if tech["ret_1m"] is not None:
        parts.append(f"  1m return: {tech['ret_1m']:+.1f}%")
    if tech["atr_pct"] is not None:
        parts.append(f"  ATR: {tech['atr_pct']:.1f}%")
    if tech["sma20"]:
        parts.append(f"  {'Above' if tech['price'] > tech['sma20'] else 'Below'} SMA20 ({tech['sma20']:.2f})")
    if tech["sma50"]:
        parts.append(f"  {'Above' if tech['price'] > tech['sma50'] else 'Below'} SMA50 ({tech['sma50']:.2f})")

    return "\n".join(parts)


def format_decision(side: str, size: float, confidence: float, sl: float, tp: float, symbol: str, asset_class: str, reason: str) -> str:
    """Format a trade decision as the JSON the model should output."""
    return json.dumps({
        "reasoning": reason,
        "decisions": [{
            "action": "open",
            "symbol": symbol,
            "asset_class": asset_class,
            "side": side,
            "size": size,
            "confidence": confidence,
            "stop_loss": round(sl, 4),
            "take_profit": round(tp, 4),
        }]
    })


def generate_reason(tech: dict, side: str, outcome: str) -> str:
    """Generate a human-readable reason matching what the AI would write."""
    reasons = []
    if side == "long":
        if tech["trend"] == "uptrend":
            reasons.append("price in uptrend above SMA20 and SMA50")
        if tech["macd_cross"] == "bullish":
            reasons.append("MACD bullish crossover")
        if tech["rsi"] and tech["rsi"] < 40:
            reasons.append(f"RSI oversold at {tech['rsi']:.0f}")
        if tech["ret_1w"] and tech["ret_1w"] > 1:
            reasons.append(f"strong 1w momentum ({tech['ret_1w']:+.1f}%)")
    else:
        if tech["trend"] == "downtrend":
            reasons.append("price in downtrend below SMA20 and SMA50")
        if tech["macd_cross"] == "bearish":
            reasons.append("MACD bearish crossover")
        if tech["rsi"] and tech["rsi"] > 60:
            reasons.append(f"RSI overbought at {tech['rsi']:.0f}")
        if tech["ret_1w"] and tech["ret_1w"] < -1:
            reasons.append(f"weak 1w momentum ({tech['ret_1w']:+.1f}%)")

    if not reasons:
        reasons.append(f"technical alignment for {side} entry")

    return "; ".join(reasons)


def score_entry(tech: dict, side: str) -> float:
    """Score an entry the same way the agent does — only keep entries with score >= 2."""
    score = 0
    if side == "long":
        if tech["ret_1m"] is not None and tech["ret_1m"] > 1:
            score += 2
        if tech["trend"] == "uptrend":
            score += 1
        if tech["rsi"] is not None and 40 < tech["rsi"] < 70:
            score += 1
        if tech["atr_pct"] and tech["atr_pct"] > 1:
            score += 1
    else:
        if tech["ret_1m"] is not None and tech["ret_1m"] < -1:
            score += 2
        if tech["trend"] == "downtrend":
            score += 1
        if tech["rsi"] is not None and 30 < tech["rsi"] < 60:
            score += 1
        if tech["atr_pct"] and tech["atr_pct"] > 1:
            score += 1
    return score


def main():
    parser = argparse.ArgumentParser(description="Generate training data from historical backtests")
    parser.add_argument("--symbols", type=int, default=0, help="Limit number of symbols (0 = all)")
    parser.add_argument("--period", type=str, default="2y", help="Historical period (1y, 2y, 5y, max)")
    parser.add_argument("--output", type=str, default="training_data.jsonl", help="Output file")
    parser.add_argument("--min-score", type=int, default=2, help="Minimum signal score to include")
    args = parser.parse_args()

    symbols = WATCHLIST
    if args.symbols > 0:
        symbols = symbols[:args.symbols]

    print(f"Generating training data from {len(symbols)} symbols, period={args.period}")
    print(f"Output: {args.output}")

    system_prompt = """You are a trading agent that analyzes technical data and outputs trade decisions in JSON format.
You receive technical indicators and market context, then output a structured decision with entry, stop loss, take profit, and confidence.
Only output trades with strong technical justification (score >= 2)."""

    total_examples = 0
    wins = 0
    losses = 0

    with open(args.output, "w") as f:
        for sym_idx, (symbol, asset_class) in enumerate(symbols):
            yf_sym = pair_to_yfinance(symbol)
            print(f"\n[{sym_idx + 1}/{len(symbols)}] {symbol} ({asset_class})...", end=" ", flush=True)

            try:
                df = yf.download(yf_sym, period=args.period, interval="1d", auto_adjust=True, progress=False)
                if df is None or df.empty or len(df) < 60:
                    print("skipped (insufficient data)")
                    continue

                # Handle MultiIndex
                if isinstance(df.columns, pd.MultiIndex):
                    if yf_sym in df.columns.get_level_values(0):
                        df = df[yf_sym]
                    elif yf_sym in df.columns.get_level_values(1):
                        df = df.xs(yf_sym, level=1, axis=1)
                    else:
                        try:
                            df = df.droplevel(1, axis=1)
                        except Exception:
                            print("skipped (column error)")
                            continue

                df = df.dropna(subset=["Close"])
                if len(df) < 60:
                    print(f"skipped ({len(df)} bars)")
                    continue

                sym_examples = 0
                sym_wins = 0

                # Walk through bars starting from index 50 (need history for indicators)
                for i in range(50, len(df) - 60, 5):  # Step by 5 to reduce overlap
                    tech = compute_technicals_at(df, i)
                    if tech is None or tech["atr"] is None or tech["atr"] <= 0:
                        continue

                    for side in ["long", "short"]:
                        score = score_entry(tech, side)
                        date_str = str(df.index[i])[:10]
                        context_text = format_context(symbol, asset_class, tech, date_str)

                        if score < args.min_score:
                            # Weak signal — teach the model to SKIP
                            skip_decision = json.dumps({
                                "reasoning": generate_reason(tech, side, "skip") + f"; signal score {score}/2 too weak, skipping",
                                "decisions": [{"action": "skip", "symbol": symbol, "reason": f"weak {side} signal (score {score})"}]
                            })
                            example = {
                                "messages": [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": context_text},
                                    {"role": "assistant", "content": skip_decision},
                                ]
                            }
                            f.write(json.dumps(example) + "\n")
                            sym_examples += 1
                            total_examples += 1
                            continue

                        # Strong signal — simulate the trade
                        result = simulate_trade(df, i, side, tech["atr"], sl_mult=1.5, tp_mult=3.0)
                        if result is None:
                            continue

                        sl = result["entry"] - (tech["atr"] * 1.5 * (1 if side == "long" else -1))
                        tp = result["entry"] + (tech["atr"] * 3.0 * (1 if side == "long" else -1))
                        confidence = min(0.95, 0.5 + score * 0.1)
                        reason = generate_reason(tech, side, result["outcome"])
                        decision = format_decision(side, 1.0, confidence, sl, tp, symbol, asset_class, reason)

                        example = {
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": context_text},
                                {"role": "assistant", "content": decision},
                            ]
                        }

                        f.write(json.dumps(example) + "\n")
                        sym_examples += 1
                        total_examples += 1
                        if result["outcome"] == "win":
                            wins += 1
                            sym_wins += 1
                        else:
                            losses += 1

                win_rate = (sym_wins / sym_examples * 100) if sym_examples > 0 else 0
                print(f"{sym_examples} examples ({win_rate:.0f}% win rate)")

            except Exception as e:
                print(f"error: {e}")
                continue

            time.sleep(0.5)  # Rate limit courtesy

    total = wins + losses
    print(f"\n{'='*50}")
    print(f"Total training examples: {total_examples}")
    print(f"Win rate in training data: {(wins / total * 100):.1f}% ({wins}W / {losses}L)")
    print(f"Output: {args.output}")
    print(f"File size: {os.path.getsize(args.output) / 1024:.1f} KB")
    print(f"\nTo fine-tune with unsloth:")
    print(f"  pip install unsloth")
    print(f"  # See: https://github.com/unslothai/unsloth")
    print(f"  # Load {args.output} as your training dataset")


if __name__ == "__main__":
    main()
