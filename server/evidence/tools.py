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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from server.evidence.store import EvidenceStore
from server.llm.client import ImagePart
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


#: How many added/removed nodes `get_diff` shows before it starts counting.
#: Only ever applied to the ranked tail -- named nodes come first, so what is
#: dropped is nameless structure.
MAX_DIFF_ROWS = 40


def _informative(node: dict[str, Any]) -> bool:
    """Does this node say anything a claim could rest on?"""
    return bool((node.get("name") or "").strip() or (node.get("value") or "").strip())


def _rank(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Named nodes first, original order within each group. Returns (shown, hidden).

    The page-wide diff this now reads is the point of the 2026-08-28 capture
    change, and it arrives with a tail: a grid re-render reports every wrapper
    `group` in the subtree alongside the four product names that matter. Sorting
    on "has a name or a value" is enough to put the readable half first, and it
    is deterministic, which a truncation policy has to be -- two runs over one
    recording must show the model the same rows.

    Nothing is lost: `full=true` returns the whole list, and the count of what
    was held back is in the response so the model knows there is more.
    """
    named = [n for n in nodes if _informative(n)]
    rest = [n for n in nodes if not _informative(n)]
    ordered = named + rest
    return ordered[:MAX_DIFF_ROWS], max(0, len(ordered) - MAX_DIFF_ROWS)


def get_diff(store: EvidenceStore, eventId: str, full: bool = False) -> dict[str, Any]:
    event = store.event(eventId)
    diff = _dump(event.diff)

    added, removed, changed = diff.get("added", []), diff.get("removed", []), diff.get("changed", [])
    out: dict[str, Any] = {
        "eventId": eventId,
        "settle": _dump(event.settle) if event.settle else None,
        # Counts first, and always exact, whatever the rows below are cut to.
        # "how much changed" and "what changed" are different questions and the
        # answer to the first must not depend on the display budget.
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }
    if diff.get("urlChanged"):
        out["urlChanged"] = diff["urlChanged"]
    if diff.get("titleChanged"):
        out["titleChanged"] = diff["titleChanged"]

    # Changed nodes are never cut. They carry a before AND an after, which is
    # the shape an expected result is made of ("15 -> 18"), and there are never
    # many of them: a re-render reports as add plus remove, not as change.
    out["changed"] = changed

    if full:
        out["added"], out["removed"] = added, removed
        return out

    shown_added, hidden_added = _rank(added)
    shown_removed, hidden_removed = _rank(removed)
    out["added"], out["removed"] = shown_added, shown_removed
    if hidden_added or hidden_removed:
        out["note"] = (
            f"Showing the {len(shown_added)} most informative of {len(added)} added and "
            f"{len(shown_removed)} of {len(removed)} removed nodes; nodes carrying a name "
            f"or a value come first. Call get_diff with full=true for the rest."
        )
    return out


def see(store: EvidenceStore, eventId: str) -> dict[str, Any]:
    """The screenshot of an event. What the tester was looking at.

    SS7.4 said a screenshot is never sent to a model, and that was written when
    the pipeline was text-only. It is now the opposite of a safety rule: the
    recorder has been taking a full-viewport PNG per event since Phase 1, the
    product list that was missing from every snapshot was IN those images, and
    they were rendered as thumbnails in the review UI and nowhere else.

    The redaction posture is unchanged and this does not widen it. A screenshot
    shows what was on the tester's screen -- exactly what the semantic snapshot
    of the same moment already contains, minus the accessibility tree and plus
    the pixels. It goes to the same endpoint under the same terms.

    **What comes back here is a DESCRIPTION, and that is deliberate.** This dict
    is what gets hashed and stored as the retrieval record, so it has to be
    stable and small; the bytes reach the model on their own turn, attached by
    the investigation loop. The image's own sha256 is in the record, so a
    citation still resolves to one exact picture.
    """
    event = store.event(eventId)
    if not event.screenshot:
        return {
            "eventId": eventId,
            "present": False,
            "note": (
                "No screenshot for this event. Capture is rate limited to about two a "
                "second, so a rapid sequence can miss one. Nothing is wrong; there is "
                "simply no picture of this moment."
            ),
        }
    return {
        "eventId": eventId,
        "present": True,
        "imagePath": event.screenshot,
        "url": event.url,
        "title": event.after.title,
        "note": "The image follows this response. Describe only what you can actually see in it.",
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
            "Semantic snapshot of the whole page before or after an event. "
            "Use `transient` for something that appeared and then vanished, such as a toast.",
            _schema({"eventId": _STR, "when": _WHEN}, ["eventId"]),
            get_snapshot,
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
            "What changed on the page between before and after an event, plus why the "
            "recorder judged the page to have settled. This is the whole document, not "
            "the area around the click. Nodes carrying a name or a value are listed "
            "first; pass full=true for the complete list.",
            _schema({"eventId": _STR, "full": _BOOL}, ["eventId"]),
            get_diff,
        ),
        ToolSpec(
            "see",
            "Look at the screenshot of an event -- the page as the tester saw it. Use it "
            "when the text evidence does not settle the question: whether a list re-sorted, "
            "what a chart or canvas showed, whether something is visually wrong. Costs a "
            "little; worth it two or three times in a session, not thirty.",
            _schema({"eventId": _STR}, ["eventId"]),
            see,
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
            # A capability statement, not a directive. This used to read
            # "Search before inventing new wording", which was an instruction
            # from the deleted naming stage left loose in every agent's tool
            # list. Mandating it per step is measured: calls/step 1.56 -> 2.17
            # and SS3.3's Spread collapsed from 1.08 to 0.16, which reads as an
            # agent that stopped adapting when nothing had changed.
            "Approved step phrasing from earlier recordings in this project. "
            "Advice about wording; never evidence, and never required.",
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
    stage: PipelineStage = PipelineStage.author
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

    def tool_definitions(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Tool schemas, in the shape a model API expects.

        `names` narrows the set. The drafting stage was once handed twelve tools
        and told about five, and more tools measurably means worse tool choice --
        so a stage that only needs six says so rather than being handed
        everything and trusted to ignore the rest.
        """
        specs = TOOLS.values() if names is None else [TOOLS[n] for n in names if n in TOOLS]
        return [
            {"name": s.name, "description": s.description, "parameters": s.parameters}
            for s in specs
        ]

    def image_for(self, response: Any) -> ImagePart | None:
        """The pixels behind a `see` response, if it had any.

        Kept apart from the response itself so that what is HASHED stays a small
        stable description while what the model SEES is the picture. The
        investigation loop asks for this after every call and attaches whatever
        comes back.
        """
        if not isinstance(response, dict) or not response.get("imagePath"):
            return None
        path = self.storage.recordings_dir / self.store.recording.id / str(response["imagePath"])
        try:
            return ImagePart(mime="image/png", data=path.read_bytes())
        except OSError:
            # The recording was saved without its screenshots -- an import, or a
            # run whose `screens/` never arrived. The text response already says
            # what it points at; a missing file is not worth failing a run for.
            return None

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
