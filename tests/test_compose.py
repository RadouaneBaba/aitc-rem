"""Composition (`server/pipeline/compose.py`) -- SS9.3, one test case wide.

Naming sees one segment. Every question about the document as a whole -- what
capability is under test, what this particular run exercises, what each step is
doing in the narrative -- needs the whole flow in view, and nothing asked those
questions in Phase 1. The output said so: a `Feature:` and a `Scenario:` both
set to the objective string the tester typed into the popup.

These tests are about the two things that must hold whatever the model says:
the document names itself properly, and a model failure costs a plainer title
rather than the run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm import ScriptedModelClient, answer
from server.models import Confidence, PipelineStage, SegmentRole, StepInvestigation
from server.pipeline.compose import compose_test_case, fallback_composition
from server.pipeline.name import NamedStep, NamingResult
from server.pipeline.segment import segment_recording
from server.storage.paths import Storage
from tests import factories as f

COMPOSED = {
    "title": "Order approval",
    "scenario": "An order over EUR500 is held for manager approval",
    "description": "Orders above the EUR500 threshold need a manager to approve them.",
    "tags": ["Checkout", "@approval", "regression!"],
    "roles": {"step_001": "setup", "step_002": "test_step"},
    "rationale": {"step_001": "signing in is how the tester reaches checkout"},
}


def recording():
    return f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, etype="input", tgt=f.target("textbox", "Email address")),
            f.event(
                "evt_002",
                1,
                at=3000.0,
                tgt=f.target("button", "Place order"),
                diff=f.confirmation_diff(),
                network=[f.network_call(status=201)],
            ),
        ],
        objective="Check that an order over EUR500 requires approval",
    )


def naming_of(store) -> NamingResult:
    result = NamingResult()
    for index, segment in enumerate(store.segments.segments):
        step_id = f"step_{index + 1:03d}"
        result.steps.append(
            NamedStep(
                segment_id=segment.id,
                step_id=step_id,
                role=SegmentRole.test_step,
                text=f"the tester does thing {index + 1}",
                confidence=Confidence.high,
                event_ids=list(segment.eventIds),
                investigation=_stub(step_id, segment.id),
            )
        )
    return result


def _stub(step_id: str, segment_id: str) -> StepInvestigation:
    return StepInvestigation(
        id=f"inv_{step_id}",
        stepId=step_id,
        segmentId=segment_id,
        stage=PipelineStage.name,
        initialUncertainty=[],
        toolCallIds=[],
        budgetUsed=0,
        budgetMax=8,
        stopReason="no_investigation_needed",
    )


@pytest.fixture
def harness(tmp_path: Path):
    rec = recording()
    segments = segment_recording(rec, run_id="run_001")
    store = EvidenceStore(recording=rec, segments=segments)
    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    runner = ToolRunner(
        store=store,
        storage=storage,
        run=storage.run(rec.id, "run_001"),
        stage=PipelineStage.decompose,
    )
    return store, runner, naming_of(store)


def compose(harness, script):
    store, runner, naming = harness
    return compose_test_case(
        store, runner, ScriptedModelClient(script), naming, model_name="scripted-1"
    )


# --------------------------------------------------------------------------


def test_the_feature_is_named_after_the_capability_not_the_objective(harness):
    result = compose(harness, lambda _r: answer(json.dumps(COMPOSED)))

    assert result.title == "Order approval"
    assert result.scenario_name == "An order over EUR500 is held for manager approval"
    assert result.title != result.scenario_name
    assert not result.degraded


def test_a_feature_that_repeats_its_own_scenario_is_rejected(harness):
    # The exact defect this stage exists to fix. If the model produces it
    # anyway, the specific half is the one worth keeping.
    said = {**COMPOSED, "title": "An order over EUR500 is held for manager approval."}
    result = compose(harness, lambda _r: answer(json.dumps(said)))

    assert result.scenario_name == "An order over EUR500 is held for manager approval"
    assert result.title != result.scenario_name


def test_roles_decide_the_narrative_and_only_known_steps_are_accepted(harness):
    said = {**COMPOSED, "roles": {"step_001": "setup", "step_999": "teardown", "step_002": "nope"}}
    result = compose(harness, lambda _r: answer(json.dumps(said)))

    assert result.roles["step_001"] == SegmentRole.setup
    # An unknown id cannot silently introduce a step, and an unknown role
    # leaves whatever naming proposed rather than guessing.
    assert "step_999" not in result.roles
    assert result.roles["step_002"] == SegmentRole.test_step


def test_tags_are_normalised_into_something_a_filter_can_use(harness):
    result = compose(harness, lambda _r: answer(json.dumps(COMPOSED)))
    assert result.tags == ["checkout", "approval", "regression"]


def test_the_reasoning_behind_each_role_is_recorded(harness):
    # SS9.3 -- no deterministic rule tells a false start from a test step, so
    # the rationale is written down rather than asserted.
    result = compose(harness, lambda _r: answer(json.dumps(COMPOSED)))

    assert {d.segmentId for d in result.decisions} == set(result.roles)
    first = next(d for d in result.decisions if d.segmentId == "step_001")
    assert "reaches checkout" in first.rationale
    assert all(d.rationale for d in result.decisions)


def test_the_investigation_is_recorded_like_any_other(harness):
    result = compose(harness, lambda _r: answer(json.dumps(COMPOSED)))

    assert result.investigation is not None
    assert result.investigation.stage == PipelineStage.decompose
    # SS3.4 reads effort per investigation without caring which stage spent it.
    assert result.investigation.budgetUsed == len(result.investigation.toolCallIds)


# --------------------------------------------------------------------------
# degrading
# --------------------------------------------------------------------------


def test_an_unusable_answer_degrades_to_a_readable_document(harness):
    # Naming has already produced the expensive, evidence-bound part. Losing
    # that because composition failed would be the wrong trade by a wide
    # margin, so the fallback is plainer rather than absent.
    result = compose(harness, lambda _r: answer("not json at all"))

    assert result.degraded
    assert result.title
    assert result.scenario_name
    assert result.roles


def test_the_fallback_still_does_not_say_the_objective_twice(harness):
    store, _runner, naming = harness
    result = fallback_composition(store, naming)

    # The application's own page title is the closest thing to a capability
    # name that can be read straight off the recording; the objective is
    # already a sentence about this one run, which is what a Scenario is.
    assert result.title == "Checkout"
    assert result.scenario_name == "Check that an order over EUR500 requires approval"
    assert result.title != result.scenario_name


def test_a_recording_with_no_steps_is_not_composed(harness):
    store, runner, _naming = harness
    model = ScriptedModelClient([])

    result = compose_test_case(store, runner, model, NamingResult(), model_name="scripted-1")

    assert result.degraded
    assert model.requests == [], "an empty flow must not cost a model call"


# --------------------------------------------------------------------------
# decomposition (SS9.3)
# --------------------------------------------------------------------------


def cases_from(value, naming, store):
    from server.pipeline.compose import _cases

    return _cases(value, naming, store)


def test_a_partial_decomposition_is_refused(harness):
    # Worse than no decomposition: the steps left out would vanish from every
    # artifact, and `event_coverage` would then fail somewhere with no way to
    # trace it back to here.
    store, _runner, naming = harness
    ids = [s.step_id for s in naming.steps]
    groups = cases_from([{"scenario": "a", "steps": ids[:1]}], naming, store)
    assert groups == []


def test_a_step_claimed_by_two_cases_is_only_placed_once(harness):
    store, _runner, naming = harness
    ids = [s.step_id for s in naming.steps]
    if len(ids) < 2:
        pytest.skip("this fixture produced a single step")
    groups = cases_from(
        [
            {"scenario": "first", "steps": ids},
            {"scenario": "second", "steps": ids},
        ],
        naming,
        store,
    )
    # The second case is left with nothing, so this is not a decomposition.
    assert groups == []


def test_one_case_is_not_a_decomposition(harness):
    store, _runner, naming = harness
    ids = [s.step_id for s in naming.steps]
    assert cases_from([{"scenario": "everything", "steps": ids}], naming, store) == []
