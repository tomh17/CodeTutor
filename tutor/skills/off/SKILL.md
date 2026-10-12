---
name: off
description: Turn tutor mode off in this project so Claude Code edits files normally again.
disable-model-invocation: true
---

Relay the `[tutor:off result]` from your context in one or two sentences. From now on in this
project, the tutoring rules no longer apply and you may edit files normally again. If a drill
was mentioned, pass that warning on.

If there's no `[tutor:off result]` block in your context, the plugin's hook didn't run. Say so.
