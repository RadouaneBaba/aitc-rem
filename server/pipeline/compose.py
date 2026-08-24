"""Stage 3b -- composition (SS9.3, restricted to one test case). Agentic.

Naming sees one segment at a time, which is the right scope for "what was the
tester doing here" and the wrong scope for every question about the document as
a whole. Nothing in Phase 1 asked those questions, and the output showed it: a
`Feature:` and a `Scenario:` both set to the objective string the tester typed
into the popup, no `Given` anywhere, and seven steps of `When`.

This stage reads the whole named flow at once and answers what only that
vantage point can:

* what capability is under test        -> the Feature name
* what specific case this recording is -> the Scenario name
* what a reader needs as context       -> the description block
* what each step is doing in the test  -> setup / test_step / teardown

That last one is the load-bearing part. Given/When/Then follows from it
mechanically (`narrative.py`), so the model is asked for the judgment and never
for the syntax.

Splitting one recording into N test cases, pruning exploratory and abandoned
work, and lifting shared setup into a `Background` are the rest of SS9.3. They
extend this stage rather than replacing it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    DecompositionDecision,
    ModelCall,
    PipelineStage,
    SegmentRole,
    StepInvestigation,
)
from server.pipeline.investigate import investigate
from server.pipeline.name import NamingResult

#: Smaller than the naming budget on purpose. This stage reasons over material
#: that has already been investigated once; it is here to see the shape of the
#: flow, not to re-derive it.
COMPOSE_BUDGET = 4

MAX_TAGS = 4

SYSTEM_PROMPT = """\
You are turning a recorded browser session into one formal QA test case.

The individual steps have already been written. Your job is the document around
them -- the part nobody can judge from a single step.

Answer with ONLY this JSON:
{
  "title": "Order approval",
  "scenario": "An order over EUR500 is held for manager approval",
  "description": "Orders above the EUR500 threshold are held for manager approval before they can be placed.",
  "tags": ["checkout", "approval"],
  "roles": {"step_001": "setup", "step_002": "test_step", "step_003": "exploratory"},
  "merge": [{"steps": ["step_001", "step_002"], "text": "the tester signs in"}],
  "split": [{"step": "step_005", "after": "evt_008",
             "text": ["the tester submits the order", "the tester approves it and submits again"]}],
  "cases": [{"scenario": "An order over EUR500 is held for manager approval",
             "steps": ["step_001", "step_005"]}],
  "rationale": {"step_001": "signing in is how the tester reaches checkout, not what this test checks"}
}

"title" is the CAPABILITY under test, as a short noun phrase: "Order approval",
"Shopping cart", "User login". It is the name of the feature file and it groups
every test about that area. It is NOT the objective sentence and it is NOT a
description of this one run. Two recordings of the same area should get the
same title.

"scenario" is the specific case THIS recording exercises, as a sentence:
"An order over EUR500 is held for manager approval". It must not repeat the
title. A reader scanning a list of scenarios should be able to tell them apart
from this line alone.

"description" is one or two sentences of context for a reader who was not
there. State the rule being checked, not the click sequence. Omit it if the
scenario name already says everything.

"tags" are 1-4 lowercase single words or hyphenated words naming the area:
["checkout", "approval"]. No leading @. No "test", no "automated", no
"regression" -- those say nothing about the content.

"roles" assigns every step id one of:
  * setup     -- getting to the state under test. Signing in, navigating to the
                 page, seeding data. Real work, but not what is being verified.
  * test_step -- the behaviour this test exists to exercise.
  * teardown  -- cleaning up afterwards.
  * exploratory -- the tester looking for something. Opening a page that turns
                 out to be the wrong one, reading a screen and leaving it,
                 hunting for a control. Real, and not part of the test.
  * abandoned -- something started and given up on. A form filled in and never
                 submitted, a dialog opened and cancelled.

Those last two are PRUNED from the test case and reported separately, so a
reader knows the narrative is not the whole session. Use them where a session
genuinely wandered: a recorded sitting is a person working, and transcribing
their wrong turns into a test case somebody has to execute is how the artifact
becomes unusable.

Be sparing. A step you merely find uninteresting is not exploratory, and
pruning a step that mattered loses work the tester actually did. If the step
advances the objective at all, it is `setup` or `test_step`.

Judge each step against the stated objective, not against how it looks in
isolation. Signing in is `setup` for a test about checkout and `test_step` for
a test about authentication. Steps before the first thing the objective
actually talks about are almost always `setup`.

"merge" groups ADJACENT step ids that describe one intent, with the sentence
they should become. The segmenter cuts where it sees a boundary, and a boundary
is not a change of intent -- typing a password and pressing Sign in are two
segments and one thing the tester was doing. Named separately they come back as
two sentences about signing in, and the reader watches the tool stutter.

  "merge": [{"steps": ["step_001", "step_002"],
             "text": "the tester signs in as \"<<user_email_1>>\""}]

The merged sentence must keep every quoted value and every <<placeholder>> the
steps it replaces carried. Those are what tell whoever runs the test what to
type; a tidier sentence that drops them is worse than the two it replaced.

Only group steps that are genuinely one action. A tester who did the same thing
twice on purpose -- submitted, was rejected, fixed it, submitted again -- did
two things, and collapsing those hides the point of the test. Omit "merge"
entirely when every step already stands on its own.

"split" is the same judgement in reverse, and you are the only stage that can
make it. The segmenter does not end a step on a REJECTED request, because a
rejection usually leaves the tester on the same screen fixing a typo -- still
one attempt. But when the rejection is the thing the test is ABOUT, that rule
puts two attempts in one step, and the result contradicts itself:

    When the tester submits an order totalling "615" with manager approval
    Then the order requires manager approval

which grants approval and then expects to be told approval is needed. Every
literal in it is true of the recording; the test case is still wrong.

You are shown each step's requests and whether they were rejected or succeeded.
A step holding a rejection AND a later success on the same endpoint is two
attempts. Split it:

  "split": [{"step": "step_005", "after": "evt_008",
             "text": ["the tester submits an order totalling \"615\"",
                      "the tester obtains manager approval and submits it again"]}]

"after" is the LAST event of the first half. "text" is the two sentences, in
order. Expected results follow their own evidence, so a result grounded in the
rejection stays with the attempt that was rejected -- you do not have to place
them.

Split only when the flow genuinely contains two attempts. A step with one
request, or with a rejection and no retry, is one step.

"cases" splits the recording into SEPARATE test cases, when it holds more than
one. A tester often checks two or three things in a sitting -- signing in, then
the cart, then checkout -- and one test case covering all of it is a test that
nobody can run in isolation and nobody can say has failed for a single reason.

  "cases": [{"scenario": "An empty cart shows the empty state",
             "steps": ["step_003", "step_004"]},
            {"scenario": "An order over EUR500 is held for manager approval",
             "steps": ["step_005", "step_006", "step_007"]}]

List every step id exactly once, in order, across all the cases. Setup steps
shared by several cases go in the FIRST case that needs them and are not
repeated -- they are lifted into a Background automatically.

Where the tester pressed "New scenario" while recording, that IS a case
boundary and you do not get to overrule it: they said so at the time.

Omit "cases" entirely when the recording is one test case, which is the common
answer. Two flows that share an objective and read as one story are one case.
Splitting a five-step recording into three cases of two steps produces three
tests that each check nothing.

"rationale" explains any role you expect to be questioned. One short clause.
Include only the steps worth explaining.

You have tools that query the recording. Use them only if the flow does not
make sense from what you are shown -- this material has already been
investigated once. Call at most ONE tool per turn.

Never invent a capability the recording does not show. If the objective is
blank and the flow is ambiguous, name the title after the part of the
application the tester spent the most time in."""


@dataclass(frozen=True)
class MergeGroup:
    """Adjacent steps composition judged to be one intent (SS9.3)."""

    step_ids: list[str]
    #: The sentence the merged step should carry. Empty keeps the first step's
    #: own text, which is the safe answer when the model offers no replacement.
    text: str = ""


@dataclass(frozen=True)
class SplitGroup:
    """One step the segmenter joined that is really two attempts (SS9.3).

    The segmenter cannot see this: it deliberately does not end a step on a
    rejected request, because a rejection usually means a typo being fixed
    rather than a second attempt. Telling those apart needs the objective, and
    composition is the only stage that has it.
    """

    step_id: str
    #: Last event of the first half. Everything after it becomes the new step.
    after_event_id: str
    #: The two sentences, in order. Either may be empty to keep what was there.
    texts: tuple[str, str] = ("", "")


@dataclass(frozen=True)
class CaseGroup:
    """One test case's worth of steps (SS9.3)."""

    scenario: str
    step_ids: list[str]


@dataclass
class ComposeResult:
    """The document-level decisions, and what they cost."""

    title: str
    scenario_name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    #: step id -> role. Missing ids keep whatever naming proposed.
    roles: dict[str, SegmentRole] = field(default_factory=dict)
    merges: list[MergeGroup] = field(default_factory=list)
    splits: list[SplitGroup] = field(default_factory=list)
    cases: list[CaseGroup] = field(default_factory=list)
    decisions: list[DecompositionDecision] = field(default_factory=list)
    investigation: StepInvestigation | None = None
    model_calls: list[ModelCall] = field(default_factory=list)
    #: True when the model did not answer and the deterministic fallback ran.
    degraded: bool = False


def compose_test_case(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming: NamingResult,
    *,
    model_name: str,
    budget: int = COMPOSE_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> ComposeResult:
    """Name the document and decide what each step is doing in it."""
    config = config or ProjectConfig()
    fallback = fallback_composition(store, naming)

    if not naming.steps:
        return fallback

    enquiry = investigate(
        runner,
        model,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=_prompt(store, naming),
        model_name=model_name,
        stage=PipelineStage.decompose,
        label="compose",
        budget=budget,
        tools_enabled=tools_enabled,
        temperature=temperature,
    )
    enquiry.finish()

    answer = enquiry.answer
    result = ComposeResult(
        title=_clean(answer.get("title")) or fallback.title,
        scenario_name=_clean(answer.get("scenario")) or fallback.scenario_name,
        description=_clean(answer.get("description")),
        tags=_tags(answer.get("tags")) or list(fallback.tags),
        roles=_roles(answer.get("roles"), naming),
        merges=_merges(answer.get("merge"), naming),
        splits=_splits(answer.get("split"), naming),
        cases=_cases(answer.get("cases"), naming, store),
        model_calls=enquiry.model_calls,
        degraded=not answer,
    )

    # A Feature that repeats its own Scenario is the defect this stage exists
    # to fix; if the model produced one anyway, keep the specific half.
    if _same(result.title, result.scenario_name):
        result.title = fallback.title

    result.investigation = enquiry.record(
        investigation_id="inv_compose",
        stage=PipelineStage.decompose,
        budget=budget,
    )
    result.decisions = _decisions(result, answer.get("rationale"), enquiry.tool_call_ids)
    return result


# --------------------------------------------------------------------------
# fallback
# --------------------------------------------------------------------------


def fallback_composition(store: EvidenceStore, naming: NamingResult) -> ComposeResult:
    """What to say when there is no model answer to use.

    Deliberately not "the objective, twice". The application's own page title
    is the closest thing to a capability name that can be read straight off the
    recording, and the objective is already a sentence about this particular
    run -- which is exactly what a Scenario name is.
    """
    objective = (store.objective or "").strip()
    return ComposeResult(
        title=_page_title(store) or _sentence(objective) or "Recorded session",
        scenario_name=_sentence(objective) or _page_title(store) or "Recorded session",
        roles={s.step_id: s.role for s in naming.steps},
        degraded=True,
    )


def _page_title(store: EvidenceStore) -> str:
    """The title the application gives itself, most common first.

    Falls back through the snapshot titles because a single page may be
    untitled while the rest of the session is not.
    """
    titles = Counter()
    for event in store.recording.events:
        for snapshot in (event.before, event.after):
            title = (getattr(snapshot, "title", "") or "").strip()
            if title:
                titles[title] += 1
    if not titles:
        return ""
    return _sentence(titles.most_common(1)[0][0])


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------


def _prompt(store: EvidenceStore, naming: NamingResult) -> str:
    lines: list[str] = []
    objective = store.objective
    lines.append(
        f"Stated objective: {objective}"
        if objective
        else "Stated objective: none given (infer the capability from the flow)."
    )

    metadata = store.recording.metadata
    lines.append(f"Started at: {metadata.startUrl}")
    lines.append(f"Duration: {int(metadata.durationMs / 1000)}s")
    lines.append("")

    lines.append("The steps, in order:")
    for named in naming.steps:
        lines.append(f"  {named.step_id}  {named.text}")
        detail: list[str] = [f"events {', '.join(named.event_ids)}"]
        # Per step, not just per recording. A step holding both a 409 and a 201
        # on the same endpoint is a rejected attempt followed by a successful
        # one -- two things the tester did, which the segmenter cannot see
        # because a 4xx deliberately does not end a segment (a rejected submit
        # leaves you on the same screen). Composition can see it, and this is
        # the line that lets it.
        outcomes = _outcomes(store, named.event_ids)
        if outcomes:
            detail.append("; ".join(outcomes))
        # The prompt tells the model a declared break is not its to overrule.
        # It could not act on that until it was shown WHERE: the instruction was
        # there and the fact was not, and one recording came back as a single
        # case with the tester's own boundary sitting inside it.
        if getattr(store.segment(named.segment_id), "hasScenarioBreak", False):
            detail.append('the tester pressed "New scenario" before this step')
        if named.confidence.value != "high":
            detail.append(f"confidence {named.confidence.value}")
        for assertion in named.assertions:
            detail.append(f"expected result: {assertion.text}")
        if named.escalation:
            detail.append(f"open question: {named.escalation}")
        lines.append(f"      ({'; '.join(detail)})")
    lines.append("")

    urls = list(dict.fromkeys(e.url for e in store.recording.events if e.url))
    if urls:
        lines.append("Pages visited, in order:")
        for url in urls[:12]:
            lines.append(f"  {url}")
        lines.append("")

    mutations = [
        f"{c.method.upper()} {c.url} -> {c.status}"
        for e in store.recording.events
        for c in e.network
        if c.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and c.status is not None
    ]
    if mutations:
        lines.append("State-changing requests that completed:")
        for mutation in list(dict.fromkeys(mutations))[:10]:
            lines.append(f"  {mutation}")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# answer handling
# --------------------------------------------------------------------------


def _outcomes(store: EvidenceStore, event_ids: list[str]) -> list[str]:
    """State-changing requests inside one step, tagged with the event they hit.

    Rejections included, and named as such: the whole point is that a step
    containing a failure and then a success contains two attempts.
    """
    out: list[str] = []
    for event_id in event_ids:
        if not store.has_event(event_id):
            continue
        for call in store.event(event_id).network:
            if call.method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue
            if call.status is None:
                continue
            verdict = "rejected" if call.status >= 400 else "succeeded"
            out.append(f"{event_id}: {call.method.upper()} {call.status} ({verdict})")
    return out


def _roles(value, naming: NamingResult) -> dict[str, SegmentRole]:
    """Composition overrules naming, but only where it actually spoke."""
    roles = {s.step_id: s.role for s in naming.steps}
    if not isinstance(value, dict):
        return roles

    known = set(roles)
    for step_id, role in value.items():
        if str(step_id) not in known:
            continue
        try:
            roles[str(step_id)] = SegmentRole(str(role).strip().lower())
        except ValueError:
            continue
    return roles


def _merges(value, naming: NamingResult) -> list[MergeGroup]:
    """Only real, distinct step ids survive. A merge naming a step that does not
    exist would silently drop the one next to it."""
    if not isinstance(value, list):
        return []
    known = {s.step_id for s in naming.steps}
    out: list[MergeGroup] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        ids = [str(sid) for sid in entry.get("steps") or [] if str(sid) in known]
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2:
            continue
        out.append(MergeGroup(step_ids=ids, text=_clean(entry.get("text"))))
    return out


def _splits(value, naming: NamingResult) -> list[SplitGroup]:
    """Parse `split`, keeping only what this recording can actually support."""
    if not isinstance(value, list):
        return []

    by_id = {s.step_id: s for s in naming.steps}
    out: list[SplitGroup] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        step_id = str(entry.get("step") or "")
        after = str(entry.get("after") or "")
        named = by_id.get(step_id)
        # The cut must land inside the step and leave something on both sides,
        # or it is not a split -- it is a rename plus an empty step.
        if named is None or after not in named.event_ids:
            continue
        if named.event_ids.index(after) == len(named.event_ids) - 1:
            continue

        texts = entry.get("text")
        first, second = "", ""
        if isinstance(texts, list) and len(texts) >= 2:
            first, second = _clean(texts[0]), _clean(texts[1])
        out.append(SplitGroup(step_id=step_id, after_event_id=after, texts=(first, second)))
    return out


def _cases(value, naming: NamingResult, store: EvidenceStore) -> list[CaseGroup]:
    """Parse `cases`, and refuse a split that would lose or duplicate a step.

    Every step must appear exactly once. A decomposition that dropped one would
    silently delete work the tester did, and `event_coverage` would then fail
    for a reason nobody could trace back to here.
    """
    known = [s.step_id for s in naming.steps]
    if not isinstance(value, list) or len(value) < 2:
        return []

    groups: list[CaseGroup] = []
    seen: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        ids = [str(i) for i in (entry.get("steps") or []) if str(i) in known]
        ids = [i for i in ids if i not in seen]
        if not ids:
            continue
        seen.extend(ids)
        groups.append(CaseGroup(scenario=_sentence(_clean(entry.get("scenario"))), step_ids=ids))

    declared = _declared_breaks(naming, store)
    if len(groups) < 2 or sorted(seen) != sorted(known):
        # Not a decomposition -- a partial one, which is worse than none: the
        # steps left out would vanish from every artifact.
        return _split_on_declared_breaks(naming, declared)

    # SS6.7 says a scenario break OVERRIDES decomposition, and override means
    # override: the tester pressed the button while they were there and we were
    # not. A model that ignores it does not get to, and neither does one that
    # merely forgets -- composition is agentic and answered differently on two
    # consecutive runs of the same recording.
    if declared and not declared.issubset({g.step_ids[0] for g in groups}):
        return _split_on_declared_breaks(naming, declared)
    return groups


def _split_on_declared_breaks(naming: NamingResult, declared: set[str]) -> list[CaseGroup]:
    """Cut where the tester said to, with no model in the loop.

    The scenario name is left empty; assembly falls back to composition's, which
    is at least about this recording. A generated name would be better and this
    is not the place to invent one.
    """
    if not declared:
        return []

    groups: list[CaseGroup] = []
    current: list[str] = []
    for named in naming.steps:
        if named.step_id in declared and current:
            groups.append(CaseGroup(scenario="", step_ids=current))
            current = []
        current.append(named.step_id)
    if current:
        groups.append(CaseGroup(scenario="", step_ids=current))
    return groups if len(groups) >= 2 else []


def _declared_breaks(naming: NamingResult, store: EvidenceStore) -> set[str]:
    """Step ids that begin where the tester pressed "New scenario"."""
    if store.segments is None:
        return set()
    breaking = {s.id for s in store.segments.segments if getattr(s, "hasScenarioBreak", False)}
    return {s.step_id for s in naming.steps if s.segment_id in breaking}


def _decisions(
    result: ComposeResult, rationale, tool_call_ids: list[str]
) -> list[DecompositionDecision]:
    """SS9.3 -- no deterministic rule tells a false start from a test step, so
    the reasoning is recorded rather than asserted."""
    reasons = rationale if isinstance(rationale, dict) else {}
    out: list[DecompositionDecision] = []
    for step_id, role in result.roles.items():
        why = _clean(reasons.get(step_id))
        decision = DecompositionDecision(
            kind="segment_role",
            role=role,
            rationale=why or f"composed from the whole flow as {role.value}",
        )
        decision.segmentId = step_id
        if tool_call_ids:
            decision.toolCallIds = list(tool_call_ids)
        out.append(decision)
    return out


def _tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        tag = str(raw).strip().lstrip("@").lower().replace(" ", "-")
        tag = "".join(ch for ch in tag if ch.isalnum() or ch == "-").strip("-")
        if tag and tag not in out:
            out.append(tag)
    return out[:MAX_TAGS]


def _clean(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _sentence(text: str) -> str:
    """Capitalise without flattening an acronym or a product name."""
    text = _clean(text).rstrip(".")
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _same(a: str, b: str) -> bool:
    return a.strip().rstrip(".").casefold() == b.strip().rstrip(".").casefold()


__all__ = [
    "COMPOSE_BUDGET",
    "ComposeResult",
    "MergeGroup",
    "compose_test_case",
    "fallback_composition",
]
