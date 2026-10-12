---
name: on
description: Turn tutor mode on in this project. You write the code; Claude asks questions, gives hints and reviews.
disable-model-invocation: true
---

The learner has turned on tutor mode. The `[tutor:on result]` block in your context says what
changed.

1. Read `${CLAUDE_PLUGIN_ROOT}/scripts/persona.md` now. Follow it for the rest of this session.
2. Confirm in two or three lines that tutor mode is on, that the plugin now blocks your edits,
   and where their notes, flashcards and journal live (`.tutor/` in this project).
3. Show this command list exactly once:

   | Command | Use it to |
   |---|---|
   | `/tutor:start <goal>` | Begin a piece of work. Starts the struggle timer. |
   | `/tutor:stuck [what you tried]` | Get the next hint on the ladder. |
   | `/tutor:solution` | Unlock the full answer (after level 3, or `force`). |
   | `/tutor:review [base]` | Get a review of what you've written. |
   | `/tutor:done` | Finish a problem and reflect. Turns it into flashcards. |
   | `/tutor:drill [topic] [easy\|medium\|hard]` | Have Claude break something for you to debug. |
   | `/tutor:cards` | Spaced-repetition review of your flashcards. |
   | `/tutor:status` | See where you are and your history. |
   | `/tutor:off` | Go back to normal Claude Code. |

4. Ask what they're about to work on.

If there's no `[tutor:on result]` block in your context, the plugin's hook didn't run. Say so,
and point them to the Troubleshooting section of the Code Tutor README.
