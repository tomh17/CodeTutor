#!/usr/bin/env python3
"""Code Tutor engine: state, the hint ladder, the edit guard, drills and flashcards.

One file, standard library only, so it runs anywhere Claude Code runs.

Who may call what
-----------------
Everything that *changes how much help you get* (turning tutor mode on, raising
the hint level, unlocking a solution, starting a drill) happens inside the
``UserPromptExpansion`` hook. Claude Code fires that hook only when a person
types a slash command, so Claude cannot call it on its own behalf.

Claude may run a short list of bookkeeping subcommands through its shell
(``MODEL_COMMANDS``). The PreToolUse guard refuses any other use of this script.

Entry points
------------
  hook-session-start   SessionStart: remind Claude that tutor mode is on
  hook-prompt          UserPromptSubmit: one line of current state per turn
  hook-expansion       UserPromptExpansion: the learner's /tutor:* commands
  hook-pretool         PreToolUse: block edits while tutor mode is on
  <model command>      see MODEL_COMMANDS
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT = Path(__file__).resolve()
PLUGIN_ROOT = SCRIPT.parent.parent
TUTOR_DIR = ".tutor"
NOTES_DIR = "notes"

DEFAULT_CONFIG = {
    # Minutes of struggle on a problem before hints beyond level 1 unlock.
    "min_struggle_minutes": 10,
    # Minutes between successive hints, so each one gets a real try.
    "hint_gap_minutes": 3,
    # Hint level that must be reached before /tutor:solution works
    # without "force".
    "solution_min_level": 3,
}
MAX_HINT = 4
HINT_LEVELS = {
    1: "NUDGE: one question that points the learner at the right area. No file names, no answer.",
    2: "LOCATE: name where to look (a file, a log, a command to run) and what to look for. Still no answer.",
    3: "CONCEPT: explain the underlying concept in general terms, without applying it to their exact bug.",
    4: "PARALLEL EXAMPLE: a short worked example of the same idea on a *different* problem. They still map it to theirs.",
}
MODEL_COMMANDS = {
    "status", "cards-due", "card-grade", "card-add", "note",
    "drill-seal", "drill-key", "drill-close",
}
DRILL_TOPICS = ("app", "containers", "kubernetes", "networking", "config", "any")
BOX_DAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def now() -> float:
    return time.time()


def minutes(seconds: float) -> int:
    return int(seconds // 60)


def stamp(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now()).strftime("%Y-%m-%d %H:%M")


def run_git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def launcher() -> str:
    """The exact command Claude should use to reach this script."""
    return f'bash "{(SCRIPT.parent / "run.sh").as_posix()}"'


def same_or_inside(path: Path, parent: Path) -> bool:
    a = os.path.normcase(os.path.realpath(path))
    b = os.path.normcase(os.path.realpath(parent))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # different drives on Windows
        return False


# --------------------------------------------------------------------------
# Project, state and config
# --------------------------------------------------------------------------

def find_root(start: str | os.PathLike | None, *, require_state: bool = True) -> Path | None:
    """Walk up from ``start`` to the folder that holds .tutor/state.json.

    Without ``require_state``, fall back to the git root (or ``start``) so
    /tutor:on knows where to create the folder.
    """
    here = Path(start or os.getcwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / TUTOR_DIR / "state.json").is_file():
            return candidate
    if require_state:
        return None
    code, out = run_git(here, "rev-parse", "--show-toplevel")
    return Path(out) if code == 0 and out else here


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / TUTOR_DIR
        self.state_path = self.dir / "state.json"
        self.config_path = self.dir / "config.json"
        self.cards_path = self.dir / "cards.json"
        self.log_path = self.dir / "log.jsonl"
        self.journal_path = self.dir / "journal.md"
        self.notes = self.dir / NOTES_DIR
        self.state = self._load(self.state_path, {})
        self.config = {**DEFAULT_CONFIG, **self._load(self.config_path, {})}

    @staticmethod
    def _load(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def log(self, event: str, **fields) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": now(), "event": event, **fields}) + "\n")

    @property
    def active(self) -> bool:
        return bool(self.state.get("active"))

    @property
    def mode(self) -> str:
        return self.state.get("mode", "normal")

    @property
    def problem(self) -> dict | None:
        return self.state.get("problem")

    @property
    def drill(self) -> dict | None:
        return self.state.get("drill")

    def git_dir(self) -> Path | None:
        code, out = run_git(self.root, "rev-parse", "--absolute-git-dir")
        return Path(out) if code == 0 and out else None

    def key_dir(self) -> Path | None:
        gd = self.git_dir()
        return gd / "tutor" if gd else None

    def branch(self) -> str:
        code, out = run_git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        return out if code == 0 else ""


# --------------------------------------------------------------------------
# Text shown to Claude
# --------------------------------------------------------------------------

def problem_line(p: Project) -> str:
    prob = p.problem
    if not prob:
        return "No problem is open. The learner can open one with /tutor:start <goal>."
    elapsed = minutes(now() - prob["started"])
    line = (
        f'Open problem: "{prob["goal"]}" ({prob.get("kind", "build")}), '
        f"{elapsed} min so far, hint level {prob['level']}/{MAX_HINT}"
    )
    if prob.get("solution"):
        line += ", solution unlocked"
    nxt = next_unlock(p)
    if nxt is not None and prob["level"] < MAX_HINT:
        line += f", next hint level unlocks in {nxt} min" if nxt > 0 else ", next hint level is unlocked"
    return line + "."


def next_unlock(p: Project) -> int | None:
    prob = p.problem
    if not prob:
        return None
    if prob["level"] == 0:
        return 0
    t = now()
    need = max(
        prob["started"] + p.config["min_struggle_minutes"] * 60,
        (prob.get("last_hint") or 0) + p.config["hint_gap_minutes"] * 60,
    )
    return max(0, int(-(-(need - t) // 60)))  # ceiling minutes


def status_text(p: Project) -> str:
    lines = [
        f"Tutor mode is {'ON' if p.active else 'OFF'} for {p.root.as_posix()}.",
        f"Mode: {p.mode}.",
        problem_line(p),
    ]
    if p.drill:
        d = p.drill
        lines.append(
            f"Drill {d['id']} ({d['topic']}, {d['difficulty']}) on branch {d['branch']}; "
            f"the learner returns to {d['base_branch']} when it is over."
        )
    due = len(due_cards(p))
    lines.append(f"Flashcards due: {due}.")
    lines.append(stats_line(p))
    return "\n".join(lines)


def stats_line(p: Project) -> str:
    events = []
    try:
        for raw in p.log_path.read_text(encoding="utf-8").splitlines():
            events.append(json.loads(raw))
    except (OSError, ValueError):
        pass
    closed = [e for e in events if e.get("event") == "problem_closed"]
    if not closed:
        return "No problems finished yet."
    mins = sorted(e["minutes"] for e in closed)
    median = mins[len(mins) // 2]
    unaided = sum(1 for e in closed if e.get("max_level", 0) == 0 and not e.get("solution"))
    solutions = sum(1 for e in closed if e.get("solution"))
    drills = [e for e in closed if e.get("kind") == "drill"]
    return (
        f"History: {len(closed)} problems finished (median {median} min), "
        f"{unaided} with no hints, {solutions} needed the solution; "
        f"{len(drills)} drills."
    )


def rules_pointer() -> str:
    return (
        f"The tutoring rules the learner chose are in {(PLUGIN_ROOT / 'scripts' / 'persona.md').as_posix()} "
        "and apply for this whole session. "
        f"Bookkeeping commands Claude may run: {launcher()} <command>, "
        f"where <command> is one of: {', '.join(sorted(MODEL_COMMANDS))}."
    )


# --------------------------------------------------------------------------
# Hooks
# --------------------------------------------------------------------------

def emit_context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def read_hook_input() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def hook_session_start() -> int:
    data = read_hook_input()
    root = find_root(data.get("cwd"))
    if not root:
        return 0
    p = Project(root)
    if not p.active:
        return 0
    emit_context(
        "SessionStart",
        "Tutor mode is active in this project: the learner writes all of the code, and the "
        "tutor plugin blocks Claude's edits outside .tutor/notes/.\n"
        + rules_pointer() + "\n" + status_text(p),
    )
    return 0


def hook_prompt() -> int:
    data = read_hook_input()
    root = find_root(data.get("cwd"))
    if not root:
        return 0
    p = Project(root)
    if not p.active:
        return 0
    emit_context("UserPromptSubmit", f"[tutor] mode={p.mode}. {problem_line(p)}")
    return 0


# ----- the learner's commands ----------------------------------------------

def hook_expansion() -> int:
    data = read_hook_input()
    name = str(data.get("command_name", ""))
    if not name.startswith("tutor:"):
        return 0  # someone else's command: not our business
    command = name.split(":", 1)[1]
    args = str(data.get("command_args", "") or "").strip()
    handler = LEARNER_COMMANDS.get(command)
    if handler is None:
        return 0
    text = handler(data.get("cwd"), args)
    if text:
        emit_context("UserPromptExpansion", f"[tutor:{command} result]\n{text}")
    return 0


def cmd_on(cwd, args) -> str:
    root = find_root(cwd) or find_root(cwd, require_state=False)
    p = Project(root)
    p.state.setdefault("version", 1)
    p.state.setdefault("mode", "normal")
    p.state.setdefault("problem", None)
    p.state.setdefault("drill", None)
    p.state["active"] = True
    p.notes.mkdir(parents=True, exist_ok=True)
    if not p.config_path.exists():
        p.config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    excluded = _exclude_from_git(p)
    p.save()
    p.log("tutor_on")
    return (
        f"Tutor mode is now ON for {root.as_posix()}.\n"
        + ("The .tutor/ folder is excluded from git through .git/info/exclude.\n" if excluded else "")
        + rules_pointer() + "\n" + status_text(p)
    )


def _exclude_from_git(p: Project) -> bool:
    code, out = run_git(p.root, "rev-parse", "--git-path", "info/exclude")
    if code != 0 or not out:
        return False
    path = Path(out)
    if not path.is_absolute():
        path = p.root / path
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if f"{TUTOR_DIR}/" not in existing.split():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(("" if existing.endswith("\n") or not existing else "\n") + f"{TUTOR_DIR}/\n")
        return True
    except OSError:
        return False


def cmd_off(cwd, args) -> str:
    root = find_root(cwd)
    if not root:
        return "Tutor mode was not on here; nothing changed."
    p = Project(root)
    p.state["active"] = False
    p.save()
    p.log("tutor_off")
    warning = ""
    if p.drill:
        warning = (
            f"\nA drill is still recorded (branch {p.drill['branch']}). It resumes if tutor mode "
            "is turned back on; /tutor:drill abort discards it."
        )
    return "Tutor mode is now OFF. Claude edits files normally again in this project." + warning


def _require_active(cwd) -> Project | str:
    root = find_root(cwd)
    if not root:
        return "Tutor mode is not on in this project. The learner can turn it on with /tutor:on."
    p = Project(root)
    if not p.active:
        return "Tutor mode is OFF in this project. The learner can turn it on with /tutor:on."
    return p


def _open_problem(p: Project, goal: str, kind: str = "build") -> dict:
    p.state["problem"] = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "goal": goal or "(not stated)",
        "kind": kind,
        "started": now(),
        "level": 0,
        "last_hint": None,
        "hints": [],
        "solution": False,
    }
    return p.state["problem"]


def cmd_start(cwd, args) -> str:
    p = _require_active(cwd)
    if isinstance(p, str):
        return p
    if p.mode in ("drill_setup", "drill_active", "postmortem"):
        return "A drill is in progress. Finish it with /tutor:done (or /tutor:drill abort) first."
    previous = p.problem
    note = ""
    if previous:
        _close_problem(p, outcome="replaced")
        note = f'The previous problem "{previous["goal"]}" was closed as replaced.\n'
    _open_problem(p, args)
    p.save()
    p.log("problem_opened", goal=args)
    return note + (
        f'New problem opened at {stamp()}: "{args or "(not stated)"}". The struggle timer has started. '
        f"Hint level 1 is available at any time; level 2 and up unlock after "
        f"{p.config['min_struggle_minutes']} min."
    )


def cmd_stuck(cwd, args) -> str:
    p = _require_active(cwd)
    if isinstance(p, str):
        return p
    if p.mode == "drill_setup":
        return "The drill is still being prepared. Wait for the ticket before asking for hints."
    if p.mode == "postmortem":
        return "The drill is in its postmortem; hints are over. Continue the postmortem."
    created = ""
    if not p.problem:
        _open_problem(p, args or "(opened by /tutor:stuck)")
        created = "No problem was open, so one was opened now (the struggle timer starts now).\n"
    prob = p.problem
    tried = args or "(the learner did not say)"
    wait = next_unlock(p)
    if prob["level"] >= MAX_HINT:
        p.save()
        return created + (
            f"Hint level is already at the maximum ({MAX_HINT}). What the learner says they tried: {tried}\n"
            "No new hint level is available. Help them work through level-4 material again. The full "
            "answer is available only through /tutor:solution, typed by the learner."
        )
    if wait and wait > 0:
        p.save()
        p.log("hint_locked", level=prob["level"], wait=wait)
        return created + (
            f"Hint level stays at {prob['level']}; the next level unlocks in {wait} min. "
            f"What the learner says they tried: {tried}\n"
            "Respond at the current level only: help them say out loud what they have observed, "
            "what they expected instead, and what one experiment would tell those apart. "
            "Introduce nothing new."
        )
    prob["level"] += 1
    prob["last_hint"] = now()
    prob["hints"].append({"level": prob["level"], "at": now(), "tried": tried})
    p.save()
    p.log("hint", level=prob["level"], problem=prob["id"])
    text = created + (
        f"Hint level is now {prob['level']}/{MAX_HINT}: {HINT_LEVELS[prob['level']]}\n"
        f"What the learner says they tried: {tried}"
    )
    if p.mode == "drill_active":
        text += "\n" + _drill_key_for_hints(p)
    return text


def cmd_solution(cwd, args) -> str:
    p = _require_active(cwd)
    if isinstance(p, str):
        return p
    prob = p.problem
    if not prob:
        return "No problem is open, so there is no solution to unlock."
    need = p.config["solution_min_level"]
    forced = args.lower().startswith("force")
    if prob["level"] < need and not forced:
        return (
            f"Solution NOT unlocked: hint level is {prob['level']} and this project requires level {need} "
            "first. The learner can keep going with /tutor:stuck, or type /tutor:solution force to "
            "override (it is recorded in their history)."
        )
    prob["solution"] = True
    p.save()
    p.log("solution", problem=prob["id"], level=prob["level"], forced=forced)
    text = (
        "Solution UNLOCKED by the learner. Claude may now explain the full answer and show the code "
        "in the conversation. Edits stay blocked: the learner types the fix in themselves."
    )
    if p.mode == "drill_active":
        text += "\n" + _drill_key_for_hints(p)
    return text


def _close_problem(p: Project, outcome: str) -> dict | None:
    prob = p.problem
    if not prob:
        return None
    elapsed = minutes(now() - prob["started"])
    summary = {
        "problem": prob["id"],
        "goal": prob["goal"],
        "kind": prob.get("kind", "build"),
        "minutes": elapsed,
        "max_level": prob["level"],
        "hints": len(prob["hints"]),
        "solution": prob["solution"],
        "outcome": outcome,
    }
    p.log("problem_closed", **summary)
    p.state["problem"] = None
    return summary


def cmd_done(cwd, args) -> str:
    p = _require_active(cwd)
    if isinstance(p, str):
        return p
    if p.mode == "drill_setup":
        return "The drill is still being prepared; there is nothing to finish yet."
    if p.mode == "postmortem":
        return "Already in the drill postmortem. Continue it, then finish with drill-close."
    summary = _close_problem(p, outcome="done")
    if p.mode == "drill_active":
        p.state["mode"] = "postmortem"
        p.save()
        return (
            "Drill finished from the learner's side. Mode is now POSTMORTEM.\n"
            + (_summary_line(summary) if summary else "")
            + "\nThe answer key stays hidden until the learner has written their postmortem."
        )
    p.save()
    if not summary:
        return "No problem was open. Treat this as a reflection on whatever they just finished."
    return "Problem closed.\n" + _summary_line(summary)


def _summary_line(s: dict) -> str:
    return (
        f'"{s["goal"]}": {s["minutes"]} min, highest hint level {s["max_level"]}/{MAX_HINT}, '
        f"{s['hints']} hints, solution {'used' if s['solution'] else 'not used'}."
    )


def cmd_status(cwd, args) -> str:
    root = find_root(cwd)
    if not root:
        return "Tutor mode has never been turned on in this project."
    return status_text(Project(root))


# ----- drills ----------------------------------------------------------------

def cmd_drill(cwd, args) -> str:
    words = args.lower().split()
    if words[:1] == ["abort"]:
        return _drill_abort(cwd)
    p = _require_active(cwd)
    if isinstance(p, str):
        return p
    if p.mode != "normal" or p.drill:
        return f"A drill is already in progress (mode {p.mode}). Finish it with /tutor:done or /tutor:drill abort."
    if p.problem:
        return "A problem is open. Close it with /tutor:done before starting a drill."
    topic = next((w for w in words if w in DRILL_TOPICS), "any")
    difficulty = next((w for w in words if w in ("easy", "medium", "hard")), "medium")
    if not p.git_dir():
        return "Drills need a git repository (the fault goes on its own branch). This folder is not one."
    code, dirty = run_git(p.root, "status", "--porcelain")
    if code != 0:
        return f"Could not read git status: {dirty}"
    if dirty.strip():
        return (
            "The working tree has uncommitted changes. Drills start from a clean tree so the fault "
            "is the only difference. Commit or stash first:\n" + dirty
        )
    base = p.branch()
    code, base_commit = run_git(p.root, "rev-parse", "HEAD")
    if code != 0:
        return "This repository has no commits yet; make one before starting a drill."
    drill_id = datetime.now().strftime("%Y%m%d-%H%M")
    branch = f"tutor/drill-{drill_id}"
    code, out = run_git(p.root, "switch", "-c", branch)
    if code != 0:
        return f"Could not create branch {branch}: {out}"
    p.state["mode"] = "drill_setup"
    p.state["drill"] = {
        "id": drill_id,
        "branch": branch,
        "base_branch": base,
        "base_commit": base_commit,
        "topic": topic,
        "difficulty": difficulty,
        "created": now(),
    }
    p.save()
    p.log("drill_setup", id=drill_id, topic=topic, difficulty=difficulty)
    p.key_dir().mkdir(parents=True, exist_ok=True)
    seal_file = p.key_dir() / "seal.json"
    return (
        f"Drill setup authorised. Switched to new branch {branch} (from {base} @ {base_commit[:8]}).\n"
        f"Topic: {topic}. Difficulty: {difficulty}.\n"
        "While mode is drill_setup, edits are allowed on this branch only.\n"
        f"The fault-injection subagent writes its answer key as JSON to {seal_file.as_posix()} and then runs:\n"
        f"  {launcher()} drill-seal\n"
        "drill-seal commits the fault, hides the key, writes the ticket and locks edits again."
    )


def _drill_abort(cwd) -> str:
    root = find_root(cwd)
    if not root:
        return "No drill to abort."
    p = Project(root)
    d = p.drill
    if not d:
        return "No drill to abort."
    if p.problem and p.problem.get("kind") == "drill":
        _close_problem(p, outcome="aborted")
    kd = p.key_dir()
    if kd:
        for f in (kd / f"{d['id']}.json", kd / "seal.json"):
            try:
                f.unlink()
            except OSError:
                pass
    p.state["mode"] = "normal"
    p.state["drill"] = None
    p.save()
    p.log("drill_aborted", id=d["id"])
    return (
        f"Drill {d['id']} aborted. The learner should now run:\n"
        f"  git switch {d['base_branch']}\n  git branch -D {d['branch']}\n"
        "(Edits are blocked for Claude; the learner runs these.)"
    )


def _drill_key_for_hints(p: Project) -> str:
    key = _read_key(p)
    if not key:
        return "(The answer key could not be read.)"
    return (
        "ANSWER KEY, for calibrating hints only. It is not to be revealed beyond the current hint level "
        "unless the solution is unlocked:\n" + json.dumps(key, indent=2)
    )


def _read_key(p: Project) -> dict | None:
    d, kd = p.drill, p.key_dir()
    if not d or not kd:
        return None
    try:
        return json.loads((kd / f"{d['id']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


REQUIRED_SEAL_FIELDS = ("title", "ticket", "root_cause", "fix", "files", "how_to_reproduce")


def model_drill_seal(p: Project, argv: list[str]) -> int:
    d = p.drill
    if p.mode != "drill_setup" or not d:
        print("REFUSED: no drill is being set up.")
        return 1
    if p.branch() != d["branch"]:
        print(f"REFUSED: not on the drill branch {d['branch']}.")
        return 1
    kd = p.key_dir()
    seal = kd / "seal.json"
    try:
        key = json.loads(seal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"REFUSED: could not read {seal.as_posix()}: {exc}")
        return 1
    missing = [f for f in REQUIRED_SEAL_FIELDS if not key.get(f)]
    if missing:
        print(f"REFUSED: the key is missing {', '.join(missing)}.")
        return 1
    code, dirty = run_git(p.root, "status", "--porcelain")
    if not dirty.strip():
        print("REFUSED: there is no change to commit. Inject the fault first.")
        return 1
    run_git(p.root, "add", "-A")
    run_git(p.root, "reset", "-q", "--", TUTOR_DIR)  # in case .tutor/ is not excluded
    code, out = run_git(p.root, "commit", "-q", "-m", "Local changes")
    if code != 0 and ("user.email" in out or "identity" in out.lower()):
        code, out = run_git(
            p.root, "-c", "user.name=tutor", "-c", "user.email=tutor@localhost",
            "commit", "-q", "-m", "Local changes",
        )
    if code != 0:
        print(f"REFUSED: git commit failed: {out}")
        return 1
    key["topic"], key["difficulty"] = d["topic"], d["difficulty"]
    (kd / f"{d['id']}.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    seal.unlink()
    ticket_dir = p.dir / "drills" / d["id"]
    ticket_dir.mkdir(parents=True, exist_ok=True)
    ticket = ticket_dir / "ticket.md"
    ticket.write_text(
        f"# Drill {d['id']}: {key['title']}\n\n"
        f"Topic: {d['topic']} · Difficulty: {d['difficulty']} · Branch: `{d['branch']}`\n\n"
        f"## Ticket\n\n{key['ticket']}\n\n"
        f"## How to see it\n\n{key['how_to_reproduce']}\n\n"
        "## Rules\n\n"
        "- Diagnose from symptoms: logs, error messages, running the thing, reading code.\n"
        "- `git diff`/`git log` against the base branch is the last resort, not the first move.\n"
        "- `/tutor:stuck` when you are stuck. `/tutor:done` when you have found and fixed it.\n",
        encoding="utf-8",
    )
    p.state["mode"] = "drill_active"
    _open_problem(p, key["title"], kind="drill")
    p.save()
    p.log("drill_sealed", id=d["id"])
    print(f"SEALED drill {d['id']}. Ticket: {ticket.as_posix()}")
    return 0


def model_drill_key(p: Project, argv: list[str]) -> int:
    if p.mode != "postmortem":
        print("REFUSED: the answer key opens only during the postmortem (after the learner's /tutor:done).")
        return 1
    key = _read_key(p)
    print(json.dumps(key, indent=2) if key else "The key could not be read.")
    return 0


def model_drill_close(p: Project, argv: list[str]) -> int:
    if p.mode != "postmortem" or not p.drill:
        print("REFUSED: there is no drill postmortem to close.")
        return 1
    d = p.drill
    p.state["mode"] = "normal"
    p.state["drill"] = None
    p.save()
    p.log("drill_closed", id=d["id"])
    print(
        f"Drill {d['id']} closed. The learner can go back with:\n"
        f"  git switch {d['base_branch']}\n"
        f"and keep or delete the drill branch ({d['branch']}) for later study:\n"
        f"  git branch -D {d['branch']}"
    )
    return 0


# ----- flashcards and journal ------------------------------------------------

def load_cards(p: Project) -> list[dict]:
    return Project._load(p.cards_path, [])


def save_cards(p: Project, cards: list[dict]) -> None:
    p.cards_path.write_text(json.dumps(cards, indent=2), encoding="utf-8")


def due_cards(p: Project) -> list[dict]:
    today = date.today().isoformat()
    return [c for c in load_cards(p) if c.get("due", today) <= today]


def _notes_file(p: Project, name: str) -> Path | None:
    path = (p.root / name) if not os.path.isabs(name) else Path(name)
    if not same_or_inside(path, p.notes):
        print(f"REFUSED: input files must be inside {p.notes.as_posix()}.")
        return None
    if not path.is_file():
        print(f"REFUSED: {path.as_posix()} does not exist.")
        return None
    return path


def model_card_add(p: Project, argv: list[str]) -> int:
    if not argv:
        print("usage: card-add <file in .tutor/notes/ holding a JSON list of {front, back, topic}>")
        return 1
    path = _notes_file(p, argv[0])
    if not path:
        return 1
    try:
        new = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"REFUSED: not valid JSON: {exc}")
        return 1
    if isinstance(new, dict):
        new = [new]
    cards = load_cards(p)
    next_id = max((c["id"] for c in cards), default=0) + 1
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    added = 0
    for item in new:
        if not isinstance(item, dict) or not item.get("front") or not item.get("back"):
            continue
        cards.append({
            "id": next_id, "front": item["front"], "back": item["back"],
            "topic": item.get("topic", "general"), "box": 1, "due": tomorrow,
            "created": date.today().isoformat(), "reviews": 0,
        })
        next_id += 1
        added += 1
    save_cards(p, cards)
    path.unlink()
    p.log("cards_added", count=added)
    print(f"Added {added} card(s); first review {tomorrow}. Deck size: {len(cards)}.")
    return 0


def model_cards_due(p: Project, argv: list[str]) -> int:
    due = due_cards(p)
    limit = int(argv[0]) if argv and argv[0].isdigit() else 10
    if not due:
        upcoming = sorted(load_cards(p), key=lambda c: c["due"])[:1]
        print("No cards due." + (f" Next one is due {upcoming[0]['due']}." if upcoming else ""))
        return 0
    print(f"{len(due)} card(s) due; showing {min(limit, len(due))}. "
          "Show the learner only the FRONT; reveal the back after they answer.")
    for c in due[:limit]:
        print(json.dumps({"id": c["id"], "topic": c["topic"], "box": c["box"],
                          "front": c["front"], "back": c["back"]}))
    return 0


def model_card_grade(p: Project, argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("again", "hard", "good"):
        print("usage: card-grade <id> again|hard|good")
        return 1
    cards = load_cards(p)
    card = next((c for c in cards if str(c["id"]) == argv[0]), None)
    if not card:
        print(f"No card {argv[0]}.")
        return 1
    if argv[1] == "again":
        card["box"] = 1
    elif argv[1] == "good":
        card["box"] = min(5, card["box"] + 1)
    card["due"] = (date.today() + timedelta(days=BOX_DAYS[card["box"]])).isoformat()
    card["reviews"] = card.get("reviews", 0) + 1
    save_cards(p, cards)
    p.log("card_graded", id=card["id"], grade=argv[1], box=card["box"])
    print(f"Card {card['id']}: box {card['box']}, next review {card['due']}.")
    return 0


def model_note(p: Project, argv: list[str]) -> int:
    if not argv:
        print("usage: note <markdown file in .tutor/notes/>")
        return 1
    path = _notes_file(p, argv[0])
    if not path:
        return 1
    body = path.read_text(encoding="utf-8").strip()
    with p.journal_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {stamp()}\n\n{body}\n")
    path.unlink()
    print(f"Appended to {p.journal_path.as_posix()}.")
    return 0


def model_status(p: Project, argv: list[str]) -> int:
    print(status_text(p))
    return 0


MODEL_HANDLERS = {
    "status": model_status,
    "cards-due": model_cards_due,
    "card-grade": model_card_grade,
    "card-add": model_card_add,
    "note": model_note,
    "drill-seal": model_drill_seal,
    "drill-key": model_drill_key,
    "drill-close": model_drill_close,
}
assert set(MODEL_HANDLERS) == MODEL_COMMANDS

LEARNER_COMMANDS = {
    "on": cmd_on,
    "off": cmd_off,
    "start": cmd_start,
    "stuck": cmd_stuck,
    "solution": cmd_solution,
    "done": cmd_done,
    "drill": cmd_drill,
    "status": cmd_status,
}


# --------------------------------------------------------------------------
# The edit guard
# --------------------------------------------------------------------------

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}

# Shell commands that change files or repository state. A speed bump, not a
# sandbox: the point is that Claude cannot drift into fixing things for you.
MUTATING_PATTERNS = [
    (r"(?:^|[^<>&=\-0-9])>{1,2}(?!\s*&)(?!\s*/dev/null)(?!\s*\$null)(?!\s*nul\b)\s*[^\s&|;)]", "output redirection into a file"),
    (r"\b(?:sed|perl|ruby)\s+(?:-[a-zA-Z]*\s+)*-[a-zA-Z]*i", "in-place edit"),
    (r"(?:^|[;&|(]\s*|\s)(?:tee|cp|mv|rm|rmdir|touch|truncate|dd|ln|chmod|chown|patch)\b(?=\s|$)", "file-changing command"),
    (r"\bkubectl\s+(?:\S+\s+)*?(?:apply|create|delete|edit|patch|replace|scale|set|label|annotate|drain|cordon|uncordon|taint|rollout\s+(?:restart|undo)|run|expose|cp)\b", "kubectl command that changes the cluster"),
    (r"\b(?:docker|podman)(?:\s+compose|-compose)?\s+(?:\S+\s+)*?(?:run|rm|rmi|stop|kill|restart|start|build|up|down|create|exec|cp|prune|pull|push|tag)\b", "container command that changes state"),
    (r"\b(?:helm\s+(?:install|upgrade|uninstall|rollback)|systemctl\s+(?:start|stop|restart|enable|disable)|k3s\s+\S+)", "command that changes a running system"),
    (r"\bgit\s+(?:-[cC]\s+\S+\s+)*(?:commit|add|reset|restore|checkout|switch|stash|apply|am|rebase|merge|cherry-pick|revert|push|clean|rm|mv|branch\s+-[dDmM])\b", "git command that changes the repository"),
    (r"\b(?:Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Copy-Item|Move-Item|Rename-Item|Clear-Content)\b", "PowerShell file command"),
    (r"open\([^)]*['\"][wax]b?\+?['\"]|\.write_(?:text|bytes)\(|writeFile|fs\.write", "script that writes files"),
    (r"state\.json|\.git[/\\]tutor|hook-(?:expansion|prompt|pretool|session-start)", "tutor plugin internals"),
]


def deny(reason: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "[tutor] " + reason,
        }
    }))
    return 0


def _norm(path: str) -> str:
    return os.path.normcase(os.path.realpath(path.replace("\\", "/")))


def tutor_invocation(command: str) -> tuple[bool, str | None]:
    """Is this shell command a call to this plugin's script? If so, return its subcommand.

    Only one plain form is accepted: [bash|python] <our run.sh or tutor.py>
    <subcommand> [simple args]. Anything chained onto it is refused, so an
    allowed subcommand can't carry an unrelated command along with it.
    """
    ours = {_norm(str(SCRIPT)), _norm(str(SCRIPT.parent / "run.sh"))}
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.split()
    idx = next((i for i, tok in enumerate(parts) if _norm(tok) in ours), None)
    if idx is None:
        # Reaching the script some other way (a variable, a relative path) is refused.
        return "tutor.py" in command, None
    if re.search(r"[;&|`$<>(){}]", command):
        return True, None
    rest = parts[idx + 1:]
    if not rest or not all(re.fullmatch(r"[\w./\\:-]+", tok) for tok in rest):
        return True, None
    return True, rest[0]


def hook_pretool() -> int:
    data = read_hook_input()
    root = find_root(data.get("cwd"))
    if not root:
        return 0
    p = Project(root)
    if not p.active:
        return 0
    tool = data.get("tool_name", "")
    tin = data.get("tool_input") or {}

    in_setup = p.mode == "drill_setup" and p.drill and p.branch() == p.drill["branch"]

    if tool in EDIT_TOOLS:
        target = tin.get("file_path") or tin.get("notebook_path") or ""
        if not target:
            return deny("edit without a file path")
        path = Path(target)
        if not path.is_absolute():
            path = Path(data.get("cwd") or root) / path
        if same_or_inside(path, p.dir / "state.json") or same_or_inside(path, p.config_path) \
                or same_or_inside(path, p.cards_path) or same_or_inside(path, p.log_path):
            return deny("the tutor's own state files are written only by the plugin.")
        if same_or_inside(path, p.notes):
            return 0
        if in_setup:
            return 0
        return deny(
            "Tutor mode is on: the learner writes the code. Explain what to change and why, ask a "
            "question, or point at where to look, and let them make the edit. Notes for the learner "
            "may go in .tutor/notes/."
        )

    if tool in SHELL_TOOLS:
        command = str(tin.get("command", ""))
        is_tutor, sub = tutor_invocation(command)
        if is_tutor:
            if sub in MODEL_COMMANDS:
                return 0
            return deny(
                "only these tutor commands may be run, in the plain form "
                f"{launcher()} <command> [args]: {', '.join(sorted(MODEL_COMMANDS))}."
            )
        if in_setup:
            if re.search(r"\bgit\s+push\b", command):
                return deny("drills never push.")
            return 0
        for pattern, label in MUTATING_PATTERNS:
            if re.search(pattern, command):
                return deny(
                    f"this command looks like it changes files ({label}). In tutor mode, Claude reads "
                    "and runs things to diagnose, but the learner makes changes. Suggest the command "
                    "and let them run it. If this command only reads, rephrase it without the "
                    "pattern above."
                )
        return 0
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

HOOKS = {
    "hook-session-start": hook_session_start,
    "hook-prompt": hook_prompt,
    "hook-expansion": hook_expansion,
    "hook-pretool": hook_pretool,
}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    sub, rest = argv[0], argv[1:]
    if sub in HOOKS:
        try:
            return HOOKS[sub]()
        except Exception as exc:  # a broken guard fails closed, but only where tutor mode is on
            if sub == "hook-pretool" and find_root(os.getcwd()):
                return deny(f"the tutor guard failed ({exc!r}), so the action was refused to be safe.")
            print(f"[tutor] hook error: {exc!r}", file=sys.stderr)
            return 0
    if sub in MODEL_HANDLERS:
        root = find_root(os.getcwd())
        if not root:
            print("Tutor mode is not on in this project.")
            return 1
        return MODEL_HANDLERS[sub](Project(root), rest)
    print(f"Unknown command {sub!r}. Claude may run: {', '.join(sorted(MODEL_COMMANDS))}.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
