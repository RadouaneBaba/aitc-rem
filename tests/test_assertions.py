"""Assertion proposal (`server/pipeline/assertions.py`) -- SS9.5.

A recording captures what the tester did, never what they were checking. The
ranking is what closes that gap, and the spec is unusually emphatic about it:

    "Systems that lead with inference produce assertions that are true but
     pointless -- 'a timestamp appeared' -- because nothing tells them which of
     forty state changes is the one under test."

So these tests are about which candidate wins and which never gets made at all.
Whether a citation is *real* is the validator's job, tested in
`test_validators.py` -- a fabricated one has to survive this stage to be
counted by the ablation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm import ScriptedModelClient, answer
from server.models import Confidence, PipelineStage, Provenance, SegmentRole, StepInvestigation
from server.pipeline.assertions import MAX_CANDIDATES, _baseline, propose_assertions
from server.pipeline.name import NamedStep, NamingResult
from server.pipeline.segment import segment_recording
from server.storage.paths import Storage
from tests import factories as f

CONFIRMATION = "Order confirmed"


def candidate(**kw) -> dict:
    return {
        "text": kw.get("text", "the order confirmation appears"),
        "provenance": kw.get("provenance", "inferred"),
        "literal": kw.get("literal", CONFIRMATION),
        "toolCallId": kw.get("tool_call_id", "tc_0001"),
        "eventId": kw.get("event_id", "evt_002"),
        "kind": "semantic_node",
    }


def recording():
    return f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, etype="input", tgt=f.target("textbox", "Purchase order")),
            f.event(
                "evt_002",
                1,
                at=3000.0,
                tgt=f.target("button", "Place order"),
                diff=f.confirmation_diff(),
                network=[f.network_call(status=201)],
                after=f.snapshot(live=[f.node("live.0", "alert", CONFIRMATION)]),
                annotations=[
                    f.annotation(
                        "ann_1",
                        "assertion",
                        at=3000.0,
                        name=CONFIRMATION,
                        event_id="evt_002",
                    )
                ],
            ),
        ],
        objective="Check that an order over EUR500 requires approval",
    )


def unannotated():
    """The same recording with nothing marked, for the demotion tests."""
    rec = recording()
    for event in rec.events:
        event.annotations = None
    return rec


@pytest.fixture
def harness(tmp_path: Path):
    return _harness(tmp_path, recording())


def _harness(tmp_path: Path, rec):
    segments = segment_recording(rec, run_id="run_001")
    store = EvidenceStore(recording=rec, segments=segments)
    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    runner = ToolRunner(
        store=store,
        storage=storage,
        run=storage.run(rec.id, "run_001"),
        stage=PipelineStage.assert_,
    )

    naming = NamingResult()
    for index, segment in enumerate(segments.segments):
        step_id = f"step_{index + 1:03d}"
        naming.steps.append(
            NamedStep(
                segment_id=segment.id,
                step_id=step_id,
                role=SegmentRole.test_step,
                text="the tester places the order",
                confidence=Confidence.high,
                event_ids=list(segment.eventIds),
                investigation=StepInvestigation(
                    id=f"inv_{step_id}",
                    stage=PipelineStage.name,
                    initialUncertainty=[],
                    toolCallIds=[],
                    budgetUsed=0,
                    budgetMax=8,
                    stopReason="no_investigation_needed",
                ),
            )
        )
    return store, runner, naming


def propose(harness, said: dict):
    store, runner, naming = harness
    model = ScriptedModelClient(lambda _r: answer(json.dumps(said)))
    return propose_assertions(store, runner, model, naming, model_name="scripted-1")


def first(result):
    return next(s for s in result.steps if s.candidates)


def investigated(result):
    """The step the stage actually asked the model about.

    Steps the recorder saw produce nothing are answered without a model call,
    so the interesting one is not always the first.
    """
    return next(s for s in result.steps if s.candidates or s.suppressed)


# --------------------------------------------------------------------------
# the ranking
# --------------------------------------------------------------------------


def test_provenance_decides_which_candidate_is_accepted(harness):
    # This ordering is the whole point of the stage. An inferred assertion can
    # be perfectly true and still be about the wrong thing; the tester marking
    # an element is them saying which thing matters.
    result = propose(
        harness,
        {
            "candidates": [
                candidate(text="a timestamp updated", provenance="inferred"),
                candidate(text="the confirmation banner appears", provenance="annotated"),
            ]
        },
    )
    step = first(result)

    assert step.candidates[0].provenance == Provenance.annotated
    assert step.candidates[0].accepted
    assert step.candidates[0].rank == 1
    # The weaker candidate is kept and proposed, not deleted: the review UI
    # turns it into a checkbox rather than a decision made for the tester.
    assert step.candidates[1].provenance == Provenance.inferred
    assert not step.candidates[1].accepted


def test_the_models_own_order_breaks_a_tie(harness):
    result = propose(
        harness,
        {
            "candidates": [
                candidate(text="the order reference is shown", provenance="inferred"),
                candidate(text="the confirmation banner appears", provenance="inferred"),
            ]
        },
    )
    assert first(result).candidates[0].text == "the order reference is shown"


def test_an_unknown_provenance_is_treated_as_inference(harness):
    # Claiming a tester pointed at something when the field was unreadable
    # would launder a guess into a statement of intent, which is the one
    # direction this ranking must not slip.
    result = propose(harness, {"candidates": [candidate(provenance="definitely-true")]})
    assert first(result).candidates[0].provenance == Provenance.inferred


def test_no_more_than_three_candidates_survive(harness):
    result = propose(
        harness,
        {"candidates": [candidate(text=f"outcome {i}") for i in range(6)]},
    )
    assert len(first(result).candidates) == MAX_CANDIDATES


# --------------------------------------------------------------------------
# noise (SS9.5, hard-excluded)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "literal,why",
    [
        ("Placed at 14:03", "a timestamp"),
        ("2 minutes ago", "a relative time"),
        ("2026-08-18", "a date"),
        ("f47ac10b-58cc-4372-a567-0e02b2c3d479", "a uuid"),
        ("a3f9c2e18b7d4a6f0192", "a generated identifier"),
        ("<<user_email_1>>", "a redaction placeholder"),
    ],
)
def test_a_value_that_will_differ_next_run_is_never_asserted(harness, literal, why):
    # These pass every grounding check and still break the moment somebody runs
    # the test, which is why the filter is code rather than a line in a prompt.
    result = propose(harness, {"candidates": [candidate(literal=literal)]})
    step = investigated(result)

    assert step.candidates == []
    assert any(why in reason for reason in step.suppressed)


def test_suppression_is_recorded_rather_than_silent(harness):
    # A tester who sees nothing cannot tell "found nothing" from "threw
    # something away". The narrative says which.
    result = propose(
        harness,
        {"candidates": [candidate(literal="Placed at 14:03"), candidate(literal=CONFIRMATION)]},
    )
    step = first(result)

    assert len(step.candidates) == 1
    assert step.suppressed
    assert any("suppressed as noise" in line for line in step.investigation.narrative)


# --------------------------------------------------------------------------
# abstaining
# --------------------------------------------------------------------------


def test_a_step_with_no_outcome_proposes_nothing(harness):
    # Most steps in a test case are like this. An omitted assertion is the
    # right answer, not a failure.
    result = propose(harness, {"candidates": []})
    assert all(s.candidates == [] for s in result.steps)


def test_a_candidate_missing_its_citation_is_dropped(harness):
    # SS3.2 -- without a retrieval to point at there is no claim, so there is
    # nothing to emit.
    result = propose(
        harness,
        {
            "candidates": [
                {"text": "the banner appears", "literal": CONFIRMATION},
                {"text": "the banner appears", "toolCallId": "tc_0001"},
                candidate(),
            ]
        },
    )
    step = first(result)
    assert len(step.candidates) == 1
    assert step.candidates[0].evidence.toolCallId == "tc_0001"


def test_an_unusable_answer_costs_the_step_its_assertions_and_nothing_else(harness):
    result = propose(harness, {"nonsense": True})
    assert all(s.candidates == [] for s in result.steps)
    assert all(s.investigation is not None for s in result.steps)


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------


def test_every_step_records_an_investigation(harness):
    # SS3.4 reads effort per step. A step the stage declined to assert about
    # still cost a decision, and a missing record would read as zero effort.
    _store, _runner, naming = harness
    result = propose(harness, {"candidates": []})

    assert len(result.investigations) == len(naming.steps)
    assert all(i.stage == PipelineStage.assert_ for i in result.investigations)


def test_the_artifact_shows_what_was_proposed_and_what_was_thrown_away(harness):
    result = propose(
        harness,
        {"candidates": [candidate(), candidate(text="a timestamp appeared", literal="at 14:03")]},
    )
    artifact = result.to_artifact()

    assert artifact["stage"] == "assert"
    step = next(s for s in artifact["steps"] if s["candidates"])
    assert step["candidates"][0]["accepted"] is True
    assert step["suppressedAsNoise"]


# --------------------------------------------------------------------------
# reaching the top of the ranking
# --------------------------------------------------------------------------


def prompt_for(rec) -> str:
    """The user turn the stage sends for the first step."""
    segments = segment_recording(rec, run_id="run_001")
    store = EvidenceStore(recording=rec, segments=segments)
    named = NamedStep(
        segment_id=segments.segments[0].id,
        step_id="step_001",
        role=SegmentRole.test_step,
        text="the tester places the order",
        confidence=Confidence.high,
        event_ids=list(segments.segments[0].eventIds),
        investigation=StepInvestigation(
            id="inv_001",
            stage=PipelineStage.name,
            initialUncertainty=[],
            toolCallIds=[],
            budgetUsed=0,
            budgetMax=8,
            stopReason="no_investigation_needed",
        ),
    )
    return _baseline(store, named, segments.segments[0])


def test_an_annotation_is_announced_but_not_pre_loaded():
    # SS6.6 -- the agent retrieves when a step is ambiguous and pays nothing
    # when it is not. But it can only choose to retrieve something it has been
    # told exists, so the prompt names the signal and withholds the content.
    marked = f.annotation("ann_1", "assertion", at=3000.0, text="the confirmation banner")
    rec = f.recording(
        events=[f.event("evt_001", 0, at=3000.0, annotations=[marked])],
        objective="Check the order confirms",
    )
    text = prompt_for(rec)

    assert "ANNOTATED" in text
    assert "get_events" in text
    assert "the confirmation banner" not in text, "the content must be retrieved, not handed over"


def test_a_step_with_no_signal_is_told_it_is_on_its_own():
    # Everything it proposes here is inference, and the prompt says so -- an
    # inferred assertion that is true but incidental is worse than none.
    rec = f.recording(events=[f.event("evt_001", 0)], objective=None)
    text = prompt_for(rec)

    assert "none -- anything you propose here is inferred" in text
    assert "ANNOTATED" not in text


# --------------------------------------------------------------------------
# what the stage declines to spend
# --------------------------------------------------------------------------


def test_a_step_the_recorder_saw_produce_nothing_costs_no_model_call(harness):
    # This stage otherwise costs one call per step, and on a forty-step
    # recording that is the difference between a run that fits a free-tier
    # daily quota and one that does not. A step with no diff, no request and no
    # annotation cannot have an expected result, so asking could only produce
    # an invention.
    store, runner, naming = harness
    model = ScriptedModelClient(lambda _r: answer(json.dumps({"candidates": [candidate()]})))

    result = propose_assertions(store, runner, model, naming, model_name="scripted-1")

    assert len(result.steps) == len(naming.steps)
    assert len(model.requests) < len(naming.steps), "every step was sent to the model"


def test_a_skipped_step_is_still_recorded(harness):
    # SS3.4 reads effort per step. A step with no record would read as zero
    # effort rather than as a decision that cost nothing, and those are
    # different things.
    result = propose(harness, {"candidates": []})
    quiet = next(s for s in result.steps if not s.candidates and not s.suppressed)

    assert quiet.investigation is not None
    assert quiet.investigation.stopReason.value == "no_investigation_needed"
    assert any("nothing a tester could check" in line for line in quiet.investigation.narrative)


# --------------------------------------------------------------------------
# provenance is verified, not taken on trust
# --------------------------------------------------------------------------


def test_a_claim_of_annotated_with_no_annotation_is_demoted(tmp_path: Path):
    # The ladder decides which candidate is accepted, so a claim ABOUT where a
    # claim came from is load-bearing -- and it was the one thing in the system
    # nobody checked. `annotated` outranks everything and costs a model nothing
    # but the word, which is exactly the shape of an unverified claim this
    # project exists to refuse.
    #
    # Verified in code rather than asked for in the prompt, for the same reason
    # noise suppression is: a rule the model is only told about holds most of
    # the time, and most of the time is not a gate.
    harness = _harness(tmp_path, unannotated())
    result = propose(
        harness,
        {
            "candidates": [
                candidate(text="the confirmation banner appears", provenance="annotated"),
            ]
        },
    )
    assert first(result).candidates[0].provenance == Provenance.inferred


def test_a_claim_of_narrated_with_no_narration_is_demoted(tmp_path: Path):
    harness = _harness(tmp_path, unannotated())
    result = propose(
        harness,
        {"candidates": [candidate(text="the banner appears", provenance="narrated")]},
    )
    assert first(result).candidates[0].provenance == Provenance.inferred


def test_objective_survives_because_this_recording_has_one(tmp_path: Path):
    # The check demotes what the evidence does not support; it must not demote
    # what it does. A stated objective is right there in the recording.
    harness = _harness(tmp_path, unannotated())
    result = propose(
        harness,
        {"candidates": [candidate(text="the order needs approval", provenance="objective")]},
    )
    assert first(result).candidates[0].provenance == Provenance.objective


def test_an_annotation_the_tester_really_made_still_outranks_inference(tmp_path: Path):
    # The other half: verification must not quietly flatten the ladder into
    # "everything is inferred", or SS9.5 stops doing anything at all.
    harness = _harness(tmp_path, recording())
    result = propose(
        harness,
        {
            "candidates": [
                candidate(text="a timestamp updated", provenance="inferred"),
                candidate(text="the confirmation banner appears", provenance="annotated"),
            ]
        },
    )
    step = first(result)
    assert step.candidates[0].provenance == Provenance.annotated
    assert step.candidates[0].accepted


def test_a_guess_about_a_precondition_is_proposed_but_not_accepted(tmp_path: Path):
    # "the catalog page is displayed", under a Given that signs the tester in,
    # in a test about the EUR500 approval rule. True, grounded, and beside the
    # point -- and this stage's own prompt says such an assertion is worse than
    # none, because somebody has to read it and decide it was pointless.
    #
    # Proposed rather than dropped: it stays in the sidecar with its evidence
    # intact, the reviewer can accept it, and the ablation still counts it. What
    # it does not do is put a Then under a Given on nobody's authority.
    harness = _harness(tmp_path, unannotated())
    store, runner, naming = harness
    for step in naming.steps:
        step.role = SegmentRole.setup

    result = propose(harness, {"candidates": [candidate(text="the catalog page is displayed")]})
    step = first(result)
    assert step.candidates[0].provenance == Provenance.inferred
    assert not step.candidates[0].accepted
    # Nothing was thrown away.
    assert step.candidates[0].evidence.literal == CONFIRMATION


def test_a_marked_precondition_is_still_accepted(tmp_path: Path):
    # The other half. If the tester pointed at it, they are saying the
    # precondition IS what they were checking, and that outranks our guess about
    # what preconditions are for.
    harness = _harness(tmp_path, recording())
    store, runner, naming = harness
    for step in naming.steps:
        step.role = SegmentRole.setup

    result = propose(
        harness,
        {"candidates": [candidate(text="the confirmation appears", provenance="annotated")]},
    )
    step = first(result)
    assert step.candidates[0].provenance == Provenance.annotated
    assert step.candidates[0].accepted
