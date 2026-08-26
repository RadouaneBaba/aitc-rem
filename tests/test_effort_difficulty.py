"""The effort/difficulty correlation (SS3.4).

    "If investigation effort correlates with human edit rate, the agent is
     spending effort where the work is genuinely hard. A chain has flat cost per
     step by construction, so the scatter plot alone separates the two
     architectures."

The claim rests entirely on the arithmetic, so the arithmetic is what is tested
here -- and, just as importantly, the refusal to report a number the data does
not support. A chart that looks like evidence and is not is worse than no chart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from effort_difficulty import (  # noqa: E402
    MIN_EDITED_STEPS,
    MIN_POINTS,
    MIN_UNTOUCHED_STEPS,
    Point,
    collect,
    pearson,
    report,
    spearman,
    svg,
)


def points(pairs, *, run: str = "rec_x/run_1") -> list[Point]:
    return [
        Point(run=run, step_id=f"step_{i:03d}", effort=e, edit_magnitude=m, edited=m > 0)
        for i, (e, m) in enumerate(pairs, start=1)
    ]


def sufficient_pairs() -> list[tuple[float, float]]:
    """The smallest sample the script will report on, and a monotone one.

    Both classes have to be populated: a correlation between effort and edit
    rate is a statement about the difference between edited and untouched
    steps, so an all-edited sample is not a weak result, it is no result.
    """
    untouched = [(0, 0.0)] * MIN_UNTOUCHED_STEPS
    edited = [(i, i * 0.1) for i in range(1, MIN_EDITED_STEPS + 1)]
    return untouched + edited


# --------------------------------------------------------------------------
# the arithmetic
# --------------------------------------------------------------------------


def test_a_perfect_monotonic_relationship_scores_one():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert pearson(xs, [2.0, 4.0, 6.0, 8.0]) == pytest.approx(1.0)
    # Spearman is the honest measure here: effort is a small integer count and
    # edit size a ratio, so what is worth claiming is "harder steps get edited
    # more", not "each extra call predicts 4% more editing".
    assert spearman(xs, [1.0, 10.0, 11.0, 500.0]) == pytest.approx(1.0)


def test_an_inverse_relationship_is_negative():
    assert spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]) == pytest.approx(-1.0)


def test_no_variance_reports_nothing_rather_than_zero():
    # Every step costing the same, or nobody editing anything, is an absence of
    # a relationship -- not a measured relationship of zero. A chain is flat by
    # construction, and reporting 0.0 for it would look like a finding.
    assert pearson([2.0, 2.0, 2.0], [1.0, 5.0, 9.0]) is None
    assert pearson([1.0, 5.0, 9.0], [0.0, 0.0, 0.0]) is None


def test_tied_values_share_a_rank():
    # Without this, two equally hard steps get an arbitrary ordering and the
    # coefficient depends on which was recorded first.
    assert spearman([1.0, 1.0, 2.0, 2.0], [3.0, 3.0, 9.0, 9.0]) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# refusing to overclaim
# --------------------------------------------------------------------------


def test_too_few_points_reports_no_correlation():
    summary = report(points([(1, 0.4), (5, 0.9)]), reviewed=1)
    assert not summary["sufficient"]
    assert summary["spearman"] is None
    assert summary["needed"]


def test_one_reviewed_run_is_one_persons_opinion_of_one_recording():
    # Enough points, all from a single session. A correlation drawn from that is
    # about one reviewer and one flow, not about the architecture.
    summary = report(points([(i % 4, (i % 3) * 0.3) for i in range(MIN_POINTS + 4)]), reviewed=1)
    assert not summary["sufficient"]


def test_a_single_edited_step_is_not_a_correlation():
    # The most likely real-world shape early on: plenty of steps, almost none
    # edited. Two points make a perfect line.
    pairs = [(1, 0.0)] * MIN_POINTS + [(6, 0.8)]
    summary = report(points(pairs), reviewed=4)
    assert not summary["sufficient"]
    assert "1 edited" in summary["needed"]


def test_enough_data_reports_the_coefficient():
    summary = report(points(sufficient_pairs()), reviewed=3)
    assert summary["sufficient"]
    assert summary["spearman"] == 1.0
    assert summary["needed"] is None


def test_two_edited_steps_are_not_a_correlation():
    # This is what the script used to call sufficient: two positives out of a
    # hundred-odd steps, reported as r = -0.057 -- noise, pointing AGAINST
    # SS3.4's own thesis -- under a script advertised as one that refuses to
    # overclaim. Two points make a perfect line.
    pairs = [(0, 0.0)] * 40 + [(6, 0.8), (5, 0.7)]
    summary = report(points(pairs), reviewed=9)

    assert not summary["sufficient"]
    assert summary["pearson"] is None and summary["spearman"] is None
    assert "2 edited" in summary["needed"]


def test_a_sample_with_nothing_left_alone_is_not_a_correlation_either():
    # The other empty half. Every step edited says nothing about whether effort
    # went where the work was hard, because there is no comparison group.
    pairs = [(i, i * 0.1) for i in range(1, MIN_POINTS + MIN_EDITED_STEPS + 1)]
    summary = report(points(pairs), reviewed=5)

    assert not summary["sufficient"]
    assert "0 untouched" in summary["needed"]


def test_both_sides_of_the_comparison_are_reported():
    # The headline number is a correlation, but the readable version is "steps
    # the agent worked hard on got edited more". Both means are reported so that
    # sentence can be checked without reading a coefficient.
    summary = report(points([(5, 0.7), (5, 0.6), (1, 0.0), (1, 0.0)]), reviewed=3)
    assert summary["meanEffortEdited"] == 5.0
    assert summary["meanEffortUntouched"] == 1.0


# --------------------------------------------------------------------------
# reading the runs
# --------------------------------------------------------------------------


def test_a_run_with_no_review_contributes_nothing(tmp_path: Path):
    # "Never reviewed" and "reviewed, nobody changed anything" are different
    # facts. Only the second is data.
    run = tmp_path / "rec_a" / "run_1"
    run.mkdir(parents=True)
    (run / "trace.json").write_text(
        json.dumps({"metrics": {"toolCallsPerStep": {"step_001": 3}}}), encoding="utf-8"
    )
    assert collect(tmp_path) == ([], 0)


def test_an_unedited_run_is_the_untouched_half_of_the_correlation(tmp_path: Path):
    run = tmp_path / "rec_a" / "run_1"
    run.mkdir(parents=True)
    (run / "trace.json").write_text(
        json.dumps({"metrics": {"toolCallsPerStep": {"step_001": 3, "step_002": 0}}}),
        encoding="utf-8",
    )
    (run / "review.json").write_text(json.dumps({"edits": []}), encoding="utf-8")

    collected, reviewed = collect(tmp_path)
    assert reviewed == 1
    assert sorted(p.effort for p in collected) == [0, 3]
    assert not any(p.edited for p in collected)


def test_the_largest_edit_on_a_step_is_the_one_that_counts(tmp_path: Path):
    # A step somebody rewrote twice was hard once, not twice.
    run = tmp_path / "rec_a" / "run_1"
    run.mkdir(parents=True)
    (run / "trace.json").write_text(
        json.dumps({"metrics": {"toolCallsPerStep": {"step_001": 2}}}), encoding="utf-8"
    )
    (run / "review.json").write_text(
        json.dumps(
            {
                "edits": [
                    {"stepId": "step_001", "magnitude": 0.2},
                    {"stepId": "step_001", "magnitude": 0.9},
                ]
            }
        ),
        encoding="utf-8",
    )
    collected, _ = collect(tmp_path)
    assert collected[0].edit_magnitude == 0.9


# --------------------------------------------------------------------------
# the chart
# --------------------------------------------------------------------------


def test_the_chart_says_so_when_the_data_is_thin():
    summary = report(points([(1, 0.4), (5, 0.9)]), reviewed=1)
    drawing = svg(points([(1, 0.4), (5, 0.9)]), summary)
    assert "NOT ENOUGH DATA" in drawing
    assert drawing.startswith("<svg")


def test_the_chart_is_self_contained():
    # No plotting dependency and no external assets: it opens anywhere, diffs
    # in review, and drops into a document.
    summary = report(points(sufficient_pairs()), reviewed=3)
    drawing = svg(points(sufficient_pairs()), summary)
    assert "http" not in drawing.replace("http://www.w3.org/2000/svg", "")
    assert "Spearman" in drawing
