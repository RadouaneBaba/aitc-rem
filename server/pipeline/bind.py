"""Prove every claim, or delete it.

The drafter writes what it believes the test should check, with no obligation
to have retrieved it first. This is where that debt is called in. For each
proposed expected result there are exactly three outcomes:

    bind        a literal from the recording supports it, and the retrieval
                that produced that literal is recorded against the claim
    revise      the evidence says something adjacent, so the claim is rewritten
                to what was actually observed, and then bound
    unsupported nothing in this run proves it -- **the claim is deleted**

The third is the one that matters. SS9.5 says "an assertion whose evidence
cannot be retrieved is not emitted", and until now that was a validator finding
that a bounded repair loop could run out of budget on, after which the claim
shipped anyway: a wrong quantity reached a real feature file with a warning
recorded beside it in `ir.json`. Deletion here makes that structurally
impossible, because an unbound claim never reaches the renderer to be warned
about.

**The model never supplies a `toolCallId`.** It names a literal it says it saw;
this module then searches the retrievals the agent actually made for one whose
stored response contains that string, and uses that call's id. A fabricated
citation is not something the model is able to express -- if no retrieval it
made contains the literal, the verdict becomes `unsupported` no matter what the
model claimed. SS3.2's guarantee is enforced by construction rather than
checked after the fact.

**Most claims never reach the model at all.** The deterministic pass reads the
evidence at the cited event, finds the string that best supports the claim, and
confirms it with one `find_text` retrieval. That costs no model call. The agent
runs only where the evidence is ambiguous or absent, which is what makes
retrieval effort track difficulty instead of step count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    Assertion,
    Evidence,
    PipelineStage,
    Provenance,
    StepInvestigation,
)
from server.pipeline.investigate import investigate
from server.pipeline.transcribe import supports_narrated
from server.pipeline.validators.base import contains_literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from server.pipeline.draft import DraftedExpectation, DraftedStep, DraftResult

#: Retrievals the binding agent gets for one contested claim. Small on purpose:
#: this is a narrow question -- "does the recording say this, at this event" --
#: and an agent still hunting after six calls has answered it.
BIND_BUDGET = 6

#: How much of the candidate literal the claim has to account for before the
#: deterministic pass will bind it without asking a model. Set where "the
#: basket is full at 5 of 5 items" binds to "5 / 5" and a claim sharing only
#: an article with a heading does not.
COVERAGE_FLOOR = 0.6

#: A literal shorter than this proves nothing. "5" appears on every page that
#: has ever had a number on it, and binding to it would satisfy both grounding
#: validators while meaning nothing at all.
MIN_LITERAL = 3

#: Strings that pass every grounding check and break the moment somebody runs
#: the test. Salvaged from `assertions.NOISE`, which is where this belonged all
#: along: an assertion about a timestamp is perfectly grounded and worthless.
#:
#: The last entry is SS9.5's "ad / analytics containers" exclusion, which the
#: spec asks for and the old NOISE table never implemented -- on a commercial
#: site it is the one that matters, because third-party beacons are where most
#: of the retrievable strings on the page come from.
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
    (
        "an ad or analytics container",
        re.compile(
            r"(googletag|doubleclick|gtm[-_]|adroll|criteo|taboola|outbrain|"
            r"_ga\b|utm_[a-z]+|facebook\.com/tr|hotjar|optimizely|segment\.io)",
            re.IGNORECASE,
        ),
    ),
]

#: Words that carry no meaning on their own. A literal matching a claim only on
#: these has not been supported by anything.
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "then",
    "there",
    "this",
    "to",
    "was",
    "were",
    "when",
    "with",
}

TOKEN = re.compile(r"[a-z0-9£$€%]+", re.IGNORECASE)

#: A value the claim puts in double quotes. The drafter is told to quote the
#: values that MATTER and only those, so a quoted string is the drafter's own
#: statement that this is the checkable content of the sentence.
QUOTED = re.compile(r'"([^"]{1,80})"')

#: Any run of digits in the claim. Numbers are what break when a feature
#: regresses, and a claim carrying one the evidence does not is half-proved at
#: best.
NUMBER = re.compile(r"\d+")

#: A claim whose whole outcome is that a container appeared.
#:
#: SS11.1 and the drafting prompt both forbid these in bold -- "the category
#: page is loaded", "the form is displayed" -- and a bolded prompt line is not
#: an enforcement, which is the lesson `NOISE` already taught. On a real
#: recording the drafter closed a scenario with *the shopping bag panel opens,
#: displaying the item(s) previously added to the cart*, bound to the literal
#: "Shopping Bag" -- the panel's own heading. Perfectly grounded, and evidence
#: that a heading exists.
#:
#: Deliberately narrow: it requires a CONTAINER noun reaching a visibility
#: verb, so "the message ... is shown" and "the application displays an error
#: message indicating that the order requires approval" are untouched. Those
#: are claims about what the application said, which is the thing worth
#: checking; this is a claim about the browser.
EXISTENCE_ONLY = re.compile(
    r"\b(page|panel|form|dialog|modal|screen|view|tab|section|menu|drawer|sidebar)\b"
    r"[^.]{0,40}?\b(open|opens|opened|load|loads|loaded|display|displays|displayed"
    r"|shown|shows|appear|appears|visible|render|renders|rendered)\b",
    re.IGNORECASE,
)


SYSTEM_PROMPT = """\
You are checking whether a recording supports one sentence from a QA test case.

The sentence was written by someone reading a summary of the session. You have
the recording itself. Your job is to find out whether it is true, and to quote
the exact string that shows it.

Answer with ONLY this JSON:

{
  "verdict": "bind" | "revise" | "unsupported",
  "text": "the rewritten sentence -- only for revise",
  "literal": "the exact string you saw, character for character",
  "eventId": "evt_029",
  "kind": "semantic_node" | "url" | "network" | "console" | "narration" | "annotation",
  "reason": "one sentence"
}

* "bind" -- the recording shows this, as written. Quote the string that shows
  it.

* "revise" -- **the step did produce a checkable outcome, and the sentence
  describes it wrongly.** A quantity that reached 18 where the sentence says
  15; a control with a different name; the right event described in the wrong
  words. Rewrite the sentence to say what the evidence actually says, and quote
  that.

  This is the answer whenever you can see what the step really did. If the
  sentence says "Cart contains 1 items" and the page said "Blue Widget added to
  cart", that is a `revise` to what the page said -- not an `unsupported`. The
  step has an outcome; the drafter only guessed at its wording, which is
  exactly the mistake this stage exists to correct. Deleting there throws away
  a real expected result and leaves the scenario with no verdict at all.

* "unsupported" -- **nothing this step did supports any version of this claim.**
  The outcome is not in the recording, or it belongs to a different step
  entirely. Say so, and the claim is dropped. Do NOT stretch to make something
  fit: a wrong claim that ships is the most expensive thing this tool can
  produce.

Between `revise` and `unsupported`, ask: did this step produce ANY outcome a
person could check? If yes, revise to it. If no, it is unsupported.

RULES ON THE LITERAL

* It must be a string you actually saw in a tool response during THIS
  investigation. Copy it exactly -- character for character, including case,
  punctuation and spacing. It is checked against what the tools returned, and a
  literal that does not appear in one of your own retrievals makes the claim
  unsupported however true the sentence is.
* Do not quote a timestamp, a date, a uuid, a generated id, or anything from an
  advertising or analytics payload. Those are grounded and worthless: they
  break the first time somebody runs the test.
* Quote the most specific thing that supports the claim. "Priority delivery"
  beats "delivery"; "18 / 18" beats "18".

* **The literal must cover everything the sentence CHECKS, not just enough of
  it to look supported.** Every value the sentence puts in quotes, and every
  number in it, has to be in the string you quote. A sentence that checks two
  things needs evidence for both.
      claim    the plan is shown as "Team" with "12" seats remaining
      BAD      literal "Team"                     ("12" is unproved)
      GOOD     literal "Team - 12 seats remaining"
      GOOD     revise to *the plan is shown as "Team"*,
               literal "Team"
  If one retrieval covers the whole sentence, bind. If none does, `revise` the
  sentence down to the part you can actually prove -- that is better than
  binding a half of it, and far better than dropping it. This is checked, and
  a literal missing a quoted value or a number makes the claim unsupported.

* A claim that some part of the interface APPEARED -- a page loading, a panel
  opening, a form being displayed -- checks the browser rather than the
  application, and is refused whatever you quote for it. If the step really did
  produce nothing else, say `unsupported`.
* Prefer what was on the PAGE. If the tester said the expected result out loud,
  that tells you WHICH outcome matters -- but a transcript is a reconstruction
  and can mis-hear a number, so bind to what the page showed, not to what the
  transcript says.

Retrieve before answering. `get_snapshot` for what was on screen, `get_diff`
for what changed, `find_text` for where a string really appears, `get_network`
and `get_console` for requests and errors.
"""


USER_PROMPT = """\
The step: {step}

The sentence to check: {claim}

It is claimed to have become true at {event_id}.
{context}

Is this true, and what exactly shows it?
"""


# --------------------------------------------------------------------------
# result
# --------------------------------------------------------------------------


@dataclass
class BoundClaim:
    """One proposal, and what happened to it."""

    step_id: str
    text: str
    verdict: str
    assertion: Assertion | None = None
    #: Why it was dropped or rewritten, in a sentence. Recorded whatever the
    #: outcome, because "why is there no expected result on this step" is a
    #: question a reviewer will ask, and a silent deletion cannot answer it.
    reason: str = ""
    original: str = ""
    tool_call_ids: list[str] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    model_calls: list = field(default_factory=list)


@dataclass
class BindResult:
    claims: list[BoundClaim] = field(default_factory=list)
    investigations: list[StepInvestigation] = field(default_factory=list)
    #: Model turns spent settling contested claims. Zero when every claim the
    #: drafter proposed was plainly supported at the event it cited, which is
    #: the common case and the point of the deterministic pass.
    model_calls: list = field(default_factory=list)

    @property
    def bound(self) -> int:
        return sum(1 for c in self.claims if c.assertion is not None)

    @property
    def deleted(self) -> int:
        return sum(1 for c in self.claims if c.assertion is None)

    def for_step(self, step_id: str) -> list[Assertion]:
        """The assertions this step ships, one per proposal at most.

        **`claims` is a history and this is a selection, and conflating them
        put the same sentence in the artifact twice.** `run._second_chance`
        re-proposes for a verdictless scenario and then re-binds, prepending the
        first attempt's claims so a reviewer asking "why is there no expected
        result here" can see what was tried. But re-binding runs over the WHOLE
        document, so every step that had already bound cleanly bound again --
        and assembly read the merged list and emitted both.

        Shipped on a real recording: `Then the product list is filtered to show
        only available items` immediately followed by `And the product list is
        filtered to show only available items`, on the same step, differing only
        in the evidence behind them. `merge_repeats` folds duplicate STEPS and
        never looked at this.

        Keyed on the drafter's ORIGINAL sentence rather than the final one,
        because a `revise` legitimately changes the text and is still the same
        proposal answered twice. Last wins: the later attempt is the one made
        with the reason the first failed in front of it.
        """
        latest: dict[str, Assertion] = {}
        for claim in self.claims:
            if claim.step_id != step_id or claim.assertion is None:
                continue
            latest[claim.original or claim.text] = claim.assertion
        return list(latest.values())

    def to_artifact(self) -> dict[str, Any]:
        return {
            "bound": self.bound,
            "deleted": self.deleted,
            "claims": [
                {
                    "stepId": c.step_id,
                    "verdict": c.verdict,
                    "text": c.text,
                    **({"original": c.original} if c.original and c.original != c.text else {}),
                    "reason": c.reason,
                    "toolCallIds": list(c.tool_call_ids),
                    **(
                        {
                            "literal": c.assertion.evidence.literal,
                            "toolCallId": c.assertion.evidence.toolCallId,
                            "eventId": c.assertion.evidence.eventId,
                            "provenance": c.assertion.provenance.value,
                        }
                        if c.assertion is not None
                        else {}
                    ),
                }
                for c in self.claims
            ],
        }


# --------------------------------------------------------------------------
# the stage
# --------------------------------------------------------------------------


def bind_claims(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    *,
    model_name: str,
    budget: int = BIND_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> BindResult:
    """Bind, revise or delete every expected result the drafter proposed."""
    config = config or ProjectConfig()
    out = BindResult()

    for step in drafted.steps:
        for index, expectation in enumerate(step.expects, start=1):
            claim = _bind_one(
                store,
                runner,
                model,
                step,
                expectation,
                index=index,
                model_name=model_name,
                budget=budget,
                tools_enabled=tools_enabled,
                temperature=temperature,
                config=config,
            )
            out.claims.append(claim)
            if claim.investigation is not None:
                out.investigations.append(claim.investigation)
            out.model_calls.extend(claim.model_calls)

    return out


def _bind_one(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    step: DraftedStep,
    expectation: DraftedExpectation,
    *,
    index: int,
    model_name: str,
    budget: int,
    tools_enabled: bool,
    temperature: float,
    config: ProjectConfig,
) -> BoundClaim:
    assertion_id = f"asrt_{step.step_id.split('_')[-1]}_{index}"

    # A0 has NO retrieval, and that has to mean none at all -- SS3.5 defines it
    # as "single prompt, all context pre-loaded, no tools", and the whole point
    # of the row is SS3.2's claim that without retrieval a model cannot ground
    # anything. The deterministic pass below is cheap and needs no model, but it
    # still calls a tool, stores a response and hashes it. Letting it run under
    # A0 gave that configuration three grounded assertions and 0.33 calls per
    # step in the ablation table -- a "no tools" row that had made retrievals.
    #
    # So A0 emits nothing, which is not a degradation but the measurement: this
    # architecture cannot express an ungrounded claim, so a configuration that
    # may not retrieve has nothing it can honestly say.
    if not tools_enabled:
        return BoundClaim(
            step_id=step.step_id,
            text=expectation.text,
            verdict="unsupported",
            reason="no retrieval is available in this configuration, so nothing can support "
            "this claim",
        )

    # 0. A claim about the browser is refused before anything is retrieved.
    #    No literal can rescue it and no agent can improve it, so spending a
    #    call would be spending it to arrive here anyway. `run._second_chance`
    #    re-asks when this leaves a scenario with no verdict, which is the
    #    right outcome: the step deserves a real one.
    browser = _existence_only(expectation.text)
    if browser:
        return BoundClaim(
            step_id=step.step_id,
            text=expectation.text,
            original=expectation.text,
            verdict="unsupported",
            reason=browser,
        )

    # 1. The cheap pass. Read what is actually at the cited event, find the
    #    string that best accounts for the claim, and retrieve the thing it
    #    came from. Most claims end here, having cost no model call.
    #
    #    `_unwitnessed` is the second gate on it, and it is the one that asks
    #    the question `COVERAGE_FLOOR` does not: does this literal witness what
    #    the claim actually CHECKS? A claim quoting a value the evidence does
    #    not contain is not settled cheaply -- it goes to the agent, which can
    #    find a literal covering the whole sentence or `revise` the sentence
    #    down to what it can prove.
    found = _best_literal(store, expectation.event_id, expectation.text)
    if found is not None and found.conclusive:
        gap = _unwitnessed(expectation.text, found.literal)
        if gap is None:
            bound = _bind_deterministically(
                store, runner, step, expectation, found, assertion_id=assertion_id, config=config
            )
            if bound is not None:
                return bound

    # 2. The contested pass. Nothing at the cited event obviously supports the
    #    claim, so it becomes a question worth an agent's time.

    result = investigate(
        runner,
        model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=USER_PROMPT.format(
            step=step.text,
            claim=expectation.text,
            event_id=expectation.event_id,
            context=_context(store, expectation.event_id),
        ),
        model_name=model_name,
        stage=PipelineStage.assert_,
        label=f"bind_{step.step_id}_{index}",
        budget=budget,
        tools_enabled=tools_enabled,
        temperature=temperature,
        step_id=step.step_id,
    )

    investigation = result.record(
        investigation_id=f"inv_bind_{step.step_id}_{index}",
        stage=PipelineStage.assert_,
        budget=budget,
        step_id=step.step_id,
    )

    claim = _from_answer(
        store,
        runner,
        result.answer,
        step=step,
        expectation=expectation,
        assertion_id=assertion_id,
        tool_call_ids=result.tool_call_ids,
        investigation=investigation,
        config=config,
    )
    claim.model_calls = list(result.model_calls)
    return claim


def _from_answer(
    store: EvidenceStore,
    runner: ToolRunner,
    answer: dict[str, Any],
    *,
    step: DraftedStep,
    expectation: DraftedExpectation,
    assertion_id: str,
    tool_call_ids: list[str],
    investigation: StepInvestigation | None,
    config: ProjectConfig,
) -> BoundClaim:
    """Turn the agent's verdict into an assertion, or into a deletion.

    Everything the model said is treated as a proposal to be checked, including
    its verdict. `bind` with a literal nothing retrieved supports is not a bind.
    """
    base = BoundClaim(
        step_id=step.step_id,
        text=expectation.text,
        original=expectation.text,
        verdict="unsupported",
        tool_call_ids=list(tool_call_ids),
        investigation=investigation,
    )

    verdict = str(answer.get("verdict") or "").strip().lower()
    reason = " ".join(str(answer.get("reason") or "").split())[:240]

    if verdict not in {"bind", "revise"}:
        base.reason = reason or "the agent could not find evidence for this claim"
        return base

    literal = str(answer.get("literal") or "")
    if len(literal.strip()) < MIN_LITERAL:
        base.reason = reason or "the agent quoted nothing specific enough to check"
        return base

    noise = _noise(literal)
    if noise:
        base.reason = f"the only evidence offered was {noise}, which does not survive a re-run"
        return base

    # The sentence the agent is answering about, which is its OWN on a revise.
    # Checked here as well as in the deterministic pass because the prompt
    # asking for it is not a guarantee -- the same reason `critic._collect` and
    # `repair.targets` both enforce the protected-step rule. An agent handed a
    # two-part claim will quote the part it found and call the verdict `bind`.
    proposed = " ".join(str(answer.get("text") or "").split()) if verdict == "revise" else ""
    checked = proposed or expectation.text

    browser = _existence_only(checked)
    if browser:
        base.reason = browser
        return base

    own = _own_input(store, literal, expectation.event_id)
    if own:
        base.reason = own
        return base

    gap = _unwitnessed(checked, literal)
    if gap:
        base.reason = (
            f"{gap}, so {literal[:40]!r} proves only part of this claim. Revise the "
            f"sentence to what the evidence shows, or drop it."
        )
        return base

    # The model named a string; this finds the retrieval that contains it. If
    # none of the agent's own calls do, the claim is unsupported however
    # confident the verdict was. This is the point at which fabrication stops
    # being possible rather than merely being detected.
    call_id = _resolve_call(runner, tool_call_ids, literal)
    if call_id is None:
        base.reason = (
            f"{literal[:60]!r} does not appear in any response this agent received, "
            f"so nothing it retrieved supports the claim"
        )
        return base

    event_id = str(answer.get("eventId") or expectation.event_id)
    if not store.has_event(event_id):
        event_id = expectation.event_id

    # `assertion_grounding` will re-check this independently against the
    # recording, so a citation that points at the wrong event is caught either
    # way. Checking it here means the claim is dropped with an explanation
    # rather than surviving to be rejected by the gate with nothing to do
    # about it.
    if not store.contains_at(literal, event_id, case_sensitive=True):
        elsewhere = store.events_containing(literal, case_sensitive=True)
        if len(elsewhere) == 1:
            # It is real, it is just somewhere else. Re-pointing is safe --
            # the literal and the retrieval are unchanged, only the event this
            # claim says it became true at.
            event_id = elsewhere[0]
        else:
            base.reason = f"{literal[:60]!r} does not appear at {event_id}" + (
                f" (it appears at {', '.join(elsewhere[:4])})" if elsewhere else " at all"
            )
            return base

    text = checked
    base.text = text
    base.verdict = verdict
    base.reason = reason or "bound to a retrieval made during this run"
    base.assertion = _assertion(
        assertion_id,
        text,
        literal=literal,
        tool_call_id=call_id,
        event_id=event_id,
        kind=str(answer.get("kind") or "semantic_node"),
        provenance=_provenance_for(store, step, config),
    )
    return base


# --------------------------------------------------------------------------
# the deterministic pass
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    """A string at an event, and how to go and retrieve it."""

    literal: str
    kind: str
    tool: str
    args: dict[str, Any]
    #: True when this string is the name or the value of the control the tester
    #: OPERATED at this event -- the option they chose, the box they ticked.
    #: See `conclusive`.
    is_own_input: bool = False

    @property
    def conclusive(self) -> bool:
        """Is this strong enough to settle the claim without asking anyone?

        A literal made of one bare number is not. "5 / 5" genuinely supports
        "the basket is full at 5 of 5 items" -- and it would equally "support"
        *the quantity of the tea selection increases to 5*, which is about
        something else entirely. Both share exactly one token with the
        candidate, so no amount of scoring separates them: this is the line
        where provenance stops being able to speak for correctness.

        So the cheap pass declines, and the claim becomes a question for an
        agent that can look at what the number was counting. That is effort
        landing on the hard claims and not on the easy ones, which is the whole
        argument for retrieval being adaptive rather than scheduled.

        **An expected result bound to the tester's own input is not evidence
        of an outcome**, and the deterministic pass cannot tell the difference
        by scoring. On a real recording of a French storefront:

            claim:   the product list updates to show lower-priced items first
            literal: "Prix bas a haut"

        which is the option the tester had just selected in the sort dropdown.
        Perfectly grounded evidence that the dropdown says what they set it to,
        and it would read identically if the list came back sorted the wrong
        way. It is `Export the order` again -- the label on the button the
        tester had just pressed -- reaching the candidate set through a door
        `_changed_at` cannot close, because choosing an option really does
        change the page.

        So this declines, and the claim becomes a question for an agent that
        can look at the list itself. Declining rather than REFUSING is the
        point: "the quantity field shows 3" after typing 3 is a thin test but
        not a false one, and the agent is the thing that can tell those apart.
        """
        if self.is_own_input:
            return False
        content = _tokens(self.literal) - STOPWORDS
        if len(content) >= 2:
            return True
        return any(len(t) >= 4 and not t.isdigit() for t in content)


def _own_input(store: EvidenceStore, literal: str, event_id: str) -> str | None:
    """Refuse a claim resting on the control the tester OPERATED at this event.

    The tester's input is not evidence of an outcome. Observed on a real
    recording of a French storefront, bound by the agent and past the whole
    gate:

        claim:   the product list updates to show lower-priced items first
        literal: "Prix bas a haut"

    which is the option they had just chosen in the sort dropdown. It proves
    the dropdown says what they set it to, and it would read identically if the
    list came back sorted the wrong way -- the one failure the step exists to
    catch.

    **The agent had the discriminating evidence and cited the other thing.** Its
    own recorded reason was *"The URL changed to include 'order:ASC' (ascending
    price) and the combobox value..."*: it found `order:ASC`, reasoned about it
    correctly, and then quoted the label. So this is not a retrieval failure and
    no amount of extra budget fixes it; refusing sends the claim back with the
    reason, and what it can bind to instead is already in the candidate set.

    Checked on the agent's answer as well as in the deterministic pass -- where
    `_Candidate.conclusive` merely DECLINES, because "the quantity field shows
    3" after typing 3 is thin but not false, and only something reading the page
    can tell those apart. Same two-tier shape as `_unwitnessed`, for the same
    reason: a prompt that asks is not a guarantee.
    """
    if not store.has_event(event_id):
        return None
    target = store.event(event_id).target
    key = _key(literal)
    if not key:
        return None
    if key not in {_key(target.name), _key(getattr(target, "value", None))}:
        return None
    return (
        f"{literal[:40]!r} is what the tester selected or entered at this event, not what "
        f"the application did with it. Quote what CHANGED instead"
    )


def _unwitnessed(claim: str, literal: str) -> str | None:
    """Checkable content in the claim that the literal does not contain.

    **`COVERAGE_FLOOR` asks how much of the LITERAL the claim accounts for.
    Nothing asked the reverse, and the reverse is the guarantee.** A claim is
    admissible only if it can point at the retrieval that produced it -- so a
    sentence making two assertions and pointing at evidence for one of them is
    half inadmissible, and the half nobody looked at is free to be wrong.

    Observed, on a real run and passing the whole gate:

        claim:   the hamper is shown as a "Small Wicker Basket" with a
                 capacity of "5 / 5"
        literal: Small Wicker Basket

    `"5 / 5"` is the entire numeric content of that sentence -- the one part a
    broken capacity counter would break -- and nothing proved it. Both
    grounding validators passed, because both were asked about the literal.

    `_Candidate.conclusive` exists to stop exactly this and cannot see it: it
    declines a claim resting on a BARE number, and a conjunction slips past by
    giving it something else to rest on. Three content tokens, coverage 1.0,
    bound without a model call.

    So: what the claim QUOTES and what it NUMBERS must appear in the evidence.
    Both are the drafter's own marks for "this is the part that matters" --
    the drafting prompt asks for quotes on the values that identify the case,
    and a digit is checkable by construction. Prose framing is untouched, which
    is why "the system displays an error message indicating that the order
    requires approval" still binds to "Orders over EUR500 require approval":
    the extra words there assert nothing new.

    Returns the description of what was missing, or None when the literal
    witnesses everything checkable in the claim.
    """
    hay = " ".join(literal.split()).casefold()

    missing = [
        f'"{value}"'
        for value in QUOTED.findall(claim)
        if " ".join(value.split()).casefold() not in hay
    ]
    if missing:
        return f"the evidence does not contain {', '.join(missing[:3])}"

    # Numbers are checked against the literal's own digits rather than as
    # substrings: "1" is in "18" and proves nothing about it.
    present = set(NUMBER.findall(literal))
    absent = [n for n in NUMBER.findall(claim) if n not in present]
    if absent:
        plural = "s" if len(absent) > 1 else ""
        return f"the evidence does not contain the number{plural} {', '.join(absent[:3])}"

    return None


def _existence_only(claim: str) -> str | None:
    """Is this a claim that a container appeared, and nothing else?

    Only when the sentence carries no other checkable content. "the payment
    panel shows a total of "615"" is about the total; the container noun is
    incidental to it, and the quoted value is checked like any other.
    """
    if not EXISTENCE_ONLY.search(claim):
        return None
    if QUOTED.search(claim) or NUMBER.search(claim):
        return None
    return (
        "this asserts that part of the interface appeared, which checks the browser "
        "rather than the application"
    )


def _bind_deterministically(
    store: EvidenceStore,
    runner: ToolRunner,
    step: DraftedStep,
    expectation: DraftedExpectation,
    found: _Candidate,
    *,
    assertion_id: str,
    config: ProjectConfig,
) -> BoundClaim | None:
    """Retrieve the thing the literal came from, and bind the claim to it.

    The retrieval is `get_snapshot` or `get_console` -- never `find_text`.
    `find_text` echoes its own query back in the response, so an assertion
    citing one would satisfy `evidence_retrieved` no matter what the recording
    said: the literal is in the response because it was in the REQUEST. Binding
    to a snapshot means the string is in the response because it was on the
    page, which is the thing SS3.2 is actually asking about.
    """
    call_id, response = runner.call(
        found.tool,
        found.args,
        step_id=step.step_id,
        stage=PipelineStage.assert_,
    )
    if not contains_literal(response, found.literal):
        return None

    # Recorded as an investigation even though nothing was investigated. The
    # retrieval is real -- it cost a call and it is what the claim cites -- and
    # a stage that does not add itself to the trace is a stage that costs quota
    # invisibly, which is how `toolCallsTotal` came to exclude composition.
    # `no_investigation_needed` is the honest stop reason: the evidence was
    # already sufficient and one call confirmed it, and `run._calls_per_step`
    # reads exactly that to keep this mandatory call out of SS3.4's effort
    # column. It is one call out of one allowed, not one out of zero: the review
    # UI and the sidecar both render "used N of M" and were printing "1 of 0".
    investigation = StepInvestigation(
        id=f"inv_bind_{step.step_id}_{assertion_id.rsplit('_', 1)[-1]}",
        stage=PipelineStage.assert_,
        stepId=step.step_id,
        initialUncertainty=[],
        toolCallIds=[call_id],
        budgetUsed=1,
        budgetMax=1,
        stopReason="no_investigation_needed",
        narrative=[f"{found.tool}({found.args.get('eventId', '')}) -> {call_id}"],
    )

    return BoundClaim(
        step_id=step.step_id,
        text=expectation.text,
        verdict="bind",
        reason="the recording shows this at the cited event",
        tool_call_ids=[call_id],
        investigation=investigation,
        assertion=_assertion(
            assertion_id,
            expectation.text,
            literal=found.literal,
            tool_call_id=call_id,
            event_id=expectation.event_id,
            kind=found.kind,
            provenance=_provenance_for(store, step, config),
        ),
    )


def _best_literal(store: EvidenceStore, event_id: str, claim: str) -> _Candidate | None:
    """The string at this event that best accounts for the claim.

    Derived from the evidence and then matched against the claim, never the
    other way round. Extracting a candidate from the claim's own words would
    happily "confirm" a sentence the recording never supported, which is the
    failure mode this whole module exists to close.
    """
    if not store.has_event(event_id):
        return None

    wanted = _tokens(claim)
    if not wanted:
        return None

    best: tuple[float, int] = (0.0, 0)
    chosen: _Candidate | None = None

    for candidate in _candidates(store, event_id):
        literal = candidate.literal
        if len(literal) < MIN_LITERAL or _noise(literal):
            continue
        tokens = _tokens(literal)
        if not tokens:
            continue

        shared = tokens & wanted
        if not (shared - STOPWORDS):
            continue
        coverage = len(shared) / len(tokens)
        if coverage < COVERAGE_FLOOR:
            continue

        # `assertion_grounding` will independently require the literal to be
        # findable at this event, so anything that would fail there is dropped
        # here instead of being bound and then rejected by the gate.
        if not store.contains_at(literal, event_id, case_sensitive=True):
            continue

        # Coverage first, then specificity: a literal the claim fully accounts
        # for is a better witness than one it half accounts for, and among
        # equals the longer one says more. "Large Wicker Basket" beats "Basket".
        score = (round(coverage, 3), len(tokens))
        if score > best:
            best, chosen = score, candidate

    return chosen


def _candidates(store: EvidenceStore, event_id: str) -> list[_Candidate]:
    """Every string at this event that a claim could honestly rest on.

    Each one carries the retrieval that produces it, so binding never has to
    guess where a literal came from.
    """
    out: list[_Candidate] = []
    seen: set[str] = set()
    event = store.event(event_id)

    # What the tester operated at this event: the option they chose, the box
    # they ticked, the field they filled. A claim resting on one of these is
    # resting on the INPUT, not on what the application did with it -- see
    # `_Candidate.conclusive`.
    own = {_key(v) for v in (event.target.name, getattr(event.target, "value", None)) if _key(v)}

    def add(value: str | None, kind: str, tool: str, args: dict[str, Any]) -> None:
        text = " ".join((value or "").split())
        if text and text not in seen:
            seen.add(text)
            out.append(
                _Candidate(
                    literal=text,
                    kind=kind,
                    tool=tool,
                    args=args,
                    is_own_input=_key(text) in own,
                )
            )

    # **An expected result is about what CHANGED.**
    #
    # Without this the cheap pass will bind a claim to any string on the page
    # that shares enough words with it, and the page is full of them. It bound
    # "a file containing the order details is downloaded" to `Export the order`
    # -- the label on the button the tester had just pressed, present before
    # the click and unchanged by it. Two shared words, a clean grounding trail,
    # and evidence of nothing: the export had in fact returned a 500.
    #
    # A claim can legitimately be about state that persisted ("the total is
    # still EUR615"), which is why this restricts only the DETERMINISTIC pass.
    # When nothing that changed supports the claim, it goes to the agent, which
    # can read the whole page and say what actually happened. Declining to
    # answer cheaply is the correct behaviour there; guessing is not.
    fresh = _changed_at(event)

    # `transient` needs its own test rather than the diff. The diff runs
    # between `before` and `after`, so a toast that appeared and vanished
    # inside the settle window is in neither -- which is the whole reason a
    # transient snapshot is taken at all (SS6.2), and filtering it by the diff
    # would discard exactly the evidence it exists to preserve.
    #
    # But a transient snapshot is a scoped snapshot of the PAGE, not of the
    # toast: at the moment the alert appeared, the form around it was captured
    # too. So the test is "was it there beforehand", and the answer for the
    # button the tester had just pressed is yes.
    before = {_key(n.name) for n in store.nodes(event_id, "before")}
    before |= {_key(n.value) for n in store.nodes(event_id, "before")}
    transient_args = {"eventId": event_id, "when": "transient"}
    for node in store.nodes(event_id, "transient"):
        for value in (node.name, node.value):
            if _key(value) and _key(value) not in before:
                add(value, "semantic_node", "get_snapshot", transient_args)

    after_args = {"eventId": event_id, "when": "after"}
    for node in store.nodes(event_id, "after"):
        for value in (node.name, node.value):
            if _key(value) in fresh:
                add(value, "semantic_node", "get_snapshot", after_args)

    if event.diff.titleChanged is not None:
        add(event.after.title, "semantic_node", "get_snapshot", after_args)
    if event.diff.urlChanged is not None:
        add(event.url, "url", "get_snapshot", after_args)

    for entry in event.console:
        add(entry.text, "console", "get_console", {"eventId": event_id})

    # What the tester pointed at, which SS9.5 ranks above everything the
    # pipeline can infer. `find_text` indexes annotations, so one can ground a
    # claim -- and `get_events` is the retrieval that returns it, which is why
    # the event's INDEX is needed rather than its id.
    index = next(
        (i for i, e in enumerate(store.events_in_range(None, None)) if e.id == event_id), None
    )
    if index is not None:
        events_args = {"start": index, "end": index}
        for annotation in event.annotations or []:
            add(annotation.text, "annotation", "get_events", events_args)
            if annotation.target:
                add(annotation.target.name, "annotation", "get_events", events_args)
                add(annotation.target.value, "annotation", "get_events", events_args)

    return out


def _changed_at(event: Any) -> set[str]:
    """Text that this action put on the page or altered.

    Read from the diff the recorder computed at capture time (SS6.2), so
    nothing is re-derived and the answer is the same one every other stage
    sees.
    """
    fresh: set[str] = set()
    for node in event.diff.added:
        fresh.add(_key(getattr(node, "name", None)))
        fresh.add(_key(getattr(node, "value", None)))
    for change in event.diff.changed:
        fresh.add(_key(getattr(change.after, "name", None)))
        fresh.add(_key(getattr(change.after, "value", None)))
    fresh.discard("")
    return fresh


def _key(value: str | None) -> str:
    return " ".join((value or "").split())


def _resolve_call(runner: ToolRunner, tool_call_ids: list[str], literal: str) -> str | None:
    """Which of the agent's own retrievals contains this string?

    Read back from the stored response rather than from anything the model
    said, and read in reverse: when several retrievals contain the literal the
    most recent one is the one the agent was looking at when it answered.
    """
    by_id = {call.id: call for call in runner.calls}
    for call_id in reversed(tool_call_ids):
        try:
            stored = runner.storage.load_tool_response(runner.run, call_id)
        except OSError:
            continue
        call = by_id.get(call_id)
        if _response_supports(stored, getattr(call, "tool", ""), literal):
            return call_id
    return None


def _response_supports(stored: Any, tool: str, literal: str) -> bool:
    """Does this response contain the literal because the RECORDING does?

    `find_text` echoes its query back, so `contains_literal` on its raw
    response is true for any string whatsoever -- the literal is present
    because it was in the request, not because anything was found. An agent
    that searched for a phrase it invented and then cited the search would
    satisfy `evidence_retrieved` perfectly, which is precisely the fabrication
    SS3.2 exists to make impossible.
    """
    if tool == "find_text" and isinstance(stored, dict):
        stored = {key: value for key, value in stored.items() if key != "query"}
    return contains_literal(stored, literal)


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def _provenance_for(store: EvidenceStore, step: DraftedStep, config: ProjectConfig) -> Provenance:
    """The best rank this step can honestly claim (SS9.5).

    Verified against the recording rather than asked of the model, for the same
    reason noise suppression is code: a claim about where a claim came from is
    load-bearing, and `annotated` costs a model nothing but the word.

    This must agree with `provenance_supported` in `validators/grounding.py`.
    They are two readings of one rule and a divergence between them shows up as
    a validator rejecting its own pipeline's output.
    """
    for candidate in _supported_provenance(store, step, config.narration_min_confidence):
        return candidate
    return Provenance.inferred


def _supported_provenance(
    store: EvidenceStore, step: DraftedStep, min_confidence: float
) -> list[Provenance]:
    """The ladder, best first, filtered to what this step can support."""
    events = [store.event(e) for e in step.event_ids if store.has_event(e)]
    if not events:
        return [Provenance.inferred]

    first, last = events[0].timestamp, events[-1].timestamp + 2000
    out: list[Provenance] = []

    # An outcome annotation lands AFTER the thing it points at, which is why
    # the window runs past the last event rather than stopping at it.
    if any(
        a.kind.value == "assertion" for e in events for a in (e.annotations or [])
    ) or store.annotations(first, last, kind="assertion"):
        out.append(Provenance.annotated)

    # Narration is the only lossy source in the system: everything else is read
    # exactly and a transcript is a reconstruction. A segment the transcriber
    # was unsure of must not outrank an honest inference, or a mis-heard number
    # becomes a claim that passes both grounding validators and is still false.
    if any(supports_narrated(s, min_confidence) for s in store.narration(first, last)):
        out.append(Provenance.narrated)

    if store.objective:
        out.append(Provenance.objective)

    out.append(Provenance.inferred)
    return out


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _assertion(
    assertion_id: str,
    text: str,
    *,
    literal: str,
    tool_call_id: str,
    event_id: str,
    kind: str,
    provenance: Provenance,
) -> Assertion:
    kinds = {"semantic_node", "url", "network", "console", "narration", "annotation", "a11y_node"}
    return Assertion(
        id=assertion_id,
        text=text,
        provenance=provenance,
        evidence=Evidence(
            literal=literal,
            toolCallId=tool_call_id,
            eventId=event_id,
            kind=kind if kind in kinds else "semantic_node",
        ),
        # Accepted, because everything that reaches here has been proved. The
        # old pipeline proposed two or three candidates per step and accepted
        # the best; this stage is handed the one claim the author thought worth
        # making and decides only whether it holds.
        accepted=True,
        rank=1,
    )


def _context(store: EvidenceStore, event_id: str) -> str:
    if not store.has_event(event_id):
        return ""
    event = store.event(event_id)
    target = (event.target.name or event.target.role or "").strip()
    lines = [f"That event is: {event.type.value}" + (f' on "{target}"' if target else "")]
    if store.objective:
        lines.append(f"The tester's stated objective: {store.objective}")
    return "\n" + "\n".join(lines) + "\n"


def _noise(literal: str) -> str:
    for reason, pattern in NOISE:
        if pattern.search(literal):
            return reason
    return ""


def _tokens(text: str) -> set[str]:
    return {m.group(0).casefold() for m in TOKEN.finditer(text or "")}


__all__ = [
    "BIND_BUDGET",
    "NOISE",
    "BindResult",
    "BoundClaim",
    "bind_claims",
]
