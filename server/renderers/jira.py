"""Jira export (SS11.3).

    "Phase 2: plain issues. Works for 100% of Jira users, zero plugin
     dependency."

Xray and Zephyr model a Test as a real structured entity and are better for it,
but they are two more third-party APIs and they are not installed everywhere. A
plain issue with the steps as a table in the description works for every Jira
there is, which is the whole argument.

**Exporting builds the issue; it does not send it.** Posting needs a site, a
project key and an API token, and a run that silently required credentials
would be a run most people cannot make. The payload is written to disk instead,
so the output is inspectable, diffable and testable with no account at all.

`push()` is the deliberate second step, and it is a separate action on purpose:
credentials come from the environment, a person invokes it, and the export
keeps working for everybody who never will. It creates the issue and attaches
the `.feature`, the evidence sidecar and the recording -- which SS11.3 asks for
and which is what makes the Jira issue self-contained rather than a pointer to
a machine nobody else can reach.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from server.config import ProjectConfig
from server.models import IRDocument, TestCaseIR
from server.pipeline.narrative import build_narrative
from server.renderers.base import ExportResult, case_evidence_rows, case_stem, review_warnings

STEP_TABLE_HEADERS = ("#", "Step", "Expected result")
EVIDENCE_TABLE_HEADERS = ("#", "Expected result", "Proved by this literal", "Retrieved by")


class JiraExporter:
    """One issue payload per test case, in Atlassian Document Format."""

    name = "jira"

    def export(self, ir: IRDocument, *, out_dir: Path, config: ProjectConfig) -> ExportResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        files: list[Path] = []
        issues: list[dict[str, Any]] = []

        # Bug reports go too, as a different issue type -- a Jira project is
        # exactly where both belong, and filing a defect as a Test is how it
        # gets closed as "working as designed".
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
    """The `POST /rest/api/3/issue` body for one test case, or one bug report.

    The issue TYPE is the whole difference, and it is not cosmetic. A defect
    filed as a Test gets triaged by whoever owns the test suite and closed as
    "working as designed"; the same text filed as a Bug reaches the person who
    can fix it. Jira is the one destination where both artifacts belong, which
    is why this exporter takes both while the spreadsheet takes only one.
    """
    fields: dict[str, Any] = {
        "summary": case.scenarioName or case.title,
        "issuetype": {
            "name": config.jira_bug_issue_type
            if case.kind == "bug_report"
            else config.jira_issue_type
        },
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
            # What belongs on the issue, per SS11.3. A bug report has no
            # `.feature` -- Gherkin refuses one (SS14) -- so listing one would
            # send whoever posts this looking for a file that was never
            # written.
            "attachments": [
                f"{case_stem(case, config)}.bug.md"
                if case.kind == "bug_report"
                else f"{case_stem(case, config)}.feature",
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

    # The issue outlives the run directory that `tc_0447` resolves in, so the
    # literal travels with it. Its own section rather than a fourth column on
    # the steps table: whoever executes this test should not have to read past
    # a tool call id to find what to check.
    evidence = _evidence_table(case)
    if evidence is not None:
        content.append(_heading("Evidence"))
        content.append(
            _paragraph(
                "Each row resolved at generation time: the tool call was looked up in the "
                "run's trace, its stored response re-hashed, and the literal confirmed to "
                "occur in it. A row that did not resolve was never written."
            )
        )
        content.append(evidence)

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


def _evidence_table(case: TestCaseIR) -> dict[str, Any] | None:
    """One row per accepted claim, naming the retrieval that proved it."""
    rows = case_evidence_rows(case)
    if not rows:
        return None

    out = [_table_row(EVIDENCE_TABLE_HEADERS, header=True)]
    for entry in rows:
        out.append(
            _table_row(
                [str(entry.step_number), entry.claim, entry.literal, entry.tool_call_id]
            )
        )
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": out,
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


# --------------------------------------------------------------------------
# posting (SS11.3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class JiraCredentials:
    """Where to post, and as whom.

    Read from the environment, never from `project.yaml`. A project file is
    committed; an API token in one is a credential in the repository, and the
    first person to do that will not be the last.
    """

    site: str
    email: str
    token: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> JiraCredentials | None:
        source = env if env is not None else os.environ
        site = (source.get("JIRA_SITE") or "").strip().rstrip("/")
        email = (source.get("JIRA_EMAIL") or "").strip()
        token = (source.get("JIRA_API_TOKEN") or "").strip()
        if not (site and email and token):
            return None
        if "://" not in site:
            site = f"https://{site}"
        return cls(site=site, email=email, token=token)

    @property
    def auth(self) -> tuple[str, str]:
        return (self.email, self.token)


@dataclass
class PushResult:
    """What actually reached Jira."""

    created: list[dict[str, str]] = field(default_factory=list)
    attached: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.created) and not self.failures


def push(
    issues: Sequence[dict[str, Any]],
    *,
    credentials: JiraCredentials,
    attachments_dir: Path | None = None,
    client: Any | None = None,
) -> PushResult:
    """Create each issue, then attach the artifacts it names.

    Separate from `export` and deliberately so. The exporter runs on every run
    and must work for somebody with no Jira account at all; posting is an
    action a person takes on purpose, with credentials they supplied. That
    split is why `export` writes a file rather than asking for a token.

    Attachments are best effort and reported rather than raised. An issue that
    exists without its `.feature` file is recoverable by hand; a run that threw
    away a created issue key because an upload failed is not.
    """
    import httpx

    result = PushResult()
    owned = client is None
    http = client or httpx.Client(timeout=30.0)

    try:
        for issue in issues:
            body = {"fields": issue.get("fields", {})}
            meta = issue.get("aitcRem") or {}
            try:
                response = http.post(
                    f"{credentials.site}/rest/api/3/issue",
                    json=body,
                    auth=credentials.auth,
                    headers={"Accept": "application/json"},
                )
            except Exception as exc:  # noqa: BLE001 - network, reported not raised
                result.failures.append(f"{meta.get('testCaseId', '?')}: {exc}")
                continue

            if response.status_code >= 300:
                result.failures.append(
                    f"{meta.get('testCaseId', '?')}: {response.status_code} {response.text[:200]}"
                )
                continue

            created = response.json()
            key = created.get("key") or created.get("id") or "?"
            result.created.append({"testCaseId": meta.get("testCaseId", "?"), "key": key})

            if attachments_dir is None:
                continue
            for name in meta.get("attachments") or []:
                path = _find_attachment(attachments_dir, name, meta)
                if path is None:
                    continue
                try:
                    upload = http.post(
                        f"{credentials.site}/rest/api/3/issue/{key}/attachments",
                        files={"file": (path.name, path.read_bytes())},
                        auth=credentials.auth,
                        # Jira refuses an attachment without this header. It is
                        # the single most common reason an upload that looks
                        # correct returns 403.
                        headers={"X-Atlassian-Token": "no-check", "Accept": "application/json"},
                    )
                    if upload.status_code < 300:
                        result.attached.append(f"{key}/{path.name}")
                    else:
                        result.failures.append(
                            f"{key}/{path.name}: {upload.status_code} {upload.text[:120]}"
                        )
                except Exception as exc:  # noqa: BLE001
                    result.failures.append(f"{key}/{path.name}: {exc}")
    finally:
        if owned:
            http.close()

    return result


def auto_push_run(run_dir: Path, config: ProjectConfig) -> list[str]:
    """Post a run's Jira payloads right after export, when the project asks for it.

    `jira.auto_push: true` in `project.yaml` opts in. It exists for a private or
    throwaway Jira where the separate `server.cli jira-push` step is pure
    friction; the default stays off because posting creates issues in a shared
    system with no dedup, so a re-export files duplicates.

    Never raises. A missing credential or a network failure is reported as a
    line and the run still succeeds -- the payloads are on disk and
    `jira-push` can send them by hand.
    """
    if not getattr(config, "jira_auto_push", False):
        return []

    payloads = sorted(run_dir.glob("*.jira.json"))
    if not payloads:
        return []

    credentials = JiraCredentials.from_env()
    if credentials is None:
        return [
            "jira auto-push skipped: set JIRA_SITE, JIRA_EMAIL and JIRA_API_TOKEN "
            "(in .env or the environment). The payloads are on disk for `jira-push`."
        ]

    issues = [json.loads(path.read_text(encoding="utf-8")) for path in payloads]
    result = push(issues, credentials=credentials, attachments_dir=run_dir)

    lines = [f"jira: created {c['key']}  ({c['testCaseId']})" for c in result.created]
    lines += [f"jira: attached {name}" for name in result.attached]
    lines += [f"jira: FAILED  {failure}" for failure in result.failures]
    if not lines:
        lines.append("jira auto-push: nothing to send")
    return lines


def _find_attachment(run_dir: Path, name: str, meta: Mapping[str, Any]) -> Path | None:
    """Where an artifact actually is.

    Most live in the run directory. `recording.json` does not -- it belongs to
    the RECORDING, which outlives any one run of it, so it sits under
    `recordings/<id>/` and a run-relative lookup silently skipped it. An issue
    without the recording attached is the one that cannot be re-run by whoever
    picks it up.
    """
    direct = run_dir / name
    if direct.is_file():
        return direct

    recording_id = str(meta.get("recordingId") or "")
    if not recording_id:
        return None
    # runs/<rec>/<run>/ -> repo root -> recordings/<rec>/
    candidate = run_dir.parent.parent.parent / "recordings" / recording_id / name
    return candidate if candidate.is_file() else None


__all__ = ["JiraCredentials", "JiraExporter", "PushResult", "build_issue", "push"]
