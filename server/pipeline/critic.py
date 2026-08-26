"""Stage 8a -- the critic (SS9.9). Agentic.

    "The critic judges what code cannot."

Twelve deterministic validators already check whether a claim resolves to a
retrieval, whether the Gherkin parses, whether every event is accounted for.
None of them can tell you that "the tester clicks the button" is a useless step
name, or that the expected result is true and about the wrong thing. That
judgment is what this stage is for, and it is the only reason A2 differs from
A1 at all (SS3.5).

Two things keep it from becoming a machine for inventing work:

**It reports; it never edits.** A finding is a sentence about what is wrong.
`repair.py` decides which stage re-runs, and that stage retrieves its own
evidence. A critic that could hand the assert stage a `literal` and a
`toolCallId` would be a path to a grounded-LOOKING fabrication, which is the one
thing SS3.2 exists to make impossible.

**Finding nothing is the expected answer.** This project has already been bitten
by mandatory effort: counting search-before-invent as investigation lifted
calls/step from 1.56 to 2.17 and collapsed SS3.3's Spread from 1.08 to 0.16 --
an agent that looked like it had stopped adapting when nothing had changed. A
critic that always finds something is that failure again, wearing a different
hat, and it costs three repair attempts per run to find out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from server.config import ProjectConfig
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import IRDocument, ModelCall, PipelineStage, StepInvestigation, TestCaseIR
from server.pipeline.investigate import investigate

#: Small on purpose. The critic reads a finished scenario, which is the thing a
#: human would read; it is not investigating the recording from scratch. Most
#: judgments it makes need no retrieval at all.
CRITIC_BUDGET = 3

#: SS9.9's five judgement axes, as a closed vocabulary. `repair.py` maps these
#: onto stages; anything else the model invents is dropped rather than guessed
#: at, because a finding nobody can act on is noise with a step id attached.
FINDING_KINDS = frozenset(
    {"step_name", "assertion", "coherence", "vocabulary", "state_jump"}
)

SYSTEM_PROMPT = """\
You are reviewing a finished QA test case before a human sees it.

Automatic checks have already run. They confirmed that every expected result
quotes something the tool actually retrieved, that the Gherkin parses, that no
recorded action went missing, and that the scenario ends on an expected result.
Do not re-check any of that. You are here for the one question no program can
answer: **would a QA engineer accept this as a test case?**

Ask that question FIRST, about the document as a whole, before you look at any
individual step.

  Is this ONE test, or several wearing one heading?

  A test case exercises one behaviour and reaches one verdict. This is the
  failure that matters most and the easiest to miss, because every sentence in
  it can be true while the whole is unusable:

      Scenario: Managing a team and updating billing
        When the tester opens the team settings page
        Then the team settings page is displayed
        When the tester invites "sam@example.com" as an editor
        Then the pending invitations list shows one entry
        When the tester opens the billing tab
        Then the current plan is shown as "Team"
        When the tester changes the seat count to "12"
        Then the monthly total updates to "144"

  Every literal there was retrieved. It is still not a test case: it is four
  unrelated checks in a row, and when it fails nobody can say what broke. That
  is a `coherence` finding, and the sentence to write is what is wrong with it
  -- "this covers four unrelated behaviours and reaches no single verdict" --
  never a proposed fix.

  Does the scenario name say what this test PROVES?

  "Managing a team and updating billing" describes what the tester did.
  "Adding a seat raises the monthly total by the per-seat price" says what the
  test establishes, and a reader scanning a list of scenarios can tell it apart
  from the others. A name that reads like a summary of the steps underneath it
  is a `coherence` finding.

Then judge the steps, on these:

* `assertion` -- is the expected result about the thing under test, or about one
  of the other forty things that changed on the page? A true statement about an
  incidental change is the most common way a generated test becomes worthless.
  Watch especially for expected results that check the BROWSER rather than the
  application: "the category page is loaded", "the form is displayed", "the page
  opens". Those are always incidental, however true.
* `step_name` -- is the step describing an intent, or is it "clicks the button"?
  A useful step names what the tester was trying to DO and uses the
  application's own words. A useless one describes a mouse.
* `vocabulary` -- does it match this project's house style, stated below?
* `state_jump` -- does the flow move between steps in a way the steps do not
  explain? A step that ends on the catalogue page followed by one that submits
  an order is missing something.

**Both kinds of mistake are real.** A finding you are not confident about
spends a re-run making the output different rather than better. But approving a
document that is four test cases in a trench coat is the more expensive error,
because it is the one that reaches the tester. If the test case genuinely reads
well, answer with an empty list and say so. If it does not, say what is wrong.

Raise a finding only when you can say what is wrong in one specific sentence
that names the problem, not the fix. "The step name does not say what is being
submitted" is a finding. "Rename it" is not.

You may NOT propose replacement text, an expected result, a quoted value, or a
tool call id. The stage that re-runs will retrieve its own evidence and write
its own sentence. Your job is the diagnosis.

Some steps are marked PROTECTED. Do not raise a `step_name` or `vocabulary`
finding against those under any circumstances -- a protected step was either
typed by the tester word for word, or copied exactly from the team's approved
phrasing, and neither is yours to improve.

You have tools that query the original recording. Use them only when you cannot
judge a step from the test case in front of you -- for instance when you suspect
an expected result is incidental and want to see what else changed. Most reviews
need none.

Call at most ONE tool per turn. Look at what it returns before deciding whether
you need anything else.

When you call tools, put a JSON object in your message text first, listing what
you cannot yet determine:
    {"uncertainties": ["whether the banner was the only thing that changed"]}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{
  "findings": [
    {"step": "step_003", "kind": "step_name",
     "finding": "does not say what is being submitted, so it would match any form on the site"}
  ],
  "reason": "one sentence on what you looked at, whether or not you found anything"
}

`step` is omitted for a `coherence` finding about the scenario as a whole.
`kind` must be one of: step_name, assertion, coherence, vocabulary, state_jump.
An empty `findings` list is a complete and acceptable answer."""


def system_prompt(config: ProjectConfig) -> str:
    """The critic instructions, plus the house style it is asked to judge against.

    `vocabulary` is one of the five axes and it is meaningless without saying
    what the vocabulary IS -- a model asked whether prose matches an unstated
    style will confidently invent one and flag every step that does not match
    its invention.
    """
    voice = f'The test case refers to the person doing the work as "{config.voice}".'
    if config.first_person:
        voice = 'The test case is written in the first person, as "I".'
    return f"{SYSTEM_PROMPT}\n\nHouse style for this project: {voice}"


@dataclass(frozen=True)
class Finding:
    """One thing the critic judged wrong, and where.

    `message` is prose, because it goes three places that are all read by
    people: the repair prompt, `Step.criticNotes`, and a `Warning` in the
    review UI when repair cannot resolve it.
    """

    kind: str
    message: str
    step_id: str | None = None
    case_id: str | None = None

    @property
    def label(self) -> str:
        where = self.step_id or self.case_id or "the scenario"
        return f"{where}: {self.message}"


@dataclass
class CriticResult:
    findings: list[Finding] = field(default_factory=list)
    investigations: list[StepInvestigation] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    #: Findings the model raised against a protected step, or with a `kind`
    #: outside the closed vocabulary. Recorded rather than dropped silently:
    #: "the critic found nothing" and "the critic found something inadmissible"
    #: are different facts about a run.
    discarded: list[str] = field(default_factory=list)
    #: Why the stage did not run, when it did not. An empty `findings` list from
    #: a critic that crashed and one from a critic that read the output and
    #: approved it are the same value and opposite facts, so the second-worst
    #: thing this stage can do is fail quietly.
    failed: str | None = None

    def for_step(self, step_id: str) -> list[Finding]:
        return [f for f in self.findings if f.step_id == step_id]

    def to_artifact(self) -> dict:
        """`critic.json` -- what the critic judged, before repair acted on it."""
        return {
            "stage": "critic",
            "findings": [
                {
                    "kind": f.kind,
                    "step": f.step_id,
                    "case": f.case_id,
                    "finding": f.message,
                }
                for f in self.findings
            ],
            "discarded": self.discarded,
            **({"failed": self.failed} if self.failed else {}),
        }


def critique(
    runner: ToolRunner,
    model: ModelClient,
    ir: IRDocument,
    *,
    model_name: str,
    protected: set[str],
    budget: int = CRITIC_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    rendered: dict[str, str] | None = None,
    only: set[str] | None = None,
    attempt: int = 1,
) -> CriticResult:
    """Judge every test case in the document. One investigation per case.

    Per case rather than per step, because three of the five axes -- coherence,
    state jumps, and whether an expected result is about the thing under test --
    are properties of the whole scenario. Asked about one step in isolation, a
    model cannot see a state jump at all: both sides of it are somewhere else.

    `only` narrows a re-critique to the steps a repair just touched, which is
    how a finding is judged resolved. Without it, attempt 2 would re-review
    steps nothing had changed and charge the run for the privilege.
    """
    config = config or ProjectConfig()
    rendered = rendered or {}
    result = CriticResult()

    for case in ir.testCases:
        if case.kind == "bug_report":
            # A bug report is evidentiary, not reusable. "Does this read as a
            # coherent test" is not a question about it.
            continue
        if only is not None and not any(s.id in only for s in case.steps):
            continue

        enquiry = investigate(
            runner,
            model,
            system_prompt=system_prompt(config),
            user_prompt=_prompt(case, rendered.get(case.id, ""), protected, only),
            model_name=model_name,
            stage=PipelineStage.critic,
            label=f"critic_{case.id}_{attempt}",
            budget=budget if tools_enabled else 0,
            tools_enabled=tools_enabled,
            temperature=temperature,
        )
        result.model_calls.extend(enquiry.model_calls)
        enquiry.finish()
        result.investigations.append(
            enquiry.record(
                investigation_id=f"inv_critic_{case.id}_{attempt}",
                stage=PipelineStage.critic,
                budget=budget,
            )
        )
        _collect(result, enquiry.answer, case, protected, only)

    return result


# --------------------------------------------------------------------------


def _collect(
    result: CriticResult,
    answer: dict,
    case: TestCaseIR,
    protected: set[str],
    only: set[str] | None,
) -> None:
    """Turn the model's answer into findings, discarding what is inadmissible.

    Three deterministic filters, none of them a prompt line, because the prompt
    already asks for all three and a prompt that asks is not a guarantee:

      * an unknown `kind` -- nothing downstream could act on it
      * a step id this case does not have -- including one the model invented
      * a `step_name` or `vocabulary` finding against a protected step, which
        SS6.7 and SS12.2 both forbid rewriting
    """
    known = {s.id for s in case.steps}

    for raw in answer.get("findings") or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        message = str(raw.get("finding") or "").strip()
        step_id = (raw.get("step") or None) and str(raw["step"]).strip()

        if not message:
            continue
        if kind not in FINDING_KINDS:
            result.discarded.append(f"unknown finding kind {kind!r}: {message}")
            continue
        if step_id is not None and step_id not in known:
            result.discarded.append(f"finding names {step_id!r}, which is not a step: {message}")
            continue
        if only is not None and step_id is not None and step_id not in only:
            continue
        if step_id in protected and kind in {"step_name", "vocabulary"}:
            result.discarded.append(
                f"{step_id}: {message} -- not applied. The step was dictated by the tester "
                f"or reused verbatim from the step library, and its wording is not the "
                f"tool's to change (SS6.7, SS12.2)."
            )
            continue

        result.findings.append(
            Finding(kind=kind, message=message, step_id=step_id, case_id=case.id)
        )


def _prompt(
    case: TestCaseIR,
    feature: str,
    protected: set[str],
    only: set[str] | None,
) -> str:
    """The rendered test case, plus the step ids the prose deliberately omits.

    The `.feature` body is prose and nothing else -- no ids, no markers (SS11.1)
    -- which is right for a reader and useless for a critic that has to say
    WHICH step is wrong. So the ids come alongside rather than in the file.
    """
    lines: list[str] = []
    if case.objective:
        lines.append(f"What the tester said they were checking: {case.objective}")
        lines.append("")

    lines.append("The test case as a human will read it:")
    lines.append("")
    lines.append(feature.strip() or "(the renderer produced nothing)")
    lines.append("")
    lines.append("The same steps, with the ids you must use to refer to them:")
    for step in case.steps:
        mark = "  PROTECTED" if step.id in protected else ""
        lines.append(f"  {step.id}  {step.keyword} {step.text}{mark}")
        for assertion in step.assertions:
            if assertion.accepted:
                lines.append(
                    f"      expected: {assertion.text}  "
                    f"[{assertion.provenance.value}, quoting {assertion.evidence.literal!r}]"
                )

    if protected:
        lines.append("")
        lines.append(
            "PROTECTED steps were either typed by the tester word for word, or copied "
            "exactly from the team's approved phrasing. Do not raise step_name or "
            "vocabulary findings against them."
        )

    if only is not None:
        lines.append("")
        lines.append(
            "This is a re-review after a repair. Judge ONLY these steps, which have "
            f"changed since you last saw them: {', '.join(sorted(only))}. If the "
            "problem you raised before is fixed, return an empty findings list."
        )

    return "\n".join(lines)


__all__ = [
    "CRITIC_BUDGET",
    "FINDING_KINDS",
    "CriticResult",
    "Finding",
    "critique",
    "system_prompt",
]
