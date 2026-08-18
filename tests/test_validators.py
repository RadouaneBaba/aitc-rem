"""The validation gate (SS9.7).

    "A deliberately fabricated assertion is rejected; an assertion pointing at
     a non-existent tool call is rejected."

That is the milestone's done-when, and it is why these fixtures are hand-built:
a real model will not fabricate on command, so the broken cases have to be
constructed. Each test breaks exactly one thing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.models import (
    AgentTrace,
    FidelityFlag,
    IRDocument,
    PipelineStage,
    Recording,
    RunConfig,
    ValidatorName,
    ValidatorStatus,
)
from server.pipeline.segment import segment_recording
from server.pipeline.validators import (
    ValidationContext,
    grounding_rate,
    validate,
)
from server.storage.paths import Storage
from tests import factories as f

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIRMATION = "Order confirmed"


class Harness:
    """A complete, honest run: recording, retrieval, trace, IR.

    Built once and then damaged one way at a time, so each test isolates a
    single failure mode.
    """

    def __init__(self, tmp_path: Path) -> None:
        self.recording = f.recording(
            events=[
                f.event(
                    "evt_001", 0, at=0.0, etype="input", tgt=f.target("textbox", "Email address")
                ),
                f.event(
                    "evt_002",
                    1,
                    at=800.0,
                    tgt=f.target("button", "Place order", css="button.submit"),
                    diff=f.confirmation_diff(),
                    network=[f.network_call(status=201)],
                    after=f.snapshot(
                        root=f.node(
                            "0",
                            "main",
                            "Checkout",
                            children=[f.node("0.0", "button", "Place order")],
                        ),
                        live=[f.node("live.0", "alert", CONFIRMATION)],
                    ),
                ),
            ],
            objective="verify the order confirmation",
        )
        self.segments = segment_recording(self.recording, run_id="run_test")
        self.store = EvidenceStore(recording=self.recording, segments=self.segments)
        self.storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
        self.run = self.storage.run(self.recording.id, "run_test")
        self.runner = ToolRunner(
            store=self.store, storage=self.storage, run=self.run, stage=PipelineStage.name
        )

        # A real retrieval, of the kind the naming stage will make.
        self.call_id, _ = self.runner.call("find_text", {"query": CONFIRMATION}, step_id="step_002")

        self.ir = self._ir()

    def _ir(self) -> IRDocument:
        assertion = f.assertion(
            "asrt_001",
            "the confirmation banner appears",
            ev=f.evidence(CONFIRMATION, self.call_id, "evt_002", "semantic_node"),
        )
        steps = [
            f.step(
                "step_001",
                "the tester enters their email address",
                event_ids=["evt_001"],
                assertions=[],
            ),
            f.step(
                "step_002",
                "the tester places the order",
                event_ids=["evt_002"],
                assertions=[assertion],
            ),
        ]
        return f.ir_document(
            test_cases=[f.test_case(steps=steps, recording_id=self.recording.id)],
            recording_id=self.recording.id,
        )

    def trace(self) -> AgentTrace:
        return AgentTrace(
            schemaVersion="1.0",
            runId="run_test",
            recordingId=self.recording.id,
            projectId="proj_test",
            ownerId="owner_test",
            createdAt=datetime.now(UTC),
            config=RunConfig(
                ablation="A2", toolsEnabled=True, criticEnabled=False, repairEnabled=False
            ),
            toolCalls=self.runner.calls,
            modelCalls=[],
            investigations=[],
            stages=[],
            validatorResults=[],
            repairAttempts=[],
            decompositionDecisions=[],
        )

    def ctx(self, *, rendered: dict[str, str] | None = None) -> ValidationContext:
        return ValidationContext(
            recording=self.recording,
            ir=self.ir,
            trace=self.trace(),
            storage=self.storage,
            run=self.run,
            segments=self.segments,
            rendered=rendered or {},
        )

    # convenience -----------------------------------------------------------

    @property
    def assertion(self):
        return self.ir.testCases[0].steps[1].assertions[0]

    @property
    def step(self):
        return self.ir.testCases[0].steps[1]


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def failures_for(report, name: ValidatorName):
    return [r for r in report.by_validator(name) if r.status == ValidatorStatus.fail]


# --------------------------------------------------------------------------
# the honest baseline
# --------------------------------------------------------------------------


def test_an_honest_run_passes_the_whole_gate(h: Harness):
    report = validate(h.ctx())
    assert report.ok, report.summary()
    assert not report.rejected
    assert not report.hard_failed
    assert grounding_rate(h.ctx(), report) == 1.0


def test_every_validator_reports_something(h: Harness):
    # Including the ones with nothing to check: "no subject" and "never ran"
    # must stay distinguishable, or the gate's coverage is unknowable.
    report = validate(h.ctx())
    reported = {r.validator for r in report.results}
    assert reported == set(ValidatorName)


# --------------------------------------------------------------------------
# evidence_retrieved -- the milestone's done-when
# --------------------------------------------------------------------------


def test_an_assertion_pointing_at_a_nonexistent_tool_call_is_rejected(h: Harness):
    h.assertion.evidence.toolCallId = "tc_9999"
    report = validate(h.ctx())

    assert report.rejected
    fails = failures_for(report, ValidatorName.evidence_retrieved)
    assert len(fails) == 1
    assert "tc_9999" in fails[0].message
    assert "did not retrieve" in fails[0].message
    assert fails[0].assertionId == "asrt_001"


def test_a_fabricated_literal_is_rejected(h: Harness):
    # The retrieval really happened; the claim about it did not.
    h.assertion.evidence.literal = "Payment declined"
    report = validate(h.ctx())

    assert report.rejected
    fails = failures_for(report, ValidatorName.evidence_retrieved)
    assert "Payment declined" in fails[0].message
    assert "does not say this" in fails[0].message


def test_a_tampered_response_is_rejected(h: Harness):
    # The stored evidence no longer hashes to what the trace recorded, so it
    # was altered after the fact.
    path = h.run.tool_response(h.call_id)
    path.write_text(
        json.dumps({"query": CONFIRMATION, "count": 99, "matches": []}), encoding="utf-8"
    )
    report = validate(h.ctx())

    assert report.rejected
    fails = failures_for(report, ValidatorName.evidence_retrieved)
    assert "hash does not verify" in fails[0].message


def test_disabling_tools_makes_every_assertion_inadmissible(h: Harness):
    """SS3.2: disable tools and the pipeline cannot emit a single valid
    assertion -- not "degrades", cannot. This is that claim, as a test."""
    trace = h.trace()
    trace.toolCalls = []
    ctx = ValidationContext(
        recording=h.recording,
        ir=h.ir,
        trace=trace,
        storage=h.storage,
        run=h.run,
        segments=h.segments,
    )
    report = validate(ctx)
    assert report.rejected
    assert grounding_rate(ctx, report) == 0.0


def test_grounding_rate_counts_only_the_ungrounded(h: Harness):
    good = h.assertion.model_copy(deep=True)
    bad = h.assertion.model_copy(deep=True)
    bad.id = "asrt_002"
    bad.evidence.toolCallId = "tc_9999"
    h.step.assertions = [good, bad]

    ctx = h.ctx()
    assert grounding_rate(ctx, validate(ctx)) == 0.5


# --------------------------------------------------------------------------
# assertion_grounding and element_exists
# --------------------------------------------------------------------------


def test_a_literal_cited_at_the_wrong_event_is_rejected(h: Harness):
    h.assertion.evidence.eventId = "evt_001"
    report = validate(h.ctx())

    fails = failures_for(report, ValidatorName.assertion_grounding)
    assert fails
    assert "evt_001" in fails[0].message
    # The message names where the string really is, so the repair loop has
    # something to act on.
    assert "evt_002" in fails[0].message


def test_a_reference_to_an_event_that_does_not_exist_is_rejected(h: Harness):
    h.step.eventIds = ["evt_404"]
    report = validate(h.ctx())

    assert failures_for(report, ValidatorName.element_exists)
    assert report.rejected


# --------------------------------------------------------------------------
# mutation_claimed
# --------------------------------------------------------------------------


def test_a_save_claim_without_a_successful_mutation_is_rejected(h: Harness):
    # The step says data changed; the recording shows no successful POST.
    h.ir.testCases[0].steps[0].text = "the tester saves the customer record"
    report = validate(h.ctx())

    fails = failures_for(report, ValidatorName.mutation_claimed)
    assert fails
    assert "no successful mutating request" in fails[0].message


def test_a_save_claim_backed_by_a_real_mutation_passes(h: Harness):
    h.step.text = "the tester submits the order"
    report = validate(h.ctx())
    assert not failures_for(report, ValidatorName.mutation_claimed)


def test_incomplete_network_capture_downgrades_the_rejection_to_a_warning(h: Harness):
    # SS6.4 -- requests before injection and from service workers are missed.
    # Rejecting a true claim because the evidence was unobtainable would be the
    # wrong failure.
    h.recording.events[0].fidelity = [FidelityFlag.network_incomplete]
    h.ir.testCases[0].steps[0].text = "the tester saves the customer record"
    report = validate(h.ctx())

    assert not failures_for(report, ValidatorName.mutation_claimed)
    warns = [
        r
        for r in report.by_validator(ValidatorName.mutation_claimed)
        if r.status == ValidatorStatus.warn
    ]
    assert warns
    assert not report.rejected


def test_a_step_that_merely_navigates_is_not_treated_as_a_mutation(h: Harness):
    h.ir.testCases[0].steps[0].text = "the tester opens the order form"
    report = validate(h.ctx())
    assert not failures_for(report, ValidatorName.mutation_claimed)


# --------------------------------------------------------------------------
# event_coverage
# --------------------------------------------------------------------------


def test_a_silently_dropped_event_is_rejected(h: Harness):
    # An event in no step and no omitted segment is work the tester did that
    # the output pretends never happened.
    h.ir.testCases[0].steps = [h.step]
    report = validate(h.ctx())

    fails = failures_for(report, ValidatorName.event_coverage)
    assert fails
    assert "evt_001" in fails[0].message


def test_an_event_covered_by_a_precondition_counts_as_accounted_for(h: Harness):
    h.ir.testCases[0].steps = [h.step]
    h.ir.testCases[0].preconditions = [
        f.precondition("pre_001", "the tester is signed in", ["evt_001"])
    ]
    report = validate(h.ctx())
    assert not failures_for(report, ValidatorName.event_coverage)


# --------------------------------------------------------------------------
# no_placeholder_leak -- the only hard fail
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leak",
    [
        "the tester signs in as tester@example.com",
        "the header is Bearer abcdef0123456789xyz",
        "the card 4539578763621486 is accepted",
        "the key sk_live_abcdef0123456789 is used",
    ],
)
def test_a_leaked_secret_is_a_hard_failure(h: Harness, leak: str):
    h.step.text = leak
    report = validate(h.ctx())

    assert report.hard_failed
    assert not report.ok
    results = [
        r
        for r in report.by_validator(ValidatorName.no_placeholder_leak)
        if r.status == ValidatorStatus.fail
    ]
    assert results


def test_a_redaction_placeholder_is_not_a_leak(h: Harness):
    # The whole point of SS7.2: placeholders carry forward into the test as
    # parameters, so they must read as safe.
    h.step.text = 'the tester signs in as "<<user_email_1>>" with "<<password>>"'
    report = validate(h.ctx())
    assert not report.hard_failed


def test_a_leak_in_the_rendered_output_is_caught_too(h: Harness):
    report = validate(h.ctx(rendered={"tc_case_001": "Then the email tester@example.com appears"}))
    assert report.hard_failed


# --------------------------------------------------------------------------
# gherkin_parses
# --------------------------------------------------------------------------


def test_valid_gherkin_parses(h: Harness):
    feature = "Feature: Checkout\n\n  Scenario: Places an order\n    When the tester places the order\n    Then the confirmation banner appears\n"
    report = validate(h.ctx(rendered={"tc_case_001": feature}))
    assert not failures_for(report, ValidatorName.gherkin_parses)


def test_invalid_gherkin_is_rejected(h: Harness):
    report = validate(h.ctx(rendered={"tc_case_001": "Scenario: orphaned\n  When nothing\n"}))
    assert failures_for(report, ValidatorName.gherkin_parses)
    assert report.rejected


# --------------------------------------------------------------------------
# selector_resolvable and library_verbatim
# --------------------------------------------------------------------------


def test_an_unrecorded_selector_warns_rather_than_rejects(h: Harness):
    h.step.selectorHints = [f.selector_hint("css", "button.invented", "low")]
    report = validate(h.ctx())

    warns = [
        r
        for r in report.by_validator(ValidatorName.selector_resolvable)
        if r.status == ValidatorStatus.warn
    ]
    assert warns
    # Selectors live in comments and are a convenience for later automation,
    # so a stale one is a nuisance rather than a false claim.
    assert not report.rejected


def test_a_recorded_selector_passes(h: Harness):
    h.step.selectorHints = [f.selector_hint("css", "button.submit", "medium")]
    report = validate(h.ctx())
    assert not [
        r
        for r in report.by_validator(ValidatorName.selector_resolvable)
        if r.status == ValidatorStatus.warn
    ]


def test_a_reuse_claim_that_cannot_be_checked_is_rejected(h: Harness):
    # Phase 1 has no library, so a step claiming reuse is claiming something
    # unverifiable -- which is not admissible.
    h.step.libraryRef = "lib_001"
    report = validate(h.ctx())
    assert failures_for(report, ValidatorName.library_verbatim)
    assert report.rejected


# --------------------------------------------------------------------------
# against a real recording
# --------------------------------------------------------------------------


def test_the_gate_runs_over_a_real_recorded_session(tmp_path: Path):
    path = FIXTURES / "checkout.recording.json"
    if not path.exists():
        pytest.skip("run `pnpm e2e` to regenerate the recorded fixtures")

    recording = Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))
    segments = segment_recording(recording, run_id="run_real")
    store = EvidenceStore(recording=recording, segments=segments)
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    run = storage.run(recording.id, "run_real")
    runner = ToolRunner(store=store, storage=storage, run=run, stage=PipelineStage.name)

    call_id, response = runner.call("find_text", {"query": CONFIRMATION})
    assert response["count"], "the confirmation must be retrievable from the real recording"
    target_event = response["matches"][0]["eventId"]

    steps = [
        f.step(
            f"step_{i:03d}",
            f"the tester performs action {i}",
            event_ids=[event.id],
            assertions=(
                [
                    f.assertion(
                        "asrt_001",
                        "the confirmation banner appears",
                        ev=f.evidence(CONFIRMATION, call_id, target_event, "semantic_node"),
                    )
                ]
                if event.id == target_event
                else []
            ),
        )
        for i, event in enumerate(recording.events, start=1)
    ]
    ir = f.ir_document(
        test_cases=[f.test_case(steps=steps, recording_id=recording.id)],
        recording_id=recording.id,
    )

    ctx = ValidationContext(
        recording=recording,
        ir=ir,
        trace=AgentTrace(
            schemaVersion="1.0",
            runId="run_real",
            recordingId=recording.id,
            projectId=recording.projectId,
            ownerId=recording.ownerId,
            createdAt=datetime.now(UTC),
            config=RunConfig(
                ablation="A2", toolsEnabled=True, criticEnabled=False, repairEnabled=False
            ),
            toolCalls=runner.calls,
            modelCalls=[],
            investigations=[],
            stages=[],
            validatorResults=[],
            repairAttempts=[],
            decompositionDecisions=[],
        ),
        storage=storage,
        run=run,
        segments=segments,
    )

    report = validate(ctx)
    assert report.ok, report.summary()
    assert grounding_rate(ctx, report) == 1.0
