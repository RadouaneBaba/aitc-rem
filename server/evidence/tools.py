"""The twelve tools of SS8.1, and the logging that makes them evidence.

Two things live here and they are deliberately separate:

* `TOOLS` -- pure functions over an `EvidenceStore`. No side effects, no
  logging, trivially testable.
* `ToolRunner` -- the wrapper that records every call. This is the part SS8.2
  calls "not debug output": it is the substrate `evidence_retrieved` resolves
  against, the data behind the review UI's why-panel, and the raw material for
  the agency proof.

Disable the runner and the pipeline cannot emit a single valid assertion. Not
"degrades" -- cannot.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server.evidence.store import EvidenceStore
from server.models import PipelineStage, TesterAnnotation, ToolCall
from server.storage.paths import RunPaths, Storage
from server.util.canonical import response_hash

ToolFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value


# --------------------------------------------------------------------------
# implementations
# --------------------------------------------------------------------------


def get_snapshot(store: EvidenceStore, eventId: str, when: str = "after") -> dict[str, Any]:
    snapshot = store.snapshot(eventId, when)  # type: ignore[arg-type]
    if snapshot is None:
        return {
            "eventId": eventId,
            "when": when,
            "present": False,
            "note": (
                "No transient snapshot for this event: nothing appeared and vanished during it."
                if when == "transient"
                else "Not captured."
            ),
        }
    return {"eventId": eventId, "when": when, "present": True, **_dump(snapshot)}


def get_full_snapshot(store: EvidenceStore, eventId: str, when: str = "after") -> dict[str, Any]:
    return store.merged_view(eventId, when)  # type: ignore[arg-type]


def query_element(
    store: EvidenceStore,
    eventId: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    when: str = "after",
) -> dict[str, Any]:
    return store.query_element(
        eventId,
        selector=selector,
        role=role,
        name=name,
        when=when,  # type: ignore[arg-type]
    )


def get_diff(store: EvidenceStore, eventId: str) -> dict[str, Any]:
    event = store.event(eventId)
    return {
        "eventId": eventId,
        "settle": _dump(event.settle) if event.settle else None,
        **_dump(event.diff),
    }


def get_network(
    store: EvidenceStore,
    eventId: str | None = None,
    fromMs: float | None = None,
    toMs: float | None = None,
) -> dict[str, Any]:
    calls = store.network(event_id=eventId, from_ms=fromMs, to_ms=toMs)
    return {"eventId": eventId, "count": len(calls), "calls": _dump(calls)}


def get_console(
    store: EvidenceStore,
    eventId: str | None = None,
    fromMs: float | None = None,
    toMs: float | None = None,
    level: str | None = None,
) -> dict[str, Any]:
    entries = store.console(event_id=eventId, from_ms=fromMs, to_ms=toMs, level=level)
    return {"eventId": eventId, "count": len(entries), "entries": _dump(entries)}


def get_narration(store: EvidenceStore, fromMs: float, toMs: float) -> dict[str, Any]:
    segments = store.narration(fromMs, toMs)
    return {
        "fromMs": fromMs,
        "toMs": toMs,
        "count": len(segments),
        "segments": _dump(segments),
        **(
            {}
            if store.recording.narration
            else {"note": "This recording has no narration; the tester did not speak."}
        ),
    }


def get_events(
    store: EvidenceStore, start: int | None = None, end: int | None = None
) -> dict[str, Any]:
    events = store.events_in_range(start, end)
    # Deliberately a summary, not the full events: handing back two snapshots
    # per event would defeat the point of retrieving on demand.
    return {
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "seq": e.seq,
                "timestamp": e.timestamp,
                "type": e.type.value,
                "url": e.url,
                "role": e.target.role,
                "name": e.target.name,
                "fidelity": [f.value for f in e.fidelity],
                "network": [
                    f"{c.method} {c.url} {c.status if c.status is not None else '-'}"
                    for c in e.network
                ],
                # The assert prompt tells the model "use get_events for the
                # annotation" and this response had no annotations in it, so the
                # instructed retrieval returned nothing and the model had to
                # fall back to inference. A tester pointing at the thing they
                # are checking is the strongest signal in the system (SS9.5);
                # advertising it and then not serving it was the worst of both.
                **(
                    {"annotations": [_annotation(a) for a in e.annotations]}
                    if e.annotations
                    else {}
                ),
            }
            for e in events
        ],
    }


def _annotation(annotation: TesterAnnotation) -> dict[str, Any]:
    """What the tester said or pointed at, flattened for a prompt."""
    target = annotation.target
    return {
        "kind": annotation.kind.value,
        "timestamp": annotation.timestamp,
        **({"text": annotation.text} if annotation.text else {}),
        **(
            {
                "target": {
                    "role": target.role,
                    "name": target.name,
                    **({"value": target.value} if target.value else {}),
                }
            }
            if target
            else {}
        ),
    }


def find_text(
    store: EvidenceStore,
    query: str,
    scope: str | None = None,
    caseSensitive: bool = False,
) -> dict[str, Any]:
    matches = store.find_text(query, scope=scope, case_sensitive=caseSensitive)
    return {
        "query": query,
        "count": len(matches),
        "matches": matches,
        **(
            {}
            if matches
            else {
                "note": (
                    "This string does not appear anywhere in the recording. "
                    "An assertion quoting it cannot be grounded."
                )
            }
        ),
    }


def search_step_library(store: EvidenceStore, query: str, limit: int = 5) -> dict[str, Any]:
    """Approved phrasing from earlier recordings (SS12).

    The library is attached to the `ToolRunner`, not to the `EvidenceStore`:
    what a team has agreed to call something is not evidence about this
    recording, and putting it on the store would let a library entry ground an
    assertion. Nothing in the library came out of the session under analysis.
    """
    library = getattr(store, "_library", None)
    if library is None:
        return {
            "query": query,
            "count": 0,
            "matches": [],
            "note": "No step library is configured for this run. Invent new wording.",
        }

    matches = library.search(query, limit=limit)
    if not matches:
        return {
            "query": query,
            "count": 0,
            "matches": [],
            "note": (
                "Nothing approved resembles this yet. Invent new wording -- it enters the "
                "library when a human approves it."
            ),
        }
    return {
        "query": query,
        "count": len(matches),
        "matches": [m.as_dict() for m in matches],
        "note": (
            "`reuse: true` means this wording is safe to copy EXACTLY as given. "
            "`reuse: false` means it is similar but says something different -- read it, "
            "then write your own sentence."
        ),
    }


def get_objective(store: EvidenceStore) -> dict[str, Any]:
    objective = store.objective
    return {
        "objective": objective,
        "stated": objective is not None,
        **(
            {}
            if objective
            else {"note": "The tester stated no objective. Infer intent from the events."}
        ),
    }


def get_neighbouring_segments(store: EvidenceStore, segmentId: str, n: int = 1) -> dict[str, Any]:
    segments = store.neighbouring_segments(segmentId, n)
    return {
        "segmentId": segmentId,
        "segments": [
            {
                "id": s.id,
                "index": s.index,
                "label": s.label,
                "eventIds": s.eventIds,
                "boundaryReason": s.boundaryReason.value,
                "isTarget": s.id == segmentId,
            }
            for s in segments
        ],
    }


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

_STR = {"type": "string"}
_NUM = {"type": "number"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}
_WHEN = {"type": "string", "enum": ["before", "after", "transient"]}


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "get_snapshot",
            "Scoped semantic snapshot of the page before or after an event. "
            "Use `transient` for something that appeared and then vanished, such as a toast.",
            _schema({"eventId": _STR, "when": _WHEN}, ["eventId"]),
            get_snapshot,
        ),
        ToolSpec(
            "get_full_snapshot",
            "The widest view of the page available for an event. More expensive than "
            "get_snapshot; ask for it when the scoped view proves insufficient.",
            _schema({"eventId": _STR, "when": _WHEN}, ["eventId"]),
            get_full_snapshot,
        ),
        ToolSpec(
            "query_element",
            "One element, its state, and its neighbours. Match by ref, by role, or by name.",
            _schema(
                {
                    "eventId": _STR,
                    "selector": _STR,
                    "role": _STR,
                    "name": _STR,
                    "when": _WHEN,
                },
                ["eventId"],
            ),
            query_element,
        ),
        ToolSpec(
            "get_diff",
            "What changed between the before and after snapshots of an event, "
            "plus why the recorder judged the page to have settled.",
            _schema({"eventId": _STR}, ["eventId"]),
            get_diff,
        ),
        ToolSpec(
            "get_network",
            "Network calls for an event, or across a time window. Bodies are redacted.",
            _schema({"eventId": _STR, "fromMs": _NUM, "toMs": _NUM}, []),
            get_network,
        ),
        ToolSpec(
            "get_console",
            "Console errors and warnings for an event or a time window.",
            _schema({"eventId": _STR, "fromMs": _NUM, "toMs": _NUM, "level": _STR}, []),
            get_console,
        ),
        ToolSpec(
            "get_narration",
            "Transcript of anything the tester said in a time window. When present this is "
            "the most direct statement of the expected result there is.",
            _schema({"fromMs": _NUM, "toMs": _NUM}, ["fromMs", "toMs"]),
            get_narration,
        ),
        ToolSpec(
            "get_events",
            "Summaries of events in a range, by index. Cheap overview, no snapshots.",
            _schema({"start": _INT, "end": _INT}, []),
            get_events,
        ),
        ToolSpec(
            "find_text",
            "Where does this exact string appear across the recording? The grounding "
            "lookup: an assertion may only quote a string this returns.",
            _schema({"query": _STR, "scope": _STR, "caseSensitive": _BOOL}, ["query"]),
            find_text,
        ),
        ToolSpec(
            "search_step_library",
            "Approved step phrasing from earlier recordings in this project. "
            "Search before inventing new wording.",
            _schema({"query": _STR, "limit": _INT}, ["query"]),
            search_step_library,
        ),
        ToolSpec(
            "get_objective",
            "What the tester said they were checking, before recording started.",
            _schema({}, []),
            get_objective,
        ),
        ToolSpec(
            "get_neighbouring_segments",
            "Surrounding segments, for when a step is ambiguous on its own.",
            _schema({"segmentId": _STR, "n": _INT}, ["segmentId"]),
            get_neighbouring_segments,
        ),
    ]
}


# --------------------------------------------------------------------------
# the logged runner
# --------------------------------------------------------------------------


@dataclass
class ToolRunner:
    """Executes tools and logs every call as content-addressed evidence.

    Each call writes `runs/<rec>/<run>/tools/tc_NNNN.json` and appends a
    `ToolCall` carrying `sha256(canonical_json(response))`. That record is what
    an assertion's `toolCallId` points at, and what the validator resolves.
    """

    store: EvidenceStore
    storage: Storage
    run: RunPaths
    stage: PipelineStage = PipelineStage.name
    #: SS12's approved phrasing. Optional: a project with no history has none,
    #: and the pipeline must run identically without it.
    library: Any = None
    calls: list[ToolCall] = field(default_factory=list)
    _seq: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Handed to the tool through the store because every tool takes the
        # store as its first argument, and widening that signature for one tool
        # would touch all twelve. Underscored: it is not evidence, and nothing
        # else should read it from there.
        self.store._library = self.library  # type: ignore[attr-defined]

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Tool schemas, in the shape a model API expects."""
        return [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in TOOLS.values()
        ]

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        step_id: str | None = None,
        segment_id: str | None = None,
        stage: PipelineStage | None = None,
    ) -> tuple[str, Any]:
        """Run one tool. Returns `(toolCallId, response)`.

        A tool that raises is still logged. A failed retrieval is evidence too,
        and hiding it would make the trace a record of what worked rather than
        a record of what happened.
        """
        args = dict(args or {})
        self._seq += 1
        call_id = f"tc_{self._seq:04d}"
        started = time.perf_counter()

        spec = TOOLS.get(tool)
        error: str | None = None
        if spec is None:
            response: Any = {
                "error": f"unknown tool {tool!r}",
                "available": sorted(TOOLS),
            }
            error = response["error"]
        else:
            try:
                response = spec.fn(self.store, **args)
            except Exception as exc:  # noqa: BLE001 - surfaced to the agent verbatim
                response = {"error": f"{type(exc).__name__}: {exc}"}
                error = response["error"]

        path = self.storage.save_tool_response(self.run, call_id, response)
        record = ToolCall(
            id=call_id,
            stage=stage or self.stage,
            tool=tool,
            args=args,
            responsePath=self.run.relative(path),
            responseHash=response_hash(response),
            timestamp=time.time(),
            durationMs=round((time.perf_counter() - started) * 1000, 3),
        )
        if step_id:
            record.stepId = step_id
        if segment_id:
            record.segmentId = segment_id
        if error:
            record.error = error

        self.calls.append(record)
        return call_id, response
