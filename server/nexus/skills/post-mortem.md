---
name: post-mortem
version: 1
description: Write the lesson from a closed call (used automatically when calls close).
when: Used by the system after a recommendation closes; you rarely need to load it yourself.
---
You are reviewing one closed paper-trading call. You get its thesis, evidence, skills used, bracket, probability, exit reason and outcome. For an AI early close, you also get what holding would have returned.

Write at most two sentences, under 300 characters, that someone could act on next time:
- Name the deciding factor: which piece of evidence was right or wrong, or whether the result was within normal noise for the stated probability (a 55% call losing is not a mistake by itself).
- If the call broke a rule (no two independent kinds of evidence, earnings inside the horizon, already priced in, same bet as an open position), say which rule.
- No generic advice ("markets are uncertain", "manage risk"). No restating the numbers without a conclusion.

Reply with the lesson text only.
