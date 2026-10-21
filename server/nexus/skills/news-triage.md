---
name: news-triage
version: 1
description: How to tell if a headline is new, tradable information or noise that is already priced in.
when: Before citing a headline or news flow as evidence for a trade.
---
For each headline you want to use:

1. **Is it new?** Headlines are deduplicated by story, but the same news often returns as follow-ups ("stocks extend gains after..."). Find the first report in recent_news (days=7). The clock starts there.
2. **Has the price reacted?** Compare the move since the first report (asset_snapshot ret_5d, or show_chart price) with the typical reaction for its category (event_study for the mapped event type, horizon 0 and 5). If most of the typical move has happened, the news is priced in. It is context now, not an edge.
3. **Does it map to measured history?** recent_news gives historical_analogs (event types) for each category. Only a mapped type with a reliable effect (load event-playbook) counts as evidence. A category without one is a story, not evidence.
4. **Magnitude and breadth.** One magnitude-1 headline is noise. Several independent sources with magnitude >= 2 over more than a day is a theme.
5. **Direction conflicts.** If news points one way and the reliable event history or the quant model points the other, the measured evidence wins. Say so.

In the answer, write the news evidence as: the headline (with date), the mapped event type, whether that type is reliable for this asset, and how much of the typical move is already done.
