"""Research engine: point-in-time correctness and that real effects are detected."""

import numpy as np
import pandas as pd

from conftest import make_bars, write_bars
from nexus import data, db
from nexus.research import analogs, backtest, event_study, signals
from nexus.research.features import asset_features


def test_features_do_not_look_ahead(synthetic):
    close = data.closes()["stock:aapl"].dropna()
    full = asset_features(close)
    cut = close.index[900]
    truncated = asset_features(close[close.index <= cut])
    pd.testing.assert_series_equal(full.loc[cut], truncated.loc[cut], check_names=False)


def _plant_events(frame: pd.DataFrame, event_type: str, target: str, bump: float, every: int = 60) -> list[str]:
    """Insert macro events and make `target` drift by `bump` over the 20 sessions after each."""
    dates = sorted(frame["date"].unique())
    planted = dates[300:-60:every]
    closes = frame[frame["instrument_id"] == target].set_index("date")["close"].copy()
    multiplier = pd.Series(1.0, index=closes.index)
    for day in planted:
        start = dates.index(day)
        for k in range(1, 21):
            multiplier.loc[dates[start + k]:] *= (1 + bump) ** (1 / 20)
    adjusted = frame.copy()
    mask = adjusted["instrument_id"] == target
    adjusted.loc[mask, "close"] = (closes * multiplier).values
    write_bars(adjusted)
    db.executemany(
        "INSERT INTO events(id,type,instrument_id,scope,date,title,source) VALUES(?,?,?,?,?,?,?)",
        [(f"ev{i}", event_type, None, "macro", day, f"planted {i}", "test") for i, day in enumerate(planted)],
    )
    data.invalidate()
    return planted


def test_event_study_finds_planted_effect(synthetic):
    _plant_events(synthetic, "rate_cut", "etf:gld", bump=0.10)
    assert event_study.compute_all() > 0
    impact = event_study.impact("rate_cut", "etf:gld")
    assert impact is not None
    h20 = impact["horizons"][20]
    assert h20["edge"] > 0.06 and h20["t_stat"] > 2 and h20["hit_rate"] > 0.7
    # An unrelated asset shows no comparable effect.
    other = event_study.impact("rate_cut", "stock:jpm")["horizons"][20]
    assert abs(other["edge"]) < h20["edge"]


def test_event_signal_only_uses_known_outcomes(synthetic):
    planted = _plant_events(synthetic, "rate_cut", "etf:gld", bump=0.05)
    closes = data.closes()
    sig = signals.EventSignal(closes, horizon=20)
    first, later = pd.Timestamp(planted[0]), pd.Timestamp(planted[-1])
    values = sig.series("etf:gld", pd.DatetimeIndex([first, later]))
    assert values.iloc[0] == 0.0  # no earlier outcome was known at the first occurrence
    assert values.iloc[1] > 0.0  # by the last one, history says "bullish"


def test_analog_forecast_ignores_the_future(synthetic):
    dates = data.closes().index
    as_of = dates[1000]
    before = analogs.mean_forward_series("stock:msft", pd.DatetimeIndex([as_of]))
    tampered = synthetic.copy()
    future = (tampered["instrument_id"] == "stock:msft") & (tampered["date"] > as_of.date().isoformat())
    tampered.loc[future, "close"] *= 3.0
    write_bars(tampered)
    after = analogs.mean_forward_series("stock:msft", pd.DatetimeIndex([as_of]))
    assert np.isclose(before.iloc[0], after.iloc[0])


def test_backtest_finds_no_edge_in_noise(synthetic):
    result = backtest.run(years=10)
    assert result["classes"], "backtest should produce per-class results"
    for asset_class, stats in result["classes"].items():
        assert stats["has_edge"] is False, f"false edge found in random data for {asset_class}"
    stored = backtest.summary()
    assert {row["asset_class"] for row in stored} == set(result["classes"])


def test_predict_returns_rows_without_model(nexus_db):
    write_bars(make_bars(700))
    rows = signals.predict(["stock:aapl", "etf:spy"])
    assert {row["instrument_id"] for row in rows} == {"stock:aapl", "etf:spy"}
    for row in rows:
        assert 0 < row["prob_up"] < 1
        assert row["model_has_edge"] is False
