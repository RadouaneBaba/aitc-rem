"""Validators that check the output against what the recording actually shows.

Four regexes lived here -- `PAST_REFERENCE`, `RESULT_CLAUSE`, `DISPLAY_CLAIM`
and `MUTATION_WORDS` -- and they were deleted on 2026-08-29 as residue of
`mutation_claimed`, which went with the other nine validators. Each was a very
carefully reasoned attempt to tell "the tester submitted the form" from "the
form was submitted" by pattern, and their comments were worth reading: they
record a repair loop spending its budget hedging a sentence into "attempts to
save" and then into "clicks Save", which is the mechanics language the feature
file exists to keep out.

They are gone rather than kept for reference because a regex guessing whether a
sentence is meaningful will always lose that question to a model reading it, and
the judge asks it now. The reasoning survives in `docs/DESIGN_NOTES.md`; dead
patterns in a live module read as rules somebody still relies on.
"""

from __future__ import annotations

from collections.abc import Iterable

from server.models import (
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
)
from server.pipeline.validators.base import ValidationContext, passed, result, skipped


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

