"""Prediction safeguards: FDR, beta adjustment, computed probabilities, replay, fact check,
news dedupe and correlated-risk limits."""

import numpy as np
import pandas as pd
import pytest

from conftest import write_bars
from nexus import config, data, db, paper
from nexus.agent import factcheck
from nexus.ingest import news
from nexus.research import event_study, probability, replay
from nexus.research.features import abnormal_forward, rolling_betas
from test_research import _plant_events


def test_benjamini_hochberg_matches_reference():
    q = event_study.benjamini_hochberg([0.01, 0.04, 0.03, 0.20])
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.20], rel=1e-4)
    assert event_study.benjamini_hochberg([]) == []


def test_noise_is_not_reliable(synthetic):
    # Pure random events on random walks: plenty of |t| > 2 by chance, none survive FDR + split-half.
    dates = sorted(synthetic["date"].unique())[300:-60:45]
    db.executemany("INSERT INTO events(id,type,instrument_id,scope,date,title,source) VALUES(?,?,?,?,?,?,?)",
                   [(f"n{i}", "rate_cut", None, "macro", d, "noise", "test") for i, d in enumerate(dates)])
    data.invalidate()
    event_study.compute_all()
    assert db.one("SELECT COUNT(*) c FROM event_impact WHERE reliable=1")["c"] == 0


def test_planted_effect_is_reliable(synthetic):
    _plant_events(synthetic, "rate_cut", "etf:gld", bump=0.10)
    event_study.compute_all()
    h20 = event_study.impact("rate_cut", "etf:gld")["horizons"][20]
    assert h20["reliable"] and h20["q_value"] <= event_study.FDR_Q and h20["stable"]
    assert any(r["event_type"] == "rate_cut" for r in event_study.strongest_for("etf:gld"))


def test_beta_adjustment_removes_market_move(synthetic):
    # A stock that is exactly 2x the market has zero abnormal return once beta is applied.
    spy = synthetic[synthetic["instrument_id"] == "etf:spy"].copy()
    lev = spy.copy()
    lev["instrument_id"] = "stock:aapl"
    returns = spy["close"].pct_change().fillna(0)
    lev["close"] = 150 * (1 + 2 * returns).cumprod()
    write_bars(pd.concat([synthetic[synthetic["instrument_id"] != "stock:aapl"], lev]))
    closes = data.closes()
    bench = {"stock:aapl": "etf:spy", "etf:spy": None}
    betas = rolling_betas(closes, bench)
    assert betas["stock:aapl"].dropna().iloc[-1] == pytest.approx(2.0, abs=0.05)
    abn = abnormal_forward(closes, 20, bench, betas)["stock:aapl"].dropna()
    raw = abnormal_forward(closes, 20, bench, betas * 0 + 1.0)["stock:aapl"].dropna()  # plain excess return
    assert abn.abs().mean() < 0.3 * raw.abs().mean()


def test_rolling_beta_is_point_in_time(synthetic):
    closes = data.closes()
    bench = {"stock:msft": "etf:spy"}
    full = rolling_betas(closes, bench)["stock:msft"]
    cut = closes.index[900]
    truncated = rolling_betas(closes[closes.index <= cut], bench)["stock:msft"]
    assert full.loc[cut] == pytest.approx(truncated.loc[cut])


def test_bracket_simulation_counts_stops_and_targets():
    days = pd.bdate_range("2020-01-01", periods=400)
    up = pd.DataFrame({"close": np.linspace(100, 300, 400)}, index=days)
    up["open"], up["high"], up["low"] = up["close"], up["close"] * 1.001, up["close"] * 0.999
    long = probability.simulate_bracket(up, "long", 20, 0.05, 0.03)
    short = probability.simulate_bracket(up, "short", 20, 0.05, 0.03)
    assert long["p_win"] == 1.0 and long["avg_win"] == pytest.approx(0.03, abs=0.005)
    assert short["p_win"] == 0.0
    assert probability.simulate_bracket(up.iloc[:40], "long", 20, 0.05, 0.03)["n"] < 30


def test_event_component_shrinks_and_never_helps_against_effect():
    assert probability.event_component(0.8, 10, "long", 0.05) == pytest.approx(0.5 + 0.3 * 10 / 30)
    assert probability.event_component(0.8, 10, "short", 0.05) <= 0.5
    assert probability.event_component(0.8, 1000, "long", 0.05) < 0.8


def test_calibration_shrinks_overconfident_evidence(nexus_db):
    assert probability.calibration_factor()[0] == 1.0
    rows = [("2020-01-01", "etf:spy", "long", "rate_cut", 20, 0.70, 0.50, 0.01 if i % 2 else -0.01, i % 2)
            for i in range(40)]
    db.executemany("INSERT INTO replay_calls(date,instrument_id,direction,event_type,horizon,probability,base,"
                   "realized_return,win) VALUES(?,?,?,?,?,?,?,?,?)", rows)
    k, basis = probability.calibration_factor()
    assert k == pytest.approx(0.0) and "replay" in basis


def test_survivorship_drift_is_removed_for_stocks(synthetic):
    frame, label = probability._ohlc(probability.universe.require("stock:nvda"))
    raw = data.ohlcv("stock:nvda", frame.index[0].date().isoformat())["close"]
    spy = data.ohlcv("etf:spy", frame.index[0].date().isoformat())["close"]
    adjusted_drift = frame["close"].pct_change().mean()
    assert "survivorship" in label
    assert abs(adjusted_drift - spy.pct_change().mean()) < abs(raw.pct_change().mean() - spy.pct_change().mean()) + 1e-5


def test_replay_is_point_in_time_and_records_calls(synthetic):
    planted = _plant_events(synthetic, "rate_cut", "etf:gld", bump=0.10, every=40)
    summary = replay.run()
    calls = db.rows("SELECT * FROM replay_calls WHERE instrument_id='etf:gld' ORDER BY date")
    assert summary["calls"] >= 1 and calls
    # The first call needs MIN_PRIOR earlier events whose 20-day outcome had already played out.
    first_allowed = pd.Timestamp(planted[replay.MIN_PRIOR])
    assert pd.Timestamp(calls[0]["date"]) >= first_allowed
    assert all(c["direction"] == "long" for c in calls)
    assert np.mean([c["win"] for c in calls]) > 0.6


def test_fact_check_flags_invented_numbers():
    blobs = ['{"n": 22, "t_stat": -2.93, "edge": 0.047, "hit_rate": 0.64}']
    good = factcheck.check("XLE fell after hot CPI: n=22, t -2.9, edge 4.7%, hit 64%.", blobs)
    assert good["ok"] and good["checked"] == 4
    bad = factcheck.check("Strong effect: n=40, t=3.5, up 12%.", blobs)
    assert not bad["ok"] and set(bad["unsupported"]) == {"n 40", "t 3.5", "12%"}
    assert "Fact check" in factcheck.note(bad) and factcheck.note({"checked": 0}) == ""


def test_duplicate_stories_are_marked(nexus_db):
    now = pd.Timestamp.now(tz="UTC")
    news.store_articles([
        {"title": "Fed cuts rates by 25 basis points, signals more easing ahead", "url": "https://a/1",
         "published_at": now.isoformat(), "provider": "rss"},
        {"title": "Fed cuts rates by 25 basis points and signals more easing ahead", "url": "https://b/2",
         "published_at": (now + pd.Timedelta(hours=3)).isoformat(), "provider": "rss"},
        {"title": "Oil jumps as OPEC agrees deeper output cuts", "url": "https://c/3",
         "published_at": (now + pd.Timedelta(hours=4)).isoformat(), "provider": "rss"},
    ])
    assert news.mark_duplicates() == 1
    rows = {r["url"]: r["duplicate_of"] for r in db.rows("SELECT url, duplicate_of FROM news")}
    assert rows["https://a/1"] is None and rows["https://b/2"] and rows["https://c/3"] is None
    assert news.mark_duplicates() == 0  # idempotent


def test_correlated_positions_count_as_one_bet(synthetic):
    # Make XOM a copy of XLE: short XLE + short XOM is the same oil bet.
    xle = synthetic[synthetic["instrument_id"] == "etf:xle"].copy()
    xom = xle.assign(instrument_id="stock:xom", close=xle["close"] * 1.25)
    write_bars(pd.concat([synthetic[synthetic["instrument_id"] != "stock:xom"], xom]))
    paper.open_position("etf:xle", "short", stop=xle["close"].iloc[-1] * 1.05, target=None, expires_at=None)
    same = paper.correlated_risk("stock:xom", "short")
    assert same["units"] == pytest.approx(2.0, abs=0.01) and same["same_bet"][0]["symbol"] == "XLE"
    assert paper.correlated_risk("stock:xom", "long")["units"] == 1.0  # a hedge, not the same bet
    config.set_many({"max_correlated_risk": "1.5"})
    with pytest.raises(ValueError, match="same bet as XLE short"):
        paper.open_position("stock:xom", "short", stop=xom["close"].iloc[-1] * 1.05, target=None, expires_at=None)
