"""Regular vs extended-hours split of US 1-minute bars (offline)."""

import pandas as pd

from nexus import universe
from nexus.ingest.prices import split_sessions

NVDA = universe.resolve("stock:nvda")


def _bars(*points: tuple[str, float]) -> pd.Series:
    index = pd.DatetimeIndex([pd.Timestamp(ts, tz="America/New_York") for ts, _ in points])
    return pd.Series([price for _, price in points], index=index)


def test_after_hours_trade_is_separate_from_regular_close():
    closes = _bars(("2026-11-24 15:59", 155.48), ("2026-11-24 16:30", 153.0), ("2026-11-24 19:59", 151.95))
    regular, extended = split_sessions(NVDA, closes)
    assert regular[0] == 155.48
    assert extended[0] == 151.95 and extended[2] == "after-hours"


def test_pre_market_next_day():
    closes = _bars(("2026-11-24 15:59", 155.48), ("2026-11-25 07:00", 158.0))
    regular, extended = split_sessions(NVDA, closes)
    assert regular[0] == 155.48
    assert extended[0] == 158.0 and extended[2] == "pre-market"


def test_regular_session_has_no_extended_quote():
    closes = _bars(("2026-11-25 08:00", 158.0), ("2026-11-25 10:15", 157.2))
    regular, extended = split_sessions(NVDA, closes)
    assert regular[0] == 157.2
    assert extended is None


def test_only_extended_bars_gives_no_regular_price():
    regular, extended = split_sessions(NVDA, _bars(("2026-11-25 05:00", 158.0)))
    assert regular is None
    assert extended[2] == "pre-market"
