---
name: position-review
version: 2
description: How to review open calls and decide whether to close one early, including on breaking news.
when: When reviewing open recommendations or positions, and before close_recommendation.
---
Default: **hold**. Stops, targets and the horizon already handle exits, and closing early on a hunch usually costs money. Every early close is compared with what holding would have returned, and that comparison shows in the track record. But news changes facts, and a position whose reason is gone should go.

For each open call (list_recommendations status=open, then asset_snapshot):
1. Read its invalidation condition and thesis.
2. Check what is new: breaking_news (instrument, minutes=1440) and shock_reaction if the asset moved >= 2σ today.
3. Close only if one of these is true:
   - **Invalidated:** the stated invalidation condition has actually happened (quote the data that shows it).
   - **Catalyst gone:** the event the thesis depended on was reversed or cancelled (the rate cut was priced out, the deal was called off), shown by a dated headline or event.
   - **Adverse shock with measured follow-through:** the asset moved >= 2σ against the position and shock_reaction shows a reliable *continuation* pattern for that side at a horizon within the remaining holding period. Quote n, t and q.
   - **New hard risk:** an earnings report or known binary event now falls inside the remaining horizon and wasn't there when the call was made.
4. Not reasons to close: the position is down but above its stop; the price is choppy; an unrelated headline; an adverse shock whose history shows reversal or noise; wanting to lock in a small gain before the target.
5. If closing, call close_recommendation with a one-sentence reason that names the condition and the data.
6. Summarise every reviewed call in a table: symbol, direction, current return, invalidation status (intact / triggered), news since entry, and the action (hold / closed).
