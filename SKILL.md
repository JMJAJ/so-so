---
name: nexus-paper-trader
description: Operate the local NEXUS single-user paper-trading terminal through its deterministic HTTP API. Use when an AI needs to inspect the paper portfolio, evaluate current positions, run an advisory market scan, review or approve AI proposals, preview and place protected paper orders, update stops/targets, close paper positions, or manage advisory/guarded-autopilot safety controls. Never use for real-money brokerage execution.
---

# NEXUS Paper Trader

Operate NEXUS as an edge-first paper-trading desk. Treat the server preview and execution engine as authoritative; never write SQLite positions directly. The terminal currently provides execution safety, not proof of profitability.

## Locate the terminal

1. Default to `http://127.0.0.1:8000`.
2. Override with `NEXUS_API_URL` when supplied.
3. Use `scripts/nexus.py` for deterministic API calls. Run `python scripts/nexus.py --help` when needed.
4. If the API is offline, ask the user to run `start-nexus.ps1`. Do not silently start long-running services unless requested.

Read [references/api.md](references/api.md) only when implementing a new integration or when the CLI lacks an operation.

## Edge-first trading loop

1. Run `snapshot` and inspect system health, agent state, risk preset, equity, exposure, open positions, pending proposals, stale quotes, and unprotected positions.
2. Stop if the kill switch is on, market data is unhealthy, the relevant quote is stale/unavailable, or the market is closed.
3. Prefer an existing pending proposal. Otherwise run exactly one `scan --wait`; do not start the recurring agent unless explicitly requested.
4. Evaluate a candidate:
   - require `trade_enabled` eligibility;
   - reject missing/wrong-side stops or targets;
   - require reward-to-risk of at least 1.5:1 unless the user explicitly chooses otherwise;
   - avoid duplicate instrument exposure;
   - consider correlation with the existing book;
   - prefer small, diversified positions over concentrating into the dominant asset class;
   - do not infer certainty from heuristic or LLM confidence;
   - require a quantified setup edge from comparable historical or forward-test trades. If no sample exists, label the order `experimental` and do not open it automatically;
   - estimate expectancy as `win_rate * average_win - (1 - win_rate) * average_loss - round_trip_costs`. Require positive expectancy after costs, with a meaningful sample (preferably at least 30 comparable trades);
   - require a market-regime filter and a reason the setup should work now, not only a list of indicators.
5. Run `preview` with the exact instrument, side, quantity, stop, and target.
6. Execute only when `allowed` is true and `errors` is empty. Never bypass a rejection or weaken configuration to force a fill.
7. For an AI-created setup, approve the proposal rather than recreating it as a manual order. This preserves provenance and idempotency.
8. Run `snapshot` again and report the actual fill, modeled loss to stop, target, costs, new total exposure, and any remaining unprotected positions.

## Decision and sizing rules

- Keep all operations paper-only.
- Require a stop for every new order, including manual orders.
- Prefer a take-profit and at least 1.5:1 reward-to-risk.
- Respect the active server preset; never change it merely to pass an order.
- For discretionary AI operation, add at most two positions per user request unless the user explicitly requests more.
- Keep combined modeled loss of new positions at or below 0.5% of current equity per invocation by default, even when the server is on Aggressive. Require explicit user permission for a higher experimental budget.
- Risk 0.25-0.5% of equity per trade until a setup has a verified positive out-of-sample expectancy. The server's Aggressive preset is a ceiling, not a recommendation.
- Do not call a trade efficient merely because it has a 1.5:1 target. Efficiency requires positive net expectancy, acceptable drawdown, and reasonable turnover.
- Treat delayed yfinance quotes as suitable for paper workflow testing, not precise live execution.
- Treat CFDs and futures marked `research_only` as non-tradable.
- Treat legacy unprotected positions as an explicit warning. Do not invent stops from stale legacy ideas; protect or close them only with current analysis and user authority.
- Never present simulated P&L as real profit or loss.

## Profitability gate

The skill must say "no trade" when it cannot establish an edge. NEXUS's delayed yfinance feed, market-only order milestone, LLM proposals, and lack of built-in historical replay mean a new setup is currently an experiment unless external or newly implemented research supplies comparable-trade statistics. Recommend implementing walk-forward replay and setup-level analytics before enabling recurring autopilot. Never compensate for missing evidence by increasing trade frequency, leverage, or confidence.

## Safety authority

Interpret user intent narrowly:

- "Analyze", "scan", or "find trades": create/review proposals only.
- "Open/place/approve paper trades": preview, then execute eligible protected paper orders.
- "Manage the book" or explicit discretionary permission: close, protect, and open paper positions within the rules above.
- "Enable autopilot": set `guarded_autopilot` only after health checks, then state that the agent still starts stopped after backend restart.
- Any mention of a real broker, real funds, or live trading: stop and explain that this skill supports NEXUS paper execution only.

Use `--confirm` for every CLI command that can fill, close, reject, change protection, alter mode, or toggle the kill switch. This flag confirms execution intent; it does not bypass server validation.

## Common commands

```powershell
python scripts/nexus.py snapshot
python scripts/nexus.py scan --wait
python scripts/nexus.py proposals --status pending
python scripts/nexus.py preview stock:nvda long 1 --stop 218 --target 240
python scripts/nexus.py approve prop_123 --confirm
python scripts/nexus.py order stock:nvda long 1 --stop 218 --target 240 --confirm
python scripts/nexus.py protect p123 --stop 218 --target 240 --confirm
python scripts/nexus.py close p123 --confirm
python scripts/nexus.py kill on --confirm
```

## Reporting

Lead with actions actually completed. Separate filled orders from rejected or pending proposals. Include actual position IDs/order IDs when useful. Always state:

- paper-only status;
- quote delay/staleness;
- fills, stops, targets, and modeled risk;
- resulting gross exposure and open-position count;
- whether advisory scanning or recurring autopilot remains active.
