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


def test_a_saved_session_reaches_the_driver_only_when_the_file_exists(tmp_path: Path):
    # A state file expires, and a replay that refused to start because of one
    # would be less useful than a replay that signs in the slow way -- the
    # recorded login is still in the steps. So an absent path is dropped rather
    # than passed on for the driver to fail a context on.
    state = tmp_path / "saucedemo.json"
    job, _ = build_job(
        a_case(),
        a_recording(),
        base_url=DEFAULT_BASE_URL,
        parameters={},
        storage_state=state,
    )
    assert "storageState" not in job

    state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    job, _ = build_job(
        a_case(),
        a_recording(),
        base_url=DEFAULT_BASE_URL,
        parameters={},
        storage_state=state,
    )
    assert job["storageState"] == str(state)


def test_a_scenario_that_inherits_a_background_replays_it_first():
    # Found by replaying a real two-scenario document. A document with more than
    # one scenario lifts the shared opening into a `Background`, so the second
    # case's own steps begin partway through the flow -- and the replay started
    # at `startUrl` and clicked a control on a page it had never navigated to.
    #
    # It is the vacuity trap in its mirror image. A green replay of a case with
    # no actions inflates `executionRate`; a red replay of a case the runner
    # never set up deflates it. Both make the column measure the harness.
    step = f.step("step_002", "the tester signs in", assertions=[])
    step.eventIds = ["evt_002"]
    case = f.test_case(
        steps=[step],
        preconditions=[
            f.precondition("pre_001", "the tester enters a password", event_ids=["evt_001"])
        ],
    )
    job, _ = build_job(case, a_recording(), base_url=DEFAULT_BASE_URL, parameters={})

    assert [s["id"] for s in job["steps"]] == ["pre_001", "step_002"]
    assert job["steps"][0]["actions"][0]["type"] == "fill"
    # And without assertions: a precondition's text states shared state, not a
    # verdict this scenario reached, so re-checking one would count the same
    # claim once per scenario that inherits it.
    assert job["steps"][0]["assertions"] == []


def test_an_event_the_runner_cannot_drive_stops_the_step_instead_of_vanishing():
    # A file chooser, a dialog and a tab opening cannot be driven from a
    # recorded selector. They used to return None and be dropped, so a step made
    # entirely of them had NO actions -- and a step with no actions was reported
    # as passing. That inflates `executionRate`, which is the one number in this
    # system nobody can argue with and therefore the one that must never be
    # vacuous. An unsupported action is a fact about the runner; hiding it makes
    # the runner grade its own gaps.
    recording = f.recording(
        events=[f.event("evt_001", 0, etype="dialog", tgt=f.target("button", "OK"))]
    )
    step = f.step("step_001", "the tester dismisses the dialog", assertions=[])
    step.eventIds = ["evt_001"]
    job, _ = build_job(
        f.test_case(steps=[step]), recording, base_url=DEFAULT_BASE_URL, parameters={}
    )
    action = job["steps"][0]["actions"][0]
    assert action["type"] == "unsupported"
    assert action["detail"] == "dialog"


def test_a_keyboard_action_is_replayed_with_the_chord_the_recorder_stored():
    # This branch had never executed once: it tested for `keydown`, which is not
    # a member of EventType -- the value is `keypress` -- so every keyboard
    # action fell through to the drop below. It also read `event.key`, and the
    # field is `keys`, which carries the whole chord. Two bugs in three lines,
    # both invisible because the fallback was silent.
    recording = f.recording(
        events=[f.event("evt_001", 0, etype="keypress", tgt=f.target("textbox", "Search"))]
    )
    recording.events[0].keys = "Control+Enter"
    step = f.step("step_001", "the tester submits with the keyboard", assertions=[])
    step.eventIds = ["evt_001"]
    job, _ = build_job(
        f.test_case(steps=[step]), recording, base_url=DEFAULT_BASE_URL, parameters={}
    )
    action = job["steps"][0]["actions"][0]
    assert action["type"] == "press"
    assert action["key"] == "Control+Enter"


def test_network_evidence_is_uncheckable_because_the_driver_never_observes_it():
    # `network` and `console` sat in CHECKABLE for a year while `replay.mjs`
    # answered `not_checkable` for both regardless: the driver attaches no
    # listeners, so the window has closed by the time an assertion is checked.
    # Two sides disagreeing about what is checkable is how a gap stays
    # invisible -- this half looked like it re-checked network evidence and
    # never did. Re-adding either means teaching the driver first.
    assertion = f.assertion()
    assertion.evidence.kind = "network"
    step = f.step("step_001", "the tester signs in", assertions=[assertion])
    step.eventIds = ["evt_001"]
    job, _ = build_job(
        f.test_case(steps=[step]), a_recording(), base_url=DEFAULT_BASE_URL, parameters={}
    )
    assert job["steps"][0]["assertions"][0]["kind"] == "not_checkable"


# --------------------------------------------------------------------------
# reading the result
# --------------------------------------------------------------------------


def test_a_case_with_no_steps_has_not_passed():
    # `ran and all(...)` over an empty list is True. This project has met that
    # shape in seven columns now -- a grounding rate of 1.0 on a run that
    # claimed nothing, `Executes` on a configuration that abstained, `Converged`
    # over findings the loop was never allowed to act on. Here it reported a
    # green replay for a test case the runner could not express one action for.
    empty = parse_result("playwright", "tc_1", {"ran": True, "steps": []}, files=[])
    assert empty.ran
    assert not empty.passed
    assert empty.assertions_checked == 0


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
