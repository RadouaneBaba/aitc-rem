"""Validators that check the output against what the recording actually shows."""

from __future__ import annotations

import re
from collections.abc import Iterable

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
from server.pipeline.segment import MUTATING_METHODS
from server.pipeline.validators.base import ValidationContext, passed, result, skipped

#: A mutation word pointing BACKWARDS at something an earlier step did. "the
#: shopping bag displays the item previously added" is a claim about what is on
#: screen now; the adding happened two steps ago and this step made no request
#: at all. Read as a mutation claim it fails a validator that is right about
#: everything except which step it is talking about.
#:
#: Narrow on purpose. It takes an explicit past-reference marker next to the
#: verb, so "the order is saved" still claims a mutation and still has to prove
#: one -- which is the whole point of this check.
PAST_REFERENCE = re.compile(
    r"\b(previously|earlier|already|beforehand)\s+\w*(ed|en)\b"
    r"|\b(\w+(ed|en))\s+(previously|earlier|already|beforehand)\b",
    re.IGNORECASE,
)

#: A step's text says what the TESTER did; an expected result says what the
#: APPLICATION did. Only the second is a claim that state changed, and this
#: pattern is how the first is told from the second.
#:
#: "the tester submits the payment method" describes pressing a button. Read as
#: a claim about persistence it fails a validator that no rewrite can satisfy:
#: every honest verb for that action -- saves, submits, adds -- is a mutation
#: word, so the repair loop spent its budget making the sentence worse, first
#: hedging it into "attempts to save" and then into "clicks Save", which is the
#: mechanics language SS11.1 exists to keep out.
#:
#: A claim of persistence in a step's own text looks different: it is a RESULT
#: clause. "the tester submits the order and it is saved" asserts something,
#: and still has to prove it.
RESULT_CLAUSE = re.compile(
    r"\b(is|are|was|were|been|becomes?|gets?)\s+(\w+\s+){0,2}"
    r"(saved|created|placed|updated|deleted|removed|added|confirmed|approved|"
    r"uploaded|submitted)\b",
    re.IGNORECASE,
)

#: Vocabulary that claims the application changed something. Kept narrow on
#: purpose: a step saying "opens the order form" must not be read as a mutation
#: and rejected for lacking a POST.
MUTATION_WORDS = re.compile(
    r"\b("
    r"saves?|saved|saving|"
    r"submits?|submitted|"
    r"creates?|created|"
    r"places?|placed|"
    r"updates?|updated|"
    r"deletes?|deleted|removes?|removed|"
    r"adds?|added|"
    r"confirms?|confirmed|"
    r"approves?|approved|"
    r"uploads?|uploaded"
    r")\b",
    re.IGNORECASE,
)


def mutation_claimed(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """A step that claims data changed must have a successful mutating request.

    Downgraded to a warning when the step carries `network_incomplete`: the
    recorder misses requests issued before injection and by service workers
    (SS6.4), and rejecting a true claim because the evidence was unobtainable
    would be the wrong failure.
    """
    checked = 0
    for case in ctx.ir.testCases:
        for step in case.steps:
            # An expected result is a claim about the application by
            # definition, so any mutation word in one counts. A step's text
            # counts only where it makes a claim rather than describing an
            # action -- see RESULT_CLAUSE.
            asserted = PAST_REFERENCE.sub(" ", " ".join(a.text for a in step.assertions))
            acted = PAST_REFERENCE.sub(" ", step.text)
            claims = bool(MUTATION_WORDS.search(asserted)) or bool(RESULT_CLAUSE.search(acted))
            if not claims:
                continue
            checked += 1

            events = [ctx.store.event(e) for e in step.eventIds if ctx.store.has_event(e)]
            successes = [
                f"{c.method} {c.url} {c.status}"
                for e in events
                for c in e.network
                if c.method.upper() in MUTATING_METHODS
                and c.status is not None
                and 200 <= c.status < 300
            ]
            if successes:
                continue

            # A step whose POINT is that the change was refused. The tester
            # submitted an order over the approval threshold, the server said
            # no, and an accepted expected result cites that very rejection --
            # so "no successful mutation" is the finding, not a defect.
            #
            # Checked against evidence rather than by reading the sentence,
            # which cannot be done reliably: "tries to place an order" is an
            # honest description of a refused submit and still contains the word
            # "place". What is required instead is real: a rejected mutating
            # request in this step, AND an accepted expected result grounded
            # somewhere in the same step. Both come from the recording, and a
            # step that simply failed can produce neither.
            rejected_events = {
                e.id
                for e in events
                for c in e.network
                if c.method.upper() in MUTATING_METHODS and c.status is not None and c.status >= 400
            }
            step_events = {e.id for e in events}
            if rejected_events and any(
                a.accepted and a.evidence.eventId in step_events for a in step.assertions
            ):
                continue

            incomplete = any(f.value == "network_incomplete" for e in events for f in e.fidelity)
            attempts = [
                f"{c.method} {c.url} {c.status}"
                for e in events
                for c in e.network
                if c.method.upper() in MUTATING_METHODS
            ]
            detail = f" Requests seen: {', '.join(attempts)}." if attempts else " No requests seen."

            yield result(
                ValidatorName.mutation_claimed,
                ValidatorStatus.warn if incomplete else ValidatorStatus.fail,
                ValidatorAction.warn if incomplete else ValidatorAction.reject,
                ctx,
                message=(
                    f"step claims the application changed something, and no successful "
                    f"mutating request is attributed to it.{detail} Say what the tester "
                    f"ATTEMPTED rather than what the application did with it -- 'the "
                    f"tester submits the payment details' rather than 'the payment "
                    f"method is saved'. Do not describe the mechanism either: 'clicks "
                    f"Save' is worse than both."
                    + (
                        " Network capture was incomplete for this step, so this is a "
                        "warning rather than a rejection."
                        if incomplete
                        else ""
                    )
                ),
                test_case_id=case.id,
                step_id=step.id,
            )

    if checked == 0:
        yield skipped(ValidatorName.mutation_claimed, ctx, "no step claims a state change")
    else:
        yield passed(ValidatorName.mutation_claimed, ctx, f"{checked} mutation claim(s) checked")


def event_coverage(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """Every recorded event is accounted for. None silently dropped.

    An event that appears in no step and in no omission is work the tester did
    that the output pretends never happened -- the exact thing SS9.3 refuses to
    do silently.

    This became load-bearing when the drafting stage took over step boundaries.
    A model that decides what a step IS can drop an event by simply not
    mentioning it, and no amount of prompting makes that impossible; this is
    the net, and it is the reason the drafter can be given that freedom safely.

    An omission names its events directly. It used to name a SEGMENT and this
    resolved the segment to find them, which was right while a step was a
    segment -- the drafter now groups events into intents that cross segment
    boundaries, so an omission that could only be expressed as a segment could
    not describe half of what a session actually wanders through. The segment
    path stays for omissions written the old way.
    """
    all_events = [e.id for e in ctx.recording.events]
    if not all_events:
        yield skipped(ValidatorName.event_coverage, ctx, "the recording has no events")
        return

    covered: set[str] = set()
    for case in ctx.ir.testCases:
        for step in case.steps:
            covered.update(step.eventIds)
        for precondition in case.preconditions:
            covered.update(precondition.eventIds)
        for omitted in case.omitted:
            covered.update(omitted.eventIds or [])
            if omitted.segmentId and ctx.segments:
                segment = next(
                    (s for s in ctx.segments.segments if s.id == omitted.segmentId), None
                )
                if segment:
                    covered.update(segment.eventIds)

    missing = [e for e in all_events if e not in covered]
    if missing:
        shown = ", ".join(missing[:8]) + (
            f" (+{len(missing) - 8} more)" if len(missing) > 8 else ""
        )
        yield result(
            ValidatorName.event_coverage,
            ValidatorStatus.fail,
            ValidatorAction.reject,
            ctx,
            message=(
                f"{len(missing)} of {len(all_events)} events appear in no step and in no "
                f"omission: {shown}. Every event must be assigned to a step or explicitly "
                f"classified as work the test does not cover."
            ),
        )
        return

    unknown = sorted(covered - set(all_events))
    if unknown:
        yield result(
            ValidatorName.event_coverage,
            ValidatorStatus.fail,
            ValidatorAction.reject,
            ctx,
            message=f"output references events that are not in the recording: {', '.join(unknown[:8])}",
        )
        return

    yield passed(ValidatorName.event_coverage, ctx, f"all {len(all_events)} events accounted for")


def selector_resolvable(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """Every emitted selector was present in the captured DOM.

    A warning, not a rejection: selectors are a convenience for later
    automation and live in comments (SS11.1), so a stale one is a nuisance
    rather than a false claim about the application.
    """
    checked = 0
    for case in ctx.ir.testCases:
        for step in case.steps:
            if not step.selectorHints:
                continue
            recorded: set[str] = set()
            for event_id in step.eventIds:
                if not ctx.store.has_event(event_id):
                    continue
                selectors = ctx.store.event(event_id).target.selectors
                recorded.update(
                    v
                    for v in (selectors.testId, selectors.role, selectors.text, selectors.css)
                    if v
                )

            for hint in step.selectorHints:
                checked += 1
                if hint.value not in recorded:
                    yield result(
                        ValidatorName.selector_resolvable,
                        ValidatorStatus.warn,
                        ValidatorAction.warn,
                        ctx,
                        message=(
                            f"selector {hint.value!r} ({hint.strategy.value}) was not captured "
                            f"for any event in this step; it may not resolve when the test is run"
                        ),
                        test_case_id=case.id,
                        step_id=step.id,
                    )

    if checked == 0:
        yield skipped(ValidatorName.selector_resolvable, ctx, "no selector hints were emitted")
    else:
        yield passed(ValidatorName.selector_resolvable, ctx, f"{checked} selector(s) checked")


def library_verbatim(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """A step marked reused must match its library entry exactly.

    This is what makes step-library reuse real rather than aspirational: a
    model that paraphrases an approved step while claiming to reuse it would
    reintroduce the step explosion the library exists to prevent (SS12.2).
    """
    reused = [
        (case, step)
        for case in ctx.ir.testCases
        for step in case.steps
        if step.libraryRef is not None
    ]
    if not reused:
        # Real logic behind the guard; the library lands in Phase 2 (SS12).
        yield skipped(
            ValidatorName.library_verbatim,
            ctx,
            "no step claims reuse (the step library is Phase 2)",
        )
        return

    library = getattr(ctx, "library", None)
    if library is None:
        yield result(
            ValidatorName.library_verbatim,
            ValidatorStatus.fail,
            ValidatorAction.reject,
            ctx,
            message=(
                f"{len(reused)} step(s) claim to reuse a library entry, but no library was "
                f"supplied to the validator. A reuse claim that cannot be checked is not "
                f"admissible."
            ),
        )
        return

    offences = 0
    for case, step in reused:
        entry = library.get(step.libraryRef)
        if entry is None:
            offences += 1
            yield result(
                ValidatorName.library_verbatim,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=f"step cites library entry {step.libraryRef!r}, which does not exist",
                test_case_id=case.id,
                step_id=step.id,
            )
        elif entry.text != step.text:
            offences += 1
            yield result(
                ValidatorName.library_verbatim,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"step is marked as reused but was rewritten: "
                    f"library has {entry!r}, step says {step.text!r}"
                ),
                test_case_id=case.id,
                step_id=step.id,
            )

    if not offences:
        yield passed(ValidatorName.library_verbatim, ctx, f"{len(reused)} reused step(s) match")
