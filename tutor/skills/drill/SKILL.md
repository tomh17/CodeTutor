---
name: drill
description: Have Claude secretly inject a realistic fault on a new branch, then debug it from a symptom-only ticket. "abort" cancels a drill.
argument-hint: [app|containers|kubernetes|networking|config|any] [easy|medium|hard] | abort
disable-model-invocation: true
---

Arguments: $ARGUMENTS

Read the `[tutor:drill result]` block in your context.

- **If it reports an error** (dirty working tree, not a git repo, a drill already running), relay
  it and stop.
- **If it says the drill was aborted**, relay the git commands it lists and stop.
- **If it says "Drill setup authorised"**, follow the steps below.

## Setting up the drill

The learner must not see the fault. Do **not** read or inject it yourself in this conversation.
Instead, launch **one** subagent with the Agent tool (general-purpose type). Pass it the brief
below, filling in the branch, topic, difficulty, seal-file path and seal command from the drill
result:

> You are preparing a debugging drill in this repository. A learner will debug what you break,
> using only a symptom report. You're on the git branch <branch>. Topic: <topic>. Difficulty:
> <difficulty>.
>
> 1. Explore the repository and pick an area that fits the topic. For example: Dockerfiles or
>    compose files for "containers"; manifests, probes, Services or ConfigMaps for
>    "kubernetes"; ports, hosts, TLS or DNS for "networking"; settings and environment variables
>    for "config"; application logic for "app". If the repository has nothing for that topic,
>    answer `NOT_POSSIBLE: <reason>` and stop.
> 2. Design ONE realistic fault: something that really happens in production. Examples: a wrong
>    port or host, a missing or misnamed environment variable, a mismatched probe path, a
>    resource limit too low, a dependency started in the wrong order, an off-by-one in a timeout
>    or retry, a race between two writers, a lock that only covers one process, a wrong volume
>    mount, a cert or SAN mismatch, a wrong image tag, a config default that doesn't match
>    another component.
>    - **easy:** the error message points close to the cause.
>    - **medium:** the symptom shows up one layer away from the cause.
>    - **hard:** cross-component or intermittent, and still deterministic enough to reproduce.
> 3. Rules:
>    - Change one to three files with a small diff.
>    - No comments or names that hint at the bug.
>    - Never touch secrets, keys, credentials, `.tutor/` or `.git/` (apart from the seal file
>      below).
>    - Delete no data.
>    - The symptom must be observable with commands the learner would normally run.
>    - If the repository has a test suite, make sure the fault doesn't simply announce itself
>      with a test named after it.
> 4. Make the change with your edit tools. Run a quick check that the symptom really occurs.
> 5. Write the answer key as JSON to <seal file path> with these fields:
>    - `title`: names the symptom, never the cause.
>    - `ticket`: 3–6 sentences, written the way a teammate or user would report it. Symptoms
>      only.
>    - `how_to_reproduce`: the commands that show the symptom.
>    - `root_cause`
>    - `fix`
>    - `files`: a list.
>    - `hints`: a list of four strings, matching levels 1–4: a nudge question, where to look, the
>      concept, a parallel example.
>    - `concepts`: a list.
> 6. Run: <seal command>
> 7. Reply with ONLY `SEALED <drill id>` or `NOT_POSSIBLE: <reason>`. Don't describe the fault.

## After the subagent replies

- **`SEALED`:** read `.tutor/drills/<id>/ticket.md` and show the learner the ticket section and
  the "How to see it" section. Tell them the timer is running, and remind them of
  `/tutor:stuck` and `/tutor:done`. Don't look at the diff or the key. Don't speculate about the
  cause.
- **`NOT_POSSIBLE`:** relay the reason, and tell them to run `/tutor:drill abort` and pick
  another topic.
- **Anything else** (the subagent described the fault, for example): tell the learner the setup
  leaked and suggest `/tutor:drill abort`.
