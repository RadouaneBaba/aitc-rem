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

    Each agentic stage has its own answer contract. Sniffing the system prompt
    keeps the stand-in honest: it has to notice what it was asked, exactly as a
    real model does.
    """
    system = request.messages[0].content or ""
    if system.startswith("You are checking whether a recording supports"):
        return "bind"
    if system.startswith("You are writing ONE manual QA test document"):
        return "draft"
    if system.startswith("You are reviewing a finished QA test case"):
        return "critic"
    if system.startswith("You are reading a finished QA test case"):
        return "coverage"
    if system.startswith("You are writing the two sentences"):
        return "bug"
    if system.startswith("You rewrite one step"):
        return "rewrite"
    if system.startswith("You propose the expected result"):
        return "reexpect"
    return "draft"


def draft_over(request: CompletionRequest) -> str:
    """A document covering whatever events the index lists.

    The stand-in reads the session index it was handed, exactly as a real
    drafter does, so the same fake works on the two-event fixture and on a
    recording made by the extension. Accounting for every event is not optional
    -- `event_coverage` is the net under the drafter's freedom to choose step
    boundaries, and a fake that ignored it would let a regression through.
    """
    import re

    digest = request.messages[1].content or ""
    events = list(dict.fromkeys(re.findall(r"evt_\d+", digest)))
    if not events:
        return drafted()

    head, tail = events[:1], events[1:] or events[:1]
    return json.dumps(
        {
            "title": "Order checkout",
            "description": "An order is placed and confirmed.",
            "tags": ["checkout"],
            "scenarios": [
                {
                    "name": "Submitting a valid order shows the confirmation",
                    "steps": [
                        {
                            "keyword": "Given",
                            "role": "setup",
                            "text": "the tester opens the order form",
                            "eventIds": head,
                        },
                        {
                            "keyword": "When",
                            "role": "test_step",
                            "text": "the tester places the order",
                            "eventIds": tail,
                            "expect": [
                                {
                                    "text": "the confirmation banner appears",
                                    "eventId": tail[-1],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def drafted(expect: list[dict] | None = None) -> str:
    """A test document over the two-event fixture recording.

    Both events are accounted for, which `event_coverage` requires: the drafter
    now chooses step boundaries, so that validator is the net under it.
    """
    return json.dumps(
        {
            "title": "Order checkout",
            "description": "An order is placed and confirmed.",
            "tags": ["checkout"],
            "scenarios": [
                {
                    "name": "Submitting a valid order shows the confirmation",
                    "steps": [
                        {
                            "keyword": "Given",
                            "role": "setup",
                            "text": "the tester fills in the purchase order",
                            "eventIds": ["evt_001"],
                        },
                        {
                            "keyword": "When",
                            "role": "test_step",
                            "text": "the tester places the order",
                            "eventIds": ["evt_002"],
                            "expect": expect
                            if expect is not None
                            else [
                                {
                                    "text": "the confirmation banner appears",
                                    "eventId": "evt_002",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    )


def grounded_model() -> ScriptedModelClient:
    """An agent that retrieves, then cites exactly what it retrieved.

    It reads the tool response rather than assuming: quoting a string it did
    not actually find is the mistake this whole gate exists to catch, so the
    well-behaved stand-in must not make it.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "draft":
            return answer(draft_over(request))
        if stage == "critic":
            # Finding nothing is the expected answer for output that reads
            # well, and a critic that always finds something is the failure
            # mode SS9.9 is most exposed to.
            return answer(json.dumps({"findings": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))

        tool_results = [m for m in request.messages if m.role == "tool"]
        if not tool_results:
            return calls(
                ("find_text", {"query": CONFIRMATION}),
                preamble=json.dumps({"uncertainties": ["what the outcome was"]}),
            )

        # Tool results arrive wrapped as {"toolCallId": ..., "result": ...} so
        # a real model can see the id. This stand-in deliberately does NOT use
        # it: under draft-then-bind the model names only the literal and the
        # code resolves which retrieval contains it, so an agent that invents
        # an id gains nothing by it.
        payload = json.loads(tool_results[-1].content or "{}")
        matches = (payload.get("result") or {}).get("matches") or []
        if not matches:
            # Nothing was found, so there is nothing to claim. Answering
            # `unsupported` is the correct outcome, not a failure.
            return answer(json.dumps({"verdict": "unsupported", "reason": "not in the recording"}))

        return answer(
            json.dumps(
                {
                    "verdict": "bind",
                    "literal": CONFIRMATION,
                    "eventId": matches[0]["eventId"],
                    "kind": "semantic_node",
                    "reason": "the banner says so",
                }
            )
        )

    return ScriptedModelClient(behave)


def fabricating_model() -> ScriptedModelClient:
    """A model that claims something it never retrieved.

    A real model cannot be asked to do this on command, which is exactly why
    the scripted client exists. Note what it is no longer able to fake: under
    draft-then-bind there is no `toolCallId` field for it to fill in, so the
    only lie available is to quote a literal it did not see -- and that is
    caught by looking for the string in its own retrievals.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "draft":
            return answer(draft_over(request))
        if stage == "critic":
            return answer(json.dumps({"findings": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        return answer(
            json.dumps(
                {
                    "verdict": "bind",
                    "literal": "Everything went perfectly",
                    "eventId": "evt_002",
                    "kind": "semantic_node",
                    "reason": "I am confident about this",
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

    for name in ("segments", "draft", "split", "assertions", "ir", "trace"):
        assert result.artifacts[name].exists(), f"{name}.json was not written"
    # Each stage reads a file and writes a file, so a wrong output can be
    # traced to the stage that produced it (SS9.1). This is the default
    # configuration -- tools on, critic off -- so there is exactly one pass of
    # render and validate and no repair.
    assert [s.stage.value for s in result.trace.stages] == [
        "segment",
        "decompose",
        "split",
        "assert",
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


def test_a_claim_the_model_did_not_retrieve_never_reaches_the_output(storage: Storage):
    """The guarantee, in its strongest form (SS3.2).

    Under retrieve-first the model supplied its own `toolCallId` and the gate
    caught a bad one after the fact. It cannot supply one at all now: it names
    a literal, and `bind.py` searches the retrievals the agent actually made
    for a response containing that string. This model quotes something no tool
    ever returned, so there is nothing to resolve and the claim is DELETED --
    it never reaches the feature file to be rejected there.

    The test that this replaces asserted the weaker property: that a fabricated
    citation was caught. Catching it was never as good as making it
    unexpressible.
    """
    result = run_pipeline(recording(), fabricating_model(), storage=storage, run_id="run_002")

    claimed = [a.text for c in result.ir.testCases for s in c.steps for a in s.assertions]
    assert claimed == [], f"an unretrieved claim reached the output: {claimed}"

    # And it is not silently absent: the run says which claim it dropped and why.
    dropped = [c for c in result.bound.claims if c.assertion is None]
    assert dropped, "the claim should be recorded as dropped, not simply missing"
    assert "does not appear in any response" in dropped[0].reason

    # Nothing was rejected, because nothing false was emitted. A configuration
    # that abstains has a vacuous grounding rate -- read it with Yield.
    assert result.trace.metrics.assertionsTotal == 0


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
        lambda request: (
            answer(
                drafted(expect=[])
                if stage_of(request) == "draft"
                else json.dumps({"findings": [], "suggestions": []})
            )
            if stage_of(request) != "draft"
            else answer(
                json.dumps(
                    {
                        "title": "Sign in",
                        "description": "",
                        "tags": [],
                        "scenarios": [
                            {
                                "name": "Signing in",
                                "steps": [
                                    {
                                        "keyword": "Given",
                                        "role": "setup",
                                        "text": "the tester signs in as tester@example.com",
                                        "eventIds": ["evt_001"],
                                    },
                                    {
                                        "keyword": "When",
                                        "role": "test_step",
                                        "text": "the tester places the order",
                                        "eventIds": ["evt_002"],
                                    },
                                ],
                            }
                        ],
                    }
                )
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

    # What that looks like changed with draft-then-bind, and the change is the
    # point. A0 used to emit its claims and have them REJECTED, so the run
    # scored a grounding rate of 0. It now emits nothing at all: a claim is
    # only written after something is found to support it, and with no
    # retrieval there is nothing to find.
    #
    # Which means the rate is vacuously 1.0 here, exactly as it is for any
    # configuration that abstains -- the trap this project has hit in four
    # separate columns. Read it with the count, which is the honest number.
    assert result.trace.metrics.assertionsTotal == 0, "A0 must not be able to claim anything"
    assert not result.report.hard_failed
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

    # One drafting investigation for the whole document, one coverage pass, and
    # binding investigations only where a claim was contested. That last number
    # is not fixed and must not be: it is the difference between an agent that
    # investigates and a chain that retrieves on a schedule (SS3.3).
    from collections import Counter

    per_stage = Counter(i.stage.value for i in result.trace.investigations)
    assert per_stage["decompose"] == 1, "the document is written once, by one author"
    assert per_stage["coverage"] == 1
    assert per_stage["assert"] <= len(result.draft.steps), (
        "binding must cost at most one investigation per claim, and fewer when "
        "the deterministic pass can settle one"
    )

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


def test_an_intent_note_becomes_the_step_name_word_for_word():
    # The popup tells the tester "It will be used word for word" as they type
    # it, and the first implementation of this never read the annotation at all
    # -- the naming stage rewrote it like any other step. A promise made in the
    # UI and broken in the pipeline is worse than not offering the feature.
    #
    # Verbatim is enforced by overwriting whatever the model wrote, rather than
    # by asking it not to paraphrase. A prompt that asks is not a guarantee.
    from server.evidence.store import EvidenceStore
    from server.models import SegmentRole
    from server.pipeline.draft import (
        DraftedScenario,
        DraftedStep,
        DraftResult,
        apply_intent_notes,
    )
    from server.pipeline.segment import segment_recording

    note = "the tester approves the order as a line manager"
    rec = f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, tgt=f.target("button", "Sign in")),
            f.event("evt_002", 1, at=5000.0, tgt=f.target("button", "Approve")),
        ],
        # The note lands BETWEEN the two clicks and describes the second one.
        # Attribution direction is not the same for every annotation: an
        # assertion note comes after what it points at, an intent note comes
        # before the step it names.
        annotations=[f.annotation("ann_1", "intent_note", at=3000.0, text=note)],
    )
    store = EvidenceStore(recording=rec, segments=segment_recording(rec, run_id="run_001"))

    drafted = DraftResult(
        title="t",
        description="",
        tags=[],
        scenarios=[
            DraftedScenario(
                name="s",
                steps=[
                    DraftedStep(
                        "step_001", "Given", SegmentRole.setup, "the tester signs in", ["evt_001"]
                    ),
                    DraftedStep(
                        "step_002",
                        "When",
                        SegmentRole.test_step,
                        "the tester clicks approve",
                        ["evt_002"],
                    ),
                ],
            )
        ],
    )

    dictated = apply_intent_notes(store, drafted)

    assert dictated == {"step_002"}
    assert drafted.steps[1].text == note
    # And the step the note was not about is left exactly as drafted.
    assert drafted.steps[0].text == "the tester signs in"


def test_a_dictated_step_is_not_the_repair_loops_to_rewrite():
    # SS6.7 and SS12.2 are the same promise from two directions: text a human
    # chose is not the tool's to improve. Enforced in `repair.targets` as well
    # as at the point of use, because a critic finding about a step the tester
    # named themselves is a finding about the tester's wording.
    from server.models import PipelineStage, RepairTrigger
    from server.pipeline.critic import Finding
    from server.pipeline.repair import targets

    finding = Finding(
        step_id="step_002",
        kind="step_name",
        message="this step name is vague",
    )
    empty = f.validation_report(results=[])

    assert (
        targets(empty, [finding], protected={"step_002"}, known_steps={"step_001", "step_002"})
        == []
    )
    # Unprotected, the same finding is actionable -- so the guard above is
    # doing the work, not the absence of a route.
    unprotected = targets(empty, [finding], protected=set(), known_steps={"step_001", "step_002"})
    assert [t.step_id for t in unprotected] == ["step_002"]
    assert unprotected[0].stage == PipelineStage.name
    assert unprotected[0].trigger == RepairTrigger.critic


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
    from server.pipeline.draft import with_subject

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
    # mandates on EVERY step is a constant added to every reading, and it did
    # real damage: search-before-invent lifted calls-per-step from 1.56 to 2.17
    # and collapsed spread from 1.08 to 0.16, which reads as an agent that
    # stopped adapting when nothing of the sort had happened.
    #
    # The per-step library search went with the naming stage, but the exclusion
    # stays, because the rule it encodes is general and the next mandatory call
    # will make the same mistake.
    #
    # They still count as tool calls -- they are real, and they cost quota. They
    # are just not evidence that this step was hard.
    from server.models import PipelineStage, StepInvestigation, ToolCall
    from server.pipeline.run import _calls_per_step

    def call(ident: str, tool: str) -> ToolCall:
        return ToolCall(
            id=ident,
            stage=PipelineStage.assert_,
            tool=tool,
            args={},
            responsePath=f"tools/{ident}.json",
            responseHash="sha256:0",
            timestamp=0.0,
            durationMs=0.0,
        )

    def investigation(ident: str, tool_call_ids: list[str]) -> StepInvestigation:
        return StepInvestigation(
            id=ident,
            stepId="step_001",
            stage=PipelineStage.assert_,
            initialUncertainty=[],
            toolCallIds=tool_call_ids,
            budgetUsed=len(tool_call_ids),
            budgetMax=8,
            stopReason="evidence_sufficient",
        )

    investigations = [investigation("inv_001", ["tc_0001", "tc_0002"])]
    calls = [call("tc_0001", "search_step_library"), call("tc_0002", "find_text")]

    assert _calls_per_step(investigations, calls) == {"step_001": 1}
    # With no trace supplied, nothing is excluded -- the metric degrades to the
    # old behaviour rather than silently reporting zero effort everywhere.
    assert _calls_per_step(investigations, None) == {"step_001": 2}

    # A repair adds a second investigation for the same step and does not undo
    # the cost of the first. Under-reporting the step that took two passes would
    # hide exactly the step SS3.4's correlation exists to find -- the hard one.
    investigations.append(investigation("inv_001_r2", ["tc_0003"]))
    assert _calls_per_step(investigations, calls) == {"step_001": 2}


def test_the_binders_mandatory_retrieval_is_not_counted_as_effort():
    # The deterministic binding pass confirms a claim with one mandatory
    # `get_snapshot`. That is a process-mandated call, not investigation -- the
    # same thing `ROUTINE_TOOLS` excludes, arriving by a different door, and
    # `ROUTINE_TOOLS` cannot catch it because it filters by tool NAME and
    # `get_snapshot` is genuine effort elsewhere.
    #
    # It gave every bound claim a floor of exactly 1: 9 of 13 runs read a column
    # of constant 1s, on a metric whose whole purpose is variance. The step is
    # still reported -- at zero -- because "this step cost nothing" and "this
    # step was never looked at" are different facts.
    from server.models import PipelineStage, StepInvestigation
    from server.pipeline.run import _calls_per_step

    mandatory = StepInvestigation(
        id="inv_bind_step_001_001",
        stepId="step_001",
        stage=PipelineStage.assert_,
        initialUncertainty=[],
        toolCallIds=["tc_0009"],
        budgetUsed=1,
        budgetMax=1,
        stopReason="no_investigation_needed",
    )
    contested = StepInvestigation(
        id="inv_bind_step_002",
        stepId="step_002",
        stage=PipelineStage.assert_,
        initialUncertainty=["which of these is the verdict"],
        toolCallIds=["tc_0010", "tc_0011", "tc_0012"],
        budgetUsed=3,
        budgetMax=6,
        stopReason="evidence_sufficient",
    )

    assert _calls_per_step([mandatory, contested], None) == {"step_001": 0, "step_002": 3}


def test_the_binders_mandatory_retrieval_is_still_a_real_call():
    # It costs quota and it is what the claim cites, so `budgetMax` must be
    # honest too: the review UI and the sidecar both render "used N of M" and
    # were printing "used 1 of 0".
    from server.pipeline import bind

    source = (Path(bind.__file__)).read_text(encoding="utf-8")
    assert "budgetMax=0" not in source


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


def _drafted_over(event_ids: list[str], per_step: int = 1):
    """A drafted document with `per_step` events per step, for shape tests."""
    from server.models import SegmentRole
    from server.pipeline.draft import DraftedScenario, DraftedStep, DraftResult

    steps = [
        DraftedStep(
            step_id=f"step_{i + 1:03d}",
            keyword="When",
            role=SegmentRole.test_step,
            text=f"step {i + 1}",
            event_ids=event_ids[i * per_step : (i + 1) * per_step],
        )
        for i in range((len(event_ids) + per_step - 1) // per_step)
    ]
    return DraftResult(
        title="t",
        description="",
        tags=[],
        scenarios=[DraftedScenario(name="one scenario", steps=steps)],
    )


def _store_with(annotations):
    from server.evidence.store import EvidenceStore
    from server.pipeline.segment import segment_recording

    rec = f.recording(
        events=[f.event(f"evt_{i:03d}", i - 1, at=float(i) * 1000.0) for i in range(1, 5)],
        annotations=annotations,
    )
    return EvidenceStore(recording=rec, segments=segment_recording(rec, run_id="run_001"))


def test_a_declared_scenario_break_is_not_the_models_to_overrule():
    # SS6.7 says a scenario break OVERRIDES the model, and override means
    # override: the tester pressed the button while they were there and we were
    # not. The agentic stage answered differently on two consecutive runs of the
    # same recording -- with a boundary the tester declared sitting inside the
    # single case it returned the second time.
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=3000.0, event_id="evt_003")])
    drafted = _drafted_over(["evt_001", "evt_002", "evt_003", "evt_004"])
    _split_on_declared_breaks(store, drafted)

    assert [[st.step_id for st in sc.steps] for sc in drafted.scenarios] == [
        ["step_001", "step_002"],
        ["step_003", "step_004"],
    ]
    # Deterministic, so no model has to agree twice.
    again = _drafted_over(["evt_001", "evt_002", "evt_003", "evt_004"])
    _split_on_declared_breaks(store, again)
    assert [[st.step_id for st in sc.steps] for sc in again.scenarios] == [
        ["step_001", "step_002"],
        ["step_003", "step_004"],
    ]


def test_a_break_at_the_very_start_is_not_a_split():
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=1000.0, event_id="evt_001")])
    drafted = _drafted_over(["evt_001", "evt_002"])
    _split_on_declared_breaks(store, drafted)
    assert len(drafted.scenarios) == 1


def test_a_cut_invalidates_the_original_name_as_well_as_creating_a_new_one():
    # The drafter wrote that name for the WHOLE session. Once a declared break
    # cuts the scenario, the first group no longer has the body the name
    # describes -- so keeping it produces a heading that promises something the
    # steps under it never reach.
    #
    # `twoflows` shipped exactly that: "An order exceeding the threshold
    # requires approval" over a body that signs in, adds one item, and asserts a
    # cart badge. Every step true, every claim grounded, and nothing re-reads a
    # name once binding has decided what the scenario actually proves.
    #
    # Both groups are left unnamed for the same reason and named the same way,
    # by `_scenario_from`, after what they VERIFY.
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=3000.0, event_id="evt_003")])
    drafted = _drafted_over(["evt_001", "evt_002", "evt_003", "evt_004"])
    _split_on_declared_breaks(store, drafted)

    assert len(drafted.scenarios) == 2
    assert [sc.name for sc in drafted.scenarios] == ["", ""]


def test_a_scenario_that_was_not_cut_keeps_the_name_it_was_given():
    # The negative case, and the one that keeps the rule honest: renaming is a
    # consequence of the body changing. Where no break falls inside a scenario,
    # nothing about it changed and the drafter's name is still the best one
    # there is -- it saw the whole session to write it.
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=9000.0)])
    drafted = _drafted_over(["evt_001", "evt_002"])
    _split_on_declared_breaks(store, drafted)

    assert len(drafted.scenarios) == 1
    assert drafted.scenarios[0].name == "one scenario"


def test_a_declared_break_carries_no_event_id_and_still_splits():
    # The shape the RECORDER actually writes, and the reason this whole path was
    # dead. `export.ts` attaches an annotation to an event only when it is a
    # fact about that event, and a boundary sits between two of them -- so a
    # `scenario_break` has a timestamp and nothing else.
    #
    # `_split_on_declared_breaks` filtered on `a.eventId`, got an empty set and
    # returned on its first line. Every test above passed because the factory
    # let them set an `eventId` the recorder never sets, so the suite was
    # exercising an input that cannot occur. SS6.7's deterministic override had
    # never fired on a real recording, and `twoflows` -- the fixture that exists
    # to prove two test cases come out of one session -- had been shipping a
    # single scenario with both flows in it.
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=2500.0)])
    assert store.recording.annotations[0].eventId is None

    drafted = _drafted_over(["evt_001", "evt_002", "evt_003", "evt_004"])
    _split_on_declared_breaks(store, drafted)

    # 2500ms falls between evt_002 (2000) and evt_003 (3000), and a break opens
    # the work that FOLLOWS it.
    assert [[st.step_id for st in sc.steps] for sc in drafted.scenarios] == [
        ["step_001", "step_002"],
        ["step_003", "step_004"],
    ]


def test_the_drafter_is_told_where_the_tester_declared_a_break():
    # The other half of the same bug, and the one that decides the outcome. The
    # deterministic split cuts only where a break opens a STEP -- cutting
    # through the middle of one would leave two halves whose sentences describe
    # work neither of them does -- so a drafter that merged across the boundary
    # cannot be repaired afterwards.
    #
    # On `twoflows` that is exactly what happened: the index never mentioned the
    # break, the drafter put the events either side of it into one step, and the
    # net then correctly declined to cut. Both halves behaved. Nothing had told
    # the one author that decides scenario boundaries that the tester had
    # already decided.
    from server.pipeline.digest import build_digest

    store = _store_with([f.annotation("ann_1", "scenario_break", at=2500.0)])
    text = build_digest(store).text

    declaration = "THE TESTER DECLARED A NEW TEST CASE HERE"
    assert declaration in text
    # Immediately before the event it opens, where a reader looking for a
    # boundary would expect it.
    lines = [ln.strip() for ln in text.splitlines()]
    marker = next(i for i, ln in enumerate(lines) if declaration in ln)
    assert lines[marker + 1].startswith("evt_003")


def test_a_break_inside_a_step_does_not_cut_it_in_half():
    # A break opens a new scenario only where it opens a STEP. The drafter
    # groups events into intents, and cutting through the middle of one would
    # leave two half-steps whose sentences describe work neither of them does.
    from server.pipeline.run import _split_on_declared_breaks

    store = _store_with([f.annotation("ann_1", "scenario_break", at=2000.0, event_id="evt_002")])
    drafted = _drafted_over(["evt_001", "evt_002", "evt_003", "evt_004"], per_step=2)
    _split_on_declared_breaks(store, drafted)
    assert len(drafted.scenarios) == 1


def _drafts(payload: dict):
    """A model that returns one drafted document and nothing else of interest."""

    def behave(request: CompletionRequest):
        if stage_of(request) != "draft":
            return answer(json.dumps({"findings": [], "suggestions": []}))
        return answer(json.dumps(payload))

    return ScriptedModelClient(behave)


ONE_STEP = {
    "title": "Order checkout",
    "description": "",
    "tags": [],
    "scenarios": [
        {
            "name": "Placing an order",
            "steps": [
                {
                    "keyword": "When",
                    "role": "test_step",
                    "text": "the tester places the order",
                    "eventIds": ["evt_002"],
                }
            ],
        }
    ],
}


def test_a_wrong_turn_is_reported_rather_than_deleted(storage: Storage):
    # SS9.3. A recorded sitting is a person working, and people look for things.
    # Transcribing a wrong turn into a test case somebody has to execute is how
    # the artifact becomes unusable -- but deleting it silently is worse, because
    # a reader would trust the narrative for a session it never covered.
    #
    # The judgement moved. It used to be a role the composer put on a step,
    # which `_prune` then removed; the drafter now says outright which events
    # are not part of the test, and `event_coverage` is what makes that
    # accounting mandatory rather than polite.
    payload = {
        **ONE_STEP,
        "omitted": [
            {
                "eventIds": ["evt_001"],
                "reason": "exploratory",
                "summary": "opened the wrong form and came back",
            }
        ],
    }
    result = run_pipeline(recording(), _drafts(payload), storage=storage, run_id="run_pruned")

    case = result.ir.testCases[0]
    assert [s.id for s in case.steps] == ["step_001"]
    assert len(case.omitted) == 1
    assert case.omitted[0].reason.value == "exploratory"
    assert case.omitted[0].eventIds == ["evt_001"]

    # And the omission is what discharges the event, so nothing went missing.
    coverage = [r for r in result.report.results if r.validator.value == "event_coverage"]
    assert coverage and coverage[0].status != ValidatorStatus.fail, coverage[0].message


def test_an_event_the_drafter_forgot_is_rejected(storage: Storage):
    # The net under the drafter's freedom to choose step boundaries. It decides
    # what a step is now, so "every event lands in a step or in an explicit
    # omission" is the one structural promise left, and it is code.
    result = run_pipeline(recording(), _drafts(ONE_STEP), storage=storage, run_id="run_dropped")

    coverage = [r for r in result.report.results if r.validator.value == "event_coverage"]
    assert coverage and coverage[0].status == ValidatorStatus.fail
    assert "evt_001" in (coverage[0].message or "")


def test_an_expected_result_that_looks_back_is_not_a_mutation_claim():
    # "the shopping bag displays the item previously added" is a claim about
    # what is on screen NOW. The adding happened two steps earlier and this
    # step issued no request at all, so read as a mutation claim it fails a
    # validator that is right about everything except which step it means.
    #
    # Found on a real recording, where it was the run's only rejection.
    from server.pipeline.validators.consistency import mutation_claimed

    assertion = f.assertion("a1", "the shopping bag page displays the item previously added")
    assertion.evidence.eventId = "evt_001"
    step = f.step(
        "step_001",
        "the tester views the shopping bag",
        assertions=[assertion],
        event_ids=["evt_001"],
    )
    recording = f.recording(events=[f.event("evt_001", 0, network=[])])
    ctx = f.validation_context(
        ir_doc=f.ir_document(test_cases=[f.test_case(steps=[step])]),
        recording_doc=recording,
    )
    assert not [r for r in mutation_claimed(ctx) if r.status == ValidatorStatus.fail]


def test_a_plain_mutation_claim_still_has_to_prove_itself():
    # The narrow rule above must not become a way out of the check. Without a
    # past-reference marker next to the verb, "the order is saved" is a claim
    # about what this step did and still needs a successful mutating request.
    from server.pipeline.validators.consistency import mutation_claimed

    assertion = f.assertion("a1", "the order is saved")
    assertion.evidence.eventId = "evt_001"
    step = f.step(
        "step_001",
        "the tester confirms the order",
        assertions=[assertion],
        event_ids=["evt_001"],
    )
    recording = f.recording(events=[f.event("evt_001", 0, network=[])])
    ctx = f.validation_context(
        ir_doc=f.ir_document(test_cases=[f.test_case(steps=[step])]),
        recording_doc=recording,
    )
    assert [r for r in mutation_claimed(ctx) if r.status == ValidatorStatus.fail]


def test_a_rerun_does_not_leave_the_previous_shape_behind(storage: Storage):
    # A feature filename carries the case id and a case id carries the scenario
    # NUMBER, so a re-run producing a different number of test cases used to
    # leave the old files beside the new ones. `checkout` shipped a run
    # directory holding `tc_..._01.feature` and `tc_..._02.feature` from a
    # two-scenario run alongside `tc_....feature` from the one-scenario re-run
    # that replaced it -- three feature files, two of them describing a document
    # that no longer exists, all downloadable and all indistinguishable.
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_shape")

    stale = result.run.root / "tc_left_over_from_before_01.feature"
    stale.write_text("Feature: a document that no longer exists", encoding="utf-8")
    (result.run.root / "tc_left_over_from_before_01.trace.md").write_text("x", encoding="utf-8")

    run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_shape")

    assert not stale.exists()
    assert not (result.run.root / "tc_left_over_from_before_01.trace.md").exists()
    # And what the run actually produced is still there.
    assert list(result.run.root.glob("*.feature"))
    # Never wide enough to reach what the gate re-reads.
    assert (result.run.root / "ir.json").is_file()
    assert (result.run.root / "trace.json").is_file()


def test_bug_mode_can_actually_be_turned_on():
    # SS14 is built, verified and was unreachable: `bug_mode_enabled` defaults
    # to False -- for a reason argued in `PipelineOptions`, that on a commercial
    # site the uncaught-exception signal fires on third-party advertising -- and
    # not one caller anywhere set it. The CLI, the API and the ablation all took
    # the default, so a whole stage could not be run.
    #
    # A default is a default. An absence of a switch is a stage that does not
    # ship.
    from server.cli import main

    parser_error: list[str] = []
    try:
        main(["run", "nonexistent.json", "--bug-mode"])
    except SystemExit as exc:  # argparse rejects an unknown flag with SystemExit(2)
        parser_error.append(str(exc))
    except FileNotFoundError:
        pass  # the flag parsed; the recording is what is missing

    assert parser_error != ["2"], "--bug-mode is not a recognised flag"

    from server.models import AblationConfig

    options = PipelineOptions.for_config(AblationConfig.A2, bug_mode_enabled=True)
    assert options.bug_mode_enabled is True


def test_a0_makes_no_retrieval_of_any_kind(storage: Storage):
    # SS3.5 defines A0 as "single prompt, all context pre-loaded, no tools",
    # and the whole point of the row is SS3.2's claim that without retrieval a
    # model cannot ground anything.
    #
    # The deterministic binding pass is cheap and needs no model, but it still
    # calls a tool, stores a response and hashes it. Letting it run under A0
    # gave that configuration three grounded assertions and 0.33 calls per step
    # in the ablation table -- a "no tools" row that had made retrievals, which
    # is the comparison quietly measuring something other than what it claims.
    from server.models import AblationConfig

    result = run_pipeline(
        recording(),
        grounded_model(),
        storage=storage,
        run_id="run_a0_quiet",
        options=PipelineOptions.for_config(AblationConfig.A0),
    )

    assert result.trace.toolCalls == [], "A0 must not retrieve, deterministically or otherwise"
    assert result.trace.metrics.toolCallsTotal == 0
    # And the consequence, which is the measurement rather than a degradation:
    # this architecture cannot express an ungrounded claim, so a configuration
    # that may not retrieve has nothing it can honestly say.
    assert result.trace.metrics.assertionsTotal == 0
    # Every dropped claim still says why, so the row is explicable.
    assert result.bound is not None and result.bound.deleted >= 1
    assert "no retrieval" in result.bound.claims[0].reason
