"""Stage 4 -- assertion proposal (SS9.5). Agentic.

A recording captures what the tester *did*. It never captures what they were
*checking*, and that gap is where a tool like this fails quietly:

    "Systems that lead with inference produce assertions that are true but
     pointless -- 'a timestamp appeared' -- because nothing tells them which of
     forty state changes is the one under test."

So the ranking matters more than any other ordering in the spec. Sources 1-3
are direct statements of intent -- the tester pointed at it, said it out loud,
or wrote it down before recording. Sources 4-5 are guesses about intent. Every
layer above inference exists to answer *which change matters*, and each is
retrieved on demand rather than pre-loaded, so a step whose outcome is obvious
costs nothing.

    1  annotated  the tester marked "this is what I'm verifying"
    2  narrated   the tester said the expected result while recording
    3  objective  the stated objective, matched to this step
    4  inferred   a new alert/status node, success vocabulary, a URL change
    5  inferred   state diff: a counter, a row count, an enabled/disabled flip

Each step gets two or three ranked candidates, never one -- the review UI
presents them as checkboxes over the step screenshot and the tester accepts or
rejects in seconds. Until that UI exists the top-ranked candidate is accepted
and the rest ride along as proposals, visible in the evidence sidecar.

Every candidate is evidence-bound (SS3.2): the literal must have come back from
a tool response received in this run, or it is not emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Assertion,
    Evidence,
    ModelCall,
    PipelineStage,
    Provenance,
    Segment,
    SegmentRole,
    StepInvestigation,
    StopReason,
)
from server.pipeline.investigate import investigate
from server.pipeline.name import NamedStep
from server.pipeline.narrative import dedupe_assertions
from server.pipeline.transcribe import supports_narrated

#: Smaller than naming's. Naming has already investigated this step once, and
#: the question here is narrower: what should a tester check, and where did the
#: string come from.
ASSERT_BUDGET = 6

#: SS9.5 -- "each step gets 2-3 ranked candidates, never one".
MAX_CANDIDATES = 3

#: The ranking that decides which candidate is accepted. A tester who pointed
#: at something outranks any inference about what they meant.
PROVENANCE_RANK = {
    Provenance.annotated: 0,
    Provenance.narrated: 1,
    Provenance.objective: 2,
    Provenance.confirmed: 3,
    Provenance.inferred: 4,
}

EVIDENCE_KINDS = {"semantic_node", "url", "network", "console", "narration", "a11y_node"}

# --------------------------------------------------------------------------
# noise (SS9.5, hard-excluded)
# --------------------------------------------------------------------------

#: A literal matching any of these is not an assertion, it is a value that will
#: differ on the next run. Enforced in code rather than asked for in the prompt:
#: an assertion about a timestamp passes every grounding check and still breaks
#: the moment somebody runs the test.
NOISE = [
    ("a timestamp", re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")),
    (
        "a relative time",
        re.compile(r"\b\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago\b", re.IGNORECASE),
    ),
    ("a date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    (
        "a uuid",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
        ),
    ),
    ("a generated identifier", re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)),
    ("a redaction placeholder", re.compile(r"<<[a-z0-9_]+>>", re.IGNORECASE)),
]

SYSTEM_PROMPT = """\
You are proposing the expected results for one step of a manual QA test case.

A recording shows what the tester DID. It never shows what they were CHECKING.
Your job is to work out which of the things that changed is the one worth
verifying, and to prove the string you quote came from the recording.

Rank your candidates by where the intent came from, best first:

  annotated  the tester marked an element as "this is what I'm verifying"
  narrated   the tester said the expected result out loud while recording
  objective  the stated objective, where it clearly speaks about this step
  inferred   you worked it out: a new alert or status message, success or
             error wording, a page moving, a counter changing, a request
             succeeding

The first three are the tester telling you what matters. The last one is you
guessing. Prefer a weaker-sounding assertion with strong provenance over a
confident-sounding one you inferred -- an inferred assertion that is true but
incidental ("a timestamp appeared") is worse than no assertion at all, because
somebody has to read it and decide it was pointless.

If the step is told to have an annotation or narration, GO AND GET IT. Use
`get_events` for the annotation and `get_narration` for the transcript. Do not
assume what it says.

NEVER propose an assertion about: a time or date, a relative time like "2
minutes ago", a uuid or generated id, or anything that would obviously differ
the next time somebody runs this test.

How to write the sentence:

* State the OUTCOME, not the mechanism that showed it. "the order requires
  manager approval" beats "the system displays an approval requirement alert",
  which describes a widget rather than a fact about the application.
* Never begin with "the system displays", "a message appears saying" or "the UI
  shows". Say what became true.
* Refer to the person executing the test as "{voice}" if you refer to them at
  all, the same as the step above. One test case, one person: steps that say
  "the tester" beside an expected result that says "the user" read as two
  documents spliced together.
      GOOD  the cart shows two items
      GOOD  the order is held for manager approval
      BAD   the system displays an approval requirement alert
      BAD   the user is redirected to the catalog page   (when the steps say "the tester")

Reply with ONLY this JSON, most important candidate first:
{
  "candidates": [
    {
      "text": "the order confirmation banner appears",
      "provenance": "annotated" | "narrated" | "objective" | "inferred",
      "literal": "Order confirmed",
      "toolCallId": "tc_0447",
      "eventId": "evt_027",
      "kind": "semantic_node",
      "why": "the tester pointed at this banner"
    }
  ]
}

Give two or three candidates when the step genuinely produced more than one
checkable outcome. Give one when only one thing mattered.

If the step produced NO observable outcome -- filling in a field, opening a
menu, scrolling -- reply with {"candidates": []}. That is the right answer and
not a failure. Most steps in a test case are like this.

Grounding, which is the part that must not go wrong:

* `literal` must be an EXACT string from a tool response you received in THIS
  conversation. Not paraphrased, not retyped from the summary above.
* Grounding requires a retrieval. Call `find_text` with the exact string you
  intend to quote, then cite the id of that call. Do this even when the string
  is already visible above: a claim is admissible only if a retrieval in this
  conversation returned it.
* `toolCallId` must be the id of the call that returned it. Every tool result
  you receive begins with its own `toolCallId` -- copy that value exactly. Do
  not invent an id and do not build one out of the tool's name.
* `text` is free prose and does NOT have to contain the literal. Write the
  sentence a tester would read; the literal is what makes it checkable.

An omitted assertion is correct. A fabricated citation is the one thing that
must never happen.

You may call at most ONE tool per turn. Look at what it returns before deciding
whether you need anything else."""


def system_prompt(config: ProjectConfig) -> str:
    """The assertion instructions, in this project's voice.

    `replace` rather than `format`: this prompt contains the literal JSON the
    model must reply with, braces and all, and doubling every one of them to
    survive `str.format` would make the example unreadable and one missed brace
    would turn a prompt edit into a crash.
    """
    return SYSTEM_PROMPT.replace("{voice}", config.voice)


@dataclass
class StepAssertions:
    """What the stage proposed for one step."""

    step_id: str
    candidates: list[Assertion] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    #: Literals the noise filter threw away, with the reason. Kept so the
    #: sidecar can show that a judgment was made rather than nothing found.
    suppressed: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> list[Assertion]:
        return [a for a in self.candidates if a.accepted]


@dataclass
class AssertionResult:
    steps: list[StepAssertions] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    #: Investigations replaced by a repair or a split-driven re-ask. SS9.10
    #: wants every one of them in the trace, and SS3.4's effort column has to
    #: count what the run actually spent on the step -- including the attempt
    #: that was rejected, which is precisely the effort a hard step provoked.
    superseded: list[StepInvestigation] = field(default_factory=list)

    @property
    def investigations(self) -> list[StepInvestigation]:
        live = [s.investigation for s in self.steps if s.investigation is not None]
        return live + list(self.superseded)

    def by_step(self) -> dict[str, list[Assertion]]:
        return {s.step_id: s.candidates for s in self.steps}

    def to_artifact(self) -> dict:
        """`assertions.json` -- the ranked proposals, before the renderer
        decides which of them a reader sees."""
        return {
            "stage": "assert",
            "steps": [
                {
                    "id": s.step_id,
                    "suppressedAsNoise": s.suppressed,
                    "candidates": [
                        {
                            "rank": a.rank,
                            "accepted": a.accepted,
                            "text": a.text,
                            "provenance": a.provenance.value,
                            "literal": a.evidence.literal,
                            "toolCallId": a.evidence.toolCallId,
                            "eventId": a.evidence.eventId,
                        }
                        for a in s.candidates
                    ],
                }
                for s in self.steps
            ],
        }


def propose_assertions(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming,
    *,
    model_name: str,
    budget: int = ASSERT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    only: set[str] | None = None,
    findings: dict[str, str] | None = None,
    previous: dict[str, list[Assertion]] | None = None,
    attempt: int = 1,
) -> AssertionResult:
    """Propose ranked expected results for every named step.

    `only` limits the pass to particular step ids. Used after composition splits
    a step: the two halves are different steps from the ones this stage was
    asked about, so their expected results have to be reconsidered rather than
    inherited. Two extra calls, and only when a split actually happened.

    `findings` and `previous` are the repair path (SS9.9): the step is asked
    again, shown what it proposed last time and why that was rejected. A step in
    `only` with no finding is a fresh proposal, not a repair -- which is what a
    split produces, and why the two are separate arguments rather than one.
    """
    # House style reaches the SENTENCE and nothing else. What is true is not a
    # preference -- the literal, the citation and the ranking are untouched by
    # this -- but the prose around it is prose, and a test case that calls the
    # same person "the tester" in its steps and "the user" in its expected
    # results reads as two documents spliced together. That really happened.
    config = config or ProjectConfig()
    findings = findings or {}
    previous = previous or {}
    result = AssertionResult()

    for named in naming.steps:
        if only is not None and named.step_id not in only:
            continue
        segment = store.segment(named.segment_id)

        # A step the recorder saw produce nothing cannot have an expected
        # result, so asking a model about it can only produce an invention --
        # and this stage otherwise costs one call per step, which on a
        # forty-step recording is the difference between a run that fits a
        # free-tier daily quota and one that does not. SS9.5 says most steps in
        # a test case have no observable outcome; this is that, in code.
        if not _could_have_an_outcome(store, named):
            result.steps.append(_nothing_to_assert(named, segment))
            continue

        proposed = _propose_one(
            store,
            runner,
            model,
            named=named,
            segment=segment,
            model_name=model_name,
            budget=budget if tools_enabled else 0,
            tools_enabled=tools_enabled,
            temperature=temperature,
            config=config,
            sink=result.model_calls,
            finding=findings.get(named.step_id),
            previous=previous.get(named.step_id),
            attempt=attempt,
        )
        result.steps.append(proposed)

    return result


def _could_have_an_outcome(store: EvidenceStore, named: NamedStep) -> bool:
    """Did anything happen here that a tester could check?

    Deliberately generous: this decides whether to spend a model call, so a
    false positive costs one call and a false negative costs an assertion. Any
    signal at all is enough.
    """
    for event_id in named.event_ids:
        event = store.event(event_id)
        diff = event.diff
        if diff.added or diff.changed or diff.urlChanged is not None:
            return True
        if any(call.status is not None for call in event.network):
            return True
        if event.console:
            return True
        if any(a.kind.value == "assertion" for a in (event.annotations or [])):
            return True

    events = [store.event(e) for e in named.event_ids]
    return bool(store.narration(events[0].timestamp, events[-1].timestamp + 2000))


def _nothing_to_assert(named: NamedStep, segment: Segment) -> StepAssertions:
    """Recorded, not skipped.

    SS3.4 reads effort per step, and a step with no record would read as zero
    effort rather than as a decision that cost nothing -- which are different
    things, and the second is the one that happened.
    """
    return StepAssertions(
        step_id=named.step_id,
        investigation=StepInvestigation(
            id=f"inv_assert_{named.step_id.split('_')[-1]}",
            stepId=named.step_id,
            segmentId=segment.id,
            stage=PipelineStage.assert_,
            initialUncertainty=[],
            toolCallIds=[],
            budgetUsed=0,
            budgetMax=0,
            stopReason=StopReason.no_investigation_needed,
            narrative=[
                "the recorder saw no change, no request and no annotation here, "
                "so there is nothing a tester could check"
            ],
        ),
    )


def _propose_one(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    named: NamedStep,
    segment: Segment,
    model_name: str,
    budget: int,
    tools_enabled: bool,
    temperature: float,
    config: ProjectConfig,
    sink: list[ModelCall],
    finding: str | None = None,
    previous: list[Assertion] | None = None,
    attempt: int = 1,
) -> StepAssertions:
    suffix = "" if attempt == 1 else f"_r{attempt}"
    enquiry = investigate(
        runner,
        model,
        system_prompt=system_prompt(config),
        user_prompt=_baseline(store, named, segment)
        + (_repair_addendum(previous or [], finding, attempt) if finding else ""),
        model_name=model_name,
        stage=PipelineStage.assert_,
        label=f"assert_{named.step_id}{suffix}",
        budget=budget,
        tools_enabled=tools_enabled,
        temperature=temperature,
        step_id=named.step_id,
        segment_id=segment.id,
    )
    sink.extend(enquiry.model_calls)
    enquiry.finish()

    candidates, suppressed = _candidates(
        enquiry.answer.get("candidates"), store, named, segment, config
    )
    for reason in suppressed:
        enquiry.narrative.append(f"suppressed as noise: {reason}")

    return StepAssertions(
        step_id=named.step_id,
        candidates=candidates,
        suppressed=suppressed,
        investigation=enquiry.record(
            investigation_id=f"inv_assert_{named.step_id.split('_')[-1]}{suffix}",
            stage=PipelineStage.assert_,
            budget=budget,
            step_id=named.step_id,
            segment_id=segment.id,
        ),
    )


REPAIR_ADDENDUM = """\

---

You have already answered for this step once and it was sent back. You are
answering again.

What you proposed (attempt {attempt}):
{proposed}

Why it was sent back:
    {finding}

Propose the expected results again. Every rule above still applies, and the
first one applies hardest: a candidate is admissible only if `literal` appears
VERBATIM in a tool response you retrieved IN THIS conversation, and `toolCallId`
is the id that response arrived with. If the problem was a citation that did not
resolve, retrieve the evidence again now and cite what comes back -- do not
adjust the id you used last time until you have seen it.

Proposing NOTHING is a valid answer and is better than a claim you cannot cite.
An empty candidate list is a complete response."""


def _repair_addendum(previous: list[Assertion], finding: str, attempt: int) -> str:
    """Show the model its own rejected answer, not just the complaint.

    Two reasons, and the second is mechanical. Showing a model what it wrote is
    the thing most likely to change what it writes next. And cassette keys are a
    hash of the request (`server/llm/cassette.py`), so a repair prompt built
    from the finding alone would be byte-identical on attempt 3 to attempt 2 --
    a cache hit replaying the same rejected answer, burning the budget having
    changed nothing.
    """
    proposed = (
        "\n".join(
            f'    "{a.text}"  (quoting {a.evidence.literal!r} from {a.evidence.toolCallId})'
            for a in previous
        )
        or "    (nothing)"
    )
    return REPAIR_ADDENDUM.format(attempt=attempt - 1, proposed=proposed, finding=finding)


# --------------------------------------------------------------------------
# answer handling
# --------------------------------------------------------------------------


def _candidates(
    value,
    store: EvidenceStore,
    named: NamedStep,
    segment: Segment,
    config: ProjectConfig,
) -> tuple[list[Assertion], list[str]]:
    """Rank, filter and number the proposals.

    Nothing here checks whether a citation is REAL -- that is the validator's
    job (SS9.7), and the ablation measures how often each configuration gets it
    wrong, so a fabricated citation has to survive this far to be counted.
    What is checked is whether the claim is worth making at all.
    """
    if not isinstance(value, list):
        return [], []

    kept: list[tuple[int, dict]] = []
    suppressed: list[str] = []

    for order, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        literal = str(raw.get("literal") or "")
        tool_call_id = str(raw.get("toolCallId") or "")
        if not (text and literal and tool_call_id):
            continue

        noise = _noise_in(literal)
        if noise:
            suppressed.append(f"{literal!r} is {noise}")
            continue

        kept.append((order, raw))

    supported = _supported_provenance(store, named, segment, config.narration_min_confidence)
    provenance_of = [
        (_provenance(raw.get("provenance"), supported), order, raw) for order, raw in kept
    ]
    provenance_of.sort(key=lambda item: (PROVENANCE_RANK[item[0]], item[1]))

    out: list[Assertion] = []
    for rank, (provenance, _order, raw) in enumerate(provenance_of[:MAX_CANDIDATES], start=1):
        kind = str(raw.get("kind") or "semantic_node")
        assertion = Assertion(
            id=f"asrt_{named.step_id.split('_')[-1]}_{rank}",
            text=str(raw["text"]).strip(),
            provenance=provenance,
            evidence=Evidence(
                literal=str(raw["literal"]),
                toolCallId=str(raw["toolCallId"]),
                eventId=str(raw.get("eventId") or "") or segment.eventIds[-1],
                kind=kind if kind in EVIDENCE_KINDS else "semantic_node",
            ),
            # Acceptance is the human's, and the review UI (SS13) is where they
            # give it. Until then the best-ranked candidate carries the step and
            # the rest ride along as proposals -- visible in the sidecar, absent
            # from the feature file, so nobody is handed three expected results
            # nobody chose.
            #
            # A GUESS about a precondition is not one of them. Checking that
            # signing in reached the catalog page, in a test about the EUR500
            # approval rule, is true and beside the point -- and this prompt
            # says two paragraphs up that such an assertion is worse than none,
            # because somebody has to read it and decide it was pointless. If
            # the tester marked it or said it, that is different: they are
            # telling us the precondition IS the point, and it stands.
            accepted=rank == 1 and not _incidental(named, provenance),
            rank=rank,
        )
        out.append(assertion)

    # Also at the source: a model asked for up to three candidates can propose
    # the same sentence twice, and two identical `Then` lines are a defect
    # wherever they came from. `_absorb` catches the merge case; this catches
    # this one.
    return dedupe_assertions(out), suppressed


def _incidental(named: NamedStep, provenance: Provenance) -> bool:
    """An inferred claim about a step that is only there to reach the state.

    Still proposed, still grounded, still counted -- it appears in the sidecar
    and the reviewer can accept it. It just does not get to put a `Then` under a
    `Given` on nobody's authority.
    """
    return named.role == SegmentRole.setup and provenance == Provenance.inferred


def _noise_in(literal: str) -> str:
    """SS9.5's hard exclusions. Returns why, or an empty string."""
    for reason, pattern in NOISE:
        if pattern.search(literal):
            return reason
    return ""


def _supported_provenance(
    store: EvidenceStore,
    named: NamedStep,
    segment: Segment,
    min_confidence: float = 0.5,
) -> set[Provenance]:
    """Which provenance claims this step could honestly make.

    The ladder decides which candidate is accepted, so a claim about where a
    claim came from is load-bearing -- and it was the one thing in the system
    nobody checked. `annotated` outranks everything, and asserting it costs a
    model nothing but the word.

    Verified deterministically here rather than asked for in the prompt, the
    same way noise suppression is code: a rule the model is merely told about
    is a rule that holds most of the time.
    """
    ok = {Provenance.inferred, Provenance.confirmed}

    events = [store.event(e) for e in named.event_ids]
    if any(
        a.kind.value == "assertion" for e in events for a in (e.annotations or [])
    ) or store.annotations(events[0].timestamp, events[-1].timestamp + 2000, kind="assertion"):
        ok.add(Provenance.annotated)

    # Narration is the only LOSSY evidence source here: everything else is read
    # exactly, and a transcript is a reconstruction. A sentence the transcriber
    # was unsure of would otherwise outrank an honest inference, and the result
    # -- a mis-heard number that passes both grounding validators and is still
    # false -- is the one failure this ladder exists to prevent. Segments with
    # no confidence at all came from a human and are trusted.
    spoken = store.narration(events[0].timestamp, events[-1].timestamp + 2000)
    if any(supports_narrated(s, min_confidence) for s in spoken):
        ok.add(Provenance.narrated)

    if store.objective:
        ok.add(Provenance.objective)

    del segment
    return ok


def _provenance(value, supported: set[Provenance] | None = None) -> Provenance:
    """`inferred` is the honest default. Claiming a tester pointed at something
    when the field was unreadable would launder a guess into a statement of
    intent, which is the one direction this ranking must not slip.

    `supported` closes the same door from the other side: a claim of `annotated`
    on a step with no annotation is a guess wearing the top rank, so it is
    demoted to what it actually is.
    """
    try:
        claimed = Provenance(str(value).strip().lower())
    except ValueError:
        return Provenance.inferred
    if supported is not None and claimed not in supported:
        return Provenance.inferred
    return claimed


# --------------------------------------------------------------------------
# prompt construction
# --------------------------------------------------------------------------


def _baseline(store: EvidenceStore, named: NamedStep, segment: Segment) -> str:
    events = [store.event(e) for e in named.event_ids]

    lines: list[str] = []
    objective = store.objective
    lines.append(f"Stated objective: {objective}" if objective else "Stated objective: none given.")
    lines.append("")
    lines.append(f"The step: {named.text}")
    lines.append(f"Events: {', '.join(named.event_ids)}")
    lines.append("")

    # Named, not pre-loaded. SS6.6: the agent retrieves narration when a step
    # is ambiguous and pays nothing when it is not -- but it can only choose to
    # retrieve something it knows exists.
    lines.append("Signals available for this step:")
    lines.extend(_signals(store, named, events))
    lines.append("")

    lines.append("What changed:")
    changes = _changes(events)
    lines.append(changes or "  (nothing the recorder could see)")
    lines.append("")

    calls = [c for e in events for c in e.network]
    lines.append("Network:")
    if calls:
        for call in calls[:8]:
            status = call.status if call.status is not None else "no response"
            lines.append(f"  {call.method} {call.url} -> {status}")
    else:
        lines.append("  (no requests)")

    errors = [c for e in events for c in e.console]
    if errors:
        lines.append("")
        lines.append("Console:")
        for entry in errors[:5]:
            lines.append(f"  [{entry.level.value}] {entry.text[:200]}")

    return "\n".join(lines)


def _signals(store: EvidenceStore, named: NamedStep, events) -> list[str]:
    out: list[str] = []

    marked = [a for e in events for a in (e.annotations or []) if a.kind.value == "assertion"]
    if marked:
        out.append(
            f"  ANNOTATED: the tester marked {len(marked)} element(s) here as "
            f"'this is what I'm verifying'. Retrieve them with get_events and use them: "
            f"this outranks anything you could infer."
        )

    spoken = store.narration(events[0].timestamp, events[-1].timestamp + 2000)
    if spoken:
        out.append(
            f"  NARRATED: the tester spoke {len(spoken)} time(s) during this step. "
            f"Retrieve it with get_narration -- they may have stated the expected "
            f"result outright."
        )

    if store.objective:
        out.append("  OBJECTIVE: a stated objective exists (above). Does it speak about this step?")

    if not out:
        out.append("  none -- anything you propose here is inferred, so be strict about it")
    return out


def _changes(events) -> str:
    out: list[str] = []
    for event in events:
        for node in event.diff.added[:6]:
            out.append(f'  + {node.role} "{node.name}"')
        for node in event.diff.removed[:4]:
            out.append(f'  - {node.role} "{node.name}"')
        for change in event.diff.changed[:4]:
            out.append(
                f'  ~ {change.after.role} "{change.after.name}" '
                f"({', '.join(change.fields)}) {change.before.value!r} -> {change.after.value!r}"
            )
        if event.diff.urlChanged:
            out.append(f"  > url {event.diff.urlChanged.to}")
    return "\n".join(out[:20])


__all__ = [
    "ASSERT_BUDGET",
    "MAX_CANDIDATES",
    "AssertionResult",
    "StepAssertions",
    "propose_assertions",
]
