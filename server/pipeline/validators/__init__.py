"""Stage 6 -- the validation gate (SS9.7).

    "These are unglamorous and they catch the majority of what would
     otherwise destroy trust. Write them before the stages they guard."

Which is why this package exists before the naming stage does.

The gate is deterministic and uses no model. It runs every validator, always,
and reports what each one did -- including the ones that had nothing to check,
because "no subject" and "never ran" have to stay distinguishable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
from server.pipeline.validators.base import ValidationContext
from server.pipeline.validators.consistency import (
    event_coverage,
    library_verbatim,
    mutation_claimed,
    selector_resolvable,
)
from server.pipeline.validators.grounding import (
    assertion_grounding,
    claim_total,
    element_exists,
    evidence_retrieved,
    no_pruned_assertion,
    provenance_supported,
)
from server.pipeline.validators.output import (
    gherkin_parses,
    no_placeholder_leak,
    suggestions_quarantined,
)
from server.pipeline.validators.style import gherkin_style

#: Order is presentation only -- every validator always runs. Grounding first
#: because it is the one the whole architecture exists to make possible.
VALIDATORS = [
    evidence_retrieved,
    assertion_grounding,
    provenance_supported,
    element_exists,
    mutation_claimed,
    event_coverage,
    gherkin_parses,
    gherkin_style,
    library_verbatim,
    no_placeholder_leak,
    selector_resolvable,
    no_pruned_assertion,
    suggestions_quarantined,
]


@dataclass
class ValidationReport:
    """The outcome of one pass of the gate."""

    results: list[ValidatorResult] = field(default_factory=list)

    @property
    def failures(self) -> list[ValidatorResult]:
        return [r for r in self.results if r.status == ValidatorStatus.fail]

    @property
    def warnings(self) -> list[ValidatorResult]:
        return [r for r in self.results if r.status == ValidatorStatus.warn]

    @property
    def rejected(self) -> bool:
        """Should the output be regenerated?"""
        return any(r.action == ValidatorAction.reject for r in self.results)

    @property
    def hard_failed(self) -> bool:
        """Must the output not be rendered at all? (no_placeholder_leak only)"""
        return any(r.action == ValidatorAction.hard_fail for r in self.results)

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.hard_failed

    def by_validator(self, name: ValidatorName) -> list[ValidatorResult]:
        return [r for r in self.results if r.validator == name]

    def summary(self) -> str:
        lines: list[str] = []
        for validator in VALIDATORS:
            name = ValidatorName(validator.__name__)
            rows = self.by_validator(name)
            failures = [r for r in rows if r.status == ValidatorStatus.fail]
            warns = [r for r in rows if r.status == ValidatorStatus.warn]
            skips = [r for r in rows if r.status == ValidatorStatus.skip]

            if failures:
                mark, note = "FAIL", f"{len(failures)} problem(s)"
            elif warns:
                mark, note = "WARN", f"{len(warns)} warning(s)"
            elif skips:
                mark, note = "skip", skips[0].skipReason or ""
            else:
                mark = "ok"
                note = next((r.message for r in rows if r.message), "")
            lines.append(f"  [{mark:>4}] {name.value:<20} {note}")

            for row in failures + warns:
                target = " ".join(
                    part
                    for part in (row.testCaseId, row.stepId, row.assertionId)
                    if part is not None
                )
                lines.append(f"         - {target}: {row.message}")
        return "\n".join(lines)


def validate(ctx: ValidationContext) -> ValidationReport:
    """Run the whole gate."""
    report = ValidationReport()
    for validator in VALIDATORS:
        report.results.extend(validator(ctx))
    return report


def grounding_rate(ctx: ValidationContext, report: ValidationReport) -> float:
    """Share of assertions whose evidence resolved.

    SS17.1 -- logged from day one as a free regression signal, and the headline
    metric of the ablation (SS3.5). Reported as 1.0 when there are no
    assertions, since a run that claims nothing has fabricated nothing.
    """
    total = claim_total(ctx.ir)
    if total == 0:
        return 1.0
    ungrounded = len(
        [
            r
            for r in report.by_validator(ValidatorName.evidence_retrieved)
            if r.status == ValidatorStatus.fail
        ]
    )
    return max(0.0, (total - ungrounded) / total)


__all__ = [
    "VALIDATORS",
    "ValidationContext",
    "ValidationReport",
    "claim_total",
    "grounding_rate",
    "validate",
]
