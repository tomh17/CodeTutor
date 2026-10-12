"""End-to-end tests for the Code Tutor plugin.

Every test drives the real entry point (scripts/run.sh) with the same JSON
Claude Code sends to hooks, against a throwaway git repository. Nothing here
needs Claude Code itself.

    python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "tutor"
RUN = PLUGIN / "scripts" / "run.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def run(args, cwd, stdin=None, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(
        [BASH, str(RUN), *args], cwd=cwd, input=stdin, capture_output=True,
        text=True, env=env, timeout=60,
    )
    return proc


def hook(event_cmd, cwd, payload):
    payload = {"cwd": str(cwd), "session_id": "test", **payload}
    proc = run([event_cmd], cwd, json.dumps(payload))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def learner(cwd, command, args=""):
    """Simulate the learner typing /tutor:<command> <args>."""
    out = hook("hook-expansion", cwd, {
        "hook_event_name": "UserPromptExpansion",
        "expansion_type": "slash_command",
        "command_name": f"tutor:{command}",
        "command_args": args,
        "prompt": f"/tutor:{command} {args}".strip(),
    })
    return out["hookSpecificOutput"]["additionalContext"] if out else ""


def pretool(cwd, tool, **tool_input):
    out = hook("hook-pretool", cwd, {
        "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
    })
    if out is None:
        return "allow"
    return out["hookSpecificOutput"]["permissionDecision"]


def bash_cmd(cwd, command):
    return pretool(cwd, "Bash", command=command)


def model(cwd, *args):
    """Claude running a bookkeeping command through its shell."""
    return run(list(args), cwd)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def state(repo):
    return json.loads((repo / ".tutor" / "state.json").read_text())


def set_state(repo, mutate):
    s = state(repo)
    mutate(s)
    (repo / ".tutor" / "state.json").write_text(json.dumps(s))


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "project"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "learner@example.com")
    git(r, "config", "user.name", "Learner")
    (r / "app.py").write_text("PORT = 8080\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def tutor_on(repo):
    learner(repo, "on")
    return repo


# --------------------------------------------------------------------------
# Off by default
# --------------------------------------------------------------------------

def test_projects_without_tutor_mode_are_untouched(repo):
    assert pretool(repo, "Edit", file_path=str(repo / "app.py"), old_string="a", new_string="b") == "allow"
    assert bash_cmd(repo, "rm -rf build") == "allow"
    assert hook("hook-prompt", repo, {"hook_event_name": "UserPromptSubmit", "prompt": "hi"}) is None
    assert hook("hook-session-start", repo, {"hook_event_name": "SessionStart", "source": "startup"}) is None


def test_other_commands_do_not_trigger_the_tutor(repo):
    out = hook("hook-expansion", repo, {
        "hook_event_name": "UserPromptExpansion", "command_name": "deploy", "command_args": "",
    })
    assert out is None
    assert not (repo / ".tutor").exists()


# --------------------------------------------------------------------------
# Turning it on and off
# --------------------------------------------------------------------------

def test_on_creates_state_and_excludes_folder_from_git(repo):
    text = learner(repo, "on")
    assert "Tutor mode is now ON" in text
    assert "persona.md" in text
    assert state(repo)["active"] is True
    assert ".tutor/" in (repo / ".git" / "info" / "exclude").read_text()
    assert git(repo, "status", "--porcelain").strip() == ""


def test_off_restores_normal_editing(tutor_on):
    learner(tutor_on, "off")
    assert pretool(tutor_on, "Edit", file_path=str(tutor_on / "app.py")) == "allow"


def test_session_start_and_prompt_context_when_on(tutor_on):
    ctx = hook("hook-session-start", tutor_on, {"hook_event_name": "SessionStart", "source": "startup"})
    text = ctx["hookSpecificOutput"]["additionalContext"]
    assert "Tutor mode is active" in text and "run.sh" in text
    ctx = hook("hook-prompt", tutor_on, {"hook_event_name": "UserPromptSubmit", "prompt": "hello"})
    assert ctx["hookSpecificOutput"]["additionalContext"].startswith("[tutor] mode=normal")


def test_subdirectory_cwd_finds_the_project(tutor_on):
    sub = tutor_on / "pkg"
    sub.mkdir()
    assert pretool(sub, "Write", file_path=str(sub / "x.py"), content="") == "deny"


# --------------------------------------------------------------------------
# The edit guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_source_edits_are_blocked(tutor_on, tool):
    assert pretool(tutor_on, tool, file_path=str(tutor_on / "app.py")) == "deny"


def test_relative_paths_are_resolved(tutor_on):
    assert pretool(tutor_on, "Write", file_path="app.py") == "deny"
    assert pretool(tutor_on, "Write", file_path=".tutor/notes/x.md") == "allow"


def test_notes_are_writable_but_state_is_not(tutor_on):
    assert pretool(tutor_on, "Write", file_path=str(tutor_on / ".tutor" / "notes" / "x.md")) == "allow"
    for name in ("state.json", "config.json", "cards.json", "log.jsonl"):
        assert pretool(tutor_on, "Write", file_path=str(tutor_on / ".tutor" / name)) == "deny"


def test_notebook_edits_are_blocked(tutor_on):
    assert pretool(tutor_on, "NotebookEdit", notebook_path=str(tutor_on / "a.ipynb")) == "deny"


READ_ONLY = [
    "ls -la",
    "git status",
    "git diff main",
    "git log --oneline -5",
    "cat app.py 2>&1 | grep PORT",
    "python -m pytest -q > /dev/null",
    "docker ps",
    "docker compose logs gateway",
    "kubectl get pods -A",
    "kubectl describe pod web-0",
    "kubectl logs deploy/web --previous",
    "curl -s http://localhost:8080/healthz",
    "pip install requests",
    "grep -rn 'port' config/",
]

MUTATING = [
    "echo hi > app.py",
    "echo hi >> notes.txt",
    "sed -i 's/8080/9090/' app.py",
    "rm -rf build",
    "cp a b",
    "mv a b",
    "tee app.py < x",
    "git commit -am fix",
    "git checkout -- app.py",
    "git switch main",
    "git stash",
    "kubectl apply -f deploy.yaml",
    "kubectl -n lab delete pod web-0",
    "kubectl rollout restart deploy/web",
    "docker compose up -d",
    "docker run --rm alpine",
    "docker-compose down",
    "helm upgrade web ./chart",
    "python -c \"open('app.py','w').write('x')\"",
    "Set-Content app.py 'x'",
    "cat .tutor/state.json",
]


@pytest.mark.parametrize("command", READ_ONLY)
def test_read_only_commands_are_allowed(tutor_on, command):
    assert bash_cmd(tutor_on, command) == "allow"


@pytest.mark.parametrize("command", MUTATING)
def test_mutating_commands_are_blocked(tutor_on, command):
    assert bash_cmd(tutor_on, command) == "deny"


def test_powershell_tool_is_guarded_too(tutor_on):
    assert pretool(tutor_on, "PowerShell", command="Remove-Item app.py") == "deny"


def test_bookkeeping_commands_are_allowed_but_learner_switches_are_not(tutor_on):
    prefix = f'bash "{RUN.as_posix()}"'
    assert bash_cmd(tutor_on, f"{prefix} status") == "allow"
    assert bash_cmd(tutor_on, f"{prefix} card-add .tutor/notes/cards.json") == "allow"
    assert bash_cmd(tutor_on, f'python "{(PLUGIN / "scripts" / "tutor.py").as_posix()}" cards-due') == "allow"
    # The learner's switches live behind the expansion hook, not the CLI.
    assert bash_cmd(tutor_on, f"{prefix} hook-expansion") == "deny"
    assert bash_cmd(tutor_on, f"echo '{{}}' | {prefix} hook-expansion") == "deny"
    # An allowed subcommand can't carry something else along.
    assert bash_cmd(tutor_on, f"{prefix} status; rm -rf x") == "deny"
    assert bash_cmd(tutor_on, f"{prefix} status && echo hi > app.py") == "deny"


def test_a_project_script_named_run_sh_is_not_mistaken_for_the_plugin(tutor_on):
    assert bash_cmd(tutor_on, "bash scripts/run.sh --help") == "allow"


def test_model_cannot_run_learner_commands_directly(tutor_on):
    proc = model(tutor_on, "stuck")
    assert proc.returncode == 1 and "Unknown command" in proc.stdout


# --------------------------------------------------------------------------
# The hint ladder
# --------------------------------------------------------------------------

def test_first_hint_is_immediate_then_locked(tutor_on):
    learner(tutor_on, "start", "add a health check")
    text = learner(tutor_on, "stuck", "read the docs")
    assert "Hint level is now 1/4" in text and "NUDGE" in text
    text = learner(tutor_on, "stuck")
    assert "stays at 1" in text and "unlocks in" in text
    assert state(tutor_on)["problem"]["level"] == 1


def test_hints_unlock_with_time(tutor_on):
    learner(tutor_on, "start", "x")
    learner(tutor_on, "stuck")

    def age(s):
        s["problem"]["started"] -= 11 * 60
        s["problem"]["last_hint"] -= 4 * 60
    set_state(tutor_on, age)
    text = learner(tutor_on, "stuck")
    assert "Hint level is now 2/4" in text and "LOCATE" in text
    assert "stays at 2" in learner(tutor_on, "stuck")  # the gap applies again


def test_ladder_tops_out_at_four(tutor_on):
    learner(tutor_on, "start", "x")
    set_state(tutor_on, lambda s: s["problem"].update(level=4))
    assert "already at the maximum" in learner(tutor_on, "stuck")


def test_stuck_without_a_problem_opens_one(tutor_on):
    text = learner(tutor_on, "stuck", "nothing works")
    assert "No problem was open" in text
    assert state(tutor_on)["problem"]["level"] == 1


def test_solution_requires_level_three_or_force(tutor_on):
    learner(tutor_on, "start", "x")
    assert "NOT unlocked" in learner(tutor_on, "solution")
    assert "UNLOCKED" in learner(tutor_on, "solution", "force")
    assert state(tutor_on)["problem"]["solution"] is True


def test_solution_at_level_three(tutor_on):
    learner(tutor_on, "start", "x")
    set_state(tutor_on, lambda s: s["problem"].update(level=3))
    assert "UNLOCKED" in learner(tutor_on, "solution")


def test_config_changes_the_timer(tutor_on):
    (tutor_on / ".tutor" / "config.json").write_text(json.dumps({"min_struggle_minutes": 0, "hint_gap_minutes": 0}))
    learner(tutor_on, "start", "x")
    learner(tutor_on, "stuck")
    assert "Hint level is now 2/4" in learner(tutor_on, "stuck")


def test_done_records_history(tutor_on):
    learner(tutor_on, "start", "build the thing")
    learner(tutor_on, "stuck")
    text = learner(tutor_on, "done")
    assert "Problem closed" in text and "highest hint level 1/4" in text
    assert state(tutor_on)["problem"] is None
    assert "1 problems finished" in learner(tutor_on, "status")


def test_start_replaces_an_open_problem(tutor_on):
    learner(tutor_on, "start", "first")
    text = learner(tutor_on, "start", "second")
    assert '"first" was closed' in text
    assert state(tutor_on)["problem"]["goal"] == "second"


# --------------------------------------------------------------------------
# Drills
# --------------------------------------------------------------------------

SEAL = {
    "title": "Health check fails after deploy",
    "ticket": "Since this morning the health check reports the app as down.",
    "how_to_reproduce": "python app.py",
    "root_cause": "PORT changed to 8081 while the probe still uses 8080",
    "fix": "Set PORT back to 8080",
    "files": ["app.py"],
    "hints": ["What port is the probe using?", "Compare app.py and the probe", "Ports must agree", "Example"],
    "concepts": ["configuration drift"],
}


def test_drill_refuses_a_dirty_tree(tutor_on):
    (tutor_on / "app.py").write_text("PORT = 1\n")
    assert "uncommitted changes" in learner(tutor_on, "drill", "config easy")
    assert state(tutor_on)["mode"] == "normal"


def test_full_drill_lifecycle(tutor_on):
    text = learner(tutor_on, "drill", "config easy")
    assert "Drill setup authorised" in text
    s = state(tutor_on)
    branch = s["drill"]["branch"]
    assert s["mode"] == "drill_setup" and s["drill"]["topic"] == "config"
    assert git(tutor_on, "rev-parse", "--abbrev-ref", "HEAD").strip() == branch

    # The setup subagent may edit on the drill branch...
    assert pretool(tutor_on, "Edit", file_path=str(tutor_on / "app.py")) == "allow"
    assert bash_cmd(tutor_on, "git push origin HEAD") == "deny"
    (tutor_on / "app.py").write_text("PORT = 8081\n")
    seal = tutor_on / ".git" / "tutor" / "seal.json"
    assert pretool(tutor_on, "Write", file_path=str(seal)) == "allow"
    seal.write_text(json.dumps(SEAL))

    # ...and hints are not available yet.
    assert "still being prepared" in learner(tutor_on, "stuck")

    proc = model(tutor_on, "drill-seal")
    assert proc.returncode == 0, proc.stdout
    assert "SEALED" in proc.stdout
    s = state(tutor_on)
    assert s["mode"] == "drill_active" and s["problem"]["kind"] == "drill"
    assert not seal.exists()
    assert git(tutor_on, "status", "--porcelain").strip() == ""
    assert "Local changes" in git(tutor_on, "log", "-1", "--format=%s")
    ticket = (tutor_on / ".tutor" / "drills" / s["drill"]["id"] / "ticket.md").read_text()
    assert "health check" in ticket.lower() and "8081" not in ticket

    # Sealed: edits are locked again, and the key stays hidden from direct reads.
    assert pretool(tutor_on, "Edit", file_path=str(tutor_on / "app.py")) == "deny"
    assert model(tutor_on, "drill-key").returncode == 1
    assert "ANSWER KEY" in learner(tutor_on, "stuck")

    # The learner finishes; the postmortem opens the key.
    text = learner(tutor_on, "done")
    assert "POSTMORTEM" in text and "8081" not in text
    assert "hints are over" in learner(tutor_on, "stuck")
    key = model(tutor_on, "drill-key")
    assert key.returncode == 0 and "8081" in key.stdout
    closed = model(tutor_on, "drill-close")
    assert closed.returncode == 0 and "git switch main" in closed.stdout
    assert state(tutor_on)["mode"] == "normal" and state(tutor_on)["drill"] is None


def test_drill_seal_requires_a_change_and_a_complete_key(tutor_on):
    learner(tutor_on, "drill", "app")
    seal = tutor_on / ".git" / "tutor" / "seal.json"
    seal.write_text(json.dumps({"title": "x"}))
    assert "missing" in model(tutor_on, "drill-seal").stdout
    seal.write_text(json.dumps(SEAL))
    assert "no change to commit" in model(tutor_on, "drill-seal").stdout


def test_drill_seal_is_refused_outside_setup(tutor_on):
    assert model(tutor_on, "drill-seal").returncode == 1


def test_drill_abort(tutor_on):
    learner(tutor_on, "drill", "any")
    text = learner(tutor_on, "drill", "abort")
    assert "aborted" in text and "git switch main" in text
    assert state(tutor_on)["mode"] == "normal"


def test_drill_blocked_while_a_problem_is_open(tutor_on):
    learner(tutor_on, "start", "x")
    assert "A problem is open" in learner(tutor_on, "drill")


# --------------------------------------------------------------------------
# Flashcards and journal
# --------------------------------------------------------------------------

def test_cards_lifecycle(tutor_on):
    notes = tutor_on / ".tutor" / "notes"
    (notes / "cards-incoming.json").write_text(json.dumps([
        {"front": "Why can't two processes share a threading.Lock?", "back": "It lives in one process's memory.", "topic": "concurrency"},
        {"front": "missing back"},
    ]))
    proc = model(tutor_on, "card-add", ".tutor/notes/cards-incoming.json")
    assert "Added 1 card" in proc.stdout
    assert not (notes / "cards-incoming.json").exists()
    assert "No cards due" in model(tutor_on, "cards-due").stdout

    cards_path = tutor_on / ".tutor" / "cards.json"
    cards = json.loads(cards_path.read_text())
    cards[0]["due"] = date.today().isoformat()
    cards_path.write_text(json.dumps(cards))
    assert "threading.Lock" in model(tutor_on, "cards-due").stdout

    assert "box 2" in model(tutor_on, "card-grade", "1", "good").stdout
    assert json.loads(cards_path.read_text())[0]["due"] == (date.today() + timedelta(days=2)).isoformat()
    assert "box 1" in model(tutor_on, "card-grade", "1", "again").stdout


def test_card_input_must_come_from_notes(tutor_on):
    (tutor_on / "cards.json").write_text("[]")
    assert model(tutor_on, "card-add", "cards.json").returncode == 1


def test_journal(tutor_on):
    (tutor_on / ".tutor" / "notes" / "journal-entry.md").write_text("Learned about probes.")
    assert model(tutor_on, "note", ".tutor/notes/journal-entry.md").returncode == 0
    assert "Learned about probes." in (tutor_on / ".tutor" / "journal.md").read_text()


# --------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------

def test_guard_fails_closed_without_python(tutor_on, tmp_path):
    """With no Python on PATH, the guard denies instead of silently allowing."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in ("dirname", "printf"):
        target = shutil.which(tool)
        if target:
            os.symlink(target, fake_bin / tool)
    proc = subprocess.run(
        [BASH, str(RUN), "hook-pretool"], cwd=tutor_on, input="{}", capture_output=True,
        text=True, env={"PATH": str(fake_bin)}, timeout=30,
    )
    assert '"deny"' in proc.stdout
