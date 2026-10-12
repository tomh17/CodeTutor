---
name: done
description: Finish the current problem or drill, reflect on it, and turn the lessons into flashcards.
disable-model-invocation: true
---

The `[tutor:done result]` block in your context tells you which case applies. The bookkeeping
command prefix appears in your tutor context ("Bookkeeping commands Claude may run"). If it
isn't there, use `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"`.

## Case A: an ordinary problem was closed

1. Report the summary line in one sentence (time taken, hint level reached).
2. Ask these three reflection questions in one short message, then **stop and wait**:
   - What was the cause, or what did you build, in a sentence or two?
   - Which observation or clue moved you forward the most?
   - Next time, what would you check first?
3. After they answer:
   - Give two or three sentences of honest feedback on their explanation. Correct anything
     wrong and add the missing piece, if any.
   - Write 2–4 flashcards to `.tutor/notes/cards-incoming.json`, as a JSON list of
     `{"front": ..., "back": ..., "topic": ...}`. Base them on what *they* found hard, and favour
     "why" and "how would you tell" questions over trivia. Then run `<prefix> card-add
     .tutor/notes/cards-incoming.json`.
   - Write a short journal entry (goal, what happened, the lesson, in their words where
     possible) to `.tutor/notes/journal-entry.md`. Then run `<prefix> note
     .tutor/notes/journal-entry.md`.
   - Tell them the cards will come up in `/tutor:cards` starting tomorrow.

## Case B: a drill moved to POSTMORTEM

1. Ask them to write a short postmortem with these headings, then **stop and wait**. Don't run
   `drill-key` yet.
   - **Symptom:** what was observed.
   - **Investigation:** what they checked, in order, and what each step told them.
   - **Root cause:** what was actually wrong.
   - **Fix:** what they changed.
   - **Prevention:** what test, alert, check or design change would have caught it sooner.
2. After they've written it, run `<prefix> drill-key` and compare their postmortem with the key:
   - What they got right.
   - Anything they missed or got wrong.
   - The fastest path from the symptom to the cause (the trail), and how theirs compared.
3. Run `<prefix> drill-close`, and pass on the git commands it prints for getting back to their
   branch. Don't run those commands yourself.
4. Write 2–4 flashcards and a journal entry as in Case A. The journal entry includes their
   postmortem.

If there's no `[tutor:done result]` block in your context, the plugin's hook didn't run. Say so.
