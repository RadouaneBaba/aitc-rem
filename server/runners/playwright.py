"""Replay a generated test case with Playwright.

Split across the process boundary on purpose. Python owns the IR and decides
what should happen; Node owns the browser and reports what did. They talk in
JSON files, which means the job and the result are both artifacts you can read
after the fact -- the same posture as every other stage.

Why not `playwright` from PyPI: it ships its own driver and downloads its own
browser binaries, roughly a gigabyte duplicated beside the ones `pnpm e2e`
already installed, and the two versions then have to be kept in lockstep by
hand. The test *runner* -- retries, traces, auto-retrying assertions, the HTML
report -- is Node-only anyway. The repo already has `@playwright/test`.

Parameters are the interesting constraint. SS7.2 turns every redacted value into
a test parameter, so a replay of a sign-in genuinely needs somebody to supply
`<<password>>`. A run that cannot is reported as **blocked**, not failed: "I
could not run this" and "this does not work" are different findings, and
conflating them would put noise straight into the ablation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from server.models import IRDocument, Recording
from server.runners.base import AssertionOutcome, ReplayResult, StepOutcome
from server.storage.paths import REPO_ROOT

DRIVER = REPO_ROOT / "scripts" / "replay.mjs"

#: How each kind of evidence is re-checked in a live browser. `narration` is
#: absent deliberately: it is a thing the tester said, and no browser can
#: confirm it. Reported as `not_checkable` rather than quietly passed.
CHECKABLE = {"semantic_node", "a11y_node", "url", "network", "console"}

PLACEHOLDER_PREFIX = "<<"


class PlaywrightRunner:
    """Drives `scripts/replay.mjs` over the repo's own Playwright install."""

    name = "playwright"

    def replay(
        self,
        ir: IRDocument,
        *,
        recording: Recording,
        out_dir: Path,
        base_url: str,
        parameters: dict[str, str] | None = None,
    ) -> list[ReplayResult]:
        out_dir.mkdir(parents=True, exist_ok=True)
        parameters = parameters or {}
        results: list[ReplayResult] = []

        for case in ir.testCases:
            job, missing = build_job(case, recording, base_url=base_url, parameters=parameters)
            job_path = out_dir / f"{case.id}.replay-job.json"
            job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")

            if missing:
                results.append(
                    ReplayResult(
                        runner=self.name,
                        case_id=case.id,
                        blocked=(
                            f"needs values for {', '.join(sorted(missing))}. These are the "
                            f"test's parameters (SS7.2); supply them to run it."
                        ),
                        files=[job_path],
                    )
                )
                continue

            results.append(self._run(case.id, job_path, out_dir))
        return results

    # ------------------------------------------------------------------

    def _run(self, case_id: str, job_path: Path, out_dir: Path) -> ReplayResult:
        node = shutil.which("node")
        if node is None or not DRIVER.exists():
            return ReplayResult(
                runner=self.name,
                case_id=case_id,
                blocked="node or scripts/replay.mjs is not available",
                files=[job_path],
            )

        result_path = out_dir / f"{case_id}.replay.json"
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [node, str(DRIVER), str(job_path), str(result_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return ReplayResult(
                runner=self.name,
                case_id=case_id,
                blocked="the replay did not finish within 180s",
                files=[job_path],
            )

        if not result_path.exists():
            return ReplayResult(
                runner=self.name,
                case_id=case_id,
                # The driver's own words. A replay that failed to start is a
                # setup problem, and hiding the reason makes it unfixable.
                blocked=(proc.stderr or proc.stdout or "the replay produced no result").strip()[
                    :400
                ],
                files=[job_path],
            )

        return parse_result(
            self.name,
            case_id,
            json.loads(result_path.read_text(encoding="utf-8")),
            files=[job_path, result_path],
        )


def build_job(
    case: Any, recording: Recording, *, base_url: str, parameters: dict[str, str]
) -> tuple[dict[str, Any], set[str]]:
    """Turn one finished test case into instructions a browser can follow.

    Driven by `eventIds` rather than by step text. The prose is for a human and
    is free to say "submits the order with manager approval"; what runs is the
    three recorded actions underneath it, each with its ranked selectors.
    """
    by_id = {e.id: e for e in recording.events}
    missing: set[str] = set()
    steps: list[dict[str, Any]] = []

    for step in case.steps:
        actions: list[dict[str, Any]] = []
        for event_id in step.eventIds:
            event = by_id.get(event_id)
            if event is None:
                continue
            action = _action(event, parameters, missing)
            if action is not None:
                actions.append(action)

        steps.append(
            {
                "id": step.id,
                "text": step.text,
                "actions": actions,
                "assertions": [
                    {
                        "id": a.id,
                        "literal": a.evidence.literal,
                        "kind": _kind(a.evidence.kind),
                        "text": a.text,
                    }
                    for a in step.assertions
                    if a.accepted
                ],
            }
        )

    return (
        {
            "caseId": case.id,
            "name": getattr(case, "scenarioName", None) or case.title,
            "baseUrl": base_url,
            "startUrl": recording.metadata.startUrl,
            "steps": steps,
        },
        missing,
    )


def _action(event: Any, parameters: dict[str, str], missing: set[str]) -> dict[str, Any] | None:
    kind = event.type.value if hasattr(event.type, "value") else str(event.type)
    selectors = _selectors(event)
    if not selectors:
        return None

    if kind == "input":
        raw = event.target.value or ""
        value = _resolve(raw, parameters, missing)
        return {"type": "fill", "selectors": selectors, "value": value}
    if kind in {"click", "submit"}:
        return {"type": "click", "selectors": selectors}
    if kind == "keydown":
        return {"type": "press", "selectors": selectors, "key": getattr(event, "key", "Enter")}
    # navigate, scroll and the rest are outcomes of the actions above rather
    # than things to re-do; replaying them would fight the application.
    return None


def _selectors(event: Any) -> list[dict[str, str]]:
    """Ranked most stable first -- the order the driver tries them in."""
    s = event.target.selectors
    out = []
    for strategy, value in (
        ("testId", s.testId),
        ("role", s.role),
        ("text", s.text),
        ("css", s.css),
    ):
        if value:
            out.append({"strategy": strategy, "value": value})
    return out


def _resolve(raw: str, parameters: dict[str, str], missing: set[str]) -> str:
    """Substitute the values a redaction placeholder stands for (SS7.2)."""
    if PLACEHOLDER_PREFIX not in raw:
        return raw
    out = raw
    for name, value in parameters.items():
        out = out.replace(f"<<{name}>>", value)
    if PLACEHOLDER_PREFIX in out:
        for part in out.split("<<")[1:]:
            if ">>" in part:
                missing.add(part.split(">>")[0])
    return out


def _kind(value: Any) -> str:
    kind = value.value if hasattr(value, "value") else str(value)
    return kind if kind in CHECKABLE else "not_checkable"


def parse_result(
    runner: str, case_id: str, raw: dict[str, Any], *, files: list[Path]
) -> ReplayResult:
    steps = [
        StepOutcome(
            step_id=str(s.get("stepId") or ""),
            ok=bool(s.get("ok")),
            selector_rank=int(s.get("selectorRank", -1)),
            error=s.get("error"),
            assertions=[
                AssertionOutcome(
                    assertion_id=str(a.get("assertionId") or ""),
                    status=str(a.get("status") or "fail"),
                    literal=str(a.get("literal") or ""),
                    detail=a.get("detail"),
                )
                for a in s.get("assertions", [])
            ],
        )
        for s in raw.get("steps", [])
    ]
    return ReplayResult(
        runner=runner,
        case_id=case_id,
        ran=bool(raw.get("ran", True)),
        blocked=raw.get("blocked"),
        steps=steps,
        files=files,
        warnings=list(raw.get("warnings", [])),
        payload=raw,
    )


__all__ = ["PlaywrightRunner", "build_job", "parse_result"]
