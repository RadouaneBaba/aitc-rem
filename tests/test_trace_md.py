"""The evidence sidecar (`server/renderers/trace_md.py`).

SS3.2's binding is enforced against `trace.json` by `evidence_retrieved`. It is
*shown* here, and that separation is the whole point of this file existing: the
feature body went back to being prose a QA lead would have written, and nothing
was lost in the move.

So these tests mostly check that everything the feature file stopped carrying
is carried here instead.
"""

from __future__ import annotations

from server.models import AgentTrace, PipelineStage, StepInvestigation
from server.renderers.trace_md import render_document, render_trace
from tests import factories as f
from tests.test_gherkin import build_case


def investigation(
    ident: str = "inv_001",
    *,
    uncertainties: list[str] | None = None,
    narrative: list[str] | None = None,
    tool_calls: list[str] | None = None,
) -> StepInvestigation:
    return StepInvestigation(
        id=ident,
        stepId="step_003",
        stage=PipelineStage.author,
        initialUncertainty=uncertainties or [],
        toolCallIds=tool_calls or [],
        budgetUsed=len(tool_calls or []),
        budgetMax=8,
        stopReason="evidence_sufficient",
        narrative=narrative or [],
    )


def trace(*investigations: StepInvestigation) -> AgentTrace:
    return AgentTrace(
        schemaVersion="1.0",
        runId="run_test01",
        recordingId="rec_test01",
        projectId="proj_test",
        ownerId="owner_test",
        createdAt=f.NOW,
        config={
            "ablation": "A2",
            "toolsEnabled": True,
            "expectationsEnabled": True,
        },
        toolCalls=[],
        modelCalls=[],
        investigations=list(investigations),
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=[],
    )


# --------------------------------------------------------------------------


def test_every_expected_result_names_the_retrieval_that_licenses_it():
    # The pointer moved out of the feature body, not out of the artifact.
    text = render_trace(build_case(), generated_on="2026-08-17")

    assert "Order confirmed" in text
    assert "tc_0447" in text
    assert "inferred" in text


def test_a_test_case_that_asserts_nothing_says_so_plainly():
    # Silence here would read as "no problems found". It is the opposite.
    case = build_case()
    for step in case.steps:
        step.assertions = []

    text = render_trace(case)
    assert "asserts nothing" in text


def test_the_traceability_the_feature_body_dropped_is_all_here():
    case = build_case()
    case.steps[0].fidelity = ["canvas_interaction"]
    case.steps[0].confidence = "low"
    case.steps[1].selectorHints = [f.selector_hint("css", "button.submit", "low")]
    case.steps[2].escalation = "did a file download?"

    text = render_trace(case)

    assert "evt_012, evt_013" in text
    assert "canvas_interaction" in text
    assert "button.submit" in text
    assert "did a file download?" in text
    assert "step_003" in text


def test_a_fidelity_flag_is_explained_rather_than_named():
    # SS6.8 -- a tool that admits what it does not know stays trusted, but only
    # if the admission is legible. `closed_shadow_root` means nothing to a
    # manual tester.
    case = build_case()
    case.steps[0].fidelity = ["closed_shadow_root"]

    text = render_trace(case)
    assert "part of this component was not readable" in text


def test_the_why_this_step_panel_reads_as_an_account_of_what_the_agent_did():
    # SS13.3 -- a tester who sees that the tool went and looked accepts the
    # output; a confident sentence with no provenance gets doubted.
    case = build_case()
    case.steps[2].investigationRef = "inv_001"
    record = investigation(
        uncertainties=["whether the order was accepted"],
        narrative=['find_text({"query": "Order confirmed"}) -> tc_0447', "evidence sufficient"],
        tool_calls=["tc_0447"],
    )

    text = render_trace(case, trace=trace(record))

    assert "whether the order was accepted" in text
    assert "find_text" in text
    assert "evidence_sufficient" in text
    assert "1 of 8 retrievals used" in text


def test_parameters_tell_the_person_running_the_test_what_to_supply():
    case = build_case(parameters=[f.parameter("user_email_1", "<<user_email_1>>", "email")])
    text = render_trace(case)

    assert "<<user_email_1>>" in text
    assert "Supply real values before running" in text


def test_coverage_suggestions_are_quarantined_out_of_the_feature_file_entirely():
    # SS9.8 -- never rendered as steps, never exported as test cases, always
    # labelled unverified. Keeping them in a different file is the strongest
    # form of that: a suggestion cannot be mistaken for a step if it is not in
    # the file the steps live in.
    case = build_case(
        suggestions=[
            f.coverage_suggestion(
                "sug_001",
                "The email field has type=email; an invalid-email path is untested.",
                "validation_path",
            )
        ]
    )

    from server.renderers.gherkin import render_test_case

    assert "invalid-email" not in render_test_case(case)

    text = render_trace(case)
    assert "UNVERIFIED" in text
    assert "invalid-email" in text


def test_omitted_work_is_accounted_for():
    case = build_case(
        omitted=[f.omitted_segment("seg_004", "exploratory", 3, "browsed the reports page")]
    )
    text = render_trace(case)

    assert "browsed the reports page" in text
    assert "exploratory" in text


def test_a_literal_containing_a_pipe_cannot_break_the_table():
    # A literal is quoted verbatim, so an application that renders "Total | EUR
    # 615" would otherwise split one cell into two and shift every column after
    # it.
    case = build_case()
    case.steps[2].assertions[0].evidence.literal = "Total | EUR 615"

    text = render_trace(case)
    header = next(ln for ln in text.splitlines() if ln.startswith("| ") and "Literal" in ln)
    row = next(ln for ln in text.splitlines() if "Total" in ln)

    assert _cells(row) == _cells(header), row


def _cells(line: str) -> int:
    """Columns in a markdown row, counting an escaped pipe as content."""
    return line.replace(r"\|", "").count("|")


def test_a_document_renders_a_sidecar_per_test_case():
    document = f.ir_document(test_cases=[build_case(), build_case(ident="tc_case_002")])
    rendered = render_document(document)

    assert set(rendered) == {"tc_case_001", "tc_case_002"}
    for text in rendered.values():
        assert text.startswith("# Order checkout - evidence")


def test_the_sidecar_stays_ascii():
    # The rest of the Python sources do; a sidecar full of typographic
    # characters is the one file most likely to be opened in something that
    # mangles them.
    text = render_trace(build_case())
    assert all(ord(ch) < 128 for ch in text)
