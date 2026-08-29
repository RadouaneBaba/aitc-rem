"""Six tools, and the logging that makes them evidence.

SS8.1 listed twelve. Six of them had, by 2026-08-29, been offered to **no stage
at all** -- `query_element`, `get_console`, `get_events`, `get_objective`,
`get_neighbouring_segments` and `search_step_library` -- reachable only through
the one `investigate()` caller that passed no `tool_names` and therefore
received the whole registry by accident. `search_step_library` was worse than
unused: its module had already been deleted, so it degraded to "no library
configured" for anything that called it.

They are gone, and the argument is measured rather than tidy: **more tools means
worse tool choice**, which is the entire reason `tool_names` exists. The step
library is the proof in the other direction -- making one tool feel obligatory
lifted calls-per-step from 1.56 to 2.17 and collapsed the effort spread that is
supposed to show an agent deciding rather than executing, from 1.08 to 0.16.

What each of the six survivors does is a question a tester asks: what changed
here, what was on the page, where does this appear, what did the server say,
what did they say out loud, and let me look at it.

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
#: A response, narrowed to what is worth putting in front of a model.
ToolView = Callable[[Any], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn
    #: What the MODEL sees, when that should be smaller than what is stored.
    #:
    #: Two different questions were being answered by one value. What is
    #: PERSISTED is the evidence: `evidence_retrieved` re-hashes it, and a
    #: predicate is re-evaluated against it, so it has to be complete or a true
    #: claim whose literal fell into a hidden tail starts being rejected. What is
    #: SENT is a budget: `get_snapshot` returns 65-72 KB of a commercial page --
    #: one call, ~16-18k tokens -- into a conversation that re-sends its history
    #: every turn, and three of them took one run to 168,690 prompt tokens
    #: against ~29,000 for a fixture.
    #:
    #: `get_diff` already caps, and there it is the same value both ways, which
    #: is survivable only because its ranking is stable. It is NOT survivable for
    #: a snapshot: `_rank` puts named nodes first, so a `first_of` predicate
    #: evaluated against a ranked view answers "the first NAMED node", and on a
    #: product grid the nameless wrappers are precisely what ranks to the back.
    #: The predicate would return the wrong answer confidently and pass the gate.
    #:
    #: `ToolRunner.image_for` already made this split for pixels; this is the
    #: same split for text. It is also the seam a live browser agent needs: an
    #: MCP client's retrievals must be persisted here or they never reach
    #: `trace.toolCalls`, which is what `evidence_retrieved` resolves against.
    view: ToolView | None = None


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


#: Nodes of a snapshot tree put in front of the model before it starts counting.
#:
#: Larger than `MAX_DIFF_ROWS` because a diff row is a leaf that says something
#: and a tree is mostly interior structure that says nothing on its own but
#: cannot be dropped without orphaning what is under it. Measured against the
#: pages this has to survive: a commercial storefront snapshot is ~950 nodes and
#: 150-172 KB, and `get_diff` on the same page comes back at 4.5-15 KB, which is
#: the size that is known to work.
MAX_SNAPSHOT_NODES = 300


def _trim(node: Any, budget: list[int]) -> Any:
    """One node and as many of its descendants as the budget allows.

    Depth-first, in DOCUMENT ORDER, which is the whole reason this is not
    `_rank`. Ranking is right for a diff, where the question is "what is worth
    reading first"; it is wrong for a page, where a claim about the FIRST
    product in a list is a claim about position and a reordered view answers a
    different question. So the view is a prefix of the document, never a
    re-sort, and the tail it drops is the bottom of the page rather than the
    nameless half of it.
    """
    if not isinstance(node, dict):
        return node
    budget[0] -= 1
    children = node.get("children")
    if not isinstance(children, list) or not children:
        return node

    kept: list[Any] = []
    for child in children:
        if budget[0] <= 0:
            break
        kept.append(_trim(child, budget))
    out = {**node}
    dropped = len(children) - len(kept)
    if kept:
        out["children"] = kept
    else:
        out.pop("children", None)
    if dropped:
        out["childrenNotShown"] = dropped
    return out


def snapshot_view(response: Any) -> Any:
    """What the model sees of a snapshot. The full tree is still what is stored.

    See `ToolSpec.view`. The count is always exact and always the real one, for
    the same reason `get_diff`'s `summary` is: "how big was the page" and "what
    was on it" are different questions and the answer to the first must not
    depend on a display budget.
    """
    if not isinstance(response, dict) or not response.get("present"):
        return response
    total = _count_nodes(response.get("root")) + sum(
        _count_nodes(region) for region in response.get("liveRegions") or []
    )
    if total <= MAX_SNAPSHOT_NODES:
        return response

    budget = [MAX_SNAPSHOT_NODES]
    out = {**response}
    if response.get("root") is not None:
        out["root"] = _trim(response["root"], budget)
    regions = response.get("liveRegions")
    if isinstance(regions, list):
        # Live regions are where an alert or a status message lands, which is
        # disproportionately what a verdict rests on, so they are trimmed last
        # and only once the document itself has spent the budget.
        out["liveRegions"] = [_trim(region, budget) for region in regions]
    out["nodesShown"] = MAX_SNAPSHOT_NODES - max(budget[0], 0)
    out["nodesTotal"] = total
    out["note"] = (
        f"Showing the first {out['nodesShown']} of {total} nodes, in document order. "
        "The rest is the bottom of the page. Use get_diff or find_text to reach it."
    )
    return out


def _count_nodes(node: Any) -> int:
    if not isinstance(node, dict):
        return 0
    children = node.get("children")
    if not isinstance(children, list):
        return 1
    return 1 + sum(_count_nodes(child) for child in children)


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
            view=snapshot_view,
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
            "get_narration",
            "Transcript of anything the tester said in a time window. When present this is "
            "the most direct statement of the expected result there is.",
            _schema({"fromMs": _NUM, "toMs": _NUM}, ["fromMs", "toMs"]),
            get_narration,
        ),
        ToolSpec(
            "find_text",
            "Where does this exact string appear across the recording? The grounding "
            "lookup: an assertion may only quote a string this returns.",
            _schema({"query": _STR, "scope": _STR, "caseSensitive": _BOOL}, ["query"]),
            find_text,
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
    calls: list[ToolCall] = field(default_factory=list)
    _seq: int = field(default=0, init=False)

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
        """Run one tool. Returns `(toolCallId, what the model should see)`.

        A tool that raises is still logged. A failed retrieval is evidence too,
        and hiding it would make the trace a record of what worked rather than
        a record of what happened.

        **What is stored and what is returned are not always the same value.**
        The full response is persisted and hashed -- it is the evidence, and both
        `evidence_retrieved` and every predicate are re-evaluated against it --
        while a tool with a `view` returns a narrowed copy to the caller, which
        is what reaches the conversation. See `ToolSpec.view` for why a snapshot
        cannot simply be capped in place.
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

        # The narrowing happens AFTER the store and the hash, never before, so
        # the record on disk is always the whole retrieval. A view that raises
        # is not worth losing a retrieval over: the full response is correct,
        # merely larger than intended.
        if spec is not None and spec.view is not None and error is None:
            try:
                return call_id, spec.view(response)
            except Exception:  # noqa: BLE001 - a display budget must never fail a run
                return call_id, response
        return call_id, response
