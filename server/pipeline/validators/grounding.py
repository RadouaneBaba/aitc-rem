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
from server.pipeline.transcribe import supports_narrated
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

        # `contains_at` rather than `find_text`: the tool caps at 40 matches and
        # sorts by a zero-padded id, so it discards the LATEST events -- which is
        # where a verdict lives. Asking the capped list whether a string is
        # present answered "no" for strings that really were there, and rejected
        # true, correctly cited claims as ungrounded on any recording long
        # enough to reach the cap.
        if not ctx.store.contains_at(evidence.literal, evidence.eventId, case_sensitive=True):
            where = ctx.store.events_containing(evidence.literal, case_sensitive=True)
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


def evidence_discriminates(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """One literal may not be the whole evidence for two different claims.

    **Grounding proves a claim points at a retrieval. It cannot prove the
    retrieval is about that claim rather than the one next to it**, and this is
    the cheapest test of the difference there is: if the same string is the
    entire evidence for two claims that say different things, it discriminates
    between neither, and at least one of them is resting on something that would
    be equally true if it were false.

    Found on a real recording of a French storefront -- 15 events, filters and
    a sort dropdown, thirteen validators green:

        the product list is filtered to show only available items
          <- "Results updated."
        the product list updates to show items matching the selected processors
          <- "Results updated."

    An aria-live region announcing that *something* changed. It is genuinely in
    the recording and genuinely retrieved, so `evidence_retrieved` and
    `assertion_grounding` are both right and both useless here. It is the bare
    number of `_Candidate.conclusive` in another costume -- a literal that
    supports any claim of its shape whatsoever.

    `_unwitnessed` cannot see it either: these claims quote nothing and contain
    no digits, so there is no checkable content for it to compare. Prose framing
    is deliberately untouched there, and this is what that costs.

    **A warning, not a rejection.** The check says two claims cannot both be
    right about this evidence; it cannot say which. On `twoflows` one of the two
    was a good claim and the other restated the scenario name -- rejecting the
    run would have punished both. Naming both and letting a reviewer choose is
    the honest action, and it is what the review UI is for.
    """
    accepted: dict[str, list[str]] = {}
    for _case, _step, assertion in _assertions(ctx):
        if not assertion.accepted:
            continue
        literal = " ".join((assertion.evidence.literal or "").split())
        if not literal:
            continue
        texts = accepted.setdefault(literal, [])
        normalised = " ".join(assertion.text.split()).casefold()
        if normalised not in [" ".join(t.split()).casefold() for t in texts]:
            texts.append(assertion.text)

    if not accepted:
        yield skipped(
            ValidatorName.evidence_discriminates, ctx, "this run accepted no expected result"
        )
        return

    shared = {lit: texts for lit, texts in accepted.items() if len(texts) > 1}
    for literal, texts in sorted(shared.items()):
        yield result(
            ValidatorName.evidence_discriminates,
            ValidatorStatus.warn,
            ValidatorAction.warn,
            ctx,
            message=(
                f"{len(texts)} expected results rest on the same evidence, {literal!r}, so it "
                f"tells them apart from nothing: "
                + "; ".join(repr(t) for t in texts)
                + ". Keep the one this evidence is actually about."
            ),
        )

    if not shared:
        yield passed(
            ValidatorName.evidence_discriminates,
            ctx,
            f"{len(accepted)} literal(s) each support one claim",
        )


def no_pruned_assertion(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """No assertion may rest on a segment that was pruned from the narrative.

    Exploratory and abandoned segments are removed from the test case but kept
    in the trace (SS9.3). An assertion grounded in one would cite evidence the
    reader cannot see, which is worse than no assertion.
    """
    # An omission names its events directly. This used to resolve
    # `omitted.segmentId` against `ctx.segments`, which was right while a step
    # was a segment -- under draft-then-bind nothing sets `segmentId`, so
    # `pruned_events` was always empty and this validator returned early on
    # every run it has ever been part of: 0 pass, 13 skip, under a skip message
    # that still described a phase which had already shipped. `event_coverage`
    # received exactly this migration (`consistency.py`); this sibling was
    # missed. The segment path stays for omissions written the old way.
    pruned_events: dict[str, str] = {}
    for case in ctx.ir.testCases:
        for omitted in case.omitted:
            for event_id in omitted.eventIds or []:
                pruned_events[event_id] = omitted.reason.value
            if omitted.segmentId and ctx.segments:
                segment = next(
                    (s for s in ctx.segments.segments if s.id == omitted.segmentId), None
                )
                for event_id in segment.eventIds if segment else []:
                    pruned_events[event_id] = omitted.reason.value

    if not pruned_events:
        yield skipped(
            ValidatorName.no_pruned_assertion,
            ctx,
            "nothing was pruned from this recording",
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
                    f"assertion is grounded in {assertion.evidence.eventId}, which was "
                    f"pruned from the narrative as {reason}. The reader cannot see "
                    f"that evidence."
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


def provenance_supported(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """A claim about where a claim came from must itself be supported.

    SS9.5's ladder decides which candidate is accepted, so `annotated` is worth
    more than any other word a model can write -- and until now nothing checked
    it. A model could label a pure inference `annotated` and it would outrank
    every genuinely-supported candidate in the step.

    `assertions.py` demotes an unsupported claim at parse time, deterministically
    and before ranking, which is where the fix belongs. This is the net: if a
    provenance ever reaches the IR that the recording cannot support, the
    demotion has regressed or something wrote the IR without going through the
    stage.

    Warn rather than reject. The claim itself may be perfectly grounded -- what
    is wrong is its rank, and rejecting a true assertion because it was
    over-credited would cost the reader an expected result to make a point.
    """
    store = ctx.store
    checked = 0
    offences = 0

    for case, step, assertion in _assertions(ctx):
        provenance = _provenance_value(assertion)
        if provenance in {"inferred", "confirmed"}:
            continue
        checked += 1

        window = _step_window(ctx, step)
        if window is None:
            continue
        start, end = window

        if provenance == "annotated":
            supported = bool(store.annotations(start, end, kind="assertion"))
        elif provenance == "narrated":
            # The same gate `_supported_provenance` applies, and it has to be
            # the same one: narration is a reconstruction, so a segment the
            # transcriber was unsure of does not support the rank. If these two
            # ever disagree, a step is demoted by the stage and then reported
            # as fine by the gate, or the reverse -- and the reverse is a
            # mis-heard literal wearing a provenance nothing objects to.
            supported = any(
                supports_narrated(s, ctx.narration_min_confidence)
                for s in store.narration(start, end)
            )
        elif provenance == "objective":
            supported = bool(store.objective)
        else:
            supported = True

        if supported:
            continue

        offences += 1
        yield result(
            ValidatorName.provenance_supported,
            ValidatorStatus.warn,
            ValidatorAction.warn,
            ctx,
            message=(
                f"assertion claims provenance {provenance!r}, but the recording has nothing "
                f"of that kind covering this step. It is an inference wearing a higher rank."
            ),
            test_case_id=case.id,
            step_id=step.id,
            assertion_id=assertion.id,
        )

    if offences:
        return
    if not checked:
        yield skipped(
            ValidatorName.provenance_supported,
            ctx,
            "every assertion is inferred, so there is no provenance claim to check",
        )
        return
    yield passed(
        ValidatorName.provenance_supported,
        ctx,
        f"{checked} assertion(s) claim more than inference, and the recording supports each",
    )


def _provenance_value(assertion) -> str:
    provenance = assertion.provenance
    return provenance.value if hasattr(provenance, "value") else str(provenance)


def _step_window(ctx: ValidationContext, step) -> tuple[float, float] | None:
    """The time span a step covers, plus the settle tail its outcome lands in."""
    times = [ctx.store.event(e).timestamp for e in step.eventIds if ctx.store.has_event(e)]
    if not times:
        return None
    return min(times), max(times) + 2000
