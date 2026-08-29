"""The decide-retrieve-observe loop (SS3.3), shared by every agentic stage.

    "A step like `click Save -> POST /api/orders 201 -> alert "Saved"` should
     cost zero tool calls. An ambiguous click with no visible outcome should
     cost eight. That variance is not inefficiency -- it is the observable
     signature of adaptive behaviour."

Naming asks it about one segment; composition asks it about a whole flow. The
loop is the same either way, and so is the `StepInvestigation` it produces --
which matters beyond tidiness, because the effort/difficulty correlation of
SS3.4 and the ablation's tool-calls-per-step column both read that record and
neither should have to know which stage wrote it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server.evidence.tools import ToolRunner
from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelClient,
)
from server.llm.gemini import parse_json_answer
from server.models import ModelCall, PipelineStage, StepInvestigation, StopReason
from server.util.canonical import canonical_json

DEFAULT_BUDGET = 8

#: Absolute ceiling on turns, independent of the tool budget. Guards against a
#: model that answers neither the question nor the instruction to stop; without
#: it the loop would spin until the quota ran out.
MAX_TURNS = 24
MAX_FORCED_TURNS = 2


@dataclass
class Investigation:
    """What one agentic decision cost, and what it concluded."""

    answer: dict[str, Any] = field(default_factory=dict)
    #: The answer turn's raw text, kept because a model answers in the SHAPE of
    #: its worked example and an example with two fenced blocks gets two fenced
    #: blocks back. The author's `.feature` body arrives in one of them.
    answer_text: str = ""
    tool_call_ids: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    narrative: list[str] = field(default_factory=list)
    stop_reason: StopReason = StopReason.no_investigation_needed
    model_calls: list[ModelCall] = field(default_factory=list)

    def finish(self, escalation: str | None = None) -> None:
        """Close the record with why it stopped.

        `escalated` is a first-class outcome, not a failure: an agent that says
        "I cannot tell whether the export succeeded" is more useful than one
        that guesses, and the review UI renders it as a question beside the
        step.
        """
        if escalation:
            self.stop_reason = StopReason.escalated
            self.narrative.append(f"escalated: {escalation}")
        elif self.stop_reason == StopReason.evidence_sufficient:
            self.narrative.append("evidence sufficient")
        elif self.stop_reason == StopReason.no_investigation_needed:
            self.narrative.append(
                "answered without investigating: the evidence was already sufficient"
            )

    def record(
        self,
        *,
        investigation_id: str,
        stage: PipelineStage,
        budget: int,
        step_id: str | None = None,
        segment_id: str | None = None,
    ) -> StepInvestigation:
        out = StepInvestigation(
            id=investigation_id,
            stage=stage,
            initialUncertainty=self.uncertainties,
            toolCallIds=self.tool_call_ids,
            budgetUsed=len(self.tool_call_ids),
            budgetMax=budget,
            stopReason=self.stop_reason,
            narrative=self.narrative,
        )
        if step_id:
            out.stepId = step_id
        if segment_id:
            out.segmentId = segment_id
        if self.answer.get("reason"):
            out.stopRationale = str(self.answer["reason"])
        return out


def investigate(
    runner: ToolRunner,
    model: ModelClient,
    *,
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    stage: PipelineStage,
    label: str,
    budget: int = DEFAULT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    step_id: str | None = None,
    segment_id: str | None = None,
    tool_names: list[str] | None = None,
    needs_retrieval: Callable[[dict[str, Any]], str] | None = None,
) -> Investigation:
    """Run one investigation to an answer, retrieving as the model asks.

    `tool_names` narrows what this stage may reach for. More tools measurably
    means worse tool choice, and a stage that needs six should not be handed
    twelve and trusted to ignore the rest.

    `needs_retrieval` reads a finished answer and returns a sentence when that
    answer makes a claim nothing was retrieved for -- or "" when it is fine. It
    is the mirror image of the budget nudge below, and it exists because the
    two failures are symmetrical and only one of them was handled: a model that
    investigates past its budget is told to stop, and a model that answers
    without investigating at all was told nothing.

    Measured, on `keyhole` against a real model: the author wrote two correct
    verdicts, made **zero** tool calls, had both silently refused by the
    citation check, and shipped scenarios ending on a `When`. It had six tools
    and declined them, because the session index already prints the string it
    wanted to quote -- and the index is a SUMMARY, which is exactly why a claim
    resting on it points at nothing.

    The nudge is deterministic, bounded by the same `MAX_FORCED_TURNS` and
    unable to invent anything: it says go and look, and the model still chooses
    what to look at and still cites only what comes back.
    """
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]
    tools = runner.tool_definitions(tool_names) if tools_enabled else []
    out = Investigation()

    turn = 0
    #: Times the model was told to stop investigating and answer. A model that
    #: ignores the instruction would otherwise loop forever, so the loop gives
    #: up rather than spinning, and the result is surfaced to the human with
    #: low confidence -- never silently accepted.
    forced = 0

    while turn < MAX_TURNS:
        turn += 1
        response = model.complete(
            CompletionRequest(
                model=model_name,
                messages=list(messages),
                tools=tools,
                temperature=temperature,
                json_output=not tools,
            )
        )
        out.model_calls.append(_record(response, stage, label, step_id, turn))

        if not response.wants_tools:
            out.answer = parse_json_answer(response.text)
            out.answer_text = response.text or ""
            missing = (
                needs_retrieval(out.answer)
                if needs_retrieval and tools_enabled and not out.tool_call_ids
                else ""
            )
            if missing and forced < MAX_FORCED_TURNS:
                forced += 1
                out.narrative.append("answered without retrieving anything; asked to look")
                messages.append(Message(role="assistant", content=response.text))
                messages.append(Message(role="user", content=missing))
                out.answer = {}
                out.answer_text = ""
                continue
            break

        if not tools_enabled:
            # A0 has no tools; a model asking for them is told so and expected
            # to answer from what it was given.
            forced += 1
            if forced > MAX_FORCED_TURNS:
                out.narrative.append("gave up: the model kept asking for tools that do not exist")
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
        if isinstance(stated, list) and not out.uncertainties:
            out.uncertainties = [str(u) for u in stated][:6]
            out.narrative.extend(f"could not determine: {u}" for u in out.uncertainties)

        if len(out.tool_call_ids) >= budget:
            out.stop_reason = StopReason.budget_exhausted
            forced += 1
            if forced == 1:
                out.narrative.append(
                    f"stopped after {len(out.tool_call_ids)} calls: budget exhausted"
                )
            if forced > MAX_FORCED_TURNS:
                out.narrative.append("gave up: the model kept investigating past its budget")
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
            if len(out.tool_call_ids) >= budget:
                break
            call_id, tool_response = runner.call(
                invocation.name,
                invocation.arguments,
                step_id=step_id,
                segment_id=segment_id,
                stage=stage,
            )
            out.tool_call_ids.append(call_id)
            out.narrative.append(f"{invocation.name}({_brief(invocation.arguments)}) -> {call_id}")
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
                    # A tool that answers with a picture attaches it here. What
                    # was hashed and stored is still the text description, so a
                    # citation resolves to exactly one image; the bytes are for
                    # the model's eyes and go no further.
                    images=[image] if (image := runner.image_for(tool_response)) else [],
                )
            )

        if out.stop_reason == StopReason.no_investigation_needed:
            out.stop_reason = StopReason.evidence_sufficient

    return out


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _assistant_turn(response: CompletionResponse) -> Message:
    return Message(role="assistant", content=response.text, tool_calls=response.tool_calls)


def _record(
    response: CompletionResponse,
    stage: PipelineStage,
    label: str,
    step_id: str | None,
    turn: int,
) -> ModelCall:
    call = ModelCall(
        id=f"mc_{label}_{turn}",
        stage=stage,
        provider=response.provider or "unknown",
        model=response.model or "unknown",
        turn=turn,
        promptTokens=response.prompt_tokens,
        completionTokens=response.completion_tokens,
        cached=response.cached,
        finishReason=response.finish_reason,
        timestamp=0.0,
    )
    if step_id:
        call.stepId = step_id
    return call


def _brief(args: dict[str, Any]) -> str:
    rendered = json.dumps(args, ensure_ascii=False)
    return rendered if len(rendered) <= 60 else rendered[:57] + "..."


__all__ = [
    "DEFAULT_BUDGET",
    "MAX_FORCED_TURNS",
    "MAX_TURNS",
    "Investigation",
    "investigate",
]
