#!/usr/bin/env python
"""Two rules from CLAUDE.md, enforced by code instead of by prose.

A rule that only exists as a paragraph is a rule that gets followed until the
session is long and the paragraph is far away. These two both cost this project
real work once:

1. `server/models/generated/` and `extension/src/types/` are codegen output.
   The source of truth is `schema/*.schema.json` plus `pnpm codegen`, and a
   hand-edit there is silently reverted by the next drift check -- or worse,
   survives and makes the schema and the code disagree.

2. `git checkout -- <path>` destroyed an uncommitted rebuild of `run.py`. There
   is no reflog entry for a working-tree discard and nothing to recover from.
   `git restore <path>` is the same hazard under a newer name.

Reads the PreToolUse payload on stdin. Exit 2 blocks the call and shows stderr
to the model; exit 0 allows it.

**Fails open.** If the payload cannot be parsed this exits 0 rather than
blocking every edit in the session. These guards prevent mistakes, not attacks,
and a guard that bricks the session when it breaks is worse than no guard.
"""

from __future__ import annotations

import json
import re
import sys

# Matched against the path with separators normalised to "/", so one pattern
# covers the Windows and POSIX spellings of the same file.
GENERATED = (
    "server/models/generated/",
    "extension/src/types/",
)

# Two narrowings, and both are what keeps this usable rather than annoying.
#
# The invocation must sit in COMMAND POSITION -- at the start, or after a
# separator. Matching anywhere blocks `echo "git checkout -- ."`, which only
# mentions the command, and a guard with false positives is a guard that gets
# switched off. `cd /d/repo && git checkout -- .` still matches, because it
# really does run.
#
# `--` must be followed by whitespace: that is the form taking a pathspec and
# discarding the working tree. `git checkout -b`, `git checkout main` and
# `git checkout --force` are untouched, as is `git restore --staged`, which
# unstages and destroys nothing.
DESTRUCTIVE = re.compile(
    r"(?:^|[;&|(]|\n)\s*"
    r"git\s+(?:checkout\s+--\s|restore\s+(?!--staged\b|--source\b))",
)


def blocked(payload: dict) -> str | None:
    """The reason this call is refused, or None to allow it."""
    tool = payload.get("tool_name", "")
    args = payload.get("tool_input") or {}

    if tool in {"Edit", "Write", "NotebookEdit"}:
        path = str(args.get("file_path") or "").replace("\\", "/")
        for directory in GENERATED:
            if directory in path:
                return (
                    f"{directory} is codegen output and is never hand-edited.\n"
                    "Edit the matching schema/*.schema.json, then run `pnpm codegen`.\n"
                    "scripts/check.sh regenerates and diffs, so a hand-edit here "
                    "reads as schema drift on a clean machine."
                )

    if tool == "Bash":
        command = str(args.get("command") or "")
        if DESTRUCTIVE.search(command):
            return (
                "Discarding working-tree changes is blocked in this repo.\n"
                "It cost a rebuild of run.py once: there is no reflog entry for a "
                "working-tree discard and nothing to recover from, and large parts "
                "of a milestone sit uncommitted here for a long time.\n"
                "Commit first (`git add -A && git commit`), or stash "
                "(`git stash push -- <path>`), which is reversible."
            )

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    reason = blocked(payload)
    if reason is None:
        return 0

    print(f"BLOCKED by .claude/hooks/guard.py\n\n{reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
