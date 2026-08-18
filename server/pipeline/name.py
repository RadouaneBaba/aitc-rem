"""Stage 3 -- naming (SS9.4). Agentic.

For each segment, one sentence describing tester intent. The baseline evidence
is handed over up front; then the agent investigates.

    "A step with an obvious outcome costs zero calls; an ambiguous one costs
     several."

That variance is not inefficiency. It is the observable signature of adaptive
behaviour (SS3.3), and the trace records it per step so the effort/difficulty
correlation of SS3.4 can be plotted from production data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelClient,
)
from server.llm.gemini import parse_json_answer
from server.models import (
    Assertion,
    Confidence,
    Evidence,
    ModelCall,
    PipelineStage,
    Segment,
    StepInvestigation,
    StopReason,
)
from server.util.canonical import canonical_json

DEFAULT_BUDGET = 8

#: Absolute ceiling on turns per step, independent of the tool budget. Guards
#: against a model that answers neither the question nor the instruction to
#: stop; without it the loop would spin until the quota ran out.
MAX_TURNS = 24
MAX_FORCED_TURNS = 2

SYSTEM_PROMPT = """\
You are naming one step of a manual QA test case, from a browser recording.

Write ONE sentence describing what the tester was trying to DO. Rules:

* Describe intent, not mechanics. "Submits the order" beats "clicks the blue button".
* Use the application's own vocabulary, taken from the accessible names you are shown.
* Never state application state the evidence does not show.
* Present tense, third person, starting with "the tester". No trailing full stop.
* If a step-library match exists, reuse its wording verbatim.

You have tools that query the recording. Use them when, and only when, you
cannot tell what happened from the evidence you already have. A step with an
obvious outcome should cost zero tool calls.

Call at most ONE tool per turn. Look at what it returns before deciding whether
you need anything else.

When you call tools, put a JSON object in your message text first, listing what
you cannot yet determine:
    {"uncertainties": ["whether the export produced a file"]}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{
  "keyword": "Given" | "When" | "Then" | "And",
  "text": "the tester submits the order form",
  "confidence": "high" | "medium" | "low",
  "reason": "why confidence is not high (omit when high)",
  "escalation": "a specific question for the human (only if you genuinely cannot tell)",
  "expected": {
    "text": "the confirmation banner appears",
    "literal": "Order confirmed",
    "toolCallId": "tc_0447",
    "eventId": "evt_027",
    "kind": "semantic_node"
  }
}

About "expected" -- the result a tester would check for after this step:

* Decide first whether this step produced an observable outcome: a message,
  a banner, a status or alert, a counter changing, a page moving, a request
  succeeding. The evidence above shows you what changed.
* If it did, you MUST ground it, and grounding requires a retrieval. Call
  `find_text` with the exact string you intend to quote, then cite the id of
  that call. Do this even when the string is already visible above: a claim is
  only admissible if a retrieval in THIS conversation returned it.
* `literal` must be an EXACT string from a tool response you received here.
  Not paraphrased, not retyped from the summary above.
* `toolCallId` must be the id of the call that returned it. Every tool result
  you receive begins with its own `toolCallId` -- copy that value exactly.
  Do not invent an id or make one up from the tool's name.
* If the step genuinely produced no observable outcome -- filling a field,
  opening a menu -- omit `expected`. That is the right answer, not a failure.
* Never invent an id. An omitted expected result is correct; a fabricated
  citation is the one thing that must never happen.
* `text` is free prose and does NOT have to contain the literal.

Never guess silently. If the evidence does not settle it, say so with low
confidence and a reason, or escalate with a precise question. An agent that
asks is more useful than one that invents."""


@dataclass
class NamedStep:
    """What the stage produces for one segment."""

    segment_id: str
    step_id: str
    keyword: str
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


def name_segments(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    *,
    model_name: str,
    budget: int = DEFAULT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
) -> NamingResult:
    """Name every segment. One investigation per segment."""
    if store.segments is None:
        raise ValueError("segments must be attached before naming")

    result = NamingResult()
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
            sink=result.model_calls,
        )
        result.steps.append(named)
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
    sink: list[ModelCall],
) -> NamedStep:
    messages = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=_baseline(store, segment)),
    ]
    tools = runner.tool_definitions() if tools_enabled else []

    tool_call_ids: list[str] = []
    uncertainties: list[str] = []
    narrative: list[str] = []
    stop_reason = StopReason.no_investigation_needed
    answer: dict[str, Any] = {}
    turn = 0
    #: Times the model was told to stop investigating and answer. A model that
    #: ignores the instruction would otherwise loop forever, so the loop gives
    #: up rather than spinning, and the step is surfaced to the human with low
    #: confidence -- never silently accepted.
    forced = 0

    while turn < MAX_TURNS:
        turn += 1
        request = CompletionRequest(
            model=model_name,
            messages=list(messages),
            tools=tools,
            temperature=temperature,
            json_output=not tools,
        )
        response = model.complete(request)
        sink.append(_record(response, step_id, turn))

        if not response.wants_tools:
            answer = parse_json_answer(response.text)
            break

        if not tools_enabled:
            # A0 has no tools; a model asking for them is told so and expected
            # to answer from what it was given.
            forced += 1
            if forced > MAX_FORCED_TURNS:
                narrative.append("gave up: the model kept asking for tools that do not exist")
                break
            messages.append(Message(role="assistant", content=response.text))
            messages.append(
                Message(
                    role="user",
                    content="No tools are available in this configuration. "
                    "Answer from the evidence above.",
                )
            )
            continue

        stated = parse_json_answer(response.text).get("uncertainties")
        if isinstance(stated, list) and not uncertainties:
            uncertainties = [str(u) for u in stated][:6]
            narrative.extend(f"could not determine: {u}" for u in uncertainties)

        if len(tool_call_ids) >= budget:
            stop_reason = StopReason.budget_exhausted
            forced += 1
            if forced == 1:
                narrative.append(f"stopped after {len(tool_call_ids)} calls: budget exhausted")
            if forced > MAX_FORCED_TURNS:
                narrative.append("gave up: the model kept investigating past its budget")
                break
            messages.append(_assistant_turn(response))
            messages.append(
                Message(
                    role="user",
                    content=(
                        "The investigation budget is used up. Answer now with the evidence "
                        "you have, at the confidence it justifies. If you still cannot tell, "
                        "escalate with a specific question."
                    ),
                )
            )
            continue

        # One retrieval per turn, deliberately.
        #
        # It matches the investigation SS3.3 describes -- decide, retrieve,
        # observe, decide again -- and it avoids a concrete provider problem:
        # Gemini 3 attaches a thought signature only to the FIRST function call
        # of a parallel batch, then rejects the replayed conversation because
        # the second one has none. Sequential calls always carry their own.
        response.tool_calls = response.tool_calls[:1]

        messages.append(_assistant_turn(response))
        for invocation in response.tool_calls:
            if len(tool_call_ids) >= budget:
                break
            call_id, tool_response = runner.call(
                invocation.name,
                invocation.arguments,
                step_id=step_id,
                segment_id=segment.id,
                stage=PipelineStage.name,
            )
            tool_call_ids.append(call_id)
            narrative.append(f"{invocation.name}({_brief(invocation.arguments)}) -> {call_id}")
            # The id is put INSIDE the content on purpose. Providers carry a
            # tool_call_id in their own envelope, but the model never sees it,
            # so asked to cite one it invents a plausible-looking name --
            # observed in a real run as `find_text_0` against a true claim,
            # correctly rejected by evidence_retrieved. An agent can only cite
            # what it was shown.
            #
            # The wrapper is for the conversation only. What was stored and
            # hashed is the raw response, so the citation still resolves to
            # exactly what the tool returned.
            messages.append(
                Message(
                    role="tool",
                    name=invocation.name,
                    tool_call_id=call_id,
                    content=canonical_json({"toolCallId": call_id, "result": tool_response}),
                )
            )

        if stop_reason == StopReason.no_investigation_needed:
            stop_reason = StopReason.evidence_sufficient

    escalation = (answer.get("escalation") or "").strip() or None
    if escalation:
        stop_reason = StopReason.escalated
        narrative.append(f"escalated: {escalation}")
    elif stop_reason == StopReason.evidence_sufficient:
        narrative.append("evidence sufficient")
    elif stop_reason == StopReason.no_investigation_needed:
        narrative.append("answered without investigating: the evidence was already sufficient")

    confidence = _confidence(answer.get("confidence"))
    text = (answer.get("text") or "").strip()
    if not text:
        # A model that returns nothing usable must not silently produce a step
        # that reads as confident.
        text = f"the tester performs an action ({segment.label})"
        confidence = Confidence.low
        answer.setdefault("reason", "the model returned no usable step text")

    investigation = StepInvestigation(
        id=f"inv_{step_id.split('_')[-1]}",
        stepId=step_id,
        segmentId=segment.id,
        stage=PipelineStage.name,
        initialUncertainty=uncertainties,
        toolCallIds=tool_call_ids,
        budgetUsed=len(tool_call_ids),
        budgetMax=budget,
        stopReason=stop_reason,
        narrative=narrative,
    )
    if answer.get("reason"):
        investigation.stopRationale = str(answer["reason"])
    if escalation:
        investigation.escalationQuestion = escalation

    return NamedStep(
        segment_id=segment.id,
        step_id=step_id,
        keyword=_keyword(answer.get("keyword")),
        text=text,
        confidence=confidence,
        event_ids=list(segment.eventIds),
        investigation=investigation,
        escalation=escalation,
        reason=str(answer["reason"]) if answer.get("reason") else None,
        assertions=_assertions(answer.get("expected"), step_id, segment),
    )


def _assertions(expected: Any, step_id: str, segment: Segment) -> list[Assertion]:
    """Turn a claimed expected result into an evidence-bound assertion.

    Nothing is checked here on purpose. Whether the citation is real is the
    validator's job (SS9.7), and the ablation measures precisely how often each
    configuration gets it wrong -- so a fabricated citation has to survive this
    far to be counted.
    """
    if not isinstance(expected, dict):
        return []
    text = str(expected.get("text") or "").strip()
    literal = str(expected.get("literal") or "")
    tool_call_id = str(expected.get("toolCallId") or "")
    if not (text and literal and tool_call_id):
        return []

    event_id = str(expected.get("eventId") or "") or segment.eventIds[-1]
    kind = str(expected.get("kind") or "semantic_node")
    if kind not in {"semantic_node", "url", "network", "console", "narration", "a11y_node"}:
        kind = "semantic_node"

    return [
        Assertion(
            id=f"asrt_{step_id.split('_')[-1]}",
            text=text,
            provenance="inferred",
            evidence=Evidence(
                literal=literal, toolCallId=tool_call_id, eventId=event_id, kind=kind
            ),
            accepted=True,
            rank=1,
        )
    ]


# --------------------------------------------------------------------------
# prompt construction
# --------------------------------------------------------------------------


def _baseline(store: EvidenceStore, segment: Segment) -> str:
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


def _assistant_turn(response: CompletionResponse) -> Message:
    return Message(role="assistant", content=response.text, tool_calls=response.tool_calls)


def _record(response: CompletionResponse, step_id: str, turn: int) -> ModelCall:
    return ModelCall(
        id=f"mc_{step_id}_{turn}",
        stage=PipelineStage.name,
        stepId=step_id,
        provider=response.provider or "unknown",
        model=response.model or "unknown",
        turn=turn,
        promptTokens=response.prompt_tokens,
        completionTokens=response.completion_tokens,
        cached=response.cached,
        finishReason=response.finish_reason,
        timestamp=0.0,
    )


def _confidence(value: Any) -> Confidence:
    try:
        return Confidence(str(value).lower())
    except ValueError:
        return Confidence.medium


def _keyword(value: Any) -> str:
    allowed = {"Given", "When", "Then", "And"}
    text = str(value or "").strip().capitalize()
    return text if text in allowed else "When"


def _brief(args: dict[str, Any]) -> str:
    rendered = json.dumps(args, ensure_ascii=False)
    return rendered if len(rendered) <= 60 else rendered[:57] + "..."
