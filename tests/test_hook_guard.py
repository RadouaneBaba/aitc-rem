"""The two CLAUDE.md rules that are enforced by code have to actually fire.

A guard that silently allows what it was written to block is worse than no
guard, because it is trusted. Both halves are tested here: the calls that must
be refused, and -- the half that matters more -- the calls that must NOT be,
since a guard with false positives gets switched off.

`.claude/hooks/guard.py` runs as a PreToolUse hook, so it is exercised the way
Claude Code invokes it: a JSON payload on stdin, a decision as an exit code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard.py"

BLOCK = 2
ALLOW = 0

WINDOWS_ROOT = "D:\\files\\Projects\\aitc-rem\\"


def run(payload: object) -> subprocess.CompletedProcess[str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=raw,
        capture_output=True,
        text=True,
        check=False,
    )


def edit(file_path: str, tool: str = "Edit") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": file_path}}


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


#: Codegen output. Hand-editing it makes the schema and the code disagree, and
#: `check.sh` regenerates and diffs, so the edit reads as schema drift later.
@pytest.mark.parametrize(
    "path",
    [
        "server/models/generated/trace_schema.py",
        "extension/src/types/ir.ts",
        WINDOWS_ROOT + "server\\models\\generated\\trace_schema.py",
        WINDOWS_ROOT + "extension\\src\\types\\trace.ts",
    ],
)
def test_generated_code_may_not_be_hand_edited(path: str) -> None:
    assert run(edit(path)).returncode == BLOCK


#: The rule is about the PATH, never about the CONTENT. Documentation that
#: quotes the rule must not trip it -- CLAUDE.md itself names both directories.
@pytest.mark.parametrize(
    "path",
    [
        "server/pipeline/bind.py",
        "schema/trace.schema.json",
        "server/models/__init__.py",
        WINDOWS_ROOT + "server\\pipeline\\draft.py",
    ],
)
def test_ordinary_source_files_are_untouched(path: str) -> None:
    assert run(edit(path)).returncode == ALLOW


def test_a_document_quoting_the_rule_is_not_blocked() -> None:
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "CLAUDE.md",
            "content": "Never hand-edit server/models/generated/ or extension/src/types/.",
        },
    }
    assert run(payload).returncode == ALLOW


#: `git checkout -- <path>` has no reflog entry and no recovery. It cost a
#: rebuild of run.py once, and large parts of a milestone sit uncommitted here.
@pytest.mark.parametrize(
    "command",
    [
        "git checkout -- .",
        "git checkout -- server/pipeline/run.py",
        "git restore server/pipeline/run.py",
        "cd /d/repo && git checkout -- .",
    ],
)
def test_discarding_working_tree_changes_is_blocked(command: str) -> None:
    assert run(bash(command)).returncode == BLOCK


#: The negative case, and the one that decides whether the guard is usable:
#: every other `git checkout` is ordinary work and must go through untouched.
@pytest.mark.parametrize(
    "command",
    [
        "git checkout -b cleanup",
        "git checkout main",
        "git checkout --force",
        "git restore --staged server/pipeline/run.py",
        "git status",
        "git stash push -- server/pipeline/run.py",
        "echo 'git checkout -- .' >> notes.md",
    ],
)
def test_ordinary_git_work_is_not_blocked(command: str) -> None:
    result = run(bash(command))
    assert result.returncode == ALLOW, result.stderr


def test_a_block_explains_itself() -> None:
    """The message is the whole value of blocking. Refusing with no reason
    just gets the guard disabled."""
    result = run(bash("git checkout -- ."))
    assert result.returncode == BLOCK
    assert "stash" in result.stderr
    assert "guard.py" in result.stderr


@pytest.mark.parametrize("payload", ["not json at all", "", "[]", "null"])
def test_an_unreadable_payload_fails_open(payload: str) -> None:
    """These guards prevent mistakes, not attacks. One that bricks every edit
    in the session when its input surprises it is worse than none."""
    assert run(payload).returncode == ALLOW
