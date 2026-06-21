"""
AI Trading Agent - uses Ollama (minimax-m3:cloud) to make trading decisions.
"""

import json
import uuid
import threading
import time
import requests
from datetime import datetime, timezone

import db
import prices
import context
import llm as llm_module


def is_market_open(asset_class: str) -> bool:
    """Check if the market for a given asset class is currently open."""
    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=Monday, 6=Sunday

    if asset_class == "crypto":
        return True  # 24/7

    if asset_class == "forex":
        # Forex: open Sunday 22:00 UTC to Friday 22:00 UTC
        if weekday == 5:  # Saturday - always closed
            return False
        if weekday == 4 and now.hour >= 22:  # Friday after 22:00
            return False
        if weekday == 6 and now.hour < 22:  # Sunday before 22:00
            return False
        return True

    if asset_class == "futures":
        # CME Globex: open Sunday 23:00 UTC to Friday 22:00 UTC
        if weekday == 5:  # Saturday - always closed
            return False
        if weekday == 4 and now.hour >= 22:  # Friday after 22:00
            return False
        if weekday == 6 and now.hour < 23:  # Sunday before 23:00
            return False
        return True

    if asset_class in ("stock", "cfd"):
        # NYSE/NASDAQ: 13:30-20:00 UTC, Mon-Fri
        if weekday >= 5:  # Saturday/Sunday
            return False
        hour_min = now.hour * 100 + now.minute
        return 1330 <= hour_min <= 2000

    return True


WATCHLIST = [
    # Forex
    ("EUR/USD", "forex"),
    ("GBP/USD", "forex"),
    ("GBP/JPY", "forex"),
    ("USD/JPY", "forex"),
    ("USD/CHF", "forex"),
    ("AUD/USD", "forex"),
    ("EUR/GBP", "forex"),
    ("NZD/USD", "forex"),
    ("USD/CAD", "forex"),
    ("EUR/JPY", "forex"),
    # Stocks - mega cap tech
    ("NVDA", "stock"),
    ("AAPL", "stock"),
    ("TSLA", "stock"),
    ("MSFT", "stock"),
    ("GOOGL", "stock"),
    ("META", "stock"),
    ("AMZN", "stock"),
    # Stocks - growth / momentum
    ("AMD", "stock"),
    ("AVGO", "stock"),
    ("PLTR", "stock"),
    ("COIN", "stock"),
    ("NFLX", "stock"),
    # Stocks - value / defensive
    ("JPM", "stock"),
    ("GOLD", "stock"),
    ("BA", "stock"),
    # ETFs
    ("SPY", "stock"),
    ("QQQ", "stock"),
    ("IWM", "stock"),
    ("GLD", "stock"),
    # Crypto
    ("BTC/USD", "crypto"),
    ("ETH/USD", "crypto"),
    ("SOL/USD", "crypto"),
    ("XRP/USD", "crypto"),
    # CFDs - indices
    ("US500", "cfd"),
    ("NAS100", "cfd"),
    ("US30", "cfd"),
    ("GER40", "cfd"),
    ("JPN225", "cfd"),
    # CFDs - commodities
    ("XAU/USD", "cfd"),
    ("XAG/USD", "cfd"),
    ("WTI", "cfd"),
    ("NATGAS", "cfd"),
    # Futures - indices (trade nearly 24/6)
    ("ES", "futures"),   # E-mini S&P 500
    ("NQ", "futures"),   # E-mini Nasdaq 100
    ("YM", "futures"),   # E-mini Dow
    ("RTY", "futures"),  # E-mini Russell 2000
    # Futures - bonds
    ("ZB", "futures"),   # 30-Year Treasury Bond
    ("ZN", "futures"),   # 10-Year Treasury Note
    # Futures - commodities
    ("ZC", "futures"),   # Corn
    ("ZS", "futures"),   # Soybeans
    ("ZW", "futures"),   # Wheat
    ("GOLD", "futures"),   # Gold
    ("SILVER", "futures"), # Silver
    ("USOIL", "futures"),  # Crude Oil WTI
]

_BASE_PROMPT = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXUS v4 — EXECUTION-FIRST TRADING AGENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IDENTITY:
You are a capital deployment engine.

Your goal is to:
- Actively trade
- Deploy capital
- Generate returns

NOT to sit idle.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA HANDLING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST use whatever data is available.

Rules:
- Price present → tradable
- Missing indicators → treat as neutral
- Infer momentum from returns if needed

You are NOT allowed to skip all assets.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGNAL ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LONG:
+2 strong positive move (>1%)
+1 continuation
+1 stable price
+1 volatility expansion
+1 neutral/bullish sentiment

SHORT:
+2 strong negative move (<-1%)
+1 continuation
+1 weak structure
+1 volatility expansion
+1 neutral/bearish sentiment

SCORE ≥ 2 → TRADE

Weak signals are acceptable.
"""

_PROFILE_CONSERVATIVE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSERVATIVE — Cautious Execution
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You prioritize capital preservation but STILL MUST TRADE.

You MUST open 1-2 trades EVERY cycle.

━━━━━━━━━━━━━━━━━━━━━━━
POSITION SIZING
━━━━━━━━━━━━━━━━━━━━━━━

FOREX: 25,000–100,000 units
STOCKS: 10–50 shares
CRYPTO: 0.1–0.5 BTC / 2–10 ETH
INDICES: 1–3 contracts
FUTURES: 1–3 contracts

━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOR
━━━━━━━━━━━━━━━━━━━━━━━

- Prefer stronger signals (score 3+)
- But still open at score 2 if nothing better exists
- Tight stops (1.0x ATR), wider targets (4.0x ATR)

━━━━━━━━━━━━━━━━━━━━━━━
RULE
━━━━━━━━━━━━━━━━━━━━━━━

1-2 trades REQUIRED every cycle
"""

_PROFILE_MODERATE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODERATE — FORCED EXECUTION MODE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST open 1–3 trades EVERY cycle.

No trades = failure.

━━━━━━━━━━━━━━━━━━━━━━━
POSITION SIZING
━━━━━━━━━━━━━━━━━━━━━━━

FOREX: 50,000–150,000 units
STOCKS: 20–100 shares
CRYPTO: 0.2–1 BTC / 5–20 ETH
INDICES: 2–5 contracts
FUTURES: 1–5 contracts (e.g. 2 ES, 3 NQ, 5 ZN)

If too small → SCALE UP

━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOR
━━━━━━━━━━━━━━━━━━━━━━━

- Open trades FIRST
- Then manage positions
- Do NOT hesitate

━━━━━━━━━━━━━━━━━━━━━━━
RULE
━━━━━━━━━━━━━━━━━━━━━━━

1–3 trades REQUIRED every cycle
"""

_PROFILE_AGGRESSIVE = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AGGRESSIVE — MAXIMUM DEPLOYMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST open 2–5 trades EVERY cycle.

Cash is a losing position.

━━━━━━━━━━━━━━━━━━━━━━━
POSITION SIZING
━━━━━━━━━━━━━━━━━━━━━━━

FOREX: 100,000–300,000 units
STOCKS: 50–200 shares
CRYPTO: 0.5–2 BTC / 10–50 ETH
INDICES: 3–10 contracts
FUTURES: 3–10 contracts

Scale UP aggressively.

━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOR
━━━━━━━━━━━━━━━━━━━━━━━

- Open trades FIRST
- Weak signals are fine
- Momentum > perfection
- Counter-trend trades allowed

━━━━━━━━━━━━━━━━━━━━━━━
RULE
━━━━━━━━━━━━━━━━━━━━━━━

2–5 trades REQUIRED every cycle
"""

_OUTPUT_FORMAT = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PORTFOLIO RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Avoid duplicate positions
- Avoid excessive correlation
- BTC + ETH = one exposure
- Major indices = one exposure

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXECUTION PRIORITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Open new trades FIRST
2. Then manage positions

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIVERSIFICATION RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- NEVER open the same symbol twice — skip if already have a position
- Spread trades across DIFFERENT symbols and asset classes
- If stocks are closed, trade crypto/forex/CFDs/futures that are open
- Each cycle should target different assets than the previous one

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY ACTIVITY RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You MUST open at least 1 position.

If you output zero opens → INVALID RESPONSE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAPITAL DEPLOYMENT RULE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If portfolio exposure < 20%:
→ you MUST aggressively open positions

Low exposure = failure

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (STRICT JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "reasoning": "brief reasoning",
  "decisions": [
    {
      "action": "open",
      "symbol": "AAPL",
      "asset_class": "stock",
      "side": "long",
      "size": 50,
      "confidence": 0.7,
      "entry_price": 185.2,
      "stop_loss": 180.0,
      "take_profit": 200.0,
      "reason": "momentum continuation"
    }
  ]
}
"""

RISK_PROFILES = {
    "conservative": "Conservative — Capital Preservation",
    "moderate": "Moderate — Balanced Risk/Reward",
    "aggressive": "Aggressive — Maximum Growth",
}

def get_system_prompt(profile: str = "moderate") -> str:
    profile_section = {
        "conservative": _PROFILE_CONSERVATIVE,
        "moderate": _PROFILE_MODERATE,
        "aggressive": _PROFILE_AGGRESSIVE,
    }.get(profile, _PROFILE_MODERATE)
    return (_BASE_PROMPT + profile_section + _OUTPUT_FORMAT).strip()


class Agent:
    def __init__(self):
        self.running = False
        self._thread = None
        self.cycle_count = 0
        self.last_cycle = None
        self.last_error = None
        self.interval_seconds = 120
        self._provider = None
        self._provider_name = "ollama"
        self._model_name = "minimax-m3:cloud"
        self._consecutive_errors = 0
        self._risk_profile = "moderate"
        self._allowed_classes = ["forex", "stock", "crypto", "cfd", "futures"]
        self._exposure_limit = 80
        self._load_provider()
        self._load_config()

    def _load_config(self):
        try:
            conn = db.get_db()
            row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'risk_profile'").fetchone()
            ac_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'allowed_asset_classes'").fetchone()
            el_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'exposure_limit'").fetchone()
            conn.close()
            if row and row["value"] in ("conservative", "moderate", "aggressive"):
                self._risk_profile = row["value"]
            if ac_row and ac_row["value"]:
                classes = [c.strip() for c in ac_row["value"].split(",") if c.strip() in ("forex", "stock", "crypto", "cfd", "futures")]
                if classes:
                    self._allowed_classes = classes
            if el_row and el_row["value"]:
                self._exposure_limit = float(el_row["value"])
        except Exception:
            pass

    def _load_provider(self):
        try:
            import crypto_utils
            conn = db.get_db()
            row = conn.execute("SELECT * FROM llm_config WHERE id = 1").fetchone()
            conn.close()
            if row:
                self._provider_name = row["provider"]
                self._model_name = row["model"]
                raw_key = row["api_key"] or ""
                api_key = crypto_utils.decrypt(raw_key) if raw_key else ""
                self._provider = llm_module.create_provider(
                    provider=row["provider"],
                    model=row["model"],
                    api_key=api_key,
                    base_url=row["base_url"] or "",
                    num_ctx=row["num_ctx"] if "num_ctx" in row.keys() else 8192,
                )
            else:
                self._provider_name = "ollama"
                self._model_name = "minimax-m3:cloud"
                self._provider = llm_module.create_provider("ollama", "minimax-m3:cloud")
        except Exception:
            self._provider_name = "ollama"
            self._model_name = "minimax-m3:cloud"
            self._provider = llm_module.create_provider("ollama", "minimax-m3:cloud")

    def reload_provider(self):
        self._load_provider()
        self._load_config()

    def reload_config(self):
        self._load_config()

    def start(self, interval=120):
        if self.running:
            return
        self.interval_seconds = interval
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._log("info", "START", None, f"Agent started (provider={self._provider_name}, model={self._model_name}, interval={interval}s)")

    def stop(self):
        self.running = False
        self._log("warn", "STOP", None, "Agent stopped by operator")

    def status(self):
        return {
            "running": self.running,
            "provider": self._provider_name,
            "model": self._model_name,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "last_error": self.last_error,
            "interval_seconds": self.interval_seconds,
            "consecutive_errors": self._consecutive_errors,
            "risk_profile": self._risk_profile,
            "watchlist": [p for p, _ in WATCHLIST],
        }

    def _loop(self):
        while self.running:
            try:
                self._run_cycle()
                if self._consecutive_errors > 0:
                    self._consecutive_errors = 0
                self.cycle_count += 1
                self.last_cycle = datetime.now(timezone.utc).isoformat()
                self.last_error = None
            except Exception as e:
                self._consecutive_errors += 1
                self.last_error = str(e)
                if self._consecutive_errors <= 2:
                    self._log("error", "CYCLE_ERR", None, f"Agent cycle error: {e}")

            wait = self.interval_seconds
            if self._consecutive_errors > 0:
                backoff = min(self.interval_seconds * (2 ** (self._consecutive_errors - 1)), 1800)
                wait = backoff
                if self._consecutive_errors == 1:
                    self._log("warn", "BACKOFF", None, f"Rate limited or errored, backing off to {wait}s")

            for _ in range(wait):
                if not self.running:
                    return
                time.sleep(1)

    def _forex_pnl(self, entry: float, current: float, size: float, side: str, pair: str, price_data: dict | None = None) -> float:
        direction = 1 if side == "long" else -1
        raw = (current - entry) * size * direction
        if "/" in pair:
            base, quote = pair.split("/")
            if quote == "USD":
                return raw
            if base == "USD" and current > 0:
                return raw / current
            if current > 0 and price_data:
                quote_usd = price_data.get(f"{quote}/USD", {}).get("price") if price_data else None
                if quote_usd:
                    return raw / current * quote_usd
                usd_quote = price_data.get(f"USD/{quote}", {}).get("price") if price_data else None
                if usd_quote and usd_quote > 0:
                    return raw / current / usd_quote
        return raw

    def _run_cycle(self):
        # 1. Fetch current prices for watchlist
        symbols = [p for p, _ in WATCHLIST]
        price_data = prices.fetch_prices(symbols)

        # 2. Get current positions
        conn = db.get_db()
        positions = [dict(r) for r in conn.execute("SELECT * FROM positions").fetchall()]
        trades = [dict(r) for r in conn.execute("SELECT * FROM trades ORDER BY closed_at DESC LIMIT 10").fetchall()]
        equity_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'starting_equity'").fetchone()
        starting_equity = float(equity_row["value"]) if equity_row else 100_000
        conn.close()

        # Calculate current equity
        realized = sum(t["pnl"] for t in trades)
        open_pnl = 0
        for p in positions:
            pd = price_data.get(p["pair"])
            if pd:
                open_pnl += self._forex_pnl(p["entry_price"], pd["price"], p["size"], p["side"], p["pair"], price_data)
        equity = starting_equity + realized + open_pnl

        # 3. Build rich market context (only open markets)
        open_markets = [ac for ac in ["forex", "stock", "crypto", "cfd", "futures"] if is_market_open(ac) and ac in self._allowed_classes]
        batch = [(pair, ac) for pair, ac in WATCHLIST if is_market_open(ac) and ac in self._allowed_classes]
        batch_symbols = [p for p, _ in batch]
        batch_classes = [ac for _, ac in batch]

        if not batch_symbols:
            self._log("info", "SKIP", None, "No open markets right now")
            return

        market_context = context.build_market_context(batch_symbols, batch_classes)

        pos_lines = []
        for p in positions:
            pd = price_data.get(p["pair"])
            cur = pd["price"] if pd else p["entry_price"]
            pnl = self._forex_pnl(p["entry_price"], cur, p["size"], p["side"], p["pair"], price_data)
            pnl_pct = ((cur - p["entry_price"]) / p["entry_price"] * 100 *
                       (1 if p["side"] == "long" else -1)) if p["entry_price"] else 0
            pos_lines.append(
                f"  [{p['id']}] {p['pair']} ({p['asset_class']}) {p['side']} "
                f"size={p['size']} entry={p['entry_price']:.4f} mark={cur:.4f} "
                f"pnl=${pnl:+,.2f} ({pnl_pct:+.1f}%)"
            )

        recent_trades = trades[:5]
        trade_lines = []
        for t in recent_trades:
            trade_lines.append(
                f"  {t['pair']} {t['side']} pnl=${t['pnl']:+,.2f} ({t['closed_at'][:10]})"
            )

        deployment_pct = 0
        if equity > 0:
            total_exposure = sum(
                abs(p["size"] * (price_data.get(p["pair"], {}).get("price", p["entry_price"])))
                for p in positions
            )
            deployment_pct = total_exposure / equity * 100

        wins = sum(1 for t in trades if t["pnl"] > 0)
        losses = sum(1 for t in trades if t["pnl"] < 0)
        win_rate = (wins / len(trades) * 100) if trades else 0

        # Build market status
        open_markets = [ac for ac in ["forex", "stock", "crypto", "cfd", "futures"] if is_market_open(ac) and ac in self._allowed_classes]

        user_msg = f"""
=== PORTFOLIO STATE ===
Starting equity: ${starting_equity:,.0f}
Current equity: ${equity:,.2f}
Unrealized P&L: ${open_pnl:+,.2f}
Realized P&L: ${realized:+,.2f}
Open positions: {len(positions)}/10
Deployment: {deployment_pct:.0f}% of equity
Win rate: {win_rate:.0f}% ({wins}W / {losses}L)

ALL assets shown below are from OPEN markets and are tradable right now.
Open markets: {', '.join(open_markets) if open_markets else 'none'}

{market_context}

=== OPEN POSITIONS ===
{chr(10).join(pos_lines) if pos_lines else "  (no open positions)"}

=== RECENT CLOSED TRADES ===
{chr(10).join(trade_lines) if trade_lines else "  (none)"}

Analyze the market context above and make your trading decisions.
Remember: justify every trade with specific technical/fundamental signals from the data.
""".strip()

        # 4. Call LLM
        response = self._call_llm(user_msg)
        if not response:
            return

        # 5. Parse and execute decisions
        decisions = self._parse_response(response)
        if not decisions:
            return

        reasoning = decisions.get("reasoning", "")
        if reasoning:
            self._log("info", "ANALYZE", None, reasoning)

        for dec in decisions.get("decisions", []):
            self._execute_decision(dec, price_data)

    def _call_llm(self, user_message: str) -> str | None:
        if not self._provider:
            raise RuntimeError("No LLM provider configured")
        try:
            result = self._provider.chat(get_system_prompt(self._risk_profile), user_message)
            if not result or not result.strip():
                if self._consecutive_errors == 0:
                    self._log("warn", "LLM", None, f"{self._provider_name} returned empty response, retrying next cycle")
                raise RuntimeError("Empty response from LLM")
            return result
        except requests.ConnectionError:
            provider_label = llm_module.PROVIDERS.get(self._provider_name, {}).get("name", self._provider_name)
            if self._consecutive_errors == 0:
                self._log("error", "LLM", None, f"Cannot connect to {provider_label}")
            raise
        except Exception as e:
            if self._consecutive_errors == 0:
                self._log("error", "LLM", None, f"{self._provider_name} error: {e}")
            raise

    def _parse_response(self, text: str) -> dict | None:
        try:
            import re
            cleaned = text.strip()

            # Strip <think> blocks (some models use these)
            cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned).strip()

            # Strip ALL code fence variants: ```json, ```JSON, ```, etc.
            cleaned = re.sub(r"^```(?:json|JSON|javascript|js)?\s*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            cleaned = cleaned.strip()

            # Remove // comments (but not inside strings)
            cleaned = re.sub(r"(?<![:\"\'\w])//[^\n]*", "", cleaned)

            # Remove trailing commas before } or ]
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

            # Strategy 1: direct parse
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

            # Strategy 2: raw_decode scanning for { with "decisions" key
            decoder = json.JSONDecoder()
            for i, ch in enumerate(cleaned):
                if ch == "{":
                    try:
                        obj, _ = decoder.raw_decode(cleaned[i:])
                        if isinstance(obj, dict) and ("decisions" in obj or "reasoning" in obj):
                            return obj
                    except json.JSONDecodeError:
                        continue

            # Strategy 3: extract largest JSON object via regex
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    # Fix single quotes and retry
                    fixed = match.group().replace("'", '"')
                    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass

            # Strategy 4: brute-force find any dict with decisions
            for i, ch in enumerate(cleaned):
                if ch == "{":
                    for j in range(len(cleaned), i, -1):
                        if cleaned[j - 1] == "}":
                            try:
                                obj = json.loads(cleaned[i:j])
                                if isinstance(obj, dict):
                                    return obj
                            except (json.JSONDecodeError, ValueError):
                                continue

            raise json.JSONDecodeError("No valid JSON found", cleaned, 0)

        except json.JSONDecodeError as e:
            preview = text[:200].replace("\n", " ")
            self._log("error", "PARSE", None, f"Failed to parse AI response: {e}. Preview: {preview}")
            return None

    def _execute_decision(self, decision: dict, price_data: dict):
        action = decision.get("action", "").lower()
        conn = db.get_db()

        try:
            if action == "open":
                if len(conn.execute("SELECT * FROM positions").fetchall()) >= 10:
                    self._log("warn", "SKIP", decision.get("symbol") or decision.get("pair"), "Max 10 positions reached", conn)
                    return

                pair = decision.get("symbol") or decision.get("pair", "")

                existing = conn.execute("SELECT * FROM positions WHERE pair = ?", (pair,)).fetchone()
                if existing:
                    self._log("warn", "SKIP", pair, f"Already have open position in {pair}, skipping duplicate", conn)
                    return

                pd = price_data.get(pair)
                if not pd:
                    self._log("warn", "SKIP", pair, "No price available, skipping open", conn)
                    return

                raw_ac = decision.get("asset_class", "stock")
                if raw_ac in ("cfd_index", "cfd_commodity", "commodity", "index"):
                    raw_ac = "cfd"

                if raw_ac not in self._allowed_classes:
                    self._log("warn", "SKIP", pair, f"Asset class '{raw_ac}' not in allowed classes ({','.join(self._allowed_classes)})", conn)
                    return

                if not is_market_open(raw_ac):
                    self._log("warn", "SKIP", pair, f"Market closed for {raw_ac}, skipping open", conn)
                    return

                size = decision.get("size", 10)
                price = pd["price"]

                equity_row = conn.execute("SELECT value FROM portfolio_config WHERE key = 'starting_equity'").fetchone()
                starting_equity = float(equity_row["value"]) if equity_row else 100_000
                trades = conn.execute("SELECT * FROM trades").fetchall()
                positions = conn.execute("SELECT * FROM positions").fetchall()
                realized = sum(t["pnl"] for t in trades)
                open_pnl = 0
                for p in positions:
                    ppd = price_data.get(p["pair"])
                    if ppd:
                        open_pnl += self._forex_pnl(p["entry_price"], ppd["price"], p["size"], p["side"], p["pair"], price_data)
                equity = starting_equity + realized + open_pnl

                notional = abs(size * price)
                if raw_ac == "forex" and "/" in pair:
                    base = pair.split("/")[0]
                    if base == "USD":
                        notional = abs(size)
                    else:
                        notional = abs(size * price)

                max_notional = equity * 0.80
                if notional > max_notional and price > 0:
                    if raw_ac == "forex" and "/" in pair and pair.split("/")[0] == "USD":
                        size = max_notional
                    else:
                        size = max(1, int(max_notional / price))
                    notional = abs(size * price)

                total_exposure = sum(
                    abs(p["size"] * (price_data.get(p["pair"], {}).get("price", p["entry_price"])))
                    for p in positions
                ) + notional
                max_exposure = equity * (self._exposure_limit / 100)
                if self._exposure_limit < 999 and total_exposure > max_exposure:
                    self._log("warn", "SKIP", pair, f"Total exposure would exceed {self._exposure_limit:.0f}% of equity (${equity:,.0f}), skipping", conn)
                    return

                pos_id = f"p{uuid.uuid4().hex[:6]}"
                conn.execute(
                    "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)",
                    (pos_id, pair, raw_ac,
                     decision.get("side", "long"), size,
                     price, datetime.now(timezone.utc).isoformat(),
                     decision.get("confidence", 0.7)),
                )
                self._log("info", "OPEN", pair,
                          f"AI opened {decision.get('side')} {size} {pair} @ {price:.4f}. "
                          f"Reason: {decision.get('reason', 'N/A')}", conn)
                
                # Create trade idea if stop_loss or take_profit provided
                if decision.get("stop_loss") or decision.get("take_profit"):
                    idea_id = f"idea_{uuid.uuid4().hex[:8]}"
                    conn.execute(
                        """INSERT INTO trade_ideas 
                           (id, symbol, asset_class, side, entry_price, stop_loss, take_profit, 
                            confidence, reasoning, status, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
                        (idea_id, pair, raw_ac, decision.get("side", "long"), price,
                         decision.get("stop_loss"), decision.get("take_profit"),
                         decision.get("confidence"), decision.get("reason"),
                         datetime.now(timezone.utc).isoformat())
                    )
                    self._log("info", "IDEA", pair,
                              f"Created trade idea: {decision.get('side')} @ {price:.4f}, "
                              f"SL: {decision.get('stop_loss', 'N/A')}, TP: {decision.get('take_profit', 'N/A')}", conn)

            elif action == "close":
                pos_id = decision.get("position_id", "")
                row = conn.execute("SELECT * FROM positions WHERE id = ?", (pos_id,)).fetchone()
                if not row:
                    self._log("warn", "SKIP", pos_id, "Position not found for close", conn)
                    return

                pd = price_data.get(row["pair"])
                exit_price = pd["price"] if pd else row["entry_price"]
                pnl = self._forex_pnl(row["entry_price"], exit_price, row["size"], row["side"], row["pair"], price_data)

                trade_id = f"t{uuid.uuid4().hex[:6]}"
                conn.execute(
                    "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?)",
                    (trade_id, row["pair"], row["side"], row["size"],
                     row["entry_price"], exit_price, pnl,
                     datetime.now(timezone.utc).isoformat()),
                )
                conn.execute("DELETE FROM positions WHERE id = ?", (pos_id,))
                self._log("info", "CLOSE", row["pair"],
                          f"AI closed {row['side']} {row['size']} {row['pair']} @ {exit_price:.4f}. "
                          f"P&L: {pnl:+,.2f}. Reason: {decision.get('reason', 'N/A')}", conn)
                
                # Auto-close corresponding trade idea
                active_idea = conn.execute(
                    "SELECT * FROM trade_ideas WHERE symbol = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                    (row["pair"],)
                ).fetchone()
                if active_idea:
                    # Calculate P&L percentage
                    direction = 1 if row["side"] == "long" else -1
                    pnl_pct = ((exit_price - row["entry_price"]) / row["entry_price"] * 100) * direction
                    
                    # Determine outcome: hit_tp, hit_sl, or manual
                    outcome = "manual"
                    if active_idea["take_profit"] and exit_price >= active_idea["take_profit"] * (1 if row["side"] == "long" else -1):
                        outcome = "hit_tp"
                    elif active_idea["stop_loss"] and exit_price <= active_idea["stop_loss"] * (1 if row["side"] == "long" else -1):
                        outcome = "hit_sl"
                    
                    conn.execute(
                        """UPDATE trade_ideas 
                           SET status = 'closed', closed_at = ?, outcome_pnl = ?
                           WHERE id = ?""",
                        (datetime.now(timezone.utc).isoformat(), pnl_pct, active_idea["id"])
                    )
                    self._log("info", "IDEA_CLOSE", row["pair"],
                              f"Trade idea closed: {outcome}, P&L: {pnl_pct:+.2f}%", conn)

            elif action == "hold":
                self._log("info", "HOLD", None,
                          f"AI holding. Reason: {decision.get('reason', 'No action needed')}", conn)

        finally:
            conn.commit()
            conn.close()

    def _log(self, level, action, pair, message, conn=None):
        own_conn = conn is None
        try:
            if own_conn:
                conn = db.get_db()
            conn.execute(
                "INSERT INTO logs VALUES (?,?,?,?,?,?)",
                (f"l{uuid.uuid4().hex[:6]}", level, action, pair, message,
                 datetime.now(timezone.utc).isoformat()),
            )
            if own_conn:
                conn.commit()
        except Exception as e:
            print(f"[Agent] Failed to write log: {e}")
        finally:
            if own_conn and conn:
                conn.close()


# Singleton
agent = Agent()
