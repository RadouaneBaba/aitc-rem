"""Is this a test case a QA lead would sign?

The gate answers *can this claim point at the retrieval that produced it*. It
has never answered the question above, and the two came apart on a real
recording: `rec_MTA7A2XHHH22` shipped fourteen validators green, 4 of 4 claims
grounded, and three of the four proving nothing. Across ten recordings the judge
called 0 of 3 held-out runs good while nine of ten reported a grounding rate of
1.0.

    The gate is doing its job and the author is not.

So this is not a fifteenth validator. Every check below is one **no validator
can perform**, and the rule for putting one here rather than in
`validators/` is the same rule that cut fourteen to five, read backwards: a
check that can be wrong does not belong at the gate, and a check that cannot be
wrong does not belong here. A regex guessing whether a sentence is meaningful
will always lose to a model reading it -- and the nine deleted refusal rules are
what that loss looks like.

## Why this is not the critic

The critic raised nine findings and the repair loop resolved one, and the
post-mortem is worth carrying: five of the seven survivors were `coherence`,
which had no repair route by design, so the loop never started. Two things are
different here and both are load-bearing.

**Fresh context.** The judge sees the finished document, the session index and
what the tester expected. It does **not** see the author's reasoning, its tool
calls, or which claims it refused. Self-critique with the same model and the
same context does not work; it is the same model reading its own justification
back and agreeing with it.

**One route.** There is no routing table deciding which stage re-runs.
Findings go to the author, which wrote the document and is the only thing that
knows which part of it is wrong. `VALIDATOR_REPAIR` and `CRITIC_REPAIR` are
exactly the machinery the rebuild removed.

## The judge here and the judge in `evals/` are deliberately two things

`evals/RUBRIC.md` and `.claude/agents/qa-judge.md` are the **instrument**: they
answer *did this change help*, out of band, on held-out recordings, and their
own rules say never edit the rubric to make a verdict pass. This module is part
of the machine, and its prompt is meant to be tuned.

They share the five questions and nothing else. Wiring the pipeline to
`RUBRIC.md` would mean tuning the pipeline tunes the instrument, and a ledger of
such numbers measures nothing.

## What it is allowed to look at

Read-only evidence tools, so *"would this verdict survive a broken build"* is a
question it can answer by looking rather than by guessing. It cannot write,
cannot re-retrieve on the author's behalf, and its findings never reach the
tester -- a reviewer reads `whyNot` in the tester's own language, never
`coherence: weak`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import ExpectationSet, IRDocument, PipelineStage, StepInvestigation
from server.pipeline.investigate import investigate

#: Read-only, and five rather than the author's six. `get_narration` stays out
#: because what the tester said is already quoted in the prompt.
#:
#: `get_network` was out on the same reasoning -- a request is not what a QA lead
#: reads a scenario against -- and `claim_within_evidence` is exactly the case
#: that reasoning missed. The finding it exists for is a sentence claiming a 409
#: over a literal that is a page alert, and the only way to say whether the
#: sentence overreaches or the author simply cited badly is to look at what the
#: server actually answered.
JUDGE_TOOLS = ["get_diff", "get_snapshot", "see", "find_text", "get_network"]

#: Small on purpose. The judge is reading a finished document, not building one,
#: and its expensive question -- would this survive a broken build -- is usually
#: answerable from the evidence already quoted beneath each step. Spending it is
#: allowed; needing more of it than the author did would mean the prompt is
#: asking for the wrong thing.
JUDGE_BUDGET = 6

#: The first five are the vocabulary `evals/RUBRIC.md` already uses, so a finding
#: here and a finding there are the same kind of thing. The last two are new and
#: `RUBRIC.md` does not have them yet -- deliberately, because the rubric is the
#: out-of-band instrument and this is part of the machine. Each closes a hole
#: that the gate cannot see and the other five did not look at:
#:
#:   claim_within_evidence  the sentence and its literal are about the same fact
#:   refusal_is_true        a `whyNot` is a statement about the recording, and
#:                          nothing anywhere checks whether it is right
CHECKS = (
    "verdict_fails_on_broken_build",
    "sentence_covers_its_events",
    "one_scenario_one_behaviour",
    "name_matches_verdict",
    "tester_intent_kept",
    "claim_within_evidence",
    "refusal_is_true",
)

#: `_parse` drops a finding whose `check` is not in the tuple above, silently.
#: That is right -- a finding pointing at a category that does not exist reaches
#: the author as an instruction to change nothing -- and it is also a trap:
#: adding a question to the PROMPT without adding it here ships a change that
#: looks clean and does nothing at all. The two lists live one screen apart for
#: that reason, and `test_judge` asserts every id in `CHECKS` appears in the
#: prompt and vice versa.

#: `fail` is what a QA lead would send back; `weak` is what they would sign
#: after an edit. Only `fail` is worth another author round -- a revision
#: triggered by every `weak` would rewrite a document that was already
#: acceptable, and every rewrite risks `merge_repeats` folding two steps into
#: one.
SEVERITIES = ("weak", "fail")


SYSTEM_PROMPT = """\
You are a QA lead. Somebody hands you a generated test case and the recording it
came from, and you say whether you would sign it.

You did not write this and you are not fixing it. You are saying what is wrong
with it, precisely enough that whoever wrote it knows what to change.

## The one question that does most of the work

**Break the feature. Does this step still pass?**

If yes, the step is decoration, whatever else is right about it.

    Then the product list updates to show lower-priced items first
    evidence: "Prix bas a haut"

That is the option the tester picked from the sort dropdown. Reverse the sort
order in the application and the dropdown still says what they set it to, so
this passes on a broken build. It proves nothing.

    Then the hamper is shown as a "Medium Wicker Basket"
    evidence: the basket's name

Break the capacity counter -- the thing the upgrade feature actually computes --
and this still passes. "13 / 13" was in the same snapshot and was not asserted.

Both of those were green on every validator. That is the gap you exist to close.

## The seven checks

Score each scenario `pass`, `weak` or `fail`.
`weak` = you would sign it after an edit. `fail` = you would send it back.

1. **verdict_fails_on_broken_build** -- would the evidence move if the feature
   broke? A restatement of the scenario name asserts nothing. Neither does a
   claim bound to a heading, a label, or the value the tester themselves typed.

   The commonest form is a literal too GENERIC to discriminate: a sentence
   saying "the badge shows 1 item" resting on the bare literal `1`, which is
   also in every price, id and timestamp on the page, so the check stays green
   on a build where the badge never updated. Judge the literal against the
   sentence, not the sentence alone. When you raise this, your `fix` must name
   the route -- the phrase the page puts around the value ("Cart contains 1
   items"), or `first_of`/`count` where the claim is really about position or
   quantity. A finding with no route is one the author cannot act on.

2. **sentence_covers_its_events** -- the step's sentence describes the events
   listed under it, all of them and no more. "adds an item to the cart and
   proceeds to checkout" over four events, two of which are a detour to a
   reports page, covers neither detour and is a fail. Nothing automated can read
   a sentence against its events; this is yours.

   A step covering many events is not the defect. "fills in the delivery
   address" over six typed fields is one action a tester performs and one step
   somebody will automate, and splitting it into six lines produces a
   transcript. The defect is a sentence that leaves something OUT -- a detour, a
   second unrelated action, a page the tester visited in between. Ask what a
   reader would be surprised to learn happened under this line.

3. **one_scenario_one_behaviour** -- one heading, one behaviour. What decides
   this is the OUTCOME, never the length: a scenario that walks a whole journey
   -- browse, add to bag, check out, pay -- to reach one verdict is one
   behaviour, and cutting it into five leaves four scenarios whose set-up is
   someone else's test. What is not one behaviour is several UNRELATED outcomes
   sharing a heading: sorting a list and then signing out, checked under one
   name, is two test cases pretending to be one.

   Two different values put through the same flow are also one behaviour. That
   is what an `Examples` table is for, and asking for it to be split into
   near-identical scenarios is asking for a transcript.

4. **name_matches_verdict** -- the scenario's name is the outcome its body
   reaches. A name promising approval over a body that only asserts a cart badge
   is a fail, however clean each half is on its own. A long scenario passes as
   long as its name is the thing it ends up establishing; it does not have to
   name every verdict along the way, and a parameter in the name (`<product>`)
   is fine.

5. **tester_intent_kept** -- nothing the tester said was lost. The objective, a
   spoken sentence, a marked element, a confirmed expectation: each of those
   outranks the author's judgement. If the tester said they were checking the
   discount and no scenario is about the discount, that is a fail no matter how
   good the prose is.

6. **claim_within_evidence** -- read each sentence against the literal printed
   under it and ask whether they are about the same fact. The gate confirms the
   literal really came back from a retrieval; nothing confirms the SENTENCE is
   about the literal. This shipped:

       Then the order is rejected with a 409 Conflict status
       evidence: "Orders over EUR500 require approval"

   That literal is a page alert. There is no 409 in it, and no request was
   retrieved. The claim may well be true -- it came from the session index,
   which is a summary and is not citable -- and it is still a sentence claiming
   more than its evidence shows. A `fail`. The fix is to retrieve the thing you
   are actually claiming, or to claim the thing you actually retrieved.

7. **refusal_is_true** -- a step that says it has no verdict gives a reason, and
   the reason is a statement about the recording that a tester will read and
   believe. Check it against the session index. This shipped:

       no verdict, because: the tester navigates to a new browser tab, which is
       outside the scope of the current application session recording

   and it is false. The recorder followed the tab, the event carries its own
   tab id, and the index says in as many words that the tester moved to another
   window. **Every validator passes a refusal, because a refusal claims
   nothing** -- so this is the one output in the system that is confident and
   otherwise entirely unchecked. A refusal that misreads the recording is a
   `fail`; one that is true, even if a better author could have found a verdict,
   is at most `weak`.

## Two ways to get this wrong

**Do not reward provenance.** Every claim in front of you already points at a
retrieval; that is the gate's job and it has done it. A document that grounded
everything and asserted nothing worth asserting is a bad document.

**Do not punish an honest gap.** A step that says why it has no verdict --
"the product list was never captured before or after this click" -- is the
DESIGNED outcome when the recording does not contain one. A visible gap beats an
invisible falsehood. That is `weak` with the reason at most, and often `pass`.

## Looking

You have get_diff, get_snapshot, see and find_text over the recording. Use them
when you cannot tell from the document whether a verdict would survive a broken
build -- typically to find out what ELSE was on the page that the author could
have asserted instead. Do not use them to re-derive the whole session; most
scenarios are decidable from what is printed below.

## What to answer with

JSON, nothing else. One entry per problem, not per scenario. An empty `findings`
list is a real and good answer.

{
  "findings": [
    {
      "check": "verdict_fails_on_broken_build",
      "severity": "fail",
      "scenario": "Sorting products by price",
      "step": "step_004",
      "what": "The verdict rests on the sort option the tester selected, which the page shows whether or not it sorted anything.",
      "fix": "Assert the first product's price, or the order of the first two names."
    }
  ]
}

`check` is one of: verdict_fails_on_broken_build, sentence_covers_its_events,
one_scenario_one_behaviour, name_matches_verdict, tester_intent_kept,
claim_within_evidence, refusal_is_true. Anything else is discarded unread.
`severity` is weak or fail. `step` is a step id from the document, or omit it
when the finding is about the scenario as a whole.

`what` and `fix` are read by the author, not by the tester. Say the specific
thing: "assert the capacity counter, which was in the same snapshot" is
actionable, "improve the assertion" is not.
"""


USER_PROMPT = """\
{expectations}

Here is the session the test case came from.

{digest}

Here is the test case.

{feature}

And here is what each step claims, with the evidence underneath it.

{steps}

Judge it.
"""


@dataclass
class Finding:
    """One thing wrong with the document, in the author's vocabulary."""

    check: str
    severity: str
    what: str
    scenario: str = ""
    step_id: str = ""
    fix: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "scenario": self.scenario,
            "stepId": self.step_id,
            "what": self.what,
            "fix": self.fix,
        }

    def as_feedback(self) -> str:
        """How it reaches the author. Plain sentences, no schema, no severity.

        The author is being asked to rewrite a document, not to process a
        report. `coherence: weak on step_004` is the vocabulary the rebuild
        deleted -- it names a machine's category rather than the thing that is
        wrong.
        """
        where = f" ({self.step_id})" if self.step_id else ""
        scenario = f'In "{self.scenario}"{where}: ' if self.scenario else ""
        fix = f" {self.fix}" if self.fix else ""
        return f"{scenario}{self.what}{fix}"


@dataclass
class JudgeResult:
    findings: list[Finding] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    model_calls: list = field(default_factory=list)
    #: Set when the call failed. The run survives -- a judgement is worth less
    #: than the document it judges -- and says so rather than reporting a clean
    #: verdict it never reached.
    failed: str = ""

    @property
    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "fail"]

    def to_artifact(self) -> dict[str, Any]:
        return {
            "stage": PipelineStage.judge.value,
            "failed": self.failed,
            "findings": [f.as_dict() for f in self.findings],
        }


def judge_document(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    ir: IRDocument,
    *,
    model_name: str,
    rendered: dict[str, str],
    budget: int = JUDGE_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
    expectations: ExpectationSet | None = None,
) -> JudgeResult:
    """Read the finished document and say what a QA lead would send back."""
    from server.pipeline.author import _expectations_block
    from server.pipeline.digest import build_digest

    del config  # house style is not a thing the judge has an opinion about
    digest = build_digest(store)

    result = investigate(
        runner,
        model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT.format(
            expectations=_expectations_block(expectations),
            digest=digest.text,
            feature="\n\n".join(rendered.values()) or "(nothing was rendered)",
            steps=describe_claims(ir),
        ),
        model_name=model_name,
        stage=PipelineStage.judge,
        label="judge",
        budget=budget if tools_enabled else 0,
        tools_enabled=tools_enabled,
        temperature=temperature,
        tool_names=JUDGE_TOOLS,
    )

    out = _parse(result.answer, ir)
    out.investigation = result.record(
        investigation_id="inv_judge", stage=PipelineStage.judge, budget=budget
    )
    out.model_calls = list(result.model_calls)
    return out


def describe_claims(ir: IRDocument) -> str:
    """Every step, its events, its verdict and the evidence underneath it.

    The layout is the argument, and it is `scripts/eval_packet.py`'s section 3:
    a step's sentence, the events it claims and the claim it reached are the
    three things that have to agree, so they are printed together with nothing
    between them. `whyNot` is printed too -- a refusal is a decision the author
    made and is as judgeable as a claim.
    """
    from server.renderers.base import test_cases

    lines: list[str] = []
    for case in test_cases(ir):
        lines.append(f'Scenario: {case.scenarioName or case.title or case.id}')
        for step in case.steps:
            events = ", ".join(step.eventIds) or "no events"
            lines.append(f"  {step.keyword} {step.text}   [{step.id}; {events}]")
            for assertion in step.assertions:
                if not assertion.accepted:
                    continue
                evidence = assertion.evidence
                lines.append(f"    verdict: {assertion.text}")
                if evidence is None:
                    # An unproved verdict, shown rather than hidden. It is in the
                    # feature file, so a QA lead reading that file sees it -- and
                    # `refusal_is_true` is the check that asks whether the reason
                    # given for not proving something is actually true of the
                    # recording. Dropping these here would leave the one output
                    # that is confident and unchecked unchecked again.
                    lines.append(
                        f"    NOT PROVED -- nothing in this run backs this sentence: "
                        f"{assertion.whyNot or 'no reason recorded'}"
                    )
                else:
                    lines.append(
                        f'    evidence: "{evidence.literal}" '
                        f"({evidence.kind} at {evidence.eventId}){_form(evidence)}"
                    )
            if step.whyNot:
                lines.append(f"    no verdict, because: {step.whyNot}")
        for omission in case.omitted or []:
            ids = ", ".join(omission.eventIds or [])
            lines.append(f"  omitted on purpose ({omission.reason}): {omission.summary} [{ids}]")
        lines.append("")
    return "\n".join(lines).rstrip() or "(the document has no steps)"


def _parse(answer: dict[str, Any], ir: IRDocument) -> JudgeResult:
    out = JudgeResult()
    raw = answer.get("findings")
    if not isinstance(raw, list):
        return out

    # Step ids are checked against the document for the same reason the author
    # never supplies a `toolCallId`: a finding pointing at a step that does not
    # exist reaches the author as an instruction to change nothing, and it is
    # indistinguishable from one it simply failed to act on.
    known = {step.id for case in ir.testCases for step in case.steps}

    for item in raw:
        if not isinstance(item, dict):
            continue
        check = _clean(item.get("check"))
        what = _clean(item.get("what"))
        if check not in CHECKS or not what:
            continue
        severity = _clean(item.get("severity"))
        step_id = _clean(item.get("step"))
        out.findings.append(
            Finding(
                check=check,
                # An unrecognised severity is treated as the weaker one. Getting
                # this backwards would let a typo trigger an author round.
                severity=severity if severity in SEVERITIES else "weak",
                what=what,
                scenario=_clean(item.get("scenario")),
                step_id=step_id if step_id in known else "",
                fix=_clean(item.get("fix")),
            )
        )
    return out


def _form(evidence) -> str:
    """How the claim was checked, when it was more than containment.

    Printed because `claim_within_evidence` is a question about the fit between
    a sentence and its evidence, and a verdict saying FIRST that was verified as
    merely PRESENT is exactly the mismatch it exists to catch. Without this line
    the two are indistinguishable on the page.
    """
    predicate = getattr(evidence, "predicate", None)
    if predicate is None or predicate.form.value == "contains":
        return ""
    where = ""
    if predicate.container is not None:
        name = f' "{predicate.container.name}"' if predicate.container.name else ""
        where = f" of the {predicate.container.role}{name}"
    how_many = f", expecting {predicate.n}" if predicate.n is not None else ""
    return f"  [checked as {predicate.form.value}{where}{how_many}]"


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


__all__ = [
    "CHECKS",
    "JUDGE_BUDGET",
    "JUDGE_TOOLS",
    "Finding",
    "JudgeResult",
    "describe_claims",
    "judge_document",
]
