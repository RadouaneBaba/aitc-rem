"""Guess what SHOULD have happened, so a human only has to agree.

There is no oracle. The recording says what the application DID, which by
construction cannot tell you whether it was right, and the objective names a
feature rather than a behaviour -- the real ones on disk read *"check if filters
are working correctly"*, and four of four such objectives produced a run the
judge called bad. So every claim the pipeline can license is a restatement of
observed behaviour, and the tool is structurally unable to write a test that
fails on the build it recorded.

The way out is not a better validator. It is asking the one person who knows.
And the way to ask is **not** an open question: testers will not answer those.
Show them a guess and two buttons.

    You filtered by "In stock."
    The list went from 24 products to 9.
    Was that right?   [ok]  [no]  [edit]

This module writes the guesses. `server/api/app.py` serves them, the review UI
renders them, and whatever comes back is the oracle the author writes against.

**Guessing is the cheap half and it is allowed to be wrong.** A guess nobody
looks at stays `inferred` and its scenarios carry `@needs-review`; a guess
somebody ticks becomes `confirmed`. The expensive half was never the guess, it
was getting a busy person to write a sentence -- so this trades a model call for
a click.

**It retrieves, and for one reason: a guess nobody can tick is not an oracle.**
This ran with no tools at all until 2026-08-29, on the argument that
`digest.py` renders 34 events of a commercial session in ~1,600 tokens and the
drafting stage declined to retrieve on 30 of 30 investigations against it. That
argument was about a stage licensing claims from a summary, and it does not
transfer, because this stage is not writing a claim -- it is writing a QUESTION
for a human, and the whole prompt below turns on the difference between *"the
list should update"* and *"the list should drop from 24 products to 9"*. The
index carries a diff shape and a sample of changed text; the second number
routinely is not in it. A stage told to be specific and given nothing to be
specific from writes the vague version, and the vague version is the one the
tester cannot answer.

Bounded hard at `GUESS_BUDGET`, and the bound is the latency argument surviving
intact: `POST /api/recordings` guesses while the tester is still sitting there,
and a screen that takes two minutes to appear is a screen nobody waits for.
Three tools, not six -- more tools measurably means worse tool choice, and the
question here is only ever *what was on the page, and what changed*.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Expectation,
    ExpectationSet,
    ExpectationSource,
    PipelineStage,
)
from server.pipeline.digest import build_digest
from server.pipeline.investigate import investigate

#: Retrievals this stage may spend, over the WHOLE session rather than per
#: expectation. Small on purpose: the tester is waiting for this screen, and an
#: oracle that arrives after they have closed the tab is worth nothing. Enough
#: for the two or three moments where the index does not carry the value the
#: expectation has to name, and not enough to walk the session.
GUESS_BUDGET = 4

#: What it may reach for. `get_diff` and `get_snapshot` answer "what changed"
#: and "what was on the page"; `find_text` confirms the exact wording of a value
#: worth putting in front of a human. `see` is deliberately absent -- a
#: screenshot is ~1k tokens and this stage is the one with a person waiting on
#: it -- and so is `get_network`: a status code is not something a tester can
#: recognise as a description of what they just did.
EXPECTATION_TOOLS = ["get_diff", "get_snapshot", "find_text"]

#: Narration or an annotation this far either side of an event still counts as
#: being about it. An outcome annotation lands AFTER the thing it points at,
#: which is why the window is not symmetric in practice -- `store.annotations`
#: and `store.narration` both take a plain range, so the slack lives here.
INTENT_WINDOW_MS = 3000


SYSTEM_PROMPT = """\
You are a QA lead reading a recording of a tester using a web application. For
each thing they did that could be checked, write what SHOULD have happened.

You are writing the ORACLE. The recording tells you what the application did; it
cannot tell you whether that was correct. Your job is to say what a correct
application would have done, so a human can agree with one click or correct you.

An expectation has to be CHECKABLE. It names a value that would be different if
the feature were broken.

  bad   the filter should work correctly
  bad   the product list should update
  good  the list should drop from 24 products to 9
  bad   the hamper should change size
  good  the hamper should become a "Large Wicker Basket" with capacity 18 / 18

Write about the thing under test, not about the interface reacting. "A panel
should open" is not an expectation; what the panel should SAY is.

You can go and look. The session index is a summary: it shows the shape of what
changed and a sample of the text, so the exact value your expectation needs is
often not in it. When you are about to write a vague expectation because you do
not know the number, retrieve instead:

  get_diff(eventId)              what changed at this moment
  get_snapshot(eventId, when)    what was on the page, before or after
  find_text(text)                where a value appears, and its exact wording

Retrieve only for that. Most expectations need nothing -- the index already
names the value, or the action is setup and gets no expectation at all. You have
a small budget for the whole session, so spend it on the moments where being
specific is the difference between a question a tester can answer and one they
cannot.

Not every action deserves one. Signing in, navigating and opening a page are
usually setup: skip them unless the sign-in is what is being tested. Between six
and twelve expectations is normal for a long session; two is normal for a short
one. Prefer fewer, sharper ones.

`observed` is what the recording shows actually happened, in one clause. Say it
plainly even when it contradicts your expectation -- that disagreement is the
most valuable thing in the file, because it means the tester recorded a bug.

Set `fromTester` to true ONLY when the tester said or marked something about
that action themselves. Do not guess at this; it is checked.

Answer with JSON and nothing else:

{
  "expectations": [
    {
      "eventIds": ["evt_009"],
      "action": "You filtered the list to in-stock products.",
      "expected": "the list should drop from 24 products to 9",
      "observed": "the count changed from 24 to 9",
      "fromTester": false
    }
  ]
}

`action` is addressed to the tester, in the second person, and has to be
recognisable to someone who did it two minutes ago -- not accurate to someone
reading a trace. It is the heading they will see above two buttons.
"""


USER_PROMPT = """\
Here is the session.

{digest}

Write the expectations.
"""


def propose_expectations(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    model_name: str,
    temperature: float = 0.0,
    tools_enabled: bool = True,
    config: ProjectConfig | None = None,
) -> ExpectationSet:
    """One investigation over the session index. Returns guesses, all unconfirmed.

    `tools_enabled` is threaded from the run rather than hardcoded, so a
    configuration with no tools does not get a stage quietly reaching for them.
    A0 never reaches here -- it disables the oracle outright -- but a stage whose
    tool access depends on which caller happened to construct it is the shape of
    defect this file exists to avoid.
    """
    config = config or ProjectConfig()
    digest = build_digest(store)

    result = investigate(
        runner,
        model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT.format(digest=digest.text),
        model_name=model_name,
        stage=PipelineStage.expectations,
        label="expectations",
        budget=GUESS_BUDGET,
        tools_enabled=tools_enabled,
        tool_names=EXPECTATION_TOOLS,
        temperature=temperature,
    )
    return _parse(result.answer, store)


def empty_set(recording_id: str) -> ExpectationSet:
    """What a recording has before anyone has guessed anything.

    A first-class value rather than `None`: every caller downstream has to cope
    with a recording nobody has answered for -- that is the normal case, not an
    error -- and an empty set says so without a special branch.
    """
    return ExpectationSet(
        schemaVersion="1.0",
        recordingId=recording_id,
        createdAt=datetime.now(UTC),
        expectations=[],
    )


def _parse(answer: dict[str, Any], store: EvidenceStore) -> ExpectationSet:
    out = empty_set(store.recording.id)
    raw = answer.get("expectations")
    if not isinstance(raw, list):
        return out

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        expected = _clean(item.get("expected"))
        if not expected:
            continue

        # Only ids the recording actually has. A model naming an event that does
        # not exist would otherwise put an expectation on nothing, and the
        # confirmation screen would show a card with no picture and no action.
        event_ids = [e for e in _strings(item.get("eventIds")) if store.has_event(e)]
        if not event_ids:
            continue

        out.expectations.append(
            Expectation(
                id=f"exp_{index:03d}",
                eventIds=event_ids,
                action=_clean(item.get("action")) or _fallback_action(store, event_ids[0]),
                expected=expected,
                observed=_clean(item.get("observed")) or None,
                # `stated` is PROVED, never taken from the answer. The model is
                # asked whether the tester said something, and then the
                # recording is checked -- same shape as every other claim here:
                # a citation the model cannot fabricate, because it does not
                # supply it.
                source=(
                    ExpectationSource.stated
                    if item.get("fromTester") and _tester_spoke_about(store, event_ids)
                    else ExpectationSource.inferred
                ),
                screenshot=_screenshot(store, event_ids),
            )
        )
    return out


def _tester_spoke_about(store: EvidenceStore, event_ids: list[str]) -> bool:
    """Did the tester actually say or mark anything about these actions?

    The check behind `stated`. Narration and annotations are the two direct
    statements of intent a recording can carry, and `stated` outranks `inferred`
    in the review UI and in what the author is told -- so it has to be a fact
    about the recording rather than a model's recollection of one.
    """
    events = [store.event(e) for e in event_ids if store.has_event(e)]
    if not events:
        return False
    start = min(e.timestamp for e in events) - INTENT_WINDOW_MS
    end = max(e.timestamp for e in events) + INTENT_WINDOW_MS

    if any(a.text or a.target for a in store.annotations(start, end)):
        return True
    return bool(store.narration(start, end))


def _fallback_action(store: EvidenceStore, event_id: str) -> str:
    """A heading for the confirmation screen when the model did not write one.

    Deliberately plain rather than clever. The tester is looking at a
    screenshot; the heading only has to tell them which moment it is.
    """
    event = store.event(event_id)
    name = (event.target.name or "").strip()
    verb = {"input": "You typed into", "select": "You chose in", "submit": "You submitted"}.get(
        event.type.value, "You clicked"
    )
    return f"{verb} {name!r}." if name else f"{verb} the {event.target.role}."


def _screenshot(store: EvidenceStore, event_ids: list[str]) -> str | None:
    """The picture for the moment being asked about, if the recorder got one.

    `chrome.tabs.captureVisibleTab` allows about two calls a second, so a rapid
    sequence leaves some events without one -- on the checkout fixture, 4 of 10.
    The search is over THIS expectation's own events, last first, because the
    last one is where the outcome is and any of them is a picture of the thing
    being asked about.

    It stops there. A neighbouring event's screenshot is a picture of a
    different moment, and the whole screen works by asking someone to judge what
    they are looking at -- showing them the wrong page and asking "was that
    right" is worse than showing them none. The card without a picture still
    carries the action, the expectation and what was observed, which is
    readable; the card with the WRONG picture is a trap.
    """
    for event_id in reversed(event_ids):
        if store.has_event(event_id) and store.event(event_id).screenshot:
            return store.event(event_id).screenshot
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


__all__ = ["EXPECTATION_TOOLS", "GUESS_BUDGET", "empty_set", "propose_expectations"]
