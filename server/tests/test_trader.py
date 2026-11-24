"""Shock reactions, evidence-sized calls and the live event trader."""

import json

import numpy as np
import pandas as pd
import pytest

from conftest import write_bars
from nexus import config, db, paper
from nexus.agent import tools, trader
from nexus.research import probability, reaction


def _series(n: int = 2500, seed: int = 3, drift_after_shock: float = 0.0) -> pd.Series:
    """Random walk with 2.5% shocks every ~40 sessions; after each, `drift_after_shock` per day for 5 days."""
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0, 0.01, n)
    for i in range(80, n - 6, 40):
        ret[i] = 0.035 if (i // 40) % 2 else -0.035
        ret[i + 1:i + 6] += drift_after_shock * np.sign(ret[i])
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=n)
    return pd.Series(100 * np.exp(np.cumsum(ret)), index=dates)


def _write(instrument_id: str, close: pd.Series) -> None:
    rows = [(instrument_id, d.date().isoformat(), c, c * 1.005, c * 0.995, c, 1e6) for d, c in close.items()]
    write_bars(pd.DataFrame(rows, columns=["instrument_id", "date", "open", "high", "low", "close", "volume"]))


def test_shock_z_is_point_in_time():
    close = _series()
    z = reaction.zscores(close)
    changed = close.copy()
    changed.iloc[1500:] *= 1.5  # rewrite the future
    assert z.iloc[:1500].equals(reaction.zscores(changed).iloc[:1500])


def test_shocks_are_declustered():
    close = _series()
    days = reaction.shock_days(close, "up")
    gaps = np.diff([close.index.get_loc(d) for d in days])
    assert len(days) > 10 and gaps.min() > reaction.COOLDOWN


def test_planted_continuation_is_reliable(nexus_db):
    _write("stock:nvda", _series(drift_after_shock=0.006))
    result = reaction.reaction("stock:nvda", "up")
    assert result["reliable_horizons"], result
    best = result["horizons"][result["reliable_horizons"][0]]
    assert best["pattern"] == "continuation" and best["edge"] > 0
    assert reaction.trade_direction(result, 5)[0] == "long"
    down = reaction.reaction("stock:nvda", "down")
    assert reaction.trade_direction(down, 5)[0] == "short"


def test_noise_shocks_are_not_reliable(nexus_db):
    _write("stock:nvda", _series(drift_after_shock=0.0))
    result = reaction.reaction("stock:nvda", "up")
    assert not result["reliable_horizons"]
    assert "noise" in result["verdict"]


def test_live_shock_conditions_the_probability(nexus_db):
    close = _series(drift_after_shock=0.006)
    _write("stock:nvda", close)
    quote = {"price": float(close.iloc[-1]) * 1.035, "change_pct": 3.5}
    shock = reaction.current_shock("stock:nvda", quote)
    assert shock["is_shock"] and shock["side"] == "up"
    long = probability.evidence_probability("stock:nvda", "long", 5, 0.03, 0.05, None, quote)
    short = probability.evidence_probability("stock:nvda", "short", 5, 0.03, 0.05, None, quote)
    assert "shock_reaction" in long["evidence_kinds"] and long["has_evidence"]
    assert not short["has_evidence"] and short["probability"] < long["probability"]
    assert long["shock"]["z"] > 2
    quiet = probability.evidence_probability("stock:nvda", "long", 5, 0.03, 0.05, None, {"change_pct": 0.1})
    assert quiet["shock"] is None or not quiet["has_evidence"]


def test_bad_print_is_flagged(nexus_db):
    close = _series()
    close.iloc[-2] *= 0.85  # one bad bar: -15% then +17%
    _write("stock:nvda", close)
    shock = reaction.current_shock("stock:nvda", None)
    assert shock["warnings"]


def test_size_tiers():
    base = {"has_evidence": False, "probability": 0.52, "evidence_kinds": []}
    assert tools.size_tier(base)[:2] == ("base_rate", 0.35)
    one = {"has_evidence": True, "probability": 0.54, "evidence_kinds": ["shock_reaction"]}
    assert tools.size_tier(one)[0] == "tactical"
    two = {"has_evidence": True, "probability": 0.54, "evidence_kinds": ["shock_reaction", "event_study"]}
    assert tools.size_tier(two)[0] == "core"
    assert tools.size_tier(two, override=True)[0] == "override"


def test_risk_mult_scales_position_size():
    from nexus import universe

    item = universe.require("stock:aapl")
    full = paper.size_for(item, 100.0, 95.0, 100_000)
    small = paper.size_for(item, 100.0, 95.0, 100_000, 0.35)
    assert small == pytest.approx(int(full * 0.35), abs=1)


def test_base_rate_call_is_recorded_small(synthetic, monkeypatch):
    def fake(instrument_id, direction, horizon_days, stop_pct, target_pct, snapshot=None, quote=None):
        return {"probability": 0.52, "base": 0.52, "raw": 0.52, "expected_return": 0.004, "avg_win": target_pct,
                "avg_loss": stop_pct, "horizon": 5, "has_evidence": False, "evidence_kinds": [], "shock": None,
                "components": [], "calibration": {"k": 1.0, "basis": "test"}, "explanation": "test"}

    monkeypatch.setattr(probability, "evidence_probability", fake)
    price = db.one("SELECT close FROM bars WHERE instrument_id='stock:aapl' ORDER BY date DESC LIMIT 1")["close"]
    proposal = {"instrument_id": "stock:aapl", "direction": "long", "horizon_days": 3, "stop": price * 0.96,
                "target": price * 1.07, "thesis": "News-driven tactical long with a short horizon.",
                "evidence": [{"type": "news", "summary": "headline"}]}
    text, is_error = tools.call("propose_recommendation", proposal, extra={"_source": "chat"})
    assert not is_error, text
    assert json.loads(text)["size"].startswith("base_rate")
    rec = db.one("SELECT size_tier, risk_mult, horizon_days FROM recommendations")
    assert rec["size_tier"] == "base_rate" and rec["risk_mult"] == 0.35 and rec["horizon_days"] == 3


@pytest.fixture()
def no_threads(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, args=(), **_):
            started.append(args)

        def start(self):
            pass

    from nexus import jobs

    monkeypatch.setattr(trader.threading, "Thread", FakeThread)
    monkeypatch.setattr(jobs, "llm_ready", lambda: True)
    monkeypatch.setattr(jobs, "has_data", lambda: True)
    trader._seen.clear()
    trader._started.clear()
    return started


def test_trigger_once_per_day_and_side(nexus_db, no_threads):
    assert trader.trigger("stock:nvda", "news", side="up")
    assert not trader.trigger("stock:nvda", "same news again", side="up")
    assert trader.trigger("stock:nvda", "reversal", side="down")
    assert not trader.trigger("index:vix", "research only", side="up")
    assert len(no_threads) == 2


def test_trigger_rate_limit_and_switch(nexus_db, no_threads):
    config.set_many({"event_trade_max_per_hour": "2"})
    assert trader.trigger("stock:aapl", "a", side="up") and trader.trigger("stock:msft", "b", side="up")
    assert not trader.trigger("stock:jpm", "c", side="up")
    config.set_many({"event_trader": "false", "event_trade_max_per_hour": "6"})
    assert not trader.trigger("stock:xom", "d", side="up")


def test_alert_triggers_runs_for_tagged_assets(synthetic, no_threads):
    alert = {"id": "n1", "title": "NVIDIA CEO steps down", "level": 3, "kinds": ["management"], "source": "wire",
             "tickers": ["stock:nvda", "index:vix"], "moves": {"stock:nvda": {"price": 190.0, "change_pct": -6.0}}}
    assert trader.on_alerts([alert]) == 1
    minor = {**alert, "id": "n2", "level": 1, "tickers": ["stock:aapl"], "moves": {}}
    assert trader.on_alerts([minor]) == 0
    instrument_id, reason, review = no_threads[0]
    assert instrument_id == "stock:nvda" and "CEO" in reason and not review
