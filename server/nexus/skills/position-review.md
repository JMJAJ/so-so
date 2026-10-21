---
name: position-review
version: 1
description: How to review open calls and decide whether to close one early.
when: When reviewing open recommendations or positions, and before close_recommendation.
---
Default: **hold**. Stops, targets and the horizon already handle exits, and closing early on a hunch usually costs money. Every early close is compared with what holding would have returned, and that comparison shows in the track record.

For each open call (list_recommendations status=open, then asset_snapshot):
1. Read its invalidation condition and thesis.
2. Check the condition against current data. Close only if one of these is true:
   - **Invalidated:** the stated invalidation condition has actually happened (quote the data that shows it).
   - **Catalyst gone:** the event the thesis depended on was reversed or cancelled (for example the rate cut was priced out, or the deal was called off), shown by a dated headline or event.
   - **New hard risk:** an earnings report or known binary event now falls inside the remaining horizon and wasn't there when the call was made.
3. Not reasons to close: the position is down but above its stop; the price is choppy; an unrelated headline; "momentum faded"; wanting to lock in a small gain before the target.
4. If closing, call close_recommendation with a one-sentence reason that names the condition and the data.
5. Summarise every reviewed call in a table: symbol, direction, current return, invalidation status (intact / triggered), and the action (hold / closed).
