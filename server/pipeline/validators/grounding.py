"""Validators that decide whether a claim was licensed by a retrieval.

`evidence_retrieved` is the mechanism SS3.2 calls the single most important
technical decision in the document. It is not enough that a quoted string
exists somewhere in the recording: it must have appeared in a tool response
THIS agent actually received during THIS run.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.evidence.predicate import evaluate
from server.models import (
    Assertion,
    AssertionStatus,
    Provenance,
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
)
from server.pipeline.validators.base import (
    ValidationContext,
    passed,
    result,
    skipped,
)
from server.util.canonical import response_hash


def _assertions(ctx: ValidationContext):
    """Every claim that says it points at a retrieval.

    An `unproved` assertion says the opposite -- it is a sentence the author
    wrote and the gate could not license, kept in the file rather than deleted
    so a scenario does not silently end on a `When`. It has no `toolCallId` to
    resolve and no stored response to re-hash, so putting it through
    `evidence_retrieved` would reject every one of them: the run would go red
    for claims that are already, visibly, admitting they are unproved.

    This filter is the whole contract between the two halves. A claim is either
    checked here or labelled unproved everywhere it is rendered, and nothing is
    allowed to be neither.
    """
    for case in ctx.ir.testCases:
        for step in case.steps:
            for assertion in step.assertions:
                if assertion.status is AssertionStatus.unproved:
                    continue
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

    Kept in step with `_assertions` above, and for the same reason in both
    directions. A bug report's `actual` is checked by `evidence_retrieved`, so
    counting only step assertions would let one rejected bug claim push the rate
    below what the run actually produced -- and an `unproved` claim is NOT
    checked, so counting it would push the rate down for a sentence that never
    said it was grounded.

    Neither is a rounding error. This project has now found the vacuous-rate
    trap in seven columns, and putting unproved claims in this denominator would
    make it eight: the number would fall whenever the author was honest and rise
    whenever it stopped writing the verdicts it could not prove.
    """
    return sum(
        1
        for c in ir.testCases
        for s in c.steps
        for a in s.assertions
        if a.status is not AssertionStatus.unproved
    ) + sum(1 for c in ir.testCases if bug_claim(c) is not None)


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
        evidence = assertion.evidence
        if evidence is None:
            # Unreachable through `_assertions`, which filters unproved claims
            # out, and cheap insurance against a future caller that does not.
            # `evidence` is optional exactly when `status` is unproved, and
            # reading it unguarded would be an AttributeError in the one place
            # that must never crash: the gate.
            continue
        checked += 1
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

        # The claim in the form it was actually made. With no predicate this is
        # the containment check it has always been; with one, the same stored
        # response is asked the question the sentence asks -- is this first, are
        # there this many, is this really not here -- because a sentence saying
        # FIRST and a check saying PRESENT is how a sort assertion shipped that
        # would pass on a build with sorting removed.
        #
        # `stored` is the full response even where the model was shown a smaller
        # view, which is what makes a positional check mean anything.
        verdict = evaluate(stored, evidence.literal, evidence.predicate)
        if verdict.unresolved:
            # Cannot-evaluate is not false, and this used to treat it as false.
            #
            # `predicate.evaluate` has three outcomes by design and this branch
            # read `not verdict.holds`, which folds the third into the second --
            # the one thing its own docstring says not to do. The practical cost
            # is that a claim whose container stops resolving, for any reason
            # including a page that never named one, is rejected as though the
            # application had failed the check.
            #
            # A warning rather than a pass, because the sentence may genuinely
            # say more than anything verified: the claim is real, its literal
            # did come back from this retrieval, and the SHAPE of it went
            # unchecked. `author._attach_claim` records the same fact on
            # `Evidence.predicateUnresolved` at the moment it happens.
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.warn,
                ValidatorAction.none,
                ctx,
                message=(
                    f"{evidence.literal!r} came back from {call.id} ({call.tool}), "
                    f"but the shape of the claim could not be checked: {verdict.why}. "
                    f"The literal is proved; FIRST, or HOW MANY, is not."
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )
        elif not verdict.holds:
            yield result(
                ValidatorName.evidence_retrieved,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"{evidence.literal!r} against the response to {call.id} "
                    f"({call.tool}): {verdict.why}. The retrieval happened, "
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

