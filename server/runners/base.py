"""The Runner seam: does the generated test case actually run?

Grounding proves *provenance* -- that a claim points at a retrieval that really
happened. It does not prove *correctness*. An assertion can be perfectly
grounded, perfectly true of the recording, and still describe something that
would not hold if somebody ran the test tomorrow.

Nothing in this project had ever executed a generated test case, so the ablation
measured how honest the output was and never whether it worked. This closes
that: replay the recorded actions against the application and re-check each
accepted assertion. It gives A0's fabricated citations somewhere to be *wrong*
rather than merely unsupported, which is a stronger claim than the harness could
previously make.

Shaped like `renderers/base.Exporter` on purpose -- a `name`, a no-arg
constructor, one keyword-only method over a finished `IRDocument`. A renderer
turns the IR into something a person reads; a runner turns it into something a
machine does. Neither is allowed to change the pipeline (SS11).

**The `.feature` file is not executed, and cannot be.** No Gherkin runner in any
language binds a step to anything but a hand-written step definition matched on
the step's text. The alternative -- constraining the model to a closed set of
step templates so a fixed step-definition library could match them -- would buy
executability by giving up the readable prose that is the product. So replay
drives the IR and the recording directly: the step text is for humans, the
`eventIds` and `selectorHints` under it are what actually runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from server.models import IRDocument


@dataclass
class StepOutcome:
    """What happened when one step was replayed."""

    step_id: str
    ok: bool
    #: Which selector candidate resolved, 0 being the most stable. -1 when none
    #: did. Averaged across a run this is a robustness measurement rather than
    #: an opinion about which selector strategy is best.
    selector_rank: int = -1
    error: str | None = None
    assertions: list[AssertionOutcome] = field(default_factory=list)


@dataclass
class AssertionOutcome:
    """Whether an accepted expected result still held on replay."""

    assertion_id: str
    #: `pass`, `fail`, or `not_checkable` -- an assertion grounded in narration
    #: is a statement the tester made out loud, and there is nothing in a
    #: browser to re-check it against. Reported rather than silently skipped.
    status: str
    literal: str = ""
    detail: str | None = None


@dataclass
class ReplayResult:
    """One test case, replayed."""

    runner: str
    case_id: str
    ran: bool = False
    #: Why the case could not be attempted at all: a missing parameter, an
    #: unreachable application. Distinct from failing, and the distinction
    #: matters -- "could not run" is not evidence about the test case.
    blocked: str | None = None
    steps: list[StepOutcome] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload: Any = None

    @property
    def passed(self) -> bool:
        return self.ran and all(s.ok for s in self.steps)

    @property
    def assertions_checked(self) -> int:
        return sum(1 for s in self.steps for a in s.assertions if a.status != "not_checkable")

    @property
    def assertions_held(self) -> int:
        return sum(1 for s in self.steps for a in s.assertions if a.status == "pass")

    @property
    def mean_selector_rank(self) -> float:
        ranks = [s.selector_rank for s in self.steps if s.selector_rank >= 0]
        return sum(ranks) / len(ranks) if ranks else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "caseId": self.case_id,
            "ran": self.ran,
            "blocked": self.blocked,
            "passed": self.passed,
            "assertionsChecked": self.assertions_checked,
            "assertionsHeld": self.assertions_held,
            "meanSelectorRank": round(self.mean_selector_rank, 3),
            "steps": [
                {
                    "stepId": s.step_id,
                    "ok": s.ok,
                    "selectorRank": s.selector_rank,
                    "error": s.error,
                    "assertions": [
                        {
                            "assertionId": a.assertion_id,
                            "status": a.status,
                            "literal": a.literal,
                            "detail": a.detail,
                        }
                        for a in s.assertions
                    ],
                }
                for s in self.steps
            ],
            "warnings": self.warnings,
        }


@runtime_checkable
class Runner(Protocol):
    """Execute a finished test case against the application it came from."""

    name: str

    def replay(
        self,
        ir: IRDocument,
        *,
        recording: Any,
        out_dir: Path,
        base_url: str,
        parameters: dict[str, str] | None = None,
    ) -> list[ReplayResult]: ...


__all__ = ["AssertionOutcome", "ReplayResult", "Runner", "StepOutcome"]
