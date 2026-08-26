"""Is this one test case, or several? (SS9.3, Decision A)

    "Real QA sessions are not one clean scenario. A tester opens the app and
     works for fifteen minutes across several flows, gets lost twice, and
     backtracks. A verbatim transcript of that is a bad test case, and it is the
     fastest route to output that feels disposable."

The drafter already answers this: it returns `scenarios`, it names them, and it
is told in bold that a scenario is ONE behaviour with ONE verdict. It has
answered "one" thirteen times out of thirteen. On the one recording in `runs/`
long enough for the question to be hard -- 34 events, three hamper-size upgrade
behaviours -- the critic diagnosed it exactly, in one sentence, and nothing
happened: `coherence` has no repair route, and cannot have one, because
re-drafting can change the step COUNT and SS3.6 promises it does not.

So this asks the question separately, and answers it in the only way that keeps
that promise: **by regrouping steps that already exist.** No step is added,
removed, reordered or re-worded, and no `step_id` or `eventId` moves. The model
proposes a partition; the code takes it whole or discards it whole.

Two things make the cost bounded. The trigger is deterministic, so a well-shaped
document never reaches the model at all -- none of the seven fixtures does. And
"one group" is a complete and correct answer, which is what a scenario that is
long because the behaviour is long deserves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import ModelCall, PipelineStage, SegmentRole, StepInvestigation
from server.pipeline.draft import DraftedScenario, DraftResult
from server.pipeline.investigate import investigate
from server.pipeline.narrative import normalise
from server.pipeline.validators.style import MAX_BEATS

#: A scenario carrying more events than this is worth one model call.
#:
#: Measured, not chosen. Across all 13 runs in `runs/`, the largest scenario a
#: well-shaped recording produced is 10 events (`checkout`, `hardpaths`); the
#: recording this whole stage exists for is 34. The separation is 10 against 34
#: and the number sits inside it with headroom on both sides -- no fixture
#: reaches it, so the fixture suite costs nothing and does not churn.
#:
#: 12 rather than 11 or 20 because SS9.2 already uses it: the segmenter's hard
#: cap is 12 events, the point at which it stops believing a run of events is
#: one intent's worth of work. A SCENARIO past that number has, by the project's
#: own arithmetic, stopped being one behaviour.
#:
#: Deliberately NOT imported from `segment.py`. The two agree by argument rather
#: than by dependency, and coupling them would let a segmentation tweak silently
#: change what gets split.
SPLIT_EVENT_FLOOR = 12

#: Small on purpose. This is a partition question about a document that has
#: already been written, not an investigation of the recording from scratch --
#: the same argument as `CRITIC_BUDGET`.
SPLIT_BUDGET = 4


@dataclass(frozen=True)
class Group:
    name: str
    step_ids: list[str]


@dataclass
class SplitDecision:
    """What happened to one candidate scenario, and why.

    "Why is this one scenario" must always have an answer, including when the
    answer is "nobody asked". A stage that silently declines is a stage whose
    output cannot be told apart from a stage that never ran.
    """

    scenario: str
    step_ids: list[str]
    reason: str
    groups: list[Group] = field(default_factory=list)
    refused: str = ""
    investigation: StepInvestigation | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "scenario": self.scenario,
            "stepIds": list(self.step_ids),
            "trigger": self.reason,
            "groups": [{"name": g.name, "stepIds": list(g.step_ids)} for g in self.groups],
        }
        if self.refused:
            out["refused"] = self.refused
        return out


@dataclass
class SplitResult:
    decisions: list[SplitDecision] = field(default_factory=list)
    investigations: list[StepInvestigation] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    #: Why the stage did not run, when it did not. "Nothing needed splitting"
    #: and "the splitter was switched off" are different facts about a run.
    failed: str = ""

    @property
    def scenarios_added(self) -> int:
        return sum(max(0, len(d.groups) - 1) for d in self.decisions)

    def to_artifact(self) -> dict[str, Any]:
        return {
            "decisions": [d.as_dict() for d in self.decisions],
            "scenariosAdded": self.scenarios_added,
            **({"failed": self.failed} if self.failed else {}),
        }


def candidates(drafted: DraftResult) -> list[tuple[int, str]]:
    """Which scenarios are worth asking about, and what tripped the trigger.

    A disjunction, and it has to be. The flagship failure -- three upgrade
    behaviours under one heading -- has THREE beats, under `MAX_BEATS`, so a
    beats-only trigger misses the case this exists for. And a scenario can reach
    five beats in ten events, which the event floor alone misses. Either signal
    is enough.

    Deterministic, so it costs nothing on a document that does not need it and
    the same recording always asks the same question.
    """
    out: list[tuple[int, str]] = []
    for index, scenario in enumerate(drafted.scenarios):
        if len(scenario.steps) < 2:
            continue
        events = len({e for step in scenario.steps for e in step.event_ids})
        beats = count_beats(scenario)
        if beats > MAX_BEATS:
            out.append((index, f"{beats} action/outcome blocks, over the limit of {MAX_BEATS}"))
        elif events > SPLIT_EVENT_FLOOR:
            out.append((index, f"{events} events in one scenario, over the floor of "
                               f"{SPLIT_EVENT_FLOOR}"))
    return out


def count_beats(scenario: DraftedScenario) -> int:
    """Action/outcome blocks, counted the way the gate counts them.

    Read off the DRAFTED expects, which over-counts where binding will later
    delete a claim. That is the safe direction: a false trigger costs one model
    call and a refusal, a missed one costs the defect this stage exists to fix.
    """
    beats = 1
    checked = False
    for step in scenario.steps:
        acts = step.role != SegmentRole.setup or bool(step.expects)
        if acts and checked:
            beats += 1
            checked = False
        if step.expects:
            checked = True
    return beats


def split_scenarios(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    *,
    model_name: str,
    budget: int = SPLIT_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> SplitResult:
    """Divide an over-long scenario into the test cases it is made of.

    Mutates `drafted.scenarios` in place, exactly as
    `run._split_on_declared_breaks` does, and for the same reason: everything
    downstream reads that list. Splits only -- it never joins, never reorders,
    never re-words, never invents, never drops, and never changes a step id.

    Running AFTER the declared-break split means a tester's own boundary is a
    floor this can only cut further inside, so SS6.7's override survives whole.
    """
    out = SplitResult()
    if not tools_enabled:
        # A0 makes no retrieval of any kind, and a tools-disabled investigation
        # still costs a model call -- which would make "single prompt, all
        # context pre-loaded" untrue of the configuration defined by it.
        out.failed = "no tools in this configuration"
        return out
    if drafted.degraded:
        out.failed = "the draft is degraded; there is nothing shaped to repartition"
        return out

    asked = candidates(drafted)
    if not asked:
        return out

    replacements: dict[int, list[DraftedScenario]] = {}
    for index, reason in asked:
        scenario = drafted.scenarios[index]
        decision = SplitDecision(
            scenario=scenario.name,
            step_ids=[s.step_id for s in scenario.steps],
            reason=reason,
        )
        out.decisions.append(decision)

        enquiry = investigate(
            runner,
            model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=_prompt(scenario, drafted, store, config),
            model_name=model_name,
            stage=PipelineStage.split,
            label=f"split_{index:02d}",
            budget=budget,
            tools_enabled=tools_enabled,
            temperature=temperature,
        )
        enquiry.finish()
        # No `step_id`: this is a decision about a whole scenario, so charging
        # its retrievals to one step would invent a difficulty signal that does
        # not exist. `run._calls_per_step` skips investigations without one, and
        # `toolCallsTotal` still counts the calls.
        investigation = enquiry.record(
            investigation_id=f"inv_split_{index:02d}",
            stage=PipelineStage.split,
            budget=budget,
        )
        decision.investigation = investigation
        out.investigations.append(investigation)
        out.model_calls.extend(enquiry.model_calls)

        groups, refused = accept(scenario, _groups(enquiry.answer))
        decision.refused = refused
        decision.groups = groups
        if len(groups) > 1:
            by_id = {step.step_id: step for step in scenario.steps}
            replacements[index] = [
                DraftedScenario(name=group.name, steps=[by_id[i] for i in group.step_ids])
                for group in groups
            ]

    if replacements:
        rebuilt: list[DraftedScenario] = []
        for index, scenario in enumerate(drafted.scenarios):
            rebuilt.extend(replacements.get(index, [scenario]))
        drafted.scenarios = rebuilt

    return out


def accept(scenario: DraftedScenario, groups: list[Group]) -> tuple[list[Group], str]:
    """Take the partition whole, or discard it whole.

    Never repaired and never partially applied. A model that returned a
    near-partition would otherwise have its mistake patched by code that cannot
    know what it meant, and the result would be a document nobody decided.
    """
    if len(groups) < 2:
        # Not a refusal. A scenario that is long because the behaviour is long
        # is one test case, and saying so is the right answer.
        return [], ""

    flat = [step_id for group in groups for step_id in group.step_ids]
    if flat != [step.step_id for step in scenario.steps]:
        # One list equality rather than four predicates -- totality, order,
        # contiguity and no-invention are the same property, and stating it once
        # leaves nothing to argue about.
        return [], "the answer is not an ordered regrouping of this scenario's steps"

    if any(not group.step_ids for group in groups):
        return [], "a group with no steps in it is not a scenario"

    texts = [step.text for step in scenario.steps]
    cuts = set()
    at = 0
    for group in groups[:-1]:
        at += len(group.step_ids)
        cuts.add(at)
    if any(normalise(texts[i - 1]) == normalise(texts[i]) for i in cuts):
        # `merge_repeats` runs PER SCENARIO, so a cut between two steps that say
        # the same thing stops them merging and changes the total step count.
        # That is the SS3.6 guarantee, and refusing here is what makes this
        # stage able to do what `coherence` repair legitimately cannot.
        return [], (
            "the cut falls between two steps that say the same sentence, which would "
            "change the step count (SS3.6)"
        )

    return groups, ""


def _groups(answer: dict[str, Any]) -> list[Group]:
    out: list[Group] = []
    for raw in answer.get("groups") or []:
        if not isinstance(raw, dict):
            continue
        steps = [str(s).strip() for s in (raw.get("steps") or []) if str(s).strip()]
        out.append(Group(name=str(raw.get("name") or "").strip(), step_ids=steps))
    return out


SYSTEM_PROMPT = """\
You are deciding whether one scenario is one test case or several.

A test case exercises ONE behaviour and reaches ONE verdict. When it fails, a
person has to be able to say what broke without reading it twice. A session
where the tester proved one thing, finished, and then went on to prove a second
thing is two test cases, however continuous it felt at the time.

The steps below are already written and already grounded. You are not rewriting
them. Your only decision is where the boundaries fall.

## What counts as a boundary

* The tester finished proving something -- reached a verdict, a confirmation, a
  refusal -- and then started on a different question.
* The subject changes: a different feature, a different rule, a different part
  of the application.
* The flow returns to a known starting state and begins again.

## What is NOT a boundary

* Length. A behaviour that takes eight steps to exercise is still one behaviour.
* A repeated action. Adding six items to reach a limit is one step of work
  towards one verdict, not six test cases.
* A step failing or being retried. That is usually the tester fixing a typo.

## Rules your answer is checked against

Every step id below appears EXACTLY ONCE in your answer, in the order given.
Groups are contiguous: a group is a run of consecutive steps. You may not add,
remove, re-word, reorder or renumber a step, and you may not invent a step id.

**Your answer is checked mechanically and thrown out WHOLE if it breaks any of
these.** A partial answer is not applied, so do not guess at a boundary you are
unsure of.

Do not cut between two steps that say the same sentence.

**Returning ONE group is a complete and correct answer**, and it is the right
one whenever the scenario really is a single behaviour. That is not a failure to
decide; it is the decision.

## Naming

Name each group after what it PROVES, not after what the tester did.

    wrong:  "Hamper size upgrades automatically as items are added"
    right:  "A hamper at capacity cannot be upgraded past the largest size"

The first describes the tester. The second is a test: it says what should be
true, so a reader knows what a failure means.

## Looking things up

The index below says what each action changed. Where that is enough, decide
from it. Go and look when it is not -- `get_diff` and `get_snapshot` answer most
questions about what happened between two steps, and `get_narration` gives you
the tester's own words about what they were checking.

Call at most ONE tool per turn.

When you call tools, put a JSON object in your message text first:
    {"uncertainties": ["whether the tester was still checking the same rule"]}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{
  "groups": [
    {"name": "An order below the threshold is placed without approval",
     "steps": ["step_001", "step_002", "step_003"]},
    {"name": "An order over the threshold is held for manager approval",
     "steps": ["step_004", "step_005"]}
  ],
  "reason": "one sentence saying what changed at the boundary"
}
"""


def _prompt(
    scenario: DraftedScenario,
    drafted: DraftResult,
    store: EvidenceStore,
    config: ProjectConfig | None,
) -> str:
    lines: list[str] = []
    objective = (store.recording.objective or "").strip()
    if objective:
        lines.append(f"The tester said they were checking: {objective}")
        lines.append("")

    lines.append(f"SCENARIO AS DRAFTED: {scenario.name}")
    lines.append("")
    for step in scenario.steps:
        events = ", ".join(step.event_ids)
        lines.append(f"  {step.step_id}  {step.keyword} {step.text}   [{events}]")
        for expect in step.expects:
            lines.append(f"      then: {expect.text}   [{expect.event_id}]")
    lines.append("")

    if drafted.digest is not None:
        lines.append("THE SESSION, AS INDEXED")
        lines.append("")
        lines.append(drafted.digest.text)

    return "\n".join(lines)


__all__ = [
    "SPLIT_BUDGET",
    "SPLIT_EVENT_FLOOR",
    "Group",
    "SplitDecision",
    "SplitResult",
    "accept",
    "candidates",
    "count_beats",
    "split_scenarios",
]
