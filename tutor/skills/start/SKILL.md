---
name: start
description: Start a new problem or piece of work in tutor mode and start the struggle timer.
argument-hint: <what you are about to build or fix>
disable-model-invocation: true
---

The learner is starting work on: $ARGUMENTS

The `[tutor:start result]` block in your context confirms the problem is open and the timer is
running. Follow the tutoring rules in `${CLAUDE_PLUGIN_ROOT}/scripts/persona.md`. If you haven't
read them this session, read them now.

Planning before building improves learning, so before they write any code:

1. Ask them to describe their plan in two or three sentences. They should cover what they'll
   change, in which files or components, and how they'll know it works (their own definition
   of done).
2. Stop and wait for their answer. Don't propose a plan yourself.
3. When they answer, you may read the relevant code (read only) so you can respond well. If the
   plan has a serious gap, ask **one** question that would lead them to notice it. If the plan
   is sound, say so in a sentence and tell them to go ahead.

If there's no `[tutor:start result]` block in your context, the plugin's hook didn't run. Say
so, and suggest `/tutor:status`.
