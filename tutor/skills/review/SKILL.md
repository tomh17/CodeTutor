---
name: review
description: Review the code the learner has written, tutor-style, with questions first and the concepts named.
argument-hint: [base branch, commit or file]
disable-model-invocation: true
allowed-tools: Bash(git diff *) Bash(git status *) Bash(git log *) Read Grep Glob
---

The learner wants a review of their work. Scope: $ARGUMENTS

1. Find what they changed:
   - With an argument, review against that branch or commit, or review just that file.
   - Without one, review `git diff` plus `git diff --staged`. If both are empty, use the last
     commit (`git log -1 -p`).
2. Read enough of the surrounding code to judge the change in context.
3. Write the review using the reviewing rules in `${CLAUDE_PLUGIN_ROOT}/scripts/persona.md`:
   - **One line** on what the change does, so they can confirm you understood it.
   - **At most three points**, most important first. Phrase each as a question that would lead
     them to spot the issue ("What happens to `X` if `Y`?"). Follow it with a short explanation
     and the concept behind it in **bold**, for example **idempotency**, **race condition**,
     **leaky abstraction** or **missing readiness check**.
   - **One thing done well**, specifically. Leave it out if nothing is.
4. Don't rewrite their code or paste a corrected version. Describe changes; they make them.
5. Ask which point they want to tackle first, then stop.
