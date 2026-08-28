"""One author, with real evidence, writing the whole test document.

Replaces `draft.py` + `bind.py` + `split.py` + `run._second_chance` +
`bugmode.py`. Those were five stages arranged around a problem that turned out
not to be the one they were solving.

## Why five stages became one

The old shape asked *"what can I prove?"* and wrote a test around the answer. A
drafter proposed sentences with no obligation to have retrieved anything; a
binder then proved each claim or **deleted** it; a splitter re-cut the result; a
second-chance pass re-asked when a scenario had been left with no verdict at
all. Every one of those stages is downstream machinery for catching a model
guessing about something it could not see -- and it could not see because the
recorder was capturing the landmark around the click rather than the page. On
30-50% of events the candidate set for an assertion was literally empty.

Open the aperture and most of the apparatus has nothing left to catch. What
remains is the part that was always load-bearing: **the citation.** The author
names a literal it says it saw; `evidence.citation` finds which of its own
retrievals contains that string. A fabricated citation is not something it can
express, because it never supplies a `toolCallId`.

## What is different, and what is deliberately not

*Different.* It sees the whole session and the expectations, it splits into
scenarios as it writes rather than being re-cut afterwards, and **refusal is
something it writes** -- `whyNot`, in language a tester can act on -- instead of
something done to it. A claim that could not be proved used to be deleted, and
the scenario quietly ended with no `Then`.

*Not different.* Draft-then-bind survives inside the loop rather than across
stages: it decides what is worth checking and then goes and looks. An author
that may only claim what it has already retrieved writes about whatever was easy
to retrieve.

## The prompt

Roughly seventy percent worked example. Every content rule ever added to a
drafting prompt in this project measured at or near zero uptake -- *"assert the
value that would BREAK"* took on one step in three and cost the run its split --
while every improvement came from more context. The example is a fresh, neutral
domain on purpose: drawing one from an existing run anchors the model to a past
result instead of giving it a target, which this project already learned once
when the critic's worked example was the recording it judged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.config import ProjectConfig
from server.evidence.citation import resolve_call
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Assertion,
    Confidence,
    Evidence,
    ExpectationSet,
    ExpectationSource,
    OmissionReason,
    PipelineStage,
    Provenance,
    ScenarioExamples,
    SegmentRole,
    StepInvestigation,
)
from server.pipeline.digest import SessionDigest, build_digest
from server.pipeline.expectations import INTENT_WINDOW_MS
from server.pipeline.investigate import investigate

#: Retrievals one author may make across a whole session.
#:
#: Generous, and it is meant to be spent unevenly. SS3.3's claim is that an
#: obvious step costs zero calls and a contested one costs fifteen, and that
#: variance is the observable signature of an agent deciding rather than a
#: pipeline executing. A per-step budget cannot express it.
AUTHOR_BUDGET = 24

#: Six, not twelve. The drafting stage was once handed twelve tools and told
#: about five, and more tools measurably means worse tool choice. Everything
#: dropped is either already in the session index (`get_events`,
#: `get_objective`), superseded by full-page capture (`get_full_snapshot`,
#: `query_element`), or gone (`search_step_library`).
AUTHOR_TOOLS = [
    "get_diff",
    "get_snapshot",
    "see",
    "find_text",
    "get_network",
    "get_narration",
]


# --------------------------------------------------------------------------
# what comes out
# --------------------------------------------------------------------------


@dataclass
class AuthoredStep:
    step_id: str
    keyword: str
    role: SegmentRole
    text: str
    event_ids: list[str]
    #: Already proved. There is no separate binding stage: a claim the author
    #: could not cite never becomes one of these.
    assertions: list[Assertion] = field(default_factory=list)
    #: Why there is no expected result here, in the tester's language. Set
    #: either because the author declined to make a claim or because the claim
    #: it made could not be resolved to a retrieval.
    why_not: str = ""
    #: This step is where the application got it wrong.
    #:
    #: "Expected 9 products, saw 24" is the same sentence whether you call it an
    #: assertion or a bug report, which is why bug mode is not a stage any more.
    #: It reaches here one of two ways: the tester pressed "Not right" on the
    #: confirmation screen, or the author saw the application contradict what
    #: should have happened. Either way the expected result stands as written --
    #: the test is SUPPOSED to fail on this build.
    bug: bool = False
    #: What the application did instead. Only meaningful with `bug`.
    actual: str = ""


@dataclass
class AuthoredScenario:
    name: str
    steps: list[AuthoredStep] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    examples: ScenarioExamples | None = None


@dataclass
class AuthoredOmission:
    event_ids: list[str]
    reason: OmissionReason
    summary: str


@dataclass
class AuthoredDocument:
    """The whole document, with every surviving claim already cited."""

    title: str
    description: str
    tags: list[str]
    scenarios: list[AuthoredScenario] = field(default_factory=list)
    omitted: list[AuthoredOmission] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    model_calls: list = field(default_factory=list)
    confidence: Confidence = Confidence.medium
    #: Set when the model failed and the deterministic fallback wrote this.
    degraded: str = ""
    digest: SessionDigest | None = None
    #: Claims the author made that could not be resolved to a retrieval, with
    #: the reason. Kept because a refusal nobody can see is indistinguishable
    #: from a step that was never worth checking.
    refused: list[dict[str, str]] = field(default_factory=list)

    @property
    def steps(self) -> list[AuthoredStep]:
        return [step for scenario in self.scenarios for step in scenario.steps]

    def to_artifact(self) -> dict[str, Any]:
        """What lands in `author.json`. SS9.1's open-the-file-and-see-who-lied."""
        return {
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "degraded": self.degraded,
            "confidence": self.confidence.value,
            "uncertainties": list(self.uncertainties),
            "refused": list(self.refused),
            "scenarios": [
                {
                    "name": scenario.name,
                    "tags": list(scenario.tags),
                    **(
                        {"examples": scenario.examples.model_dump(mode="json")}
                        if scenario.examples
                        else {}
                    ),
                    "steps": [
                        {
                            "id": step.step_id,
                            "keyword": step.keyword,
                            "role": step.role.value,
                            "text": step.text,
                            "eventIds": list(step.event_ids),
                            **({"whyNot": step.why_not} if step.why_not else {}),
                            **({"bug": True, "actual": step.actual} if step.bug else {}),
                            "assertions": [
                                a.model_dump(mode="json", exclude_none=True)
                                for a in step.assertions
                            ],
                        }
                        for step in scenario.steps
                    ],
                }
                for scenario in self.scenarios
            ],
            "omitted": [
                {
                    "eventIds": list(o.event_ids),
                    "reason": o.reason.value,
                    "summary": o.summary,
                }
                for o in self.omitted
            ],
        }


# --------------------------------------------------------------------------
# the tester's own words
# --------------------------------------------------------------------------


#: An outcome annotation lands after the thing it points at, so a window that
#: stops at the last event of a step misses the note describing what was seen.
SETTLE_TAIL_MS = 2000


def intent_notes(store: EvidenceStore) -> dict[str, str]:
    """Map each event to the note the tester typed for the step it starts.

    SS6.7. A note names the step that starts NEXT: typing one means stopping,
    opening the popup and describing something, which a tester does before
    doing the thing rather than after. The `annotated` fixture proves it -- the
    note lands between the sign-in click and the add-to-cart click and
    describes adding to the cart. Falling back to the event containing it
    covers the tester who narrates after the fact instead.

    Keyed on the EVENT rather than on the segment, because the author chooses
    step boundaries and a segment is no longer a step.
    """
    notes = [
        n for n in store.annotations(0, float("inf"), kind="intent_note") if (n.text or "").strip()
    ]
    if not notes:
        return {}

    events = store.events_in_range(None, None)
    out: dict[str, str] = {}
    for note in notes:
        upcoming = next((e.id for e in events if e.timestamp >= note.timestamp), None)
        containing = next(
            (e.id for e in events if e.timestamp <= note.timestamp <= e.timestamp + SETTLE_TAIL_MS),
            None,
        )
        target = upcoming or containing
        # First note wins: a tester who typed twice for one step meant the
        # first description, and concatenating them silently would produce a
        # sentence neither of them wrote.
        if target and target not in out:
            out[target] = note.text.strip()
    return out


def apply_intent_notes(store: EvidenceStore, document: AuthoredDocument) -> set[str]:
    """Give a step the tester's own words, verbatim (SS6.7).

    The popup tells the tester the note "will be used word for word". That is a
    promise, and a promise a model is merely asked to keep is not kept: the
    first implementation of this never read the annotation on the server side
    at all, so a tester who took the trouble to describe a step watched the
    tool rewrite it anyway.

    Enforced by not asking a model rather than by asking one not to paraphrase.
    Applies only where the note's event OPENS a step -- a note describes the
    step that starts next, and stamping its text onto a step that merely
    contains that event somewhere in the middle would rename the wrong thing.

    Returns the ids of the steps whose wording is now the tester's. Nothing
    downstream rewrites a step any more, so this is now a fact for the review UI
    rather than a fence around one -- but it is still the promise the popup
    made, and it is still kept in code rather than in a prompt.
    """
    notes = intent_notes(store)
    if not notes:
        return set()

    dictated: set[str] = set()
    for step in document.steps:
        if not step.event_ids:
            continue
        note = notes.get(step.event_ids[0])
        if note:
            step.text = note
            dictated.add(step.step_id)
    return dictated


# --------------------------------------------------------------------------
# the prompt
# --------------------------------------------------------------------------


WORKED_EXAMPLE = """\
Here is one good answer, on a different application, end to end.

The session index said:

    evt_001  click  button "Find a room"            | +12 -0 ~0 | "3 rooms free"
    evt_002  select combobox "Duration"  -> "2 hours" | +0 -0 ~1 | "14:00-16:00"
    evt_003  click  button "Book Ada Lovelace Room" | POST /api/bookings 201
             +4 -1 ~1 | "Booked: Ada Lovelace Room, 14:00-16:00" | "2 rooms free"
    evt_004  click  link "My bookings"              | url -> /bookings | +31 -22 ~0

The tester expected: "booking a room should take it out of the free count".

The author called get_diff("evt_003"), saw the count change, and called
find_text("2 rooms free") to be sure of the exact wording. Two calls. It did not
retrieve anything for evt_001 or evt_002, because nothing about them was in
doubt.

    {
      "feature": "Meeting room booking",
      "description": "Booking a room confirms it and removes it from availability",
      "tags": ["booking"],
      "scenarios": [
        {
          "name": "Booking a room reduces the number free",
          "steps": ["step_001", "step_002", "step_003"]
        },
        {
          "name": "A confirmed booking appears in the tester's own list",
          "steps": ["step_004"]
        }
      ],
      "steps": [
        {
          "id": "step_001",
          "keyword": "Given",
          "role": "setup",
          "text": "the tester searches for an available room",
          "events": ["evt_001"]
        },
        {
          "id": "step_002",
          "keyword": "When",
          "role": "test_step",
          "text": "the tester books the Ada Lovelace Room for 2 hours",
          "events": ["evt_002", "evt_003"],
          "expected": "the room is confirmed for 14:00-16:00",
          "evidence": {
            "eventId": "evt_003",
            "literal": "Booked: Ada Lovelace Room, 14:00-16:00"
          }
        },
        {
          "id": "step_003",
          "keyword": "Then",
          "role": "test_step",
          "text": "the tester checks the availability count",
          "events": [],
          "expected": "the number of free rooms drops from 3 to 2",
          "evidence": { "eventId": "evt_003", "literal": "2 rooms free" }
        },
        {
          "id": "step_004",
          "keyword": "When",
          "role": "test_step",
          "text": "the tester opens their own bookings",
          "events": ["evt_004"],
          "expected": null,
          "whyNot": "The bookings page replaced most of the screen and nothing on it names the room that was just booked, so there is no way to tell this list apart from any other list of bookings."
        }
      ],
      "omitted": []
    }

Four things in that answer are worth copying.

**The verdict is the count, not the confirmation banner.** Both were on the
page. Break the availability feature and "Booked: ..." still appears, so a test
resting only on the banner passes on a broken build. The count is what the
feature computes.

**step_003 has no events.** An expected result is about what the APPLICATION
did; it does not need an action of its own. Do not invent a click to hang it on.

**step_004 refuses, and says why in a sentence its tester can act on.** That is
worth more than a claim about a heading being present. Never write an expected
result that amounts to "the page appeared".

**Two scenarios, decided while writing.** They check different things.
"""


SYSTEM_PROMPT = """\
You are a QA engineer. You are given a recording of somebody using a web
application, and you write the test cases for it.

{example}

## How to work

The session index below is the map. It lists every event, what was clicked, what
changed, what the network did and what the tester said. For most steps it is
enough.

The tools are the territory, for when it is not:

  get_diff(eventId)        what changed on the whole page, most informative first
  get_snapshot(eventId)    the full page, before or after
  see(eventId)             look at the screenshot -- use it when the text does
                           not settle it
  find_text(query)         where a string really appears in the session
  get_network(eventId)     the requests
  get_narration(from, to)  what the tester said out loud

Look when a claim is contested and not when it is obvious. An unambiguous step
should cost you nothing; one where you cannot tell what changed deserves as many
calls as it takes.

## The rules that are not obvious

**A step says what the TESTER did. An expected result says what the APPLICATION
did.** "the tester submits the order" is a step; "the order is confirmed" is an
expected result. "clicks the Save button" is neither -- it describes the
mechanism, and a test written against the mechanism breaks when the button
moves.

**Assert the value the feature COMPUTES, not the label the tester chose.** After
choosing "Price: low to high", the page still says "Price: low to high" whether
or not it sorted anything. Assert the order, or the first price.

**An expected result costs one retrieval, always.** The `literal` must be a
string a TOOL gave back to you, character for character. Seeing it in the
session index above is not enough -- the index is a summary, and a claim resting
on it points at nothing. So before you write an `expected`, call `get_diff` or
`find_text` or `get_snapshot` on that event and quote from the answer.

This is not a formality and it is not negotiable: a claim you cannot point at is
dropped, and the step ends up with a `whyNot` saying you did not look. If you
write four expected results, expect to have made at least four calls. You do not
supply the id of the retrieval -- that is looked up from what you actually
called, which is why you cannot invent one.

**Only the scenario needs a verdict, not every step.** `When ... And ... And ...
Then` is normal and often better than a verdict on every line.

**If you cannot check something, say so in `whyNot` and move on.** A refusal a
tester can act on beats a claim that proves nothing. Never pad a scenario with
an expected result that says the interface appeared.

## What to answer with

JSON, and nothing else, in the shape of the worked example. Additionally:

* `role` is one of setup, test_step, teardown, exploratory, abandoned. Signing
  in and navigating are usually setup.
* `keyword` is Given, When or Then. Given belongs to the opening block.
* Every recorded event must appear in exactly one step's `events`, or in
  `omitted` with a reason naming it. Nothing the tester did may silently vanish.
* A scenario may carry `"examples": {{"columns": [...], "rows": [[...], ...]}}`
  when the same flow was genuinely repeated with different values. Use step text
  like "the tester adds <items> items" and it renders as a Scenario Outline.
  Only when the flow really repeats -- never to make one run look like two.

{voice}
"""


USER_PROMPT = """\
{expectations}

Here is the session.

{digest}
{feedback}
Write the test cases.
"""


FEEDBACK = """\

## You have written this once already, and it came back

A reviewer read the document and the gate checked it. Here is everything that
was wrong with it:

{findings}

Write the document again, whole. Fix what is named above and change nothing
else -- a rewrite that also reshuffles the parts nobody objected to makes it
impossible to tell what the revision was for.

Two things are worth saying because they are counter-intuitive under criticism:

**A verdict you cannot prove is still a `whyNot`.** If a finding asks for an
assertion the recording does not support, say so in `whyNot` rather than
reaching for a weaker literal. Being told that a verdict proves nothing is not
permission to bind a different thing that also proves nothing.

**Never make two steps in one scenario say the same thing.** Two adjacent steps
with identical text are folded into one, so the document silently loses a step
and the whole revision is refused. If a finding pushes you toward a more generic
sentence, keep the detail that tells it apart from its neighbour.
"""


NO_EXPECTATIONS = """\
Nobody has said what should have happened, so you are working from the recording
alone. Be correspondingly careful: the recording can only tell you what the
application DID, and a test that merely restates that will pass on a broken
build. Where you cannot tell whether something was right, say so in `whyNot`.
"""


def _feedback_block(feedback: list[str] | None) -> str:
    """The findings, numbered, or nothing at all on a first attempt."""
    if not feedback:
        return ""
    findings = "\n".join(f"{n}. {text}" for n, text in enumerate(feedback, start=1))
    return FEEDBACK.format(findings=findings)


def _voice_rule(config: ProjectConfig) -> str:
    if config.first_person:
        return 'Write steps in the first person: "I submit the order".'
    return f'Every step names its subject: "{config.voice} submits the order".'


def _expectations_block(expectations: ExpectationSet | None) -> str:
    """The oracle, rendered for the prompt, loudest signal first.

    A rejected expectation is put first and marked, because it is the only input
    in the whole system that says the application did the WRONG thing. Burying
    it among nine confirmations is how it gets treated as one more sentence.
    """
    if not expectations or not expectations.expectations:
        return NO_EXPECTATIONS

    rejected = [e for e in expectations.expectations if e.source == ExpectationSource.rejected]
    rest = [e for e in expectations.expectations if e.source != ExpectationSource.rejected]

    lines = ["The tester was asked what should have happened. Their answers:"]
    if rejected:
        lines.append("")
        lines.append(
            "THESE DID NOT HAPPEN. The tester says the application got them wrong. Write the "
            "step, write what should have happened as the expected result, and set "
            '"bug": true on it -- the test is supposed to FAIL on this build.'
        )
        for item in rejected:
            lines.append(f"  {', '.join(item.eventIds)}: should have {item.expected}")
            if item.observed:
                lines.append(f"      instead: {item.observed}")
            if item.note:
                lines.append(f"      they added: {item.note}")

    if rest:
        lines.append("")
        for item in rest:
            mark = {
                ExpectationSource.confirmed: "confirmed",
                ExpectationSource.corrected: "in their own words",
                ExpectationSource.stated: "they said this during the recording",
                ExpectationSource.inferred: "a guess nobody has checked",
            }.get(item.source, item.source.value)
            lines.append(f"  {', '.join(item.eventIds)}: should {item.expected}  [{mark}]")

    lines.append("")
    lines.append(
        "Where one of these covers a step, it IS the expected result -- reword it to fit the "
        "scenario, but do not quietly replace it with something easier to prove."
    )
    return "\n".join(lines)


def write_document(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    model_name: str,
    budget: int = AUTHOR_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    expectations: ExpectationSet | None = None,
    feedback: list[str] | None = None,
) -> AuthoredDocument:
    """One conversation. Out comes the whole document, cited.

    `feedback` makes it a revision: what the gate rejected and what the judge
    would send back, as sentences rather than as a report. It arrives as context
    on a FRESH conversation rather than as another turn on the old one, for the
    same reason the judge never sees the author's reasoning -- a model shown its
    own justification for a claim defends it.
    """
    config = config or ProjectConfig()
    digest = build_digest(store)

    result = investigate(
        runner,
        model,
        system_prompt=SYSTEM_PROMPT.format(
            example=WORKED_EXAMPLE, voice=_voice_rule(config)
        ),
        user_prompt=USER_PROMPT.format(
            expectations=_expectations_block(expectations),
            digest=digest.text,
            feedback=_feedback_block(feedback),
        ),
        model_name=model_name,
        stage=PipelineStage.author,
        label="author",
        budget=budget if tools_enabled else 0,
        tools_enabled=tools_enabled,
        temperature=temperature,
        tool_names=AUTHOR_TOOLS,
    )

    document = _parse(result.answer, store, runner, result.tool_call_ids, config, expectations)
    document.digest = digest
    document.uncertainties = list(result.uncertainties)
    document.investigation = result.record(
        investigation_id="inv_author",
        stage=PipelineStage.author,
        budget=budget,
    )
    document.model_calls = list(result.model_calls)
    return document


# --------------------------------------------------------------------------
# parsing, and the one check that survives
# --------------------------------------------------------------------------


def _parse(
    answer: dict[str, Any],
    store: EvidenceStore,
    runner: ToolRunner,
    tool_call_ids: list[str],
    config: ProjectConfig,
    expectations: ExpectationSet | None,
) -> AuthoredDocument:
    raw_steps = answer.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return _fallback(store, config, why="the author returned no steps")

    document = AuthoredDocument(
        title=_clean(answer.get("feature")) or _fallback_title(store),
        description=_clean(answer.get("description")),
        tags=_tags(answer.get("tags"), config),
    )

    by_id: dict[str, AuthoredStep] = {}
    for index, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            continue
        text = _clean(raw.get("text"))
        if not text:
            continue
        step_id = _clean(raw.get("id")) or f"step_{index:03d}"
        step = AuthoredStep(
            step_id=step_id,
            keyword=_keyword(raw.get("keyword")),
            role=_role(raw.get("role")),
            text=with_subject(text, config),
            event_ids=[e for e in _strings(raw.get("events")) if store.has_event(e)],
            why_not=_clean(raw.get("whyNot")),
            bug=bool(raw.get("bug")),
            actual=_clean(raw.get("actual")),
        )
        _attach_claim(step, raw, store, runner, tool_call_ids, document, expectations)
        by_id[step_id] = step

    document.scenarios = _scenarios(answer.get("scenarios"), by_id, config)
    if not document.scenarios:
        # A document with steps and no usable scenario grouping is still a
        # document. One scenario beats losing the run.
        document.scenarios = [AuthoredScenario(name=document.title, steps=list(by_id.values()))]

    document.omitted = _omissions(answer.get("omitted"), store)
    _apply_rejections(document, expectations)
    return document


def _apply_rejections(document: AuthoredDocument, expectations: ExpectationSet | None) -> None:
    """A rejected expectation makes its step a bug, whatever the author decided.

    The tester pressed "Not right": they are saying the application did the
    wrong thing here, and that is the one finding nothing else in the system can
    produce. The prompt asks the author to mark it, and a prompt that asks is
    not a guarantee -- the same reason an intent note is stamped on rather than
    requested.

    The expected result is left exactly as it is. A bug report's whole point is
    that the test SHOULD fail on this build.
    """
    if not expectations:
        return
    rejected = {
        event_id: item
        for item in expectations.expectations
        if item.source == ExpectationSource.rejected
        for event_id in item.eventIds
    }
    if not rejected:
        return
    for step in document.steps:
        item = next((rejected[e] for e in step.event_ids if e in rejected), None)
        if item is None:
            continue
        step.bug = True
        if not step.actual:
            step.actual = item.observed or ""


def _attach_claim(
    step: AuthoredStep,
    raw: dict[str, Any],
    store: EvidenceStore,
    runner: ToolRunner,
    tool_call_ids: list[str],
    document: AuthoredDocument,
    expectations: ExpectationSet | None,
) -> None:
    """Turn the author's claim into a cited assertion, or refuse it out loud.

    This is the whole of what used to be `bind.py`, and it is short now for one
    reason: the refusal rules that made it 1,213 lines -- `_existence_only`,
    `_own_input`, `_unwitnessed`, `evidence_discriminates` -- were each catching
    a symptom of an author with nothing to look at. They are regexes guessing
    whether a sentence means anything, and a regex will always lose that to a
    model reading it. The judge asks the question they were approximating.

    What stays is the one check that cannot be wrong: **does the string the
    author quoted actually appear in a response it actually received.**
    """
    expected = _clean(raw.get("expected"))
    if not expected:
        if not step.why_not:
            # Silence is legitimate -- only the scenario needs a verdict -- so
            # this is not recorded as a refusal.
            return
        return

    evidence = raw.get("evidence")
    literal = _clean(evidence.get("literal")) if isinstance(evidence, dict) else ""
    if not literal:
        _refuse(step, document, expected, "the author quoted nothing to rest it on")
        return

    call_id = resolve_call(runner, tool_call_ids, literal)
    if call_id is None:
        # It may still be true. It is simply not something this run went and
        # looked at, and the whole architecture exists to keep those apart.
        _refuse(
            step,
            document,
            expected,
            f"nothing this run retrieved contains {literal[:60]!r}",
        )
        return

    event_id = _clean(evidence.get("eventId")) if isinstance(evidence, dict) else ""
    if not store.has_event(event_id):
        event_id = step.event_ids[-1] if step.event_ids else ""

    if not event_id or not store.contains_at(literal, event_id, case_sensitive=True):
        elsewhere = store.events_containing(literal, case_sensitive=True)
        if len(elsewhere) == 1:
            # Real, just somewhere else. Re-pointing is safe: the literal and
            # the retrieval are unchanged, only the moment it became true.
            event_id = elsewhere[0]
        else:
            _refuse(
                step,
                document,
                expected,
                f"{literal[:60]!r} does not appear at {event_id or 'any event of this step'}",
            )
            return

    step.assertions.append(
        Assertion(
            id=f"assert_{step.step_id.split('_')[-1]}_001",
            text=expected,
            provenance=_provenance(step, store, expectations),
            evidence=Evidence(
                literal=literal,
                toolCallId=call_id,
                eventId=event_id,
                kind=_clean((evidence or {}).get("kind")) or "semantic_node",
            ),
            accepted=True,
        )
    )
    # A claim that landed leaves no refusal behind, even if the author wrote
    # one speculatively.
    step.why_not = ""


def _refuse(step: AuthoredStep, document: AuthoredDocument, claim: str, reason: str) -> None:
    """Drop a claim, and leave a sentence where it was.

    The old pipeline deleted it silently; the scenario then ended with no
    `Then` and a style warning said so in a vocabulary nobody outside the
    pipeline reads. 27 of those warnings were a readout of the capture problem
    and not one of them told a reviewer what to do.
    """
    document.refused.append({"stepId": step.step_id, "claim": claim, "reason": reason})
    if not step.why_not:
        step.why_not = f"Could not check that {claim}: {reason}."


def _provenance(
    step: AuthoredStep, store: EvidenceStore, expectations: ExpectationSet | None
) -> Provenance:
    """How direct a statement of intent this claim rests on (SS9.5).

    Verified against the recording and the answers file rather than asked of the
    model, for the reason every provenance rank here is: a rank the model can
    assert is a rank it will assert.
    """
    events = set(step.event_ids)
    if expectations:
        for item in expectations.expectations:
            if not events.intersection(item.eventIds):
                continue
            if item.source in (ExpectationSource.confirmed, ExpectationSource.corrected):
                return Provenance.confirmed

    # `narrated` and `annotated` stay apart because they are different things:
    # one is the tester SAYING what they were checking, the other is them
    # POINTING at it. Narration is also the only lossy source here -- a
    # transcript is a reconstruction, and a mis-heard number passes every check
    # in this file -- so a reader has to be able to see which a claim rests on.
    # Checked against the recording rather than asked of the model, for the
    # reason every rank here is: a rank a model may assert is one it will.
    for event_id in step.event_ids:
        if store.event(event_id).annotations:
            return Provenance.annotated
    if step.event_ids:
        seen = [store.event(e) for e in step.event_ids]
        start = min(e.timestamp for e in seen) - INTENT_WINDOW_MS
        end = max(e.timestamp for e in seen) + INTENT_WINDOW_MS
        if store.narration(start, end):
            return Provenance.narrated
    if store.objective:
        return Provenance.objective
    return Provenance.inferred


def _scenarios(
    value: Any, by_id: dict[str, AuthoredStep], config: ProjectConfig
) -> list[AuthoredScenario]:
    if not isinstance(value, list):
        return []
    out: list[AuthoredScenario] = []
    used: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        steps = [by_id[s] for s in _strings(raw.get("steps")) if s in by_id and s not in used]
        if not steps:
            continue
        used.update(s.step_id for s in steps)
        out.append(
            AuthoredScenario(
                name=_clean(raw.get("name")),
                steps=steps,
                tags=_tags(raw.get("tags"), config, inherit=False),
                examples=_examples(raw.get("examples")),
            )
        )

    # Any step the scenarios forgot joins the last one rather than vanishing.
    # `event_coverage` counts events into steps, so a dropped step is a dropped
    # event, and losing one silently is the single thing that net exists for.
    orphans = [s for s in by_id.values() if s.step_id not in used]
    if orphans:
        if out:
            out[-1].steps.extend(orphans)
        else:
            out.append(AuthoredScenario(name="", steps=orphans))
    return out


def _examples(value: Any) -> ScenarioExamples | None:
    if not isinstance(value, dict):
        return None
    columns = _strings(value.get("columns"))
    rows_raw = value.get("rows")
    if not columns or not isinstance(rows_raw, list):
        return None
    rows = [
        [str(cell) for cell in row] for row in rows_raw if isinstance(row, list) and len(row) == len(columns)
    ]
    # One row is not a table. `parameters: inline` already renders a single set
    # of values in the step text, where a reader finds them without looking in
    # two places.
    if len(rows) < 2:
        return None
    return ScenarioExamples(columns=columns, rows=rows)


def _omissions(value: Any, store: EvidenceStore) -> list[AuthoredOmission]:
    if not isinstance(value, list):
        return []
    out: list[AuthoredOmission] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        events = [e for e in _strings(raw.get("events") or raw.get("eventIds")) if store.has_event(e)]
        if not events:
            continue
        out.append(
            AuthoredOmission(
                event_ids=events,
                reason=_reason(raw.get("reason")),
                summary=_clean(raw.get("summary")) or _clean(raw.get("reason")),
            )
        )
    return out


_REASONS = {r.value: r for r in OmissionReason}


def _reason(value: Any) -> OmissionReason:
    return _REASONS.get(str(value or "").strip().lower(), OmissionReason.exploratory)


def with_subject(text: str, config: ProjectConfig) -> str:
    """Make sure the step says who is doing it.

    A step is a sentence about a person. Dropped, it reads as an instruction to
    the reader and matches no step definition -- and it happens: a prompt whose
    worked examples omitted the subject produced "submits an order totalling
    \"615\"" with nobody submitting anything.

    Deterministic rather than another prompt line, because the prompt already
    says it and said it while an example showed the opposite. Worked examples
    outweigh rules and will contradict them silently; this is the net under
    that. Left alone when any plausible subject is present, so "the approver
    releases the order" is not rewritten into nonsense.
    """
    if not text or config.first_person:
        return text
    lowered = text.lower()
    if lowered.startswith(config.voice.lower()) or lowered.startswith(("the ", "an ", "a ", "i ")):
        return text
    return f"{config.voice} {text[0].lower() + text[1:]}"


_KEYWORDS = {"given": "Given", "when": "When", "then": "Then", "and": "And", "but": "But"}


def _keyword(value: Any) -> str:
    return _KEYWORDS.get(str(value or "").strip().lower(), "When")


_ROLES = {r.value: r for r in SegmentRole}


def _role(value: Any) -> SegmentRole:
    return _ROLES.get(str(value or "").strip().lower(), SegmentRole.test_step)


def _tags(value: Any, config: ProjectConfig, *, inherit: bool = True) -> list[str]:
    tags = [t.lstrip("@") for t in _strings(value)]
    if inherit:
        tags = [*config.tags, *tags]
    return list(dict.fromkeys(t for t in tags if t))


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _fallback_title(store: EvidenceStore) -> str:
    return store.objective or "Recorded session"


def _fallback(store: EvidenceStore, config: ProjectConfig, *, why: str) -> AuthoredDocument:
    """A readable document when the model produced nothing usable.

    Degrades loudly rather than failing: one step per event, no claims, and
    `degraded` set so every renderer and the review UI can say why. A run that
    dies takes the recording with it; a run that says "I could not read this"
    leaves the evidence for somebody else.
    """
    steps = [
        AuthoredStep(
            step_id=f"step_{index:03d}",
            keyword="When" if index > 1 else "Given",
            role=SegmentRole.test_step if index > 1 else SegmentRole.setup,
            text=f"the tester interacts with {event.target.name or event.target.role}",
            event_ids=[event.id],
            why_not="The author did not produce a document for this run.",
        )
        for index, event in enumerate(store.events_in_range(None, None), start=1)
    ]
    return AuthoredDocument(
        title=_fallback_title(store),
        description="",
        tags=_tags(None, config),
        scenarios=[AuthoredScenario(name=_fallback_title(store), steps=steps)],
        confidence=Confidence.low,
        degraded=why,
    )


__all__ = [
    "AUTHOR_BUDGET",
    "with_subject",
    "AUTHOR_TOOLS",
    "AuthoredDocument",
    "AuthoredOmission",
    "AuthoredScenario",
    "AuthoredStep",
    "write_document",
]
