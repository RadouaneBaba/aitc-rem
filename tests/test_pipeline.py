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
from server.models import (
    AblationConfig,
    ExpectationSet,
    PipelineStage,
    Recording,
    ValidatorStatus,
)
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
    if system.startswith("You are a QA engineer"):
        return "author"
    if system.startswith("You are a QA lead reading a recording"):
        return "expectations"
    if system.startswith("You are a QA lead. Somebody hands you"):
        return "judge"
    if system.startswith("You are reading a finished QA test case"):
        return "coverage"
    return "author"


def signs_it_off(_request: CompletionRequest):
    """A judge with nothing to say. The normal case, and the quiet one."""
    return answer(json.dumps({"findings": []}))


def sends_it_back(check: str = "verdict_fails_on_broken_build", severity: str = "fail"):
    """A judge that objects, so the revision path can be exercised at all.

    A real model cannot be asked to fail a document on command, which is the
    same reason `ScriptedModelClient` exists for the fabricating author.
    """

    def behave(_request: CompletionRequest):
        return answer(
            json.dumps(
                {
                    "findings": [
                        {
                            "check": check,
                            "severity": severity,
                            "scenario": "Submitting a valid order shows the confirmation",
                            "step": "step_002",
                            "what": "The verdict rests on a banner that appears either way.",
                            "fix": "Assert the order reference the application computed.",
                        }
                    ]
                }
            )
        )

    return behave


def document_over(request: CompletionRequest, *, literal: str | None = None) -> str:
    """A feature file covering whatever events the index lists, plus its annotations.

    The stand-in reads the session index it was handed, exactly as the author
    does, so the same fake works on the two-event fixture and on a recording
    made by the extension. Accounting for every event is not optional --
    `event_coverage` is the net under the author's freedom to choose step
    boundaries, and a fake that ignored it would let a regression through.

    It emits the shape the author emits now: Gherkin prose, and one annotation
    per step line in document order. A fake still emitting the old JSON-only
    shape would exercise only the fallback, which is exactly the trap this
    project already fell into once with the `scenario_break` factory.
    """
    import re

    # messages[1] is the user prompt, which carries the session index. Reading
    # the LAST message instead picks up the tool response on the second turn,
    # whose only event id is the one that matched -- and both steps then claim
    # the same event, which `event_coverage` correctly rejects.
    digest = request.messages[1].content or ""
    events = list(dict.fromkeys(re.findall(r"evt_\d+", digest)))
    if not events:
        events = ["evt_001", "evt_002"]
    head, tail = events[:1], events[1:] or events[:1]

    body = [
        "Feature: Order checkout",
        "",
        "  An order is placed and confirmed.",
        "",
        "  Scenario: Submitting a valid order shows the confirmation",
        "    Given the tester fills in the purchase order",
        "    When the tester places the order",
    ]
    annotations: list[dict] = [
        {"kind": "step", "id": "step_001", "role": "setup", "events": head},
        {"kind": "step", "id": "step_002", "role": "test_step", "events": tail},
    ]
    if literal:
        body.append("    Then the confirmation banner appears")
        annotations.append(
            {"kind": "verdict", "evidence": {"eventId": tail[-1], "literal": literal}}
        )
    else:
        annotations[-1]["whyNot"] = "Nothing retrieved for this step names the outcome."

    return json.dumps(
        {
            "feature": "\n".join(body) + "\n",
            "title": "Order checkout",
            "description": "An order is placed and confirmed.",
            "tags": ["checkout"],
            "annotations": annotations,
        }
    )


def grounded_model() -> ScriptedModelClient:
    """An author that retrieves, then cites exactly what it retrieved.

    It reads the tool response rather than assuming: quoting a string it did not
    actually find is the mistake this whole gate exists to catch, so the
    well-behaved stand-in must not make it.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return signs_it_off(request)

        tool_results = [m for m in request.messages if m.role == "tool"]
        if not tool_results:
            return calls(
                ("find_text", {"query": CONFIRMATION}),
                preamble=json.dumps({"uncertainties": ["what the outcome was"]}),
            )

        # Tool results arrive wrapped as {"toolCallId": ..., "result": ...} so a
        # real model can see the id. This stand-in deliberately does NOT use it:
        # the author names only the literal and the code resolves which
        # retrieval contains it, so an agent that invents an id gains nothing.
        payload = json.loads(tool_results[-1].content or "{}")
        matches = (payload.get("result") or {}).get("matches") or []
        # Nothing found means nothing to claim, and the author says so in
        # `whyNot` rather than claiming anyway. That is the correct outcome, not
        # a failure.
        return answer(document_over(request, literal=CONFIRMATION if matches else None))

    return ScriptedModelClient(behave)


def fabricating_model() -> ScriptedModelClient:
    """An author that claims something it never retrieved.

    A real model cannot be asked to do this on command, which is exactly why the
    scripted client exists. Note what it is no longer able to fake: there is no
    `toolCallId` field for it to fill in, so the only lie available is to quote
    a literal it did not see -- and that is caught by looking for the string in
    its own retrievals.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return signs_it_off(request)
        return answer(document_over(request, literal="Everything went perfectly"))

    return ScriptedModelClient(behave)


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


# --------------------------------------------------------------------------
# the spine
# --------------------------------------------------------------------------


def test_a_run_produces_every_artifact(storage: Storage):
    result = run_pipeline(recording(), grounded_model(), storage=storage, run_id="run_001")

    for name in ("segments", "expectations", "author", "judge", "ir", "trace"):
        assert result.artifacts[name].exists(), f"{name}.json was not written"
    # Each stage reads a file and writes a file, so a wrong output can be
    # traced to the stage that produced it (SS9.1). One pass of each: the
    # scripted model's document draws no `fail` from the judge and nothing at
    # the gate rejects it, so the revision round never opens. That is the
    # normal shape -- `test_a_judge_fail_buys_exactly_one_more_author_round`
    # is the other one.
    assert [s.stage.value for s in result.trace.stages] == [
        "segment",
        "expectations",
        "author",
        "render",
        "validate",
        "judge",
        "coverage",
    ]
    assert result.revision_rounds == 1
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
    a literal, and `evidence.citation` searches the retrievals the agent
    actually made for a response containing that string. This model quotes
    something no tool ever returned, so there is nothing to resolve and the
    claim never reaches the feature file to be rejected there.

    The test that this replaces asserted the weaker property: that a fabricated
    citation was caught. Catching it was never as good as making it
    unexpressible.
    """
    result = run_pipeline(recording(), fabricating_model(), storage=storage, run_id="run_002")

    claimed = [a.text for c in result.ir.testCases for s in c.steps for a in s.assertions]
    assert claimed == [], f"an unretrieved claim reached the output: {claimed}"

    # And it is not silently absent -- which is the half the old pipeline got
    # wrong. The claim is recorded as refused WITH ITS REASON, and the step
    # carries a sentence a tester can act on instead of just ending.
    assert result.document.refused, "a refused claim must be recorded, not simply missing"
    assert "nothing this run retrieved" in result.document.refused[0]["reason"]
    assert any(s.why_not for s in result.document.steps)

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
    """`no_placeholder_leak` is the only hard fail, and it erases the output.

    A real model cannot be asked to leak on command, which is what the scripted
    client is for. Note the shape: the leak is in the STEP TEXT, not in a
    citation -- redaction happens in the browser, so a value reaching the
    document at all means something upstream is wrong, and shipping the file
    anyway would put the secret in an xlsx and a Jira issue too.
    """

    def behave(request: CompletionRequest):
        if stage_of(request) != "author":
            return answer(json.dumps({"expectations": [], "suggestions": []}))
        return answer(
            json.dumps(
                {
                    "feature": "Sign in",
                    "description": "",
                    "tags": [],
                    "scenarios": [{"name": "Signing in", "steps": ["step_001", "step_002"]}],
                    "steps": [
                        {
                            "id": "step_001",
                            "keyword": "Given",
                            "role": "setup",
                            "text": "the tester signs in as tester@example.com",
                            "events": ["evt_001"],
                        },
                        {
                            "id": "step_002",
                            "keyword": "When",
                            "role": "test_step",
                            "text": "the tester places the order",
                            "events": ["evt_002"],
                        },
                    ],
                }
            )
        )

    result = run_pipeline(
        recording(), ScriptedModelClient(behave), storage=storage, run_id="run_003"
    )

    assert result.report.hard_failed
    assert result.rendered == {}
    assert not list(result.run.root.glob("*.feature"))


# --------------------------------------------------------------------------
# the judge, and the one revision it can ask for
# --------------------------------------------------------------------------


def judging_model(judge, *, author_literal: str | None = CONFIRMATION) -> ScriptedModelClient:
    """A well-behaved author with a judge of the caller's choosing.

    "Well-behaved" has to include RETRIEVING, and for a long time this fixture
    did not. It answered on the first turn quoting a literal it had never
    looked up, so `_attach_claim` refused every verdict it wrote and each of
    these judge tests ran against a document with no assertions in it. Nothing
    said so, because a refused claim never becomes an assertion and so
    `evidence_retrieved` had nothing to reject -- the same hole
    `_revision_feedback` now closes, met first in the test suite.

    Same shape as the `scenario_break` factory trap already in CLAUDE.md: a
    fixture that can build an input the real path cannot survive is a fixture
    that keeps a test green over a path that never ran.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return judge(request)

        if author_literal and not [m for m in request.messages if m.role == "tool"]:
            return calls(("find_text", {"query": author_literal}))
        return answer(document_over(request, literal=author_literal))

    return ScriptedModelClient(behave)


def test_a_judge_fail_buys_exactly_one_more_author_round(storage: Storage):
    # SS9.9 with the routing table removed. The old loop was bounded at three
    # attempts PER STAGE and resolved one finding in nine, because five of the
    # survivors were `coherence` and had no route in the table at all. There is
    # one route now -- back to the author, which wrote the document -- and the
    # bound is on rounds rather than on stages.
    #
    # Two, not more. Every rewrite risks `merge_repeats` folding two steps into
    # one, and a document nobody signs after one honest revision is saying
    # something upstream is wrong.
    result = run_pipeline(
        recording(), judging_model(sends_it_back()), storage=storage, run_id="run_001"
    )

    assert result.revision_rounds == 2
    assert [s.stage.value for s in result.trace.stages].count("author") == 2
    assert [s.stage.value for s in result.trace.stages].count("judge") == 2


def test_a_weak_finding_is_reported_and_does_not_spend_a_round(storage: Storage):
    # `weak` is what a QA lead would sign after an edit. Rewriting a document
    # that was already acceptable costs an author round and risks a step, so
    # weak findings reach the trace and the reviewer without buying a rewrite.
    result = run_pipeline(
        recording(),
        judging_model(sends_it_back(severity="weak")),
        storage=storage,
        run_id="run_001",
    )

    assert result.revision_rounds == 1
    assert result.judgement is not None
    assert [f.severity for f in result.judgement.findings] == ["weak"]
    assert result.judgement.fails == []


def test_the_judge_never_reaches_the_tester(storage: Storage):
    # The critic put `coherence: weak` in the review UI, in a vocabulary nobody
    # outside the pipeline reads. A finding is input to the author; what a
    # reviewer sees is prose -- the step's own `whyNot`, in their language.
    result = run_pipeline(
        recording(),
        judging_model(sends_it_back(severity="weak")),
        storage=storage,
        run_id="run_001",
    )

    feature = next(iter(result.rendered.values()))
    assert "verdict_fails_on_broken_build" not in feature
    assert "weak" not in feature
    assert "The verdict rests on" not in feature


def test_an_unresolved_finding_is_recorded_as_exhausted_rather_than_dropped(storage: Storage):
    # `Converged` measured how much of what the critic said the loop was
    # ALLOWED to act on, because findings it never reached vanished from the
    # trace. This project has met that denominator trap in six columns; a
    # finding that survives the last round stays visible as one.
    result = run_pipeline(
        recording(), judging_model(sends_it_back()), storage=storage, run_id="run_001"
    )

    assert result.trace.repairAttempts
    last = result.trace.repairAttempts[-1]
    assert last.exhausted
    assert last.trigger.value == "judge"
    # And it says what was wrong in sentences, not in a category. A finding the
    # author is meant to act on has to be readable by the author.
    assert last.finding


def test_the_first_attempt_gate_is_the_first_attempts(storage: Storage):
    # SS3.5 asks for the first-attempt rate by name, and a second round
    # overwrites `report` entirely. Reporting only the second would be the
    # revision loop marking its own homework.
    result = run_pipeline(
        recording(), judging_model(sends_it_back()), storage=storage, run_id="run_001"
    )

    from server.pipeline.run import _pass_rate

    assert result.first_report is not None
    assert result.revision_rounds == 2
    assert result.trace.metrics.validatorFirstPassRate == pytest.approx(
        _pass_rate(result.first_report)
    )
    # And it is a different object from the final report, not an alias -- the
    # coverage stage edits `report.results` in place and would otherwise
    # backdate itself into the first-attempt number.
    assert result.first_report is not result.report


def test_a_revision_that_would_lose_a_step_is_refused_whole(storage: Storage):
    # `merge_repeats` folds any two ADJACENT steps whose text matches exactly,
    # so a rewrite prompted with "this verdict proves nothing" can make one
    # step's name generic enough to swallow its neighbour. That changes the step
    # COUNT between two attempts of the same run -- SS3.6 promises it does not
    # -- and moves `Yield`'s denominator, so the metric improves because a step
    # vanished.
    #
    # `narrative.would_collapse` is this guard for a single-step rewrite. A
    # whole-document rewrite has no index to ask about, so the question becomes
    # whether the revision contains such a pair at all.
    same = "the tester places the order"

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return sends_it_back()(request)
        # The revision is recognisable by the feedback block the author is
        # handed, which is the same thing a real model would key on.
        if "came back" in (request.messages[1].content or ""):
            return answer(
                json.dumps(
                    {
                        "feature": "Order checkout",
                        "description": "An order is placed and confirmed.",
                        "tags": ["checkout"],
                        "scenarios": [
                            {"name": "Placing an order", "steps": ["step_001", "step_002"]}
                        ],
                        "steps": [
                            {
                                "id": "step_001",
                                "keyword": "When",
                                "role": "test_step",
                                "text": same,
                                "events": ["evt_001"],
                            },
                            {
                                "id": "step_002",
                                "keyword": "When",
                                "role": "test_step",
                                "text": same,
                                "events": ["evt_002"],
                            },
                        ],
                    }
                )
            )
        return answer(document_over(request, literal=CONFIRMATION))

    result = run_pipeline(
        recording(), ScriptedModelClient(behave), storage=storage, run_id="run_001"
    )

    # The first document shipped, whole. Not a patched version of the second.
    assert [s.text for s in result.document.steps] == [
        "the tester fills in the purchase order",
        "the tester places the order",
    ]
    assert any("previous document" in r.finding for r in result.trace.repairAttempts)


def test_a_judge_that_fails_degrades_the_run_rather_than_ending_it(storage: Storage):
    # A judgement is worth less than the document it judges. A run lost to a
    # critic is exactly what the rebuild deleted, so the stage says it did not
    # run rather than returning a clean verdict it never reached.
    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            raise RuntimeError("the provider is having a day")
        # Retrieves first, like any author whose claims are meant to survive:
        # a stand-in that quotes without looking has every verdict refused, and
        # this test would then be measuring the refusal path rather than the
        # judge's failure.
        if not [m for m in request.messages if m.role == "tool"]:
            return calls(("find_text", {"query": CONFIRMATION}))
        return answer(document_over(request, literal=CONFIRMATION))

    result = run_pipeline(
        recording(), ScriptedModelClient(behave), storage=storage, run_id="run_001"
    )

    assert result.judgement is not None
    assert "the provider is having a day" in result.judgement.failed
    assert result.rendered
    assert result.revision_rounds == 1


def test_a0_has_no_judge_because_it_cannot_look(storage: Storage):
    # The judge is gated on its own flag, never on an ablation arm, so an arm is
    # never the difference between two changes at once. A0 is the exception the
    # rule implies rather than an exception to it: its first question is whether
    # a verdict would survive a broken build, and answering that means looking.
    result = run_pipeline(
        recording(),
        judging_model(sends_it_back()),
        storage=storage,
        run_id="run_001",
        options=PipelineOptions.for_config(AblationConfig.A0),
    )

    assert result.judgement is None
    assert result.revision_rounds == 1
    assert "judge" not in [s.stage.value for s in result.trace.stages]


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


def test_the_oracle_may_retrieve_so_its_guess_names_a_value(storage: Storage):
    """An expectation nobody can tick is not an oracle.

    This stage ran with no tools until 2026-08-29, and the argument for that was
    about a stage LICENSING a claim from a summary. It does not transfer: this
    one writes a QUESTION for a human, and the difference between "the list
    should update" and "the list should drop from 24 products to 9" is a value
    the session index does not always carry. Bounded at `GUESS_BUDGET`, because
    the tester is waiting on the screen this feeds.
    """

    def behave(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return signs_it_off(request)
        if stage == "expectations":
            if not [m for m in request.messages if m.role == "tool"]:
                return calls(("get_diff", {"eventId": "evt_002"}))
            return answer(
                json.dumps(
                    {
                        "expectations": [
                            {
                                "eventIds": ["evt_002"],
                                "action": "You placed the order.",
                                "expected": f"the page should say {CONFIRMATION!r}",
                                "observed": "it did",
                                "fromTester": False,
                            }
                        ]
                    }
                )
            )
        return answer(document_over(request, literal=None))

    result = run_pipeline(
        recording(), ScriptedModelClient(behave), storage=storage, run_id="run_oracle"
    )

    # The retrieval happened, and it is attributed to the stage that made it
    # rather than to the author -- `_calls_per_step` reads the trace, and its
    # claim is that effort is what the run spent on a step, whoever spent it.
    retrieved = [c for c in result.trace.toolCalls if c.stage == PipelineStage.expectations]
    assert retrieved, "the oracle asked for a tool and did not get one"

    assert result.expectations is not None
    assert CONFIRMATION in result.expectations.expectations[0].expected


def test_the_oracle_cannot_retrieve_where_the_configuration_has_no_tools(storage: Storage):
    """`tools_enabled` is threaded from the run, not decided inside the stage.

    A0 disables the oracle outright, so this can never fire there today -- which
    is exactly why it is pinned. A stage whose tool access depends on which
    caller happened to construct it is the defect, not the symptom.
    """
    result = run_pipeline(
        recording(),
        fabricating_model(),
        storage=storage,
        run_id="run_oracle_a0",
        options=PipelineOptions(tools_enabled=False),
    )
    assert result.trace.toolCalls == []


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
    # `grounded_model` produces output the judge has nothing to say about, so
    # this is the null case: the oracle changed nothing on this recording, and
    # the sentence has to say that rather than imply a difference it cannot see.
    report = run_ablation([recording()], grounded_model(), storage=storage, model_name="scripted-1")
    finding = report.finding()
    assert "must not be read alone" in finding
    assert "nothing to say" in finding
    assert report.rows["A2"].judge_findings == 0
    # And the vacuous reading is refused by construction: there is no rate over
    # zero findings to report as 1.0. A count of nothing is a count of nothing,
    # which is the whole reason `Converged` was replaced by two counts.
    assert report.rows["A2"].judge_fails == 0
    assert "Converged" not in report.table()


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

    # One investigation for the whole document, and one coverage pass. It used
    # to be one drafting investigation plus one per contested claim across four
    # more stages; the retrieval that settled a claim now happens inside the
    # author's own loop, which is where SS3.3 always said it belonged.
    from collections import Counter

    per_stage = Counter(i.stage.value for i in result.trace.investigations)
    assert per_stage["author"] == 1, "the document is written once, by one author"
    assert per_stage["coverage"] == 1

    feature = next(iter(result.rendered.values()))
    assert "Feature:" in feature
    # The evidence left the feature body and became a document beside it. The
    # citation itself is untouched: the pointer still resolves in the trace,
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
    from server.pipeline.author import (
        AuthoredDocument,
        AuthoredScenario,
        AuthoredStep,
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

    drafted = AuthoredDocument(
        title="t",
        description="",
        tags=[],
        scenarios=[
            AuthoredScenario(
                name="s",
                steps=[
                    AuthoredStep(
                        "step_001", "Given", SegmentRole.setup, "the tester signs in", ["evt_001"]
                    ),
                    AuthoredStep(
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


def test_a_step_always_says_who_is_doing_it():
    # A step is a sentence about a person. Dropped, it reads as an instruction
    # to whoever is holding the document and matches no step definition. This
    # is not hypothetical: a prompt edit whose worked examples omitted the
    # subject produced "submits an order totalling "615"" with nobody
    # submitting anything, and the prompt had said to include it twice.
    from server.config import ProjectConfig
    from server.pipeline.author import with_subject

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


def _drafted_over(event_ids: list[str], per_step: int = 1):
    """A drafted document with `per_step` events per step, for shape tests."""
    from server.models import SegmentRole
    from server.pipeline.author import AuthoredDocument, AuthoredScenario, AuthoredStep

    steps = [
        AuthoredStep(
            step_id=f"step_{i + 1:03d}",
            keyword="When",
            role=SegmentRole.test_step,
            text=f"step {i + 1}",
            event_ids=event_ids[i * per_step : (i + 1) * per_step],
        )
        for i in range((len(event_ids) + per_step - 1) // per_step)
    ]
    return AuthoredDocument(
        title="t",
        description="",
        tags=[],
        scenarios=[AuthoredScenario(name="one scenario", steps=steps)],
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
    """A model that returns one authored document and nothing else of interest."""

    def behave(request: CompletionRequest):
        if stage_of(request) != "author":
            return answer(json.dumps({"expectations": [], "suggestions": []}))
        return answer(json.dumps(payload))

    return ScriptedModelClient(behave)


ONE_STEP = {
    "feature": "Order checkout",
    "description": "",
    "tags": [],
    "scenarios": [{"name": "Placing an order", "steps": ["step_001"]}],
    "steps": [
        {
            "id": "step_001",
            "keyword": "When",
            "role": "test_step",
            "text": "the tester places the order",
            "events": ["evt_002"],
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
    # which `_prune` then removed; the author now says outright which events
    # are not part of the test, and `event_coverage` is what makes that
    # accounting mandatory rather than polite.
    payload = {
        **ONE_STEP,
        "omitted": [
            {
                "events": ["evt_001"],
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


def test_an_event_the_author_forgot_is_rejected(storage: Storage):
    # The net under the author's freedom to choose step boundaries. It decides
    # what a step is now, so "every event lands in a step or in an explicit
    # omission" is the one structural promise left, and it is code.
    result = run_pipeline(recording(), _drafts(ONE_STEP), storage=storage, run_id="run_dropped")

    coverage = [r for r in result.report.results if r.validator.value == "event_coverage"]
    assert coverage and coverage[0].status == ValidatorStatus.fail
    assert "evt_001" in (coverage[0].message or "")


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


def test_a0_makes_no_retrieval_of_any_kind(storage: Storage):
    # SS3.5 defines A0 as "single prompt, all context pre-loaded, no tools",
    # and the whole point of the row is SS3.2's claim that without retrieval a
    # model cannot ground anything.
    #
    # It also gets no oracle, which is the other half of the row: A0 is the
    # architecture this project replaces, and that architecture could neither
    # look nor ask.
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
    # And it says so rather than just coming out empty: every step carries a
    # sentence explaining why it has no verdict. An empty scenario and a
    # scenario that explains itself read identically in a metrics table and not
    # at all alike to a person.
    assert all(s.why_not for s in result.document.steps)


def _rejected_set(recording_id: str, *event_ids: str) -> ExpectationSet:
    """The oracle a tester produces by pressing "Not right" on one action.

    `rejected` is the strongest source in the file: it says the recording
    contains a bug, and `author._apply_rejections` stamps `bug=True` on the step
    deterministically rather than asking the author to notice.
    """
    from server.models import Expectation, ExpectationSource

    return ExpectationSet(
        schemaVersion="1.0",
        recordingId=recording_id,
        createdAt=f.NOW,
        expectations=[
            Expectation(
                id="exp_001",
                eventIds=list(event_ids),
                action="You placed the order.",
                expected="the order should have been held for approval",
                observed="the order was confirmed",
                source=ExpectationSource.rejected,
            )
        ],
    )


def test_a_rejected_expectation_produces_a_bug_report_instead_of_a_crash(storage: Storage):
    """Pressing "Not right" must reach a written bug report, not a ValidationError.

    `BugDetail.environment` is required by the schema and `_bug_detail` did not
    pass it, so every construction raised out of `_assemble` and killed the run.
    Nothing caught it because the path needs a step that is BOTH `bug=True` and
    carries an accepted assertion, and that needs a human to have answered the
    confirmation screen -- which, across 14 expectations on disk, nobody ever
    had. The crash was unreachable and therefore invisible, and the work that
    makes the screen reachable is what would have shipped it.
    """
    rec = recording()
    result = run_pipeline(
        rec,
        grounded_model(),
        storage=storage,
        run_id="run_rejected",
        # Both events, because one rejected expectation routinely spans the
        # action and the check -- "you placed the order" is a form filled and a
        # button pressed. Which of them the author hangs its verdict on is its
        # decision, and the report has to survive either answer.
        options=PipelineOptions(expectations=_rejected_set(rec.id, "evt_001", "evt_002")),
    )

    case = result.ir.testCases[0]
    assert case.kind == "bug_report"
    assert case.bug is not None
    # The expected result stands exactly as written -- a bug report's whole
    # point is that the test SHOULD fail on this build.
    assert case.bug.expected
    assert case.bug.actual == "the order was confirmed"

    # The environment is what a triager needs to reproduce, and the URL comes
    # from the failing step's own event rather than from `startUrl`.
    assert case.bug.environment.browser == "Chrome/140"
    assert case.bug.environment.viewport == "1280x800"
    assert case.bug.environment.url == "https://demo.local/checkout"

    # A bug report is not Gherkin -- `render_document` skips it and `bug_md`
    # writes it -- so the run must have produced the markdown and no feature.
    assert list(result.run.root.glob("*.bug.md"))


def test_an_author_that_quotes_without_looking_is_told_so(storage: Storage):
    """The hole that shipped a document with no verdicts and a clean gate.

    When the author quotes a literal it never retrieved, `_attach_claim` drops
    the claim and writes a `whyNot` -- so it never becomes an assertion, so
    `evidence_retrieved` has nothing to reject, so the loop sees a green gate
    and stops. Measured on a live run of `keyhole`: the author wrote two
    correct verdicts quoting a count that was plainly in the session index,
    made zero tool calls, had both silently refused, and shipped a feature file
    whose scenarios end on a `When`.

    Every validator was right. The gate is not the thing that was wrong -- the
    author simply never learned that the one thing it had to do, it had not
    done. It is also the finding the author can always act on, because the fix
    is entirely in its hands.
    """

    def never_looks(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return signs_it_off(request)
        return answer(document_over(request, literal=CONFIRMATION))

    result = run_pipeline(
        recording(), ScriptedModelClient(never_looks), storage=storage, run_id="run_001"
    )

    # The claim really was dropped, and the gate really was clean about it --
    # that half was never in doubt.
    assert result.document.refused
    assert not [r for r in result.report.results if r.status == ValidatorStatus.fail]

    # What is new is that the author was told, in a sentence naming the fix.
    told = [a.finding for a in result.trace.repairAttempts]
    assert told, "a refused claim reached nobody, which is how this shipped"
    assert "the confirmation banner appears" in told[0]
    assert "Retrieve the thing you are claiming" in told[0]
    # And it spent the round it was worth spending.
    assert result.revision_rounds == 2


def test_an_author_that_writes_verdicts_without_looking_is_sent_back_to_look(storage: Storage):
    """The nudge, and why it is code rather than another sentence in the prompt.

    The prompt already says this plainly and at length. Measured on `keyhole`
    against a real model: six tools offered, ZERO called, two correct verdicts
    written quoting a count -- both silently refused by the citation check, and
    the document shipped with scenarios ending on a `When`. The author had read
    the string in the session index and reasonably concluded it had evidence.

    It is the mirror of the budget nudge that has always been in `investigate`:
    a model going past its budget is told to stop, and a model that never
    started was told nothing.
    """
    turns: list[int] = []

    def looks_only_when_told(request: CompletionRequest):
        stage = stage_of(request)
        if stage == "expectations":
            return answer(json.dumps({"expectations": []}))
        if stage == "coverage":
            return answer(json.dumps({"suggestions": []}))
        if stage == "judge":
            return signs_it_off(request)

        nudged = any(
            "made no retrievals" in (m.content or "") for m in request.messages if m.role == "user"
        )
        turns.append(1)
        if nudged and not [m for m in request.messages if m.role == "tool"]:
            return calls(("find_text", {"query": CONFIRMATION}))
        return answer(document_over(request, literal=CONFIRMATION))

    result = run_pipeline(
        recording(), ScriptedModelClient(looks_only_when_told), storage=storage, run_id="run_001"
    )

    assert result.trace.toolCalls, "the author was never sent back to look"
    # And the verdict it wrote all along now stands, on evidence it actually has.
    claims = [a for c in result.ir.testCases for s in c.steps for a in s.assertions]
    assert [a.text for a in claims] == ["the confirmation banner appears"]
    assert claims[0].evidence.toolCallId == result.trace.toolCalls[0].id
    assert not result.document.refused


def test_a_document_of_pure_refusals_is_not_nudged(storage: Storage):
    # Forcing a retrieval out of an author that claimed nothing is the
    # mandatory-tool-call anti-pattern: it lifted calls-per-step from 1.56 to
    # 2.17 and flattened the effort spread from 1.08 to 0.16, which is an agent
    # that stopped deciding. Refusing IS an answer.
    from server.pipeline.author import _unretrieved_verdicts

    assert _unretrieved_verdicts({"annotations": [{"kind": "step", "whyNot": "nothing showed"}]}) == ""
    assert _unretrieved_verdicts({}) == ""
    assert _unretrieved_verdicts(
        {"annotations": [{"kind": "verdict", "evidence": {"literal": "Order confirmed"}}]}
    )
