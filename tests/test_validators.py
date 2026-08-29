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
    IRDocument,
    PipelineStage,
    Recording,
    RedactionLevel,
    RunConfig,
    ValidatorAction,
    ValidatorName,
    ValidatorStatus,
)
from server.pipeline.segment import segment_recording
from server.pipeline.validators import (
    ValidationContext,
    grounding_rate,
    validate,
)
from server.pipeline.validators.output import no_placeholder_leak
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
            store=self.store, storage=self.storage, run=self.run, stage=PipelineStage.author
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
                ablation="A2", toolsEnabled=True, expectationsEnabled=True
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


# --------------------------------------------------------------------------
# mutation_claimed
# --------------------------------------------------------------------------


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
    runner = ToolRunner(store=store, storage=storage, run=run, stage=PipelineStage.author)

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
                ablation="A2", toolsEnabled=True, expectationsEnabled=True
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


# --------------------------------------------------------------------------
# what redaction was actually in force
# --------------------------------------------------------------------------


def _context(recording, ir, storage, run_paths) -> ValidationContext:
    return ValidationContext(
        recording=recording,
        ir=ir,
        trace=AgentTrace(
            schemaVersion="1.0",
            runId="run_test",
            recordingId=recording.id,
            projectId="proj_test",
            ownerId="owner_test",
            createdAt=datetime.now(UTC),
            config=RunConfig(ablation="A2", toolsEnabled=True, expectationsEnabled=True),
            toolCalls=[],
            modelCalls=[],
            investigations=[],
            stages=[],
            validatorResults=[],
            repairAttempts=[],
            decompositionDecisions=[],
        ),
        storage=storage,
        run=run_paths,
    )


@pytest.fixture
def storage(tmp_path):
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


@pytest.fixture
def run_paths(storage):
    return storage.run("rec_test01", "run_test")


def _leaky(level=None):
    """A run whose output carries something secret-shaped, at a given level."""
    recording = f.recording()
    if level is not None:
        recording.metadata.redaction = level
    step = f.step(text="the tester signs in as ada@example.com", assertions=[])
    ir = f.ir_document(test_cases=[f.test_case(steps=[step])])
    return recording, ir


def test_a_leak_is_fatal_by_default(storage, run_paths):
    """SS7's promise: raw secrets never exist in a persisted artifact.

    The only `hard_fail` in the gate. It does not reject the claim, it refuses
    to write the file at all -- a tool that breaks this promise once has broken
    it permanently.
    """
    recording, ir = _leaky()
    ctx = _context(recording, ir, storage, run_paths)

    results = list(no_placeholder_leak(ctx))
    assert results[0].status == ValidatorStatus.fail
    assert results[0].action == ValidatorAction.hard_fail


def test_a_leak_warns_when_the_tester_turned_redaction_down(storage, run_paths):
    """Not the validator being weakened, and the distinction matters.

    Weakening would mean loosening what counts as a leak. Nothing is loosened:
    the same scan runs, finds the same string and says the same thing. What
    changes is the consequence, and only for a recording whose own metadata
    records that a human deliberately turned the pattern scan off before
    recording. You cannot ask a tool for raw values and also ask it to refuse to
    write them down -- leaving this fatal would mean the setting existed and
    silently produced no output at all.
    """
    recording, ir = _leaky(RedactionLevel.secrets_only)
    ctx = _context(recording, ir, storage, run_paths)

    results = list(no_placeholder_leak(ctx))
    assert results[0].status == ValidatorStatus.warn
    assert results[0].action == ValidatorAction.none
    # And it says so in terms of what the reader now has to do about the files.
    assert "secrets_only" in (results[0].message or "")
    assert ".env" in (results[0].message or "")


def test_a_recording_with_no_level_recorded_is_treated_as_fully_redacted(storage, run_paths):
    # Every recording made before the setting existed. Defaulting the other way
    # would silently downgrade the whole corpus.
    recording, ir = _leaky()
    assert getattr(recording.metadata, "redaction", None) is None
    ctx = _context(recording, ir, storage, run_paths)
    assert list(no_placeholder_leak(ctx))[0].action == ValidatorAction.hard_fail


def test_an_unredacted_recording_is_refused_unless_the_endpoint_is_paid():
    """The one case the pre-send gate refuses on rather than warns about.

    `origin_policy` is normally a warning, deliberately: a tester pointing this
    at a real site is not doing anything wrong and needs to know what it costs
    rather than to be stopped. An unredacted recording is different in kind.
    Free-tier prompts may be used for training and read by human reviewers, and
    the values in this one are real credentials somebody typed -- the one
    mistake that cannot be taken back, decided in the recorder possibly days
    earlier and possibly by somebody else.

    `origin_policy: off` is exactly the assertion "this endpoint is paid and
    carries a no-training term", which is the only condition under which it is
    anybody's business but the tool's.
    """
    from server.cli import check_origins

    recording = f.recording()
    recording.metadata.redaction = RedactionLevel.off

    for policy in ("warn", "allowlist"):
        with pytest.raises(SystemExit) as refused:
            check_origins(recording, allow=True, policy=policy)
        assert "redaction" in str(refused.value)

    # And it goes through where the endpoint is declared safe.
    check_origins(recording, allow=False, policy="off")


def test_a_fully_redacted_recording_still_only_warns():
    from server.cli import check_origins

    recording = f.recording(origins=["https://not-on-the-allowlist.example"])
    check_origins(recording, allow=False, policy="warn")
