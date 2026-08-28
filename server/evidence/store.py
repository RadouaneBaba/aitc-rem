"""The recording as a queryable evidence store (SS8).

    "The contract is not a format. It is queryability."

This is what makes tool calling possible and therefore what makes the system
agentic: a recording that can only be dumped into a prompt forces the one-shot
architecture the project exists to replace.

On ingest the recording is indexed -- events by id and time, snapshot nodes by
role and name, network calls by time window and URL, console entries by
severity, narration by time. Nothing here talks to a model; this layer only
answers questions.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from server.models import (
    CapturedEvent,
    ConsoleEntry,
    NarrationSegment,
    NetworkCall,
    Recording,
    Segment,
    SegmentsDocument,
    SemanticNode,
    SemanticSnapshot,
    TesterAnnotation,
)

When = Literal["before", "after", "transient"]

MAX_MATCHES = 40


@dataclass(frozen=True)
class FlatNode:
    """A snapshot node, flattened with the path that locates it."""

    event_id: str
    when: str
    ref: str
    role: str
    name: str
    value: str | None
    state: tuple[str, ...]
    path: str

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "eventId": self.event_id,
            "when": self.when,
            "ref": self.ref,
            "role": self.role,
            "name": self.name,
        }
        if self.value is not None:
            out["value"] = self.value
        if self.state:
            out["state"] = list(self.state)
        if self.path:
            out["path"] = self.path
        return out


@dataclass
class EvidenceStore:
    """Indexed access to one recording."""

    recording: Recording
    segments: SegmentsDocument | None = None

    _by_id: dict[str, CapturedEvent] = field(default_factory=dict, init=False)
    _times: list[float] = field(default_factory=list, init=False)
    _ordered: list[CapturedEvent] = field(default_factory=list, init=False)
    _nodes: dict[tuple[str, str], list[FlatNode]] = field(default_factory=dict, init=False)
    _segments_by_id: dict[str, Segment] = field(default_factory=dict, init=False)
    _segment_of_event: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._ordered = sorted(self.recording.events, key=lambda e: (e.timestamp, e.seq))
        self._by_id = {e.id: e for e in self._ordered}
        self._times = [e.timestamp for e in self._ordered]

        for event in self._ordered:
            for when in ("before", "after", "transient"):
                snapshot = getattr(event, when, None)
                if snapshot is not None:
                    self._nodes[(event.id, when)] = _flatten(event.id, when, snapshot)

        self.attach_segments(self.segments)

    def attach_segments(self, segments: SegmentsDocument | None) -> None:
        self.segments = segments
        self._segments_by_id = {}
        self._segment_of_event = {}
        if not segments:
            return
        for segment in segments.segments:
            self._segments_by_id[segment.id] = segment
            for event_id in segment.eventIds:
                self._segment_of_event[event_id] = segment.id

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def event(self, event_id: str) -> CapturedEvent:
        try:
            return self._by_id[event_id]
        except KeyError:
            raise KeyError(
                f"no event {event_id!r} in {self.recording.id} "
                f"(have {len(self._by_id)} events, {self._first_last()})"
            ) from None

    def _first_last(self) -> str:
        if not self._ordered:
            return "none"
        return f"{self._ordered[0].id}..{self._ordered[-1].id}"

    def has_event(self, event_id: str) -> bool:
        return event_id in self._by_id

    def events_in_range(self, start: int | None, end: int | None) -> list[CapturedEvent]:
        lo = 0 if start is None else max(0, start)
        hi = len(self._ordered) if end is None else min(len(self._ordered), end + 1)
        return self._ordered[lo:hi]

    def events_between(self, from_ms: float, to_ms: float) -> list[CapturedEvent]:
        lo = bisect_left(self._times, from_ms)
        return [e for e in self._ordered[lo:] if e.timestamp <= to_ms]

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------

    def snapshot(self, event_id: str, when: When = "after") -> SemanticSnapshot | None:
        event = self.event(event_id)
        return getattr(event, when, None)

    def nodes(self, event_id: str, when: When = "after") -> list[FlatNode]:
        self.event(event_id)  # raises with a useful message if unknown
        return self._nodes.get((event_id, when), [])

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def find_text(
        self,
        query: str,
        *,
        scope: str | None = None,
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Where does this string appear across the recording? Capped, for an agent.

        The grounding lookup: an agent about to claim something uses this to
        find the retrieval that would license the claim.

        `MAX_MATCHES` belongs HERE and nowhere else. It exists to bound a tool
        response, which is a presentation concern -- and because ids are
        zero-padded, the sort below makes the cap discard the LATEST events,
        which is where a test's verdict lives. Code that asks a yes/no question
        must call `contains_at` or `events_containing` instead: a presence check
        that reads a truncated list answers "no" for a string that is really
        there, and rejects a true, correctly cited claim as ungrounded.
        """
        matches = sorted(
            self._scan(query, scope=scope, case_sensitive=case_sensitive),
            key=lambda m: str(m.get("eventId", "")),
        )
        return matches[:MAX_MATCHES]

    def contains_at(self, literal: str, event_id: str, *, case_sensitive: bool = True) -> bool:
        """Does this string really appear at this event? Uncapped.

        What `assertion_grounding` and the binder actually want to know. Both
        used to ask `find_text` and scan its 40-match answer, so on a recording
        long enough to hit the cap they were reading an index that stopped
        partway through the session.
        """
        return any(
            match.get("eventId") == event_id
            for match in self._scan(literal, scope=event_id, case_sensitive=case_sensitive)
        )

    def events_containing(self, literal: str, *, case_sensitive: bool = True) -> list[str]:
        """Every event this string appears at, in order. Uncapped.

        For the one caller that needs more than a boolean: `bind._from_answer`
        re-points a citation when the literal turns out to live at exactly one
        other event, and a truncated list would let it re-point to the wrong one
        or decline a re-point that was available.
        """
        return sorted(
            {
                str(match["eventId"])
                for match in self._scan(literal, case_sensitive=case_sensitive)
                if match.get("eventId")
            }
        )

    def _scan(
        self,
        query: str,
        *,
        scope: str | None = None,
        case_sensitive: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Every match anywhere in the recording, uncapped and unsorted.

        One implementation for five sources, because `scope` used to be honoured
        by the semantic-node loop alone: a scoped search still returned every
        URL, request, console line and annotation in the whole session, so
        `find_text(lit, scope=evt)` was not a per-event search at all.
        """
        needle = query if case_sensitive else query.casefold()

        for (event_id, when), nodes in self._nodes.items():
            if scope and scope not in (event_id, when):
                continue
            for node in nodes:
                for field_name in ("name", "value"):
                    haystack = getattr(node, field_name)
                    if not haystack:
                        continue
                    probe = haystack if case_sensitive else haystack.casefold()
                    if needle in probe:
                        match = node.as_dict()
                        match["matchedField"] = field_name
                        match["kind"] = "semantic_node"
                        yield match
                        break

        # The page URL, which is not a node and not a request.
        #
        # SS9.5 counts "a meaningful URL change" as an outcome signal and the IR
        # has a `url` evidence kind for exactly that, but neither was reachable:
        # a URL assertion passed `evidence_retrieved` (the string really was in
        # the tool response) and then failed `assertion_grounding`, because the
        # recording could not be searched anywhere the URL actually lives. The
        # validator was right both times; the index was incomplete.
        for event in self._ordered:
            if scope and scope != event.id:
                continue
            seen: set[str] = set()
            for where, haystack in (
                ("url", event.url),
                ("before.url", event.before.url),
                ("after.url", event.after.url),
            ):
                if not haystack or haystack in seen:
                    continue
                seen.add(haystack)
                probe = haystack if case_sensitive else haystack.casefold()
                if needle in probe:
                    yield {
                        "eventId": event.id,
                        "kind": "url",
                        "matchedField": where,
                        "url": haystack,
                    }
                    break

        for event in self._ordered:
            if scope and scope != event.id:
                continue
            for call in event.network:
                for field_name in ("url", "responseBody", "requestBody"):
                    haystack = getattr(call, field_name, None)
                    if not haystack:
                        continue
                    probe = haystack if case_sensitive else haystack.casefold()
                    if needle in probe:
                        yield {
                            "eventId": event.id,
                            "kind": "network",
                            "matchedField": field_name,
                            "method": call.method,
                            "url": call.url,
                            "status": call.status,
                        }
                        break
            for entry in event.console:
                probe = entry.text if case_sensitive else entry.text.casefold()
                if needle in probe:
                    yield {
                        "eventId": event.id,
                        "kind": "console",
                        "matchedField": "text",
                        "level": entry.level.value,
                        "text": entry.text,
                    }

        # Narration is not attached to an event -- it is a time range over the
        # session -- so a scoped search cannot honestly return any of it. Left in
        # the unscoped index, where it is what lets a claim the tester spoke
        # aloud be found at all.
        for segment in self.recording.narration if not scope else ():
            probe = segment.text if case_sensitive else segment.text.casefold()
            if needle in probe:
                yield {
                    "kind": "narration",
                    "matchedField": "text",
                    "startMs": segment.startMs,
                    "endMs": segment.endMs,
                    "text": segment.text,
                }

        # Annotations. This index is what `assertion_grounding` reads, so a gap
        # in it looks exactly like a validator bug: a page-URL assertion once
        # passed `evidence_retrieved` and failed `assertion_grounding` because
        # URLs were not indexed, and both validators were right. An annotation
        # is the same shape of hole -- a tester points at "Order confirmed", the
        # model quotes what they pointed at, and the claim is rejected as
        # ungrounded despite being the best-supported one in the run.
        for annotation in self._annotations():
            if scope and scope != annotation.eventId:
                continue
            for matched_field, value in (
                ("text", annotation.text),
                ("name", annotation.target.name if annotation.target else None),
                ("value", annotation.target.value if annotation.target else None),
            ):
                if not value:
                    continue
                probe = value if case_sensitive else value.casefold()
                if needle not in probe:
                    continue
                yield {
                    **({"eventId": annotation.eventId} if annotation.eventId else {}),
                    "kind": "annotation",
                    "matchedField": matched_field,
                    "annotationKind": annotation.kind.value,
                    "timestamp": annotation.timestamp,
                    "text": value,
                }

    def _annotations(self) -> list[TesterAnnotation]:
        """Every annotation, session-level and per-event, deduplicated by id.

        `export.ts` writes an annotation in both places on purpose -- the
        session list is what the segmenter reads for boundaries, the per-event
        copy is what the assertion stage reads for intent -- so an index built
        naively over both would report every match twice.
        """
        seen: dict[str, TesterAnnotation] = {}
        for annotation in self.recording.annotations:
            seen[annotation.id] = annotation
        for event in self.recording.events:
            for annotation in event.annotations or []:
                seen[annotation.id] = annotation
        return list(seen.values())

    def annotations(
        self, from_ms: float, to_ms: float, *, kind: str | None = None
    ) -> list[TesterAnnotation]:
        """Annotations landing in a time window, newest signal first.

        The mirror of `narration()`: the assertion stage asks "did the tester
        say anything about this step", and this answers "did they point at
        anything during it".
        """
        return [
            a
            for a in self._annotations()
            if from_ms <= a.timestamp <= to_ms and (kind is None or a.kind.value == kind)
        ]

    def query_element(
        self,
        event_id: str,
        *,
        selector: str | None = None,
        role: str | None = None,
        name: str | None = None,
        when: When = "after",
    ) -> dict[str, Any]:
        """One element, its state, and its neighbours."""
        if not (selector or role or name):
            raise ValueError("query_element needs a selector, or a role, or a name")

        nodes = self.nodes(event_id, when)
        hits = [
            (index, node)
            for index, node in enumerate(nodes)
            if (not selector or node.ref == selector)
            and (not role or node.role == role)
            and (not name or name.casefold() in node.name.casefold())
        ]

        if not hits:
            return {
                "eventId": event_id,
                "when": when,
                "found": False,
                "note": "No node matched. Try find_text, or get_snapshot to see what is there.",
            }

        first = hits[0][0]
        return {
            "eventId": event_id,
            "when": when,
            "found": True,
            "matches": [node.as_dict() for _, node in hits[:10]],
            # Neighbours matter as much as the hit: an agent deciding whether a
            # value changed needs to see what sits around it.
            "neighbours": [n.as_dict() for n in nodes[max(0, first - 2) : first + 3]],
        }

    # ------------------------------------------------------------------
    # network, console, narration
    # ------------------------------------------------------------------

    def network(
        self,
        *,
        event_id: str | None = None,
        from_ms: float | None = None,
        to_ms: float | None = None,
    ) -> list[NetworkCall]:
        if event_id is not None:
            return list(self.event(event_id).network)
        lo = from_ms if from_ms is not None else float("-inf")
        hi = to_ms if to_ms is not None else float("inf")
        return [c for e in self._ordered for c in e.network if lo <= c.startTime <= hi]

    def console(
        self,
        *,
        event_id: str | None = None,
        from_ms: float | None = None,
        to_ms: float | None = None,
        level: str | None = None,
    ) -> list[ConsoleEntry]:
        if event_id is not None:
            entries = list(self.event(event_id).console)
        else:
            lo = from_ms if from_ms is not None else float("-inf")
            hi = to_ms if to_ms is not None else float("inf")
            entries = [c for e in self._ordered for c in e.console if lo <= c.timestamp <= hi]
        if level:
            entries = [c for c in entries if c.level.value == level]
        return entries

    def narration(self, from_ms: float, to_ms: float) -> list[NarrationSegment]:
        """Transcript segments overlapping the window.

        SS6.6 -- narration is a direct read on the test oracle, and it is
        retrieved rather than pre-loaded so an unambiguous step pays nothing.
        """
        return [s for s in self.recording.narration if s.endMs >= from_ms and s.startMs <= to_ms]

    # ------------------------------------------------------------------
    # segments
    # ------------------------------------------------------------------

    def segment(self, segment_id: str) -> Segment:
        try:
            return self._segments_by_id[segment_id]
        except KeyError:
            raise KeyError(f"no segment {segment_id!r} in this run") from None

    def segment_of(self, event_id: str) -> str | None:
        return self._segment_of_event.get(event_id)

    def neighbouring_segments(self, segment_id: str, n: int = 1) -> list[Segment]:
        segment = self.segment(segment_id)
        assert self.segments is not None
        lo = max(0, segment.index - n)
        hi = min(len(self.segments.segments), segment.index + n + 1)
        return self.segments.segments[lo:hi]

    @property
    def objective(self) -> str | None:
        return self.recording.objective


def _flatten(event_id: str, when: str, snapshot: SemanticSnapshot) -> list[FlatNode]:
    out: list[FlatNode] = []

    def walk(node: SemanticNode, trail: list[str]) -> None:
        out.append(
            FlatNode(
                event_id=event_id,
                when=when,
                ref=node.ref,
                role=node.role,
                name=node.name,
                value=node.value,
                state=tuple(node.state or ()),
                path=" > ".join(trail),
            )
        )
        label = f'{node.role} "{node.name}"' if node.name else node.role
        for child in node.children or []:
            walk(child, [*trail, label])

    walk(snapshot.root, [])
    for region in snapshot.liveRegions:
        walk(region, ["(live region)"])
    return out
