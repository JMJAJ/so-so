"""Point-in-time replay of the evidence policy: a track record without waiting months.

For every past event, act as the live system would have on that day, using only data
available then:
  1. Event history known before the event: earlier occurrences whose outcome had
     already played out (date + horizon < today). It counts as reliable when n >= 8,
     |t| >= 3 (a stricter bar standing in for the false-discovery correction, which
     can't be recomputed cheaply at every date) and both halves agree in sign.
  2. If reliable, take the trade in the effect's direction with a standard bracket
     (stop 2 x ATR14, target 3 x ATR14) and the live probability formula: bracket base
     rate from the prior three years plus the shrunk event hit rate.
  3. Play the bracket forward on the real daily highs and lows and record the outcome.

This tests the evidence engine (event studies + probability formula), not the LLM's
judgement on top of it. Results also feed `probability.calibration_factor`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data, db, universe
from ..taxonomy import EVENT_TYPES
from .features import abnormal_forward, rolling_betas
from .probability import event_component, simulate_bracket

MIN_PRIOR = 8
MIN_T = 3.0
BASE_YEARS = 3


def _atr_pct(frame: pd.DataFrame, pos: int) -> float | None:
    window = frame.iloc[max(0, pos - 14):pos + 1]
    if len(window) < 10:
        return None
    prev = window["close"].shift(1)
    tr = pd.concat([window["high"] - window["low"], (window["high"] - prev).abs(), (window["low"] - prev).abs()],
                   axis=1).max(axis=1)
    atr = float(tr.mean())
    price = float(window["close"].iloc[-1])
    return atr / price if price else None


def _prior_stats(outcomes: np.ndarray) -> dict | None:
    n = len(outcomes)
    if n < MIN_PRIOR:
        return None
    mean, sd = float(outcomes.mean()), float(outcomes.std(ddof=1))
    t = mean / (sd / np.sqrt(n)) if sd > 0 else 0.0
    half = n // 2
    early, late = outcomes[:half].mean(), outcomes[half:].mean()
    stable = np.sign(early) == np.sign(mean) == np.sign(late) and mean != 0
    return {"n": n, "mean": mean, "t": float(t), "hit": float((outcomes > 0).mean()), "stable": bool(stable)}


def run(horizon: int = 20, progress=None) -> dict:
    closes = data.closes()
    events = data.events_frame()
    if closes.empty or events.empty:
        return {"calls": 0}
    bench = {item.id: item.benchmark_id for item in universe.INSTRUMENTS}
    abn = abnormal_forward(closes, horizon, bench, rolling_betas(closes, bench))
    calendar = closes.index
    tradable = [item.id for item in universe.tradable() if item.id in abn]
    frames = {iid: data.ohlcv(iid) for iid in tradable}
    calls: list[tuple] = []

    for event_type, group in events.groupby("type"):
        if progress:
            progress(f"replay {event_type}")
        scope = EVENT_TYPES.get(event_type, {}).get("scope", "macro")
        pairs = ([(iid, rows["date"]) for iid, rows in group.groupby("instrument_id") if iid in abn]
                 if scope == "asset" else [(iid, group["date"].drop_duplicates()) for iid in tradable])
        for iid, dates in pairs:
            frame = frames.get(iid)
            if frame is None or len(frame) < 300:
                continue
            positions = np.sort(calendar.searchsorted(pd.DatetimeIndex(dates)))
            positions = positions[positions < len(calendar)]
            column = abn[iid].to_numpy()
            outcomes = np.array([column[p] for p in positions])
            for k, pos in enumerate(positions):
                known = [j for j in range(k) if positions[j] + horizon < pos and not np.isnan(outcomes[j])]
                stats = _prior_stats(outcomes[known]) if known else None
                if not stats or not stats["stable"] or abs(stats["t"]) < MIN_T:
                    continue
                day = calendar[pos]
                fpos = int(frame.index.searchsorted(day))
                if fpos + horizon >= len(frame):
                    continue
                atr = _atr_pct(frame, fpos)
                if not atr:
                    continue
                direction = "long" if stats["mean"] > 0 else "short"
                stop_pct, target_pct = 2 * atr, 3 * atr
                start = int(frame.index.searchsorted(day - pd.Timedelta(days=365 * BASE_YEARS)))
                base = simulate_bracket(frame.iloc[start:], direction, horizon, stop_pct, target_pct,
                                        end=fpos - start - horizon)["p_win"]
                p_event = event_component(stats["hit"], stats["n"], direction, stats["mean"])
                probability = float(np.clip(base + (p_event - 0.5), 0.2, 0.85))
                realized = _single_path(frame, fpos, direction, horizon, stop_pct, target_pct)
                calls.append((day.date().isoformat(), iid, direction, event_type, horizon, probability,
                              base, realized, int(realized > 0)))

    with db.session() as conn:
        conn.execute("DELETE FROM replay_calls")
        conn.executemany(
            """INSERT INTO replay_calls(date,instrument_id,direction,event_type,horizon,probability,base,
               realized_return,win) VALUES(?,?,?,?,?,?,?,?,?)""",
            calls,
        )
    return summary()


def _single_path(frame: pd.DataFrame, pos: int, direction: str, horizon: int, stop_pct: float,
                 target_pct: float) -> float:
    entry = float(frame["close"].iloc[pos])
    long = direction == "long"
    stop = entry * (1 - stop_pct) if long else entry * (1 + stop_pct)
    target = entry * (1 + target_pct) if long else entry * (1 - target_pct)
    exit_price = float(frame["close"].iloc[pos + horizon])
    for j in range(pos + 1, pos + horizon + 1):
        row = frame.iloc[j]
        low, high = row["low"], row["high"]
        open_ = row["open"] if not pd.isna(row["open"]) else row["close"]
        if long and low <= stop:
            exit_price = min(open_, stop)
            break
        if long and high >= target:
            exit_price = max(open_, target)
            break
        if not long and high >= stop:
            exit_price = max(open_, stop)
            break
        if not long and low <= target:
            exit_price = min(open_, target)
            break
    raw = exit_price / entry - 1
    return raw if long else -raw


def summary() -> dict:
    rows = db.rows("SELECT * FROM replay_calls ORDER BY date")
    if not rows:
        return {"calls": 0}
    frame = pd.DataFrame(rows)
    buckets = []
    for low, high in ((0.2, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 0.85)):
        part = frame[(frame["probability"] >= low) & (frame["probability"] < high)]
        if len(part):
            buckets.append({"bucket": f"{low:.2f}–{high:.2f}", "n": int(len(part)),
                            "stated": float(part["probability"].mean()), "realized": float(part["win"].mean())})
    by_type = (frame.groupby("event_type")
               .agg(n=("win", "size"), hit_rate=("win", "mean"), avg_return=("realized_return", "mean"))
               .reset_index().sort_values("n", ascending=False))
    returns = frame["realized_return"]
    return {
        "calls": int(len(frame)),
        "period": [frame["date"].min(), frame["date"].max()],
        "hit_rate": float(frame["win"].mean()),
        "avg_return": float(returns.mean()),
        "t_stat": float(returns.mean() / (returns.std(ddof=1) / np.sqrt(len(returns)))) if len(returns) > 1 else None,
        "avg_probability": float(frame["probability"].mean()),
        "avg_base": float(frame["base"].mean()) if frame["base"].notna().any() else None,
        "brier": float(((frame["probability"] - frame["win"]) ** 2).mean()),
        "calibration": buckets,
        "by_event_type": by_type.to_dict("records"),
    }
