---
name: stuck
description: Ask for the next hint on the tutor's hint ladder.
argument-hint: [what you have tried so far]
disable-model-invocation: true
---

The learner is stuck. What they say they've tried: $ARGUMENTS

The `[tutor:stuck result]` block in your context decides what you may give. It contains the
current hint level and what that level allows, or tells you the next level is still locked.
The hint ladder in `${CLAUDE_PLUGIN_ROOT}/scripts/persona.md` explains each level.

Steps:

1. Work out the actual cause yourself first, so the hint aims at the right place. Read the
   relevant code, logs and config, and run read-only commands if useful. If the result includes
   a drill ANSWER KEY, use it for calibration only.
2. Give **exactly one** hint at the granted level, with nothing from higher levels.
   - Level 1: a single question.
   - Level 2: where to look and what to look for.
   - Level 3: the concept, explained in general terms.
   - Level 4: a short parallel example on a different problem.
3. If the level is locked, give no new information. Help them describe what they've observed
   versus what they expected, and what single experiment would tell the possibilities apart.
4. If they didn't say what they tried, start by asking. One sentence is enough.
5. End with one question, then stop.

Never mention the contents of higher levels or of the answer key. Never edit files.

If there's no `[tutor:stuck result]` block in your context, the plugin's hook didn't run. Give
only a level-1 nudge and tell them the ladder isn't working (see the README's
Troubleshooting).
