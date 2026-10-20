# NEXUS — evidence-based investment research

NEXUS is a local research terminal whose AI recommends what to invest in over the next 1–8 weeks.
It grounds those calls in market history, news history and how the two have been correlated.
Every recommendation is then paper-traded and scored, so you can see whether the AI is right.

It covers about 150 instruments: US large caps, sector/bond/commodity ETFs, crypto, major FX
pairs and commodity futures.

## How it works

```
 prices (yfinance, 10y daily) ─┐
 macro (FRED, keyless) ────────┤        ┌─ event studies: what each asset did after each kind of event
 earnings surprises ───────────┼─ events┤─ historical analogs: past dates that looked like today, and what came next
 geopolitics (GDELT) ──────────┤        ├─ lead-lag correlations: drivers that predicted an asset's next 20 sessions
 headlines (RSS, Yahoo,        │        └─ quant signals, validated walk-forward (and reported honestly when they don't work)
   Finnhub, GDELT) ── LLM tags each headline with an event category that has measured history
                                   │
            AI analyst / chat (tool use over all of the above) ── recommendation with cited evidence
                                   │
            paper broker (autopilot) ── scorer (hit rate, excess return, calibration) ── lessons fed back to the AI
```

- **Structured events with long history.** These are detected from data, not guessed: earnings
  beats and misses, Fed hikes and cuts, CPI and payroll surprises, VIX/oil/yield/dollar/crypto
  shocks, credit stress, and GDELT spikes in armed conflict, Middle East, Russia–Ukraine, US–China,
  sanctions and unrest. Each event's date is the first session the market could react, so measured
  returns are ones you could actually have captured.
- **News today, mapped to history.** The fast LLM classifies each new headline into a category,
  and each category maps to the historical event types that are the best evidence for it.
  "How did this kind of news affect X before?" is answerable from day one.
- **Honesty built in.** Every number carries `n`, hit rate, edge vs. normal and a t-stat. The quant
  model is validated walk-forward per asset class. If it has no out-of-sample edge, its forecast
  falls back to the base rate and the AI is told so.
- **Guarding against luck.** Event effects are measured against a beta-adjusted benchmark
  (market model, trailing-year beta). With thousands of (event × asset) tests, an effect only
  counts as *reliable* if it survives a Benjamini–Hochberg false-discovery correction (q ≤ 0.10)
  and both halves of its history agree in sign.
- **Probabilities come from data, not the LLM.** For each proposed trade the server simulates the
  same stop and target from every past entry day (single stocks have their survivor drift
  removed). It adjusts that base rate only for reliable evidence, shrinks the adjustment by how
  well evidence predicted outcomes before, and records the call only if its expected value is
  positive. The AI's own number is kept for comparison.
- **A track record without waiting.** A point-in-time replay runs the evidence engine on past dates
  using only what was known then. Until 20 live calls have closed, its calibration sets how much
  evidence is trusted.
- **Checks on the AI.** Every t-stat, `n` and percentage the AI quotes is looked up in the tool
  results it actually received, and anything unsupported is flagged under the answer.
- **Portfolio risk.** A new position whose returns move with existing ones (60-day correlation,
  adjusted for long/short) counts as the same bet. It's refused above two risk budgets per bet.
- **Verification.** Recommendations are scored on their own path (stop, target or horizon) against
  a benchmark. The Track Record page shows calibration (stated probability vs. realized) and what
  kinds of evidence actually made money.

## Quick start

Prerequisites: Node 18+ (or Bun), Python 3.11+.

```bash
npm install
cd server && pip install -r requirements.txt
```

Set an LLM key in `.env` (see `.env.example`) or later in the app under **Settings**. Anthropic
(Claude) is the default. OpenAI, OpenRouter, Ollama and LM Studio also work.

Windows, both servers at once:

```powershell
.\start-nexus.ps1
```

Or in two terminals:

```bash
cd server && python -m uvicorn main:app --port 8000
npm run dev   # http://localhost:3000
```

On first launch the backend bootstraps itself. It downloads 10 years of daily history, FRED macro
series, ~2,500 earnings surprises and 30 days of GDELT, then builds the event studies and runs the
walk-forward backtest. This takes about 10–20 minutes and progress shows in the header. The rest of
the GDELT history backfills in the background.

## The app

| View | What it's for |
|---|---|
| **AI chat** | Full-page chat with conversation history, inline charts and the slash commands below |
| **Today** | Market regime, the AI's brief, open calls with live marks, events that historically move markets, classified headlines |
| **Screener** | Every instrument with its signal z-scores and 20-session forecast |
| **Asset** | Candles with event markers; forecast breakdown; analog fan chart; event history with every past occurrence; correlations and lead-lag drivers; news; past AI calls |
| **News & events** | Classified headlines, detected events, and the event library (which assets each event type moves most reliably) |
| **Portfolio** | Paper positions, equity vs. SPY, closed trades |
| **Track record** | Hit rate, excess return, Brier score, calibration, breakdowns by evidence type, quant model validation |
| **Settings** | LLM provider and keys, risk, universe, background jobs, analyst runs, logs |

**AI chat** has its own page, and **Ask AI** (top right) opens the same conversation as a sidebar on
any other page. It uses the same tools as the analyst and can draw charts inline (price with a call's
entry/stop/target, performance comparisons, analog fans, event studies, equity vs SPY). Charts are
built from stored data, not from numbers the model types. Slash commands:

| Command | Does |
|---|---|
| `/invest [focus]` | Scan, investigate the strongest candidates, record the trades with real evidence (paper positions via autopilot), chart each one |
| `/chart <anything>` | e.g. `/chart GLD vs SPY over 2 years`, `/chart what gold did after rate cuts` |
| `/scan`, `/why NVDA`, `/recommend gold` | Rank candidates, review one asset, record a single call |
| `/regime`, `/news`, `/backtest`, `/record`, `/portfolio` | Macro regime, headlines with history, model validation, track record, position review |

## CLI (also usable by Claude Code)

Run these from `server/`. Add `--json` for machine-readable output.

```bash
python -m nexus init                 # first-run bootstrap
python -m nexus update               # daily refresh (bars, macro, events, scoring, forecasts)
python -m nexus scan --class etf     # ranked candidates
python -m nexus asset NVDA           # full evidence bundle for one instrument
python -m nexus event rate_cut GLD   # event study: what GLD did after Fed cuts
python -m nexus ask "what usually happens to oil after Middle East escalations?"
python -m nexus recommend --focus semiconductors
python -m nexus recs --status all
python -m nexus why rec_ab12cd34ef
python -m nexus report               # is the AI actually right?
python -m nexus backtest --run       # recompute walk-forward validation
python -m nexus replay --run         # point-in-time replay of the evidence engine + calibration
python -m nexus news-backfill        # ~1y Finnhub company news + 3 months GDELT, deduped, classified
```

## Schedule (UTC, in-process)

| Job | When |
|---|---|
| monitor (fills, stops, targets, expiry) | every 5 min |
| news fetch + LLM classification | every 30 min |
| daily data, scoring, forecasts | 21:45 daily |
| AI analyst run | 22:30 Mon–Fri |
| earnings, event studies, backtest, replay | Saturday 06:00 |
| GDELT history backfill | every 2 h until complete |

## Limits worth knowing

- Prices are delayed yfinance data. Paper fills add slippage, and orders placed while a market is
  closed fill at the next open.
- CPI and payroll surprises use first-release values and exact release dates from ALFRED when a
  (free) FRED API key is set in Settings. Without one they fall back to revised FRED data with
  approximate dates, flagged `approx_date`.
- Event-study t-stats use overlapping windows and are optimistic, which is why only FDR-corrected,
  split-half-stable effects count as reliable. The walk-forward backtest uses non-overlapping samples.
- The universe is today's large caps, so stock history is survivor-biased. Probabilities remove each
  stock's excess drift over the S&P 500; event studies are relative to a benchmark, which limits it.
- This is a research tool with paper money. It is not investment advice.

See `AGENTS.md` for the code layout.
