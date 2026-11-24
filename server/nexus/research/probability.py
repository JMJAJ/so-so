"""Probabilities and expected value computed from evidence, not stated by the LLM.

A call is scored on its own path: it wins if it exits (stop, target or horizon) with a
profit. So its base rate is a *bracket simulation*: replay the same stop and target
distances from every past entry day in the asset's history and count how often the
trade made money, plus the average win and loss.

  base      bracket simulation on the asset's daily highs and lows (last 10 years). When the
            asset moved >= 2σ today or yesterday, the bracket is also replayed from past shock
            days only and blended in by n / (n + 20): the base rate of the situation you trade in.
  shock     a reliable continuation/reversal after past shocks (research/reaction.py) counts as
            evidence like a reliable event effect.
            Single stocks first have their excess drift over the S&P 500 removed: the
            universe is today's large caps (survivors), so their raw history overstates
            how often buying them worked.
  events    reliable event effects active in the last 10 days (FDR-corrected, stable):
            their hit rate, shrunk toward 50% by n / (n + 20), shifts the base.
  model     the quant model's calibrated prob_up, only where walk-forward found an edge.
  calibrate p is pulled toward 50% by how well past probabilities matched outcomes:
            the live track record once 20 calls have closed, else the point-in-time replay.
  value     EV = p × avg win − (1 − p) × avg loss. A call needs EV > 0 to be recorded.
Analogs and news stay context for the LLM: neither has a validated track record yet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data, db, universe
from . import event_study, reaction

SHRINK = 20
MIN_CALIBRATION_N = 20
P_MIN, P_MAX = 0.20, 0.85
HISTORY_DAYS = 365 * 10
STEP = 3


def nearest_horizon(days: int) -> int:
    return min(event_study.HORIZONS[1:], key=lambda h: abs(h - days))


def _ohlc(item: universe.Instrument) -> tuple[pd.DataFrame, str]:
    start = (pd.Timestamp.today() - pd.Timedelta(days=HISTORY_DAYS)).date().isoformat()
    frame = data.ohlcv(item.id, start)
    if frame.empty or item.asset_class != "stock":
        return frame, f"{item.symbol} history"
    spy_bars = data.ohlcv("etf:spy", start)
    spy = spy_bars["close"] if not spy_bars.empty else pd.Series(dtype=float)
    if spy.empty:
        return frame, f"{item.symbol} history"
    # Remove the stock's average daily excess return over SPY (survivorship drift).
    own = frame["close"].pct_change(fill_method=None)
    excess = float(own.mean() - spy.reindex(frame.index).pct_change(fill_method=None).mean())
    factor = np.exp(-excess * np.arange(len(frame)))
    frame = frame.copy()
    for column in ("open", "high", "low", "close"):
        frame[column] = frame[column] * factor
    return frame, f"{item.symbol} history, survivorship drift removed"


def simulate_bracket(frame: pd.DataFrame, direction: str, horizon: int, stop_pct: float, target_pct: float,
                     end: int | None = None, entries: list[int] | None = None, min_n: int = 30) -> dict:
    """Replay the bracket from every STEP-th day of `frame` (rows before `end` only), or only
    from the row positions in `entries` (a conditional base rate, e.g. past shock days)."""
    frame = frame.iloc[:end] if end is not None else frame
    o, h, l, c = (frame[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    o = np.where(np.isnan(o), c, o)
    h = np.where(np.isnan(h), c, h)
    l = np.where(np.isnan(l), c, l)
    long = direction == "long"
    returns = []
    starts = range(0, len(c) - horizon - 1, STEP) if entries is None else \
        [i for i in entries if 0 <= i < len(c) - horizon - 1]
    for i in starts:
        entry = c[i]
        if not entry or np.isnan(entry):
            continue
        stop = entry * (1 - stop_pct) if long else entry * (1 + stop_pct)
        target = entry * (1 + target_pct) if long else entry * (1 - target_pct)
        exit_price = c[i + horizon]
        for j in range(i + 1, i + horizon + 1):
            if long:
                if l[j] <= stop:
                    exit_price = min(o[j], stop)
                    break
                if h[j] >= target:
                    exit_price = max(o[j], target)
                    break
            else:
                if h[j] >= stop:
                    exit_price = max(o[j], stop)
                    break
                if l[j] <= target:
                    exit_price = min(o[j], target)
                    break
        raw = exit_price / entry - 1
        returns.append(raw if long else -raw)
    arr = np.array(returns)
    if len(arr) < min_n:
        return {"n": len(arr), "p_win": 0.5, "avg_win": target_pct, "avg_loss": stop_pct, "mean": 0.0}
    wins, losses = arr[arr > 0], arr[arr <= 0]
    return {
        "n": int(len(arr)),
        "p_win": float((arr > 0).mean()),
        "avg_win": float(wins.mean()) if len(wins) else target_pct,
        "avg_loss": float(-losses.mean()) if len(losses) else stop_pct,
        "mean": float(arr.mean()),
    }


def event_component(hit_rate: float, n: int, direction: str, sign_of_edge: float) -> float:
    """Directional probability implied by an event's history, shrunk toward 0.5."""
    p_up = 0.5 + (hit_rate - 0.5) * n / (n + SHRINK)
    p = p_up if direction == "long" else 1 - p_up
    if (sign_of_edge > 0) != (direction == "long"):
        p = min(p, 0.5)  # an effect pointing against the trade can only lower the odds
    return p


def calibration_factor() -> tuple[float, str]:
    """k in p' = base + k (p - base): how much of the evidence's claimed lift over the bracket
    base rate showed up in outcomes. Live track record first (once 20 calls have closed),
    else the point-in-time replay; 1.0 when neither has enough calls."""
    for source, sql in (
        ("live track record", """SELECT probability p, base_probability b,
                                 CASE WHEN realized_return > 0 THEN 1 ELSE 0 END w FROM recommendations
                                 WHERE status='closed' AND realized_return IS NOT NULL AND base_probability IS NOT NULL"""),
        ("replay", "SELECT probability p, base b, win w FROM replay_calls WHERE base IS NOT NULL"),
    ):
        rows = db.rows(sql)
        if len(rows) >= MIN_CALIBRATION_N:
            claimed = float(np.mean([r["p"] - r["b"] for r in rows]))
            delivered = float(np.mean([r["w"] - r["b"] for r in rows]))
            if abs(claimed) < 0.01:
                return 1.0, f"{source}: evidence claimed too little lift to calibrate"
            k = float(np.clip(delivered / claimed, 0.0, 1.5))
            return k, (f"{source}: n={len(rows)}, evidence claimed {claimed:+.1%} over base, "
                       f"delivered {delivered:+.1%}")
    return 1.0, "not enough closed calls to calibrate yet"


def shock_bracket(frame: pd.DataFrame, shock: dict, direction: str, horizon_days: int, stop_pct: float,
                  target_pct: float, unconditional: dict) -> dict | None:
    """The bracket replayed only from past shocks like today's, shrunk toward the unconditional
    bracket by n / (n + SHRINK). After a shock volatility is higher, so stops and targets are hit
    more often: this is the base rate of the situation the trade is actually entered in."""
    dates = reaction.shock_days(frame["close"], shock["side"])
    entries = [int(i) for i in frame.index.get_indexer(dates) if i >= 0]
    cond = simulate_bracket(frame, direction, int(horizon_days), stop_pct, target_pct, entries=entries,
                            min_n=reaction.RELIABLE_N)
    if cond["n"] < reaction.RELIABLE_N:
        return None
    w = cond["n"] / (cond["n"] + SHRINK)

    def blend(key: str) -> float:
        return (1 - w) * unconditional[key] + w * cond[key]

    return {"n": cond["n"], "weight": w, "p_win_raw": cond["p_win"], "p_win": blend("p_win"),
            "avg_win": blend("avg_win"), "avg_loss": blend("avg_loss")}


def evidence_probability(instrument_id: str, direction: str, horizon_days: int, stop_pct: float,
                         target_pct: float, snapshot: dict | None = None, quote: dict | None = None) -> dict:
    item = universe.require(instrument_id)
    horizon = nearest_horizon(horizon_days)
    frame, history_label = _ohlc(item)
    bracket = simulate_bracket(frame, direction, int(horizon_days), stop_pct, target_pct) if not frame.empty else \
        {"n": 0, "p_win": 0.5, "avg_win": target_pct, "avg_loss": stop_pct, "mean": 0.0}
    base = bracket["p_win"]
    components = [{"source": f"bracket base rate ({history_label}, n={bracket['n']})", "p": base}]
    adjustments: list[float] = []
    evidence_kinds: list[str] = []

    # A live shock (today's or yesterday's move >= 2 sigma): condition the base rate on past
    # shocks, and count the measured follow-through or reversal as evidence when it is reliable.
    shock = reaction.current_shock(item.id, quote) if not frame.empty else None
    shock_info = None
    if shock and shock["is_shock"]:
        conditional = shock_bracket(frame, shock, direction, horizon_days, stop_pct, target_pct, bracket)
        react = reaction.reaction(item.id, shock["side"])
        shock_info = {**shock, "reaction": react["verdict"]}
        if conditional:
            bracket = {**bracket, "avg_win": conditional["avg_win"], "avg_loss": conditional["avg_loss"]}
            base = conditional["p_win"]
            components.append({"source": f"same bracket after past {shock['side']} shocks >= {reaction.SIGMA:g}σ "
                                         f"(n={conditional['n']}, won {conditional['p_win_raw']:.0%}, weight "
                                         f"{conditional['weight']:.2f})", "p": round(base, 4)})
        pointed = reaction.trade_direction(react, int(horizon_days))
        if not pointed and (react.get("reliable_horizons") or react.get("pooled_reliable_horizons")):
            components.append({"source": f"shock reaction not counted at {horizon_days} sessions: reliable only at "
                                         "other horizons, or this asset's own shocks point the other way",
                               "p": round(base, 4)})
        if pointed:
            pointed, row, source = pointed
            h = row["horizon"]
            p_up = 0.5 + (row["hit_rate"] - 0.5) * row["n"] / (row["n"] + SHRINK)
            p_react = p_up if direction == "long" else 1 - p_up
            if pointed != direction:
                p_react = min(p_react, 0.5)  # a reaction against the trade can only lower the odds
            adjustments.append(p_react - 0.5)
            evidence_kinds.append("shock_reaction")
            who = item.symbol if source == "asset" else f"all {item.asset_class}s"
            components.append({"source": f"{who}: {row['pattern']} after {shock['side']} shocks, {h} sessions "
                                         f"(n={row['n']}, t={row['t_stat']}, q={row['q_value']})",
                               "p": round(p_react, 4)})

    for event in event_study.recent_events(10, item.id):
        impact = event_study.impact(event["type"], item.id)
        stats = impact["horizons"].get(horizon) if impact else None
        if not stats or not stats.get("reliable"):
            continue
        p_event = event_component(stats["hit_rate"], stats["n"], direction, stats["edge"])
        adjustments.append(p_event - 0.5)
        evidence_kinds.append("event_study")
        components.append({"source": f"{event['type']} ({event['date']}), n={stats['n']}, q={stats['q_value']:.3f}",
                           "p": p_event})

    if snapshot and snapshot.get("model_has_edge") and snapshot.get("prob_up") is not None:
        p_model = snapshot["prob_up"] if direction == "long" else 1 - snapshot["prob_up"]
        adjustments.append(p_model - 0.5)
        evidence_kinds.append("quant_model")
        components.append({"source": f"{item.asset_class} quant model (walk-forward edge)", "p": p_model})

    # Strongest single adjustment: overlapping evidence is not independent, so don't add them up.
    edge = max(adjustments, key=abs) if adjustments else 0.0
    raw = float(np.clip(base + edge, P_MIN, P_MAX))
    k, calibration = calibration_factor()
    # Calibration shrinks only the evidence part; the bracket base rate is already empirical.
    p = float(np.clip(base + k * (raw - base), P_MIN, P_MAX))
    ev = p * bracket["avg_win"] - (1 - p) * bracket["avg_loss"]
    # Evidence pointing against the trade lowers p; only evidence for it counts as support.
    supporting = sorted({kind for kind, adj in zip(evidence_kinds, adjustments) if adj > 0})
    has_evidence = bool(supporting)
    return {
        "probability": round(p, 4),
        "base": round(base, 4),
        "raw": round(raw, 4),
        "expected_return": round(ev, 5),
        "avg_win": round(bracket["avg_win"], 5),
        "avg_loss": round(bracket["avg_loss"], 5),
        "horizon": horizon,
        "has_evidence": has_evidence,
        "evidence_kinds": supporting,
        "shock": shock_info,
        "components": components,
        "calibration": {"k": round(k, 3), "basis": calibration},
        "explanation": (
            f"{direction} {item.symbol}, stop {stop_pct:.1%} / target {target_pct:.1%} over {horizon_days} sessions: "
            f"the same bracket won {base:.0%} of {bracket['n']} past entries"
            + (f"; reliable evidence would move it to {raw:.0%}, calibrated to {p:.0%} (k={k:.2f}: {calibration})"
               if has_evidence else "; no reliable evidence beyond that")
            + (f" (entered after a {shock_info['z']:+.1f}σ move; {shock_info['reaction']})" if shock_info else "")
            + f". Expected value {ev:+.2%} per trade"
        ),
    }


STOP_ATR = (1.5, 2.0, 3.0)
REWARD_RISK = (1.5, 2.0, 3.0)
BRACKET_HORIZONS = (10, 20)


def best_bracket(instrument_id: str, direction: str, price: float, minimum: float,
                 snapshot: dict | None = None) -> dict | None:
    """The stop/target/horizon (within the checklist's rules: stop 1.5-3x ATR, reward/risk >= 1.5)
    with the highest historical expected value for this instrument and direction, if any passes
    the same EV > 0 and minimum-probability gate. None when no such bracket exists."""
    item = universe.require(instrument_id)
    frame, _ = _ohlc(item)
    if frame.empty or len(frame) < 60:
        return None
    tr = pd.concat([frame["high"] - frame["low"], (frame["high"] - frame["close"].shift()).abs(),
                    (frame["low"] - frame["close"].shift()).abs()], axis=1).max(axis=1)
    atr_pct = float(tr.tail(14).mean() / frame["close"].iloc[-1])
    if not atr_pct or np.isnan(atr_pct):
        return None
    scored = []
    for k in STOP_ATR:
        for rr in REWARD_RISK:
            for horizon in BRACKET_HORIZONS:
                stop_pct, target_pct = k * atr_pct, k * atr_pct * rr
                sim = simulate_bracket(frame, direction, horizon, stop_pct, target_pct)
                ev = sim["p_win"] * sim["avg_win"] - (1 - sim["p_win"]) * sim["avg_loss"]
                scored.append((ev, stop_pct, target_pct, horizon))
    for _ev, stop_pct, target_pct, horizon in sorted(scored, reverse=True)[:3]:
        prob = evidence_probability(instrument_id, direction, horizon, stop_pct, target_pct, snapshot)
        if prob["expected_return"] > 0 and prob["probability"] >= minimum:
            sign = -1 if direction == "long" else 1
            return {"stop": round(price * (1 + sign * stop_pct), 4), "target": round(price * (1 - sign * target_pct), 4),
                    "horizon_days": horizon, "stop_pct": stop_pct, "target_pct": target_pct,
                    "probability": prob["probability"], "expected_return": prob["expected_return"]}
    return None
