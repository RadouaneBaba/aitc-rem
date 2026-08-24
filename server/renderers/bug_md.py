"""The bug report, as something a developer can act on (SS14.2).

Markdown rather than Gherkin, and that is the whole point of the file. Gherkin
is a language for saying what SHOULD happen; a bug report says what did. A
`.feature` whose scenario is a defect would be picked up by a suite and would
fail on purpose, every run, forever.

The shape is what a developer needs before deciding whether to reproduce
something: the steps, the two sentences, and the evidence behind the second one.
`actual` carries its citation into the document -- the same `tc_` id
`evidence_retrieved` resolved -- because "the server returned 500" is worth
exactly as much as the reader's ability to check it.
"""

from __future__ import annotations

from server.config import ProjectConfig
from server.models import IRDocument, TestCaseIR
from server.renderers.base import case_stem


def bug_filename(case: TestCaseIR, config: ProjectConfig | None = None) -> str:
    return f"{case_stem(case, config or ProjectConfig())}.bug.md"


def render_document(ir: IRDocument, *, config: ProjectConfig | None = None) -> dict[str, str]:
    """testCaseId -> markdown, for the bug reports only."""
    config = config or ProjectConfig()
    return {
        case.id: render_bug(case, config=config)
        for case in ir.testCases
        if case.kind == "bug_report" and case.bug is not None
    }


def render_bug(case: TestCaseIR, *, config: ProjectConfig | None = None) -> str:
    config = config or ProjectConfig()
    bug = case.bug
    assert bug is not None

    out: list[str] = [f"# {case.title}", ""]
    if case.objective:
        out.append(f"**What the tester was checking:** {case.objective}")
        out.append("")

    out.append(
        "Recorded from a real session. The steps below are what was actually done, "
        "up to and including the point where it went wrong -- everything after that "
        "was the tester recovering and is not part of reproducing this."
    )
    out.append("")

    out.append("## Steps to reproduce")
    out.append("")
    # The steps themselves, not the Gherkin layout. A repro list is what to DO;
    # Given/When/Then is a way of writing what should happen, and the two
    # sentences that say that have their own headings below.
    for index, step in enumerate(case.steps, start=1):
        marker = " **<- fails here**" if step.id == bug.failureStepId else ""
        out.append(f"{index}. {step.text}{marker}")
    out.append("")

    out.append("## Expected")
    out.append("")
    out.append(bug.expected)
    out.append("")

    out.append("## Actual")
    out.append("")
    out.append(bug.actual)
    if bug.actualEvidence is not None:
        evidence = bug.actualEvidence
        out.append("")
        out.append(
            f"> Grounded in `{evidence.literal}` "
            f"({evidence.kind.value}, {evidence.eventId}, retrieved as "
            f"`{evidence.toolCallId}`)."
        )
    out.append("")

    if bug.failedRequestIds or bug.consoleErrorIds:
        out.append("## Evidence captured at the failure")
        out.append("")
        for event_id in bug.failedRequestIds or []:
            out.append(f"- failed request, at `{event_id}`")
        for event_id in bug.consoleErrorIds or []:
            out.append(f"- uncaught exception, at `{event_id}`")
        out.append("")

    out.append("## Environment")
    out.append("")
    out.append(f"- Browser: {bug.environment.browser}")
    out.append(f"- Viewport: {bug.environment.viewport}")
    out.append(f"- URL: {bug.environment.url}")

    if case.parameters:
        out.append("")
        out.append("## Parameters")
        out.append("")
        out.append(
            "Redaction replaced these in the browser before anything reached disk "
            "(SS7), so this report does not contain them. Supply real values to "
            "reproduce."
        )
        out.append("")
        for parameter in case.parameters:
            out.append(f"- `{parameter.placeholder}` ({parameter.category})")

    out.append("")
    return "\n".join(out)


__all__ = ["bug_filename", "render_bug", "render_document"]
