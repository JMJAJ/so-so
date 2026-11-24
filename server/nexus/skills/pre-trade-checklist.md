---
name: pre-trade-checklist
version: 3
description: The checks every new trade goes through before propose_recommendation, and what each one changes.
when: Before calling propose_recommendation, every time.
---
The server decides whether a trade has an edge and how big it is: it computes the probability and expected value from data, rejects EV <= 0, and sizes the rest by evidence tier (core 100%, tactical 60%, base_rate 35% of the risk budget). Your job is a coherent thesis, a sane bracket and an honest invalidation. Do not refuse a trade only because you count fewer than two kinds of evidence: propose it, and let the server price and size it. Refuse only on a hard fail below.

**Hard fails (no trade):**
1. **Bad data.** asset_snapshot / shock_reaction warnings about a bad print, or a move the bars and the live quote disagree on. Say what looks wrong.
2. **Earnings inside the holding period (stocks)**, unless the earnings report is the event being traded. Shorten horizon_days to end before it, or skip. A gap can jump straight over the stop.
3. **Directly against reliable evidence.** A reliable event effect, shock reaction or validated model pointing the other way. The server would lower p anyway; don't fight it.
4. **The server says no.** EV <= 0 for every bracket it suggests. Report its verdict as given.

**Checks that shape the trade (adjust, don't veto):**
5. **Evidence.** List what supports the trade by kind: reliable event effect (event_effects), shock reaction (shock_reaction, when today moved >= 2σ), quant model with walk-forward edge, analogs, lead-lag drivers, classified news. Analogs and news are context: cite them, but only the first three move the server's probability.
6. **Already priced in?** If ret_5d has already moved most of the expected edge, say why more is left (a reliable continuation pattern is a reason) or shorten the horizon.
7. **Same bet as the book.** Positions in `portfolio` that are the same sector or rho > 0.5 (same direction) add to that bet. The broker refuses trades past the correlated-risk limit; prefer the cleaner expression.
8. **Track record.** If this kind of evidence, asset class or direction lost money over n >= 5 closed calls, say so and prefer a shorter horizon or a better-evidenced alternative.
9. **Bracket.** Stop where the thesis is wrong: 1.5 to 2.5x daily ATR (vol_20d x price / sqrt(252)), beyond obvious recent levels; after a shock, use the wider end. Target at reward/risk >= 1.5. If the server rejects your bracket and suggests one, use it only if it still fits the thesis.
10. **Invalidation.** One concrete, checkable condition that would prove the thesis wrong before the stop (for example "NVDA closes back below 150" or "the export ban is confirmed"). position-review and the live event trader use it.

Then call propose_recommendation and report the server's probability, EV and size tier as given.
