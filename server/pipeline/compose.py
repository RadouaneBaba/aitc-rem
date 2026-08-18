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
  "roles": {"step_001": "setup", "step_002": "test_step"},
  "merge": [{"steps": ["step_001", "step_002"], "text": "the tester signs in"}],
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
