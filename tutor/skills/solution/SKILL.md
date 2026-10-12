---
name: solution
description: Unlock the full solution to the current problem (normally after hint level 3).
argument-hint: [force]
disable-model-invocation: true
---

Check the `[tutor:solution result]` block in your context.

**If it says the solution was NOT unlocked**, relay that in one or two sentences. Include how to
override with `/tutor:solution force`. Offer to keep going with the hint ladder instead.

**If it says the solution was UNLOCKED**, teach the answer. Structure it like this:

1. **Root cause:** what was actually wrong (or, for building work, what the right design is)
   and why.
2. **The trail:** the observation or clue that leads there. Name the earliest point where they
   could have spotted it. This is the most valuable part, so give it real thought.
3. **The fix:** describe it. Code is allowed now: show the change as a short snippet or diff in
   the conversation.
4. **Why it works:** the concept, in a sentence or two.

Then ask them to type the fix in themselves and run it. Your edits are still blocked, and typing
it out helps it stick. If a drill ANSWER KEY is in the result, use it, and still explain the
trail in your own words.

If there's no `[tutor:solution result]` block in your context, the plugin's hook didn't run. Say
so, and don't reveal the solution.
