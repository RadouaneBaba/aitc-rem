"""One author, the whole session in view.

This replaces `name.py`, `assertions.py` and `compose.py`, which between them
wrote every sentence of the test case without any one of them ever seeing the
test case. Naming was shown a single segment and asked for a sentence, so it
produced one sentence per segment -- a transcript. The assert stage was shown a
single step and asked what could be checked there, so it asserted wherever the
evidence happened to be dense rather than where the test had a verdict.
Composition saw the whole flow and was forbidden from touching assertions, so
the one stage that could tell what the test was ABOUT could not act on it.

The result, on a real recording, was six unrelated When/Then beats with no
`Given` and no closing `Then`: a document written by three people who never
met. Nothing here is a better prompt for that architecture. It is one call that
gets to answer the question none of them was asked -- *what is this test?*

**What the drafter may and may not decide.** It sets step boundaries, step
text, roles, keywords, scenario splits, names, tags, what to omit, and the
SENTENCE of every expected result. It never sets a `toolCallId`, a literal or a
hash: `bind.py` does that from retrievals it makes itself, so a fabricated
citation is not a thing the drafter is able to express. SS3.2's guarantee is
strictly stronger here than it was under retrieve-first, because the model is
no longer trusted to report which retrieval it used.

**Why the expected results are proposals.** The drafter writes the sentence it
believes the test should check, without first proving it can. `bind.py` then
proves each one or deletes it. That ordering is what lets the document have a
shape: an author that may only claim what it has already retrieved writes about
whatever was easy to retrieve, which is exactly how the old assert stage came
to write "the hampers category page is loaded" -- an assertion that the browser
works.

**Retrieval is discretionary and zero is a valid answer.** The index says what
changed on every event; where that is enough, writing from it is correct and
costs nothing. Where it says `(re-render; nothing named)` on the step that
matters, the drafter should go and look. That variance is the point: a
mandatory call would put a constant under every reading of SS3.3's effort
metric, which is precisely what the per-step library search did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Confidence,
    OmissionReason,
    PipelineStage,
    SegmentRole,
    StepInvestigation,
)
from server.pipeline.digest import SessionDigest, build_digest
from server.pipeline.investigate import investigate
from server.pipeline.narrative import keeps_parameters, would_collapse

#: Larger than a per-step budget was, and spent once rather than per step. The
#: old pipeline gave every segment eight retrievals it mostly did not need; the
#: whole document gets twelve, and a legible recording should use none of them.
DRAFT_BUDGET = 12

#: Keywords the drafter may put on a step. `Then` is deliberately absent: an
#: expected result is not a step, it is an `expect` hanging off one, and
#: letting the model write `Then` as a step is how a scenario ends up asserting
#: before it has acted. The renderer turns every `expect` into a `Then`.
STEP_KEYWORDS = ("Given", "When")

_VOICE_RULE = {
    True: 'Present tense, first person, starting with "I".',
    False: 'Present tense, third person, starting with "{voice}".',
}


SYSTEM_PROMPT = """\
You are writing ONE manual QA test document from a recording of a tester using
a web application. You can see the whole session at once. Nobody else will see
it -- every other stage works on your output -- so the shape of this test is
yours to decide and yours alone.

Answer with ONLY this JSON:

{{
  "title": "Role assignment",
  "description": "A member cannot be granted a role higher than the one held by the person granting it.",
  "tags": ["permissions"],
  "scenarios": [
    {{
      "name": "A member cannot be promoted above the rank of whoever is promoting them",
      "steps": [
        {{"keyword": "Given", "role": "setup",
          "text": "{voice} opens the team settings for \\"Northern Region\\"",
          "eventIds": ["evt_001", "evt_002", "evt_003"]}},
        {{"keyword": "When", "role": "test_step",
          "text": "{voice} promotes a member through each rank up to Manager",
          "eventIds": ["evt_004", "evt_005", "evt_006", "evt_007"],
          "expect": [{{"text": "the member is shown as a Manager", "eventId": "evt_007"}}]}},
        {{"keyword": "When", "role": "test_step",
          "text": "{voice} tries to promote the member to Administrator",
          "eventIds": ["evt_008"],
          "expect": [{{"text": "the change is refused with \\"You cannot assign a role above your own\\"",
                       "eventId": "evt_008"}}]}}
      ]
    }}
  ],
  "omitted": [
    {{"eventIds": ["evt_009", "evt_010"], "reason": "exploratory",
      "summary": "opened the audit log and closed it again"}}
  ],
  "uncertainties": ["could not tell whether the refusal came from the server or from the form"]
}}

Those are worked examples of the SHAPE, not of the subject. Nothing above is
about the session you are reading. Take the format, the granularity and the
register from it; take every noun from the index.

## The shape of a test

* "title" is the CAPABILITY under test, a short noun phrase -- "Role
  assignment", "Password reset", "Invoice export". It names the feature file
  and groups every test about that area, so two recordings of the same area get
  the same title. It is NOT a description of this run.

* "name" is what THIS scenario proves, as a sentence that could be read on its
  own in a list: "A member cannot be promoted above the rank of whoever is
  promoting them". It must not repeat the title.

* A scenario is ONE behaviour with ONE verdict. If the session covers several
  unrelated behaviours, write several scenarios. Six actions each with their
  own unrelated outcome is not a test case; it is six test cases, and shipping
  them as one is the single worst thing you can do here.

* Keep a scenario to at most FOUR When/Then blocks. A fifth is the signal that
  you are writing two test cases under one heading; split it. This is checked
  mechanically and a run that exceeds it is rejected.

* Where the index says THE TESTER DECLARED A NEW TEST CASE HERE, a scenario
  begins at that event. That is not a hint -- the tester pressed a button to
  say so while they were there and you were not. The step that starts there
  must not begin before it either: an event on the far side of that line
  belongs to the previous scenario's last step, never to the same step.

* THE LAST STEP OF EVERY SCENARIO MUST HAVE AN "expect". A scenario that ends
  on an action has no verdict -- nothing to pass or fail -- and is not a test.
  If the session genuinely ends mid-action, end the scenario earlier, at the
  last point where something was actually established.

## Steps

* A step is ONE INTENT, and one intent is very often many events. Five
  consecutive clicks on the same stepper control are one step -- "{voice}
  raises the limit to its maximum" -- not five. Transcribing them one event at
  a time is the failure this whole stage exists to prevent.

* Describe intent, not mechanics. Never write clicks, taps, presses, types
  into, selects from the dropdown, or scrolls to -- those describe a mouse.
  {voice_rule}

* Use the application's own words, taken from the names in the index -- but
  those names come from the accessibility tree, and one is often several pieces
  of interface glued together: a label, a badge count, a status. Write what a
  PERSON would call the thing.
      GOOD  {voice} opens the notifications panel
      BAD   {voice} opens the "Notifications 4 unread 4"
  If the index says an element was unnamed, say what it DID rather than naming
  it. Never quote a role: "generic", "listitem", "button" are what the recorder
  saw when it could not read a label, not what the tester clicked.
      GOOD  {voice} confirms the choice
      BAD   {voice} selects the "generic" option

* Quote the values that MATTER, in double quotes, exactly as written. Redaction
  placeholders like <<user_email_1>> are values and are quoted the same way.
  Quote at most the one or two that identify THIS case:
      GOOD  {voice} submits the request with a limit of "500"
      BAD   {voice} enters a reference, sets the limit, ticks the box
            and submits
      BAD   submits the request with a limit of "500"   (no subject)

* ONE sentence, one intent. If it needs more than one "and", or a
  comma-separated list of actions, it is describing a segment rather than
  naming a goal.

* If a request in a step was REJECTED, do not describe the action as having
  succeeded. The tester tried; the application refused; that refusal is very
  often what the test is about.
      GOOD  {voice} tries to place an order totalling "900"
      BAD   {voice} places an order totalling "900"   (the server returned 409)

## Keywords

You choose these, with the whole flow in front of you.

* "Given" is the world BEFORE the test begins -- signing in, navigating to the
  page, getting to the state under test. It belongs to the opening block and
  nowhere else. Never write a "Given" after anything has been checked.
* "When" is everything the test actually does.
* Never write "Then" as a step keyword. An expected result is an "expect" on
  the step that produced it, and it renders as "Then".
* A scenario normally opens with one or two "Given" steps. A scenario with no
  "Given" at all is usually a scenario that forgot to say where it started.

## Expected results

An "expect" is what a person executing this test should SEE, in plain prose,
and the "eventId" is where you believe it became true.

* Write what MATTERS, not what is easiest to point at. The test's verdict is
  the outcome the tester was looking for -- read the objective at the top of
  the index, and the tester's own annotations and narration if there are any.

* NEVER assert that navigation worked. "the category page is loaded", "the
  page opens", "the form is displayed" -- these check that the browser
  functions, not that the application does. A "Given" step almost never
  deserves an "expect" at all.

* Most steps have no "expect". Two or three across a whole scenario is normal.
  Manufacturing one per step is how a test case becomes a transcript with
  keywords on it.

* Do not hedge and do not pre-verify. Write the sentence you believe the test
  should check. Every one of these is checked afterwards against what was
  actually retrieved from the recording, and any that cannot be proved is
  DELETED rather than softened. A confident claim that gets deleted costs
  nothing; a vague claim that survives is worse than no claim.

* Say what was observed, not what it implies. "the member is shown as a
  Manager" is checkable. "the promotion works correctly" is not.

* **Write what the recording SHOWS, including when it shows a failure.** If the
  thing the tester attempted did not succeed, the expected result is what
  actually happened -- "an internal server error is shown" -- never what should
  have happened. A recorded session that ended in an error is still a test
  case: it is the test case for that error.
      GOOD  the export fails with an internal server error
      BAD   a file containing the order details is downloaded
            (the request returned 500 and nothing was downloaded)
  Writing the second costs the scenario its only verdict, because it will be
  checked against the recording and deleted.

## Accounting for the session

Every event id in the index must appear EXACTLY ONCE, either in a step's
"eventIds" or in an "omitted" entry. This is checked mechanically and a run
that drops an event is rejected.

* "omitted" is for real work that is not part of the test: "exploratory" for a
  tester looking around -- opening the wrong page, reading a screen and
  leaving -- and "abandoned" for something started and given up on.
* Be sparing. A step you merely find uninteresting is not exploratory. If it
  advances the objective at all, it belongs in the test as "setup" or
  "test_step".

## Looking things up

The index tells you what each action changed. Where that is enough, write from
it -- **making no tool calls at all is a perfectly good outcome** and costs the
run nothing.

Go and look when it is not enough, and especially when:
* the step that decides the verdict says "(re-render; nothing named)"
* you cannot tell what an action accomplished
* you are about to write an "expect" and are unsure of the wording on the page

`get_diff` and `get_snapshot` answer most of it. `find_text` tells you where a
string really appears. `get_narration` and `get_events` give you the tester's
own words. Spend calls where the session is unclear and nowhere else.

Put anything you could not resolve in "uncertainties". Saying "I could not tell
whether the price changed because of the upgrade or the quantity" is more
useful than guessing, and a human sees it.
"""


USER_PROMPT = """\
{digest}

Write the test document for this session.
"""


# --------------------------------------------------------------------------
# result
# --------------------------------------------------------------------------


@dataclass
class DraftedExpectation:
    """A claim the drafter believes the test should make. Not yet evidence.

    It carries no `toolCallId` and no literal, because the drafter has no way
    to supply one that could be trusted. `bind.py` turns this into an
    `Assertion` or deletes it.
    """

    text: str
    event_id: str


@dataclass
class DraftedStep:
    step_id: str
    keyword: str
    role: SegmentRole
    text: str
    event_ids: list[str]
    expects: list[DraftedExpectation] = field(default_factory=list)


@dataclass
class DraftedScenario:
    name: str
    steps: list[DraftedStep] = field(default_factory=list)


@dataclass
class DraftedOmission:
    event_ids: list[str]
    reason: OmissionReason
    summary: str


@dataclass
class DraftResult:
    """The whole document, before anything has been proved."""

    title: str
    description: str
    tags: list[str]
    scenarios: list[DraftedScenario]
    omitted: list[DraftedOmission] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    #: Every model turn this stage spent, drafting and repairs alike. The trace
    #: is the one list the metrics read, so a stage that does not add itself
    #: here is a stage that costs quota invisibly.
    model_calls: list = field(default_factory=list)
    #: One record per repair pass over a step. Separate from `investigation`
    #: because SS3.4's effort column is per STEP, and a step that took two
    #: passes really did cost the run two passes -- under-reporting it would
    #: hide exactly the step the correlation exists to find.
    repairs: list[StepInvestigation] = field(default_factory=list)
    confidence: Confidence = Confidence.medium
    #: Set when the model failed and the deterministic fallback wrote this. A
    #: degraded draft still produces a readable file; it just has nothing to say
    #: about what the session MEANT.
    degraded: str = ""
    digest: SessionDigest | None = None

    @property
    def steps(self) -> list[DraftedStep]:
        return [step for scenario in self.scenarios for step in scenario.steps]

    def to_artifact(self) -> dict[str, Any]:
        """What lands in `draft.json`.

        SS9.1: every stage writes its intermediate output so a human can open
        it and see which stage lied. With one drafting call that matters more,
        not less -- this file IS the model's contribution to the run.
        """
        return {
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "degraded": self.degraded,
            "confidence": self.confidence.value,
            "uncertainties": list(self.uncertainties),
            "digestTokens": self.digest.approx_tokens if self.digest else 0,
            "scenarios": [
                {
                    "name": scenario.name,
                    "steps": [
                        {
                            "id": step.step_id,
                            "keyword": step.keyword,
                            "role": step.role.value,
                            "text": step.text,
                            "eventIds": list(step.event_ids),
                            "expect": [
                                {"text": e.text, "eventId": e.event_id} for e in step.expects
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
# the stage
# --------------------------------------------------------------------------


def draft_document(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    model_name: str,
    budget: int = DRAFT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> DraftResult:
    """Write the whole test document in one investigation."""
    config = config or ProjectConfig()
    digest = build_digest(store)

    result = investigate(
        runner,
        model,
        system_prompt=system_prompt(config),
        user_prompt=USER_PROMPT.format(digest=digest.text),
        model_name=model_name,
        stage=PipelineStage.decompose,
        label="draft",
        budget=budget if tools_enabled else 0,
        tools_enabled=tools_enabled,
        temperature=temperature,
    )

    drafted = _parse(result.answer, store, config)
    drafted.digest = digest
    drafted.uncertainties = list(result.uncertainties)
    drafted.investigation = result.record(
        investigation_id="inv_draft",
        stage=PipelineStage.decompose,
        budget=budget,
    )
    drafted.model_calls = list(result.model_calls)
    return drafted


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

    Keyed on the EVENT now rather than on the segment, because the drafter
    chooses step boundaries and a segment is no longer a step.
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


def apply_intent_notes(store: EvidenceStore, drafted: DraftResult) -> set[str]:
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

    Returns the ids of the steps whose wording is now the tester's, which
    `repair.py` treats as untouchable.
    """
    notes = intent_notes(store)
    if not notes:
        return set()

    dictated: set[str] = set()
    for step in drafted.steps:
        if not step.event_ids:
            continue
        note = notes.get(step.event_ids[0])
        if note:
            step.text = note
            dictated.add(step.step_id)
    return dictated


def system_prompt(config: ProjectConfig) -> str:
    """The instructions, with every worked example in the project's voice.

    Rendering the examples matters more than the rules do. The naming prompt
    said twice to open with the subject and showed examples written without
    one; the model copied the examples and produced "submits an order totalling
    \"615\"" with nobody submitting anything.
    """
    rule = _VOICE_RULE[config.first_person].format(voice=config.voice)
    voice = "I" if config.first_person else config.voice
    return SYSTEM_PROMPT.format(voice_rule=rule, voice=voice)


# --------------------------------------------------------------------------
# repair (SS9.9)
# --------------------------------------------------------------------------


REWRITE_PROMPT = """\
You are rewriting ONE step of a QA test case that a reviewer objected to.

The step: {text}
What is wrong with it: {finding}

{context}

Answer with ONLY: {{"text": "the rewritten sentence", "reason": "what you changed"}}

Keep it about the same actions -- this step covers exactly the same events and
you are not being asked to describe something else. {voice_rule}

* ONE sentence, one intent, and it must still read as a test step.
* NEVER describe the mechanism. "clicks", "presses", "types into", "selects
  from" are all worse than whatever you were asked to fix, because they
  describe a mouse instead of a goal. A rewrite that adds one has failed.
* Keep every quoted value and every <<placeholder>> the original carried: those
  tell whoever runs the test what to supply.
* Do not hedge by adding words like "attempt to" on top of the original verb.
  If the point is that the outcome is unproven, name the ACTION instead of the
  outcome -- "submits the payment details", not "attempts to save the payment
  method".
"""


REEXPECT_PROMPT = """\
You are proposing a better expected result for ONE step of a QA test case.

The step: {text}
What was wrong with the previous expected result: {finding}

{context}

Answer with ONLY:
{{"expect": [{{"text": "what a person executing this test should see",
             "eventId": "evt_012"}}],
  "reason": "why this one"}}

Write what MATTERS -- the outcome this step exists to produce -- not whatever
is easiest to point at. Never assert that navigation worked. An empty "expect"
list is a valid answer: a step with nothing worth checking is better with no
expected result than with a pointless one.

Whatever you write is checked against the recording afterwards and DELETED if
it cannot be proved, so state it plainly rather than hedging.
"""


def rewrite_steps(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    *,
    findings: dict[str, str],
    model_name: str,
    budget: int,
    tools_enabled: bool,
    temperature: float,
    config: ProjectConfig,
    attempt: int,
) -> set[str]:
    """Rewrite the sentence of each flagged step, in place.

    **Never touches `eventIds` or `step_id`.** That single constraint is what
    keeps `event_coverage` and the scenario grouping stable across attempts,
    and it is why this walks the drafted steps rather than re-running the
    drafting stage with a filter -- the latter would re-decide boundaries and
    quietly change the step count mid-run, which SS3.6 promises does not
    happen.
    """
    changed: set[str] = set()
    by_id = {step.step_id: step for step in drafted.steps}
    texts = [step.text for step in drafted.steps]
    order = {step.step_id: i for i, step in enumerate(drafted.steps)}

    for step_id, finding in findings.items():
        step = by_id.get(step_id)
        if step is None:
            continue

        result = investigate(
            runner,
            model,
            system_prompt="You rewrite one step of a QA test case, precisely and briefly.",
            user_prompt=REWRITE_PROMPT.format(
                text=step.text,
                finding=finding,
                context=_step_context(store, step),
                voice_rule=_VOICE_RULE[config.first_person].format(voice=config.voice),
            ),
            model_name=model_name,
            stage=PipelineStage.name,
            label=f"rewrite_{step_id}_{attempt}",
            budget=budget,
            tools_enabled=tools_enabled,
            temperature=temperature,
            step_id=step_id,
        )

        drafted.model_calls.extend(result.model_calls)
        drafted.repairs.append(
            result.record(
                investigation_id=f"inv_rewrite_{step_id}_{attempt}",
                stage=PipelineStage.name,
                budget=budget,
                step_id=step_id,
            )
        )
        text = with_subject(_clean(result.answer.get("text")), config)
        if not text or text == step.text:
            continue

        # A repair prompted with "this name is too vague" can come back with a
        # sentence identical to its neighbour, and `merge_repeats` would then
        # fold the two and DELETE a step -- changing the step count mid-run and
        # moving Yield's denominator, which is worse than the finding, because
        # the metric would improve by losing a step.
        if would_collapse(texts, order[step_id], text):
            continue

        # A rewrite that drops a redaction placeholder costs the reader the one
        # thing telling them what to supply before running the test (SS7.2).
        # The prompt asks for them to be kept; a prompt that asks is not a
        # guarantee, and this is the only path that rewrites a step's text
        # after the placeholders were put in it.
        if not keeps_parameters(text, [step.text]):
            continue

        step.text = text
        texts[order[step_id]] = text
        changed.add(step_id)

    return changed


def repropose_expectations(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    *,
    findings: dict[str, str],
    model_name: str,
    budget: int,
    tools_enabled: bool,
    temperature: float,
    config: ProjectConfig,
    attempt: int,
) -> set[str]:
    """Propose fresh expected results for the flagged steps, in place.

    The claims are replaced, not edited: an expectation that failed the gate is
    not a sentence to touch up, it is a claim the run could not support. What
    comes back goes through `bind.py` exactly like a first-attempt proposal, so
    a repair cannot smuggle in an unbound claim.
    """
    changed: set[str] = set()
    by_id = {step.step_id: step for step in drafted.steps}

    for step_id, finding in findings.items():
        step = by_id.get(step_id)
        if step is None:
            continue

        result = investigate(
            runner,
            model,
            system_prompt="You propose the expected result for one step of a QA test case.",
            user_prompt=REEXPECT_PROMPT.format(
                text=step.text,
                finding=finding,
                context=_step_context(store, step),
            ),
            model_name=model_name,
            stage=PipelineStage.assert_,
            label=f"reexpect_{step_id}_{attempt}",
            budget=budget,
            tools_enabled=tools_enabled,
            temperature=temperature,
            step_id=step_id,
        )

        drafted.model_calls.extend(result.model_calls)
        drafted.repairs.append(
            result.record(
                investigation_id=f"inv_reexpect_{step_id}_{attempt}",
                stage=PipelineStage.assert_,
                budget=budget,
                step_id=step_id,
            )
        )
        known = {event.id for event in store.events_in_range(None, None)}
        proposed = _expects(result.answer.get("expect"), known)
        # An empty list is a real answer and is applied: "this step has nothing
        # worth checking" is often the correct response to "this expected
        # result is about the wrong thing".
        if proposed != step.expects:
            step.expects = proposed
            changed.add(step_id)

    return changed


def _step_context(store: EvidenceStore, step: DraftedStep) -> str:
    """The part of the index this step covers, so a repair can see it again."""
    lines = [f"Events in this step: {', '.join(step.event_ids)}"]
    if store.objective:
        lines.append(f"The tester's stated objective: {store.objective}")
    for event_id in step.event_ids[:6]:
        if not store.has_event(event_id):
            continue
        event = store.event(event_id)
        target = (event.target.name or event.target.role or "").strip()
        lines.append(f"  {event_id}  {event.type.value}" + (f' on "{target}"' if target else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# parsing the answer
# --------------------------------------------------------------------------


def _parse(answer: dict[str, Any], store: EvidenceStore, config: ProjectConfig) -> DraftResult:
    """Turn the model's JSON into a document, or fall back to one.

    Every field is defended, because a drafting stage that raises takes the
    whole run with it and there is no second author to fall back on. What a
    malformed answer costs is the MEANING of the session, not the run: the
    fallback still produces one step per event and a readable file.
    """
    known = {event.id for event in store.events_in_range(None, None)}

    scenarios = _scenarios(answer.get("scenarios"), known, config)
    if not scenarios:
        return _fallback(store, config, why="the drafting stage returned no usable scenarios")

    return DraftResult(
        title=_clean(answer.get("title")) or _fallback_title(store),
        description=_clean(answer.get("description")),
        tags=_tags(answer.get("tags"), config),
        scenarios=scenarios,
        omitted=_omissions(answer.get("omitted"), known),
        confidence=Confidence.high,
    )


def _scenarios(value: Any, known: set[str], config: ProjectConfig) -> list[DraftedScenario]:
    if not isinstance(value, list):
        return []

    out: list[DraftedScenario] = []
    counter = 0
    used: set[str] = set()

    for raw in value:
        if not isinstance(raw, dict):
            continue
        steps: list[DraftedStep] = []
        for raw_step in raw.get("steps") or []:
            if not isinstance(raw_step, dict):
                continue
            # An event claimed by two steps would be counted twice by
            # `event_coverage` and rendered twice in the trace. First claim
            # wins, deterministically, rather than the last one silently
            # overwriting the first.
            event_ids = [
                e for e in _strings(raw_step.get("eventIds")) if e in known and e not in used
            ]
            if not event_ids:
                continue
            used.update(event_ids)
            counter += 1
            keyword, role = _reconcile(raw_step.get("keyword"), raw_step.get("role"))
            steps.append(
                DraftedStep(
                    step_id=f"step_{counter:03d}",
                    keyword=keyword,
                    role=role,
                    text=with_subject(_clean(raw_step.get("text")), config),
                    event_ids=event_ids,
                    expects=_expects(raw_step.get("expect"), known),
                )
            )
        if steps:
            out.append(DraftedScenario(name=_clean(raw.get("name")), steps=steps))

    return out


def _expects(value: Any, known: set[str]) -> list[DraftedExpectation]:
    if not isinstance(value, list):
        return []
    out: list[DraftedExpectation] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        text = _clean(raw.get("text"))
        event_id = _clean(raw.get("eventId"))
        # An expectation pointing at an event that does not exist cannot be
        # bound and cannot be shown to a reviewer. Dropping it here rather than
        # letting `element_exists` reject the whole draft keeps the failure
        # proportionate to what went wrong.
        if text and event_id in known:
            out.append(DraftedExpectation(text=text, event_id=event_id))
    return out


def _omissions(value: Any, known: set[str]) -> list[DraftedOmission]:
    if not isinstance(value, list):
        return []
    out: list[DraftedOmission] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        event_ids = [e for e in _strings(raw.get("eventIds")) if e in known]
        if not event_ids:
            continue
        reason = (
            OmissionReason.abandoned
            if str(raw.get("reason", "")).lower() == "abandoned"
            else OmissionReason.exploratory
        )
        out.append(
            DraftedOmission(
                event_ids=event_ids,
                reason=reason,
                summary=_clean(raw.get("summary")) or "not part of this test",
            )
        )
    return out


def _reconcile(keyword: Any, role: Any) -> tuple[str, SegmentRole]:
    """Make the drafter's keyword and its role say the same thing.

    They are two spellings of one judgement -- where the scenario stops
    arranging and starts acting -- and the drafter is asked for both because
    each reads naturally in the prompt. Downstream only one can be
    authoritative: `narrative._base_keyword` derives from the ROLE, because
    that is what survives a reviewer deleting a step, and a `Given` the drafter
    asked for would otherwise be silently dropped when its role said
    `test_step`.

    So `Given` is taken as a statement that the step is setup. The reverse is
    deliberately NOT applied: a `When` on a step the drafter also called setup
    is resolved by position instead, because `narrative._opening_block` already
    demotes a setup step that appears after the scenario has begun acting -- and
    that rule is about where the step sits, which the drafter cannot see when
    writing one line of JSON.

    `Then` is normalised away entirely. An expected result is not a step, and a
    model that writes one as a step is describing an outcome as an action;
    rendering that verbatim produces a scenario that asserts before it acts.
    """
    text = str(keyword or "").strip().capitalize()
    resolved = _role(role)
    if text == "Given":
        return "Given", SegmentRole.setup
    if text not in STEP_KEYWORDS:
        text = "Given" if resolved == SegmentRole.setup else "When"
    return text, resolved


def _role(value: Any) -> SegmentRole:
    text = str(value or "").strip().lower()
    for role in SegmentRole:
        if role.value == text:
            return role
    return SegmentRole.test_step


def with_subject(text: str, config: ProjectConfig) -> str:
    """Make sure the step says who is doing it.

    A step is a sentence about a person. Dropped, it reads as an instruction to
    the reader and matches no step definition -- and it happens: a prompt whose
    worked examples omitted the subject produced "submits an order totalling
    \"615\"" with nobody submitting anything.

    Deterministic rather than another prompt line, because the prompt already
    says it and said it while an example showed the opposite. Left alone when
    any plausible subject is present, so "the approver releases the order" is
    not rewritten into nonsense.
    """
    if not text or config.first_person:
        return text
    lowered = text.lower()
    if lowered.startswith(config.voice.lower()) or lowered.startswith(("the ", "an ", "a ", "i ")):
        return text
    return f"{config.voice} {text[0].lower() + text[1:]}"


def _tags(value: Any, config: ProjectConfig) -> list[str]:
    proposed = [t.lstrip("@").strip().lower() for t in _strings(value)]
    merged = list(config.tags) + [t for t in proposed if t and t not in config.tags]
    return merged[:6]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _clean(value: Any) -> str:
    """Whitespace collapsed, and no trailing full stop.

    A Gherkin step is a sentence FRAGMENT -- the keyword is its subject and the
    line is the predicate -- so a full stop is never right on one, which is why
    the voice rule says so. Nothing enforced it, and steps shipped with one.
    Stripped rather than warned about: there is no case where it is correct,
    and a warning a reviewer has to act on by hand for a character is worse
    than the character.

    Only a lone trailing stop goes. An ellipsis is content -- "Validating with
    the finance system..." is what the page said, and trimming it would break
    the literal the claim is bound to.
    """
    text = " ".join(str(value or "").split()).strip()
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1].rstrip()
    return text


# --------------------------------------------------------------------------
# the fallback
# --------------------------------------------------------------------------


def _fallback(store: EvidenceStore, config: ProjectConfig, *, why: str) -> DraftResult:
    """A readable document with no judgement in it.

    Used when the model fails outright. It is deliberately a transcript -- one
    step per event, no expectations -- because a fallback that GUESSED at
    structure would be indistinguishable from a real draft in the output while
    being worth much less, and the run needs to say plainly that the drafting
    stage did not happen.
    """
    steps: list[DraftedStep] = []
    for index, event in enumerate(store.events_in_range(None, None), start=1):
        target = (event.target.name or event.target.role or "the page").strip()
        steps.append(
            DraftedStep(
                step_id=f"step_{index:03d}",
                keyword="Given" if index == 1 else "When",
                role=SegmentRole.setup if index == 1 else SegmentRole.test_step,
                text=with_subject(f'acts on "{target}"', config),
                event_ids=[event.id],
            )
        )

    return DraftResult(
        title=_fallback_title(store),
        description="",
        tags=list(config.tags),
        scenarios=[DraftedScenario(name=_fallback_title(store), steps=steps)] if steps else [],
        confidence=Confidence.low,
        degraded=why,
    )


def _fallback_title(store: EvidenceStore) -> str:
    """A title from the page, when the model did not supply one.

    Salvaged from `compose._page_title`: the first snapshot title, trimmed of
    the site name that follows a dash or a pipe on almost every commercial
    page.
    """
    for event in store.events_in_range(None, None):
        title = (event.after.title or "").strip()
        if not title:
            continue
        for separator in ("|", "-", "—", "–", ":"):
            if separator in title:
                title = title.split(separator)[0].strip()
                break
        if title:
            return title[:60]
    return "Recorded session"


__all__ = [
    "DRAFT_BUDGET",
    "apply_intent_notes",
    "intent_notes",
    "repropose_expectations",
    "rewrite_steps",
    "DraftResult",
    "DraftedExpectation",
    "DraftedOmission",
    "DraftedScenario",
    "DraftedStep",
    "draft_document",
    "system_prompt",
    "with_subject",
]
