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

from dataclasses import dataclass, field

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
)
from server.pipeline.investigate import DEFAULT_BUDGET, investigate

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
  one "and", or a comma-separated list of things the tester did, it is
  describing too much -- name the goal instead and quote only the values a
  reader needs to reproduce it. "Submits the order with manager approval" beats
  "enters a purchase order, sets the total, ticks approval and submits".
* You are shown the step before this one. Do not restate it. If this step
  genuinely repeats an earlier action, say so -- "places the order again".
* Never state application state the evidence does not show.
* If a step-library match exists, reuse its wording verbatim.

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
  "escalation": "a specific question for the human (only if you genuinely cannot tell)"
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
    """The naming instructions, in this project's voice."""
    rule = _VOICE_RULE[config.first_person].format(voice=config.voice)
    return SYSTEM_PROMPT.format(voice_rule=rule)


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

    @property
    def investigations(self) -> list[StepInvestigation]:
        return [s.investigation for s in self.steps]

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
            sink=result.model_calls,
        )
        result.steps.append(named)
        previous = named.text
    return result


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
    sink: list[ModelCall],
) -> NamedStep:
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
    )


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
