"""Guarded LLM proposal agent.

The agent can create proposals, but only the deterministic execution service can
create or close ledger positions.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone

import requests

import context
import crypto_utils
import db
import execution
import llm as llm_module
import proposals
from instruments import INSTRUMENTS, is_market_open as catalog_market_open


WATCHLIST = [(instrument.symbol, instrument.asset_class) for instrument in INSTRUMENTS]


def is_market_open(asset_class: str) -> bool:
    return catalog_market_open(asset_class)


SYSTEM_PROMPT = """
You are the advisory analyst inside a paper-trading terminal. Capital preservation
and data honesty are more important than activity. A hold/no_setup response is valid.
Never invent a price, indicator, or catalyst. Proposals must include a protective
stop, a target on the profitable side of entry, and a quantity. Avoid duplicate or
highly correlated exposure. Respond with JSON only:
{
  "reasoning": "brief portfolio-level reasoning",
  "decisions": [
    {
      "action": "propose" | "hold",
      "instrument_id": "stock:aapl",
      "side": "long" | "short",
      "quantity": 1,
      "stop_loss": 180.0,
      "take_profit": 200.0,
      "confidence": 0.0,
      "reason": "specific evidence"
    }
  ]
}
""".strip()


class Agent:
    def __init__(self) -> None:
        self.running = False
        self._thread: threading.Thread | None = None
        self._cycle_lock = threading.Lock()
        self._stop_event = threading.Event()
        self.cycle_count = 0
        self.last_cycle: str | None = None
        self.last_error: str | None = None
        self.interval_seconds = 120
        self.stage = "idle"
        self._provider = None
        self._provider_name = "ollama"
        self._model_name = "minimax-m3:cloud"
        self._mode = "advisory"
        self._kill_switch = False
        self._allowed_classes = ["forex", "stock", "crypto"]
        self._load_provider()
        self._load_config()

    def _load_provider(self) -> None:
        try:
            conn = db.get_db()
            row = conn.execute("SELECT * FROM llm_config WHERE id=1").fetchone()
            conn.close()
            if row:
                self._provider_name, self._model_name = row["provider"], row["model"]
                key = crypto_utils.decrypt(row["api_key"]) if row["api_key"] else ""
                self._provider = llm_module.create_provider(
                    row["provider"], row["model"], key, row["base_url"] or "",
                    row["num_ctx"] if "num_ctx" in row.keys() else 8192,
                )
                return
        except Exception:
            pass
        self._provider = llm_module.create_provider("ollama", "minimax-m3:cloud")

    def _load_config(self) -> None:
        try:
            conn = db.get_db()
            values = {row["key"]: row["value"] for row in conn.execute(
                "SELECT key,value FROM portfolio_config WHERE key IN ('agent_mode','kill_switch','allowed_asset_classes')"
            )}
            conn.close()
            self._mode = values.get("agent_mode", "advisory")
            self._kill_switch = values.get("kill_switch", "false") == "true"
            allowed = [item for item in values.get("allowed_asset_classes", "forex,stock,crypto").split(",") if item]
            self._allowed_classes = allowed or ["forex", "stock", "crypto"]
        except Exception:
            pass

    def reload_provider(self) -> None:
        self._load_provider()
        self._load_config()

    def reload_config(self) -> None:
        self._load_config()

    def start(self, interval: int = 120) -> bool:
        self.reload_config()
        if self.running or self._kill_switch:
            return False
        self.interval_seconds = max(30, min(interval, 3600))
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="nexus-agent")
        self._thread.start()
        self._log("info", "START", None, f"Agent started in {self._mode} mode.")
        return True

    def stop(self) -> None:
        was_running = self.running
        self.running = False
        self._stop_event.set()
        self.stage = "idle"
        if was_running:
            self._log("warn", "STOP", None, "Agent stopped by operator.")

    def trigger(self) -> bool:
        self.reload_config()
        if self._kill_switch or self._cycle_lock.locked():
            return False
        threading.Thread(target=self._run_cycle, daemon=True, name="nexus-agent-trigger").start()
        return True

    def status(self) -> dict:
        return {
            "running": self.running, "provider": self._provider_name, "model": self._model_name,
            "cycle_count": self.cycle_count, "last_cycle": self.last_cycle,
            "last_error": self.last_error, "interval_seconds": self.interval_seconds,
            "mode": self._mode, "kill_switch": self._kill_switch, "stage": self.stage,
            "cycle_active": self._cycle_lock.locked(),
        }

    def _loop(self) -> None:
        while self.running and not self._stop_event.is_set():
            self._run_cycle()
            self._stop_event.wait(self.interval_seconds)

    def _run_cycle(self) -> None:
        if not self._cycle_lock.acquire(blocking=False):
            return
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        started = datetime.now(timezone.utc)
        proposal_count = executed_count = 0
        conn = db.get_db()
        conn.execute(
            "INSERT INTO agent_runs(id,mode,status,stage,started_at) VALUES(?,?,?,?,?)",
            (run_id, self._mode, "running", "preflight", started.isoformat()),
        )
        conn.commit()
        conn.close()
        try:
            self.reload_config()
            if self._kill_switch:
                raise RuntimeError("Kill switch is active")
            self.stage = "market_context"
            portfolio = execution.portfolio_snapshot()
            tradable = [
                item for item in INSTRUMENTS
                if item.eligibility == "trade_enabled" and item.asset_class in self._allowed_classes and catalog_market_open(item)
            ]
            if not tradable:
                self._log("info", "HOLD", None, "No accuracy-gated markets are open.")
                return
            symbols = [item.symbol for item in tradable]
            classes = [item.asset_class for item in tradable]
            market_context = context.build_market_context(symbols, classes)
            catalog = "\n".join(f"- {item.id}: {item.symbol} ({item.asset_class})" for item in tradable)
            user_message = f"""
PAPER PORTFOLIO
Equity: {portfolio['equity']:.2f}
Day P&L: {portfolio['day_pnl']:+.2f}
Gross exposure: {portfolio['exposure_pct']:.1f}%
Open positions: {portfolio['open_count']}
Risk preset: {portfolio['risk_profile']}

ACCURACY-GATED INSTRUMENT IDs
{catalog}

MARKET CONTEXT
{market_context}

Return zero proposals when no setup has a valid stop and positive expected reward.
""".strip()
            self.stage = "llm"
            if not self._provider:
                raise RuntimeError("No LLM provider configured")
            response = self._provider.chat(SYSTEM_PROMPT, user_message)
            parsed = self._parse_response(response)
            reasoning = str(parsed.get("reasoning", ""))
            if reasoning:
                self._log("info", "ANALYZE", None, reasoning)
            self.stage = "validation"
            for decision in parsed.get("decisions", []):
                if str(decision.get("action", "hold")).lower() in ("hold", "no_setup"):
                    continue
                try:
                    created = proposals.create_proposal(decision, source="ai")
                    proposal_count += 1
                    if isinstance(created, dict) and created.get("order", {}).get("status") == "filled":
                        executed_count += 1
                except (ValueError, KeyError) as exc:
                    self._log("warn", "REJECT", decision.get("instrument_id"), f"Invalid AI proposal: {exc}")
            self.cycle_count += 1
            self.last_cycle = _iso_now()
            self.last_error = None
            self.stage = "idle"
        except Exception as exc:
            self.last_error = str(exc)
            self.stage = "error"
            self._log("error", "CYCLE_ERR", None, f"Agent cycle failed: {exc}")
        finally:
            finished = datetime.now(timezone.utc)
            status = "failed" if self.last_error and self.stage == "error" else "completed"
            conn = db.get_db()
            conn.execute(
                """UPDATE agent_runs SET status=?,stage=?,finished_at=?,duration_ms=?,error=?,proposal_count=?,executed_count=?
                   WHERE id=?""",
                (status, self.stage, finished.isoformat(), int((finished - started).total_seconds() * 1000),
                 self.last_error if status == "failed" else None, proposal_count, executed_count, run_id),
            )
            conn.commit()
            conn.close()
            if self.stage == "error":
                self.stage = "idle"
            self._cycle_lock.release()

    def _parse_response(self, text: str) -> dict:
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", (text or "").strip()).strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"```$", "", cleaned).strip()
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise ValueError("LLM response did not contain JSON")
            parsed = json.loads(match.group())
        if not isinstance(parsed, dict) or not isinstance(parsed.get("decisions", []), list):
            raise ValueError("LLM response has an invalid proposal schema")
        return parsed

    def test_provider(self) -> dict:
        started = time.perf_counter()
        try:
            if not self._provider:
                raise RuntimeError("No provider configured")
            response = self._provider.chat("Reply with JSON only.", '{"health":"Return the word ok"}')
            return {"ok": bool(response.strip()), "latency_ms": int((time.perf_counter() - started) * 1000), "provider": self._provider_name, "model": self._model_name}
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            return {"ok": False, "latency_ms": int((time.perf_counter() - started) * 1000), "provider": self._provider_name, "model": self._model_name, "error": str(exc)}

    def _log(self, level: str, action: str, pair: str | None, message: str) -> None:
        try:
            conn = db.get_db()
            conn.execute(
                "INSERT INTO logs VALUES(?,?,?,?,?,?)",
                (f"l{uuid.uuid4().hex[:8]}", level, action, pair, message, _iso_now()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


agent = Agent()
