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


__all__ = ["ExportResult", "Exporter", "case_stem", "review_warnings"]
