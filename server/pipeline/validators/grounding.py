"""Validators that decide whether a claim was licensed by a retrieval.

`evidence_retrieved` is the mechanism SS3.2 calls the single most important
technical decision in the document. It is not enough that a quoted string
exists somewhere in the recording: it must have appeared in a tool response
THIS agent actually received during THIS run.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.models import (
    Assertion,
    Provenance,
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
)
from server.pipeline.validators.base import (
    ValidationContext,
    contains_literal,
    passed,
    result,
    skipped,
)
from server.util.canonical import response_hash


def _assertions(ctx: ValidationContext):
    for case in ctx.ir.testCases:
        for step in case.steps:
            for assertion in step.assertions:
                yield case, step, assertion
        claim = bug_claim(case)
        if claim is not None:
            yield claim


def bug_claim(case) -> tuple | None:
    """A bug report's `actual`, as a claim the gate can check (SS14.2).

    "`expected` and `actual` are subject to the same evidence binding (SS3.2) --
    `actual` must quote something the agent retrieved."

    Yielded into the same loop as every other assertion rather than checked by a
    branch of its own, because a second implementation of evidence binding is a
    second thing that can be wrong -- and this is the one sentence a developer
    reads before deciding whether to go and reproduce something.
    """
    bug = getattr(case, "bug", None)
    if bug is None or bug.actualEvidence is None:
        return None
    step = next((s for s in case.steps if s.id == bug.failureStepId), None)
    if step is None:
        return None
    return (
        case,
        step,
        Assertion(
            id=f"{case.id}_actual",
            text=bug.actual,
            provenance=Provenance.inferred,
            evidence=bug.actualEvidence,
            accepted=True,
        ),
    )


def claim_total(ir) -> int:
    """Every claim the gate checks, which is the denominator of the grounding rate.

    Kept in step with `_assertions` above: a bug report's `actual` is checked by
    `evidence_retrieved`, so counting only step assertions here would let one
    rejected bug claim push the rate below what the run actually produced.
    """
    return sum(len(s.assertions) for c in ir.testCases for s in c.steps) + sum(
        1 for c in ir.testCases if bug_claim(c) is not None
    )


def evidence_retrieved(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """Resolve every assertion's pointer, verify the hash, confirm the literal.

    Three ways to fail, and each is a different lie:

      * the tool call does not exist       -- the agent never looked
      * the stored response fails its hash -- the log changed after the fact
      * the literal is not in the response -- it looked, then embellished

    A single-prompt architecture cannot do this at any price: there is no
    retrieval event to point at.
    """
    checked = 0
    for case, step, assertion in _assertions(ctx):
        checked += 1
        evidence = assertion.evidence
        call = ctx.tool_call(evidence.toolCallId)

        if call is None:
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"assertion cites {evidence.toolCallId!r}, which is not in this run's "
                    f"trace ({len(ctx.trace.toolCalls)} tool calls recorded). "
                    f"The agent did not retrieve this."
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )
            continue

        try:
            stored = ctx.storage.load_tool_response(ctx.run, call.id)
        except OSError as exc:
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=f"stored response for {call.id} is unreadable: {exc}",
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )
            continue

        actual = response_hash(stored)
        if actual != call.responseHash:
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"{call.id} response hash does not verify "
                    f"(recorded {call.responseHash[:12]}..., stored {actual[:12]}...). "
                    f"The evidence has changed since it was retrieved."
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )
            continue

        if not contains_literal(stored, evidence.literal):
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"{evidence.literal!r} does not appear in the response to "
                    f"{call.id} ({call.tool}). The retrieval happened, "
                    f"but it does not say this."
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )

    if checked == 0:
        yield skipped(ValidatorName.evidence_retrieved, ctx, "no assertions in this run")
    else:
        yield passed(
            ValidatorName.evidence_retrieved,
            ctx,
            f"{checked} assertion(s) resolved to a retrieval",
        )

