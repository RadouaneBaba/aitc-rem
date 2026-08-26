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


def skipped_for(report, name: ValidatorName):
    """A skip and a pass are different facts, and the gate keeps them apart.

    "This had no subject" and "this was never run" have to stay
    distinguishable, or the gate's coverage is unknowable.
    """
    return [r for r in report.by_validator(name) if r.status == ValidatorStatus.skip]


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
    # The step says data CHANGED; the recording shows no successful POST.
    #
    # "and it is saved" rather than "saves", and the difference is the whole
    # rule: a step's text says what the TESTER did, an expected result says
    # what the APPLICATION did, and only the second is a claim about state.
    h.ir.testCases[0].steps[0].text = "the tester submits the record and it is saved"
    report = validate(h.ctx())

    fails = failures_for(report, ValidatorName.mutation_claimed)
    assert fails
    assert "no successful mutating request" in fails[0].message


def test_a_step_describing_an_action_is_not_a_claim_about_the_application(h: Harness):
    # "the tester saves the payment method" describes pressing a button. Read
    # as a claim that something persisted, it fails a validator that NO rewrite
    # can satisfy -- every honest verb for that action is a mutation word. On a
    # real fixture the repair loop spent its whole budget making the sentence
    # worse, hedging it to "attempts to save" and then to "clicks Save", which
    # is exactly the mechanics language SS11.1 exists to keep out.
    #
    # The claim, when there is one, lives in the expected result.
    h.ir.testCases[0].steps[0].text = "the tester saves the customer record"
    h.ir.testCases[0].steps[0].assertions = []
    report = validate(h.ctx())
    assert not failures_for(report, ValidatorName.mutation_claimed)


def test_an_expected_result_claiming_a_change_still_has_to_prove_it(h: Harness):
    # The other half, and the one that keeps this validator worth having. An
    # expected result is a claim about the application by definition, so any
    # mutation word in one counts.
    step = h.ir.testCases[0].steps[0]
    step.text = "the tester fills in the customer form"
    step.assertions = [f.assertion("a1", "the customer record is saved")]
    report = validate(h.ctx())
    assert failures_for(report, ValidatorName.mutation_claimed)


def test_a_save_claim_backed_by_a_real_mutation_passes(h: Harness):
    h.step.text = "the tester submits the order"
    report = validate(h.ctx())
    assert not failures_for(report, ValidatorName.mutation_claimed)


def test_incomplete_network_capture_downgrades_the_rejection_to_a_warning(h: Harness):
    # SS6.4 -- requests before injection and from service workers are missed.
    # Rejecting a true claim because the evidence was unobtainable would be the
    # wrong failure.
    h.recording.events[0].fidelity = [FidelityFlag.network_incomplete]
    h.ir.testCases[0].steps[0].text = "the tester submits the record and it is saved"
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


def test_a_claim_about_what_the_page_says_is_not_a_claim_that_it_persisted(h: Harness):
    # A deadlock, not a loosening, and the deadlock is what proves it.
    #
    # `hardpaths` shows a status message reading "Payment method saved".
    # `bind._unwitnessed` requires a claim to quote the value it rests on, so
    # every admissible sentence about that message contains the word "saved" --
    # and the one sentence that does not, "a confirmation appears", is refused
    # by `bind._existence_only`. Between the two rules nothing could be said,
    # and the run was rejected for a claim that was true, grounded and about
    # the screen.
    # evt_001 carries no network at all, so a persistence claim on this step
    # cannot be proved and the rejection would be unavoidable.
    h.ir.testCases[0].steps[0].assertions = [
        f.assertion(
            "asrt_display",
            'the status message reads "Payment method saved"',
            ev=f.evidence("Payment method saved", h.call_id, "evt_001", "semantic_node"),
        )
    ]
    assert not failures_for(validate(h.ctx()), ValidatorName.mutation_claimed)


def test_the_display_verb_must_come_first_or_it_is_still_a_persistence_claim(h: Harness):
    # The negative case, and the whole reason the rule is about ORDER rather
    # than about the presence of a display verb. "the order is placed and a
    # confirmation is shown" asserts persistence in its first clause and must
    # still prove a successful request.
    h.ir.testCases[0].steps[0].assertions = [
        f.assertion(
            "asrt_persist",
            "the order is placed and a confirmation is shown",
            ev=f.evidence("Order confirmed", h.call_id, "evt_001", "semantic_node"),
        )
    ]

    fails = failures_for(validate(h.ctx()), ValidatorName.mutation_claimed)
    assert fails
    assert "changed something" in fails[0].message


def test_one_literal_may_not_be_the_whole_evidence_for_two_different_claims(h: Harness):
    # Grounding proves a claim points at a retrieval. It cannot prove the
    # retrieval is ABOUT that claim rather than the one next to it.
    #
    # Found on a real recording, thirteen validators green: two claims -- "the
    # product list is filtered to show only available items" and "the product
    # list updates to show items matching the selected processors" -- both
    # resting on "Results updated.", an aria-live region announcing that
    # something changed. Genuinely retrieved, and it tells them apart from
    # nothing. `_unwitnessed` cannot see it: neither claim quotes a value or
    # contains a digit, so there is no checkable content to compare.
    step = h.ir.testCases[0].steps[1]
    step.assertions = [
        f.assertion(
            "asrt_a",
            "the list shows only available items",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
        f.assertion(
            "asrt_b",
            "the list shows items matching the selected processors",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
    ]

    warnings = [
        r
        for r in validate(h.ctx()).results
        if r.validator == ValidatorName.evidence_discriminates and r.status == ValidatorStatus.warn
    ]
    assert warnings
    assert CONFIRMATION in (warnings[0].message or "")
    assert "available items" in (warnings[0].message or "")


def test_two_claims_may_share_a_literal_when_they_say_the_same_thing(h: Harness):
    # The negative case. A reviewer rewording one claim into the other's
    # sentence is a duplicate, not a discrimination failure, and this check must
    # not double up on `merge_repeats`.
    step = h.ir.testCases[0].steps[1]
    step.assertions = [
        f.assertion(
            "asrt_a",
            "the confirmation banner appears",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
        f.assertion(
            "asrt_b",
            "the confirmation banner appears",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
    ]
    assert not failures_for(validate(h.ctx()), ValidatorName.evidence_discriminates)
    assert not [
        r
        for r in validate(h.ctx()).results
        if r.validator == ValidatorName.evidence_discriminates and r.status == ValidatorStatus.warn
    ]


def test_a_rejected_claim_does_not_count_against_the_evidence_it_used(h: Harness):
    # Only what SHIPS can mislead a reader.
    step = h.ir.testCases[0].steps[1]
    step.assertions = [
        f.assertion(
            "asrt_a",
            "the list shows only available items",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
        f.assertion(
            "asrt_b",
            "something else entirely",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
            accepted=False,
        ),
    ]
    assert not [
        r
        for r in validate(h.ctx()).results
        if r.validator == ValidatorName.evidence_discriminates and r.status == ValidatorStatus.warn
    ]


def test_this_finding_never_rejects_a_run(h: Harness):
    # It says two claims cannot both be right about this evidence; it cannot say
    # WHICH. On `twoflows` one of the two was a good claim and the other
    # restated the scenario name -- rejecting would have punished both.
    step = h.ir.testCases[0].steps[1]
    step.assertions = [
        f.assertion(
            "asrt_a",
            "the list shows only available items",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
        f.assertion(
            "asrt_b",
            "the list shows the selected processors",
            ev=f.evidence(CONFIRMATION, h.call_id, "evt_002", "semantic_node"),
        ),
    ]
    assert not failures_for(validate(h.ctx()), ValidatorName.evidence_discriminates)


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


def test_an_event_claimed_by_two_steps_is_rejected(h: Harness):
    # The drafting prompt says every event id appears EXACTLY ONCE, and this is
    # the net that makes the drafter's freedom over step boundaries safe. It
    # unioned into a set, so it only ever asked "at least once": a drafter that
    # assigned one event to two steps passed the gate and shipped two steps
    # describing the same action.
    h.ir.testCases[0].steps[0].eventIds = ["evt_001", "evt_002"]

    fails = failures_for(validate(h.ctx()), ValidatorName.event_coverage)

    assert fails
    assert "evt_002" in fails[0].message
    assert "step_001" in fails[0].message and "step_002" in fails[0].message


def test_a_bug_report_may_retrace_the_events_the_test_case_already_covers(h: Harness):
    # SS14.2. A bug report is a second DOCUMENT about one recording, not a
    # second claim on the same events: its repro steps are the test case's
    # steps seen from the developer's side, so they carry the same event ids by
    # construction.
    #
    # Found by the fix above, on the fixture built to contain a 500: counting
    # rather than unioning turned `bugged` into a rejection where nothing was
    # wrong. The rule is "no event twice in a test case", not "no event twice
    # in the IR" -- the same distinction preconditions already needed.
    repro = f.test_case(
        "tc_bug_001",
        kind="bug_report",
        steps=[
            f.step("bug_step_001", "the tester signs in", event_ids=["evt_001"]),
            f.step("bug_step_002", "the tester submits the order", event_ids=["evt_002"]),
        ],
    )
    h.ir.testCases.append(repro)

    assert not failures_for(validate(h.ctx()), ValidatorName.event_coverage)


def test_two_steps_of_one_bug_report_still_may_not_share_an_event(h: Harness):
    # The exemption is for the report as a whole against the test case, not a
    # licence inside it: two repro steps describing one action is the same
    # defect wherever it appears.
    repro = f.test_case(
        "tc_bug_001",
        kind="bug_report",
        steps=[
            f.step("bug_step_001", "the tester signs in", event_ids=["evt_001"]),
            f.step("bug_step_002", "the tester signs in again", event_ids=["evt_001"]),
        ],
    )
    h.ir.testCases.append(repro)

    fails = failures_for(validate(h.ctx()), ValidatorName.event_coverage)
    assert fails
    assert "bug_step_001" in fails[0].message and "bug_step_002" in fails[0].message


# --------------------------------------------------------------------------
# no_pruned_assertion -- 0 pass, 13 skip before this
# --------------------------------------------------------------------------


def test_an_assertion_grounded_in_a_pruned_event_is_rejected(h: Harness):
    # The reader of the feature file cannot see a pruned event, so an assertion
    # citing one points at evidence that is not there. This resolved omissions
    # through `omitted.segmentId`, which draft-then-bind never sets, so it
    # returned early on every run ever made -- reporting "no subject" for a
    # recording that had just pruned an event.
    h.ir.testCases[0].steps = [h.step]
    h.ir.testCases[0].omitted = [f.omitted_segment(segment_id=None, reason="exploratory", count=1)]
    h.ir.testCases[0].omitted[0].eventIds = ["evt_002"]

    fails = failures_for(validate(h.ctx()), ValidatorName.no_pruned_assertion)

    assert fails
    assert "evt_002" in fails[0].message
    assert "exploratory" in fails[0].message


def test_an_omission_that_no_assertion_cites_passes(h: Harness):
    # The negative case. Pruning is normal -- SS9.3 expects it -- and this
    # validator is about assertions, not about omissions.
    h.ir.testCases[0].omitted = [f.omitted_segment(segment_id=None, reason="abandoned", count=1)]
    h.ir.testCases[0].omitted[0].eventIds = ["evt_003"]

    report = validate(h.ctx())

    assert not failures_for(report, ValidatorName.no_pruned_assertion)
    assert not skipped_for(report, ValidatorName.no_pruned_assertion), (
        "an omission is a subject: this must run rather than skip"
    )


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
