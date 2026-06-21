"""
Market context engine — technical indicators, asset info, and news for the AI agent.
All data is cached to avoid hammering yfinance on every cycle.
"""

import time
import numpy as np
import pandas as pd
import yfinance as yf

from prices import pair_to_yfinance

# ── Caches ──

_hist_cache: dict[str, pd.DataFrame] = {}
_hist_cache_time: float = 0
HIST_CACHE_TTL = 300  # 5 minutes

_info_cache: dict[str, dict] = {}
_info_cache_time: float = 0
INFO_CACHE_TTL = 1800  # 30 minutes

_news_cache: dict[str, list[str]] = {}
_news_cache_time: float = 0
NEWS_CACHE_TTL = 900  # 15 minutes

# ── Technical Indicators ──

def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = _ema(series, 12)
    ema26 = _ema(series, 26)
    macd_line = ema12 - ema26
    signal = _ema(macd_line, 9)
    histogram = macd_line - signal
    return macd_line, signal, histogram

def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()

def _trend_label(sma20: float | None, sma50: float | None, price: float) -> str:
    if sma20 is None or sma50 is None:
        return "unknown"
    if price > sma20 > sma50:
        return "uptrend"
    if price < sma20 < sma50:
        return "downtrend"
    return "sideways"

# ── Data Fetching ──

def _fetch_history(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch 6-month daily OHLCV for all symbols in one batch."""
    global _hist_cache, _hist_cache_time

    now = time.time()
    if now - _hist_cache_time < HIST_CACHE_TTL and _hist_cache:
        return {s: _hist_cache[s] for s in symbols if s in _hist_cache}

    yf_map = {s: pair_to_yfinance(s) for s in symbols}
    yf_tickers = sorted(set(yf_map.values()))

    hist: dict[str, pd.DataFrame] = {}
    try:
        df = yf.download(
            yf_tickers,
            period="6mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        if df is not None and not df.empty:
            for yf_sym in yf_tickers:
                try:
                    if len(yf_tickers) == 1:
                        sub = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    else:
                        if yf_sym not in df.columns.get_level_values(0):
                            continue
                        sub = df[yf_sym][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    if len(sub) < 20:
                        continue
                    hist[yf_sym] = sub
                except Exception as e:
                    print(f"[context] History parse error for {yf_sym}: {e}")
    except Exception as e:
        print(f"[context] yf.download error: {e}")

    reverse: dict[str, list[str]] = {}
    for orig, yf_sym in yf_map.items():
        reverse.setdefault(yf_sym, []).append(orig)

    result: dict[str, pd.DataFrame] = {}
    for yf_sym, frame in hist.items():
        for orig in reverse.get(yf_sym, []):
            result[orig] = frame

    _hist_cache = result
    _hist_cache_time = now
    return {s: result[s] for s in symbols if s in result}

def _fetch_info(symbols: list[str]) -> dict[str, dict]:
    """Fetch asset info (sector, PE, market cap) — cached 30 min."""
    global _info_cache, _info_cache_time

    now = time.time()
    if now - _info_cache_time < INFO_CACHE_TTL and _info_cache:
        return {s: _info_cache[s] for s in symbols if s in _info_cache}

    result: dict[str, dict] = {}
    for sym in symbols:
        yf_sym = pair_to_yfinance(sym)
        try:
            t = yf.Ticker(yf_sym)
            info = t.info or {}
            result[sym] = {
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "market_cap": info.get("marketCap"),
                "forward_pe": info.get("forwardPE"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "avg_volume": info.get("averageVolume"),
                "short_name": info.get("shortName"),
            }
        except Exception:
            result[sym] = {}

    _info_cache = result
    _info_cache_time = now
    return {s: result.get(s, {}) for s in symbols}

def _fetch_news(symbols: list[str], max_per_symbol: int = 3) -> dict[str, list[str]]:
    """Fetch recent news headlines — cached 15 min."""
    global _news_cache, _news_cache_time

    now = time.time()
    if now - _news_cache_time < NEWS_CACHE_TTL and _news_cache:
        return {s: _news_cache[s] for s in symbols if s in _news_cache}

    result: dict[str, list[str]] = {}
    for sym in symbols:
        yf_sym = pair_to_yfinance(sym)
        try:
            t = yf.Ticker(yf_sym)
            raw_news = t.news or []
            headlines = []
            for n in raw_news[:max_per_symbol]:
                title = n.get("title", "")
                if title:
                    headlines.append(title)
            if headlines:
                result[sym] = headlines
        except Exception:
            pass

    _news_cache = result
    _news_cache_time = now
    return {s: result.get(s, []) for s in symbols}

_BULLISH_WORDS = {
    "surge", "soar", "rally", "jump", "gain", "rise", "climb", "beat", "upgrade",
    "bullish", "breakout", "record", "high", "growth", "profit", "strong", "boost",
    "outperform", "buy", "optimistic", "recovery", "expand", "boom", "upbeat",
    "upside", "momentum", "uptrend", "demand", "innovation", "approval", "deal",
}
_BEARISH_WORDS = {
    "crash", "plunge", "drop", "fall", "loss", "decline", "slump", "miss", "downgrade",
    "bearish", "breakdown", "record low", "recession", "deficit", "weak", "cut",
    "underperform", "sell", "pessimistic", "downturn", "shrink", "bust", "gloomy",
    "downside", "risk", "downtrend", "warning", "lawsuit", "fraud", "investigate",
    "sanction", "ban", "tariff", "default", "bankruptcy",
}

def _score_sentiment(headlines: list[str]) -> float:
    """Score headlines from -1 (very bearish) to +1 (very bullish). Returns 0 if no headlines."""
    if not headlines:
        return 0.0
    total = 0.0
    for h in headlines:
        words = set(h.lower().split())
        bull = len(words & _BULLISH_WORDS)
        bear = len(words & _BEARISH_WORDS)
        total += (bull - bear)
    max_possible = len(headlines) * 3
    if max_possible == 0:
        return 0.0
    return max(-1.0, min(1.0, total / max_possible))

# ── Compute Technicals ──

def _compute_technicals(df: pd.DataFrame) -> dict | None:
    """Calculate all technical indicators from OHLCV DataFrame."""
    try:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        price = float(close.iloc[-1])

        sma20_s = _sma(close, 20)
        sma50_s = _sma(close, 50)
        rsi_s = _rsi(close)
        macd_line, signal, histogram = _macd(close)
        atr_s = _atr(high, low, close)

        sma20 = float(sma20_s.iloc[-1]) if not pd.isna(sma20_s.iloc[-1]) else None
        sma50 = float(sma50_s.iloc[-1]) if len(sma50_s) >= 50 and not pd.isna(sma50_s.iloc[-1]) else None
        rsi = float(rsi_s.iloc[-1]) if not pd.isna(rsi_s.iloc[-1]) else None
        macd_val = float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else None
        macd_sig = float(signal.iloc[-1]) if not pd.isna(signal.iloc[-1]) else None
        atr_val = float(atr_s.iloc[-1]) if not pd.isna(atr_s.iloc[-1]) else None

        n = len(close)
        ret_1w = ((price / float(close.iloc[-6])) - 1) * 100 if n >= 6 else None
        ret_1m = ((price / float(close.iloc[-22])) - 1) * 100 if n >= 22 else None
        ret_3m = ((price / float(close.iloc[-66])) - 1) * 100 if n >= 66 else None

        high_52w = float(high.max()) if n >= 50 else None
        low_52w = float(low.min()) if n >= 50 else None
        from_high = ((price / high_52w) - 1) * 100 if high_52w else None
        from_low = ((price / low_52w) - 1) * 100 if low_52w else None

        macd_signal = None
        if macd_val is not None and macd_sig is not None:
            if macd_val > macd_sig:
                macd_signal = "bullish"
            elif macd_val < macd_sig:
                macd_signal = "bearish"
            else:
                macd_signal = "neutral"

        atr_pct = (atr_val / price * 100) if (atr_val and price) else None

        return {
            "price": price,
            "sma20": sma20,
            "sma50": sma50,
            "rsi": rsi,
            "macd": macd_val,
            "macd_signal": macd_sig,
            "macd_cross": macd_signal,
            "atr": atr_val,
            "atr_pct": atr_pct,
            "trend": _trend_label(sma20, sma50, price),
            "ret_1w": ret_1w,
            "ret_1m": ret_1m,
            "ret_3m": ret_3m,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "from_high": from_high,
            "from_low": from_low,
        }
    except Exception as e:
        print(f"[context] Technicals error: {e}")
        return None

# ── Public API ──

def build_market_context(symbols: list[str], asset_classes: list[str]) -> str:
    """
    Build a complete market context string for the AI agent.
    Returns formatted text with market overview, technicals, news, and asset info.
    """
    history = _fetch_history(symbols)
    info_data = _fetch_info(symbols)
    news_data = _fetch_news(symbols)

    sections = []

    # ── Market Overview ──
    overview_indices = ["US500", "NAS100", "US30", "VIX"]
    overview_lines = ["=== MARKET OVERVIEW ==="]
    for idx in overview_indices:
        h = history.get(idx)
        if h is not None:
            tech = _compute_technicals(h)
            if tech:
                label = idx
                if idx == "VIX":
                    overview_lines.append(
                        f"  {label}: {tech['price']:.2f} (1w: {tech.get('ret_1w', 0):+.1f}%, "
                        f"trend: {tech['trend']})"
                    )
                else:
                    overview_lines.append(
                        f"  {label}: {tech['price']:,.2f} (1w: {tech.get('ret_1w', 0):+.1f}%, "
                        f"1m: {tech.get('ret_1m', 0):+.1f}%, trend: {tech['trend']}, "
                        f"RSI: {tech.get('rsi', 0):.0f})"
                    )
    if len(overview_lines) > 1:
        sections.append("\n".join(overview_lines))

    # ── Technicals per symbol (scored and filtered) ──
    tech_lines = ["=== TECHNICAL ANALYSIS ==="]
    sym_class = dict(zip(symbols, asset_classes))
    scored_symbols: list[tuple[float, str, dict, int, int]] = []

    from agent import is_market_open

    for sym in symbols:
        h = history.get(sym)
        if h is None:
            continue
        tech = _compute_technicals(h)
        if not tech:
            continue

        # Compute LONG score
        long_score = 0
        trend = tech.get("trend", "unknown")
        rsi = tech.get("rsi")
        macd_cross = tech.get("macd_cross")
        ret_1m = tech.get("ret_1m")

        if ret_1m is not None and ret_1m > 1:
            long_score += 2
        if trend == "uptrend":
            long_score += 1
        if rsi is not None and 40 < rsi < 70:
            long_score += 1
        if tech.get("atr_pct") and tech["atr_pct"] > 1:
            long_score += 1
        headlines = news_data.get(sym, [])
        sentiment = _score_sentiment(headlines)
        if sentiment >= 0:
            long_score += 1

        # Compute SHORT score
        short_score = 0
        if ret_1m is not None and ret_1m < -1:
            short_score += 2
        if trend == "downtrend":
            short_score += 1
        if rsi is not None and 30 < rsi < 60:
            short_score += 1
        if tech.get("atr_pct") and tech["atr_pct"] > 1:
            short_score += 1
        if sentiment <= 0:
            short_score += 1

        best_score = max(long_score, short_score)
        # Boost open-market symbols so they get prioritized
        ac = sym_class.get(sym, "")
        if is_market_open(ac):
            best_score += 3
        scored_symbols.append((best_score, sym, tech, long_score, short_score))

    scored_symbols.sort(key=lambda x: -x[0])
    top_symbols = scored_symbols[:15]

    for best_score, sym, tech, long_score, short_score in top_symbols:
        ac = sym_class.get(sym, "")
        parts = [f"  {sym} ({ac})"]
        parts.append(f"${tech['price']:.4f}" if tech["price"] < 1000 else f"${tech['price']:,.2f}")
        parts.append(f"long={long_score}/6 short={short_score}/6")

        if tech["trend"] != "unknown":
            parts.append(f"trend={tech['trend']}")
        if tech["rsi"] is not None:
            rsi_label = ""
            if tech["rsi"] > 70:
                rsi_label = " OVERBOUGHT"
            elif tech["rsi"] < 30:
                rsi_label = " OVERSOLD"
            parts.append(f"RSI={tech['rsi']:.0f}{rsi_label}")
        if tech["macd_cross"]:
            parts.append(f"MACD={tech['macd_cross']}")
        if tech["ret_1w"] is not None:
            parts.append(f"1w={tech['ret_1w']:+.1f}%")
        if tech["ret_1m"] is not None:
            parts.append(f"1m={tech['ret_1m']:+.1f}%")
        if tech["ret_3m"] is not None:
            parts.append(f"3m={tech['ret_3m']:+.1f}%")
        if tech["from_high"] is not None:
            parts.append(f"from52wh={tech['from_high']:+.1f}%")
        if tech["from_low"] is not None:
            parts.append(f"from52wl={tech['from_low']:+.1f}%")
        if tech["atr_pct"] is not None:
            parts.append(f"ATR={tech['atr_pct']:.1f}%")
        if tech["sma20"] is not None:
            above_below = "above" if tech["price"] > tech["sma20"] else "below"
            parts.append(f"{above_below} SMA20")
        if tech["sma50"] is not None:
            above_below = "above" if tech["price"] > tech["sma50"] else "below"
            parts.append(f"{above_below} SMA50")

        headlines = news_data.get(sym, [])
        sentiment = _score_sentiment(headlines)
        parts.append(f"news_sentiment={sentiment:+.2f}")

        tech_lines.append(" | ".join(parts))

    if len(tech_lines) > 1:
        sections.append("\n".join(tech_lines))

    # ── News (limited) ──
    all_news = []
    for sym in symbols:
        headlines = news_data.get(sym, [])
        for h in headlines:
            all_news.append(f"  [{sym}] {h}")
    if all_news:
        news_section = ["=== RECENT NEWS ==="] + all_news[:10]
        sections.append("\n".join(news_section))

    # ── Asset Info (top stocks only) ──
    stock_syms = [s for s, ac in zip(symbols, asset_classes) if ac == "stock"]
    info_lines = ["=== ASSET FUNDAMENTALS ==="]
    for sym in stock_syms[:10]:
        inf = info_data.get(sym, {})
        parts = [f"  {sym}"]
        if inf.get("sector"):
            parts.append(f"sector={inf['sector']}")
        if inf.get("market_cap"):
            mc = inf["market_cap"]
            if mc >= 1e12:
                parts.append(f"mcap=${mc/1e12:.1f}T")
            elif mc >= 1e9:
                parts.append(f"mcap=${mc/1e9:.0f}B")
            elif mc:
                parts.append(f"mcap=${mc/1e6:.0f}M")
        if inf.get("forward_pe") and inf["forward_pe"] > 0:
            parts.append(f"fwdPE={inf['forward_pe']:.1f}")
        if len(parts) > 1:
            info_lines.append(" | ".join(parts))
    if len(info_lines) > 1:
        sections.append("\n".join(info_lines))

    # ── Whale Activity ──
    crypto_syms = [s for s, ac in zip(symbols, asset_classes) if ac == "crypto"]
    if crypto_syms:
        import whales
        whale_signals = whales.get_whale_signals(crypto_syms)
        whale_section = whales.format_whale_context(whale_signals)
        if whale_section:
            sections.append(whale_section)

    return "\n\n".join(sections)
