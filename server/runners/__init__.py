"""Runners (SS3.5's missing column): execute a finished test case.

A runner is to correctness what a renderer is to readability -- a new file, not
a pipeline change. Both read a finished `IRDocument` and neither may alter it.
"""

from pathlib import Path
from typing import Any

from server.models import IRDocument, Recording
from server.runners.base import AssertionOutcome, ReplayResult, Runner, StepOutcome
from server.runners.playwright import PlaywrightRunner

RUNNERS: dict[str, type] = {PlaywrightRunner.name: PlaywrightRunner}

#: The bundled demo app. Replay is scoped to it on purpose: it is deterministic
#: and local, which is what makes the resulting number a measurement. Against a
#: live third-party site the same harness measures that site's flakiness.
DEFAULT_BASE_URL = "http://localhost:5173"


def replay_all(
    ir: IRDocument,
    *,
    recording: Recording,
    out_dir: Path,
    base_url: str = DEFAULT_BASE_URL,
    parameters: dict[str, str] | None = None,
    storage_state: Path | None = None,
    names: list[str] | None = None,
) -> list[ReplayResult]:
    """Replay every test case with the named runners."""
    chosen = names or [PlaywrightRunner.name]
    out: list[ReplayResult] = []
    for name in chosen:
        runner: Any = RUNNERS.get(name)
        if runner is None:
            out.append(
                ReplayResult(
                    runner=name,
                    case_id="",
                    blocked=f"unknown runner {name!r}; have {sorted(RUNNERS)}",
                )
            )
            continue
        out.extend(
            runner().replay(
                ir,
                recording=recording,
                out_dir=out_dir,
                base_url=base_url,
                parameters=parameters,
                storage_state=storage_state,
            )
        )
    return out


__all__ = [
    "DEFAULT_BASE_URL",
    "RUNNERS",
    "AssertionOutcome",
    "PlaywrightRunner",
    "ReplayResult",
    "Runner",
    "StepOutcome",
    "replay_all",
]
