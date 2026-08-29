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
from pathlib import Path
from typing import Any

from server.config import ProjectConfig
from server.evidence.citation import resolve_call, resolve_event_call
from server.evidence.predicate import evaluate
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.llm.gemini import fenced_block
from server.models import (
    Assertion,
    Confidence,
    Evidence,
    ExpectationSet,
    ExpectationSource,
    NodeRef,
    OmissionReason,
    PipelineStage,
    Predicate,
    PredicateForm,
    Provenance,
    ScenarioExamples,
    SegmentRole,
    StepInvestigation,
)
from server.pipeline.digest import SessionDigest, build_digest
from server.pipeline.expectations import INTENT_WINDOW_MS
from server.pipeline.featurefile import FeatureParseError, parse_feature
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


#: Where the worked examples live, one file per Gherkin style.
#:
#: A file rather than a string constant, and one per style rather than one with
#: branches, because the example IS the specification of a style. Every attempt
#: in this project's history to change output with a RULE measured at or near
#: zero uptake; every improvement came from more context. So "add a style" has
#: to mean "write a good feature file in it", which is a thing a person can do
#: in an afternoon, rather than "add a clause and hope".
STYLES_DIR = Path(__file__).resolve().parent / "styles"

#: What a project gets if it says nothing. Named for what it optimises: a
#: reader who is going to write step definitions against this.
DEFAULT_STYLE = "automation"


def worked_example(style: str = DEFAULT_STYLE) -> str:
    """The example for this style, falling back to the default rather than failing.

    A typo in `project.yaml` must not cost a run. It costs the wrong house
    style, which is visible in the output and fixable by the person who made
    the typo.
    """
    for name in (style, DEFAULT_STYLE):
        path = STYLES_DIR / f"{_slug(name)}.md"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def _slug(name: str) -> str:
    return "".join(c for c in str(name).strip().lower() if c.isalnum() or c in "-_")


SYSTEM_PROMPT = """\
You are a QA engineer. You are given a recording of somebody using a web
application, and you write the test cases for it -- as a Gherkin feature file.

{example}

## How to work

The session index below is the map. It lists every event, what was clicked,
what changed, what the network did and what the tester said. For most steps it
is enough.

The tools are the territory, for when it is not:

  get_diff(eventId)        what changed on the whole page, most informative first
  get_snapshot(eventId)    the page, before or after, as a tree of nodes
  find_text(query)         where a string really appears in the session
  get_network(eventId)     the requests and what the server answered
  get_narration(from, to)  what the tester said out loud
  see(eventId)             look at the screenshot

Look when a claim is contested and not when it is obvious. An unambiguous step
should cost you nothing; one where you cannot tell what changed deserves as
many calls as it takes.

`see` is the expensive one and the last resort. Reach for it when the TEXT DOES
NOT SETTLE THE QUESTION YOU ARE ACTUALLY ASKING -- two snapshots with the same
names in a different order, a canvas, a chart, a layout claim. Not to confirm
something you can already read.

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
session index above is not enough -- the index is a summary, and a claim
resting on it points at nothing. So before you write a verdict line, call
`get_diff` or `find_text` or `get_snapshot` or `get_network` on that event and
quote from the answer.

This is not a formality and it is not negotiable: a claim you cannot point at is
dropped and the step ends up saying you did not look. If you write four
verdicts, expect to have made at least four calls. You do not supply the id of
the retrieval -- that is looked up from what you actually called, which is why
you cannot invent one.

**Say what KIND of claim you are making.** A verdict's `predicate` is how the
checker knows what to verify, and without one it can only ask whether your
string is somewhere in the response:

  contains   (the default; omit it)  the string is there
  first_of   {{"form": "first_of", "container": {{"role": "list", "name": "..."}}}}
             your literal names the FIRST thing in that container. Use it for
             every claim about sorting, ranking or ordering -- "contains" is
             true of a sorted list and a shuffled one alike.
  count      {{"form": "count", "container": {{...}}, "role": "listitem", "n": 9}}
             the container holds exactly n of them. Use it for "the list drops
             to 9 products".
  absent     {{"form": "absent"}}
             your literal is NOT there. Use it for "the error is gone", "the
             button is no longer offered". Cite the event you looked at.

A container is named by its ROLE and its accessible NAME, as the page's own
accessibility tree names them -- never a css selector or an id.

**Only the scenario needs a verdict, not every step.** `When ... And ... Then`
is normal and often better than a verdict on every line.

**If you cannot check something, say so in `whyNot` and move on.** A refusal a
tester can act on beats a claim that proves nothing. Never pad a scenario with
a verdict that says the interface appeared. And a `whyNot` is a statement about
the recording that somebody will read and believe, so it has to be TRUE: check
the session index before you write that something was out of scope.

## What to answer with

Two fenced blocks, exactly as the worked example shows them and in that order:

1. ```gherkin  -- the whole feature file. This is the artifact; write it to be
   read.
2. ```json     -- `title`, `tags`, and `annotations`.

Nothing else, and do not omit either block.

* Every line counts: each `Given`, each `When`, each `Then`, each `And`, in
  every scenario. A file with nine step lines has nine annotations.
* `line` repeats that line's text with the keyword stripped. It is how each
  annotation is matched to its line, and it is the only thing an annotation
  repeats -- the sentence itself belongs to the file.
* `kind` is `step` or `verdict`. A `verdict` attaches to the step line above it.
* `role`, on a step, is one of setup, test_step, teardown, exploratory,
  abandoned. Signing in and navigating are usually setup.
* Every recorded event must appear in exactly one step's `events`, or in
  `omitted` with a reason naming it. Nothing the tester did may silently vanish.
* Write `Scenario:` blocks. Do not write a `Background:` -- shared setup is
  worked out from the scenarios.
* A repeated flow is one `Scenario Outline` with an `Examples` table, not two
  near-identical scenarios. Two rows minimum: one row is not a table.

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
            example=worked_example(config.style), voice=_voice_rule(config)
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
        needs_retrieval=_unretrieved_verdicts,
    )

    document = _parse(
        result.answer,
        store,
        runner,
        result.tool_call_ids,
        config,
        expectations,
        answer_text=result.answer_text,
    )
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
    answer_text: str = "",
) -> AuthoredDocument:
    # The author writes a `.feature` and annotates its lines. That is the whole
    # of the 2026-08-29 change: no model in this pipeline had ever seen a
    # feature file, so the one artifact it is judged by was assembled by a
    # script from parts none of which were Gherkin.
    document = _from_feature(
        answer, store, runner, tool_call_ids, config, expectations, answer_text
    )
    if document is not None:
        _apply_rejections(document, expectations)
        return document

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


def _from_feature(
    answer: dict[str, Any],
    store: EvidenceStore,
    runner: ToolRunner,
    tool_call_ids: list[str],
    config: ProjectConfig,
    expectations: ExpectationSet | None,
    answer_text: str = "",
) -> AuthoredDocument | None:
    """Build the document out of the `.feature` the author wrote, or return None.

    None means "this is not a feature file I can read", and the caller falls
    back to the JSON path. That fallback is a safety property rather than
    politeness: a whole-document rewrite that fails to parse must not spend the
    single revision round on a FORMAT error, which is the recorded reason
    prose-first emission was rejected the first time it was proposed.

    ## The join

    `annotations` is one entry per step line, in document order, and it is
    matched by ORDINAL. Line numbers would ask a model to count lines in a
    string it has just generated; repeating each line's text as a key would
    duplicate the prose this change exists to stop duplicating, and would break
    outright on two steps that legitimately read the same. A length mismatch is
    the signal to fall back, which is worth more than being clever.

    ## Where the prose lives

    In the file, once. A step's sentence and a verdict's sentence are the line;
    the annotation carries only what prose cannot -- the events a line accounts
    for, the literal that proves it, why there is no verdict. That is what stops
    `ir.json` and the `.feature` from drifting: there is nothing to drift.
    """
    text = answer.get("feature")
    if not isinstance(text, str) or "\n" not in text:
        # The normal path, and it is where the body actually arrives.
        #
        # The contract asks for a ```gherkin fence and a ```json fence, because
        # that is what the worked example shows and therefore what a model
        # returns. It was once "JSON and nothing else, with a `feature` key",
        # and on the checkout recording a real model reproduced the example's
        # JSON block faithfully -- including its lack of a `feature` key -- and
        # dropped the Gherkin entirely: a complete, correct set of annotations
        # with nothing to attach them to, falling through to the deterministic
        # fallback and shipping "the tester interacts with Password".
        #
        # The example outweighs the rules. The rule changed to match it.
        #
        # A `feature` key still works, and a one-line one is the OLD contract's
        # feature NAME -- recognising that is what lets every shape live in one
        # parser while the prompt changes underneath.
        text = fenced_block(answer_text, "gherkin")
    if not text or "\n" not in text:
        return None

    try:
        parsed = parse_feature(text)
    except FeatureParseError:
        return None

    raw_annotations = answer.get("annotations")
    if not isinstance(raw_annotations, list):
        return None
    aligned = _align(parsed.lines, raw_annotations)
    if aligned is None:
        return None
    annotations = aligned

    document = AuthoredDocument(
        title=_clean(answer.get("title")) or parsed.name or _fallback_title(store),
        description=_clean(answer.get("description")) or parsed.description,
        tags=_tags(answer.get("tags") or parsed.tags, config),
    )

    marker = 0
    for scenario in parsed.scenarios:
        built = AuthoredScenario(
            name=scenario.name,
            tags=_tags(scenario.tags, config, inherit=False),
            examples=scenario.examples,
        )
        for line in scenario.lines:
            raw = annotations[marker] if isinstance(annotations[marker], dict) else {}
            marker += 1
            if _clean(raw.get("kind")).lower() == "verdict":
                # A verdict is not a step. It attaches to the step above it, and
                # a scenario that opens with one has nothing to attach to --
                # which is `Then` with no `When`, and not a document.
                if not built.steps:
                    return None
                _attach_verdict(
                    built.steps[-1],
                    line.text,
                    raw,
                    store,
                    runner,
                    tool_call_ids,
                    document,
                    expectations,
                    config,
                )
                continue

            step_no = sum(len(s.steps) for s in document.scenarios) + len(built.steps) + 1
            built.steps.append(
                AuthoredStep(
                    step_id=_clean(raw.get("id")) or f"step_{step_no:03d}",
                    keyword=_keyword(line.keyword),
                    role=_role(raw.get("role")),
                    # NOT put through `with_subject`. The author wrote a line of
                    # a feature file and a reader will see exactly that line;
                    # rewriting its subject afterwards would edit prose the
                    # author composed to read a particular way, which is the
                    # assembly this change removes. The voice rule is in the
                    # prompt, where it belongs.
                    text=line.text,
                    event_ids=[e for e in _strings(raw.get("events")) if store.has_event(e)],
                    why_not=_clean(raw.get("whyNot")),
                    bug=bool(raw.get("bug")),
                    actual=_clean(raw.get("actual")),
                )
            )
        if built.steps:
            document.scenarios.append(built)

    if not document.scenarios:
        return None

    document.omitted = _omissions(answer.get("omitted"), store)
    return document


def _unretrieved_verdicts(answer: dict[str, Any]) -> str:
    """Did this answer write verdicts without going and looking at anything?

    Handed to `investigate` as `needs_retrieval`, and it is the mirror of the
    budget nudge that has always been there: a model investigating past its
    budget is told to stop, and a model that answered without investigating at
    all was told nothing at all.

    It is worth stating why this is not the prompt's job, because the prompt
    already says it plainly and at length. Measured on `keyhole` against a real
    model: six tools offered, **zero** called, two correct verdicts written
    quoting a count -- and both silently refused by the citation check, so the
    document shipped with scenarios ending on a `When`. The author had read the
    string in the session index and reasonably concluded it had evidence. The
    index is a SUMMARY, which is exactly why a claim resting on it points at
    nothing, and no amount of saying so has moved a model that can see the
    string right there in its prompt.

    So this is deterministic and it invents nothing: it counts verdicts, counts
    retrievals, and where there are some of the first and none of the second it
    says go and look. The model still chooses what to look at, still writes its
    own sentences, and still cites only what comes back.
    """
    annotations = answer.get("annotations")
    if not isinstance(annotations, list):
        return ""
    wanted = [
        a
        for a in annotations
        if isinstance(a, dict)
        and _clean(a.get("kind")).lower() == "verdict"
        and isinstance(a.get("evidence"), dict)
        and _clean(a["evidence"].get("literal"))
    ]
    if not wanted:
        # A document of pure refusals is a legitimate answer, and forcing a
        # retrieval out of one would be the mandatory-tool-call anti-pattern:
        # it lifted calls-per-step from 1.56 to 2.17 and flattened the effort
        # spread from 1.08 to 0.16, which is an agent that stopped deciding.
        return ""

    quoted = ", ".join(f"{_clean(a['evidence'].get('literal'))[:40]!r}" for a in wanted[:3])
    return (
        f"You wrote {len(wanted)} expected result(s) and made no retrievals. The session "
        f"index is a SUMMARY -- a claim resting on it points at nothing, and every one of "
        f"these will be dropped exactly as written.\n\n"
        f"Go and look now. For each verdict, call get_diff or get_snapshot or find_text or "
        f"get_network on the event it is about, and quote from what comes back: {quoted}.\n\n"
        f"If a retrieval does not support the claim, that is a real answer -- say so in "
        f"whyNot rather than quoting something weaker."
    )


def _align(lines: list[Any], annotations: list[Any]) -> list[dict[str, Any]] | None:
    """One annotation per step line, matched by the line it echoes.

    ## Why the annotation echoes its line at all

    The first version joined by ORDINAL alone, and the first real model broke it
    on its first run: it wrote a six-line document and returned five
    annotations, having forgotten the `Given` that opened its second scenario.
    The document was good and the content was right; the join threw it away.

    Counting lines in a string you have just generated is a bad thing to ask a
    model for, and the cost of getting it wrong under a positional join is not
    "one line loses its events" -- it is every subsequent line silently
    attributed to its neighbour, which is worse than a degraded run because it
    is wrong and quiet.

    So an annotation carries `line`: the text of the step line it is about,
    keyword stripped. That is a duplicate of prose, which is exactly what this
    whole change removes -- but it is a duplicate in the MODEL'S OUTPUT used as
    a join key and then discarded. The file's own text stays the single source
    of the sentence, so there is nothing to drift.

    ## How it degrades

    * exact match on the next annotation -- the normal case, and free.
    * no match there -- look ahead a little. An annotation the author omitted
      leaves its line with no events, which `event_coverage` then reports as an
      unaccounted event. A visible gap, in the mechanism built for it.
    * no `line` anywhere -- fall back to ordinal, and require the counts to
      agree exactly. That is the older contract, kept working.
    """
    if not any(isinstance(a, dict) and _clean(a.get("line")) for a in annotations):
        return list(annotations) if len(annotations) == len(lines) else None

    remaining = [a if isinstance(a, dict) else {} for a in annotations]
    out: list[dict[str, Any]] = []
    for line in lines:
        want = _norm(line.text)
        found = next(
            (i for i, a in enumerate(remaining) if _norm(_clean(a.get("line"))) == want),
            None,
        )
        if found is None:
            # A line the author did not annotate. It becomes a step with no
            # events rather than stealing the next annotation's -- and the
            # missing events surface at the gate.
            out.append({})
            continue
        # Anything skipped over was an annotation for a line that is not in the
        # file. Dropped rather than guessed at: a claim about a sentence nobody
        # wrote is not a claim about this document.
        out.append(remaining[found])
        del remaining[: found + 1]
    return out


def _norm(text: str) -> str:
    """Whitespace and trailing punctuation folded away, so an echo that differs
    only in spacing still matches the line it is about."""
    return " ".join(str(text).split()).strip(" .").casefold()


def _attach_verdict(
    step: AuthoredStep,
    text: str,
    raw: dict[str, Any],
    store: EvidenceStore,
    runner: ToolRunner,
    tool_call_ids: list[str],
    document: AuthoredDocument,
    expectations: ExpectationSet | None,
    config: ProjectConfig,
) -> None:
    """A verdict LINE, bound the same way a verdict FIELD always was.

    `_attach_claim` is reused rather than reimplemented: the citation, the
    predicate, the recording-side re-check and the refusal wording are the one
    rule this whole architecture exists to enforce, and a second implementation
    of it is a second thing that can be wrong. Only where the sentence comes
    from is different -- the file rather than an `expected` field.
    """
    del config
    _attach_claim(
        step,
        {"expected": text, "evidence": raw.get("evidence"), "whyNot": raw.get("whyNot")},
        store,
        runner,
        tool_call_ids,
        document,
        expectations,
    )
    # A refusal the author wrote about this verdict belongs on the step that
    # was supposed to carry it, and only when nothing landed.
    if not step.assertions and not step.why_not:
        step.why_not = _clean(raw.get("whyNot"))


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

    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    literal = _clean(evidence.get("literal"))
    if not literal:
        _refuse(step, document, expected, "the author quoted nothing to rest it on")
        return

    predicate = _predicate(evidence.get("predicate"))
    negative = predicate is not None and predicate.form is PredicateForm.absent

    event_id = _clean(evidence.get("eventId"))
    if not store.has_event(event_id):
        event_id = step.event_ids[-1] if step.event_ids else ""

    # Which retrieval licenses this claim, and it depends on what is claimed.
    #
    # A bare literal is licensed by any retrieval CONTAINING it -- that is the
    # rule the architecture exists to enforce, unchanged.
    #
    # A POSITIONAL or COUNTING claim is about a page, and a page is identified
    # by its event rather than by a string that may appear on several. Observed
    # on a live run: the author claimed the list held 9 items at evt_001, had
    # retrieved both events' snapshots, and `resolve_call` handed back evt_002's
    # -- the most recent retrieval containing "Showing 9 of 24 products", which
    # is the text of the CHANGE and appears in both. Counting evt_002's list
    # then said 3, and a true claim was refused for a reason that was about the
    # wrong page.
    #
    # A NEGATIVE claim cannot cite a retrieval containing its own literal at
    # all -- the whole point is that none does -- so it has always been licensed
    # this way.
    #
    # None of this loosens anything: the retrieval must still be one this run
    # made, `evaluate` still has to hold against it, and where no retrieval of
    # the event exists the literal-driven search is the fallback rather than a
    # free pass.
    by_event = negative or (predicate is not None and predicate.container is not None)
    call_id = None
    if by_event:
        call_id = resolve_event_call(runner, tool_call_ids, event_id)
    if call_id is None and not negative:
        call_id = resolve_call(runner, tool_call_ids, literal)
    if call_id is None:
        # It may still be true. It is simply not something this run went and
        # looked at, and the whole architecture exists to keep those apart.
        _refuse(
            step,
            document,
            expected,
            (
                f"this run never retrieved {event_id or 'the moment'} itself, so it "
                f"cannot say {literal[:60]!r} was missing from it"
                if negative
                else f"nothing this run retrieved contains {literal[:60]!r}"
            ),
        )
        return

    # The second, independent check: is this true of the RECORDING, and not only
    # of what the agent happened to be shown. Skipped for a negative claim, where
    # the literal is absent by construction.
    if not negative and (
        not event_id or not store.contains_at(literal, event_id, case_sensitive=True)
    ):
        elsewhere = store.events_containing(literal, case_sensitive=True)
        # Re-pointing is safe for a bare literal -- it and the retrieval are
        # unchanged, only the moment it became true. It is NOT safe under a
        # predicate: `first_of` is a claim about a position inside one stored
        # response, and moving it to a different event would carry the sentence
        # to a page whose order nobody checked.
        if len(elsewhere) == 1 and predicate is None:
            event_id = elsewhere[0]
        else:
            _refuse(
                step,
                document,
                expected,
                f"{literal[:60]!r} does not appear at {event_id or 'any event of this step'}",
            )
            return

    if predicate is not None:
        verdict = evaluate(_stored(runner, call_id), literal, predicate)
        if verdict.unresolved:
            # Neither true nor false. Passing it would put a green badge on an
            # unchecked claim; rejecting it would kill true claims whenever a
            # response shape changes. The author is told what did not resolve.
            _refuse(step, document, expected, verdict.why)
            return
        if not verdict.holds:
            _refuse(step, document, expected, verdict.why)
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
                kind=_clean(evidence.get("kind")) or "semantic_node",
                predicate=predicate,
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


def _predicate(value: Any) -> Predicate | None:
    """What the author says it is claiming, or None for plain containment.

    Unparseable is None rather than an error, and that is the conservative
    direction: a malformed predicate degrades the claim to the substring check it
    would have had anyway, where a raised error would lose a verdict over a
    field the author was not obliged to send. A predicate the author asked for
    and got wrong shows up as a refusal in `evaluate`, with a sentence saying so.
    """
    if not isinstance(value, dict):
        return None
    form = _clean(value.get("form")).lower()
    if form not in set(PredicateForm):
        return None
    container = value.get("container")
    node = None
    if isinstance(container, dict) and _clean(container.get("role")):
        node = NodeRef(
            role=_clean(container.get("role")),
            name=_clean(container.get("name")) or None,
        )
    n = value.get("n")
    return Predicate(
        form=PredicateForm(form),
        container=node,
        role=_clean(value.get("role")) or None,
        n=int(n) if isinstance(n, int | float) and not isinstance(n, bool) and n >= 0 else None,
    )


def _stored(runner: ToolRunner, call_id: str) -> Any:
    """The retrieval as it was persisted -- the FULL response, not the view.

    A tool may hand the model something smaller than what it stored (see
    `ToolSpec.view`), and a positional predicate evaluated against that view
    answers a different question than the one the author asked.
    """
    try:
        return runner.storage.load_tool_response(runner.run, call_id)
    except OSError:
        return None


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
