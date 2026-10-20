"""Agent loop, tools, chat persistence and the HTTP API, with a scripted LLM."""

import json

import pytest
from fastapi.testclient import TestClient

from nexus import db, jobs, llm
from nexus.agent import analyst, chat, tools
from nexus.llm import Reply
from nexus.llm.anthropic_provider import AnthropicProvider
from nexus.llm.openai_compat import OpenAICompatProvider


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


def test_chat_runs_tools_and_records_recommendation(synthetic, monkeypatch):
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
    weak = dict(_proposal("stock:aapl"), probability=0.51)
    provider = ScriptedProvider([
        Reply(text="", tool_calls=[
            {"id": "a", "name": "propose_recommendation", "input": weak},
            {"id": "b", "name": "propose_recommendation", "input": _proposal("stock:msft")},
            {"id": "c", "name": "propose_recommendation", "input": _proposal("stock:jpm")},
        ]),
        Reply(text="Brief: one idea."),
    ])
    monkeypatch.setattr(llm, "create", lambda kind="main": provider)
    result = analyst.run(max_recs=1)
    assert result["recommendations"] == 1
    tool_results = provider.calls[1]["messages"][-1]["results"]
    assert "minimum" in tool_results[0]["content"] and tool_results[0]["is_error"]
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
                 "/api/settings", "/api/jobs", "/api/runs", "/api/universe"]:
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
