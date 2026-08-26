"""Dividing one recording into the test cases it actually contains (SS9.3).

Every run in `runs/` produced exactly one test case, including `twoflows`,
whose objective names two flows. The drafter is told in bold that a scenario is
one behaviour with one verdict; on the 34-event commercial recording it wrote
three near-duplicate upgrade beats under one heading, the critic said so
precisely, and nothing happened -- `coherence` has no repair route and cannot
have one, because re-drafting can change the step COUNT.

So the interesting tests here are not "does the model split well". They are the
deterministic net: a partition is taken WHOLE or discarded WHOLE, and the step
count is identical either way. That is what lets this stage do what the repair
loop legitimately cannot.
"""

from __future__ import annotations

import json

from server.evidence.store import EvidenceStore
from server.llm import CompletionRequest, ScriptedModelClient, answer
from server.models import SegmentRole
from server.pipeline.draft import DraftedExpectation, DraftedScenario, DraftedStep, DraftResult
from server.pipeline.split import (
    SPLIT_EVENT_FLOOR,
    Group,
    accept,
    candidates,
    split_scenarios,
)
from server.storage.paths import Storage
from tests import factories as f


def step(ident: str, text: str, *, events: list[str], role: str = "test_step", expect: str = ""):
    return DraftedStep(
        step_id=ident,
        keyword="Given" if role == "setup" else "When",
        role=SegmentRole(role),
        text=text,
        event_ids=events,
        expects=[DraftedExpectation(text=expect, event_id=events[-1])] if expect else [],
    )


def drafted(*steps: DraftedStep, name: str = "One long scenario") -> DraftResult:
    return DraftResult(
        title="Hampers",
        description="",
        tags=[],
        scenarios=[DraftedScenario(name=name, steps=list(steps))],
    )


def long_scenario() -> DraftResult:
    """Three upgrade behaviours under one heading, the shape of the real defect.

    Three beats -- UNDER `MAX_BEATS` -- and 15 events. A beats-only trigger
    misses it, which is exactly what happened on `rec_MT7MXBS9B2VB`.
    """
    return drafted(
        step("step_001", "the tester opens the hamper page", events=["evt_001"], role="setup"),
        step(
            "step_002",
            "the tester fills the small basket",
            events=[f"evt_{i:03d}" for i in range(2, 8)],
            expect="the hamper is shown as a Small Wicker Basket",
        ),
        step(
            "step_003",
            "the tester keeps adding items",
            events=[f"evt_{i:03d}" for i in range(8, 13)],
            expect="the hamper is shown as a Medium Wicker Basket",
        ),
        step(
            "step_004",
            "the tester fills the largest basket",
            events=[f"evt_{i:03d}" for i in range(13, 16)],
            expect="no bigger hampers are available",
        ),
    )


# --------------------------------------------------------------------------
# the trigger -- deterministic, and it must not fire on a well-shaped document
# --------------------------------------------------------------------------


def test_a_well_shaped_scenario_never_reaches_the_model():
    # The no-churn, no-cost guarantee. The largest scenario any fixture produces
    # is 10 events; if this starts firing on them, every fixture run costs an
    # extra model call and the fixture outputs move for no reason.
    document = drafted(
        step("step_001", "the tester signs in", events=["evt_001"], role="setup"),
        step("step_002", "the tester adds an item", events=["evt_002", "evt_003"]),
        step(
            "step_003",
            "the tester places the order",
            events=["evt_004"],
            expect="the order is confirmed",
        ),
    )
    assert candidates(document) == []


def test_a_long_scenario_reaches_the_trigger_on_events_alone():
    # The flagship recording has THREE beats, under MAX_BEATS. A beats-only
    # trigger would have missed the defect this stage exists for.
    from server.pipeline.split import count_beats

    document = long_scenario()
    assert count_beats(document.scenarios[0]) <= 4, "under the beat limit, as the real one was"

    asked = candidates(document)
    assert [index for index, _ in asked] == [0]
    assert "events" in asked[0][1]


def test_the_floor_is_a_floor_and_not_a_ceiling():
    events = [f"evt_{i:03d}" for i in range(1, SPLIT_EVENT_FLOOR + 1)]
    at_the_floor = drafted(
        step("step_001", "the tester signs in", events=events[:1], role="setup"),
        step("step_002", "the tester works", events=events[1:], expect="something is true"),
    )
    assert candidates(at_the_floor) == []


def test_a_single_step_scenario_is_never_a_candidate():
    # There is nowhere to cut, so asking would spend a call to be told so.
    document = drafted(
        step("step_001", "the tester does everything", events=[f"evt_{i:03d}" for i in range(30)])
    )
    assert candidates(document) == []


# --------------------------------------------------------------------------
# the net -- whole or nothing
# --------------------------------------------------------------------------


def scenario_of(*ids: str) -> DraftedScenario:
    return DraftedScenario(
        name="x",
        steps=[step(i, f"the tester does {i}", events=[f"evt_{i[-3:]}"]) for i in ids],
    )


def test_a_valid_partition_is_applied():
    scenario = scenario_of("step_001", "step_002", "step_003")
    groups, refused = accept(
        scenario,
        [Group("first", ["step_001"]), Group("second", ["step_002", "step_003"])],
    )
    assert refused == ""
    assert [g.step_ids for g in groups] == [["step_001"], ["step_002", "step_003"]]


def test_one_group_is_a_complete_answer():
    # A scenario that is long because the behaviour is long is one test case,
    # and saying so is the decision rather than a failure to decide.
    scenario = scenario_of("step_001", "step_002")
    groups, refused = accept(scenario, [Group("all of it", ["step_001", "step_002"])])
    assert groups == [] and refused == ""


def test_a_partition_that_reorders_a_step_is_refused_whole():
    scenario = scenario_of("step_001", "step_002", "step_003")
    groups, refused = accept(
        scenario,
        [Group("a", ["step_002"]), Group("b", ["step_001", "step_003"])],
    )
    assert groups == []
    assert "ordered regrouping" in refused


def test_a_partition_that_drops_a_step_is_refused_whole():
    # Partially applying it would delete work the tester did, and
    # `event_coverage` would reject the run -- correctly, and confusingly.
    scenario = scenario_of("step_001", "step_002", "step_003")
    groups, refused = accept(scenario, [Group("a", ["step_001"]), Group("b", ["step_002"])])
    assert groups == []
    assert refused


def test_a_partition_that_invents_a_step_id_is_refused_whole():
    scenario = scenario_of("step_001", "step_002")
    groups, refused = accept(
        scenario, [Group("a", ["step_001"]), Group("b", ["step_002", "step_009"])]
    )
    assert groups == []
    assert refused


def test_a_partition_that_repeats_a_step_is_refused_whole():
    scenario = scenario_of("step_001", "step_002")
    groups, refused = accept(
        scenario, [Group("a", ["step_001"]), Group("b", ["step_001", "step_002"])]
    )
    assert groups == []
    assert refused


def test_a_cut_between_two_identical_steps_is_refused():
    # `merge_repeats` runs PER SCENARIO, so cutting here stops the two merging
    # and changes the total step count -- the SS3.6 guarantee that keeps
    # `coherence` out of CRITIC_REPAIR in the first place. Refusing it is what
    # makes this stage able to act where the repair loop cannot.
    scenario = DraftedScenario(
        name="x",
        steps=[
            step("step_001", "the tester adds an item", events=["evt_001"]),
            step("step_002", "the tester adds an item", events=["evt_002"]),
            step("step_003", "the tester checks out", events=["evt_003"]),
        ],
    )
    groups, refused = accept(
        scenario,
        [Group("a", ["step_001"]), Group("b", ["step_002", "step_003"])],
    )
    assert groups == []
    assert "step count" in refused


def test_a_cut_elsewhere_in_the_same_scenario_is_allowed():
    # The negative case: the rule is about the cut point, not about the
    # scenario containing a repeat anywhere.
    scenario = DraftedScenario(
        name="x",
        steps=[
            step("step_001", "the tester adds an item", events=["evt_001"]),
            step("step_002", "the tester adds an item", events=["evt_002"]),
            step("step_003", "the tester checks out", events=["evt_003"]),
        ],
    )
    groups, refused = accept(
        scenario,
        [Group("a", ["step_001", "step_002"]), Group("b", ["step_003"])],
    )
    assert refused == ""
    assert len(groups) == 2


# --------------------------------------------------------------------------
# end to end, through the stage
# --------------------------------------------------------------------------


def splitting_model(groups: list[dict]) -> ScriptedModelClient:
    def behave(request: CompletionRequest):
        return answer(json.dumps({"groups": groups, "reason": "the subject changes"}))

    return ScriptedModelClient(behave)


def store_and_runner(tmp_path):
    recording = f.recording(
        events=[f.event(f"evt_{i:03d}", i, at=float(i * 100)) for i in range(1, 20)],
        objective="fill a hamper",
    )
    store = EvidenceStore(recording=recording)
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    from server.evidence.tools import ToolRunner
    from server.models import PipelineStage

    runner = ToolRunner(
        store=store,
        storage=storage,
        run=storage.run(recording.id, "run_split"),
        stage=PipelineStage.split,
    )
    return store, runner


def test_splitting_does_not_change_a_single_step_id(tmp_path):
    # The invariant everything downstream rests on: `apply_intent_notes` keeps
    # its protected ids, `repair.targets` keeps its `known_steps`, and
    # `event_coverage` accounts for the same events either way.
    store, runner = store_and_runner(tmp_path)
    document = long_scenario()
    before = [s.step_id for s in document.steps]
    before_events = [list(s.event_ids) for s in document.steps]

    split_scenarios(
        store,
        runner,
        splitting_model(
            [
                {"name": "A small hamper fills to capacity", "steps": ["step_001", "step_002"]},
                {"name": "A full hamper upgrades", "steps": ["step_003", "step_004"]},
            ]
        ),
        document,
        model_name="test",
    )

    assert [s.step_id for s in document.steps] == before
    assert [list(s.event_ids) for s in document.steps] == before_events


def test_the_step_count_is_the_same_whether_or_not_the_split_fired(tmp_path):
    # SS3.6, end to end. A stage that could change the step count would move
    # `Yield`'s denominator, which is worse than being wrong -- the metric
    # improves.
    store, runner = store_and_runner(tmp_path)
    unsplit = long_scenario()
    document = long_scenario()

    split_scenarios(
        store,
        runner,
        splitting_model(
            [
                {"name": "A small hamper fills to capacity", "steps": ["step_001", "step_002"]},
                {"name": "A full hamper upgrades", "steps": ["step_003", "step_004"]},
            ]
        ),
        document,
        model_name="test",
    )

    assert len(document.scenarios) == 2
    assert len(document.steps) == len(unsplit.steps)


def test_a_refused_partition_leaves_one_scenario_and_says_why(tmp_path):
    store, runner = store_and_runner(tmp_path)
    document = long_scenario()

    result = split_scenarios(
        store,
        runner,
        splitting_model([{"name": "a", "steps": ["step_004"]}, {"name": "b", "steps": ["x"]}]),
        document,
        model_name="test",
    )

    assert len(document.scenarios) == 1
    assert result.decisions[0].refused, "why is this one scenario always has an answer"
    assert result.to_artifact()["decisions"][0]["refused"]


def test_the_splitter_never_runs_without_tools(tmp_path):
    # A0 makes NO retrieval of any kind, and a tools-disabled investigation
    # still costs a model call -- which would make "single prompt, all context
    # pre-loaded" untrue of the configuration defined by it.
    store, runner = store_and_runner(tmp_path)
    document = long_scenario()

    def refuse(request: CompletionRequest):
        raise AssertionError("the splitter must not call a model under A0")

    result = split_scenarios(
        store, runner, ScriptedModelClient(refuse), document, model_name="test", tools_enabled=False
    )

    assert result.failed
    assert len(document.scenarios) == 1


def test_a_degraded_draft_is_not_repartitioned(tmp_path):
    # The fallback writes one step per event; partitioning that spends a call
    # to rearrange something nobody decided.
    store, runner = store_and_runner(tmp_path)
    document = long_scenario()
    document.degraded = "the model failed"

    def refuse(request: CompletionRequest):
        raise AssertionError("a degraded draft has no shape to repartition")

    result = split_scenarios(store, runner, ScriptedModelClient(refuse), document, model_name="t")
    assert result.failed
