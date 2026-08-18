"""The naming stage and its investigation budget (SS9.4, SS3.3).

The claim under test is SS3.1's: that effort varies with difficulty. A chain has
flat cost per step by construction, so a run where an obvious step costs zero
tool calls and an ambiguous one costs several is the observable difference
between the two architectures -- and it is checked here rather than asserted.

Driven by ScriptedModelClient so the control flow is deterministic and offline.
Real model responses go through cassettes, not through this file.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm import CompletionRequest, ScriptedModelClient, answer, calls
from server.models import Confidence, PipelineStage, StopReason
from server.pipeline.name import DEFAULT_BUDGET, name_segments
from server.pipeline.segment import segment_recording
from server.storage.paths import Storage
from tests import factories as f

CONFIRMATION = "Order confirmed"


def build(tmp_path: Path, events=None):
    recording = f.recording(
        events=events
        or [
            f.event(
                "evt_001",
                0,
                at=0.0,
                etype="input",
                tgt=f.target("textbox", "Purchase order number"),
            ),
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
    segments = segment_recording(recording, run_id="run_test")
    store = EvidenceStore(recording=recording, segments=segments)
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    run = storage.run(recording.id, "run_test")
    runner = ToolRunner(store=store, storage=storage, run=run, stage=PipelineStage.name)
    return store, runner


def named(text: str, **extra) -> str:
    return json.dumps({"keyword": "When", "text": text, "confidence": "high", **extra})


# --------------------------------------------------------------------------
# the budget, and what it records
# --------------------------------------------------------------------------


def test_an_obvious_step_costs_no_tool_calls(tmp_path: Path):
    # SS3.3: "a step like click Save -> POST 201 -> alert should cost ZERO
    # tool calls." Spending effort here would be the chain's behaviour, not an
    # agent's.
    store, runner = build(tmp_path)
    model = ScriptedModelClient(
        [answer(named("the tester submits the order")) for _ in store.segments.segments]
    )

    result = name_segments(store, runner, model, model_name="scripted-1")

    assert all(s.investigation.budgetUsed == 0 for s in result.steps)
    assert all(
        s.investigation.stopReason == StopReason.no_investigation_needed for s in result.steps
    )
    assert runner.calls == []


def test_an_ambiguous_step_investigates_and_records_what_it_looked_at(tmp_path: Path):
    store, runner = build(tmp_path)
    segments = len(store.segments.segments)

    # Retrieval is sequential: one call per turn, then a look at what came
    # back. Asking for two at once yields one, and the second turn decides
    # again from what the first returned.
    script = [
        calls(
            ("get_diff", {"eventId": "evt_002"}),
            ("find_text", {"query": CONFIRMATION}),
            preamble=json.dumps({"uncertainties": ["whether the order was actually accepted"]}),
        ),
        calls(("find_text", {"query": CONFIRMATION})),
        answer(named("the tester submits the order form")),
    ]
    script += [answer(named("the tester fills the form"))] * (segments - 1)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")
    first = result.steps[0].investigation

    assert first.budgetUsed == 2
    assert first.stopReason == StopReason.evidence_sufficient
    assert first.initialUncertainty == ["whether the order was actually accepted"]
    assert len(first.toolCallIds) == 2
    # Every id resolves in the run's tool log, which is what makes the
    # why-panel and evidence_retrieved possible.
    assert {c.id for c in runner.calls} >= set(first.toolCallIds)
    assert all(c.stepId == "step_001" for c in runner.calls)


def test_effort_varies_across_steps_within_one_run(tmp_path: Path):
    """The signature of adaptive behaviour: not that effort is high, but that
    it differs. A chain is flat here by construction (SS3.4)."""
    store, runner = build(tmp_path)
    segments = len(store.segments.segments)
    assert segments >= 2, "this test needs at least two segments"

    script = [answer(named("the tester enters the purchase order number"))]
    script += [
        calls(("get_diff", {"eventId": "evt_002"})),
        answer(named("the tester places the order")),
    ]
    script += [answer(named("another step"))] * (segments - 2)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")
    per_step = result.tool_calls_per_step()

    assert len(set(per_step.values())) > 1, f"effort was flat: {per_step}"
    assert per_step["step_001"] == 0
    assert per_step["step_002"] == 1


def test_the_budget_is_enforced_and_reported(tmp_path: Path):
    store, runner = build(tmp_path)
    budget = 3

    def relentless(request: CompletionRequest):
        # A model that would investigate forever, and that ignores being told
        # to stop. The budget caps the retrieval; the turn cap stops the loop.
        del request
        return calls(("get_diff", {"eventId": "evt_002"}))

    result = name_segments(
        store, runner, ScriptedModelClient(relentless), model_name="scripted-1", budget=budget
    )
    first = result.steps[0].investigation

    assert first.budgetUsed == budget
    assert first.budgetMax == budget
    assert first.stopReason == StopReason.budget_exhausted
    # Surfaced to the human with the problem stated, never silently accepted.
    assert result.steps[0].confidence == Confidence.low
    assert any("gave up" in line for line in first.narrative)
    assert len(runner.calls) == budget * len(store.segments.segments)


def test_escalation_is_a_first_class_outcome(tmp_path: Path):
    # SS3.3 -- "an agent that says 'I cannot tell whether the export succeeded'
    # is more useful than one that guesses", and the review UI renders it as a
    # direct question next to the step.
    store, runner = build(tmp_path)
    question = "I could not tell whether the export finished - did a file download?"
    script = [
        answer(
            named(
                "the tester exports the report",
                confidence="low",
                escalation=question,
            )
        )
    ] * len(store.segments.segments)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")
    first = result.steps[0]

    assert first.escalation == question
    assert first.investigation.stopReason == StopReason.escalated
    assert first.investigation.escalationQuestion == question


# --------------------------------------------------------------------------
# output shape
# --------------------------------------------------------------------------


def test_a_model_returning_nothing_usable_does_not_produce_a_confident_step(tmp_path: Path):
    store, runner = build(tmp_path)
    script = [answer("I'm afraid I can't help with that.")] * len(store.segments.segments)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")

    assert all(s.confidence == Confidence.low for s in result.steps)
    assert all(s.text for s in result.steps)
    assert all("no usable step text" in (s.reason or "") for s in result.steps)


def test_the_narrative_reads_as_an_account_of_what_the_agent_did(tmp_path: Path):
    # This is what the review UI's "why this step" panel renders (SS13.3).
    store, runner = build(tmp_path)
    script = [
        calls(
            ("find_text", {"query": CONFIRMATION}),
            preamble=json.dumps({"uncertainties": ["what the outcome was"]}),
        ),
        answer(named("the tester places the order")),
    ] + [answer(named("a step"))] * (len(store.segments.segments) - 1)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")
    narrative = result.steps[0].investigation.narrative

    assert narrative[0].startswith("could not determine:")
    assert any("find_text" in line and "tc_" in line for line in narrative)
    assert narrative[-1] == "evidence sufficient"


def test_every_turn_is_accounted_for_in_the_trace(tmp_path: Path):
    store, runner = build(tmp_path)
    script = [
        calls(("get_diff", {"eventId": "evt_002"})),
        answer(named("the tester places the order")),
    ] + [answer(named("a step"))] * (len(store.segments.segments) - 1)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")

    assert len(result.model_calls) == len(store.segments.segments) + 1
    assert result.model_calls[0].stage == PipelineStage.name
    assert result.model_calls[0].turn == 1
    assert result.model_calls[1].turn == 2


def test_the_baseline_prompt_carries_the_objective_and_the_evidence(tmp_path: Path):
    store, runner = build(tmp_path)
    model = ScriptedModelClient([answer(named("x"))] * len(store.segments.segments))
    name_segments(store, runner, model, model_name="scripted-1")

    prompt = model.requests[0].messages[1].content or ""
    assert "orders over EUR500 require approval" in prompt
    assert "Purchase order number" in prompt
    # The baseline is deliberately compact: everything else is one tool call
    # away, and pre-loading it would make every step cost what the hardest one
    # costs.
    assert len(prompt) < 6000


def test_tools_are_offered_by_default_and_withheld_for_a0(tmp_path: Path):
    store, runner = build(tmp_path)
    n = len(store.segments.segments)

    with_tools = ScriptedModelClient([answer(named("x"))] * n)
    name_segments(store, runner, with_tools, model_name="scripted-1")
    assert with_tools.requests[0].tools, "A1/A2 must offer the evidence tools"

    without = ScriptedModelClient([answer(named("x"))] * n)
    name_segments(store, runner, without, model_name="scripted-1", tools_enabled=False)
    assert without.requests[0].tools == []
    assert without.requests[0].json_output is True


def test_a0_cannot_retrieve_even_if_the_model_asks(tmp_path: Path):
    """SS3.2 -- disable tools and the pipeline cannot emit a valid assertion.
    The naming stage must not quietly grant access when the model asks."""
    store, runner = build(tmp_path)
    n = len(store.segments.segments)

    def asks_then_answers(request: CompletionRequest):
        refused = any("No tools are available" in (m.content or "") for m in request.messages)
        return (
            answer(named("the tester places the order"))
            if refused
            else calls(("find_text", {"query": CONFIRMATION}))
        )

    result = name_segments(
        store,
        runner,
        ScriptedModelClient(asks_then_answers),
        model_name="scripted-1",
        tools_enabled=False,
    )

    assert runner.calls == [], "no retrieval may happen with tools disabled"
    assert all(s.investigation.budgetUsed == 0 for s in result.steps)
    assert len(result.steps) == n


def test_default_budget_matches_the_spec():
    assert DEFAULT_BUDGET == 8


def test_only_one_tool_runs_per_turn(tmp_path: Path):
    """Sequential retrieval, deliberately.

    It matches SS3.3's decide-retrieve-observe loop, and it avoids a concrete
    provider problem: Gemini 3 signs only the first function call of a parallel
    batch, then rejects the replayed conversation because the rest are
    unsigned. A model that asks for three tools gets one, and decides again.
    """
    store, runner = build(tmp_path)
    script = [
        calls(
            ("get_diff", {"eventId": "evt_002"}),
            ("find_text", {"query": CONFIRMATION}),
            ("get_objective", {}),
        ),
        answer(named("the tester places the order")),
    ] + [answer(named("a step"))] * (len(store.segments.segments) - 1)

    result = name_segments(store, runner, ScriptedModelClient(script), model_name="scripted-1")

    assert result.steps[0].investigation.budgetUsed == 1
    assert [c.tool for c in runner.calls] == ["get_diff"]


def test_the_tool_call_id_is_visible_to_the_model(tmp_path: Path):
    """An agent can only cite what it was shown.

    Providers carry a tool_call_id in their own envelope, but the model never
    sees it. Asked to cite one, a real model invented `find_text_0` against an
    otherwise TRUE claim -- correctly rejected by evidence_retrieved, and
    useless output either way. The id now travels inside the content.
    """
    store, runner = build(tmp_path)
    script = [
        calls(("find_text", {"query": CONFIRMATION})),
        answer(named("the tester places the order")),
    ] + [answer(named("a step"))] * (len(store.segments.segments) - 1)

    model = ScriptedModelClient(script)
    name_segments(store, runner, model, model_name="scripted-1")

    tool_message = next(
        m for r in model.requests for m in r.messages if m.role == "tool"
    )
    payload = json.loads(tool_message.content or "{}")
    assert payload["toolCallId"] == "tc_0001"
    assert "result" in payload
    # And the id in the message is the one the runner actually logged.
    assert payload["toolCallId"] in {c.id for c in runner.calls}
