"""The session index: the whole recording, small enough to read at once.

SPEC SS3.6 justified the retrieval architecture on context volume -- "a
six-minute session with full snapshots far exceeds any context window" -- and
that sentence was written against raw DOM, before SS6.3 made snapshots
semantic. Measured on `rec_MT7MXBS9B2VB`, 34 events and 50 seconds of a
commercial site come to roughly 1,600 tokens in this form. The volume problem
the six-stage pipeline was built around does not exist at this density.

What that buys is the thing the old pipeline could never have: **one author
with the whole session in view.** Naming saw one segment, so it wrote one
sentence per segment; the assert stage saw one step, so it asserted wherever
evidence happened to be dense. Nobody was ever in a position to ask what the
test was about, and the output showed it.

This is deliberately an INDEX, not the evidence. It says a heading appeared and
names it; it does not carry the snapshot the heading came from. That is the
line that keeps the drafting stage agentic: everything here is a pointer to
something retrievable, so a drafter that needs more can go and get it, and one
that does not need more does not pay for it. Handing over the full evidence
would remove the decision; handing over nothing would make the first few calls
of every run identical, which is the failure the per-step library search
already demonstrated (`run.py:_calls_per_step`).

The field selection mirrors `evidence/tools.py:get_events`, which is the same
overview the agent can fetch itself, plus the two things that turn an overview
into a map: a summary of what each action CHANGED, and where the tester paused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from server.models import CapturedEvent
from server.pipeline.segment import break_openers

if TYPE_CHECKING:  # pragma: no cover - typing only
    from server.evidence.store import EvidenceStore

#: A pause longer than this reads as the tester stopping to think, which is
#: usually a boundary between intents. Reported as a hint, never as a decision:
#: the segmenter used to CUT on this, and a tester pausing to read a page mid-
#: task produced a step boundary in the middle of one intent.
IDLE_HINT_MS = 2_000.0

#: Per-event caps. Every one of these exists so that a single busy event on a
#: commercial site -- 33 requests, most of them analytics -- cannot crowd out
#: the other thirty events in the session.
MAX_DIFF_NODES = 6
MAX_NETWORK = 4
MAX_CONSOLE = 2
MAX_NAME = 80
MAX_NARRATION = 240

#: Requests that say something about the application under test. An analytics
#: beacon is a POST too, and on a commercial homepage there are dozens of them.
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class SessionDigest:
    """The index, plus what it cost to build."""

    text: str
    event_count: int
    #: Approximate, and only ever used to report the saving in the trace. Four
    #: characters to the token is the usual rule of thumb and wrong in detail;
    #: it is not load-bearing anywhere.
    approx_tokens: int
    event_ids: list[str] = field(default_factory=list)


def build_digest(store: EvidenceStore, *, include_narration: bool = True) -> SessionDigest:
    """Render the whole session as one readable index.

    `include_narration` is here because narration is the one lossy evidence
    source in the system (a transcript is a reconstruction, not a reading), and
    a drafter that quotes it as though it were exact would produce a claim that
    passes every grounding check and is still false. It goes in the index
    because deciding WHICH outcome matters is exactly what narration is good
    for -- but `bind.py` still makes the claim rest on a snapshot literal.
    """
    lines: list[str] = []
    events = store.events_in_range(None, None)
    noise = _recurring_labels(events)
    breaks = break_openers(store.recording)

    lines.extend(_header(store, events))

    previous: CapturedEvent | None = None
    for event in events:
        lines.extend(
            _event_block(
                store,
                event,
                previous,
                include_narration=include_narration,
                noise=noise,
                opens_case=event.id in breaks,
            )
        )
        previous = event

    text = "\n".join(lines)
    return SessionDigest(
        text=text,
        event_count=len(events),
        approx_tokens=len(text) // 4,
        event_ids=[e.id for e in events],
    )


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------


def _header(store: EvidenceStore, events: list[CapturedEvent]) -> list[str]:
    recording = store.recording
    out = [
        "SESSION",
        f"  recording   {recording.id}",
        f"  events      {len(events)}",
    ]

    if events:
        seconds = (events[-1].timestamp - events[0].timestamp) / 1000.0
        out.append(f"  duration    {seconds:.1f}s")
    if recording.metadata.startUrl:
        out.append(f"  start url   {recording.metadata.startUrl}")

    # The tester's own words about what they were doing. SS9.5 ranks this above
    # everything the pipeline can infer, so it goes at the top where it frames
    # the rest of the index rather than into an event block halfway down.
    if store.objective:
        out.append(f"  objective   {store.objective}")

    parameters = typed_parameters(recording)
    if parameters:
        rendered = ", ".join(f"{p.placeholder} ({p.category.value})" for p in parameters[:8])
        out.append(f"  redacted    {rendered}")

    out.append("")
    out.append("EVENTS")
    return out


def typed_parameters(recording: Any) -> list[Any]:
    """Placeholders that stand for something the tester actually entered.

    Redaction runs over every request and response body on every origin, which
    is right -- a secret must never reach disk, and a rule that fires only on
    the application's own traffic would miss one that leaks through a third
    party. But a placeholder minted inside an analytics beacon is not a test
    parameter, and the Fortnum recording produced eleven of them: numeric
    strings in tracking payloads that matched the phone pattern, published to
    the tester as values they must supply to run the test. None of them exist.

    A real parameter was typed or chosen, so it shows up in an event's target
    value. That is the honest test, and it is cheap.
    """
    entered: set[str] = set()
    for event in recording.events:
        value = getattr(event.target, "value", None)
        if value:
            entered.add(str(value))

    haystack = " ".join(entered)
    return [p for p in recording.parameters if p.placeholder and p.placeholder in haystack]


# --------------------------------------------------------------------------
# one event
# --------------------------------------------------------------------------


def _recurring_labels(events: list[CapturedEvent]) -> set[str]:
    """Node text that shows up in the diffs of event after event.

    A promotional carousel rotates on a timer, so every click during the
    session reports "Festivities start early at Fortnum's" as newly added --
    and six slots of the diff summary go to marketing copy that had nothing to
    do with the action. A node that changes on most of the session's events did
    not change BECAUSE of any of them.

    This is SS9.5's "ad / analytics containers" exclusion, which the spec asks
    for and `assertions.NOISE` never implemented, applied where it does the
    most good: the index the author reads. It suppresses the label from the
    summary only. The node is still in the recording and still retrievable, so
    a drafter with a reason to care can go and look.
    """
    if len(events) < 4:
        return set()

    seen: dict[str, int] = {}
    for event in events:
        labels = {_node_label(node) for node in list(event.diff.added) + list(event.diff.removed)}
        for label in labels:
            if label:
                seen[label] = seen.get(label, 0) + 1

    ceiling = max(3, int(len(events) * 0.3))
    return {label for label, count in seen.items() if count > ceiling}


def _event_block(
    store: EvidenceStore,
    event: CapturedEvent,
    previous: CapturedEvent | None,
    *,
    include_narration: bool,
    noise: set[str],
    opens_case: bool = False,
) -> list[str]:
    out: list[str] = []

    # A pause, reported before the event it precedes, because that is where a
    # reader looking for a boundary would expect to see it.
    if previous is not None:
        gap = event.timestamp - previous.timestamp
        if gap >= IDLE_HINT_MS:
            out.append(f"  -- {gap / 1000.0:.1f}s pause --")

    # The tester's own declaration that a new test case starts here (SS6.7).
    #
    # It was missing from this index entirely, and the omission was invisible
    # because a `scenario_break` carries no `eventId` -- `export.ts` attaches an
    # annotation to an event only when it is a fact ABOUT that event, and a
    # boundary is not. So the loop over `event.annotations` below never saw one,
    # and the ONE author that decides where scenarios begin was never told the
    # tester had already decided.
    #
    # `twoflows` is the fixture built to prove two test cases come out of one
    # recording, and it shipped a single scenario with both flows in it: the
    # drafter merged the two events either side of the break into one step, and
    # `run._split_on_declared_breaks` then correctly declined to cut through the
    # middle of a step. Both halves behaved; nothing had told the drafter.
    #
    # Stated as an instruction rather than as an observation, because that is
    # what it is. The deterministic split remains the net behind it.
    if opens_case:
        out.append(
            "  -- THE TESTER DECLARED A NEW TEST CASE HERE: a scenario must start at this event --"
        )

    # A tab change, before anything else about the event.
    #
    # SS18 milestone 21. The recorder follows a tab opened from a recorded tab,
    # so a payment provider or a PDF now lands in the same session -- and
    # without this line the index reads as one continuous page and the author
    # writes "the tester continued" for "a payment window opened". It is the
    # same shape as the `scenario_break` bug: a session-level fact that no
    # per-event block carried, silently absent rather than wrong.
    #
    # `previous.tabId` rather than the session's origin tab, because what
    # matters is the MOVE. Both ids being absent is the single-tab case and
    # prints nothing.
    if previous is not None and event.tabId is not None and previous.tabId != event.tabId:
        out.append("      -- A DIFFERENT BROWSER TAB. The tester moved to another window here --")

    seconds = event.timestamp / 1000.0
    target = _target(event)
    out.append(f"  {event.id}  {event.type.value}{target}  @{seconds:.1f}s")

    # An annotation is the tester pointing at something, and SS9.5 ranks it top
    # of the provenance ladder. It is indented under its event but written
    # first, because it changes how everything below it should be read.
    for annotation in event.annotations or []:
        out.append(f"      tester: {_annotation(annotation)}")

    if event.keys:
        out.append(f"      keys: {event.keys}")

    url_line = _url(event)
    if url_line:
        out.append(f"      {url_line}")

    diff = _diff(event, noise)
    if diff:
        out.append(f"      changed: {diff}")

    network = _network(event)
    if network:
        out.append(f"      network: {network}")

    console = _console(event)
    if console:
        out.append(f"      console: {console}")

    if include_narration:
        # From the START of the session for the first event, not from the
        # previous one -- there is no previous one, and the window that does not
        # exist is the one the tester says the most useful thing in.
        #
        # `previous is not None` dropped everything spoken before the first
        # click. On `rec_MT7VTN7ZRJPO` the events begin at 15.6s and four of the
        # five segments fall in 0.9s-14.9s, so the ONLY sentence the drafter
        # ever saw was the least informative of them -- "And I will add to bag
        # a...". Thrown away: "I will test if I can add the coffee products
        # correctly to the cart", which is the objective, said out loud.
        #
        # This is the `scenario_break` bug in a second costume: a session-level
        # fact that no per-event block can carry, silently absent rather than
        # wrong, and invisible because the fixture built to prove narration
        # works has the tester speaking *during* the session rather than before
        # it. SS6.7 says the tester's own words outrank the model; a window that
        # cannot contain them is not a ladder.
        spoken = _narration(store, previous.timestamp if previous is not None else 0.0,
                            event.timestamp)
        if spoken:
            out.append(f"      said: {spoken}")

    if event.fidelity:
        out.append(f"      not captured: {', '.join(f.value for f in event.fidelity)}")

    if event.dialog is not None:
        out.append(f"      dialog: {_short(_dialog(event), MAX_NAME)}")

    return out


def _target(event: CapturedEvent) -> str:
    """What was acted on, as a reader would name it.

    Role and name rather than a selector: SS6.1's recorder is black-box and the
    role+name fallback is the normal case, not the exception.
    """
    role = (event.target.role or "").strip()
    name = _short((event.target.name or "").strip(), MAX_NAME)
    if name and role:
        return f' "{name}" ({role})'
    if name:
        return f' "{name}"'
    # No accessible name. Said outright rather than shown as `(generic)`, which
    # reads like a label and was taken for one: a real recording produced *the
    # tester adds the "generic" item to the shopping bag*, with an ARIA role
    # quoted as a product name. SS6.8 flags this case as `no_accessible_name`
    # precisely because the recorder cannot say what the thing was, and the
    # index has to admit that in words rather than print the role and hope.
    if role:
        return f" [an unnamed {role} -- the recorder could not tell what it was]"
    return " [an element with no accessible name]"


def _url(event: CapturedEvent) -> str:
    """Where the tester was, and whether this action moved them.

    A page URL is where a page-level assertion actually lives, and it was the
    one thing missing from `find_text`'s index long enough to make a true claim
    look like a validator bug. Naming it here means the drafter does not have
    to go looking for it.
    """
    change = event.diff.urlChanged
    if change is not None:
        return f"url: {change.from_} -> {change.to}"
    return f"url: {event.url}"


def _diff(event: CapturedEvent, noise: set[str]) -> str:
    """What this action changed on the page, named rather than counted.

    "+12 -3 ~1" tells the drafter that something happened; the node names tell
    it WHAT, which is the difference between writing "the page updates" and
    writing "the hamper capacity is updated". Both are prose the binder will
    have to prove, but only one of them is worth proving.
    """
    diff = event.diff
    counts = []
    if diff.added:
        counts.append(f"+{len(diff.added)}")
    if diff.removed:
        counts.append(f"-{len(diff.removed)}")
    if diff.changed:
        counts.append(f"~{len(diff.changed)}")

    named: list[str] = []

    # Changed nodes first, and the ordering is the whole point. "15 -> 18" says
    # what the action did; "Shop Now (button)" appearing in the tree does not.
    # Filling the summary with additions first is how six slots went to a
    # promotional carousel while the quantity counter -- the one thing the
    # tester was watching -- fell off the end.
    for change in diff.changed[:MAX_DIFF_NODES]:
        before = (change.before.value or change.before.name or "").strip()
        after = (change.after.value or change.after.name or "").strip()
        if after and before != after:
            named.append(f"{_short(before, 30)} -> {_short(after, 30)}")
        elif after:
            named.append(_short(after, 40))

    # A framework that re-renders a subtree reports every node in it as removed
    # and re-added, so a click that toggled one control comes back as +354/-355
    # -- and the first six "added" nodes are navigation chrome that was never
    # touched. Naming those actively misleads: the drafter reads "1. Delivery,
    # 2. Hamper" and writes a step about the delivery stage of the wizard, when
    # what actually happened was one field changing.
    if not _is_rerender(diff):
        for node in diff.added:
            if len(named) >= MAX_DIFF_NODES:
                break
            label = _node_label(node)
            if label and label not in noise:
                named.append(label)

    if diff.titleChanged is not None:
        named.append(f"title -> {_short(diff.titleChanged.to, 40)}")

    if not counts and not named:
        return ""
    head = " ".join(counts)
    if not named:
        # Said plainly rather than left blank, because "the page changed a lot
        # and none of it was legible from here" is exactly the case where a
        # drafter should spend a retrieval on `get_diff`.
        return f"{head} (re-render; nothing named)"
    return f"{head} | " + " | ".join(named)


#: Above this, an added/removed pair that is nearly balanced is a subtree being
#: replaced rather than content arriving. Below it, a handful of nodes coming
#: and going is ordinary and worth naming.
RERENDER_FLOOR = 40


def _is_rerender(diff: Any) -> bool:
    added, removed = len(diff.added), len(diff.removed)
    if added < RERENDER_FLOOR or removed < RERENDER_FLOOR:
        return False
    return abs(added - removed) <= max(added, removed) * 0.1


def _node_label(node: Any) -> str:
    name = (getattr(node, "name", "") or "").strip()
    value = (getattr(node, "value", "") or "").strip()
    role = (getattr(node, "role", "") or "").strip()
    text = name or value
    if not text:
        return ""
    return f'"{_short(text, 48)}"' + (f" ({role})" if role else "")


def _network(event: CapturedEvent) -> str:
    """The application's own traffic, with third-party noise pushed to a count.

    SS6.4 budgets nothing here, and on a commercial site that shows: `evt_001`
    of the Fortnum recording carries 33 requests, twelve of them "mutating"
    POSTs, essentially all analytics beacons. Listing those in full would bury
    the one request that says what the application did.
    """
    if not event.network:
        return ""

    page_host = _host(event.url)
    first_party = [c for c in event.network if _host(c.url) == page_host]
    third_party = len(event.network) - len(first_party)

    # A state-mutating request is the strongest cheap signal that the action
    # did something, so it is listed ahead of the reads.
    ordered = sorted(
        first_party,
        key=lambda c: (0 if (c.method or "").upper() in MUTATING else 1, c.startTime),
    )

    rendered = [
        f"{c.method} {_path(c.url)} {c.status if c.status is not None else '-'}"
        for c in ordered[:MAX_NETWORK]
    ]
    if len(ordered) > MAX_NETWORK:
        rendered.append(f"+{len(ordered) - MAX_NETWORK} more")
    if third_party:
        rendered.append(f"[{third_party} third-party]")
    return "  |  ".join(rendered) if rendered else ""


def _console(event: CapturedEvent) -> str:
    """Errors, with the uncaught ones marked.

    Marked rather than filtered: whether an uncaught exception belongs to the
    application or to an ad tag sitting on it is `bugmode`'s judgement, and
    hiding them here would take that decision away from the stage that owns it.
    """
    if not event.console:
        return ""
    rendered = []
    for entry in event.console[:MAX_CONSOLE]:
        mark = "uncaught " if entry.uncaught else ""
        rendered.append(f"{mark}{entry.level.value}: {_short(entry.text, 60)}")
    if len(event.console) > MAX_CONSOLE:
        rendered.append(f"+{len(event.console) - MAX_CONSOLE} more")
    return "  |  ".join(rendered)


def _narration(store: EvidenceStore, from_ms: float, to_ms: float) -> str:
    """What the tester said while doing this, if anything.

    Quoted here so the drafter can decide which outcome matters. It must not
    become the evidence for the claim: a mis-heard number becomes a literal
    that passes `evidence_retrieved` and `assertion_grounding` and is still
    false, which is why `bind.py` binds to what was on the PAGE.
    """
    spoken = store.narration(from_ms, to_ms)
    if not spoken:
        return ""
    joined = " ".join(s.text.strip() for s in spoken if s.text.strip())
    return _short(joined, MAX_NARRATION)


def _annotation(annotation: Any) -> str:
    kind = annotation.kind.value
    text = (annotation.text or "").strip()
    target = getattr(annotation, "target", None)
    if target is not None and (target.name or target.value):
        pointed = (target.name or target.value or "").strip()
        return f'{kind} -> "{_short(pointed, MAX_NAME)}"' + (f" — {text}" if text else "")
    return f"{kind}" + (f": {text}" if text else "")


def _dialog(event: CapturedEvent) -> str:
    dialog = event.dialog
    if dialog is None:
        return ""
    message = (getattr(dialog, "message", "") or "").strip()
    kind = getattr(dialog, "type", None)
    label = getattr(kind, "value", kind) or "dialog"
    return f"{label}: {message}" if message else str(label)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _host(url: str) -> str:
    if "://" not in url:
        return ""
    rest = url.split("://", 1)[1]
    return rest.split("/", 1)[0].lower()


def _path(url: str) -> str:
    """The path, which is what identifies a request to a reader.

    A full analytics URL is several hundred characters of query string and says
    nothing; the path says which endpoint was hit.
    """
    if "://" not in url:
        return _short(url, 48)
    rest = url.split("://", 1)[1]
    path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    return _short(path.split("?", 1)[0], 48)


def _short(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = ["IDLE_HINT_MS", "SessionDigest", "build_digest"]
