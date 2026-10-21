---
name: pre-trade-checklist
version: 1
description: The checks every new trade must pass before propose_recommendation.
when: Before calling propose_recommendation, every time.
---
Work through these in order. Stop at the first hard fail and say which check failed; "no trade" is a valid answer.

1. **Independent evidence (hard).** List the evidence for the trade by kind: reliable event effect (load event-playbook), quant model with a walk-forward edge (model_has_edge true), analogs, lead-lag driver (correlations), classified news. Two pieces of the same kind count as one. You need at least two different kinds pointing the same way. Analogs or news alone are not enough: neither has a validated track record.
2. **Already priced in?** asset_snapshot: if ret_5d has already moved by most of the expected edge in the trade's direction, the move has happened. Skip it, or say why more is left.
3. **Earnings inside the holding period (hard for stocks).** asset_snapshot next_earnings: if a report falls before the horizon ends, either shorten horizon_days to end before it or skip. An earnings gap can jump straight over the stop.
4. **Same bet as the book.** portfolio: if an open position is in the same sector or moves with this one (correlations: rho > 0.5 for the same direction, or < -0.5 for the opposite), this adds to that bet instead of diversifying. The broker refuses trades past the correlated-risk limit, so check before proposing.
5. **Track record.** track_record: if this kind of evidence, asset class or direction has lost money over n >= 5 closed calls, say so and require stronger evidence.
6. **Bracket.** Stop where the thesis is wrong: 1.5 to 2.5x daily ATR (vol_20d x price / sqrt(252) is a fair ATR proxy), beyond obvious recent levels. Target at reward/risk >= 1.5. Don't move the stop closer to make the numbers work.
7. **Invalidation.** Write one concrete, checkable condition that would prove the thesis wrong before the stop is hit (for example "XLE closes above its 50-day average" or "next CPI prints below consensus"). position-review uses it later.

Then call propose_recommendation. The server computes the probability and expected value from data and rejects calls with no edge. Report its verdict as given.
