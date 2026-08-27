"""The Exporter seam (SS11).

    "One IR, three renderers. No format is second-class, and a fourth output
     means writing a renderer, not touching the pipeline."

That claim is only true if the formats sit behind one interface, so this is it.
Gherkin, Excel and Jira each implement `Exporter` and none of them can reach
back into the pipeline: they read a finished `IRDocument` and write files.

Xray and Zephyr are deferred (SS4), but they are deferred *behind this
interface* -- the shape is fixed now so that adding them later is a new file
rather than a refactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from server.config import ProjectConfig
from server.models import IRDocument, TestCaseIR


@dataclass
class ExportResult:
    """What an exporter produced, and what it could not."""

    exporter: str
    files: list[Path] = field(default_factory=list)
    #: Anything the reader has to know before trusting the output -- a step
    #: whose confidence was low, a Jira issue that was built but not sent.
    warnings: list[str] = field(default_factory=list)
    #: Built but not delivered. The Jira exporter puts its issue payload here
    #: rather than posting it, so a run is inspectable without credentials.
    payload: Any = None

    def __str__(self) -> str:
        names = ", ".join(p.name for p in self.files) or "nothing"
        return f"{self.exporter}: {names}"


@runtime_checkable
class Exporter(Protocol):
    """SS11.3's interface, in Python.

    Takes the whole document rather than one test case: Excel wants a workbook
    with a sheet per case, and Jira wants to know how many issues it is about
    to create. An exporter that only cares about one case iterates.
    """

    name: str

    def export(self, ir: IRDocument, *, out_dir: Path, config: ProjectConfig) -> ExportResult: ...


def case_stem(case: TestCaseIR, config: ProjectConfig) -> str:
    """One filename stem per test case, shared by every exporter.

    So `tc_rec_X.feature`, `tc_rec_X.trace.md` and `tc_rec_X.jira.json` sit
    together in a directory and obviously belong to each other.
    """
    return config.feature_stem(case_id=case.id, title=case.title, recording_id=case.recordingId)


def test_cases(ir: IRDocument) -> list[TestCaseIR]:
    """The reusable test cases, without the bug reports (SS14).

    A bug report shares the IR and almost nothing else: it is historical rather
    than future-facing, its steps end at a failure, and its central claim is
    that something is wrong. A spreadsheet of test cases with one row that says
    "this never worked" is a spreadsheet nobody can filter. `bug_md.py` renders
    those, and the Jira exporter files them as a different issue type.
    """
    return [case for case in ir.testCases if case.kind != "bug_report"]


def review_warnings(ir: IRDocument) -> list[str]:
    """What a reader must not miss, in any format.

    SS13.4 -- low-confidence steps and escalations are visually distinct and
    never hidden. A spreadsheet has no styling conventions the reader shares,
    so it says so in words instead.
    """
    out: list[str] = []
    for case in ir.testCases:
        escalations = [s for s in case.steps if s.escalation]
        low = [s for s in case.steps if s.confidence.value == "low"]
        unasserted = [s for s in case.steps if not any(a.accepted for a in s.assertions)]

        if escalations:
            out.append(
                f"{case.id}: {len(escalations)} step(s) have an unanswered question from the agent"
            )
        if low:
            out.append(f"{case.id}: {len(low)} step(s) are low confidence")
        if len(unasserted) == len(case.steps) and case.steps:
            out.append(
                f"{case.id}: no step has an expected result, so this documents a "
                f"procedure rather than a test"
            )
    return out


@dataclass(frozen=True)
class EvidenceRow:
    """One accepted claim, with the retrieval that proved it.

    Every field is read off the `IRDocument` -- no exporter reaches into the run
    directory for it -- which is what lets the audit trail travel with a file
    somebody emailed.
    """

    case_id: str
    case_title: str
    step_number: int
    step_text: str
    claim: str
    literal: str
    tool_call_id: str
    event_id: str
    provenance: str


def evidence_rows(ir: IRDocument) -> list[EvidenceRow]:
    """The `.trace.md` evidence table, for exporters that leave the run directory.

    `runs/` is local and gets cleared; a workbook in somebody's Downloads and a
    Jira issue in somebody's browser both outlive it. Carrying `evt_004` alone
    makes the claim's provenance unresolvable the moment the artifact travels,
    which is the one property this project has that a test-case generator does
    not -- so the literal and the retrieval go WITH the export.

    Deliberately not the step grid. SS11.2's reasoning still holds: `tc_0447` in
    front of a tester executing a step is noise at the wrong moment. This is a
    second surface, for the person deciding whether to BELIEVE the test rather
    than the person running it.
    """
    return [row for case in ir.testCases for row in case_evidence_rows(case)]


def case_evidence_rows(case: TestCaseIR) -> list[EvidenceRow]:
    """`evidence_rows` for one test case. Jira builds an issue at a time."""
    from server.pipeline.narrative import build_narrative

    numbers: dict[str, tuple[int, str]] = {}
    number = 0
    for line in build_narrative(case.steps).body:
        if line.is_assertion:
            continue
        number += 1
        numbers[line.step.id] = (number, line.text)

    rows: list[EvidenceRow] = []
    for step in case.steps:
        position, text = numbers.get(step.id, (0, step.text))
        for assertion in step.assertions:
            if not assertion.accepted:
                continue
            rows.append(
                EvidenceRow(
                    case_id=case.id,
                    case_title=case.scenarioName or case.title,
                    step_number=position,
                    step_text=text,
                    claim=assertion.text,
                    literal=assertion.evidence.literal,
                    tool_call_id=assertion.evidence.toolCallId,
                    event_id=assertion.evidence.eventId,
                    provenance=assertion.provenance.value,
                )
            )
    return rows


__all__ = [
    "EvidenceRow",
    "ExportResult",
    "Exporter",
    "case_evidence_rows",
    "case_stem",
    "evidence_rows",
    "review_warnings",
    "test_cases",
]
