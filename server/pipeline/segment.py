"""Stage 1 -- segmentation. Deterministic, code only, no model (SS9.2).

Cuts the event stream into candidate steps using rules. The same recording
always produces the same segment count, which is what makes the audit trail
meaningful and merge/split in the review UI predictable -- and it is why this
stage is code while naming and decomposition are not.

Every event lands in exactly one segment. Nothing is dropped, which the
`event_coverage` validator later re-checks against the output (SS9.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from server.models import (
    BoundaryReason,
    CapturedEvent,
    FidelityFlag,
    Recording,
    Segment,
    SegmentsDocument,
    SemanticNode,
)

# SS9.2 boundary triggers, highest priority first. The order matters only when
# several fire at once: the segment records the strongest reason.
PRIORITY: list[BoundaryReason] = [
    BoundaryReason.checkpoint_annotation,
    BoundaryReason.url_change,
    BoundaryReason.form_submit,
    BoundaryReason.state_mutation,
    BoundaryReason.idle_gap,
    BoundaryReason.region_replacement,
    BoundaryReason.hard_cap,
]

IDLE_GAP_MS = 2000.0
REGION_REPLACEMENT_RATIO = 0.6
MAX_EVENTS_PER_SEGMENT = 12

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class Boundary:
    """A place the stream is cut, and why."""

    reason: BoundaryReason
    #: True when the trigger belongs to the event that follows the cut
    #: (an idle gap, a checkpoint) rather than the one that precedes it.
    before: bool


def segment_recording(
    recording: Recording,
    run_id: str,
    *,
    now: datetime | None = None,
) -> SegmentsDocument:
    """Cut `recording` into candidate steps."""
    segments: list[Segment] = []
    current: list[CapturedEvent] = []
    #: Why the segment now being accumulated began.
    current_reason = BoundaryReason.recording_start

    checkpoint_times = _annotation_times(recording, {"checkpoint", "scenario_break"})
    # Session-level, because a boundary sits BETWEEN two actions rather than on
    # one of them -- which is exactly why `export.ts` declines to attach these
    # to an event. The cut below already honours them; this is what lets the
    # resulting segment say which annotation opened it, so decomposition can
    # tell "the tester declared a new test case here" from its own guess.
    break_times = _annotation_times(recording, {"scenario_break"})
    # The FIRST event after each break, resolved once. Comparing timestamps
    # inside the segment builder marked every later segment too: "starts after
    # the break" is true of all of them, and only one of them opens it.
    break_openers = {
        next((e.id for e in recording.events if e.timestamp >= t), "") for t in break_times
    } - {""}

    for index, event in enumerate(recording.events):
        previous = recording.events[index - 1] if index else None

        opening = _opens_before(event, previous, checkpoint_times)
        if current and opening is not None:
            segments.append(_build(current, len(segments), current_reason, break_openers))
            current = []
            current_reason = opening

        current.append(event)

        closing = _closes_after(event, len(current))
        if closing is not None:
            segments.append(_build(current, len(segments), current_reason, break_openers))
            current = []
            current_reason = closing

    if current:
        segments.append(_build(current, len(segments), current_reason, break_openers))

    document = SegmentsDocument(
        schemaVersion="1.0",
        recordingId=recording.id,
        runId=run_id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=now or datetime.now(UTC),
        segments=segments,
        eventCount=len(recording.events),
    )
    _assert_full_coverage(recording, document)
    return document


# --------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------


def _opens_before(
    event: CapturedEvent,
    previous: CapturedEvent | None,
    checkpoint_times: list[float],
) -> BoundaryReason | None:
    """Triggers that belong to the event about to be added."""
    reasons: list[BoundaryReason] = []

    # A tester checkpoint overrides the segmenter entirely (SS6.7).
    if previous is not None and _checkpoint_between(previous, event, checkpoint_times):
        reasons.append(BoundaryReason.checkpoint_annotation)
    if any(a.kind.value in {"checkpoint", "scenario_break"} for a in (event.annotations or [])):
        reasons.append(BoundaryReason.checkpoint_annotation)

    if previous is not None and event.timestamp - previous.timestamp > IDLE_GAP_MS:
        reasons.append(BoundaryReason.idle_gap)

    return _strongest(reasons)


def _closes_after(event: CapturedEvent, size: int) -> BoundaryReason | None:
    """Triggers that belong to the event just added."""
    reasons: list[BoundaryReason] = []

    if event.diff.urlChanged is not None or event.type.value == "navigate":
        reasons.append(BoundaryReason.url_change)

    if event.type.value == "submit":
        reasons.append(BoundaryReason.form_submit)

    if _completed_mutations(event):
        reasons.append(BoundaryReason.state_mutation)

    if _region_replaced(event):
        reasons.append(BoundaryReason.region_replacement)

    if size >= MAX_EVENTS_PER_SEGMENT:
        reasons.append(BoundaryReason.hard_cap)

    return _strongest(reasons)


def _strongest(reasons: list[BoundaryReason]) -> BoundaryReason | None:
    if not reasons:
        return None
    return min(reasons, key=PRIORITY.index)


def _completed_mutations(event: CapturedEvent) -> list[str]:
    """Successful state-mutating requests, as `POST /api/orders 201` strings.

    A 4xx or 5xx is deliberately not a boundary: a rejected submit leaves the
    tester on the same screen, still working on the same step, and cutting there
    would split one attempt into two steps.
    """
    out: list[str] = []
    for call in event.network:
        if call.method.upper() not in MUTATING_METHODS:
            continue
        if call.status is None or not (200 <= call.status < 300):
            continue
        out.append(f"{call.method.upper()} {_path_of(call.url)} {call.status}")
    return out


def _region_replaced(event: CapturedEvent) -> bool:
    """Did most of what was on screen get replaced?"""
    before = _count_named(event.before.root) + sum(
        _count_named(n) for n in event.before.liveRegions
    )
    if before < 4:
        # Too small a base for a ratio to mean anything; a two-node scope would
        # trip on any change at all.
        return False
    churn = len(event.diff.added) + len(event.diff.removed)
    return churn / before > REGION_REPLACEMENT_RATIO


def _count_named(node: SemanticNode) -> int:
    total = 1 if node.name else 0
    for child in node.children or []:
        total += _count_named(child)
    return total


def _annotation_times(recording: Recording, kinds: set[str]) -> list[float]:
    return sorted(a.timestamp for a in recording.annotations if a.kind.value in kinds)


def _checkpoint_between(previous: CapturedEvent, event: CapturedEvent, times: list[float]) -> bool:
    return any(previous.timestamp < t <= event.timestamp for t in times)


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def _build(
    events: list[CapturedEvent],
    index: int,
    reason: BoundaryReason,
    break_openers: set[str] | None = None,
) -> Segment:
    fidelity: list[FidelityFlag] = []
    for event in events:
        for flag in event.fidelity:
            if flag not in fidelity:
                fidelity.append(flag)

    mutations: list[str] = []
    for event in events:
        mutations.extend(_completed_mutations(event))

    annotations = [a for e in events for a in (e.annotations or [])]

    segment = Segment(
        id=f"seg_{index + 1:03d}",
        index=index,
        eventIds=[e.id for e in events],
        boundaryReason=reason,
        startTimestamp=events[0].timestamp,
        endTimestamp=events[-1].timestamp,
        label=_label(events, mutations),
    )
    if events[0].url:
        segment.startUrl = events[0].url
    if events[-1].after.url:
        segment.endUrl = events[-1].after.url
    if mutations:
        segment.mutations = mutations
    if fidelity:
        segment.fidelity = fidelity
    if any(a.kind.value == "checkpoint" for a in annotations):
        segment.hasCheckpoint = True
    # A scenario break marks the segment that STARTS after it: the tester said
    # "a new test case begins here", and here is the next thing they did.
    opened_by_break = events[0].id in (break_openers or set())
    if opened_by_break or any(a.kind.value == "scenario_break" for a in annotations):
        segment.hasScenarioBreak = True
    return segment


def _label(events: list[CapturedEvent], mutations: list[str]) -> str:
    """A cheap deterministic summary.

    Lets the decompose stage read a whole fifteen-minute session at once without
    pulling a single full snapshot -- which is the difference between one
    affordable prompt and a context overflow.
    """
    parts: list[str] = []
    for event in events[:4]:
        name = event.target.name or event.target.role
        parts.append(f'{event.type.value} "{name}"' if event.target.name else event.type.value)
    if len(events) > 4:
        parts.append(f"+{len(events) - 4} more")

    label = ", ".join(parts)
    if mutations:
        label += f" -> {'; '.join(dict.fromkeys(mutations))}"
    outcome = _outcome_of(events[-1])
    if outcome:
        label += f" -> {outcome}"
    return label


def _outcome_of(event: CapturedEvent) -> str:
    """The most assertion-shaped thing the last event produced."""
    for node in event.diff.added:
        if node.role in {"alert", "alertdialog", "status"} and node.name:
            return f'{node.role} "{node.name}"'
    if event.diff.urlChanged is not None:
        return f"navigated to {_path_of(event.diff.urlChanged.to)}"
    return ""


def _path_of(url: str) -> str:
    for marker in ("://",):
        if marker in url:
            rest = url.split(marker, 1)[1]
            return "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    return url


def _assert_full_coverage(recording: Recording, document: SegmentsDocument) -> None:
    """Every event in exactly one segment. None dropped, none duplicated.

    Checked here rather than only in the validator because a segmenter that
    loses events silently would corrupt every stage downstream, and this is
    cheap enough to run on every call.
    """
    assigned = [eid for s in document.segments for eid in s.eventIds]
    expected = [e.id for e in recording.events]
    if assigned != expected:
        missing = set(expected) - set(assigned)
        extra = set(assigned) - set(expected)
        raise AssertionError(
            "segmentation lost or reordered events: "
            f"missing={sorted(missing)} unexpected={sorted(extra)} "
            f"assigned={len(assigned)} expected={len(expected)}"
        )
