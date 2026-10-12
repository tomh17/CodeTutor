# Code Tutor

A Claude Code plugin that turns Claude from the one who writes the code into a tutor. **You
write every line.** Claude asks questions, gives hints on a timed ladder, reviews what you
built, breaks things on purpose so you can practice debugging, and turns what you struggled
with into flashcards.

It's slower than letting Claude build. That's deliberate: the aim is skills you keep, so you
can build, run and debug a large codebase without AI.

---

## Contents

- [Why it works this way](#why-it-works-this-way)
- [Requirements](#requirements)
- [Install](#install)
- [Five-minute tour](#five-minute-tour)
- [Commands](#commands)
- [How it works](#how-it-works)
  - [The pieces](#the-pieces)
  - [Who can flip which switch](#who-can-flip-which-switch)
  - [The edit guard](#the-edit-guard)
  - [The hint ladder](#the-hint-ladder)
  - [Drills](#drills)
  - [Flashcards](#flashcards)
  - [Where things are stored](#where-things-are-stored)
- [Configuration](#configuration)
- [A practice plan](#a-practice-plan)
- [Limits](#limits)
- [Troubleshooting](#troubleshooting)
- [Developing the plugin](#developing-the-plugin)

---

## Why it works this way

Each feature follows a specific research finding:

| Finding | What the plugin does about it |
|---|---|
| Testing yourself and spacing practice over time are the two most effective study techniques; rereading and highlighting are among the least ([Dunlosky et al., 2013](https://www.psychologicalscience.org/news/releases/which-study-strategies-make-the-grade.html)). | `/tutor:done` turns each problem into flashcards. `/tutor:cards` quizzes you from memory, on a schedule that spaces the cards out. |
| Struggling with a problem *before* being taught the answer leads to deeper understanding ("productive failure", [Sinha & Kapur, 2021](https://www.weforum.org/stories/2021/09/students-who-productively-fail-learn-more/)). | A struggle timer: hints beyond a single nudge stay locked for the first 10 minutes. |
| Unrestricted AI help raised practice scores but lowered exam scores. A version limited to hints mostly removed that harm ([Bastani et al.](https://papers.ssrn.com/abstract=4895486)). | Claude's edits are blocked by a hook, not just by instructions. Help comes in graded hints. |
| Developers learning a new library with AI help scored 17 points lower on a later quiz, with the largest gap on debugging. Those who asked only conceptual questions and fixed their own errors kept most of the learning ([Anthropic, 2026](https://www.anthropic.com/research/AI-assistance-coding-skills)). | Conceptual questions get full answers. "Fix this" gets a question back. Drills give you debugging practice on purpose. |
| Planning before building, and explaining afterwards, improve transfer to new problems. | `/tutor:start` asks for your plan before you code. `/tutor:done` asks you to explain the cause, the clue and what you'd check first next time. |

---

## Requirements

- **Claude Code** in the terminal or the VS Code extension, recent enough to support
  `UserPromptExpansion` hooks. Built and validated against v2.1.296.
- **Python 3.9+** (`py`, `python3` or `python` on your PATH).
- **Git.** Drills and reviews use it. On Windows, Claude Code runs hooks through **Git Bash**,
  which comes with Git for Windows.

---

## Install

### Option A: install from this folder (recommended)

In Claude Code (terminal or VS Code), run:

```
/plugin marketplace add C:\Users\Username\Documents\Projects\CodeTutor
/plugin install tutor@code-tutor-local
```

Then start a new Claude Code session. The plugin loads in every project, but it **does
nothing** until you type `/tutor:on` in a project.

To pick up changes you make to the plugin later: `/plugin marketplace update code-tutor-local`,
then start a new session.

### Option B: load it for one session (handy while editing the plugin)

```
claude --plugin-dir C:\Users\UserName\Documents\Projects\CodeTutor\tutor
```

---

## Five-minute tour

Use a real project. PersonalAIAssistant works well, and a clean git tree makes drills
possible.

```
/tutor:on
```
Claude confirms tutor mode is on. From now on it cannot edit files in this project. A `.tutor/`
folder appears, and it's excluded from git automatically.

```
/tutor:start add a /readyz endpoint to the gateway that fails while the model is loading
```
The struggle timer starts. Claude asks for your plan in two or three sentences before you code.

*…you work on it. You ask Claude conceptual questions whenever you like…*

```
/tutor:stuck I added the route but don't know how to check the inference state
```
You get a level-1 nudge: a single question. Ask again in a few minutes and, once 10 minutes
have passed, you get level 2 (where to look), and so on.

```
/tutor:review
```
Claude reviews your diff: at most three points, each asked as a question first, each naming
the concept involved.

```
/tutor:done
```
Claude asks three reflection questions. After you answer, it writes 2–4 flashcards from what
*you* found hard, plus a journal entry.

Tomorrow:

```
/tutor:cards
```

When you have a clean tree and 30 minutes:

```
/tutor:drill networking medium
```

---

## Commands

| Command | What it does |
|---|---|
| `/tutor:on` | Turn tutor mode on for this project (the folder containing `.tutor/`). |
| `/tutor:off` | Turn it off. Claude edits normally again. Your history is kept. |
| `/tutor:start <goal>` | Open a problem and start the struggle timer. Claude asks for your plan. |
| `/tutor:stuck [what you tried]` | The next hint, if it has unlocked (see [the hint ladder](#the-hint-ladder)). |
| `/tutor:solution` | Unlock the full answer once you've reached hint level 3. `/tutor:solution force` overrides that, and the override is recorded. |
| `/tutor:review [base]` | Review your uncommitted work, or your work against a branch or commit, or a single file. |
| `/tutor:done` | Close the problem or drill, reflect on it, and make flashcards and a journal entry. |
| `/tutor:drill [topic] [difficulty]` | Claude secretly breaks something on a new branch and gives you a symptom-only ticket. Topics: `app`, `containers`, `kubernetes`, `networking`, `config`, `any`. Difficulty: `easy`, `medium`, `hard`. |
| `/tutor:drill abort` | Cancel a drill. |
| `/tutor:cards [n]` | Review the flashcards that are due, from memory, one at a time. |
| `/tutor:status` | Mode, open problem, hint level, cards due, and your history. |

You can ask normal questions at any time. Conceptual questions ("What's the difference between a
liveness and a readiness probe?") get full answers. Requests to write or fix code get a
question back, or a pointer to `/tutor:stuck`.

---

## How it works

### The pieces

```
tutor/
├── .claude-plugin/plugin.json   name, version, description
├── hooks/hooks.json             the four hooks below, all calling scripts/run.sh
├── scripts/
│   ├── run.sh                   finds Python (py -3, python3 or python), then runs tutor.py
│   ├── tutor.py                 the engine: state, hint ladder, guard, drills, cards (stdlib only)
│   └── persona.md               the tutoring rules Claude follows in tutor mode
└── skills/<command>/SKILL.md    one per slash command: what Claude does after the command
```

Each slash command works in two halves:

1. A **hook** (code) changes the state and decides what's allowed. For example, `/tutor:stuck`
   raises the hint level only if enough time has passed.
2. A **skill** (instructions) tells Claude how to act on the result. For `/tutor:stuck`, that
   means giving exactly one hint at the level the hook granted.

Four hooks connect the plugin to Claude Code:

| Hook | When it fires | What it does |
|---|---|---|
| `SessionStart` | A session starts, resumes or is compacted | If tutor mode is on here, tells Claude so, points it at `persona.md`, and adds the current status. |
| `UserPromptSubmit` | Every message you send | Adds one line of state (mode, open problem, minutes elapsed, hint level). This keeps Claude anchored to the real clock instead of guessing. |
| `UserPromptExpansion` | **You** type a `/tutor:*` command | Runs the state change (`on`, `start`, `stuck`, `solution`, `done`, `drill`, `status`, `off`) and passes the result to Claude as context. |
| `PreToolUse` | Before Claude edits a file or runs a shell command | The [edit guard](#the-edit-guard). |

Every hook first looks for `.tutor/state.json` in the current folder or a parent. If there
isn't one, or tutor mode is off, it exits immediately. That's why the plugin has no effect on
your other projects.

### Who can flip which switch

The design question was how to stop Claude from making things easier for itself, for example by
raising its own hint level or unlocking a solution.

- **Only you can change how much help you get.** These state changes run inside the
  `UserPromptExpansion` hook, which Claude Code fires only when a person types a slash command.
  The skills are also marked `disable-model-invocation`, so Claude can't trigger them itself.
  `tutor.py` has no command-line way to reach them.
- **Claude can do bookkeeping:** `status`, `cards-due`, `card-grade`, `card-add`, `note`,
  `drill-seal`, `drill-key` and `drill-close`. Each refuses to run in the wrong mode. For
  example, `drill-key` opens only during a postmortem, after *you* typed `/tutor:done`.
- **The guard enforces the boundary.** Claude may run the plugin script only in its plain form,
  `bash ".../run.sh" <allowed command> [simple args]`, with nothing chained on. Any mention of
  the hook entry points, `state.json` or the drill key folder is refused.

### The edit guard

While tutor mode is on, the `PreToolUse` hook handles each kind of action like this:

| Claude tries to | Result |
|---|---|
| `Edit`, `Write`, `MultiEdit` or `NotebookEdit` a project file | **Denied**, with a reason telling Claude to explain the change instead |
| Write inside `.tutor/notes/` | Allowed (flashcard drafts, journal drafts, notes for you) |
| Write the plugin's own state files | Denied |
| Run a read-only command (`ls`, `cat`, `git diff`, `kubectl get`, `docker logs`, `curl`, tests…) | Allowed. Claude can diagnose so it can aim its hints. |
| Run a command that changes files or systems | **Denied** |

Commands treated as changes:

- Output redirection: `>` and `>>`, except into `/dev/null`.
- In-place edits: `sed -i`, `perl -i`.
- File commands: `rm`, `cp`, `mv`, `tee`, `touch`, `chmod` and similar.
- Git commands that change the repository: `commit`, `checkout`, `switch`, `reset`, `stash`,
  `push`…
- `kubectl apply`, `delete`, `scale` and `rollout restart`.
- `docker run`, `rm`, `build`, `compose up` and `compose down`.
- `helm install` and `helm upgrade`.
- PowerShell file cmdlets.
- Scripts that open files for writing.

So in tutor mode, **you** operate the system. Claude can look, but it can't touch.

If the guard itself crashes in a tutor-mode project, it denies the action rather than allowing
it. If Python can't be found at all, `run.sh` still denies actions in tutor-mode projects. In
other projects, neither case blocks anything.

### The hint ladder

| Level | Claude may give | Unlocks |
|---|---|---|
| 1 Nudge | One question pointing toward the right area | Immediately |
| 2 Locate | Where to look and what to look for | 10 min after `/tutor:start`, and 3 min after the previous hint |
| 3 Concept | The underlying concept, in general terms | 3 more minutes |
| 4 Parallel example | A worked example on a *different* problem | 3 more minutes |
| Solution | Full explanation and code in the chat (you still type the fix) | `/tutor:solution` once you reach level 3 (or `force`) |

If a level is still locked, `/tutor:stuck` doesn't raise it. Instead Claude helps you describe
what you've seen, what you expected and what experiment would tell the two apart. That alone
often solves the problem.

Every hint is logged with what you said you'd tried, so `/tutor:status` can show trends over
time: median time to solve, problems solved with no hints, and how often you needed the
solution.

### Drills

A drill is a realistic fault, injected where you can't see it, for you to debug from symptoms
alone. The flow:

```
you: /tutor:drill containers medium
  hook  checks the tree is clean, creates branch tutor/drill-<time>, mode = drill_setup
        (edits are allowed only on that branch, only in this mode)
  Claude launches a subagent with a brief:
        pick ONE realistic fault for the topic, change 1–3 files, no hint comments,
        no secrets touched, confirm the symptom is reproducible,
        write the answer key to .git/tutor/seal.json, run drill-seal,
        reply only "SEALED <id>"
  drill-seal  commits the fault as "Local changes", moves the key into .git/tutor/<id>.json,
              writes .tutor/drills/<id>/ticket.md, mode = drill_active, timer starts,
              edits locked again
  Claude shows you the ticket: symptoms and how to see them, nothing else

you: debug it, using /tutor:stuck as needed (the hints are calibrated against the key)

you: /tutor:done
  hook  mode = postmortem; the key stays hidden
  Claude asks for your postmortem: Symptom / Investigation / Root cause / Fix / Prevention
you: write it
  Claude runs drill-key, compares it with your postmortem, shows the fastest trail from symptom
  to cause, runs drill-close, makes flashcards, and tells you how to get back:
      git switch <your branch>
      git branch -D tutor/drill-<id>     (or keep it, to study later)
```

Some honest caveats:

- **Peeking is possible.** `git diff main`, `git log -p`, reading `.git/tutor/`, or expanding the
  setup subagent's output in the UI will all show you the answer. Comparing against a known-good
  version is a legitimate real-world technique (it's what `git bisect` does), so the ticket
  calls it *the last resort, not the first move*. The rest is on your honour.
- **Fault quality depends on the repo.** A `containers` drill needs Dockerfiles or compose
  files. If they don't exist, the subagent reports `NOT_POSSIBLE` and you pick another topic.
  As you containerize PersonalAIAssistant, more topics open up.

### Flashcards

Cards are built from *your* problems and drills, not generic trivia. They prefer "why" and "how
would you tell" questions. Scheduling uses a Leitner system with five boxes, reviewed after
1, 2, 4, 8 and 16 days. `again` sends a card back to box 1, `hard` keeps it in its box, and
`good` moves it up a box. Reviews are always recall from memory: you see the front and answer
before the back is shown.

### Where things are stored

| Path | What | Who writes it |
|---|---|---|
| `<project>/.tutor/state.json` | Mode, open problem, hint level, drill | The plugin only |
| `<project>/.tutor/config.json` | Your settings ([Configuration](#configuration)) | You |
| `<project>/.tutor/cards.json` | Flashcard deck | The plugin |
| `<project>/.tutor/journal.md` | Journal of problems, lessons and postmortems | The plugin, from Claude's drafts |
| `<project>/.tutor/log.jsonl` | Every event, used for the history in `/tutor:status` | The plugin |
| `<project>/.tutor/notes/` | Scratch space Claude may write to | Claude |
| `<project>/.tutor/drills/<id>/ticket.md` | Drill tickets | The plugin |
| `<project>/.git/tutor/<id>.json` | Drill answer keys, out of view and kept across branch switches | The plugin |

`.tutor/` is added to `.git/info/exclude`, which is your local ignore list, so it never shows
up in `git status` and survives branch switches. If you want to keep your journal and deck,
back up `.tutor/` or copy them somewhere tracked.

---

## Configuration

Edit `<project>/.tutor/config.json` (created by `/tutor:on`):

```json
{
  "min_struggle_minutes": 10,
  "hint_gap_minutes": 3,
  "solution_min_level": 3
}
```

To make practice harder, raise the timers. If you're short on time, lower them, but notice how
often you do that. `/tutor:status` keeps the history either way.

---

## A practice plan

Suggested for your four goals: containers, k3s/Kubernetes, system design, and debugging.

1. **Weeks 1–3, containers.** In PersonalAIAssistant: `/tutor:on`, then `/tutor:start
   containerize the hub services with a Dockerfile and compose.yaml`. Expect to hit services
   that only listen on loopback, `psutil` seeing the container instead of the host, startup
   order, and secrets in images. Use `/tutor:review` on each milestone.
2. **Every week, debugging.** Two drills a week, mixing topics (`app`, `config`, `networking`,
   then `containers` once you have Dockerfiles). Mixing topics is harder than doing one topic at
   a time, and that's the point. For your first session, investigate the two real incidents
   already in `audit/` (`*.corrupt-concurrent-writers`, `*.forked-by-two-writers`). Use
   `/tutor:start explain how these audit files got corrupted` and work it out from the files
   and `audit.py`.
3. **Weeks 4–8, k3s.** `/tutor:start deploy the hub to k3s on the Pi`. Probes, StatefulSet vs
   Deployment for the audit writers, ConfigMaps vs the web console writing `hosts.yaml`,
   NetworkPolicy for "only diagnostics may reach the broker". Then `kubernetes` drills.
4. **Throughout, system design.** Before reading the README's reasoning for a design choice,
   `/tutor:start write an ADR for why the console reads the CA's audit log instead of
   receiving a callback`. Write your answer first, then ask Claude to question it.
5. **Daily, 5 minutes:** `/tutor:cards`.

To stay ready for working without AI: spend the first 20 minutes of every drill with
documentation only (`--help`, `kubectl explain`, official docs) before your first
`/tutor:stuck`.

---

## Limits

- **The guard is a speed bump, not a sandbox.** It stops Claude from drifting into fixing
  things, which is the realistic failure mode. A determined workaround, such as a script that
  writes files in a way the patterns don't recognise, could get past it. The persona tells
  Claude not to try, and the guard catches the common forms.
- **Some read-only commands look like writes.** For example, `awk '$3 > 10'` contains a `>`.
  When that happens, Claude is told to rephrase the command or ask you to run it.
- **Claude can still show code in the chat.** The persona limits it to a few illustrative lines
  until you unlock the solution, but that's an instruction, not something code enforces. If it
  slips, say so. Feedback in the moment works.
- **Times are wall-clock.** If you walk away for an hour, the hints unlock. Use `/tutor:done`
  and `/tutor:start` around breaks if that bothers you.

---

## Troubleshooting

**Claude says there's "no `[tutor:…] result` block".** The expansion hook didn't run. Check:

1. Did you type the command in full, `/tutor:stuck` rather than `/stuck`?
2. `/plugin` shows `tutor` as enabled, with no errors listed for it.
3. Python works in Git Bash: open Git Bash and run `py -3 --version` or `python --version`.
4. Run the engine by hand from your project folder:
   `bash <path-to>/CodeTutor/tutor/scripts/run.sh status`.

**Every edit is blocked in a project where you didn't turn tutor mode on.** A parent folder
probably has a `.tutor/state.json`. The plugin applies to everything beneath the nearest one.
Run `/tutor:off` there, or delete that `.tutor/` folder.

**A legitimate read-only command was denied.** Tell Claude to rephrase it, or run it yourself.
If it keeps happening, the patterns live in `MUTATING_PATTERNS` in `scripts/tutor.py`. Changing
them is a good exercise.

**A drill was set up but the subagent described the fault.** Run `/tutor:drill abort` and start
another. The skill tells Claude to treat this as a leak.

**Windows without Git Bash.** The hooks call `bash`. Install Git for Windows, or change the hook
commands in `hooks/hooks.json` to call `py -3 "${CLAUDE_PLUGIN_ROOT}/scripts/tutor.py" ...`
directly.

---

## Developing the plugin

The tests drive the real hooks with the JSON Claude Code sends, against a throwaway git repo:

```bash
python -m pip install pytest
python -m pytest tests -q
```

To check the manifests:

```bash
claude plugin validate ./tutor
claude plugin validate .
```

Layout of this folder:

```
CodeTutor/
├── .claude-plugin/marketplace.json   makes this folder installable with /plugin marketplace add
├── tutor/                            the plugin itself (see "The pieces")
├── tests/test_tutor.py               70 end-to-end tests
└── README.md
```

Extending the plugin is a good tutor-mode project in its own right. Ideas: export the deck to
your `CodebaseQuiz` page; add a `/tutor:explain` that asks you to predict what a file does
before Claude explains it; track time-to-diagnosis per drill topic and chart it.
