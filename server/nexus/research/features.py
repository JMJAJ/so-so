"""Point-in-time features. Every value at row t uses data up to and including t only."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import data


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def asset_features(close: pd.Series) -> pd.DataFrame:
    """Per-instrument technical state (one row per date)."""
    close = close.dropna()
    ret = close.pct_change(fill_method=None)
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vol250 = ret.rolling(250, min_periods=120).std() * np.sqrt(252)
    sma50, sma200 = sma(close, 50), sma(close, 200)
    macd = ema(close, 12) - ema(close, 26)
    frame = pd.DataFrame({
        "close": close,
        "ret_5d": close.pct_change(5, fill_method=None),
        "ret_20d": close.pct_change(20, fill_method=None),
        "ret_60d": close.pct_change(60, fill_method=None),
        "ret_120d": close.pct_change(120, fill_method=None),
        "mom_12_1": close.shift(21) / close.shift(252) - 1,
        "vol_20d": vol20,
        "vol_ratio": vol20 / vol250,
        "rsi_14": rsi(close),
        "dist_sma50": close / sma50 - 1,
        "dist_sma200": close / sma200 - 1,
        "trend_up": ((close > sma200) & (sma50 > sma200)).astype(float).where(sma200.notna()),
        "macd_hist": (macd - ema(macd, 9)) / close,
        "dist_high_252": close / close.rolling(252, min_periods=120).max() - 1,
    })
    frame["z_ret_5d"] = frame["ret_5d"] / (ret.rolling(250, min_periods=120).std() * np.sqrt(5))
    return frame


def regime_frame() -> pd.DataFrame:
    """Market-wide state used for analogs and the dashboard regime strip."""
    return data._cached(("regime",), _regime_frame)


def _regime_frame() -> pd.DataFrame:
    closes = data.closes()
    if closes.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=closes.index)
    if "index:vix" in closes:
        vix = closes["index:vix"]
        out["vix"] = vix
        out["vix_pct_1y"] = vix.rolling(252, min_periods=120).rank(pct=True)
    if "etf:spy" in closes:
        spy = closes["etf:spy"]
        out["spy_ret_60d"] = spy.pct_change(60, fill_method=None)
        out["spy_trend"] = (spy > sma(spy, 200)).astype(float).where(sma(spy, 200).notna())
        out["spy_dd"] = spy / spy.rolling(252, min_periods=60).max() - 1
    if "index:tnx" in closes and "index:irx" in closes:
        out["curve"] = closes["index:tnx"] - closes["index:irx"]
        out["us10y"] = closes["index:tnx"]
        out["us10y_chg_60d"] = closes["index:tnx"].diff(60)
    if "index:dxy" in closes:
        out["dxy_ret_60d"] = closes["index:dxy"].pct_change(60, fill_method=None)
    if "commodity:wti" in closes:
        out["oil_ret_60d"] = closes["commodity:wti"].pct_change(60, fill_method=None)
    hy = data.macro("BAMLH0A0HYM2")
    if not hy.empty:
        out["hy_spread"] = hy.reindex(out.index, method="ffill")
    conflict = data.theme_share("global_conflict")
    if len(conflict) > 30:
        smoothed = conflict.rolling(7, min_periods=3).mean()
        out["conflict_z"] = ((smoothed - smoothed.rolling(180, min_periods=60).mean()) /
                             smoothed.rolling(180, min_periods=60).std()).reindex(out.index, method="ffill")
    return out


def regime_label(row: pd.Series) -> dict:
    """Plain-language regime summary from the latest regime row."""
    vix = row.get("vix")
    trend = row.get("spy_trend")
    curve = row.get("curve")
    risk = "neutral"
    if vix is not None and not pd.isna(vix):
        if vix >= 25 or (trend == 0 and vix >= 20):
            risk = "risk-off"
        elif vix < 17 and trend == 1:
            risk = "risk-on"
    return {
        "risk": risk,
        "vix": _f(vix),
        "vix_percentile": _f(row.get("vix_pct_1y")),
        "spy_trend": "up" if trend == 1 else ("down" if trend == 0 else None),
        "spy_ret_60d": _f(row.get("spy_ret_60d")),
        "spy_drawdown": _f(row.get("spy_dd")),
        "curve_10y_3m": _f(curve),
        "curve_inverted": bool(curve is not None and not pd.isna(curve) and curve < 0),
        "us10y": _f(row.get("us10y")),
        "us10y_chg_60d": _f(row.get("us10y_chg_60d")),
        "dollar_ret_60d": _f(row.get("dxy_ret_60d")),
        "oil_ret_60d": _f(row.get("oil_ret_60d")),
        "hy_spread": _f(row.get("hy_spread")),
        "conflict_z": _f(row.get("conflict_z")),
    }


def _f(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(number) else round(number, 4)


def forward_returns(closes: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Return from close(t) to close(t+h). NaN where the future is unknown."""
    return closes.shift(-horizon) / closes - 1


BETA_WINDOW = 252


def rolling_betas(closes: pd.DataFrame, benchmark_of: dict[str, str | None]) -> pd.DataFrame:
    """Market-model beta of each asset to its benchmark, from the trailing year of daily
    returns and lagged one day so the beta used at t is known at t. Assets without a
    benchmark get NaN (their abnormal return is the raw return)."""
    daily = closes.pct_change(fill_method=None)
    betas = pd.DataFrame(index=closes.index, columns=closes.columns, dtype=float)
    for bench in {b for b in benchmark_of.values() if b and b in daily}:
        cols = [c for c, b in benchmark_of.items() if b == bench and c in daily]
        if not cols:
            continue
        cov = daily[cols].rolling(BETA_WINDOW, min_periods=120).cov(daily[bench])
        var = daily[bench].rolling(BETA_WINDOW, min_periods=120).var()
        betas[cols] = cov.div(var, axis=0).clip(-1.0, 3.0).shift(1)
    return betas


def abnormal_forward(closes: pd.DataFrame, horizon: int, benchmark_of: dict[str, str | None],
                     betas: pd.DataFrame | None = None) -> pd.DataFrame:
    """Forward return minus beta × the benchmark's forward return (market model).
    Gold or bonds measured against SPY get a beta near zero, so they are judged on their
    own move instead of against an unrelated equity index. Horizon 0 = the reaction day
    (close t-1 to close t)."""
    if horizon == 0:
        fwd = closes / closes.shift(1) - 1
    else:
        fwd = forward_returns(closes, horizon)
    betas = rolling_betas(closes, benchmark_of) if betas is None else betas
    out = fwd.copy()
    for column, bench in benchmark_of.items():
        if column in out and bench and bench in fwd:
            beta = betas[column].fillna(1.0)
            out[column] = fwd[column] - beta * fwd[bench]
    return out
