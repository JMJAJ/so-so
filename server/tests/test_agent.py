"""Agent loop, tools, chat persistence and the HTTP API, with a scripted LLM."""

import json

import pytest
from fastapi.testclient import TestClient

from nexus import config, db, jobs, llm, recommendations
from nexus.agent import analyst, chat, tools
from nexus.llm import Reply
from nexus.llm.anthropic_provider import AnthropicProvider
from nexus.llm.openai_compat import OpenAICompatProvider
from nexus.research import probability


class ScriptedProvider:
    """Plays back a fixed sequence of replies and records what it was sent."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, tools=None, *, max_tokens=16000, on_text=None, effort=None):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        reply = self.replies.pop(0)
        if on_text and reply.text:
            on_text(reply.text)
        return reply


def _price(instrument_id: str) -> float:
    return db.one("SELECT close FROM bars WHERE instrument_id=? ORDER BY date DESC LIMIT 1", (instrument_id,))["close"]


def _proposal(instrument_id: str) -> dict:
    price = _price(instrument_id)
    return {
        "instrument_id": instrument_id, "direction": "long", "horizon_days": 20, "stop": price * 0.94,
        "target": price * 1.1, "probability": 0.58, "confidence": "medium",
        "thesis": "Scripted thesis with enough words to be valid.",
        "evidence": [{"type": "analogs", "summary": "20 analogs, 65% up"}],
    }


def _computed(p: float, ev: float, evidence: bool = False):
    def fake(instrument_id, direction, horizon_days, stop_pct, target_pct, snapshot=None):
        return {"probability": p, "base": 0.5, "raw": p, "expected_return": ev, "avg_win": target_pct,
                "avg_loss": stop_pct, "horizon": 20, "has_evidence": evidence,
                "components": [{"source": "bracket base rate (test)", "p": 0.5}],
                "calibration": {"k": 1.0, "basis": "test"}, "explanation": f"test bracket won {p:.0%}"}
    return fake


@pytest.fixture()
def favourable(monkeypatch):
    """The synthetic random walks have no edge, so stub the probability engine for plumbing tests."""
    monkeypatch.setattr(probability, "evidence_probability", _computed(0.58, 0.01))


def test_every_tool_runs_on_real_data(synthetic):
    calls = {
        "scan_universe": {}, "asset_snapshot": {"instrument": "AAPL"}, "recent_news": {},
        "event_study": {"event_type": "rate_cut", "instrument": "etf:gld"}, "event_effects": {"instrument": "gld"},
        "analogs": {"instrument": "stock:msft"}, "correlations": {"instrument": "etf:spy"}, "macro_regime": {},
        "portfolio": {}, "track_record": {}, "model_validation": {}, "list_recommendations": {"status": "all"},
    }
    for name, args in calls.items():
        text, is_error = tools.call(name, args)
        assert not is_error, f"{name}: {text}"
        json.loads(text)
    text, is_error = tools.call("asset_snapshot", {"instrument": "NOT_A_TICKER"})
    assert is_error and "Unknown instrument" in text


def test_chat_runs_tools_and_records_recommendation(synthetic, favourable, monkeypatch):
    provider = ScriptedProvider([
        Reply(text="Checking.", tool_calls=[{"id": "t1", "name": "asset_snapshot", "input": {"instrument": "NVDA"}}]),
        Reply(text="", tool_calls=[{"id": "t2", "name": "propose_recommendation", "input": _proposal("stock:nvda")}]),
        Reply(text="Recorded a long NVDA call."),
    ])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    events = []
    result = chat.send(None, "/recommend NVDA", on_event=events.append)
    assert result["text"] == "Recorded a long NVDA call."
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["asset_snapshot", "propose_recommendation"]
    rec = db.one("SELECT * FROM recommendations")
    assert rec["instrument_id"] == "stock:nvda" and rec["source"] == "chat"
    # The slash command was expanded for the model; the tool results were fed back.
    assert "Investigate NVDA" in provider.calls[0]["messages"][-1]["text"]
    assert provider.calls[1]["messages"][-1]["role"] == "tool"
    history = chat.public_messages(result["conversation_id"])
    assert history[0] == {"role": "user", "text": "/recommend NVDA"}


def test_chat_failure_leaves_replayable_history(synthetic, monkeypatch):
    class Broken(ScriptedProvider):
        def complete(self, *args, **kwargs):
            if self.calls:
                raise RuntimeError("provider down")
            return super().complete(*args, **kwargs)

    provider = Broken([Reply(text="", tool_calls=[{"id": "t1", "name": "portfolio", "input": {}}])])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    result = chat.send(None, "how is my portfolio?")
    stored = chat.history(result["conversation_id"])
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert not stored[-1]["tool_calls"]


def test_analyst_enforces_limits(synthetic, monkeypatch):
    good = _computed(0.58, 0.01)
    monkeypatch.setattr(probability, "evidence_probability",
                        lambda iid, *a, **k: _computed(0.45, -0.002)(iid, *a, **k) if iid == "stock:aapl" else good(iid, *a, **k))
    provider = ScriptedProvider([
        Reply(text="", tool_calls=[
            {"id": "a", "name": "propose_recommendation", "input": _proposal("stock:aapl")},
            {"id": "b", "name": "propose_recommendation", "input": _proposal("stock:msft")},
            {"id": "c", "name": "propose_recommendation", "input": _proposal("stock:jpm")},
        ]),
        Reply(text="Brief: one idea."),
    ])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    result = analyst.run(max_recs=1)
    assert result["recommendations"] == 1
    tool_results = provider.calls[1]["messages"][-1]["results"]
    assert "Not recorded (negative expected value)" in tool_results[0]["content"] and tool_results[0]["is_error"]
    assert not tool_results[1]["is_error"]
    assert "limit" in tool_results[2]["content"]
    run = db.one("SELECT * FROM runs")
    assert run["status"] == "completed" and run["summary"] == "Brief: one idea."


def test_message_conversion_round_trips():
    history = [
        {"role": "user", "text": "hi"},
        {"role": "assistant", "text": "looking", "tool_calls": [{"id": "x", "name": "portfolio", "input": {}}], "native": None},
        {"role": "tool", "results": [{"id": "x", "name": "portfolio", "content": "{}", "is_error": False}]},
    ]
    anthropic_msgs = AnthropicProvider._messages(AnthropicProvider.__new__(AnthropicProvider), history)
    assert anthropic_msgs[1]["content"][1]["type"] == "tool_use"
    assert anthropic_msgs[2]["content"][0]["tool_use_id"] == "x"
    openai_msgs = OpenAICompatProvider._messages("sys", history)
    assert openai_msgs[0]["role"] == "system"
    assert openai_msgs[2]["tool_calls"][0]["function"]["name"] == "portfolio"
    assert openai_msgs[3] == {"role": "tool", "tool_call_id": "x", "content": "{}"}


@pytest.fixture()
def client(synthetic, monkeypatch):
    monkeypatch.setattr(jobs, "run_async", lambda name: None)
    from nexus.api import app

    with TestClient(app) as test_client:
        yield test_client


def test_api_endpoints(client):
    for path in ["/api/status", "/api/dashboard", "/api/forecasts", "/api/assets/stock:aapl", "/api/events",
                 "/api/event-types", "/api/news", "/api/portfolio", "/api/track-record", "/api/models",
                 "/api/settings", "/api/jobs", "/api/runs", "/api/briefs", "/api/markets", "/api/universe"]:
        response = client.get(path)
        assert response.status_code == 200, f"{path}: {response.text[:300]}"
    assert client.get("/api/assets/nope:nope").status_code == 404
    bad = client.post("/api/recommendations", json={"instrument_id": "stock:aapl", "direction": "long",
                                                     "stop": 1e9, "target": 2e9, "thesis": "x" * 30})
    assert bad.status_code == 400


def test_api_chat_streams_events(client, monkeypatch):
    provider = ScriptedProvider([Reply(text="Hello from the scripted model.")])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    response = client.post("/api/chat", json={"message": "hi"})
    frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    kinds = [frame["type"] for frame in frames]
    assert kinds[0] == "conversation" and kinds[-1] == "end"
    assert "".join(f["text"] for f in frames if f["type"] == "text") == "Hello from the scripted model."


def test_settings_store_secrets_encrypted(client):
    response = client.put("/api/settings", json={"values": {"risk_per_trade": "0.005"},
                                                  "secrets": {"finnhub_api_key": "abc123secret"}})
    assert response.status_code == 200
    body = response.json()
    assert body["values"]["risk_per_trade"] == "0.005"
    assert body["secrets"]["finnhub_api_key"]["set"] is True
    raw = db.one("SELECT value FROM settings WHERE key='secret:finnhub_api_key'")["value"]
    assert "abc123secret" not in raw


def test_show_chart_builds_every_kind(synthetic):
    cases = [
        {"kind": "price", "instrument": "AAPL"},
        {"kind": "compare", "instruments": ["AAPL", "MSFT", "SPY"], "years": 2},
        {"kind": "analogs", "instrument": "stock:msft"},
        {"kind": "equity"},
        {"kind": "bar", "labels": ["a", "b"], "values": [0.01, -0.02]},
    ]
    for args in cases:
        text, is_error = tools.call("show_chart", args)
        assert not is_error, f"{args}: {text}"
        payload = json.loads(text)
        assert payload["chart"]["kind"] in ("line", "fan", "bar") and payload["summary"]
    _, is_error = tools.call("show_chart", {"kind": "event_study", "instrument": "GLD"})
    assert is_error


def test_charts_reach_ui_but_not_model(synthetic, monkeypatch):
    provider = ScriptedProvider([
        Reply(text="", tool_calls=[{"id": "c1", "name": "show_chart", "input": {"kind": "price", "instrument": "SPY"}}]),
        Reply(text="Here is SPY."),
    ])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    events = []
    result = chat.send(None, "/chart SPY", on_event=events.append)
    charts = [e for e in events if e["type"] == "chart"]
    assert len(charts) == 1 and charts[0]["chart"]["series"][0]["points"]
    sent_back = provider.calls[1]["messages"][-1]["results"][0]["content"]
    assert "points" not in sent_back and "summary" in sent_back
    history = chat.public_messages(result["conversation_id"])
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["text"] == "Here is SPY." and len(history[1]["charts"]) == 1


def test_invest_command_expands_with_limits(nexus_db):
    text = chat.expand("/invest energy")
    assert "focus: energy" in text and "propose_recommendation" in text and "show_chart" in text


def test_propose_records_computed_probability_not_stated(synthetic, favourable):
    confident = dict(_proposal("stock:aapl"), probability=0.72, confidence="high")
    text, is_error = tools.call("propose_recommendation", confident, extra={"_source": "chat"})
    assert not is_error, text
    result = json.loads(text)
    assert result["paper_position"].startswith("OPENED:")
    assert result["recorded"]["probability"] == pytest.approx(0.58)
    assert result["probability"]["you_stated"] == 0.72
    rec = db.one("SELECT probability, stated_probability, base_probability, evidence FROM recommendations")
    assert rec["stated_probability"] == 0.72 and rec["base_probability"] == 0.5
    assert "calibration" in rec["evidence"]


def test_propose_rejects_negative_expected_value(synthetic):
    # On a driftless random walk this bracket has no edge, so the real engine refuses it.
    text, is_error = tools.call("propose_recommendation", _proposal("stock:msft"), extra={"_source": "chat"})
    assert is_error and "Not recorded" in text
    assert db.one("SELECT COUNT(*) c FROM recommendations")["c"] == 0


def test_propose_says_not_opened_when_limits_block(synthetic, favourable):
    config.set_many({"max_exposure": "0.01"})
    text, is_error = tools.call("propose_recommendation", _proposal("stock:msft"), extra={"_source": "chat"})
    assert not is_error, text
    result = json.loads(text)
    assert result["paper_position"].startswith("NOT OPENED:") and "exposure" in result["paper_position"]
    assert db.one("SELECT COUNT(*) c FROM recommendations")["c"] == 1


def test_skills_catalog_and_load():
    from nexus.agent import skills

    names = {s["name"] for s in skills.catalog()}
    assert {"pre-trade-checklist", "position-review", "news-triage", "post-mortem", "event-playbook"} <= names
    text, is_error = tools.call("load_skill", {"name": "pre-trade-checklist"})
    assert not is_error and json.loads(text)["skill"] == "pre-trade-checklist@1"
    assert tools.call("load_skill", {"name": "nope"})[1]
    assert "pre-trade-checklist" in skills.prompt_section()


def test_skills_loaded_in_chat_are_recorded_and_tracked(synthetic, favourable, monkeypatch):
    provider = ScriptedProvider([
        Reply(text="", tool_calls=[{"id": "s1", "name": "load_skill", "input": {"name": "pre-trade-checklist"}}]),
        Reply(text="", tool_calls=[{"id": "p1", "name": "propose_recommendation", "input": _proposal("stock:nvda")}]),
        Reply(text="Done."),
    ])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    chat.send(None, "/recommend NVDA")
    rec = db.one("SELECT id, skills FROM recommendations")
    assert json.loads(rec["skills"]) == ["pre-trade-checklist@1"]
    # Close it early through the tool; holding is scored once the path resolves.
    text, is_error = tools.call("close_recommendation", {"recommendation_id": rec["id"],
                                                         "reason": "Invalidation hit: closed below the 50-day average"},
                                extra={"_skills": ["position-review@1"]})
    assert not is_error, text
    row = db.one("SELECT status, exit_reason, close_skills FROM recommendations")
    assert row["status"] == "closed" and row["exit_reason"] == "ai_review"
    assert json.loads(row["close_skills"]) == ["position-review@1"]
    db.execute("UPDATE recommendations SET expires_at='2000-01-01T00:00:00+00:00', created_at='2020-01-01T00:00:00+00:00'")
    assert recommendations.score_early_closes() == 1
    record = recommendations.track_record()
    assert record["by_skill"]["pre-trade-checklist@1"]["n"] == 1
    assert record["early_closes"]["scored"] == 1 and record["early_closes"]["avg_saved"] is not None


def test_postmortems_write_lessons(synthetic, favourable, monkeypatch):
    tools.call("propose_recommendation", _proposal("stock:msft"), extra={"_source": "chat"})
    rec_id = db.one("SELECT id FROM recommendations")["id"]
    recommendations._close(recommendations.get(rec_id), _price("stock:msft") * 0.94, "stop")
    provider = ScriptedProvider([Reply(text="Analogs alone were not enough; no second kind of evidence agreed.")])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    assert recommendations.write_postmortems() == 1
    assert "post-mortem" not in provider.calls[0]["system"][:20] and "two sentences" in provider.calls[0]["system"]
    assert "Analogs alone" in db.one("SELECT lesson FROM recommendations")["lesson"]
    assert "Recent post-mortems" in recommendations.lessons()
