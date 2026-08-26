#!/usr/bin/env python
"""Freeze what the pipeline produces today, so a later run can be read against it.

    `compare_features.py` reads one recording across A0 / A1 / A2 -- the same
    pipeline, three configurations. That answers "does agency help". It cannot
    answer "did the change I just made improve the output", because both halves
    of that comparison never exist at the same time: the old runs are overwritten
    or deleted the moment the new ones are made.

So this writes the old half down first. One markdown section per invocation,
appended under a label, holding the full feature text and the numbers beside it.
Run it before a change and again after, and the file is the answer.

    python scripts/snapshot_features.py --label Before
    python scripts/snapshot_features.py --label After

`runs/` is gitignored, so this file is the ONLY durable record of what the
output looked like. Nothing here is recoverable once a run directory is removed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"
DEFAULT_OUT = REPO_ROOT / "docs" / "GHERKIN_BEFORE_AFTER.md"


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def objective_of(ir: dict[str, Any] | None) -> str:
    """What the tester said they were checking, which is how a human names a run.

    Recording ids are not memorable and were never meant to be. Taken from the
    IR rather than the recording so a snapshot still works after the recording
    file has gone.
    """
    if not ir:
        return ""
    for case in ir.get("testCases", []):
        for source in (case.get("objective"), case.get("description")):
            if source:
                return str(source)
    return str(ir.get("title") or "")


def latest_runs(runs_dir: Path) -> list[Path]:
    """One run directory per recording -- the most recent by mtime.

    A recording accumulates ablation runs and re-runs, and a snapshot listing
    all of them is a snapshot nobody reads. The newest is the one that reflects
    the code as it stands.

    An `abl_*` run is skipped while any ordinary run exists, and the reason is
    not tidiness: the ablation runs A0 last-but-one and A2 last, so "newest"
    after an `ablate` is an ablation configuration rather than the pipeline as
    someone would actually use it. A snapshot of A0's output -- which by
    construction claims nothing -- read as the tool's output would be the
    vacuity trap wearing a third hat. The ablation's own numbers go in the
    table below, where they say which configuration they are.
    """
    out: list[Path] = []
    for recording in sorted(runs_dir.glob("rec_*")):
        candidates = [d for d in recording.iterdir() if d.is_dir() and (d / "ir.json").is_file()]
        ordinary = [d for d in candidates if not d.name.startswith("abl_")]
        pool = ordinary or candidates
        if pool:
            out.append(max(pool, key=lambda d: (d / "ir.json").stat().st_mtime))
    return out


def _gate(trace: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Rejections and warnings, by validator name, deduplicated."""
    rejected: list[str] = []
    warned: list[str] = []
    for entry in (trace or {}).get("validatorResults", []) or []:
        name = str(entry.get("validator", "?"))
        action = str(entry.get("action", ""))
        if action == "reject" or action == "hard_fail":
            rejected.append(name)
        elif action == "warn":
            warned.append(name)
    return sorted(set(rejected)), sorted(set(warned))


def _counts(ir: dict[str, Any] | None) -> dict[str, int]:
    """Scenarios, steps and ACCEPTED assertions.

    Accepted rather than proposed: a claim binding deleted is not in the
    artifact, and counting it would make a run that proved less look like a run
    that claimed more -- the vacuity trap this project has hit in five columns.
    """
    cases = [c for c in (ir or {}).get("testCases", []) if c.get("kind") != "bug"]
    steps = [s for c in cases for s in c.get("steps", [])]
    accepted = 0
    for step in steps:
        for assertion in step.get("assertions", []) or []:
            if assertion.get("status", "accepted") != "rejected":
                accepted += 1
    return {
        "scenarios": len(cases),
        "steps": len(steps),
        "assertions": accepted,
        "events": len({e for s in steps for e in s.get("eventIds", []) or []}),
    }


def _feature_text(run: Path) -> str:
    files = sorted(run.glob("*.feature"))
    return "\n\n".join(f.read_text(encoding="utf-8").strip() for f in files)


def section(run: Path) -> str:
    ir = _load(run / "ir.json")
    trace = _load(run / "trace.json")
    metrics = (trace or {}).get("metrics") or {}
    counts = _counts(ir)
    rejected, warned = _gate(trace)
    feature = _feature_text(run)

    recording_id = run.parent.name
    objective = objective_of(ir)

    out = [f"### `{recording_id}` — {objective or 'no stated objective'}", ""]
    out.append(f"`{run.relative_to(REPO_ROOT).as_posix()}`")
    out.append("")
    out.append("| | |")
    out.append("|---|---|")
    out.append(f"| scenarios | {counts['scenarios']} |")
    out.append(f"| steps | {counts['steps']} |")
    out.append(f"| events covered | {counts['events']} |")
    out.append(f"| accepted expected results | {counts['assertions']} |")
    out.append(f"| grounding rate | {metrics.get('groundingRate', '—')} |")
    out.append(f"| validator pass (first / final) | "
               f"{metrics.get('validatorFirstPassRate', '—')} / "
               f"{metrics.get('validatorFinalPassRate', '—')} |")
    # Raised beside resolved, always. `Converged` alone is vacuously 1.0 for a
    # critic that found nothing, which is the same trap as a grounding rate
    # without a yield -- this project has now met it in five columns.
    out.append(f"| critic findings (raised / resolved) | "
               f"{metrics.get('criticFindingsRaised', '—')} / "
               f"{metrics.get('criticFindingsResolved', '—')} |")
    out.append(f"| repair attempts / convergence | "
               f"{metrics.get('repairAttempts', '—')} / "
               f"{metrics.get('repairConvergenceRate', '—')} |")
    out.append(f"| tool calls total | {metrics.get('toolCallsTotal', '—')} |")
    out.append(f"| tool calls per step | `{metrics.get('toolCallsPerStep') or {}}` |")
    split = _load(run / "split.json") or {}
    out.append(f"| scenarios added by the splitter | {split.get('scenariosAdded', '—')} |")
    out.append(f"| rejected by | {', '.join(rejected) if rejected else '*nothing*'} |")
    out.append(f"| warned by | {', '.join(warned) if warned else '*nothing*'} |")
    out.append("")
    out.append("```gherkin")
    out.append(feature or "(no feature file was written)")
    out.append("```")
    out.append("")
    return "\n".join(out)


def ablation_table(runs_dir: Path) -> str:
    report = _load(runs_dir / "ablation.json")
    if not report:
        return "*No `runs/ablation.json` at the time of this snapshot.*\n"
    rows = report.get("rows") or report.get("configs") or []
    if not rows:
        return "```json\n" + json.dumps(report, indent=1)[:4000] + "\n```\n"
    return "```json\n" + json.dumps(rows, indent=1)[:4000] + "\n```\n"


def render(label: str, runs: Iterable[Path], runs_dir: Path) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [f"## {label} — {stamp}", ""]
    runs = list(runs)
    out.append(f"{len(runs)} recording(s), newest run of each.")
    out.append("")
    for run in runs:
        out.append(section(run))
    out.append("#### Ablation at this point")
    out.append("")
    out.append(ablation_table(runs_dir))
    out.append("---")
    out.append("")
    return "\n".join(out)


HEADER = """\
# What the Gherkin looked like, before and after

`runs/` is gitignored and is deleted between milestones, so this file is the
only durable record of what the pipeline actually produced. Each section is a
snapshot: the full feature text for every recording, plus the numbers that say
whether it was honest as well as readable.

Read a grounding rate beside a yield, always. A configuration that claims
nothing scores 1.0.

"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="e.g. Before, After")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--runs", type=Path, default=RUNS)
    args = parser.parse_args(argv)

    if not args.runs.is_dir():
        print(f"No runs directory at {args.runs}", file=sys.stderr)
        return 1

    runs = latest_runs(args.runs)
    if not runs:
        print(f"No runs with an ir.json under {args.runs}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    existing = args.out.read_text(encoding="utf-8") if args.out.is_file() else HEADER
    args.out.write_text(existing.rstrip() + "\n\n" + render(args.label, runs, args.runs),
                        encoding="utf-8")

    print(f"{args.label}: {len(runs)} recording(s) -> {args.out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
