"""The effort/difficulty correlation (SS3.4).

    "If investigation effort correlates with human edit rate, the agent is
     spending effort where the work is genuinely hard. A chain has flat cost per
     step by construction, so the scatter plot alone separates the two
     architectures -- using production data, with no hand-written golden set."

Both halves already exist and are collected for free. `trace.metrics
.toolCallsPerStep` counts retrievals per step across every stage; `review.json`
records which steps a human edited and by how much. This joins them, measures
the correlation, and draws it.

Run it:

    .venv/Scripts/python scripts/effort_difficulty.py [--out runs/effort.svg]

No plotting dependency. The data is a few dozen points and the output is an SVG
anybody can open, diff, or drop into a document -- adding a charting library to
draw one scatter would cost more than it returns. The JSON beside it is the
real deliverable: plot it however you like.

**It refuses to report a correlation it cannot support.** Two points make a
perfect line, and a chart that looks like evidence when it is not is worse than
no chart, so this says how much data it had and what it would need.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS = REPO_ROOT / "runs"

#: Below this, a correlation coefficient is an artefact of the sample rather
#: than a finding about the architecture.
MIN_POINTS = 12

#: And the edits have to come from more than one session, or the "correlation"
#: is one reviewer's opinion of one recording.
MIN_REVIEWED_RUNS = 3


@dataclass(frozen=True)
class Point:
    run: str
    step_id: str
    #: Retrievals spent on this step, across naming and assertion (SS3.3).
    effort: int
    #: How much a human changed it afterwards. 0 means they left it alone.
    edit_magnitude: float
    edited: bool


def collect(runs_dir: Path) -> tuple[list[Point], int]:
    """Join effort against edits, per step, across every run that has both."""
    points: list[Point] = []
    reviewed = 0

    for trace_path in sorted(runs_dir.glob("rec_*/*/trace.json")):
        run_dir = trace_path.parent
        review_path = run_dir / "review.json"
        if not review_path.exists():
            continue

        trace = _load(trace_path)
        review = _load(review_path)
        if trace is None or review is None:
            continue

        per_step = ((trace.get("metrics") or {}).get("toolCallsPerStep")) or {}
        if not per_step:
            continue
        reviewed += 1

        # Largest edit per step: a step someone rewrote twice was hard once.
        magnitude: dict[str, float] = {}
        for edit in review.get("edits", []):
            step_id = edit.get("stepId")
            if not step_id:
                continue
            magnitude[step_id] = max(magnitude.get(step_id, 0.0), float(edit.get("magnitude") or 0))

        for step_id, effort in per_step.items():
            size = magnitude.get(step_id, 0.0)
            points.append(
                Point(
                    run=f"{run_dir.parent.name}/{run_dir.name}",
                    step_id=step_id,
                    effort=int(effort),
                    edit_magnitude=size,
                    edited=step_id in magnitude,
                )
            )

    return points, reviewed


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    # No variance in one axis means no correlation to speak of, not a
    # correlation of zero: every step cost the same, or nobody edited anything.
    return None if dx == 0 or dy == 0 else num / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation -- the honest one here.

    Effort is a small-integer count and edit magnitude is a ratio, so the
    relationship worth claiming is monotonic ("harder steps get edited more"),
    not linear ("each extra tool call predicts 4% more editing").
    """
    return pearson(_ranks(xs), _ranks(ys))


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def report(points: list[Point], reviewed: int) -> dict:
    effort = [float(p.effort) for p in points]
    size = [p.edit_magnitude for p in points]
    edited = [p for p in points if p.edited]

    enough = len(points) >= MIN_POINTS and reviewed >= MIN_REVIEWED_RUNS and len(edited) >= 2
    return {
        "steps": len(points),
        "reviewedRuns": reviewed,
        "stepsEdited": len(edited),
        "meanEffortEdited": (
            round(sum(p.effort for p in edited) / len(edited), 3) if edited else None
        ),
        "meanEffortUntouched": (
            round(
                sum(p.effort for p in points if not p.edited) / max(1, len(points) - len(edited)),
                3,
            )
            if len(points) > len(edited)
            else None
        ),
        "sufficient": enough,
        "pearson": round(pearson(effort, size), 4) if enough and pearson(effort, size) else None,
        "spearman": (
            round(spearman(effort, size), 4) if enough and spearman(effort, size) else None
        ),
        "needed": (
            None
            if enough
            else (
                f"{MIN_POINTS} steps from {MIN_REVIEWED_RUNS} reviewed runs with at least two "
                f"edited steps; have {len(points)} steps from {reviewed} run(s) with "
                f"{len(edited)} edited. Approve some drafts in the review UI and re-run."
            )
        ),
        "points": [
            {"run": p.run, "stepId": p.step_id, "effort": p.effort, "edit": p.edit_magnitude}
            for p in points
        ],
    }


def svg(points: list[Point], summary: dict) -> str:
    """A scatter, drawn plainly. Effort across, edit size up."""
    w, h, pad = 640, 420, 56
    max_x = max((p.effort for p in points), default=1) or 1
    max_y = max((p.edit_magnitude for p in points), default=1.0) or 1.0

    def px(v: float) -> float:
        return pad + (v / max_x) * (w - 2 * pad)

    def py(v: float) -> float:
        return h - pad - (v / max_y) * (h - 2 * pad)

    dots = "\n".join(
        f'  <circle cx="{px(p.effort):.1f}" cy="{py(p.edit_magnitude):.1f}" r="5" '
        f'fill="{"#b3261e" if p.edited else "#2f6f4f"}" fill-opacity="0.65">'
        f"<title>{_esc(p.run)} {_esc(p.step_id)}: {p.effort} call(s), "
        f"edit {p.edit_magnitude:.2f}</title></circle>"
        for p in points
    )

    if summary["sufficient"]:
        caption = (
            f"Spearman {summary['spearman']}  ·  Pearson {summary['pearson']}  ·  "
            f"{summary['steps']} steps from {summary['reviewedRuns']} reviewed runs"
        )
    else:
        caption = f"NOT ENOUGH DATA — {summary['needed']}"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" \
font-family="system-ui, sans-serif" font-size="12">
  <rect width="{w}" height="{h}" fill="#ffffff"/>
  <text x="{pad}" y="26" font-size="14" font-weight="600">Investigation effort vs human editing \
(SS3.4)</text>
  <text x="{pad}" y="44" fill="#5b6470">{_esc(caption)}</text>
  <line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#1c1f23"/>
  <line x1="{pad}" y1="{pad + 12}" x2="{pad}" y2="{h - pad}" stroke="#1c1f23"/>
  <text x="{w / 2}" y="{h - 16}" text-anchor="middle" fill="#5b6470">tool calls spent on the \
step &#8594;</text>
  <text x="16" y="{h / 2}" text-anchor="middle" fill="#5b6470" \
transform="rotate(-90 16 {h / 2})">size of the human edit &#8594;</text>
  <text x="{pad - 8}" y="{py(0):.1f}" text-anchor="end" fill="#5b6470">0</text>
  <text x="{pad - 8}" y="{py(max_y):.1f}" text-anchor="end" fill="#5b6470">{max_y:.2f}</text>
  <text x="{px(max_x):.1f}" y="{h - pad + 16}" text-anchor="middle" fill="#5b6470">{max_x}</text>
{dots}
  <circle cx="{w - pad - 96}" cy="{pad - 4}" r="5" fill="#b3261e" fill-opacity="0.65"/>
  <text x="{w - pad - 84}" y="{pad}" fill="#5b6470">edited</text>
  <circle cx="{w - pad - 34}" cy="{pad - 4}" r="5" fill="#2f6f4f" fill-opacity="0.65"/>
  <text x="{w - pad - 22}" y="{pad}" fill="#5b6470">left alone</text>
</svg>
"""


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(RUNS))
    parser.add_argument("--out", default=str(RUNS / "effort_difficulty.svg"))
    args = parser.parse_args()

    points, reviewed = collect(Path(args.runs))
    summary = report(points, reviewed)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg(points, summary), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Steps:            {summary['steps']} from {summary['reviewedRuns']} reviewed run(s)")
    print(f"Edited by a human:{summary['stepsEdited']:>4}")
    if summary["meanEffortEdited"] is not None:
        print(f"Mean effort, edited steps:     {summary['meanEffortEdited']}")
    if summary["meanEffortUntouched"] is not None:
        print(f"Mean effort, untouched steps:  {summary['meanEffortUntouched']}")

    if summary["sufficient"]:
        print(f"\nSpearman: {summary['spearman']}   Pearson: {summary['pearson']}")
        print(
            "A positive rank correlation is SS3.4's claim: the agent spends effort where the\n"
            "work is genuinely hard. A chain is flat by construction and cannot produce one."
        )
    else:
        # Refusing to report is the point. Two points make a perfect line.
        print(f"\nNo correlation reported. {summary['needed']}")

    print(f"\nWritten to {out} and {out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
