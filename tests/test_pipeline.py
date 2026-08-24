"""The whole spine, end to end, and the ablation over it.

This is the milestone-10 done-when: A0/A1/A2 run on the same recordings and
produce the SS3.5 table. Driven by a scripted model so the comparison is
deterministic -- the point being tested is the harness and the metrics, not any
particular model's competence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.ablation import run_ablation, write_report
from server.llm import CompletionRequest, ScriptedModelClient, answer, calls
from server.models import AblationConfig, Recording, ValidatorAction, ValidatorStatus
from server.pipeline.run import PipelineOptions, run_pipeline
from server.storage.paths import Storage
from tests import factories as f

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONFIRMATION = "Order confirmed"


def recording() -> Recording:
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
            ),
        ],
        objective="verify that orders over EUR500 require approval",
    )


def stage_of(request: CompletionRequest) -> str:
    """Which stage is asking.

    The pipeline runs three agentic stages against one scripted client, and
    each has its own answer contract. Sniffing the system prompt keeps the
    stand-in honest: it has to notice what it was asked, exactly as a real
    model does.
    """
    system = request.messages[0].content or ""
    if system.startswith("You are proposing the expected results"):
        return "assert"
    if system.startswith("You are turning a recorded browser session"):
        return "compose"
    if system.startswith("You are reviewing a finished QA test case"):
        return "critic"
    if system.startswith("You are reading a finished QA test case"):
        return "coverage"
    if system.startswith("You are writing the two sentences"):
        return "bug"
    return "name"


def composed(roles: dict[str, str] | None = None) -> str:
    return json.dumps(
        {
            "title": "Order checkout",
            "scenario": "Submitting a valid order shows the confirmation",
            "tags": ["checkout"],
            "roles": roles or {},
        }
    )


def grounded_model() -> ScriptedModelClient:
    """An agent that retrieves, then cites exactly what it retrieved.

    It reads the tool response rather than assuming: citing an event it did not
    actually find the string at is the mistake this whole gate exists to catch,
    so the well-behaved stand-in must not make it.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "compose":
            return answer(composed())
        if stage == "critic":
            # Finding nothing is the expected answer for output that reads
            # well, and a critic that always finds something is the failure
            # mode SS9.9 is most exposed to.
            return answer(json.dumps({"findings": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))

        tool_results = [m for m in request.messages if m.role == "tool"]
        baseline = request.messages[1].content or ""

        if stage == "name":
            # Only claim a change when the evidence shows one, or
            # mutation_claimed will rightly reject the step.
            mutated = "-> 201" in baseline or "-> 200" in baseline
            text = "the tester places the order" if mutated else "the tester fills in the form"
            return answer(json.dumps({"role": "test_step", "text": text, "confidence": "high"}))

        if not tool_results:
            return calls(
                ("find_text", {"query": CONFIRMATION}),
                preamble=json.dumps({"uncertainties": ["what the outcome was"]}),
            )

        # Tool results arrive wrapped as {"toolCallId": ..., "result": ...} so
        # the model can see the id it must cite. The stand-in reads the same
        # shape a real model does, including taking the id from the content
        # rather than from an envelope it cannot see.
        payload = json.loads(tool_results[-1].content or "{}")
        call_id = payload.get("toolCallId")
        matches = (payload.get("result") or {}).get("matches") or []
        if not matches:
            # Nothing was found, so there is nothing to claim. Omitting the
            # expected result is the correct outcome, not a failure.
            return answer(json.dumps({"candidates": []}))

        return answer(
            json.dumps(
                {
                    "candidates": [
                        {
                            "text": "the confirmation banner appears",
                            "provenance": "inferred",
                            "literal": CONFIRMATION,
                            "toolCallId": call_id,
                            "eventId": matches[0]["eventId"],
                            "kind": "semantic_node",
                        }
                    ]
                }
            )
        )

    return ScriptedModelClient(behave)


def fabricating_model() -> ScriptedModelClient:
    """The A0 failure mode: no retrieval, but a confident citation anyway.

    A real model cannot be asked to do this on command, which is exactly why
    the scripted client exists.
    """

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
                        "text": "the tester fills in the form",
                        "confidence": "high",
                    }
                )
            )
        return answer(
            json.dumps(
                {
                    "candidates": [
                        {
                            "text": "the confirmation banner appears",
                            "provenance": "inferred",
                            "literal": CONFIRMATION,
                            "toolCallId": "tc_0447",
                            "eventId": "evt_002",
                            "kind": "semantic_node",
                        }
                    ]
                }
            )
        )

    return ScriptedModelClient(behave)


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


# --------------------------------------------------------------------------
# the spine
# --------------------------------------------------------------------------


def test_a_run_produces_every_artifact(storage: Storage):
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_001")

    for name in ("segments", "naming", "assertions", "ir", "trace"):
        assert result.artifacts[name].exists(), f"{name}.json was not written"
    # Each stage reads a file and writes a file, so a wrong output can be
    # traced to the stage that produced it (SS9.1). This is the default
    # configuration -- tools on, critic off -- so there is exactly one pass of
    # render and validate and no repair.
    assert [s.stage.value for s in result.trace.stages] == [
        "segment",
        "name",
        "assert",
        "decompose",
        "render",
        "validate",
        "coverage",
    ]
    assert result.artifacts["coverage"].exists()
    assert result.rendered
    assert list(result.run.root.glob("*.feature"))
    # The evidence the feature body no longer carries is written beside it.
    assert list(result.run.root.glob("*.trace.md"))


def test_an_honest_run_passes_the_gate_and_grounds_its_assertions(storage: Storage):
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_001")

    assert result.report.ok, result.report.summary()
    assert result.grounding_rate == 1.0
    assert result.trace.metrics.assertionsTotal >= 1
    assert result.trace.metrics.assertionsUngrounded == 0


def test_a_fabricated_citation_is_caught_by_the_gate(storage: Storage):
    result = run_pipeline(recording(), fabricating_model(), storage=storage, run_id="run_002")

    assert result.report.rejected
    assert result.grounding_rate == 0.0
    failures = [r for r in result.report.results if r.status.value == "fail"]
    assert any("tc_0447" in (r.message or "") for r in failures)


def test_the_trace_records_what_the_agent_did(storage: Storage):
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_001")

    assert result.trace.toolCalls, "a run with tools must log its retrievals"
    assert result.trace.investigations
    assert result.trace.modelCalls
    # Every assertion's pointer resolves in the same trace it was produced by.
    for case in result.ir.testCases:
        for step in case.steps:
            for assertion in step.assertions:
                assert any(c.id == assertion.evidence.toolCallId for c in result.trace.toolCalls)


def test_the_written_trace_round_trips_through_the_schema(storage: Storage):
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_001")
    from server.models import AgentTrace

    reloaded = AgentTrace.model_validate(
        json.loads(result.artifacts["trace"].read_text(encoding="utf-8"))
    )
    assert reloaded.runId == "run_001"
    assert len(reloaded.toolCalls) == len(result.trace.toolCalls)


def test_a_leaked_secret_prevents_the_feature_file_from_being_written(storage: Storage):
    leaky = ScriptedModelClient(
        lambda request: answer(
            json.dumps(
                {
                    "keyword": "When",
                    "text": "the tester signs in as tester@example.com",
                    "confidence": "high",
                }
            )
        )
    )
    result = run_pipeline(recording(), leaky, storage=storage, run_id="run_003")

    assert result.report.hard_failed
    assert result.rendered == {}
    assert not list(result.run.root.glob("*.feature"))


# --------------------------------------------------------------------------
# the ablation
# --------------------------------------------------------------------------


def test_a0_has_no_tools_and_cannot_ground_anything(storage: Storage):
    result = run_pipeline(
        recording(),
        fabricating_model(),
        storage=storage,
        run_id="run_a0",
        options=PipelineOptions.for_config(AblationConfig.A0),
    )

    # SS3.2 -- disable tools and the pipeline cannot emit a single valid
    # assertion. Not "degrades": cannot.
    assert result.trace.toolCalls == []
    assert result.grounding_rate == 0.0
    assert result.report.rejected
    # And the truncation policy is declared rather than applied silently.
    assert result.trace.config.a0Truncation is not None


def test_the_ablation_produces_the_table(storage: Storage):
    report = run_ablation(
        [recording()],
        grounded_model(),
        storage=storage,
        model_name="scripted-1",
    )

    assert set(report.rows) == {"A0", "A1", "A2"}
    table = report.table()
    assert "Grounded" in table and "Calls/step" in table
    for config in ("A0", "A1", "A2"):
        assert config in table


def test_the_ablation_separates_the_architectures(storage: Storage):
    report = run_ablation([recording()], grounded_model(), storage=storage, model_name="scripted-1")

    a0, a2 = report.rows["A0"], report.rows["A2"]
    assert a0.tool_calls == 0, "A0 must make no retrievals"
    assert a2.tool_calls > 0, "A2 must retrieve"

    # Yield, not rate. A well-behaved model with no tools has no id to cite, so
    # it omits the expected result rather than inventing one -- which scores a
    # vacuous 100% on rate and zero on yield. Reading rate alone here would
    # report the two architectures as equivalent.
    assert a0.grounded_yield == 0.0
    assert a2.grounded_yield > 0.0
    assert a0.grounding_rate == 1.0, "abstaining is not the same as being wrong"
    assert "A0" in report.finding() and "A2" in report.finding()


def test_the_ablation_finding_is_stated_either_way(storage: Storage):
    # SS3.5 -- "if A1 is roughly A2, that is a genuine finding worth knowing in
    # month two rather than month five." The harness must say so, not bury it.
    #
    # `grounded_model` produces output the critic has nothing to say about, so
    # this is the null case: A1 and A2 really did run the same pipeline, and the
    # sentence has to say that rather than imply a difference it cannot see.
    report = run_ablation([recording()], grounded_model(), storage=storage, model_name="scripted-1")
    finding = report.finding()
    assert "must not be read alone" in finding
    assert "raised no findings" in finding
    assert report.rows["A2"].critic_findings == 0
    # And the vacuous reading is refused: no findings is not perfect
    # convergence, for the same reason abstaining is not perfect grounding.
    assert report.rows["A2"].repair_convergence_rate == 0.0


def test_the_finding_reports_a_critic_that_did_have_something_to_say(storage: Storage):
    # The other branch. A2's row is only worth printing if the sentence beside
    # it can distinguish "the critic found nothing" from "the critic found
    # things and fixed them".
    from tests.test_critic import scripted

    model = scripted(
        names=["the tester clicks the button", "the tester places the order"],
        findings=[{"step": "step_001", "kind": "step_name", "finding": "describes a mouse"}],
        later_findings=[],
    )
    report = run_ablation([recording()], model, storage=storage, model_name="scripted-1")

    assert report.rows["A2"].critic_findings >= 1
    assert report.rows["A1"].critic_findings == 0, "A1 has no critic, by definition (SS3.5)"
    assert "resolved" in report.finding()


def test_the_report_is_written_as_a_reusable_artifact(storage: Storage, tmp_path: Path):
    report = run_ablation([recording()], grounded_model(), storage=storage, model_name="scripted-1")
    path = write_report(report, tmp_path / "ablation.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert len(payload["table"]) == 3
    assert payload["finding"]
    # Every run is addressable, so a surprising number can be opened.
    assert len(payload["runs"]) == 3
    assert all(Path(r["runPath"]).exists() for r in payload["runs"])


# --------------------------------------------------------------------------
# against a real recording
# --------------------------------------------------------------------------


def test_the_spine_runs_over_a_real_recorded_session(storage: Storage):
    path = FIXTURES / "checkout.recording.json"
    if not path.exists():
        pytest.skip("run `pnpm e2e` to regenerate the recorded fixtures")

    real = Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))
    result = run_pipeline(real, grounded_model(), storage=storage, run_id="run_real")

    assert result.report.ok, result.report.summary()
    assert result.grounding_rate == 1.0
    # Naming and assertion each investigate every step; composition and
    # coverage each investigate the flow once. Every one of them records the
    # same way, so SS3.4 can read effort per step without knowing which stage
    # spent it -- which is the property being pinned here, not the arithmetic.
    from collections import Counter

    steps = len(result.naming.steps)
    per_stage = Counter(i.stage.value for i in result.trace.investigations)
    assert per_stage["name"] == steps
    assert per_stage["assert"] == steps
    assert per_stage["decompose"] == 1
    assert per_stage["coverage"] == 1

    feature = next(iter(result.rendered.values()))
    assert "Feature:" in feature
    # The evidence left the feature body and became a document beside it. The
    # binding itself is untouched: the pointer still resolves in the trace,
    # which is what `evidence_retrieved` reads (SS3.2).
    sidecar = next(iter(result.sidecars.values()))
    for case in result.ir.testCases:
        for step in case.steps:
            for assertion in step.assertions:
                assert assertion.evidence.toolCallId in sidecar
                assert assertion.evidence.literal in sidecar

    # Every event in the recording is accounted for in the output.
    covered = {e for c in result.ir.testCases for s in c.steps for e in s.eventIds}
    assert covered == {e.id for e in real.events}


def test_an_intent_note_becomes_the_step_name_word_for_word(tmp_path: Path):
    # The popup tells the tester "It will be used word for word" as they type
    # it, and until now nothing on this side read the annotation at all -- the
    # naming stage rewrote it like any other step. A promise made in the UI and
    # broken in the pipeline is worse than not offering the feature.
    #
    # Verbatim is enforced by not calling a model, rather than by asking one not
    # to paraphrase.
    from server.evidence.store import EvidenceStore
    from server.evidence.tools import ToolRunner
    from server.llm.scripted import ScriptedModelClient
    from server.models import Confidence, PipelineStage
    from server.pipeline.name import name_segments
    from server.pipeline.segment import segment_recording

    note = "the tester approves the order as a line manager"
    recording = f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, tgt=f.target("button", "Approve")),
        ],
        annotations=[f.annotation("ann_1", "intent_note", at=0.0, text=note)],
    )
    segments = segment_recording(recording, run_id="run_001")
    store = EvidenceStore(recording=recording, segments=segments)
    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    runner = ToolRunner(
        store=store,
        storage=storage,
        run=storage.run(recording.id, "run_001"),
        stage=PipelineStage.name,
    )

    def refuse(_request):
        raise AssertionError("a dictated step must not reach a model at all")

    result = name_segments(
        store, runner, ScriptedModelClient(refuse), model_name="test", tools_enabled=False
    )
    assert [s.text for s in result.steps] == [note]
    assert result.steps[0].confidence == Confidence.high


def test_library_verbatim_rejects_a_reuse_claim_that_was_rewritten(tmp_path: Path):
    # 47 lines of this validator have existed since Phase 1 and never once run,
    # because nothing ever set `libraryRef`. It is the thing that makes reuse
    # real rather than aspirational: a model that paraphrases an approved step
    # while claiming to reuse it reintroduces the step explosion the library
    # exists to prevent, and does it with a citation saying otherwise.
    from server.library import StepLibrary
    from server.pipeline.validators.consistency import library_verbatim

    library = StepLibrary(tmp_path / "library.db")
    entry = library.add("the tester signs in")
    assert entry is not None

    honest = f.step("step_001", "the tester signs in", assertions=[])
    honest.libraryRef = entry.id
    liar = f.step("step_002", "the tester logs in to the app", assertions=[])
    liar.libraryRef = entry.id

    ctx = f.validation_context(ir_doc=f.ir_document(test_cases=[f.test_case(steps=[honest, liar])]))
    ctx.library = library
    results = list(library_verbatim(ctx))

    failures = [r for r in results if r.status == ValidatorStatus.fail]
    assert len(failures) == 1
    assert failures[0].stepId == "step_002"
    assert failures[0].action == ValidatorAction.reject


def test_a_reuse_claim_with_no_library_is_not_admissible(tmp_path: Path):
    # A claim that cannot be checked is not a claim. Rejecting rather than
    # skipping is the same posture as SS3.2's evidence binding: the gate does
    # not wave through what it was unable to verify.
    from server.pipeline.validators.consistency import library_verbatim

    step = f.step("step_001", "the tester signs in", assertions=[])
    step.libraryRef = "lib_whatever"
    ctx = f.validation_context(ir_doc=f.ir_document(test_cases=[f.test_case(steps=[step])]))
    results = list(library_verbatim(ctx))
    assert [r.action for r in results] == [ValidatorAction.reject]


def test_a_step_always_says_who_is_doing_it():
    # A step is a sentence about a person. Dropped, it reads as an instruction
    # to whoever is holding the document and matches no step definition. This
    # is not hypothetical: a prompt edit whose worked examples omitted the
    # subject produced "submits an order totalling "615"" with nobody
    # submitting anything, and the prompt had said to include it twice.
    from server.config import ProjectConfig
    from server.pipeline.name import with_subject

    config = ProjectConfig()
    assert with_subject('submits an order totalling "615"', config) == (
        'the tester submits an order totalling "615"'
    )
    # Already correct, and a different actor, both left alone -- rewriting
    # "the approver releases the order" would produce nonsense.
    assert with_subject("the tester signs in", config) == "the tester signs in"
    assert with_subject("the approver releases the order", config) == (
        "the approver releases the order"
    )
    # First person needs no subject: "I" is the subject.
    assert with_subject("submit the order", ProjectConfig(voice="I")) == "submit the order"


def test_a_mandatory_search_is_not_evidence_of_investigation():
    # SS3.3's claim is that effort varies with difficulty -- "a step with an
    # obvious outcome costs zero calls; an ambiguous one costs several" -- and
    # the ablation's Spread column is how that is measured. A call the process
    # mandates on EVERY step is a constant added to every reading, and it does
    # real damage: introducing search-before-invent lifted calls-per-step from
    # 1.56 to 2.17 and collapsed spread from 1.08 to 0.16, which would read as
    # an agent that stopped adapting when nothing of the sort had happened.
    #
    # They still count as tool calls -- they are real, and they cost quota. They
    # are just not evidence that this step was hard.
    from server.models import Confidence, PipelineStage, SegmentRole, StepInvestigation, ToolCall
    from server.pipeline.name import NamedStep, NamingResult
    from server.pipeline.run import _calls_per_step

    def call(ident: str, tool: str) -> ToolCall:
        return ToolCall(
            id=ident,
            stage=PipelineStage.name,
            tool=tool,
            args={},
            responsePath=f"tools/{ident}.json",
            responseHash="sha256:0",
            timestamp=0.0,
            durationMs=0.0,
        )

    naming = NamingResult()
    naming.steps.append(
        NamedStep(
            segment_id="seg_001",
            step_id="step_001",
            role=SegmentRole.test_step,
            text="the tester signs in",
            confidence=Confidence.high,
            event_ids=["evt_001"],
            investigation=StepInvestigation(
                id="inv_001",
                stepId="step_001",
                stage=PipelineStage.name,
                initialUncertainty=[],
                toolCallIds=["tc_0001", "tc_0002"],
                budgetUsed=2,
                budgetMax=8,
                stopReason="evidence_sufficient",
            ),
        )
    )

    calls = [call("tc_0001", "search_step_library"), call("tc_0002", "find_text")]
    assert _calls_per_step(naming.investigations, calls) == {"step_001": 1}
    # With no trace supplied, nothing is excluded -- the metric degrades to the
    # old behaviour rather than silently reporting zero effort everywhere.
    assert _calls_per_step(naming.investigations, None) == {"step_001": 2}

    # A repair supersedes a step's investigation but does not undo its cost.
    # Under-reporting the step that took two passes would hide exactly the step
    # SS3.4's correlation exists to find -- the hard one.
    naming.superseded.append(
        StepInvestigation(
            id="inv_001_r2",
            stepId="step_001",
            stage=PipelineStage.name,
            initialUncertainty=[],
            toolCallIds=["tc_0003"],
            budgetUsed=1,
            budgetMax=8,
            stopReason="evidence_sufficient",
        )
    )
    assert _calls_per_step(naming.investigations, calls) == {"step_001": 2}


def test_a_step_about_a_refused_change_satisfies_mutation_claimed():
    # The tester submits an order over the approval threshold, the server says
    # no, and the expected result cites that refusal. "No successful mutation"
    # is the finding here, not a defect -- and it is exactly what a test about
    # an approval rule looks like.
    #
    # Judged on evidence, not on reading the sentence: an accepted assertion has
    # to be grounded IN the rejected request's own event, which a step that
    # merely failed cannot fake.
    from server.pipeline.validators.consistency import mutation_claimed

    assertion = f.assertion("a1", "the order requires manager approval")
    assertion.evidence.eventId = "evt_001"
    step = f.step(
        "step_001",
        "the tester submits an order that is rejected",
        assertions=[assertion],
        event_ids=["evt_001"],
    )
    recording = f.recording(events=[f.event("evt_001", 0, network=[f.network_call(status=409)])])
    ctx = f.validation_context(
        ir_doc=f.ir_document(test_cases=[f.test_case(steps=[step])]),
        recording_doc=recording,
    )
    assert not [r for r in mutation_claimed(ctx) if r.status == ValidatorStatus.fail]


def test_a_step_claiming_a_change_that_never_happened_still_fails():
    # The other half. Without a grounded rejection to point at, a step that says
    # data changed and shows no successful request is making a claim the
    # recording does not support.
    from server.pipeline.validators.consistency import mutation_claimed

    step = f.step(
        "step_001",
        "the tester submits the order and it is saved",
        assertions=[],
        event_ids=["evt_001"],
    )
    recording = f.recording(events=[f.event("evt_001", 0, network=[])])
    ctx = f.validation_context(
        ir_doc=f.ir_document(test_cases=[f.test_case(steps=[step])]),
        recording_doc=recording,
    )
    assert [r for r in mutation_claimed(ctx) if r.status == ValidatorStatus.fail]


def test_a_declared_scenario_break_is_not_the_models_to_overrule():
    # SS6.7 says a scenario break OVERRIDES decomposition, and override means
    # override: the tester pressed the button while they were there and we were
    # not. Composition is agentic and answered differently on two consecutive
    # runs of the same recording -- with a boundary the tester declared sitting
    # inside the single case it returned the second time.
    from server.models import Confidence, PipelineStage, SegmentRole, StepInvestigation
    from server.pipeline.compose import _split_on_declared_breaks
    from server.pipeline.name import NamedStep, NamingResult

    naming = NamingResult()
    for i in range(1, 5):
        naming.steps.append(
            NamedStep(
                segment_id=f"seg_{i:03d}",
                step_id=f"step_{i:03d}",
                role=SegmentRole.test_step,
                text=f"step {i}",
                confidence=Confidence.high,
                event_ids=[f"evt_{i:03d}"],
                investigation=StepInvestigation(
                    id=f"inv_{i}",
                    stage=PipelineStage.name,
                    initialUncertainty=[],
                    toolCallIds=[],
                    budgetUsed=0,
                    budgetMax=8,
                    stopReason="evidence_sufficient",
                ),
            )
        )

    groups = _split_on_declared_breaks(naming, {"step_003"})
    assert [g.step_ids for g in groups] == [
        ["step_001", "step_002"],
        ["step_003", "step_004"],
    ]
    # Deterministic, so no model has to agree twice.
    assert groups == _split_on_declared_breaks(naming, {"step_003"})


def test_a_break_at_the_very_start_is_not_a_split():
    from server.models import Confidence, PipelineStage, SegmentRole, StepInvestigation
    from server.pipeline.compose import _split_on_declared_breaks
    from server.pipeline.name import NamedStep, NamingResult

    naming = NamingResult()
    naming.steps.append(
        NamedStep(
            segment_id="seg_001",
            step_id="step_001",
            role=SegmentRole.test_step,
            text="one",
            confidence=Confidence.high,
            event_ids=["evt_001"],
            investigation=StepInvestigation(
                id="inv_1",
                stage=PipelineStage.name,
                initialUncertainty=[],
                toolCallIds=[],
                budgetUsed=0,
                budgetMax=8,
                stopReason="evidence_sufficient",
            ),
        )
    )
    assert _split_on_declared_breaks(naming, {"step_001"}) == []


def test_a_wrong_turn_is_pruned_and_reported_rather_than_deleted():
    # SS9.3. A recorded sitting is a person working, and people look for things.
    # Transcribing a wrong turn into a test case somebody has to execute is how
    # the artifact becomes unusable -- but deleting it silently is worse, because
    # a reader would trust the narrative for a session it never covered.
    from server.models import SegmentRole
    from server.pipeline.run import _prune

    steps = [
        f.step("step_001", "the tester signs in", role="setup", assertions=[]),
        f.step(
            "step_002",
            "the tester opens the reports page",
            role="exploratory",
            assertions=[],
            event_ids=["evt_003"],
        ),
        f.step("step_003", "the tester places the order", role="test_step", assertions=[]),
    ]
    kept, omitted = _prune(steps, {"step_002": "seg_002"})

    assert [s.id for s in kept] == ["step_001", "step_003"]
    assert len(omitted) == 1
    assert omitted[0]["reason"] == "exploratory"
    assert omitted[0]["eventCount"] == 1
    # Marked where it happened, so the reader sees the gap in place rather than
    # in a footnote.
    assert omitted[0]["afterStepId"] == "step_001"
    # The SEGMENT id: `event_coverage` and `no_pruned_assertion` both resolve an
    # omission back to its segment, and a step id resolves to nothing -- which
    # would report every pruned event as unaccounted for.
    assert omitted[0]["segmentId"] == "seg_002"
    assert all(s.role != SegmentRole.exploratory for s in kept)


def test_nothing_is_pruned_from_an_ordinary_recording():
    # Pruning is for sessions that genuinely wandered. A step merely being
    # uninteresting is not a wrong turn, and removing one loses work the tester
    # actually did.
    from server.pipeline.run import _prune

    steps = [
        f.step("step_001", "the tester signs in", role="setup", assertions=[]),
        f.step("step_002", "the tester places the order", role="test_step", assertions=[]),
    ]
    kept, omitted = _prune(steps, {})
    assert len(kept) == 2
    assert omitted == []
