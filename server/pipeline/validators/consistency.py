"""Validators that check the output against what the recording actually shows."""

from __future__ import annotations

import re
from collections.abc import Iterable

from server.models import (
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
)
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

#: A claim about what is ON SCREEN, where the mutation word is part of what the
#: screen says rather than the claim's own verb.
#:
#: The same conflation `RESULT_CLAUSE` fixes for a step's text, arriving one
#: level up, and this one is a deadlock rather than merely a bad rejection. The
#: `hardpaths` recording shows a status message reading "Payment method saved".
#: `bind._unwitnessed` requires a claim to quote the value it rests on, so every
#: admissible sentence about that message contains the word "saved" -- and the
#: only sentence that does not ("a confirmation appears") is refused by
#: `bind._existence_only`. Between the two rules, nothing could be said at all.
#:
#: The discriminator is ORDER, and it is why this is narrow rather than a
#: loosening: the display verb must come FIRST. "the order is shown as placed"
#: asserts what the page says. "the order is placed and a confirmation is
#: shown" asserts persistence and still has to prove a successful request.
DISPLAY_CLAIM = re.compile(
    r"\b(is|are|was|were)\s+(display|shown|render)\w*\b"
    r"|\b(displays?|shows?|reads?|states?|indicates?)\b",
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

    # Counted rather than unioned. A set only ever answers "at least once", and
    # the drafting prompt says every event id appears EXACTLY ONCE: a drafter
    # that assigns one event to two steps would otherwise pass the net that
    # exists to make its freedom safe, and ship two steps describing the same
    # action.
    #
    # Scoped to ONE case, which is not a detail. A bug report retraces the same
    # session on purpose (SS14.2) -- its repro steps are the test case's steps
    # seen from the developer's side, and carry the same event ids by
    # construction. A rule reading "no event twice in the IR" turns the fixture
    # built to contain a 500 into a rejection with nothing wrong in it. The rule
    # is per document, and two repro steps describing one action is still the
    # defect, inside the report.
    claimed_by: dict[str, list[str]] = {}
    covered: set[str] = set()
    for case in ctx.ir.testCases:
        within: dict[str, list[str]] = {}
        for step in case.steps:
            covered.update(step.eventIds)
            for event_id in step.eventIds:
                within.setdefault(event_id, []).append(step.id)
        for event_id, steps in within.items():
            if len(steps) > 1:
                claimed_by[event_id] = steps
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

    # Preconditions are excluded on purpose: `_build_case` copies an earlier
    # case's setup steps in so each scenario is runnable standalone, so the same
    # event legitimately appears in a step of case 1 and a precondition of case
    # 2. Two STEPS claiming it is the defect.
    duplicated = claimed_by
    if duplicated:
        shown = "; ".join(
            f"{event_id} is claimed by {' and '.join(steps)}"
            for event_id, steps in sorted(duplicated.items())[:4]
        )
        yield result(
            ValidatorName.event_coverage,
            ValidatorStatus.fail,
            ValidatorAction.reject,
            ctx,
            message=(
                f"{len(duplicated)} event(s) belong to more than one step: {shown}. "
                f"An event is one thing the tester did, and two steps describing it "
                f"are two steps describing the same action."
            ),
        )
        return

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

