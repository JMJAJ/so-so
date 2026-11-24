---
name: event-trade
version: 1
description: How to trade breaking news or a price shock within minutes: follow it, fade it, exit, or pass.
when: In a live event run, or whenever the user asks what to do about something that just happened.
---
Speed matters, but the edge is not in being first to the headline: it is in knowing what this asset usually does *after* a move like this one. Work fast and in this order.

1. **What happened, and is it real?** breaking_news (instrument, minutes=720) and recent_news (days=2). Find the first report; the clock starts there. Then shock_reaction: today's move in σ. If it warns about a bad print or the bars and quote disagree, stop: no trade.
2. **Is it new information?** A follow-up ("extends gains after...") of a story that is days old is not a new event. A single magnitude-1 headline is noise. Name the category (CEO change, guidance, M&A, regulator, sanctions, central bank, war...).
3. **What follows shocks like this?** From shock_reaction, read the reliable horizons: *continuation* means trade with the move, *reversal* means fade it. If no horizon is reliable, the reaction history is noise for this asset: the trade can still go ahead at base_rate size if the server finds positive EV, but say plainly that there is no measured edge.
   Then check event_effects (horizon 5) for a mapped structured event (earnings beat/miss, rate decision, oil shock, geopolitics).
4. **Held position?** If the book holds the asset (the task says so, or `portfolio`), decide that first:
   - the news breaks the stated invalidation or catalyst, or a reliable reaction points against the position at the remaining horizon: close_recommendation, naming the headline and the statistic;
   - otherwise hold, and say why the stop is still the right exit.
5. **New trade.** Horizon 2-10 sessions, matching the reliable reaction horizon when there is one. Stop on the wide end (2-2.5x ATR, post-shock volatility is higher), target at reward/risk >= 1.5. Stocks with earnings inside the horizon: skip. Invalidation tied to the news ("guidance is walked back", "closes back below the pre-news price X").
6. **Propose** once. The server replays your bracket from past shock days, applies the reliable reaction, and sizes it. If it rejects and suggests a bracket that still fits the thesis, propose that. If it rejects without one, that is the answer.

Report in three sentences: what happened (headline, time, move in σ), what history says (pattern, n, t, q), what you did (trade with size tier, close, or pass and why).
