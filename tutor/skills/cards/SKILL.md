---
name: cards
description: Spaced-repetition review of the flashcards built from your own problems and drills.
argument-hint: [how many, default 10]
disable-model-invocation: true
---

Run a flashcard review. Use the bookkeeping command prefix from your tutor context, or
`bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"` if it isn't there.

1. Run `<prefix> cards-due $ARGUMENTS`. If nothing is due, say when the next card is due and
   stop.
2. Go through the cards **one at a time**:
   - Show only the **front**, then stop and wait. They answer from memory: no hints and no
     multiple choice. "I don't know" is a fine answer.
   - After they answer, show the **back**. In a sentence or two, say what they got right and
     what they missed.
   - Grade it:
     - `again`: wrong or blank.
     - `hard`: right but shaky or slow.
     - `good`: right and confident.

     If they want to grade themselves, let them.
   - Run `<prefix> card-grade <id> <grade>`, then show the next card.
3. At the end, give the score in one line, and name the topic they should revisit if one keeps
   coming up.

Don't show more than one front at a time, and never show a back before they've answered.
Retrieving the answer is the exercise.
