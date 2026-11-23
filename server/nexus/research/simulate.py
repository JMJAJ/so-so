"""Monte Carlo simulation of future prices: one asset, the whole paper account, and "what if"
scenarios, plus an honesty check of the simulator on past dates.

Paths use filtered historical simulation. Each asset's daily log returns are divided by the
EWMA volatility known the day before (point-in-time), which leaves standardised shocks. A path
stitches together random runs of those shocks (stationary bootstrap, mean run BLOCK sessions:
keeps fat tails and short-run momentum), scales them by today's volatility decaying toward the
long-run level, and compounds. Several assets are drawn from the same historical days, so their
co-movement is the real one.

  drift     the long-run mean daily return; single stocks and crypto get the S&P 500's instead
            (today's universe is the survivors, so their own history overstates how often
            buying them worked).
  analogs   optional: runs start only inside the forward windows of the 40 past dates most like
            today (research/analogs.py), i.e. history from similar conditions.
  bracket   stops and targets are checked on daily closes, so intraday touches are missed.

The ranges are what history makes plausible, not forecasts. `check()` replays the simulator on
past dates with data <= that date and measures how often the outcome landed inside the 50% and
80% bands; every simulation reports that score next to its fan.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from .. import accounts, data, db, paper, universe
from ..taxonomy import EVENT_TYPES, label
from . import analogs, event_study

LAMBDA = 0.94  # EWMA decay (RiskMetrics)
BLOCK = 5  # mean run length of consecutive historical days
REVERT = 0.97  # daily persistence of today's volatility above or below its long-run level
HISTORY = 252 * 10
MIN_HISTORY = 250
PATHS = 4000
HORIZONS = (5, 10, 20, 40)
QUANTILES = (10, 25, 50, 75, 90)
CHECK_SAMPLE = ("etf:spy", "etf:qqq", "etf:tlt", "etf:gld", "etf:xle", "etf:iwm", "stock:aapl", "stock:msft",
                "stock:nvda", "stock:jpm", "stock:xom", "crypto:btc", "crypto:eth", "forex:eurusd", "forex:usdjpy",
                "commodity:gold", "commodity:wti")
SCENARIO_ASSETS = ("etf:spy", "etf:qqq", "etf:iwm", "etf:tlt", "etf:gld", "etf:xle", "etf:uup", "crypto:btc")
PRESETS = [
    {"id": "oil_up", "label": "Oil +10% in a week", "driver": "commodity:wti", "move": 0.10, "window": 5},
    {"id": "oil_down", "label": "Oil −10% in a week", "driver": "commodity:wti", "move": -0.10, "window": 5},
    {"id": "vix_spike", "label": "VIX +40% in a week", "driver": "index:vix", "move": 0.40, "window": 5},
    {"id": "spy_down", "label": "S&P 500 −5% in a week", "driver": "etf:spy", "move": -0.05, "window": 5},
    {"id": "dollar_up", "label": "Dollar +2% in a week", "driver": "index:dxy", "move": 0.02, "window": 5},
    {"id": "btc_down", "label": "Bitcoin −15% in a week", "driver": "crypto:btc", "move": -0.15, "window": 5},
    {"id": "rate_hike", "label": "Fed hikes", "driver": "rate_hike"},
    {"id": "rate_cut", "label": "Fed cuts", "driver": "rate_cut"},
]
FDR_Q = event_study.FDR_Q
MIN_N = 8


# ── Shared machinery ─────────────────────────────────────────────────────────

def _log_returns(ids: list[str], as_of: pd.Timestamp | None) -> pd.DataFrame:
    closes = data.closes()
    ids = [i for i in ids if i in closes]
    frame = closes[ids]
    if as_of is not None:
        frame = frame[frame.index <= as_of]
    frame = frame.dropna(how="all")
    return np.log(frame).diff().iloc[1:].tail(HISTORY)


def _shocks(returns: pd.Series) -> tuple[np.ndarray, float, float, float]:
    """(standardised shocks with NaN where the asset had no print, today's daily vol,
    long-run daily vol, mean daily log return)."""
    clean = returns.dropna()
    mean = float(clean.mean())
    long_run = float(clean.std())
    var = (clean - mean).pow(2).ewm(alpha=1 - LAMBDA, adjust=False).mean()
    before = np.sqrt(var.shift(1)).fillna(long_run).replace(0, long_run)  # vol known the day before
    z = ((clean - mean) / before).clip(-8, 8)
    z = (z - z.mean()) / z.std()
    return z.reindex(returns.index).to_numpy(), float(np.sqrt(var.iloc[-1])), long_run, mean


def _drift(item: universe.Instrument, own_mean: float, as_of: pd.Timestamp | None) -> tuple[float, str]:
    if item.asset_class in ("stock", "crypto") and item.id != "etf:spy":
        spy = _log_returns(["etf:spy"], as_of)
        if not spy.empty and spy["etf:spy"].notna().sum() >= MIN_HISTORY:
            return float(spy["etf:spy"].mean()), "S&P 500 drift (survivorship-safe)"
        return 0.0, "zero drift"
    return own_mean, "own long-run drift"


def _vol_path(now: float, long_run: float, horizon: int) -> np.ndarray:
    return long_run + (now - long_run) * REVERT ** np.arange(1, horizon + 1)


def _draw(rng: np.random.Generator, size: int, paths: int, horizon: int, starts: np.ndarray | None) -> np.ndarray:
    """Stationary-bootstrap row indices, shape (paths, horizon)."""
    pick = (lambda: rng.integers(0, size, paths)) if starts is None else (lambda: rng.choice(starts, paths))
    rows = np.empty((paths, horizon), dtype=int)
    current = pick()
    for day in range(horizon):
        if day:
            jump = rng.random(paths) < 1 / BLOCK
            current = np.where(jump, pick(), (current + 1) % size)
        rows[:, day] = current
    return rows


def _fan(cum: np.ndarray) -> list[dict]:
    """cum: (paths, horizon + 1) simple returns from day 0."""
    q = np.percentile(cum, QUANTILES, axis=0)
    return [{"day": d, **{f"p{k}": round(float(q[i, d]), 5) for i, k in enumerate(QUANTILES)}}
            for d in range(cum.shape[1])]


def _max_drawdown(prices: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(prices, axis=1)
    return (prices / peak - 1).min(axis=1)


def _analog_starts(item_id: str, index: pd.DatetimeIndex, horizon: int,
                   as_of: pd.Timestamp | None) -> tuple[np.ndarray | None, str]:
    found = analogs.find(item_id, k=40, as_of=as_of, with_paths=False)
    if not found:
        return None, "not enough history for analogs; used all history"
    rows: set[int] = set()
    for row in found["analogs"]:
        pos = index.searchsorted(pd.Timestamp(row["date"]))
        rows.update(range(pos + 1, min(pos + 1 + horizon, len(index))))
    if len(rows) < 100:
        return None, "too few analog days; used all history"
    return np.array(sorted(rows)), f"history from the {found['k']} most similar past setups only"


def _horizon(value) -> int:
    return int(min(max(int(value or 20), 1), 60))


# ── One asset ────────────────────────────────────────────────────────────────

def asset(instrument_id: str, horizon: int = 20, *, paths: int = PATHS, analog: bool = False,
          direction: str | None = None, stop: float | None = None, target: float | None = None,
          as_of: pd.Timestamp | None = None, seed: int | None = None, with_check: bool = True) -> dict:
    item = universe.require(instrument_id)
    horizon = _horizon(horizon)
    returns = _log_returns([item.id], as_of)
    series = returns[item.id] if item.id in returns else pd.Series(dtype=float)
    if series.notna().sum() < MIN_HISTORY:
        raise ValueError(f"Not enough price history to simulate {item.symbol}")
    series = series.dropna()
    z, vol_now, vol_long, own_mean = _shocks(series)
    drift, drift_label = _drift(item, own_mean, as_of)
    starts, basis = (None, "all history")
    if analog:
        starts, basis = _analog_starts(item.id, series.index, horizon, as_of)
    rng = np.random.default_rng(seed)
    rows = _draw(rng, len(z), paths, horizon, starts)
    log_paths = np.cumsum(drift + _vol_path(vol_now, vol_long, horizon) * z[rows], axis=1)
    cum = np.hstack([np.zeros((paths, 1)), np.expm1(log_paths)])
    final = cum[:, -1]

    price = None
    if as_of is None:
        from ..ingest import prices

        quote = prices.quote(item.id)
        price = quote["price"] if quote and quote.get("price") else None
    if not price:
        price = float(data.closes()[item.id].loc[:as_of].dropna().iloc[-1])
    worst = np.sort(final)[: max(1, paths // 20)]
    result = {
        "instrument_id": item.id, "symbol": item.symbol, "asset_class": item.asset_class,
        "price": price, "horizon": horizon, "paths": paths,
        "as_of": series.index[-1].date().isoformat(),
        "fan": _fan(cum),
        "p_up": round(float((final > 0).mean()), 4),
        "mean": round(float(final.mean()), 5),
        "median": round(float(np.median(final)), 5),
        "var95": round(float(np.percentile(final, 5)), 5),
        "cvar95": round(float(worst.mean()), 5),
        "typical_drawdown": round(float(np.median(_max_drawdown(1 + cum))), 5),
        "vol_now": round(float(vol_now * np.sqrt(252)), 4),
        "vol_long": round(float(vol_long * np.sqrt(252)), 4),
        "method": {"basis": basis, "drift": drift_label, "history_days": int(len(z)), "block": BLOCK},
    }

    if stop is None and target is None and as_of is None:
        rec = db.one("SELECT direction, stop, target FROM recommendations WHERE instrument_id=? AND status='open' "
                     "ORDER BY created_at DESC LIMIT 1", (item.id,))
        if rec:
            direction, stop, target = rec["direction"], rec["stop"], rec["target"]
            result["bracket_source"] = "open AI call"
    if direction in ("long", "short") and (stop or target):
        result["bracket"] = _bracket(cum, price, direction, stop, target)
        result["levels"] = [{"label": k, "value": round(float(v / price - 1), 5)}
                            for k, v in (("stop", stop), ("target", target)) if v]
    if with_check:
        result["check"] = coverage(item.asset_class, horizon)
    return result


def _bracket(cum: np.ndarray, price: float, direction: str, stop: float | None, target: float | None) -> dict:
    sign = 1 if direction == "long" else -1
    trade = sign * cum[:, 1:]  # the trade's return, day 1..horizon
    stop_ret = sign * (stop / price - 1) if stop else -np.inf
    target_ret = sign * (target / price - 1) if target else np.inf
    hit_stop = trade <= stop_ret
    hit_target = trade >= target_ret
    never = trade.shape[1] + 1
    first_stop = np.where(hit_stop.any(axis=1), hit_stop.argmax(axis=1), never)
    first_target = np.where(hit_target.any(axis=1), hit_target.argmax(axis=1), never)
    stopped = first_stop < first_target
    targeted = first_target < first_stop
    outcome = np.where(stopped, stop_ret, np.where(targeted, target_ret, trade[:, -1]))
    return {
        "direction": direction, "stop": stop, "target": target,
        "p_target": round(float(targeted.mean()), 4),
        "p_stop": round(float(stopped.mean()), 4),
        "p_neither": round(float((~stopped & ~targeted).mean()), 4),
        "p_profit": round(float((outcome > 0).mean()), 4),
        "expected_return": round(float(outcome.mean()), 5),
        "note": "Stops and targets checked on daily closes; intraday touches are missed.",
    }


# ── Whole account ────────────────────────────────────────────────────────────

def _usd_per_unit(item: universe.Instrument, price: np.ndarray) -> np.ndarray | float:
    if item.quote_currency == "USD":
        return item.multiplier
    if item.symbol.startswith("USD/"):
        return item.multiplier / price
    return item.multiplier


def _sessions_until(expires_at: str | None, horizon: int) -> int:
    if not expires_at:
        return horizon
    today = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)
    end = pd.Timestamp(expires_at).tz_localize(None) if pd.Timestamp(expires_at).tzinfo else pd.Timestamp(expires_at)
    return int(min(max(np.busday_count(today.date(), end.date()), 0), horizon))


def portfolio(horizon: int = 20, *, paths: int = PATHS, account_id: str | None = None,
              seed: int | None = None) -> dict:
    """Simulate every open position in the account on the same historical days, with each
    position's stop, target and expiry applied, and sum the P&L."""
    horizon = _horizon(horizon)
    account = accounts.get(account_id)
    state = paper.portfolio(mark=True, account_id=account["id"])
    open_positions = [p for p in state["positions"] if p["status"] == "open" and p["current_price"]]
    equity = float(state["equity"])
    base = {"account": account["name"], "equity": equity, "horizon": horizon, "paths": paths,
            "positions": [], "pending_skipped": state["pending_count"]}
    if not open_positions:
        return {**base, "fan": None, "note": "No open positions to simulate."}
    ids = sorted({p["instrument_id"] for p in open_positions})
    returns = _log_returns(ids, None)
    shocks, vols, drifts = {}, {}, {}
    for instrument_id in ids:
        item = universe.require(instrument_id)
        if instrument_id not in returns or returns[instrument_id].notna().sum() < MIN_HISTORY:
            continue
        z, now, long_run, own_mean = _shocks(returns[instrument_id])
        shocks[instrument_id] = np.nan_to_num(z)  # no print that day: no move
        vols[instrument_id] = _vol_path(now, long_run, horizon)
        drifts[instrument_id] = _drift(item, own_mean, None)[0]
    rng = np.random.default_rng(seed)
    rows = _draw(rng, len(returns), paths, horizon, None)

    total = np.zeros((paths, horizon + 1))
    rows_out = []
    finals = []
    for position in open_positions:
        instrument_id = position["instrument_id"]
        item = universe.require(instrument_id)
        current = float(position["current_price"])
        if instrument_id not in shocks:
            rows_out.append({"symbol": item.symbol, "side": position["side"], "skipped": "not enough history"})
            continue
        log_paths = np.cumsum(drifts[instrument_id] + vols[instrument_id] * shocks[instrument_id][rows], axis=1)
        price = current * np.hstack([np.ones((paths, 1)), np.exp(log_paths)])
        long = position["side"] == "long"
        stop, target = position.get("stop"), position.get("target")
        never = horizon + 1

        def first_cross(level: float | None, below: bool) -> np.ndarray:
            if not level:
                return np.full(paths, never)
            crossed = (price[:, 1:] <= level) if below else (price[:, 1:] >= level)
            return np.where(crossed.any(axis=1), crossed.argmax(axis=1) + 1, never)

        stop_day = first_cross(stop, below=long)
        target_day = first_cross(target, below=not long)
        expiry = _sessions_until(position.get("expires_at"), horizon)
        stopped = (stop_day < target_day) & (stop_day <= expiry)
        targeted = (target_day < stop_day) & (target_day <= expiry)
        # Freeze each path at its exit: the stop or target level, or the close on the expiry session.
        exit_day = np.where(stopped, stop_day, np.where(targeted, target_day, expiry))
        exit_price = np.where(stopped, stop or 0.0, np.where(targeted, target or 0.0, price[:, expiry]))
        days = np.arange(horizon + 1)
        frozen = np.where(days[None, :] >= exit_day[:, None], exit_price[:, None], price)
        direction = 1 if long else -1
        pnl = (frozen - current) * float(position["quantity"]) * direction * _usd_per_unit(item, frozen)
        total += pnl
        finals.append(pnl[:, -1])
        rows_out.append({
            "instrument_id": instrument_id, "symbol": item.symbol, "side": position["side"],
            "notional": round(float(position["notional"]), 2),
            "mean_pnl": round(float(pnl[:, -1].mean()), 2),
            "p5_pnl": round(float(np.percentile(pnl[:, -1], 5)), 2),
            "p_stop": round(float(stopped.mean()), 4), "p_target": round(float(targeted.mean()), 4),
        })
    if not finals:
        return {**base, "positions": rows_out, "fan": None, "note": "No position has enough history to simulate."}
    final_total = total[:, -1]
    var_total = float(final_total.var())
    simulated = [r for r in rows_out if "mean_pnl" in r]
    for row, pnl_final in zip(simulated, finals):
        # Share of the account's variance this position carries (sums to 1 across positions).
        row["risk_share"] = round(float(np.cov(pnl_final, final_total, bias=True)[0, 1] / var_total), 4) if var_total else 0.0
    equity_ret = total / equity if equity else total
    worst = np.sort(final_total)[: max(1, paths // 20)]
    return {
        **base, "positions": rows_out,
        "fan": _fan(equity_ret),
        "mean_pnl": round(float(final_total.mean()), 2),
        "median_pnl": round(float(np.median(final_total)), 2),
        "p_loss": round(float((final_total < 0).mean()), 4),
        "p_loss_5pct": round(float((equity_ret[:, -1] < -0.05).mean()), 4),
        "p_loss_10pct": round(float((equity_ret[:, -1] < -0.10).mean()), 4),
        "p_gain_5pct": round(float((equity_ret[:, -1] > 0.05).mean()), 4),
        "var95": round(float(np.percentile(final_total, 5)), 2),
        "cvar95": round(float(worst.mean()), 2),
        "check": coverage(None, horizon),
        "note": "Open positions only, with their stops, targets and expiry; pending orders are left out.",
    }


# ── What-if scenarios ────────────────────────────────────────────────────────

def _triggers(close: pd.Series, move: float, window: int, spacing: int) -> list[pd.Timestamp]:
    """First days the `window`-session return crossed `move`, at least `spacing` sessions apart."""
    change = close / close.shift(window) - 1
    hit = (change >= move) if move > 0 else (change <= move)
    first = hit & ~hit.shift(1, fill_value=False)
    chosen: list[pd.Timestamp] = []
    last = -10**9
    for ts in first[first].index:
        pos = close.index.get_loc(ts)
        if pos - last >= spacing:
            chosen.append(ts)
            last = pos
    return chosen


def _effect(close: pd.Series, dates: list[pd.Timestamp], horizon: int) -> dict | None:
    forward = close.shift(-horizon) / close - 1
    values = forward.reindex(dates).dropna()
    if len(values) < 3:
        return None
    normal = float(forward.dropna().mean())
    edge = float(values.mean() - normal)
    sd = float(values.std(ddof=1)) or 1e-9
    t = edge / (sd / np.sqrt(len(values)))
    half = len(values) // 2
    stable = half >= 2 and np.sign(values.iloc[:half].mean() - normal) == np.sign(values.iloc[half:].mean() - normal)
    return {"n": int(len(values)), "mean": round(float(values.mean()), 5), "median": round(float(values.median()), 5),
            "hit_rate": round(float((values > 0).mean()), 4), "normal": round(normal, 5), "edge": round(edge, 5),
            "t_stat": round(float(t), 2), "p_value": event_study._t_two_sided(float(t), len(values) - 1),
            "stable": bool(stable)}


def scenario(driver: str, move: float | None = None, window: int = 5, horizon: int = 20,
             instruments: list[str] | None = None, account_id: str | None = None) -> dict:
    """What each asset (and the account's open positions) did after past occurrences of a move in
    a driver ("oil +10% in 5 sessions") or of an event type ("rate_hike"). Effects are measured
    against the asset's normal return over the same horizon and FDR-corrected across assets."""
    horizon = _horizon(horizon)
    account = accounts.get(account_id)
    state = paper.portfolio(mark=False, account_id=account["id"])
    held = {p["instrument_id"]: p for p in state["positions"] if p["status"] == "open"}
    targets = [universe.require(i).id for i in (instruments or [])] or list(dict.fromkeys([*held, *SCENARIO_ASSETS]))
    targets = [t for t in targets if universe.get(t)]
    closes = data.closes()

    if driver in EVENT_TYPES:
        title = f"After {label(driver)}"
        h = min(event_study.HORIZONS[1:], key=lambda value: abs(value - horizon))
        rows = []
        for target in targets:
            impact = event_study.impact(driver, target)
            stats = (impact or {}).get("horizons", {}).get(h) or (impact or {}).get("horizons", {}).get(str(h))
            if stats:
                rows.append({"instrument_id": target, "n": stats["n"], "mean": round(stats["mean"], 5),
                             "median": round(stats.get("median", stats["mean"]), 5), "hit_rate": stats["hit_rate"],
                             "normal": round(stats["mean"] - stats["edge"], 5), "edge": round(stats["edge"], 5),
                             "t_stat": round(stats["t_stat"], 2), "q_value": stats.get("q_value"),
                             "stable": bool(stats.get("stable")), "reliable": bool(stats.get("reliable"))})
        occurrences = db.one("SELECT COUNT(*) c FROM events WHERE type=?", (driver,))["c"]
        last = db.one("SELECT MAX(date) d FROM events WHERE type=?", (driver,))["d"]
        now_text = f"last occurrence {last}" if last else "never seen in the stored history"
        horizon = h
    else:
        item = universe.require(driver)
        if move is None or not move:
            raise ValueError("A price driver needs a move, e.g. 0.10 for +10%")
        if item.id not in closes:
            raise ValueError(f"No price history for {item.symbol}")
        driver_close = closes[item.id].dropna()
        window = int(min(max(window, 1), 60))
        dates = _triggers(driver_close, float(move), window, spacing=horizon)
        title = f"{item.symbol} {float(move):+.0%} within {window} sessions"
        rows = []
        for target in targets:
            if target not in closes:
                continue
            effect = _effect(closes[target].dropna(), dates, horizon)
            if effect:
                rows.append({"instrument_id": target, **effect})
        q_values = event_study.benjamini_hochberg([r["p_value"] for r in rows])
        for row, q in zip(rows, q_values):
            row["q_value"] = round(float(q), 4)
            row["reliable"] = bool(q <= FDR_Q and row["stable"] and row["n"] >= MIN_N)
            row.pop("p_value", None)
        occurrences = len(dates)
        latest = float(driver_close.iloc[-1] / driver_close.iloc[-1 - window] - 1) if len(driver_close) > window else None
        now_text = (f"{item.symbol} has moved {latest:+.1%} over the last {window} sessions" if latest is not None else "")
        if dates:
            now_text += f"; last time the condition hit: {dates[-1].date()}"

    impact_rows = []
    for row in rows:
        item = universe.require(row["instrument_id"])
        row["symbol"] = item.symbol
        position = held.get(row["instrument_id"])
        if position:
            direction = 1 if position["side"] == "long" else -1
            row["position"] = position["side"]
            row["position_effect"] = round(direction * row["mean"] * float(position["notional"]), 2)
            impact_rows.append(row)
    rows.sort(key=lambda r: (r["instrument_id"] not in held, not r["reliable"], -abs(r["edge"])))
    reliable = [r for r in rows if r["reliable"]]
    return {
        "driver": driver, "move": move, "window": window if driver not in EVENT_TYPES else None,
        "horizon": horizon, "title": title, "occurrences": int(occurrences), "now": now_text,
        "assets": rows,
        "account": account["name"],
        "account_effect": round(sum(r["position_effect"] for r in impact_rows), 2) if impact_rows else None,
        "reliable_count": len(reliable),
        "note": ("Average path after past occurrences vs the asset's normal return. Only rows marked reliable "
                 f"(q <= {FDR_Q}, same sign in both halves, n >= {MIN_N}) are evidence; the rest is noise-sized."),
    }


# ── Honesty check ────────────────────────────────────────────────────────────

def check(horizon: int = 20, years: float = 5, every: int = 20, paths: int = 1000,
          ids: tuple[str, ...] = CHECK_SAMPLE, progress: Callable[[str], None] | None = None) -> dict:
    """Run the simulator on past dates (data <= each date only) and store where the realised
    return fell in that day's fan."""
    closes = data.closes()
    ids = tuple(i for i in ids if i in closes)
    rows = []
    for count, instrument_id in enumerate(ids):
        if progress:
            progress(f"simulation check {count + 1}/{len(ids)}: {instrument_id}")
        close = closes[instrument_id].dropna()
        if len(close) < MIN_HISTORY + horizon + 50:
            continue
        start = close.index[-1] - pd.Timedelta(days=int(365 * years))
        eligible = [i for i in range(MIN_HISTORY + 20, len(close) - horizon) if close.index[i] >= start]
        for i in eligible[::every]:
            as_of = close.index[i]
            try:
                sim = asset(instrument_id, horizon, paths=paths, as_of=as_of, seed=i, with_check=False)
            except ValueError:
                continue
            band = sim["fan"][-1]
            realized = float(close.iloc[i + horizon] / close.iloc[i] - 1)
            rows.append((instrument_id, as_of.date().isoformat(), horizon, band["p10"], band["p25"], band["p50"],
                         band["p75"], band["p90"], sim["p_up"], realized))
    db.execute("DELETE FROM sim_checks WHERE horizon=?", (horizon,))
    db.executemany("INSERT OR REPLACE INTO sim_checks(instrument_id,date,horizon,p10,p25,p50,p75,p90,p_up,realized) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    return summary(horizon)


def _score(rows: list[dict]) -> dict:
    realized = np.array([r["realized"] for r in rows])
    in80 = float(np.mean([(r["p10"] <= r["realized"] <= r["p90"]) for r in rows]))
    in50 = float(np.mean([(r["p25"] <= r["realized"] <= r["p75"]) for r in rows]))
    p_up = np.array([r["p_up"] for r in rows])
    brier = float(np.mean((p_up - (realized > 0)) ** 2))
    base = float(np.mean(((realized > 0).mean() - (realized > 0)) ** 2))
    if in80 < 0.74:
        verdict = "too narrow: real outcomes land outside the range more often than it says"
    elif in80 > 0.86:
        verdict = "too wide: the range is more cautious than it needs to be"
    else:
        verdict = "ranges match reality"
    return {"n": len(rows), "in80": round(in80, 3), "in50": round(in50, 3), "brier": round(brier, 4),
            "brier_base": round(base, 4), "verdict": verdict}


def summary(horizon: int = 20) -> dict:
    rows = db.rows("SELECT * FROM sim_checks WHERE horizon=?", (horizon,))
    if not rows:
        return {"horizon": horizon, "n": 0, "overall": None, "by_class": {},
                "note": "Not run yet: the weekly research job runs it, or run it from the track record page."}
    by_class: dict[str, list[dict]] = {}
    for row in rows:
        item = universe.get(row["instrument_id"])
        by_class.setdefault(item.asset_class if item else "other", []).append(row)
    return {"horizon": horizon, "n": len(rows), "overall": _score(rows),
            "by_class": {k: _score(v) for k, v in sorted(by_class.items())},
            "from": min(r["date"] for r in rows), "to": max(r["date"] for r in rows),
            "note": "Each row: the simulator run on a past date with only the data known then. A good simulator "
                    "has ~80% of outcomes inside its 80% band and ~50% inside its 50% band."}


def coverage(asset_class: str | None, horizon: int) -> dict | None:
    """The honesty score to show next to a fan: the asset class's own if it has enough checks, else overall."""
    nearest = db.one("SELECT horizon FROM sim_checks GROUP BY horizon ORDER BY ABS(horizon - ?) LIMIT 1", (horizon,))
    if not nearest:
        return None
    rows = db.rows("SELECT c.* FROM sim_checks c WHERE horizon=?", (nearest["horizon"],))
    scope = "all assets"
    if asset_class:
        own = [r for r in rows if (universe.get(r["instrument_id"]) or universe.require("etf:spy")).asset_class == asset_class]
        if len(own) >= 30:
            rows, scope = own, f"{asset_class} assets"
    if len(rows) < 30:
        return None
    return {**_score(rows), "scope": scope, "horizon": nearest["horizon"]}
