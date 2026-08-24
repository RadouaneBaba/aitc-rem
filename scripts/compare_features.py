#!/usr/bin/env python
"""Read the SAME recording's feature file across A0 / A1 / A2, side by side.

    `runs/` accumulates a directory per run, and after a few ablations there
    are more feature files than anyone will open. Almost none of them are worth
    reading on their own: a feature file is only informative next to the one
    the other configuration produced from the SAME recording.

That is the whole reason this exists. "Has the output got better" is not a
question you can answer by reading one file, because you have nothing to
compare it against and no memory of what the previous version said. Read across
the configurations instead -- same recording, same model, one architectural
difference -- and the difference is the answer.

    python scripts/compare_features.py            # list what there is to read
    python scripts/compare_features.py checkout   # read that one, all configs

The name is matched loosely against the recording's own `objective`, so
`checkout`, `approval` or a recording id all work.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"


def latest_ablation() -> dict:
    path = RUNS / "ablation.json"
    if not path.exists():
        sys.exit(
            "No runs/ablation.json. Produce one with:\n"
            "  .venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json --offline"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def objective_of(run_path: Path) -> str:
    """What the tester said they were checking, which is how a human names a run.

    Recording ids are not memorable and were never meant to be. The objective
    is the one string that tells you which session this was.
    """
    ir = run_path / "ir.json"
    if not ir.exists():
        return ""
    document = json.loads(ir.read_text(encoding="utf-8"))
    for case in document.get("testCases", []):
        if case.get("objective"):
            return case["objective"]
        if case.get("title"):
            return case["title"]
    return ""


def feature_text(run_path: Path) -> str:
    files = sorted(run_path.glob("*.feature"))
    if not files:
        return "(no feature file -- the gate hard-failed, or nothing was rendered)"
    return "\n\n".join(f.read_text(encoding="utf-8") for f in files)


def main() -> int:
    report = latest_ablation()
    by_recording: dict[str, dict[str, Path]] = {}
    for entry in report["runs"]:
        by_recording.setdefault(entry["recordingId"], {})[entry["config"]] = Path(
            entry["runPath"]
        )

    labelled = {rec: objective_of(next(iter(paths.values()))) for rec, paths in by_recording.items()}

    if len(sys.argv) < 2:
        print("Recordings in the latest ablation:\n")
        for rec, objective in labelled.items():
            print(f"  {rec}\n      {objective or '(no objective stated)'}\n")
        print("Read one with:  python scripts/compare_features.py <word from its objective>")
        return 0

    needle = " ".join(sys.argv[1:]).casefold()
    matches = [
        rec
        for rec, objective in labelled.items()
        if needle in objective.casefold() or needle in rec.casefold()
    ]
    if not matches:
        print(f"Nothing matches {needle!r}. Run with no arguments to see what there is.")
        return 1
    if len(matches) > 1:
        print(f"{needle!r} matches several. Be more specific:\n")
        for rec in matches:
            print(f"  {rec}  --  {labelled[rec]}")
        return 1

    recording = matches[0]
    print("=" * 78)
    print(f"  {labelled[recording] or recording}")
    print(f"  {recording}")
    print("=" * 78)

    # A0 first, deliberately. Reading it before the others is what makes the
    # difference legible -- and A0 is the shape this project replaces, so it is
    # the baseline the other two are answering.
    for config in ("A0", "A1", "A2"):
        path = by_recording[recording].get(config)
        if path is None:
            continue
        described = {
            "A0": "A0 -- one prompt, everything pre-loaded, no tools",
            "A1": "A1 -- the agent can retrieve",
            "A2": "A2 -- A1, plus a critic and a bounded repair loop",
        }[config]
        print(f"\n{'-' * 78}\n{described}\n{'-' * 78}\n")
        print(feature_text(path))

    print(f"\n{'-' * 78}")
    print("What to look for, in rough order of how much it matters:")
    print("  * Does A0 have any 'Then' lines at all, and are they cited?")
    print("  * Do the step names describe an INTENT, or a mouse?")
    print("  * Is the expected result about the thing under test, or something")
    print("    incidental that also happened to change?")
    print("  * A2 differs from A1 only where the critic had something to say.")
    print("    Often that is nowhere, and that is a real answer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
