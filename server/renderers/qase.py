"""Qase export (SS11).

QA teams live in test management tools, not in `.feature` files, and Qase is the
one worth building against rather than merely documenting: it is the only
commercial tool with a real free tier that *includes API access*, so somebody
reviewing this project can open a workspace and run the exporter end to end
without paying anyone. It also has a bulk-create endpoint and a native
`gherkin` step type, which means our artifact goes in more or less as it stands.

Same bargain as `jira.py`, for the same reason: **this builds the payload and
does not send it.** A run that silently required an API token would be a run
most people cannot make. The body is written to disk, ready for one `curl`, and
that command is in the warnings so nobody has to go and find it.

Two shapes, because Qase supports both and they suit different readers:

  * `steps_type: "gherkin"` -- the scenario as Gherkin text, which round-trips
    with what we already produce.
  * `steps_type: "classic"` -- the action/expected grid a manual tester reads in
    the Qase UI. Built from the same IR, so neither is a second-class citizen.

`config/project.yaml`'s `qase.steps` chooses. Classic is the default: the point
of an export is to meet a team where they are, and the grid is what the tool's
own UI shows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.config import ProjectConfig
from server.models import IRDocument, TestCaseIR
from server.pipeline.narrative import build_narrative
from server.renderers.base import ExportResult, review_warnings
from server.renderers.gherkin import render_test_case

#: Qase's own vocabulary. `severity` and `priority` are deliberately left at
#: their defaults: neither is a fact about the recording, and inventing one
#: would put a judgement into an export that nobody made.
DEFAULT_SUITE = "aitc-rem"

ENDPOINT = "https://api.qase.io/v1/case/{project}/bulk"


class QaseExporter:
    """One bulk-create body per run, holding every test case in it."""

    name = "qase"

    def export(self, ir: IRDocument, *, out_dir: Path, config: ProjectConfig) -> ExportResult:
        out_dir.mkdir(parents=True, exist_ok=True)

        cases = [build_case(case, config) for case in ir.testCases]
        # One request for the whole run: Qase takes an array, and N separate
        # calls would be N chances to half-import a suite.
        body = {"cases": cases}

        path = out_dir / f"{ir.recordingId}.qase.json"
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")

        project = config.qase_project_code or "<PROJECT_CODE>"
        warnings = review_warnings(ir)
        warnings.append(
            f"{len(cases)} case(s) were built but not sent. To import them:\n"
            f"    curl -X POST {ENDPOINT.format(project=project)} \\\n"
            f'         -H "Token: $QASE_API_TOKEN" -H "Content-Type: application/json" \\\n'
            f"         --data @{path.name}"
        )
        if not config.qase_project_code:
            warnings.append(
                "No qase.project_code is set in config/project.yaml, so the command above "
                "has a placeholder in it."
            )

        return ExportResult(exporter=self.name, files=[path], warnings=warnings, payload=body)


def build_case(case: TestCaseIR, config: ProjectConfig) -> dict[str, Any]:
    """One entry in Qase's bulk-create array."""
    body: dict[str, Any] = {
        "title": case.scenarioName or case.title,
        "suite_title": config.qase_suite or DEFAULT_SUITE,
        "description": case.description or "",
        # Manual, because that is what this is. A test case generated from a
        # human's session and reviewed by a human is not automated until
        # somebody automates it, and saying otherwise in the tool of record
        # would misreport the suite's coverage.
        "is_flaky": 0,
        "automation": 0,
    }

    if case.tags:
        body["tags"] = list(case.tags)
    if case.preconditions:
        body["preconditions"] = "\n".join(p.text for p in case.preconditions)

    if config.qase_steps == "gherkin":
        body["steps_type"] = "gherkin"
        # The rendered scenario, header and sidecar pointer stripped: Qase wants
        # the Gherkin, not our file's front matter.
        body["steps"] = _gherkin_body(case, config)
    else:
        body["steps_type"] = "classic"
        body["steps"] = _classic_steps(case)

    return body


def _classic_steps(case: TestCaseIR) -> list[dict[str, Any]]:
    """The action/expected grid, which is what a manual tester actually reads.

    Built from the same narrative the feature file uses, so the two cannot drift:
    a step's expected result here is the assertion rendered under it there.
    """
    narrative = build_narrative(case.steps)
    steps: list[dict[str, Any]] = []
    position = 0

    for line in narrative.body:
        if line.is_assertion:
            # Belongs to the row above it: an expected result is not an action.
            if steps:
                existing = steps[-1]["expected_result"]
                steps[-1]["expected_result"] = f"{existing}\n{line.text}" if existing else line.text
            continue
        position += 1
        steps.append(
            {
                "position": position,
                "action": f"{line.keyword} {line.text}",
                "expected_result": "",
                "data": "",
            }
        )
    return steps


def _gherkin_body(case: TestCaseIR, config: ProjectConfig) -> str:
    """The scenario alone, without our header comment or tag line."""
    rendered = render_test_case(case, config=config)
    lines = [
        line
        for line in rendered.splitlines()
        if not line.startswith("#") and not line.strip().startswith("@")
    ]
    return "\n".join(lines).strip("\n")


__all__ = ["ENDPOINT", "QaseExporter", "build_case"]
