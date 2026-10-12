---
name: status
description: Show tutor mode state, the open problem, hint level, due flashcards and history.
disable-model-invocation: true
---

Present the `[tutor:status result]` from your context compactly: a few lines, without repeating
labels. Then suggest the single most useful next action, for example `/tutor:cards` if cards are
due, `/tutor:done` if a problem has been open a long time, or `/tutor:start` if nothing is open.

If there's no `[tutor:status result]` block in your context, the plugin's hook didn't run. Say
so, and point to the README's Troubleshooting section.
