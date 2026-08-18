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
from server.models import AblationConfig, Recording
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


def grounded_model() -> ScriptedModelClient:
    """An agent that retrieves, then cites exactly what it retrieved.

    It reads the tool response rather than assuming: citing an event it did not
    actually find the string at is the mistake this whole gate exists to catch,
    so the well-behaved stand-in must not make it.
    """

    def behave(request: CompletionRequest):
        tool_results = [m for m in request.messages if m.role == "tool"]
        baseline = request.messages[1].content or ""
        # Only claim a change when the evidence shows one, or mutation_claimed
        # will rightly reject the step.
        mutated = "-> 201" in baseline or "-> 200" in baseline
        text = "the tester places the order" if mutated else "the tester fills in the form"

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
        base = {"keyword": "When", "text": text, "confidence": "high"}
        if not matches:
            # Nothing was found, so there is nothing to claim. Omitting the
            # expected result is the correct outcome, not a failure.
            return answer(json.dumps(base))

        return answer(
            json.dumps(
                {
                    **base,
                    "expected": {
                        "text": "the confirmation banner appears",
                        "literal": CONFIRMATION,
                        "toolCallId": call_id,
                        "eventId": matches[0]["eventId"],
                        "kind": "semantic_node",
                    },
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
        del request
        return answer(
            json.dumps(
                {
                    "keyword": "When",
                    "text": "the tester fills in the form",
                    "confidence": "high",
                    "expected": {
                        "text": "the confirmation banner appears",
                        "literal": CONFIRMATION,
                        "toolCallId": "tc_0447",
                        "eventId": "evt_002",
                        "kind": "semantic_node",
                    },
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

    for name in ("segments", "ir", "trace"):
        assert result.artifacts[name].exists(), f"{name}.json was not written"
    # Each stage reads a file and writes a file, so a wrong output can be
    # traced to the stage that produced it (SS9.1).
    assert [s.stage.value for s in result.trace.stages] == ["segment", "name", "render", "validate"]
    assert result.rendered
    assert list(result.run.root.glob("*.feature"))


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
    report = run_ablation([recording()], grounded_model(), storage=storage, model_name="scripted-1")
    finding = report.finding()
    assert "A1 and A2 are within 5 points" in finding
    assert "must not be read alone" in finding


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
    assert len(result.naming.steps) == len(result.trace.investigations)

    feature = next(iter(result.rendered.values()))
    assert "Feature:" in feature
    assert "# evidence:" in feature
    # Every event in the recording is accounted for in the output.
    covered = {e for c in result.ir.testCases for s in c.steps for e in s.eventIds}
    assert covered == {e.id for e in real.events}
