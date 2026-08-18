"""Validators that decide whether a claim was licensed by a retrieval.

`evidence_retrieved` is the mechanism SS3.2 calls the single most important
technical decision in the document. It is not enough that a quoted string
exists somewhere in the recording: it must have appeared in a tool response
THIS agent actually received during THIS run.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
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


def assertion_grounding(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """The literal must also be present in the recording at the cited event.

    Belt and braces over `evidence_retrieved`: a tool could in principle return
    something the recording does not contain, and the recording is the ground
    truth (SS5, principle 1).
    """
    checked = 0
    for case, step, assertion in _assertions(ctx):
        checked += 1
        evidence = assertion.evidence

        if not ctx.store.has_event(evidence.eventId):
            yield result(
                ValidatorName.assertion_grounding,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"assertion cites event {evidence.eventId!r}, which is not in the recording"
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )
            continue

        matches = ctx.store.find_text(evidence.literal, case_sensitive=True)
        if not any(m.get("eventId") == evidence.eventId for m in matches):
            where = sorted({str(m.get("eventId")) for m in matches if m.get("eventId")})
            elsewhere = f" (it does appear at {', '.join(where[:5])})" if where else " at all"
            yield result(
                ValidatorName.assertion_grounding,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"{evidence.literal!r} does not appear at {evidence.eventId} "
                    f"in the recording{elsewhere}"
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )

    if checked == 0:
        yield skipped(ValidatorName.assertion_grounding, ctx, "no assertions in this run")
    else:
        yield passed(
            ValidatorName.assertion_grounding,
            ctx,
            f"{checked} literal(s) found in the recording",
        )


def element_exists(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """Every event a step or assertion refers to has to be real."""
    checked = 0
    for case in ctx.ir.testCases:
        for step in case.steps:
            for event_id in step.eventIds:
                checked += 1
                if not ctx.store.has_event(event_id):
                    yield result(
                        ValidatorName.element_exists,
                        ValidatorStatus.fail,
                        ValidatorAction.reject,
                        ctx,
                        message=f"step cites event {event_id!r}, which is not in the recording",
                        test_case_id=case.id,
                        step_id=step.id,
                    )
            for assertion in step.assertions:
                checked += 1
                if not ctx.store.has_event(assertion.evidence.eventId):
                    yield result(
                        ValidatorName.element_exists,
                        ValidatorStatus.fail,
                        ValidatorAction.reject,
                        ctx,
                        message=(
                            f"assertion cites event {assertion.evidence.eventId!r}, "
                            f"which is not in the recording"
                        ),
                        test_case_id=case.id,
                        step_id=step.id,
                        assertion_id=assertion.id,
                    )

    if checked == 0:
        yield skipped(ValidatorName.element_exists, ctx, "no steps in this run")
    else:
        yield passed(ValidatorName.element_exists, ctx, f"{checked} reference(s) resolved")


def no_pruned_assertion(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """No assertion may rest on a segment that was pruned from the narrative.

    Exploratory and abandoned segments are removed from the test case but kept
    in the trace (SS9.3). An assertion grounded in one would cite evidence the
    reader cannot see, which is worse than no assertion.
    """
    pruned_events: dict[str, str] = {}
    for case in ctx.ir.testCases:
        for omitted in case.omitted:
            segment = None
            if ctx.segments:
                segment = next(
                    (s for s in ctx.segments.segments if s.id == omitted.segmentId), None
                )
            for event_id in segment.eventIds if segment else []:
                pruned_events[event_id] = omitted.reason.value

    if not pruned_events:
        # Real logic behind the guard, no subject yet: decomposition arrives in
        # Phase 2, and until then nothing is ever pruned.
        yield skipped(
            ValidatorName.no_pruned_assertion,
            ctx,
            "no segments were pruned (decomposition is Phase 2)",
        )
        return

    offences = 0
    for case, step, assertion in _assertions(ctx):
        reason = pruned_events.get(assertion.evidence.eventId)
        if reason:
            offences += 1
            yield result(
                ValidatorName.no_pruned_assertion,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"assertion is grounded in {assertion.evidence.eventId}, which belongs "
                    f"to a segment pruned as {reason}. The reader cannot see that evidence."
                ),
                test_case_id=case.id,
                step_id=step.id,
                assertion_id=assertion.id,
            )

    if not offences:
        yield passed(
            ValidatorName.no_pruned_assertion,
            ctx,
            f"no assertion rests on any of {len(pruned_events)} pruned event(s)",
        )
