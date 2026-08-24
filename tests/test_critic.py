"""The critic, the repair loop and coverage suggestions (SS9.8, SS9.9).

Driven by `ScriptedModelClient` throughout, and for the reason that client
exists: these stages are defined by what they do when the output is BAD, and no
real model can be asked to produce a vague step name on command. The one thing
under test here is the loop's own logic -- which stage re-runs, what it refuses
to touch, and what it reports when it gives up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.llm import CompletionRequest, ScriptedModelClient, answer
from server.models import PipelineStage, RepairTrigger, ValidatorName, ValidatorStatus
from server.pipeline.narrative import would_collapse
from server.pipeline.repair import CRITIC_REPAIR, VALIDATOR_REPAIR, targets
from server.pipeline.run import PipelineOptions, run_pipeline
from server.storage.paths import Storage
from tests import factories as f
from tests.test_pipeline import CONFIRMATION, composed, recording, stage_of

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


def a2(**overrides) -> PipelineOptions:
    from server.models import AblationConfig

    return PipelineOptions.for_config(AblationConfig.A2, **overrides)


#: The first line of `name.REPAIR_ADDENDUM`. The stand-in has to notice it the
#: way a real model would -- from the prompt it was handed, not from a flag the
#: test set.
REWRITING = "You are writing it again"


def scripted(
    *,
    names: list[str],
    repaired: str = "the tester enters the purchase order reference",
    findings: list[dict] | None = None,
    later_findings: list[dict] | None = None,
    suggestions: list[dict] | None = None,
) -> ScriptedModelClient:
    """A run whose naming can be sent back, and whose critic can be scripted.

    `names` is one per step, in order. `repaired` is what naming answers when it
    is handed a step back with a finding -- recognised from the prompt, so the
    stand-in has to notice it was asked something different, exactly as a real
    model does. `later_findings` is what the critic says on the re-review, an
    empty list meaning resolved.
    """
    state = {"critiques": 0, "named": 0}

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "compose":
            return answer(composed())
        if stage == "critic":
            state["critiques"] += 1
            raised = findings if state["critiques"] == 1 else (later_findings or [])
            return answer(json.dumps({"findings": raised or []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": suggestions or []}))
        if stage == "name":
            if REWRITING in (request.messages[1].content or ""):
                text = repaired
            else:
                text = names[min(state["named"], len(names) - 1)]
                state["named"] += 1
            return answer(
                json.dumps({"role": "test_step", "text": text, "confidence": "high"})
            )

        tool_results = [m for m in request.messages if m.role == "tool"]
        if not tool_results:
            from server.llm import calls

            return calls(("find_text", {"query": CONFIRMATION}))
        payload = json.loads(tool_results[-1].content or "{}")
        matches = (payload.get("result") or {}).get("matches") or []
        if not matches:
            return answer(json.dumps({"candidates": []}))
        return answer(
            json.dumps(
                {
                    "candidates": [
                        {
                            "text": "the confirmation banner appears",
                            "provenance": "inferred",
                            "literal": CONFIRMATION,
                            "toolCallId": payload.get("toolCallId"),
                            "eventId": matches[0]["eventId"],
                            "kind": "semantic_node",
                        }
                    ]
                }
            )
        )

    return ScriptedModelClient(behave)


# --------------------------------------------------------------------------
# the trigger table -- which stage owns a finding
# --------------------------------------------------------------------------


def test_an_assembly_bug_is_never_handed_to_a_model():
    # `event_coverage` rejects when an event appears in no step and no
    # omission. That is `_assemble` dropping something, and re-running a model
    # cannot fix it -- but a re-run might produce different step text and make
    # the failure LOOK different, which turns a structural bug into a haunting.
    assert ValidatorName.event_coverage not in VALIDATOR_REPAIR


def test_a_leaked_secret_is_never_repaired():
    # SS7.1: the feature file is not written at all. The fix is upstream in
    # redaction, and a repair that happened to produce a clean sentence would
    # hide a redaction hole rather than close it.
    assert ValidatorName.no_placeholder_leak not in VALIDATOR_REPAIR


def test_coherence_findings_do_not_re_run_composition():
    # Acting on one means re-running composition, which decides merges, splits
    # and case boundaries -- so it can change the step COUNT, and SS3.6
    # promises the same recording produces the same count every time.
    assert "coherence" not in CRITIC_REPAIR
    assert "state_jump" not in CRITIC_REPAIR


def test_a_rejection_with_no_step_has_nothing_to_re_run():
    report = f.validation_report(
        [
            f.validator_result(
                ValidatorName.event_coverage, ValidatorStatus.fail, reject=True, step_id=None
            )
        ]
    )
    assert targets(report, [], protected=set(), known_steps={"step_001"}) == []


def test_several_rejections_on_one_step_are_asked_about_once():
    # A step asked twice in one attempt costs two model calls to answer one
    # question, and the second answer overwrites the first.
    report = f.validation_report(
        [
            f.validator_result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                reject=True,
                step_id="step_001",
                message="cites tc_0447, which is not in this run's trace",
            ),
            f.validator_result(
                ValidatorName.assertion_grounding,
                ValidatorStatus.fail,
                reject=True,
                step_id="step_001",
                message="not in the index",
            ),
        ]
    )
    out = targets(report, [], protected=set(), known_steps={"step_001"})
    assert len(out) == 1
    assert out[0].stage == PipelineStage.assert_
    assert out[0].trigger == RepairTrigger.validator
    assert "tc_0447" in out[0].finding and "not in the index" in out[0].finding


# --------------------------------------------------------------------------
# what the critic may not touch
# --------------------------------------------------------------------------


def test_a_step_the_tester_named_is_never_rewritten(storage: Storage):
    # SS6.7 -- the popup tells the tester the note is used "word for word", and
    # Milestone 8 already shipped one bug where a promise like that went unread
    # on the server side. A critic finding is not licence to break it.
    # The note lands on the step that starts NEXT (SS6.7), which is step_002 --
    # a tester stops, describes what they are about to do, then does it.
    rec = f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, tgt=f.target("button", "Sign in")),
            f.event(
                "evt_002",
                1,
                at=3000.0,
                tgt=f.target("button", "Place order"),
                diff=f.confirmation_diff(),
                network=[f.network_call(status=201)],
                after=f.snapshot(live=[f.node("live.0", "alert", CONFIRMATION)]),
            ),
        ],
        annotations=[
            f.annotation(kind="intent_note", at=1.0, text="the tester places the order as an approver")
        ],
    )
    model = scripted(
        names=["the tester signs in", "the tester places the order"],
        findings=[
            {
                "step": "step_002",
                "kind": "step_name",
                "finding": "does not say which approval was applied",
            }
        ],
    )
    result = run_pipeline(rec, model, storage=storage, run_id="run_prot", options=a2())

    dictated = result.ir.testCases[0].steps[1]
    assert dictated.text == "the tester places the order as an approver"
    assert not result.repair.attempts, "a protected step must not enter the repair loop"
    # Refused, and said so. "The critic found nothing" and "the critic found
    # something inadmissible" are different facts about a run.
    assert any("not applied" in d for d in result.critic.discarded)


def test_a_repair_that_would_swallow_a_step_is_refused():
    # `merge_repeats` folds adjacent steps whose text matches exactly, so a
    # repair prompted with "this name is too vague" can delete the step beside
    # it -- changing the step count mid-run and moving Yield's denominator.
    texts = ["the tester signs in", "the tester places the order"]
    assert would_collapse(texts, 1, "the tester signs in")
    assert would_collapse(texts, 1, "The tester signs in.")
    assert not would_collapse(texts, 1, "the tester places the order again")


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


def test_a_critic_finding_re_runs_naming_and_the_trace_says_so(storage: Storage):
    model = scripted(
        names=["the tester clicks the button", "the tester places the order"],
        findings=[
            {
                "step": "step_001",
                "kind": "step_name",
                "finding": "describes a mouse, not an intent",
            }
        ],
        later_findings=[],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_fix", options=a2())

    assert result.ir.testCases[0].steps[0].text == "the tester enters the purchase order reference"
    assert result.repair.attempts, "the repair must be recorded, not just performed"
    attempt = result.repair.attempts[0]
    assert attempt.stage == PipelineStage.name
    assert attempt.trigger == RepairTrigger.critic
    assert attempt.resolved and not attempt.exhausted
    assert result.trace.metrics.repairConvergenceRate == 1.0
    assert result.trace.metrics.criticFindingsRaised == 1


def test_a_finding_that_never_resolves_is_surfaced_not_swallowed(storage: Storage):
    # SS9.9 -- "on exhaustion the step is surfaced to the human with the
    # unresolved finding stated plainly, never silently accepted."
    model = scripted(
        names=["the tester clicks the button"],
        findings=[
            {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
        ],
        later_findings=[
            {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
        ],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_stuck", options=a2())

    assert any(a.exhausted for a in result.repair.attempts)
    assert result.trace.metrics.repairConvergenceRate == 0.0
    # Both places a human looks.
    case = result.ir.testCases[0]
    assert any("describes a mouse" in n for s in case.steps for n in (s.criticNotes or []))
    assert any(w.source.value == "critic" for w in case.warnings)


def test_the_first_attempt_rate_is_not_improved_by_the_repair_that_followed(
    storage: Storage,
):
    # SS3.5's row is "validator pass rate (FIRST attempt)". Today first and
    # final are the same number only because nothing re-runs; once a loop
    # exists, letting Valid1st absorb the improvement would make the repair
    # loop report itself working by hiding that it had to work at all.
    model = scripted(
        names=["the tester clicks the button", "the tester places the order"],
        findings=[
            {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
        ],
        later_findings=[],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_rates", options=a2())

    metrics = result.trace.metrics
    assert metrics.validatorFirstPassRate is not None
    assert metrics.validatorFinalPassRate is not None
    # The frozen report is kept whole, not just its rate.
    assert result.first_report is not None
    assert all(r.attempt == 1 for r in result.first_report.results)


def test_a_later_stage_cannot_backdate_a_result_into_the_first_attempt(storage: Storage):
    # `first_report` used to BE `draft.report` when nothing repaired, and the
    # coverage stage edits `report.results` in place -- so a validator that had
    # nothing to check on attempt 1 and passed at the end was scored as if it
    # had passed on attempt 1. It surfaced as A1 out-scoring A2 on first-attempt
    # pass rate over identical attempt-1 output, which is impossible.
    #
    # Two guarantees, because either alone leaves the pair unreadable: the
    # first-attempt report is a snapshot, and the final rate is measured over
    # the validators that judged the first draft -- so coverage running cannot
    # move it and only a repair can.
    result = run_pipeline(
        recording(),
        scripted(
            names=["the tester places the order"],
            suggestions=[
                {
                    "category": "boundary_value",
                    "text": "record an order totalling exactly 500",
                    "rationale": "the threshold is quoted and nothing landed on it",
                    "basedOn": ["evt_002"],
                }
            ],
        ),
        storage=storage,
        run_id="run_backdate",
        options=a2(),
    )

    assert result.ir.testCases[0].suggestions, "coverage must actually have run"
    quarantine = [
        r
        for r in result.first_report.results
        if r.validator == ValidatorName.suggestions_quarantined
    ]
    assert quarantine and quarantine[0].status == ValidatorStatus.skip, (
        "on attempt 1 there are no suggestions yet, so the validator has nothing "
        "to check -- and the snapshot must still say so afterwards"
    )
    # No repair happened, so the two rates must be identical. Anything else is
    # the loop taking credit for a stage that is not part of it.
    assert not result.repair.attempts
    assert (
        result.trace.metrics.validatorFirstPassRate
        == result.trace.metrics.validatorFinalPassRate
    )


def test_the_superseded_draft_is_kept_beside_the_one_that_replaced_it(storage: Storage):
    # SS9.1's whole claim is that you can open the intermediate artifact and see
    # which stage lied. A repair that silently replaced the draft it was
    # repairing would take that away exactly when it is most wanted.
    model = scripted(
        names=["the tester clicks the button", "the tester places the order"],
        findings=[
            {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
        ],
        later_findings=[],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_keep", options=a2())

    assert (result.run.root / "naming.attempt1.json").exists()
    assert (result.run.root / "ir.attempt1.json").exists()
    superseded = json.loads((result.run.root / "naming.attempt1.json").read_text(encoding="utf-8"))
    assert superseded["steps"][0]["text"] == "the tester clicks the button"


def test_repair_effort_still_counts_against_the_step_that_needed_it(storage: Storage):
    # SS3.4's column has to reflect what the run actually spent on a step.
    # Under-reporting the step that took two passes would hide exactly the step
    # the correlation exists to find -- the hard one.
    model = scripted(
        names=["the tester clicks the button", "the tester places the order"],
        findings=[
            {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
        ],
        later_findings=[],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_effort", options=a2())

    stages = [i.stage for i in result.trace.investigations if i.stepId == "step_001"]
    assert stages.count(PipelineStage.name) == 2, "both naming passes must be in the trace"


# --------------------------------------------------------------------------
# A1 vs A2 -- the whole reason this phase exists
# --------------------------------------------------------------------------


def test_a1_does_not_critique_and_a2_does(storage: Storage):
    # SS3.5 defines A1 as "tools available, no critic, no repair loop" and A2 as
    # the full pipeline. Until Phase 3 those two arms were the same pipeline and
    # the thesis table had two identical rows.
    from server.models import AblationConfig

    def run(config, run_id):
        model = scripted(
            names=["the tester clicks the button", "the tester places the order"],
            findings=[
                {"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}
            ],
            later_findings=[],
        )
        return run_pipeline(
            recording(),
            model,
            storage=storage,
            run_id=run_id,
            options=PipelineOptions.for_config(config),
        )

    a1_result = run(AblationConfig.A1, "run_a1")
    a2_result = run(AblationConfig.A2, "run_a2")

    assert a1_result.critic is None
    assert not a1_result.repair.attempts
    assert a1_result.ir.testCases[0].steps[0].text == "the tester clicks the button"

    assert a2_result.critic is not None
    assert a2_result.repair.attempts
    assert (
        a2_result.ir.testCases[0].steps[0].text
        == "the tester enters the purchase order reference"
    )


def test_coverage_runs_in_a1_too_so_the_arms_differ_by_one_thing(storage: Storage):
    # Attaching coverage to the A2 flag would make the A1/A2 comparison measure
    # two changes at once, which is the same mistake as letting Valid1st absorb
    # the repair loop.
    from server.models import AblationConfig

    options = PipelineOptions.for_config(AblationConfig.A1)
    assert options.suggestions_enabled
    assert not options.critic_enabled


# --------------------------------------------------------------------------
# coverage suggestions
# --------------------------------------------------------------------------


def test_a_suggestion_never_reaches_the_feature_file(storage: Storage):
    # SS9.8 and the decision log both say it in the strongest terms available:
    # suggestions "must never contaminate grounded output".
    model = scripted(
        names=["the tester places the order"],
        suggestions=[
            {
                "category": "boundary_value",
                "text": "record an order totalling exactly 500",
                "rationale": "the banner quotes a 500 threshold and nothing exercised it",
                "basedOn": ["evt_002"],
            }
        ],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_sug", options=a2())

    case = result.ir.testCases[0]
    assert case.suggestions and case.suggestions[0].category.value == "boundary_value"
    for feature in result.rendered.values():
        assert "totalling exactly 500" not in feature
    # The quarantine is a gate, not a convention.
    assert any(
        r.validator == ValidatorName.suggestions_quarantined and r.status == ValidatorStatus.pass_
        for r in result.report.results
    )


def test_a_suggestion_does_not_move_the_grounding_rate(storage: Storage):
    # A suggestion is not a claim about the session and must never be counted
    # as one -- neither as an assertion nor as evidence of yield.
    model = scripted(
        names=["the tester places the order"],
        suggestions=[
            {
                "category": "api_error_shape",
                "text": "record a duplicate purchase order reference",
                "rationale": "the endpoint documents a conflict nothing provoked",
                "basedOn": ["evt_002"],
            }
        ],
    )
    with_suggestion = run_pipeline(
        recording(), model, storage=storage, run_id="run_with", options=a2()
    )
    without = run_pipeline(
        recording(),
        scripted(names=["the tester places the order"]),
        storage=storage,
        run_id="run_without",
        options=a2(suggestions_enabled=False),
    )

    assert with_suggestion.ir.testCases[0].suggestions
    assert not without.ir.testCases[0].suggestions
    assert with_suggestion.grounding_rate == without.grounding_rate
    assert (
        with_suggestion.trace.metrics.assertionsTotal == without.trace.metrics.assertionsTotal
    )


def test_a_suggestion_with_no_rationale_is_dropped_and_said_so(storage: Storage):
    # `rationale` is where the evidence goes, so a suggestion without one is an
    # opinion about software in general. SS9.8's whole value is that it reasons
    # about THIS application.
    model = scripted(
        names=["the tester places the order"],
        suggestions=[
            {"category": "validation_path", "text": "test the email field", "basedOn": []}
        ],
    )
    result = run_pipeline(recording(), model, storage=storage, run_id="run_norat", options=a2())

    assert not result.ir.testCases[0].suggestions
    payload = json.loads(
        (result.run.root / "coverage.json").read_text(encoding="utf-8")
    )
    assert any("no rationale" in d for d in payload["discarded"])


# --------------------------------------------------------------------------
# bug mode (SS14)
# --------------------------------------------------------------------------


def _load(name: str):
    from server.models import Recording

    path = FIXTURES / f"{name}.recording.json"
    if not path.exists():
        pytest.skip("run `pnpm e2e` to regenerate the recorded fixtures")
    return Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))


SERVER_ERROR = "Internal server error"


def failing_recording():
    """A 500 the application also told the tester about, in a live region.

    Both halves matter. The 500 is what `detect` scores on; the alert is what
    there is to QUOTE, and SS14.2 will not accept a bug report without one.
    """
    return f.recording(
        events=[
            f.event(
                "evt_001",
                0,
                at=0.0,
                tgt=f.target("button", "Export"),
                network=[f.network_call(status=500)],
                after=f.snapshot(live=[f.node("live.0", "alert", SERVER_ERROR)]),
            )
        ]
    )


def bug_model(*, literal: str | None) -> ScriptedModelClient:
    """A run that reaches a bug report, or refuses to.

    `literal=None` is the model that cannot find anything saying what went
    wrong -- the case where writing nothing is the right answer.
    """
    from server.llm import calls

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "compose":
            return answer(composed())
        if stage == "critic":
            return answer(json.dumps({"findings": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "name":
            return answer(
                json.dumps(
                    {
                        "role": "test_step",
                        "text": "the tester exports the order",
                        "confidence": "high",
                    }
                )
            )

        is_bug = stage == "bug"
        tool_results = [m for m in request.messages if m.role == "tool"]
        if not tool_results:
            return calls(("find_text", {"query": SERVER_ERROR if is_bug else CONFIRMATION}))

        payload = json.loads(tool_results[-1].content or "{}")
        matches = (payload.get("result") or {}).get("matches") or []
        if not is_bug:
            return answer(json.dumps({"candidates": []}))
        if literal is None or not matches:
            return answer(
                json.dumps({"expected": "the export succeeds", "actual": "it did not, somehow"})
            )
        return answer(
            json.dumps(
                {
                    "expected": "the export succeeds and a file is produced",
                    "actual": "the server returned a 500 and no export was created",
                    "literal": literal,
                    "toolCallId": payload.get("toolCallId"),
                    "eventId": matches[0]["eventId"],
                    "kind": "semantic_node",
                }
            )
        )

    return ScriptedModelClient(behave)


@pytest.mark.parametrize("name", ["checkout", "twoflows", "wander", "narrated"])
def test_a_rejection_the_test_is_about_is_not_a_bug(name: str):
    # Every one of these fixtures contains a 409 on a state-mutating POST, and
    # in every one of them that 409 IS the thing under test -- "orders over
    # EUR500 require approval" is the objective, not a defect. A threshold two
    # medium signals could clear would turn all four into bug reports, which is
    # a louder and more damaging failure than detecting nothing at all.
    from server.pipeline.bugmode import detect

    signals = detect(_load(name))
    assert not signals.detected, signals.summary
    # And the signal is still recorded. A tester asking why it is NOT a bug
    # gets the arithmetic rather than silence.
    assert any(s.kind == "http_4xx_on_mutation" for s in signals.signals)


def test_a_real_failure_recording_is_detected_as_one():
    # Milestone 20's done-when, on a recording the real extension made through
    # the real browser. Three of SS14.1's signals arrive together the way they
    # do in the wild: the tester's marker, an uncaught exception, and a 5xx.
    from server.pipeline.bugmode import detect

    signals = detect(_load("bugged"))
    assert signals.detected, signals.summary
    kinds = {s.kind for s in signals.signals}
    assert {"bug_marker", "uncaught_exception", "http_5xx"} <= kinds
    # And it knows WHERE, which is what the repro steps get cut at.
    assert signals.failure_event_id is not None


def test_the_testers_own_marker_is_decisive():
    # SS14.1 -- the tester pressed the key at the moment they saw it, so it
    # settles both whether and where.
    from server.pipeline.bugmode import detect

    rec = f.recording(
        events=[f.event("evt_001", 0, at=0.0, tgt=f.target("button", "Export"))],
        annotations=[f.annotation(kind="bug_marker", at=10.0, event_id="evt_001")],
    )
    signals = detect(rec)
    assert signals.detected
    assert signals.failure_event_id == "evt_001"


def test_a_server_error_is_detected_without_any_annotation():
    # SS6.7 -- "the tool must be fully usable with zero annotations". Detection
    # cannot depend on the hotkey.
    from server.pipeline.bugmode import detect

    signals = detect(failing_recording())
    assert signals.detected
    assert signals.failure_event_id == "evt_001"


def test_a_bug_reports_actual_must_quote_a_retrieval(storage: Storage):
    # SS14.2 -- "`expected` and `actual` are subject to the same evidence
    # binding (SS3.2); `actual` must quote something the agent retrieved." This
    # is the one sentence a developer reads before deciding whether to go and
    # reproduce something, so it gets no weaker path than any assertion.
    from server.pipeline.validators.grounding import bug_claim

    result = run_pipeline(
        failing_recording(),
        bug_model(literal=SERVER_ERROR),
        storage=storage,
        run_id="run_bug",
        options=a2(),
    )

    bug = next((c for c in result.ir.testCases if c.kind == "bug_report"), None)
    assert bug is not None, "a 500 with a citable line must produce a report"
    assert bug.bug is not None and bug.bug.actualEvidence is not None
    # The claim goes through the same gate as any assertion, in the same loop.
    assert bug_claim(bug) is not None
    assert any(
        r.validator == ValidatorName.evidence_retrieved and r.status == ValidatorStatus.pass_
        for r in result.report.results
    )


def test_a_retrieval_made_after_the_trace_was_built_still_resolves(storage: Storage):
    # Found on a real run, and it is the most confusing failure this codebase
    # can produce: `evidence_retrieved` rejecting a citation that is true,
    # resolvable and correct.
    #
    # `AgentTrace(toolCalls=runner.calls)` LOOKS like it aliases the runner's
    # live list. It does not -- Pydantic validates the field and copies it -- so
    # every stage that retrieves after the trace was built is invisible to the
    # gate unless the trace is re-synced. The bug describer is the last such
    # stage, which makes it the canary.
    result = run_pipeline(
        failing_recording(),
        bug_model(literal=SERVER_ERROR),
        storage=storage,
        run_id="run_sync",
        options=a2(),
    )

    bug = next(c for c in result.ir.testCases if c.kind == "bug_report")
    cited = bug.bug.actualEvidence.toolCallId
    assert any(c.id == cited for c in result.trace.toolCalls), (
        f"the bug report cites {cited}, which the trace does not contain -- "
        f"the retrieval log was snapshotted before the describer ran"
    )
    assert not [
        r
        for r in result.report.results
        if r.validator == ValidatorName.evidence_retrieved
        and r.status == ValidatorStatus.fail
    ]


def test_a_bug_report_that_cannot_cite_anything_is_not_written(storage: Storage):
    # Refusing is the correct outcome, not a degradation: a developer sent to
    # reproduce something the tool invented has lost more time than the tool
    # ever saved.
    result = run_pipeline(
        failing_recording(),
        bug_model(literal=None),
        storage=storage,
        run_id="run_nobug",
        options=a2(),
    )

    assert all(c.kind != "bug_report" for c in result.ir.testCases)
    assert not list(result.run.root.glob("*.bug.md"))


def test_a_bug_report_is_written_beside_the_test_case_not_instead_of_it(storage: Storage):
    # SS14.1 -- "the tool offers a bug report ALONGSIDE the test case rather
    # than instead of it". The steps that reached the failure are a test case
    # whether or not the failure turns out to be a defect.
    result = run_pipeline(
        failing_recording(),
        bug_model(literal=SERVER_ERROR),
        storage=storage,
        run_id="run_both",
        options=a2(),
    )

    kinds = {c.kind.value for c in result.ir.testCases}
    assert kinds == {"test_case", "bug_report"}
    assert list(result.run.root.glob("*.feature")), "the test case is still produced"
    assert list(result.run.root.glob("*.bug.md")), "and the bug report beside it"


def test_a_lifted_background_step_is_rendered_rather_than_dropped():
    # A latent bug this phase surfaced rather than caused, and the worst kind:
    # `lift_background` moved the leading setup steps into `narrative.background`
    # and `_background` rendered `case.preconditions` instead, so every
    # multi-scenario recording silently lost its sign-in from the feature file.
    # Nothing caught it -- `event_coverage` reads the IR rather than the rendered
    # output, and a file missing a step still parses.
    import copy

    from server.models import SegmentRole
    from server.pipeline.narrative import sync_keywords
    from server.renderers.gherkin import render_test_case

    case = f.test_case()
    setup = copy.deepcopy(case.steps[0])
    setup.id, setup.role, setup.text, setup.assertions = (
        "step_000",
        SegmentRole.setup,
        "the tester signs in",
        [],
    )
    case.steps[0].role = SegmentRole.test_step
    case.steps = [setup, case.steps[0]]
    sync_keywords(case.steps)

    ir = f.ir_document()
    ir.testCases = [case, copy.deepcopy(case)]
    ir.testCases[1].id = "tc_second"

    feature = render_test_case(case, ir=ir)
    assert "Background:" in feature
    assert "the tester signs in" in feature, "the lifted step must survive being lifted"


def test_a_bug_report_is_not_a_scenario_that_shares_setup():
    # Adding a bug report made `len(ir.testCases) > 1` true for a
    # single-scenario feature, which lifted a Background out of it. A bug report
    # is not a scenario and is not even rendered here, so it must not be counted
    # when deciding whether two scenarios share setup.
    import copy

    from server.models import SegmentRole
    from server.pipeline.narrative import sync_keywords
    from server.renderers.gherkin import render_test_case

    case = f.test_case()
    setup = copy.deepcopy(case.steps[0])
    setup.id, setup.role, setup.text, setup.assertions = (
        "step_000",
        SegmentRole.setup,
        "the tester signs in",
        [],
    )
    case.steps[0].role = SegmentRole.test_step
    case.steps = [setup, case.steps[0]]
    sync_keywords(case.steps)

    ir = f.ir_document()
    ir.testCases = [case, copy.deepcopy(case)]
    ir.testCases[1].id = "tc_bug"
    ir.testCases[1].kind = "bug_report"

    feature = render_test_case(case, ir=ir)
    assert "Background:" not in feature
    assert "Given the tester signs in" in feature


def test_a_bug_report_is_never_rendered_as_gherkin():
    # Gherkin is a language for saying what SHOULD happen. A `.feature` whose
    # scenario is a defect would be picked up by a suite and fail on purpose,
    # every run, forever.
    from server.renderers.gherkin import render_document

    ir = f.ir_document()
    ir.testCases[0].kind = "bug_report"
    assert render_document(ir) == {}
