"""
Whale activity detection — tracks large crypto movements and volume anomalies.
Uses free public APIs (no key required) and yfinance volume data.
"""

import time
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone

from prices import pair_to_yfinance

# ── Caches ──

_whale_cache: dict[str, list[dict]] = {}
_whale_cache_time: float = 0
WHALE_CACHE_TTL = 120  # 2 minutes

_volume_cache: dict[str, dict] = {}
_volume_cache_time: float = 0
VOLUME_CACHE_TTL = 300  # 5 minutes

# ── Blockchain.info — large BTC transactions (free, no key) ──

def _fetch_btc_whales(min_btc: float = 100) -> list[dict]:
    """Fetch recent large BTC transactions from blockchain.info."""
    try:
        resp = requests.get(
            "https://blockchain.info/latestblocks?format=json",
            timeout=5,
        )
        if not resp.ok:
            return []

        blocks = resp.json()
        whales: list[dict] = []

        for block in blocks[:3]:
            block_hash = block.get("hash", "")
            try:
                block_resp = requests.get(
                    f"https://blockchain.info/rawblock/{block_hash}?format=json",
                    timeout=5,
                )
                if not block_resp.ok:
                    continue
                block_data = block_resp.json()

                for tx in block_data.get("tx", []):
                    total_out = sum(out.get("value", 0) for out in tx.get("out", []))
                    btc_amount = total_out / 1e8
                    if btc_amount >= min_btc:
                        whales.append({
                            "type": "btc_transfer",
                            "amount": btc_amount,
                            "symbol": "BTC",
                            "usd_value": None,
                            "time": tx.get("time", int(time.time())),
                            "hash": tx.get("hash", "")[:16],
                        })
            except Exception:
                continue

            if len(whales) >= 5:
                break

        return whales[:10]
    except Exception:
        return []


# ── Volume spike detection — whale proxy using yfinance ──

def _fetch_volume_anomalies(symbols: list[str]) -> list[dict]:
    """Detect abnormal volume across crypto pairs using yfinance."""
    global _volume_cache, _volume_cache_time

    now = time.time()
    if now - _volume_cache_time < VOLUME_CACHE_TTL and _volume_cache:
        cached_results = []
        for sym in symbols:
            if sym in _volume_cache:
                cached_results.append(_volume_cache[sym])
        if cached_results:
            return cached_results

    anomalies: list[dict] = []

    for sym in symbols:
        try:
            yf_sym = pair_to_yfinance(sym)
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="30d", interval="1d")

            if hist is None or hist.empty or len(hist) < 5:
                continue

            volumes = hist["Volume"].dropna()
            if len(volumes) < 5:
                continue

            avg_volume = volumes.iloc[:-1].mean()
            latest_volume = volumes.iloc[-1]
            latest_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else latest_close

            if avg_volume <= 0:
                continue

            volume_ratio = latest_volume / avg_volume
            price_change = ((latest_close - prev_close) / prev_close) * 100

            if volume_ratio >= 2.0:
                signal_type = "accumulation" if price_change > 0 else "distribution"
                usd_est = latest_volume * latest_close

                anomaly = {
                    "type": f"volume_spike_{signal_type}",
                    "symbol": sym,
                    "volume_ratio": round(volume_ratio, 1),
                    "price_change_pct": round(price_change, 2),
                    "signal": signal_type,
                    "usd_volume": usd_est,
                    "time": int(time.time()),
                }
                anomalies.append(anomaly)
                _volume_cache[sym] = anomaly

        except Exception:
            continue

    _volume_cache_time = now
    return anomalies


# ── Large price movement detection ──

def _detect_large_moves(symbols: list[str], threshold_pct: float = 5.0) -> list[dict]:
    """Detect large price movements as whale activity proxy."""
    moves: list[dict] = []

    for sym in symbols:
        try:
            yf_sym = pair_to_yfinance(sym)
            ticker = yf.Ticker(yf_sym)
            hist = ticker.history(period="5d", interval="1h")

            if hist is None or hist.empty or len(hist) < 2:
                continue

            latest = float(hist["Close"].iloc[-1])
            day_ago = float(hist["Close"].iloc[-24]) if len(hist) >= 24 else float(hist["Close"].iloc[0])

            change_pct = ((latest - day_ago) / day_ago) * 100

            if abs(change_pct) >= threshold_pct:
                moves.append({
                    "type": "large_move",
                    "symbol": sym,
                    "change_pct": round(change_pct, 2),
                    "direction": "surge" if change_pct > 0 else "dump",
                    "current_price": latest,
                    "time": int(time.time()),
                })
        except Exception:
            continue

    return moves


# ── Public API ──

def get_whale_signals(crypto_symbols: list[str] | None = None) -> list[dict]:
    """
    Get all whale signals: large BTC transfers, volume anomalies, and large moves.
    Returns a list of signal dicts sorted by recency.
    """
    global _whale_cache, _whale_cache_time

    now = time.time()
    if now - _whale_cache_time < WHALE_CACHE_TTL and _whale_cache:
        all_signals = []
        for signals in _whale_cache.values():
            all_signals.extend(signals)
        return sorted(all_signals, key=lambda x: x.get("time", 0), reverse=True)[:15]

    if crypto_symbols is None:
        crypto_symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"]

    all_signals: list[dict] = []

    # BTC blockchain transfers
    btc_whales = _fetch_btc_whales(min_btc=100)
    all_signals.extend(btc_whales)

    # Volume anomalies
    volume_anomalies = _fetch_volume_anomalies(crypto_symbols)
    all_signals.extend(volume_anomalies)

    # Large price moves
    large_moves = _detect_large_moves(crypto_symbols)
    all_signals.extend(large_moves)

    # Cache by type
    _whale_cache = {
        "btc_whales": btc_whales,
        "volume": volume_anomalies,
        "moves": large_moves,
    }
    _whale_cache_time = now

    return sorted(all_signals, key=lambda x: x.get("time", 0), reverse=True)[:15]


def format_whale_context(signals: list[dict]) -> str:
    """Format whale signals into a text block for the AI agent prompt."""
    if not signals:
        return ""

    lines = ["=== WHALE ACTIVITY ==="]

    for s in signals[:10]:
        if s["type"] == "btc_transfer":
            lines.append(f"  LARGE BTC TRANSFER: {s['amount']:.0f} BTC moved (tx: {s['hash']})")
        elif "volume_spike" in s["type"]:
            direction = "ACCUMULATION (bullish)" if s.get("signal") == "accumulation" else "DISTRIBUTION (bearish)"
            lines.append(
                f"  {s['symbol']} VOLUME SPIKE: {s['volume_ratio']:.0f}x avg volume, "
                f"price {s['price_change_pct']:+.1f}%, {direction}"
            )
        elif s["type"] == "large_move":
            lines.append(
                f"  {s['symbol']} LARGE {s['direction'].upper()}: {s['change_pct']:+.1f}% in 24h @ {s['current_price']:.2f}"
            )

    return "\n".join(lines) if len(lines) > 1 else ""
