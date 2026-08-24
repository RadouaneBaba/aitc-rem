"""Stage 8b -- the bounded repair loop (SS9.9).

    "Findings are not merely reported -- the offending stage re-runs with the
     criticism as additional input, and with tool access to resolve what the
     critic flagged."

    generate -> validate (code) -> critique (model) -> repair -> validate -> ...

Bounded at three attempts. On exhaustion the step is surfaced to the human with
the unresolved finding stated plainly -- never silently accepted.

**Which stage re-runs is a table, not a judgment.** A model asked "what should
we do about this?" would answer differently on two runs of the same recording,
and this is the one place in the pipeline where being wrong costs a rewrite of
work that was already correct. So the mapping below is code, and two of its rows
are deliberately empty:

`event_coverage` rejects when an event appears in no step and no omission. That
is an assembly bug -- something in `_assemble` dropped it -- and re-running a
model cannot fix it. Worse, a re-run might produce different step text and make
the failure *look* different, which is how a structural bug becomes a haunting.

`no_placeholder_leak` hard-fails when a secret reached the rendered output. The
feature file is not written at all (SS7.1). Asking a model again for a step that
contained a password is the wrong instinct in a way worth naming: the fix is
upstream in redaction, and a repair that happened to produce a clean sentence
would hide a redaction hole rather than close it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server.evidence.store import EvidenceStore
from server.models import (
    PipelineStage,
    RepairAttempt,
    RepairTrigger,
    ValidatorAction,
    ValidatorName,
    ValidatorStatus,
)
from server.pipeline.critic import CriticResult, Finding
from server.pipeline.name import NamingResult, intent_notes

#: SS9.9's bound. Three attempts per stage, then the human is told.
MAX_REPAIR_ATTEMPTS = 3

#: Which stage owns a rejection. Everything absent from this table is either
#: warn-only by design, or not a model's fault -- see the module docstring.
VALIDATOR_REPAIR: dict[ValidatorName, PipelineStage] = {
    # The claim, or its citation, is wrong. The assert stage retrieves again.
    ValidatorName.evidence_retrieved: PipelineStage.assert_,
    ValidatorName.assertion_grounding: PipelineStage.assert_,
    ValidatorName.element_exists: PipelineStage.assert_,
    ValidatorName.mutation_claimed: PipelineStage.assert_,
    ValidatorName.no_pruned_assertion: PipelineStage.assert_,
    # The step TEXT is what broke -- a reuse claim that does not match the
    # library entry, or prose the Gherkin parser could not read.
    ValidatorName.library_verbatim: PipelineStage.name,
    ValidatorName.gherkin_parses: PipelineStage.name,
}

#: SS9.9's five judgement axes, and which of them a re-run can act on.
#:
#: `coherence` and `state_jump` are absent on purpose. Acting on either means
#: re-running composition, which decides merges, splits and case boundaries --
#: so it can change the step COUNT, and SS3.6 promises the same recording
#: produces the same count every time. A reproducibility guarantee is worth more
#: than an automatic fix for a finding a human can act on in five seconds.
CRITIC_REPAIR: dict[str, PipelineStage] = {
    "step_name": PipelineStage.name,
    "vocabulary": PipelineStage.name,
    "assertion": PipelineStage.assert_,
}


@dataclass(frozen=True)
class Target:
    """One step to re-run, why, and which stage owns it."""

    stage: PipelineStage
    step_id: str
    finding: str
    trigger: RepairTrigger


@dataclass
class RepairOutcome:
    attempts: list[RepairAttempt] = field(default_factory=list)
    #: Findings that ran out of budget unresolved. These become `criticNotes`
    #: on the step and a `Warning` on the case -- SS9.9's "surfaced to the human
    #: with the unresolved finding stated plainly".
    unresolved: list[Target] = field(default_factory=list)

    @property
    def findings_raised(self) -> int:
        """The denominator. `repairConvergenceRate` over zero findings is
        vacuously 1.0, in exactly the way `groundingRate` is vacuously 1.0 for a
        configuration that abstains -- so the two are always reported together
        (SS3.5)."""
        return len({(a.stage, a.targetStepId, a.finding) for a in self.attempts})

    @property
    def convergence_rate(self) -> float:
        raised = self.findings_raised
        if not raised:
            return 0.0
        resolved = len(
            {(a.stage, a.targetStepId, a.finding) for a in self.attempts if a.resolved}
        )
        return resolved / raised


def protected_steps(store: EvidenceStore, naming: NamingResult) -> set[str]:
    """Steps whose wording is not the tool's to change.

    Two sources, both promises made elsewhere and both enforced here rather
    than trusted to a prompt:

      * a step named from a tester's intent note (SS6.7). The popup tells the
        tester it will be used "word for word", and Milestone 8 already shipped
        one bug where a promise like that went unread on the server side.
      * a step copied character-for-character from an approved library entry
        (SS12.2). Rewriting it makes `library_verbatim` reject on the next
        pass -- so a repair would trade a critic finding for a validator
        rejection, which is not progress.
    """
    dictated = set(intent_notes(store))
    return {
        named.step_id
        for named in naming.steps
        if named.library_ref or named.segment_id in dictated
    }


def targets(
    report,
    findings: list[Finding],
    *,
    protected: set[str],
    known_steps: set[str],
) -> list[Target]:
    """What to re-run, deduplicated per (stage, step).

    Several validators can reject the same step for related reasons, and a step
    asked twice in one attempt would cost two model calls to answer one
    question. The findings are joined instead, so the stage sees everything
    wrong with the step at once.
    """
    collected: dict[tuple[PipelineStage, str], list[tuple[RepairTrigger, str]]] = {}

    for row in report.results:
        if row.action != ValidatorAction.reject or row.status != ValidatorStatus.fail:
            continue
        stage = VALIDATOR_REPAIR.get(row.validator)
        # No stepId means the rejection is about the document, not a step --
        # `event_coverage` is the case that matters, and it is not repairable
        # anyway. Nothing to re-run.
        if stage is None or not row.stepId:
            continue
        collected.setdefault((stage, row.stepId), []).append(
            (RepairTrigger.validator, f"{row.validator.value}: {row.message or 'rejected'}")
        )

    for finding in findings:
        stage = CRITIC_REPAIR.get(finding.kind)
        if stage is None or not finding.step_id:
            continue
        collected.setdefault((stage, finding.step_id), []).append(
            (RepairTrigger.critic, f"{finding.kind}: {finding.message}")
        )

    out: list[Target] = []
    for (stage, step_id), reasons in collected.items():
        if step_id not in known_steps:
            continue
        # Renaming a protected step is refused at the source. An assertion
        # repair on the same step is fine -- what is protected is the WORDING,
        # not the expected result.
        if stage == PipelineStage.name and step_id in protected:
            continue
        trigger = (
            RepairTrigger.validator
            if any(t == RepairTrigger.validator for t, _ in reasons)
            else RepairTrigger.critic
        )
        out.append(
            Target(
                stage=stage,
                step_id=step_id,
                finding=" | ".join(text for _, text in reasons),
                trigger=trigger,
            )
        )
    return sorted(out, key=lambda t: (t.step_id, t.stage.value))


def still_failing(report, target: Target) -> bool:
    """Did the rejection that triggered this repair survive it?"""
    return any(
        row.stepId == target.step_id
        and row.status == ValidatorStatus.fail
        and row.action == ValidatorAction.reject
        and VALIDATOR_REPAIR.get(row.validator) == target.stage
        for row in report.results
    )


def still_flagged(critic: CriticResult | None, target: Target) -> bool:
    """Did the critic raise the same kind of finding against the step again?

    Judged by re-asking rather than by "the text changed". A rewrite is not
    evidence of an improvement -- that is the whole reason this is a loop and
    not a single pass.
    """
    if critic is None:
        return False
    return any(
        f.step_id == target.step_id and CRITIC_REPAIR.get(f.kind) == target.stage
        for f in critic.findings
    )


def record(
    outcome: RepairOutcome,
    target: Target,
    *,
    attempt: int,
    resolved: bool,
    exhausted: bool,
) -> None:
    outcome.attempts.append(
        RepairAttempt(
            stage=target.stage,
            attempt=attempt,
            trigger=target.trigger,
            finding=target.finding,
            targetStepId=target.step_id,
            resolved=resolved,
            exhausted=exhausted,
        )
    )
    if exhausted and not resolved:
        outcome.unresolved.append(target)


__all__ = [
    "CRITIC_REPAIR",
    "MAX_REPAIR_ATTEMPTS",
    "VALIDATOR_REPAIR",
    "RepairOutcome",
    "Target",
    "protected_steps",
    "record",
    "still_failing",
    "still_flagged",
    "targets",
]
