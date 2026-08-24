"""Stage 3 -- naming (SS9.4). Agentic.

For each segment, one sentence describing tester intent. The baseline evidence
is handed over up front; then the agent investigates.

    "A step with an obvious outcome costs zero calls; an ambiguous one costs
     several."

That variance is not inefficiency. It is the observable signature of adaptive
behaviour (SS3.3), and the trace records it per step so the effort/difficulty
correlation of SS3.4 can be plotted from production data.

What this stage does NOT decide is the Gherkin keyword. It sees one segment, and
Given/When/Then is a property of the whole scenario -- asked anyway, a model
answers `When` every time. It proposes a role instead, composition (SS9.3)
overrules it with the whole flow in view, and `narrative.py` derives the keyword
from that.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Assertion,
    Confidence,
    ModelCall,
    PipelineStage,
    Segment,
    SegmentRole,
    StepInvestigation,
    StopReason,
)
from server.pipeline.investigate import DEFAULT_BUDGET, investigate
from server.pipeline.narrative import would_collapse

#: An outcome lands after the action that caused it, so a window that stops at
#: the last event misses the annotation describing what the tester saw.
SETTLE_TAIL_MS = 2000

#: How the step sentence is framed, per the project's configured voice.
_VOICE_RULE = {
    True: 'Present tense, first person, starting with "I". No trailing full stop.',
    False: 'Present tense, third person, starting with "{voice}". No trailing full stop.',
}

SYSTEM_PROMPT = """\
You are naming one step of a manual QA test case, from a browser recording.

Write ONE sentence describing what the tester was trying to DO. Rules:

* Describe intent, not mechanics. "Submits the order" beats "clicks the blue
  button". Never write clicks, taps, presses, types into, selects from the
  dropdown, or scrolls to -- those describe a mouse, not a test.
* {voice_rule}
* Use the application's own vocabulary, taken from the accessible names you are
  shown.
* Quote the values that MATTER, exactly as given, in double quotes: the tester
  enters "PO-4471" as the purchase order number. Redaction placeholders such as
  <<password>> are values too and are quoted the same way. "Enters the
  password" tells the person running this test nothing; 'signs in as
  "<<user_email_1>>" with "<<password>>"' tells them what to supply.
* ONE sentence, one intent. A segment often holds several actions; describe
  what they add up to, not each one in turn. If your sentence needs more than
  one "and", or a comma-separated list, it is describing too much.
* NEVER gloss what a value is for. "with \"PO-4471\" as the purchase order
  number, \"615\" as the order total, and manager approval" is a form being
  filled in, read out field by field. It is not an intent, and no step
  definition will ever match it.
  Name the goal and quote at most the one or two values that identify THIS
  case. Every example below still opens with the subject, because every step
  does:
      GOOD  {voice} submits the order with manager approval
      GOOD  {voice} submits an order totalling "615" with manager approval
      BAD   {voice} enters a purchase order, sets the total, ticks approval and
            submits
      BAD   {voice} submits the order with "PO-4471" as the purchase order
            number and "615" as the order total
      BAD   submits the order with manager approval   (no subject at all)
  Sign-in is the exception that proves the rule: two placeholders, no gloss --
  'signs in as "<<user_email_1>>" with "<<password>>"'.
* You are shown the step before this one. Do not restate it. If this step
  genuinely repeats an earlier action, say so -- "places the order again".
* Never state application state the evidence does not show.
* If a request in this step was REJECTED, do not describe the action as
  completed. The tester tried; the application refused, and that refusal is
  very often the thing the test exists to check.
      GOOD  {voice} submits an order over the approval threshold
      GOOD  {voice} tries to place an order totalling "900"
      BAD   {voice} places an order totalling "900"   (the server returned 409)
* SEARCH BEFORE YOU INVENT. Call `search_step_library` with the sentence you
  were about to write. If a match comes back with `reuse: true`, copy its
  `text` EXACTLY, character for character, and put its `id` in `libraryRef`.
  That is what stops one action being called three things across a suite, and
  it is the main reason a generated suite becomes unmaintainable.
  A match with `reuse: false` is similar but says something different -- read
  it, then write your own sentence and leave `libraryRef` out.

You have tools that query the recording. Use them when, and only when, you
cannot tell what happened from the evidence you already have. A step with an
obvious outcome should cost zero tool calls.

Call at most ONE tool per turn. Look at what it returns before deciding whether
you need anything else.

When you call tools, put a JSON object in your message text first, listing what
you cannot yet determine:
    {{"uncertainties": ["whether the export produced a file"]}}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{{
  "role": "setup" | "test_step" | "teardown",
  "text": "the tester submits the order form",
  "confidence": "high" | "medium" | "low",
  "reason": "why confidence is not high (omit when high)",
  "escalation": "a specific question for the human (only if you genuinely cannot tell)",
  "libraryRef": "lib_... (ONLY when text is copied exactly from a library match)"
}}

About "role" -- what this step is doing in the test:

* `setup` -- getting to the state under test. Signing in, navigating to the
  page, seeding data. Not the thing being verified.
* `test_step` -- the behaviour this test exists to exercise.
* `teardown` -- cleaning up afterwards.

Judge it against the stated objective. Signing in is `setup` for a test about
checkout, and `test_step` for a test about authentication.

Do NOT write the expected result. A later stage proposes those, ranked by where
the intent came from, and it has to retrieve its own evidence to do it. Your job
is the sentence describing what the tester did.

Never guess silently. If the evidence does not settle it, say so with low
confidence and a reason, or escalate with a precise question. An agent that
asks is more useful than one that invents."""


def system_prompt(config: ProjectConfig) -> str:
    """The naming instructions, in this project's voice.

    The worked examples are rendered in the project's voice too, not left
    generic. Written without a subject once, they taught the model to drop it:
    a real run came back "submits an order totalling \"615\"" with nobody
    doing the submitting. Examples outweigh rules, so the examples have to be
    right.
    """
    rule = _VOICE_RULE[config.first_person].format(voice=config.voice)
    return SYSTEM_PROMPT.format(voice_rule=rule, voice=config.voice)


def split_named(naming: NamingResult, splits: list) -> tuple[NamingResult, set[str]]:
    """Cut named steps the way composition asked, before assertions are redone.

    The IR-level `apply_splits` happens later and does the same cut; this one
    exists so the assertion stage has the two halves as real steps to reason
    about. A step created by a split is not the step this pipeline proposed
    expected results for, and inheriting them is how the retry ended up with no
    expected result at all -- while "Order confirmed", the outcome the whole
    test exists to reach, went unmentioned.
    """
    if not splits:
        return naming, set()

    by_step = {getattr(sp, "step_id", ""): sp for sp in splits}
    out = NamingResult(
        model_calls=naming.model_calls,
        superseded=list(naming.superseded),
        discarded_rewrites=list(naming.discarded_rewrites),
    )
    touched: set[str] = set()

    for named in naming.steps:
        split = by_step.get(named.step_id)
        after = getattr(split, "after_event_id", None)
        cut = named.event_ids.index(after) + 1 if after in named.event_ids else 0
        if split is None or not (0 < cut < len(named.event_ids)):
            out.steps.append(named)
            continue

        first, second = getattr(split, "texts", ("", ""))
        head = replace(
            named,
            text=first or named.text,
            event_ids=named.event_ids[:cut],
            assertions=[],
        )
        tail = replace(
            named,
            step_id=f"{named.step_id}b",
            text=second or named.text,
            event_ids=named.event_ids[cut:],
            assertions=[],
        )
        out.steps.extend([head, tail])
        touched.update({head.step_id, tail.step_id})

    return out, touched


REPAIR_ADDENDUM = """\

---

This step has already been written once and sent back. You are writing it again.

What you wrote (attempt {attempt}):
    "{rejected}"

Why it was sent back:
    {finding}

Write the sentence again, fixing that specific problem. Every rule above still
applies -- the same voice, the same subject, one intent, the same quoting of
values that matter. Do not simply reword: if the finding says the step does not
say WHAT was submitted, the new sentence has to say it, which may mean looking
at the evidence again.

Do not make the sentence more generic to satisfy the finding. A step that reads
identically to the one before or after it is worse than the one you are
replacing, and it will be rejected."""


def rename_steps(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming: NamingResult,
    *,
    findings: dict[str, str],
    model_name: str,
    budget: int = DEFAULT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    attempt: int = 2,
) -> tuple[NamingResult, set[str]]:
    """Write particular steps again, with the finding that rejected them (SS9.9).

    Not `name_segments` with a filter, for a reason that would be a silent bug:
    `name_segments` walks `store.segments` and takes each step's events from the
    SEGMENT. A step created by a split (SS9.3) holds only half of one, so
    re-naming it that way would quietly restore the other half's events and
    contradict the split that composition asked for. This walks the named steps
    instead and preserves `step_id`, `segment_id` and `event_ids` exactly.

    Returns the new result and the ids that actually changed -- which is not the
    same as the ids that were asked about. A repair whose replacement collides
    with a neighbouring step is refused, and the caller needs to know it got
    nothing so the finding can be marked unresolved rather than silently
    dropped.
    """
    config = config or ProjectConfig()
    out = NamingResult(
        model_calls=list(naming.model_calls),
        superseded=list(naming.superseded),
        discarded_rewrites=list(naming.discarded_rewrites),
    )
    texts = [s.text for s in naming.steps]
    changed: set[str] = set()

    for index, named in enumerate(naming.steps):
        finding = findings.get(named.step_id)
        # A dictated step and a library-verbatim step are not the tool's to
        # reword (SS6.7, SS12.2). The critic is told so and its findings are
        # filtered, so reaching here means something upstream is wrong -- refuse
        # rather than trust the filter.
        if finding is None or named.library_ref:
            out.steps.append(named)
            continue

        enquiry = investigate(
            runner,
            model,
            system_prompt=system_prompt(config),
            user_prompt=_baseline(
                store, store.segment(named.segment_id), previous=texts[index - 1] if index else None
            )
            + REPAIR_ADDENDUM.format(
                attempt=attempt - 1, rejected=named.text, finding=finding
            ),
            model_name=model_name,
            stage=PipelineStage.name,
            label=f"{named.step_id}_r{attempt}",
            budget=budget if tools_enabled else 0,
            tools_enabled=tools_enabled,
            temperature=temperature,
            step_id=named.step_id,
            segment_id=named.segment_id,
        )
        out.model_calls.extend(enquiry.model_calls)
        answer = enquiry.answer
        escalation = (answer.get("escalation") or "").strip() or None
        enquiry.finish(escalation)

        text = with_subject((answer.get("text") or "").strip(), config)
        if not text or text.strip().casefold() == named.text.strip().casefold():
            # No usable answer, or the same sentence again. Keep what we had:
            # the finding stays unresolved and is surfaced to the human, which
            # is what SS9.9 asks for on exhaustion.
            out.superseded.append(
                enquiry.record(
                    investigation_id=f"inv_{named.step_id}_r{attempt}",
                    stage=PipelineStage.name,
                    budget=budget,
                    step_id=named.step_id,
                    segment_id=named.segment_id,
                )
            )
            out.steps.append(named)
            continue

        if would_collapse(texts, index, text):
            # SS3.6 -- two attempts of the same run must produce the same step
            # count, and `merge_repeats` folds adjacent steps whose text matches.
            out.discarded_rewrites.append(
                f"{named.step_id}: refused {text!r} -- it repeats the step beside it, "
                f"which `merge_repeats` would fold, changing the step count mid-run."
            )
            out.superseded.append(
                enquiry.record(
                    investigation_id=f"inv_{named.step_id}_r{attempt}",
                    stage=PipelineStage.name,
                    budget=budget,
                    step_id=named.step_id,
                    segment_id=named.segment_id,
                )
            )
            out.steps.append(named)
            continue

        investigation = enquiry.record(
            investigation_id=f"inv_{named.step_id}_r{attempt}",
            stage=PipelineStage.name,
            budget=budget,
            step_id=named.step_id,
            segment_id=named.segment_id,
        )
        if escalation:
            investigation.escalationQuestion = escalation
        investigation.narrative.append(f"rewritten after: {finding}")

        out.superseded.append(named.investigation)
        out.steps.append(
            replace(
                named,
                text=text,
                confidence=_confidence(answer.get("confidence")),
                investigation=investigation,
                escalation=escalation,
                reason=str(answer["reason"]) if answer.get("reason") else None,
                library_ref=_library_ref(runner, answer.get("libraryRef"), text),
            )
        )
        texts[index] = text
        changed.add(named.step_id)

    return out, changed


def with_subject(text: str, config: ProjectConfig) -> str:
    """Make sure the step says who is doing it.

    A step is a sentence about a person. Dropped, it reads as an instruction to
    the reader and matches no step definition -- and it happens: a prompt edit
    whose worked examples omitted the subject produced "submits an order
    totalling \"615\"" with nobody submitting anything.

    Deterministic rather than another prompt line, because the prompt already
    says it twice and said it while the examples showed the opposite. Left
    alone if any plausible subject is already there, so a step naming a
    different actor -- "the approver releases the order" -- is not rewritten
    into nonsense.
    """
    if config.first_person:
        return text
    lowered = text.lower()
    if lowered.startswith(config.voice.lower()) or lowered.startswith(("the ", "an ", "a ")):
        return text
    return f"{config.voice} {text[0].lower() + text[1:]}"


@dataclass
class NamedStep:
    """What the stage produces for one segment."""

    segment_id: str
    step_id: str
    role: SegmentRole
    text: str
    confidence: Confidence
    event_ids: list[str]
    investigation: StepInvestigation
    escalation: str | None = None
    reason: str | None = None
    library_ref: str | None = None
    #: At most one in Phase 1. The ranked, multi-candidate assert stage is
    #: Phase 2 (SS9.5); this exists so the ablation has a grounding rate to
    #: measure, which is the metric the whole comparison turns on.
    assertions: list[Assertion] = field(default_factory=list)


@dataclass
class NamingResult:
    steps: list[NamedStep] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    #: Investigations a repair replaced (SS9.9). Kept rather than dropped for
    #: two reasons: SS9.10 wants every `StepInvestigation` in the trace, and
    #: SS3.4's effort column has to count what the run actually spent on a step
    #: -- including the attempt that was rejected, which is exactly the effort
    #: a hard step provoked.
    superseded: list[StepInvestigation] = field(default_factory=list)
    #: Rewrites a repair produced and this stage refused, with the reason.
    #: Recorded rather than dropped: "repair changed nothing" and "repair
    #: proposed something inadmissible" are different facts about a run.
    discarded_rewrites: list[str] = field(default_factory=list)

    @property
    def investigations(self) -> list[StepInvestigation]:
        return [s.investigation for s in self.steps] + list(self.superseded)

    def tool_calls_per_step(self) -> dict[str, int]:
        """The x-axis of the effort/difficulty correlation (SS3.4)."""
        return {s.step_id: len(s.investigation.toolCallIds) for s in self.steps}

    def to_artifact(self) -> dict:
        """`naming.json` -- what this stage decided, before composition sees it.

        SS9.1: each stage reads a file and writes a file, so a wrong sentence
        can be blamed on naming or on composition without re-running either.
        """
        return {
            "stage": "name",
            "steps": [
                {
                    "id": s.step_id,
                    "segmentId": s.segment_id,
                    "text": s.text,
                    "role": s.role.value,
                    "confidence": s.confidence.value,
                    "eventIds": s.event_ids,
                    "investigationRef": s.investigation.id,
                    "toolCalls": list(s.investigation.toolCallIds),
                    **({"escalation": s.escalation} if s.escalation else {}),
                    **({"reason": s.reason} if s.reason else {}),
                    "assertions": [
                        {
                            "text": a.text,
                            "literal": a.evidence.literal,
                            "toolCallId": a.evidence.toolCallId,
                        }
                        for a in s.assertions
                    ],
                }
                for s in self.steps
            ],
        }


def name_segments(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    model_name: str,
    budget: int = DEFAULT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> NamingResult:
    """Name every segment. One investigation per segment."""
    if store.segments is None:
        raise ValueError("segments must be attached before naming")

    config = config or ProjectConfig()
    result = NamingResult()
    previous: str | None = None
    dictated = intent_notes(store)

    for index, segment in enumerate(store.segments.segments):
        step_id = f"step_{index + 1:03d}"
        named = _name_one(
            store,
            runner,
            model,
            segment=segment,
            step_id=step_id,
            model_name=model_name,
            budget=budget if tools_enabled else 0,
            tools_enabled=tools_enabled,
            temperature=temperature,
            config=config,
            previous=previous,
            note=dictated.get(segment.id),
            sink=result.model_calls,
        )
        result.steps.append(named)
        previous = named.text
    return result


def intent_notes(store: EvidenceStore) -> dict[str, str]:
    """Map each segment to the note the tester typed for it, if any (SS6.7).

    Attribution needs every segment in view, so it happens here rather than
    inside `_name_one` -- the same reason network calls are attributed at
    assembly rather than in the frame.

    A note names the step that starts NEXT. Typing one means stopping, opening
    the popup and describing something, which a tester does before doing the
    thing, and the timestamps say so: in the annotated fixture the note lands
    between the sign-in click and the add-to-cart click, and it describes adding
    to the cart. Falling back to the segment containing it covers the tester who
    narrates after the fact instead.
    """
    notes = [
        n for n in store.annotations(0, float("inf"), kind="intent_note") if (n.text or "").strip()
    ]
    if not notes or store.segments is None:
        return {}

    spans: list[tuple[float, float, str]] = []
    for segment in store.segments.segments:
        events = [store.event(e) for e in segment.eventIds if store.has_event(e)]
        if events:
            spans.append((events[0].timestamp, events[-1].timestamp + SETTLE_TAIL_MS, segment.id))
    spans.sort()

    out: dict[str, str] = {}
    for note in notes:
        upcoming = next((sid for start, _end, sid in spans if start >= note.timestamp), None)
        containing = next(
            (sid for start, end, sid in spans if start <= note.timestamp <= end), None
        )
        target = upcoming or containing
        # First note wins: a tester who typed twice for one step meant the first
        # description, and silently concatenating them would produce a sentence
        # neither of them wrote.
        if target and target not in out:
            out[target] = note.text.strip()
    return out


def _dictated_step(segment: Segment, step_id: str, note: str) -> NamedStep:
    """SS6.7 -- an intent note becomes the step name VERBATIM.

    The popup says so to the tester's face ("It will be used word for word")
    and nothing on this side read the annotation, so the promise was never kept
    and a tester who took the trouble to type a step name watched the tool
    rewrite it anyway. That is worse than not offering the feature at all.

    Verbatim is enforced by not calling a model, rather than by asking one not
    to paraphrase. It also costs no quota, which is the small consolation for a
    step the tester had to describe themselves.
    """
    return NamedStep(
        segment_id=segment.id,
        step_id=step_id,
        role=_role(None),
        text=note,
        # The tester wrote it. Nothing about it is uncertain.
        confidence=Confidence.high,
        event_ids=list(segment.eventIds),
        investigation=StepInvestigation(
            id=f"inv_{step_id}",
            stage=PipelineStage.name,
            initialUncertainty=[],
            toolCallIds=[],
            budgetUsed=0,
            budgetMax=0,
            stopReason=StopReason.no_investigation_needed,
            narrative=["the tester named this step themselves; used word for word (SS6.7)"],
        ),
    )


def _name_one(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    segment: Segment,
    step_id: str,
    model_name: str,
    budget: int,
    tools_enabled: bool,
    temperature: float,
    config: ProjectConfig,
    previous: str | None,
    note: str | None,
    sink: list[ModelCall],
) -> NamedStep:
    if note is not None:
        return _dictated_step(segment, step_id, note)

    enquiry = investigate(
        runner,
        model,
        system_prompt=system_prompt(config),
        user_prompt=_baseline(store, segment, previous=previous),
        model_name=model_name,
        stage=PipelineStage.name,
        label=step_id,
        budget=budget,
        tools_enabled=tools_enabled,
        temperature=temperature,
        step_id=step_id,
        segment_id=segment.id,
    )
    sink.extend(enquiry.model_calls)
    answer = enquiry.answer

    escalation = (answer.get("escalation") or "").strip() or None
    enquiry.finish(escalation)

    confidence = _confidence(answer.get("confidence"))
    text = (answer.get("text") or "").strip()
    if not text:
        # A model that returns nothing usable must not silently produce a step
        # that reads as confident.
        text = f"{config.voice} performs an action ({segment.label})"
        confidence = Confidence.low
        answer.setdefault("reason", "the model returned no usable step text")
    else:
        text = with_subject(text, config)

    investigation = enquiry.record(
        investigation_id=f"inv_{step_id.split('_')[-1]}",
        stage=PipelineStage.name,
        budget=budget,
        step_id=step_id,
        segment_id=segment.id,
    )
    if escalation:
        investigation.escalationQuestion = escalation

    return NamedStep(
        segment_id=segment.id,
        step_id=step_id,
        role=_role(answer.get("role")),
        text=text,
        confidence=confidence,
        event_ids=list(segment.eventIds),
        investigation=investigation,
        escalation=escalation,
        reason=str(answer["reason"]) if answer.get("reason") else None,
        library_ref=_library_ref(runner, answer.get("libraryRef"), text),
    )


def _library_ref(runner: ToolRunner, claimed, text: str) -> str | None:
    """Honour a reuse claim only when the text really is the entry (SS12.2).

    A model that copies approved wording *almost* exactly and still claims reuse
    would reintroduce the step explosion the library exists to prevent -- with a
    `libraryRef` on it saying the opposite. `library_verbatim` rejects that at
    the gate; this refuses to record it in the first place, so the common case
    never becomes a rejection a human has to read.
    """
    library = getattr(runner, "library", None)
    if library is None or not str(claimed or "").strip():
        return None
    entry = library.exact(text)
    return entry.id if entry is not None else None


# --------------------------------------------------------------------------
# prompt construction
# --------------------------------------------------------------------------


def _baseline(store: EvidenceStore, segment: Segment, *, previous: str | None = None) -> str:
    """SS9.4's baseline input: the segment's events, its first and last scoped
    snapshots, the diff, a network summary, and the top library matches.

    Deliberately compact. Anything the agent might need beyond this is one tool
    call away, and pre-loading it would make every step cost what the hardest
    step costs.
    """
    events = [store.event(e) for e in segment.eventIds]
    first, last = events[0], events[-1]

    lines: list[str] = []
    objective = store.objective
    lines.append(
        f"Stated objective: {objective}"
        if objective
        else "Stated objective: none given (infer intent from the actions)."
    )
    lines.append("")

    # The previous sentence, so one intent spanning two segments does not come
    # back as the same sentence twice. A reader who sees the tool stutter stops
    # believing the rest of the file.
    if previous:
        lines.append(f"The step before this one reads: {previous}")
    else:
        lines.append("This is the first step of the test.")
    lines.append("")

    lines.append(
        f"Segment {segment.id} ({len(events)} action(s)), began: {segment.boundaryReason.value}"
    )
    lines.append(f"URL: {first.url}")
    lines.append("")

    lines.append("Actions:")
    for event in events:
        target = (
            f'{event.target.role} "{event.target.name}"' if event.target.name else event.target.role
        )
        value = f" value={event.target.value!r}" if event.target.value else ""
        lines.append(f"  {event.id} @{int(event.timestamp)}ms  {event.type.value} {target}{value}")
        for flag in event.fidelity:
            lines.append(f"      ! {flag.value}")
    lines.append("")

    lines.append("Page before the first action:")
    lines.append(_render_nodes(store, first.id, "before"))
    lines.append("")
    lines.append("Page after the last action settled:")
    lines.append(_render_nodes(store, last.id, "after"))
    lines.append("")

    changes = _render_diff(events)
    lines.append("What changed:")
    lines.append(changes or "  (nothing the recorder could see)")
    lines.append("")

    calls = [c for e in events for c in e.network]
    lines.append("Network:")
    if calls:
        for call in calls[:8]:
            status = call.status if call.status is not None else "no response"
            # Say plainly when the server refused. "-> 409" is a number a model
            # can skim past, and one that did: a step went out saying "places an
            # order" for a submission the server rejected, which `mutation_claimed`
            # then correctly failed for claiming a change that never happened.
            verdict = ""
            if isinstance(call.status, int):
                verdict = "  <-- REJECTED" if call.status >= 400 else ""
            lines.append(f"  {call.method} {call.url} -> {status}{verdict}")
    else:
        lines.append("  (no requests)")

    errors = [c for e in events for c in e.console]
    if errors:
        lines.append("")
        lines.append("Console:")
        for entry in errors[:5]:
            lines.append(f"  [{entry.level.value}] {entry.text[:200]}")

    return "\n".join(lines)


def _render_nodes(store: EvidenceStore, event_id: str, when: str, limit: int = 25) -> str:
    nodes = store.nodes(event_id, when)  # type: ignore[arg-type]
    if not nodes:
        return "  (not captured)"
    out: list[str] = []
    for node in nodes[:limit]:
        depth = node.path.count(">") + 1 if node.path else 0
        label = f'{node.role} "{node.name}"' if node.name else node.role
        value = f" = {node.value!r}" if node.value else ""
        state = f" [{', '.join(node.state)}]" if node.state else ""
        out.append(f"  {'  ' * depth}{label}{value}{state}")
    if len(nodes) > limit:
        out.append(f"  ... {len(nodes) - limit} more nodes (use get_snapshot for the rest)")
    return "\n".join(out)


def _render_diff(events) -> str:
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


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _confidence(value) -> Confidence:
    try:
        return Confidence(str(value).lower())
    except ValueError:
        return Confidence.medium


def _role(value) -> SegmentRole:
    """One segment is a weak vantage point for this call, which is why
    composition overrules it. `test_step` is the safe default: it keeps the
    step in the narrative, where a wrong `setup` would quietly demote it."""
    try:
        return SegmentRole(str(value).strip().lower())
    except ValueError:
        return SegmentRole.test_step


__all__ = ["DEFAULT_BUDGET", "NamedStep", "NamingResult", "name_segments", "system_prompt"]
