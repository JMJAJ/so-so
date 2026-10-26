"""Price simulation: point-in-time, calibrated bands on random walks, bracket odds, account
simulation with stops, and what-if scenarios that find planted effects and ignore noise."""

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from conftest import write_bars
from nexus import data, jobs, paper
from nexus.agent import charts, tools
from nexus.research import simulate


def test_fan_is_ordered_and_starts_at_zero(synthetic):
    sim = simulate.asset("etf:spy", 20, paths=2000, seed=1)
    assert sim["fan"][0] == {"day": 0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    for row in sim["fan"][1:]:
        assert row["p10"] < row["p25"] < row["p50"] < row["p75"] < row["p90"]
    assert len(sim["fan"]) == 21 and 0 < sim["p_up"] < 1 and sim["var95"] < sim["median"]
    assert sim["typical_drawdown"] <= 0


def test_simulation_is_point_in_time(synthetic):
    as_of = data.closes().index[1000]
    before = simulate.asset("stock:aapl", 20, paths=500, as_of=as_of, seed=3, with_check=False)
    # Rewrite everything after as_of: the simulation at as_of must not change.
    later = synthetic[(synthetic["instrument_id"] == "stock:aapl") & (pd.to_datetime(synthetic["date"]) > as_of)].copy()
    later["close"] *= 3.0
    write_bars(later)
    after = simulate.asset("stock:aapl", 20, paths=500, as_of=as_of, seed=3, with_check=False)
    assert before["fan"] == after["fan"] and before["as_of"] == as_of.date().isoformat()


def test_bracket_odds_add_up(synthetic):
    price = data.closes()["etf:gld"].dropna().iloc[-1]
    near_target = simulate.asset("etf:gld", 20, paths=2000, direction="long", stop=price * 0.80,
                                 target=price * 1.01, seed=2)["bracket"]
    assert near_target["p_target"] > near_target["p_stop"]
    assert near_target["p_target"] + near_target["p_stop"] + near_target["p_neither"] == pytest.approx(1.0, abs=1e-3)
    short = simulate.asset("etf:gld", 20, paths=2000, direction="short", stop=price * 1.01,
                           target=price * 0.80, seed=2)["bracket"]
    assert short["p_stop"] > short["p_target"]


def test_bands_match_reality_on_random_walks(synthetic):
    summary = simulate.check(horizon=20, years=4, every=10, paths=800, ids=("etf:spy", "etf:gld", "stock:aapl"))
    overall = summary["overall"]
    assert overall["n"] >= 150
    assert 0.72 <= overall["in80"] <= 0.88 and 0.40 <= overall["in50"] <= 0.60
    assert simulate.coverage("etf", 20)["scope"] == "etf assets"
    assert simulate.asset("etf:spy", 20, paths=200, seed=1)["check"]["n"] >= 30


def test_portfolio_simulation_applies_stops_and_splits_risk(synthetic):
    assert simulate.portfolio(20, paths=500)["fan"] is None
    spy = data.closes()["etf:spy"].dropna().iloc[-1]
    tlt = data.closes()["etf:tlt"].dropna().iloc[-1]
    paper.open_position("etf:spy", "long", stop=spy * 0.97, target=spy * 1.06, expires_at=None, quantity=2)
    paper.open_position("etf:tlt", "short", stop=tlt * 1.05, target=None, expires_at=None, quantity=3)
    paper.monitor()
    sim = simulate.portfolio(20, paths=3000, seed=4)
    rows = {r["symbol"]: r for r in sim["positions"]}
    assert set(rows) == {"SPY", "TLT"}
    assert sum(r["risk_share"] for r in rows.values()) == pytest.approx(1.0, abs=1e-6)
    assert rows["SPY"]["p_stop"] > 0 and rows["SPY"]["p_stop"] + rows["SPY"]["p_target"] <= 1
    # A stopped-out long can't lose (much) more than the distance to its stop.
    assert rows["SPY"]["p5_pnl"] >= -(spy * 0.03 * 2) * 1.6
    assert sim["var95"] <= sim["median_pnl"] and 0 <= sim["p_loss"] <= 1


def _plant_shocks(frame: pd.DataFrame, every: int = 60) -> pd.DataFrame:
    """SPY drops 10% over 5 sessions every `every` sessions; GLD then rises 10% over the next 20."""
    frame = frame.copy()
    dates = sorted(frame["date"].unique())
    spy_factor = pd.Series(1.0, index=dates)
    gld_factor = pd.Series(1.0, index=dates)
    for start in range(300, len(dates) - 40, every):
        for i in range(5):
            spy_factor.iloc[start + i:] *= 0.9 ** 0.2
        for i in range(20):
            gld_factor.iloc[start + 5 + i:] *= 1.1 ** 0.05
    for instrument_id, factor in (("etf:spy", spy_factor), ("etf:gld", gld_factor)):
        mask = frame["instrument_id"] == instrument_id
        frame.loc[mask, "close"] = frame.loc[mask, "close"] * frame.loc[mask, "date"].map(factor).to_numpy()
    return frame


def test_scenario_finds_planted_effect_and_not_noise(synthetic):
    write_bars(_plant_shocks(synthetic))
    result = simulate.scenario("etf:spy", -0.08, 5, 20, ["etf:gld", "etf:tlt", "stock:jpm"])
    rows = {r["symbol"]: r for r in result["assets"]}
    assert result["occurrences"] >= 12
    assert rows["GLD"]["reliable"] and rows["GLD"]["edge"] > 0.05
    assert not rows["TLT"]["reliable"] and not rows["JPM"]["reliable"]
    with pytest.raises(ValueError):
        simulate.scenario("etf:spy", None)


def test_scenario_counts_effect_on_open_positions(synthetic):
    write_bars(_plant_shocks(synthetic))
    gld = data.closes()["etf:gld"].dropna().iloc[-1]
    paper.open_position("etf:gld", "short", stop=gld * 1.2, target=None, expires_at=None, quantity=1)
    paper.monitor()
    result = simulate.scenario("etf:spy", -0.08, 5, 20)
    assert result["assets"][0]["symbol"] == "GLD" and result["assets"][0]["position"] == "short"
    assert result["account_effect"] < 0  # the planted GLD rally hurts a GLD short


def test_tools_and_charts(synthetic):
    text, is_error = tools.call("simulate", {"instrument": "SPY", "horizon": 10})
    assert not is_error, text
    result = json.loads(text)
    assert [row["day"] for row in result["fan"]] == [5, 10] and "not a forecast" in result["reading"]
    text, is_error = tools.call("scenario", {"driver": "SPY", "move": -0.05})
    assert not is_error, text
    chart = charts.show_chart("simulation", instrument="GLD", horizon=10)
    assert chart["chart"]["kind"] == "fan" and len(chart["chart"]["fan"]) == 11
    assert "not yet checked" in chart["chart"]["note"]
    assert charts.show_chart("scenario", driver="SPY", move=-0.05)["chart"]["kind"] == "bar"
    with pytest.raises(ValueError, match="No open positions"):
        charts.show_chart("portfolio_sim")


def test_simulation_api(synthetic, monkeypatch):
    monkeypatch.setattr(jobs, "run_async", lambda name: None)
    from nexus.api import app

    with TestClient(app) as client:
        for path in ["/api/assets/etf:spy/simulate?horizon=10", "/api/assets/etf:spy/simulate?similar=true",
                     "/api/portfolio/simulate", "/api/scenarios", "/api/scenario?driver=SPY&move=-0.05",
                     "/api/scenario?driver=rate_hike", "/api/simulation/check"]:
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.text[:300]}"
        assert client.get("/api/scenario?driver=SPY").status_code == 400
        assert np.isfinite(client.get("/api/assets/etf:spy/simulate").json()["p_up"])
