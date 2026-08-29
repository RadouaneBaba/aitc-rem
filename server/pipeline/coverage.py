"""Stage 7 -- coverage suggestions (SS9.8). Agentic.

    "The one output that cannot exist without reasoning about the unobserved."

Every other stage in this pipeline describes what happened. This one reads what
the recording REVEALED about the application -- a field with a type constraint,
an error shape the API documents, a threshold a banner appears above -- and says
what a tester might record next.

That makes it the clearest functional line between this tool and a transcription
tool, and also the most dangerous output it produces, for the same reason: it is
the only thing here that is not a claim about the session. So it is quarantined
three times over. It lives in its own IR block, never in `steps`. Every renderer
prints it under a heading that says UNVERIFIED. And `suggestions_quarantined`
rejects a run where a suggestion reads back as text already in the feature file.

**Unverified is not the same as ungrounded.** A suggestion is allowed to be
about behaviour nobody exercised. It is not allowed to rest on an observation
nobody made, which is what `basedOn` is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from server.config import ProjectConfig
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    CoverageSuggestion,
    IRDocument,
    ModelCall,
    PipelineStage,
    StepInvestigation,
    TestCaseIR,
)
from server.pipeline.investigate import investigate

COVERAGE_BUDGET = 4

#: What this stage may reach for.
#:
#: It passed nothing at all until 2026-08-29 -- the ONE `investigate()` caller
#: that did not constrain its set -- so it was handed the entire registry,
#: twelve tools including six offered to no stage on purpose and one whose
#: module had already been deleted. The whole reason `tool_names` exists is that
#: more tools measurably means worse tool choice, and this stage was the one
#: place the rule was not applied.
#:
#: Three, not six. "What else should have been tested here" is answered from the
#: page and what changed on it; a request body and a spoken sentence are about
#: what DID happen, which the finished test case in the prompt already covers.
COVERAGE_TOOLS = ["get_diff", "get_snapshot", "find_text"]

#: How many a run may propose per test case. Not a quality filter -- a filter
#: on usefulness. Twenty suggestions is a wall of text a tester scrolls past,
#: and the three that mattered are in it somewhere.
MAX_SUGGESTIONS = 5

CATEGORIES = {
    "validation_path",
    "api_error_shape",
    "boundary_value",
    "disabled_state",
    "visible_branch",
}

SYSTEM_PROMPT = """\
You are reading a finished QA test case and the recording behind it, and saying
what the tester might usefully record NEXT.

This is not a claim about what happened. It is a prompt for a human, and it will
be shown to them under a heading that says UNVERIFIED. Nobody will run it as a
test. So the bar is different from every other question you have been asked
here: be useful, be specific, and do not pretend to certainty you lack.

Look for what the recording REVEALED about the application, not what it did:

* `validation_path` -- a field with a constraint that was only satisfied. An
  email input, a required field, a maximum length. The happy path was recorded;
  the refusal was not.
* `api_error_shape` -- a response the application clearly knows how to produce
  and this session never provoked. If a request came back 201 and the endpoint
  is plainly the same one that returns a conflict, say so.
* `boundary_value` -- a threshold you can see in the evidence. If an approval
  banner appears above 500, then 500 exactly is untested and is the value most
  likely to be wrong.
* `disabled_state` -- a control that was disabled throughout, or became enabled,
  and was never exercised in the other state.
* `visible_branch` -- a route through the UI that was visible the whole time and
  never taken.

Rules:

* Each suggestion must rest on something you actually saw. Put the ids in
  `basedOn`: an event (`evt_0007`), a retrieval (`tc_0012`), a step
  (`step_003`), a request (`net_0002`) or a console line. A suggestion with
  nothing behind it is a guess about software in general, and the tester can
  produce those without us.
* Do not restate the test case. "Check that an order over 500 needs approval" is
  worthless when that is the test you just read.
* Do not suggest testing that the thing that worked still works.
* Say what to record and why it is worth recording, in one sentence each. The
  `rationale` is where the evidence goes: "the endpoint returned 201 here and
  the form shows a duplicate-reference message that never appeared".
* Propose at most {max} suggestions. Fewer good ones beat five padded ones, and
  an empty list is a legitimate answer for a session that revealed nothing.

You have tools that query the recording. Use them to check whether something you
suspect is untested really is -- `find_text` over a message you think exists,
`get_network` for the shape of a response.

Call at most ONE tool per turn. Look at what it returns before deciding whether
you need anything else.

When you call tools, put a JSON object in your message text first, listing what
you cannot yet determine:
    {{"uncertainties": ["whether the email field validates format"]}}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{{
  "suggestions": [
    {{"category": "boundary_value",
      "text": "record an order totalling exactly 500",
      "rationale": "the approval banner quotes 'Orders over EUR500 require approval', so 500 itself is the boundary and nothing exercised it",
      "basedOn": ["evt_0007", "tc_0012"]}}
  ]
}}

`category` must be one of: validation_path, api_error_shape, boundary_value,
disabled_state, visible_branch."""


def system_prompt(config: ProjectConfig) -> str:
    return SYSTEM_PROMPT.format(max=MAX_SUGGESTIONS)


#: Four or more characters, so "the" and "an" do not match everything.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")


def reads_back_as_step(text: str, feature: str) -> bool:
    """Is this "suggestion" just the test case again?

    A suggestion is bound to reuse the application's nouns -- that is what makes
    it specific. But one whose every distinctive word is already in the rendered
    feature is a step wearing a suggestion's label, and SS9.8's quarantine is
    about exactly that confusion.

    Shared by the stage, which refuses to emit one, and by
    `suggestions_quarantined`, which rejects a run that contains one. The two
    must not diverge, which is why there is one function and not two -- the same
    arrangement as `supports_narrated`.
    """
    words = set(_WORD.findall(text.casefold()))
    if not words:
        return False
    return words <= set(_WORD.findall(feature.casefold()))


@dataclass
class CoverageResult:
    by_case: dict[str, list[CoverageSuggestion]] = field(default_factory=dict)
    investigations: list[StepInvestigation] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    #: Proposals thrown out before they reached the IR, with the reason. A
    #: suggestion dropped for an unknown category and a session that genuinely
    #: revealed nothing are different outcomes, and the sidecar should not make
    #: them look the same.
    discarded: list[str] = field(default_factory=list)
    #: Why the stage did not run, when it did not.
    failed: str | None = None

    def to_artifact(self) -> dict:
        return {
            "stage": "coverage",
            "cases": {
                case_id: [
                    {
                        "id": s.id,
                        "category": s.category.value,
                        "text": s.text,
                        "rationale": s.rationale,
                        "basedOn": s.basedOn,
                    }
                    for s in suggestions
                ]
                for case_id, suggestions in self.by_case.items()
            },
            "discarded": self.discarded,
            **({"failed": self.failed} if self.failed else {}),
        }


def suggest_coverage(
    runner: ToolRunner,
    model: ModelClient,
    ir: IRDocument,
    *,
    model_name: str,
    budget: int = COVERAGE_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    rendered: dict[str, str] | None = None,
) -> CoverageResult:
    """Propose what to test next, per test case.

    Runs after the gate has settled, which SS9.8 requires in as many words --
    "after a test case is grounded and validated". A suggestion derived from a
    draft that the validators went on to reject would be advice about a test
    case that no longer exists.
    """
    config = config or ProjectConfig()
    rendered = rendered or {}
    result = CoverageResult()

    for case in ir.testCases:
        # A bug report is a historical record of one failure. "What else should
        # we test" is a question about the test case beside it, not about this.
        if case.kind == "bug_report":
            continue

        enquiry = investigate(
            runner,
            model,
            system_prompt=system_prompt(config),
            user_prompt=_prompt(case, rendered.get(case.id, "")),
            model_name=model_name,
            stage=PipelineStage.coverage,
            label=f"coverage_{case.id}",
            budget=budget if tools_enabled else 0,
            tools_enabled=tools_enabled,
            temperature=temperature,
            tool_names=COVERAGE_TOOLS,
        )
        result.model_calls.extend(enquiry.model_calls)
        enquiry.finish()
        result.investigations.append(
            enquiry.record(
                investigation_id=f"inv_coverage_{case.id}",
                stage=PipelineStage.coverage,
                budget=budget,
            )
        )
        suggestions = _collect(result, enquiry.answer, case, rendered.get(case.id, ""))
        if suggestions:
            result.by_case[case.id] = suggestions

    return result


def attach(ir: IRDocument, result: CoverageResult) -> None:
    """Put the suggestions in the one place they are allowed to be (SS9.8)."""
    for case in ir.testCases:
        proposed = result.by_case.get(case.id)
        if proposed:
            case.suggestions = proposed


# --------------------------------------------------------------------------


def _collect(
    result: CoverageResult, answer: dict, case: TestCaseIR, feature: str
) -> list[CoverageSuggestion]:
    out: list[CoverageSuggestion] = []
    for raw in answer.get("suggestions") or []:
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("category") or "").strip()
        text = str(raw.get("text") or "").strip()
        rationale = str(raw.get("rationale") or "").strip()

        if not text or not rationale:
            # `rationale` is where the evidence goes, so a suggestion without
            # one is an opinion about software in general. SS9.8's whole value
            # is that it reasons about THIS application.
            result.discarded.append(f"{case.id}: no rationale for {text or '(no text)'}")
            continue
        if category not in CATEGORIES:
            result.discarded.append(f"{case.id}: unknown category {category!r} for {text!r}")
            continue
        if reads_back_as_step(text, feature):
            # Refused here rather than only at the gate, the same way
            # `_library_ref` refuses a reuse claim before `library_verbatim`
            # ever has to reject one: the common case should not become a
            # rejection somebody has to read.
            result.discarded.append(
                f"{case.id}: restates the test case rather than extending it: {text!r}"
            )
            continue
        if len(out) >= MAX_SUGGESTIONS:
            result.discarded.append(f"{case.id}: over the cap of {MAX_SUGGESTIONS}: {text!r}")
            continue

        based_on = [str(r) for r in (raw.get("basedOn") or []) if str(r).strip()]
        out.append(
            CoverageSuggestion(
                id=f"sug_{case.id}_{len(out) + 1:03d}",
                text=text,
                rationale=rationale,
                category=category,
                basedOn=based_on,
            )
        )
    return out


def _prompt(case: TestCaseIR, feature: str) -> str:
    lines: list[str] = []
    if case.objective:
        lines.append(f"What the tester said they were checking: {case.objective}")
        lines.append("")
    lines.append("The test case this session produced, which is what NOT to suggest again:")
    lines.append("")
    lines.append(feature.strip() or "(the renderer produced nothing)")
    lines.append("")
    lines.append("The events behind each step, so you can retrieve around them:")
    for step in case.steps:
        lines.append(f"  {step.id}  events {', '.join(step.eventIds)}  -- {step.text}")
    if case.parameters:
        lines.append("")
        lines.append(
            "Redacted values, which are the test's parameters. A constraint on one of "
            "these is worth checking and its VALUE is not available to you:"
        )
        for parameter in case.parameters:
            lines.append(f"  {parameter.placeholder} ({parameter.category})")
    return "\n".join(lines)


__all__ = [
    "CATEGORIES",
    "COVERAGE_BUDGET",
    "MAX_SUGGESTIONS",
    "CoverageResult",
    "attach",
    "suggest_coverage",
    "system_prompt",
]
