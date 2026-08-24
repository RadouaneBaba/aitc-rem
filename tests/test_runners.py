"""Replay: does the generated test case actually run? (SS3.5's missing column)

Grounding proves *provenance* -- that a claim points at a retrieval that really
happened. It does not prove *correctness*, and the two come apart in practice:
the first real replay in this project found a test case whose every validator
passed and whose expected result contradicted its own step.

These tests cover the deterministic half -- turning a finished test case into
instructions a browser can follow. Driving the browser is `scripts/replay.mjs`
and is exercised against the demo app, not here.
"""

from __future__ import annotations

from pathlib import Path

from server.runners import DEFAULT_BASE_URL, PlaywrightRunner, replay_all
from server.runners.base import Runner
from server.runners.playwright import build_job, parse_result
from tests import factories as f


def a_recording():
    return f.recording(
        events=[
            f.event("evt_001", 0, etype="input", tgt=f.target("textbox", "Password")),
            f.event("evt_002", 1, tgt=f.target("button", "Sign in")),
        ]
    )


def a_case(step_ids=("evt_001", "evt_002")):
    step = f.step("step_001", "the tester signs in", assertions=[f.assertion()])
    step.eventIds = list(step_ids)
    return f.test_case(steps=[step])


# --------------------------------------------------------------------------
# the seam
# --------------------------------------------------------------------------


def test_a_runner_matches_the_exporter_shape():
    # SS11's claim is that a new output is a new file, never a pipeline change.
    # A runner is the same bargain for execution: read a finished IRDocument,
    # change nothing.
    assert isinstance(PlaywrightRunner(), Runner)
    assert PlaywrightRunner.name == "playwright"


# --------------------------------------------------------------------------
# building the job
# --------------------------------------------------------------------------


def test_actions_come_from_the_events_not_from_the_step_text():
    # No Gherkin runner in any language executes a .feature without hand-written
    # step definitions matched on the step's text. Constraining the model to a
    # closed vocabulary so a fixed step library could match it would buy
    # executability by giving up the readable prose that is the product. So the
    # prose stays free and the events underneath it are what runs.
    job, missing = build_job(a_case(), a_recording(), base_url=DEFAULT_BASE_URL, parameters={})
    assert not missing
    actions = job["steps"][0]["actions"]
    assert [a["type"] for a in actions] == ["fill", "click"]


def test_selectors_are_ranked_most_stable_first():
    # The order the driver tries them in, and the reason "which rank resolved"
    # is a robustness measurement rather than an opinion.
    job, _ = build_job(a_case(), a_recording(), base_url=DEFAULT_BASE_URL, parameters={})
    strategies = [s["strategy"] for s in job["steps"][0]["actions"][0]["selectors"]]
    assert strategies == sorted(strategies, key=["testId", "role", "text", "css"].index)


def test_a_missing_parameter_blocks_the_run_rather_than_failing_it():
    # SS7.2 makes every redacted value a test parameter, so a replay of a
    # sign-in genuinely needs somebody to supply <<password>>. "I could not run
    # this" and "this does not work" are different findings, and scoring the
    # first as the second would put noise straight into the ablation.
    recording = a_recording()
    recording.events[0].target.value = "<<password>>"
    _job, missing = build_job(a_case(), recording, base_url=DEFAULT_BASE_URL, parameters={})
    assert missing == {"password"}


def test_a_supplied_parameter_is_substituted():
    recording = a_recording()
    recording.events[0].target.value = "<<password>>"
    job, missing = build_job(
        a_case(), recording, base_url=DEFAULT_BASE_URL, parameters={"password": "hunter2"}
    )
    assert not missing
    assert job["steps"][0]["actions"][0]["value"] == "hunter2"


def test_only_accepted_expected_results_are_re_checked():
    # A candidate the ranking demoted is a proposal, not a claim the test case
    # makes. Re-checking it would measure something nobody asserted.
    step = f.step(
        "step_001",
        "the tester signs in",
        assertions=[f.assertion("asrt_1"), f.assertion("asrt_2", accepted=False)],
    )
    step.eventIds = ["evt_001"]
    job, _ = build_job(
        f.test_case(steps=[step]), a_recording(), base_url=DEFAULT_BASE_URL, parameters={}
    )
    assert [a["id"] for a in job["steps"][0]["assertions"]] == ["asrt_1"]


def test_narration_evidence_is_marked_uncheckable_rather_than_assumed():
    # A literal grounded in narration is a thing the tester said out loud. No
    # browser can confirm it, and reporting it as a pass would inflate the
    # number this exists to measure.
    assertion = f.assertion()
    assertion.evidence.kind = "narration"
    step = f.step("step_001", "the tester signs in", assertions=[assertion])
    step.eventIds = ["evt_001"]
    job, _ = build_job(
        f.test_case(steps=[step]), a_recording(), base_url=DEFAULT_BASE_URL, parameters={}
    )
    assert job["steps"][0]["assertions"][0]["kind"] == "not_checkable"


# --------------------------------------------------------------------------
# reading the result
# --------------------------------------------------------------------------


def test_a_result_separates_could_not_run_from_did_not_pass():
    blocked = parse_result(
        "playwright", "tc_1", {"ran": False, "blocked": "nothing is listening"}, files=[]
    )
    assert not blocked.ran
    assert not blocked.passed
    assert blocked.blocked

    failed = parse_result(
        "playwright",
        "tc_1",
        {
            "ran": True,
            "steps": [
                {
                    "stepId": "step_001",
                    "ok": False,
                    "selectorRank": 1,
                    "assertions": [{"assertionId": "a1", "status": "fail", "literal": "x"}],
                }
            ],
        },
        files=[],
    )
    assert failed.ran
    assert not failed.passed
    assert failed.blocked is None
    assert failed.assertions_checked == 1
    assert failed.assertions_held == 0
    assert failed.mean_selector_rank == 1.0


def test_an_unknown_runner_is_reported_rather_than_ignored(tmp_path: Path):
    results = replay_all(
        f.ir_document(test_cases=[a_case()]),
        recording=a_recording(),
        out_dir=tmp_path,
        names=["nosuchrunner"],
    )
    assert results[0].blocked is not None
    assert "nosuchrunner" in results[0].blocked
