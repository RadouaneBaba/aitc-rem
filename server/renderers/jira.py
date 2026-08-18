"""Jira export (SS11.3).

    "Phase 2: plain issues. Works for 100% of Jira users, zero plugin
     dependency."

Xray and Zephyr model a Test as a real structured entity and are better for it,
but they are two more third-party APIs and they are not installed everywhere. A
plain issue with the steps as a table in the description works for every Jira
there is, which is the whole argument.

**This builds the issue; it does not send it.** Posting needs a site, a project
key and an API token, and a run that silently required credentials would be a
run most people cannot make. The payload is written to disk instead, so the
output is inspectable, diffable and testable with no account at all -- and
`push()` is one function away for when a project supplies its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.config import ProjectConfig
from server.models import IRDocument, TestCaseIR
from server.pipeline.narrative import build_narrative
from server.renderers.base import ExportResult, case_stem, review_warnings

STEP_TABLE_HEADERS = ("#", "Step", "Expected result")


class JiraExporter:
    """One issue payload per test case, in Atlassian Document Format."""

    name = "jira"

    def export(self, ir: IRDocument, *, out_dir: Path, config: ProjectConfig) -> ExportResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        issues: list[dict[str, Any]] = []

        for case in ir.testCases:
            issue = build_issue(case, config)
            issues.append(issue)
            path = out_dir / f"{case_stem(case, config)}.jira.json"
            path.write_text(json.dumps(issue, indent=2, ensure_ascii=False), encoding="utf-8")
            files.append(path)

        warnings = review_warnings(ir)
        warnings.append(
            f"{len(issues)} issue(s) were built but not sent. Posting needs a Jira site, "
            f"a project key and an API token; the payloads are on disk for review."
        )

        return ExportResult(exporter=self.name, files=files, warnings=warnings, payload=issues)


def build_issue(case: TestCaseIR, config: ProjectConfig) -> dict[str, Any]:
    """The `POST /rest/api/3/issue` body for one test case."""
    fields: dict[str, Any] = {
        "summary": case.scenarioName or case.title,
        "issuetype": {"name": config.jira_issue_type},
        "description": _description(case),
        "labels": _labels(case, config),
    }
    if config.jira_project_key:
        fields["project"] = {"key": config.jira_project_key}

    return {
        "fields": fields,
        # Not part of the Jira body. Carried alongside so whoever posts this
        # knows what else belongs on the issue, per SS11.3.
        "aitcRem": {
            "testCaseId": case.id,
            "recordingId": case.recordingId,
            "runId": case.runId,
            "attachments": [
                f"{case_stem(case, config)}.feature",
                f"{case_stem(case, config)}.trace.md",
                "recording.json",
            ],
        },
    }


# --------------------------------------------------------------------------
# Atlassian Document Format
# --------------------------------------------------------------------------


def _description(case: TestCaseIR) -> dict[str, Any]:
    content: list[dict[str, Any]] = []

    if case.description:
        content.append(_paragraph(case.description))
    if case.objective:
        content.append(_panel("info", f"Objective as stated by the tester: {case.objective}"))

    if case.preconditions:
        content.append(_heading("Preconditions"))
        content.append(_bullets([p.text for p in case.preconditions]))

    content.append(_heading("Steps"))
    content.append(_steps_table(case))

    if case.parameters:
        content.append(_heading("Parameters"))
        content.append(_paragraph("Supply a real value for each of these before running the test."))
        content.append(_bullets([f"{p.placeholder} ({p.category})" for p in case.parameters]))

    if case.omitted:
        total = sum(o.eventCount for o in case.omitted)
        content.append(
            _panel(
                "note",
                f"{total} action(s) were left out of this test case as exploratory or "
                f"abandoned. Nothing was discarded -- they are in the run's evidence.",
            )
        )

    # SS9.8 -- suggestions are quarantined into a panel that says what they are,
    # never into the steps table.
    if case.suggestions:
        content.append(_heading("Coverage suggestions (unverified)"))
        content.append(_panel("warning", "Not part of this test and not grounded in a retrieval."))
        content.append(_bullets([s.text for s in case.suggestions]))

    return {"type": "doc", "version": 1, "content": content}


def _steps_table(case: TestCaseIR) -> dict[str, Any]:
    narrative = build_narrative(case.steps)
    rows = [_table_row(STEP_TABLE_HEADERS, header=True)]

    number = 0
    pending: list[list[str]] = []
    for line in narrative.body:
        if line.is_assertion:
            if pending:
                pending[-1][2] = f"{pending[-1][2]}\n{line.text}" if pending[-1][2] else line.text
            continue
        number += 1
        pending.append([str(number), f"{line.keyword} {line.text}", ""])

    for cells in pending:
        rows.append(_table_row(cells))

    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": rows,
    }


def _table_row(cells, *, header: bool = False) -> dict[str, Any]:
    kind = "tableHeader" if header else "tableCell"
    return {
        "type": "tableRow",
        "content": [
            {"type": kind, "attrs": {}, "content": [_paragraph(str(cell))]} for cell in cells
        ],
    }


def _paragraph(text: str) -> dict[str, Any]:
    """ADF has no newline character inside a text node; a line break is a node.

    Left as one text node per line rather than collapsed, so an expected result
    stacked under another stays on its own line in Jira.
    """
    lines = str(text).split("\n")
    content: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if index:
            content.append({"type": "hardBreak"})
        if line:
            content.append({"type": "text", "text": line})
    return {"type": "paragraph", "content": content or [{"type": "text", "text": ""}]}


def _heading(text: str, level: int = 3) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _bullets(items: list[str]) -> dict[str, Any]:
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [_paragraph(item)]} for item in items if item],
    }


def _panel(kind: str, text: str) -> dict[str, Any]:
    return {"type": "panel", "attrs": {"panelType": kind}, "content": [_paragraph(text)]}


def _labels(case: TestCaseIR, config: ProjectConfig) -> list[str]:
    """Jira rejects a label containing a space, so they are hyphenated."""
    out: list[str] = []
    for tag in [*case.tags, *config.tags]:
        label = tag.strip().lstrip("@").replace(" ", "-")
        if label and label not in out:
            out.append(label)
    return out


__all__ = ["JiraExporter", "build_issue"]
