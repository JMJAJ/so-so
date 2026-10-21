---
name: nexus
description: Use the NEXUS research system in this repo to answer market questions with real data (event studies, historical analogs, correlations, classified news, regime, backtests), review or create paper-trading recommendations, and check the AI's track record. Use when the user asks what to invest in, why an asset moved, what historically follows an event, or how the paper portfolio / AI calls are doing.
---

# NEXUS CLI

Run commands from `server/` with `python -m nexus <command>`. Add `--json` (before the
subcommand) for structured output, e.g. `python -m nexus --json scan`. The commands read the
local SQLite store directly; the API server doesn't need to be running.

If commands report missing data, the store hasn't been bootstrapped. Tell the user
`python -m nexus init` takes 10–20 minutes before running it.

## Research (read-only, no LLM needed)

| Command | Returns |
|---|---|
| `scan [--class stock\|etf\|crypto\|forex\|commodity] [--direction long\|short] [--limit N] [--refresh]` | Ranked candidates with forecast, signal z-scores, recent events, news flow |
| `asset <SYMBOL or id>` | Snapshot, active events with historical effect, most reliable event effects, analogs, correlations/lead-lag, news |
| `event <event_type> <SYMBOL>` | Event study per horizon (0/5/10/20/40 sessions) and every past occurrence |
| `regime` | Risk-on/off, VIX, curve, rates, dollar, credit, conflict intensity, recent macro events |
| `backtest [--run]` | Walk-forward validation per asset class and per-signal IC |
| `portfolio`, `recs [--status open\|closed\|all]`, `why <rec_id>`, `report` | Paper account, recommendations, a call's thesis/evidence/outcome, track record |

Event types: earnings_beat, earnings_miss, rate_hike, rate_cut, inflation_hot, inflation_cool,
jobs_strong, jobs_weak, vix_spike, equity_selloff, oil_shock_up, oil_shock_down, yield_spike,
yield_drop, dollar_surge, dollar_slump, credit_stress, crypto_crash, crypto_surge,
geopolitical_escalation, mideast_escalation, russia_ukraine_escalation, us_china_tension,
sanctions_wave, unrest_spike.

## AI actions (use the configured LLM; cost money)

- `ask "<question>" [--conv <id>]` runs the in-app chat agent with the same tools.
- `recommend [--focus <text>] [--max N]` runs the analyst, which may record recommendations and
  open paper positions if autopilot is on. Confirm with the user before running it.

## Reading the numbers

- `edge` = mean return after the event minus the asset's normal return over the same period.
  Overlapping windows make |t| < 2 noise. `n` < 8 is thin.
- Stocks/ETFs are measured vs SPY and alt-coins vs BTC; FX, commodities, SPY and BTC use raw returns.
- `model_has_edge: false` means the walk-forward test found no reliable quant edge for that
  asset class. `prob_up` is then just the historical base rate.
- Always quote n, edge/hit rate and t when relaying evidence. This is paper-trading research,
  not personal investment advice.
