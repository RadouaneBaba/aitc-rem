"""One recording, one run -- applied to the runs already on disk.

`api._run_id` makes this true from now on: pressing Stop and then answering the
confirmation screen re-run in place instead of stacking a second directory. What
that does not do is tidy up what stacked before it. `rec_MTEU954A8F5X` has three
runs, `rec_MTE5BVCZO8QU` has six, and every one of them shows up in the run
picker as a separate row with nothing on screen saying which is which.

## What it keeps

The run with the most BOUND assertions -- an expected result whose evidence
resolved to a retrieval this run actually made. Not the newest, and not the one
with the most steps.

That is the only ranking available that measures the thing the tool is for. A
later run is not a better run: on the coffee recording, `run_001` shipped two
bound verdicts and the two runs that followed it -- both written against
CONFIRMED expectations, which should have made them better -- shipped one,
because the author reached for a `Scenario Outline` whose templated verdict
could not bind to a literal. Keeping the newest would have thrown away the best
of the three.

Ties break toward the newest, which is the only thing left to say when two runs
prove the same amount.

## What it does not do

Delete anything, unless you pass `--delete`. It prints the plan and stops.
`runs/` is `.gitignore`d, so there is no reflog and no recovery -- the same
reason CLAUDE.md's standing warning about `git checkout --` exists. Read the
plan, then run it again.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"


@dataclass(frozen=True)
class Run:
    path: Path
    bound: int
    assertions: int
    steps: int
    mtime: float

    @property
    def name(self) -> str:
        return self.path.name

    def summary(self) -> str:
        return f"{self.bound} bound / {self.assertions} claimed, {self.steps} steps"


def read_run(path: Path) -> Run | None:
    """Measure one run, or None when it has no `ir.json` to measure."""
    ir_path = path / "ir.json"
    if not ir_path.exists():
        return None
    try:
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    bound = claimed = steps = 0
    for case in ir.get("testCases") or []:
        for step in case.get("steps") or []:
            steps += 1
            for assertion in step.get("assertions") or []:
                if not assertion.get("accepted", True):
                    continue
                claimed += 1
                # The whole point of the run: a claim that points at the
                # retrieval which produced it, in this run.
                if (assertion.get("evidence") or {}).get("toolCallId"):
                    bound += 1

    return Run(path=path, bound=bound, assertions=claimed, steps=steps, mtime=path.stat().st_mtime)


def plan(runs_dir: Path) -> list[tuple[str, Run | None, list[Run], list[Path]]]:
    """Per recording: which run to keep, which to remove, and what crashed.

    A directory with no `ir.json` is a run that died before it wrote one. It is
    invisible in the picker -- `api._list_runs` globs `*/*/ir.json` -- so it is
    clutter rather than a wrong row, but it is still a run directory that
    produced nothing and can never be reviewed. Swept only when the recording
    has a real run to keep, so a recording whose ONLY attempt failed keeps its
    evidence of failing.
    """
    out: list[tuple[str, Run | None, list[Run], list[Path]]] = []
    for recording in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if recording.name.startswith("_"):
            # `_cassettes` is not a recording.
            continue
        dirs = [p for p in sorted(recording.iterdir()) if p.is_dir()]
        runs = [r for r in (read_run(p) for p in dirs) if r]
        measured = {r.path for r in runs}
        crashed = [p for p in dirs if p not in measured]

        if not runs or (len(runs) < 2 and not crashed):
            continue
        best = max(runs, key=lambda r: (r.bound, r.assertions, r.mtime))
        out.append((recording.name, best, [r for r in runs if r.path != best.path], crashed))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delete",
        action="store_true",
        help="actually remove the runs. Without it, print the plan and stop.",
    )
    parser.add_argument("--runs-dir", type=Path, default=RUNS)
    args = parser.parse_args()

    if not args.runs_dir.exists():
        print(f"no runs directory at {args.runs_dir}")
        return 0

    work = plan(args.runs_dir)
    if not work:
        print("Every recording already has one run. Nothing to do.")
        return 0

    removing = 0
    for recording, best, rest, crashed in work:
        print(f"\n{recording}")
        if best:
            print(f"  keep    {best.name:<14} {best.summary()}")
        for run in sorted(rest, key=lambda r: r.name):
            print(f"  remove  {run.name:<14} {run.summary()}")
            removing += 1
        for path in sorted(crashed):
            print(f"  remove  {path.name:<14} no ir.json - this run never finished")
            removing += 1

    print(f"\n{len(work)} recording(s), {removing} run(s) to remove.")

    if not args.delete:
        print("\nThis was a dry run. Nothing was deleted.")
        print("`runs/` is gitignored, so a delete cannot be undone -- read the plan above,")
        print("then run again with --delete.")
        return 0

    for _recording, _best, rest, crashed in work:
        for run in rest:
            shutil.rmtree(run.path)
        for path in crashed:
            shutil.rmtree(path)
    print(f"\nRemoved {removing} run(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
