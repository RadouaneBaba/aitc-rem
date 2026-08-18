"""Gherkin narrative layout. Deterministic, code only, no model.

Given/When/Then is a property of a *scenario*, not of a step. The naming stage
sees one segment at a time (SS9.4) and so cannot know whether the step it is
looking at is arrival at the state under test or the thing being tested -- ask
it for a keyword anyway and it answers `When` every time, which is exactly what
the Phase 1 output did for seven steps running.

So the model supplies the role (SS9.3: setup / test_step / teardown) and this
module supplies the keyword. Roles are a judgment about the flow; keywords are
a mechanical consequence of the roles plus where the assertions fall. Only the
first of those needs a model.

Determinism note: `segments.json` is untouched here and stays reproducible for
the same recording. What this module rewrites is downstream of naming, and the
one structural change it makes -- merging two adjacent steps that say the same
sentence -- unions their `eventIds`, so `event_coverage` still accounts for
every event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from server.models import Assertion, Confidence, SegmentRole, Step, StepKeyword

GIVEN = "Given"
WHEN = "When"
THEN = "Then"
AND = "And"

#: Lowest confidence wins when two steps merge: a merged step is no more
#: certain than its least certain part.
_CONFIDENCE_ORDER = {Confidence.low: 0, Confidence.medium: 1, Confidence.high: 2}

#: Redaction placeholders (SS7.1). They are the test case parameters, so a
#: rewrite that loses one costs the reader the only thing telling them what
#: to supply before running.
PLACEHOLDER = re.compile(r"<<([a-z0-9_]+)>>", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """One rendered Gherkin step line.

    `step` is set on every line; `assertion` only on expected-result lines,
    which is what lets the sidecar renderer walk the same structure and label
    each line correctly.
    """

    keyword: str
    text: str
    beat: int
    step: Step | None = None
    assertion: Assertion | None = None

    @property
    def is_assertion(self) -> bool:
        return self.assertion is not None


@dataclass
class Narrative:
    """A scenario, laid out."""

    background: list[Line] = field(default_factory=list)
    body: list[Line] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    @property
    def beats(self) -> int:
        """How many action blocks the scenario has.

        Used to decide whether blank lines between beats help or just make a
        short scenario look sparse.
        """
        return len({line.beat for line in self.body if not line.is_assertion})

    @property
    def has_expected_result(self) -> bool:
        return any(line.is_assertion for line in self.body)


def build_narrative(steps: list[Step], *, lift_background: bool = False) -> Narrative:
    """Lay a scenario out: assign keywords, place assertions.

    Layout only. Merging happens once, during assembly, so `ir.json` and the
    rendered feature always show the same steps -- a renderer that quietly
    collapsed two of them would make the artifact disagree with the record the
    validators read.

    `lift_background` moves leading setup steps into a `Background` block. Off
    by default: with a single scenario, `Background` is indirection for no gain
    and the whole test reads better top to bottom. It earns its keep once a
    recording yields several scenarios that share setup (SS9.3).
    """
    head: list[Step] = []
    rest: list[Step] = list(steps)
    if lift_background:
        cut = _leading_setup_count(rest)
        head, rest = rest[:cut], rest[cut:]

    return Narrative(
        background=_lay_out(head) if head else [],
        body=_lay_out(rest),
        steps=list(steps),
    )


def apply_merges(
    steps: list[Step],
    groups: list[list[str]],
    *,
    texts: dict[str, str] | None = None,
) -> list[Step]:
    """Fold together the steps composition judged to be one intent.

    The segmenter cuts on evidence of a boundary; a boundary is not a change of
    intent. Typing a password and pressing Sign in are two segments and one
    thing the tester was doing, and named in isolation they come back as two
    sentences about signing in -- which is the tool visibly stuttering.

    No rule separates that from a tester who genuinely did the same thing twice,
    so the judgment is composition's (it sees the whole flow) and the mechanics
    are here. Only adjacent steps merge: reordering a test case is not a
    phrasing decision.
    """
    if not groups:
        return list(steps)

    texts = texts or {}
    position = {step.id: index for index, step in enumerate(steps)}
    absorbed_by: dict[str, str] = {}
    #: keeper id -> the sentence the merged step should carry.
    rename: dict[str, str] = {}

    for group in groups:
        known = [sid for sid in group if sid in position]
        if len(known) < 2:
            continue
        known.sort(key=position.__getitem__)
        if position[known[-1]] - position[known[0]] != len(known) - 1:
            # Not contiguous. Merging across a gap would silently delete the
            # step in between.
            continue
        for sid in known[1:]:
            absorbed_by[sid] = known[0]
        replacement = next((texts[sid] for sid in known if texts.get(sid)), "")
        originals = [position[sid] for sid in known]
        if replacement and _keeps_parameters(replacement, [steps[i].text for i in originals]):
            rename[known[0]] = replacement
        elif replacement:
            # The merged sentence dropped a redaction placeholder. SS7.2 makes
            # those the test's parameters -- the one thing telling whoever runs
            # it what to supply -- so the more specific original wins over a
            # tidier summary.
            rename[known[0]] = max(
                (steps[i].text for i in originals), key=lambda t: len(PLACEHOLDER.findall(t))
            )

    out: list[Step] = []
    by_id: dict[str, int] = {}
    for step in steps:
        keeper_id = absorbed_by.get(step.id)
        if keeper_id is not None and keeper_id in by_id:
            out[by_id[keeper_id]] = _absorb(out[by_id[keeper_id]], step)
            continue
        by_id[step.id] = len(out)
        out.append(step)

    for step in out:
        if step.id in rename:
            step.text = rename[step.id]
    return out


def merge_repeats(steps: list[Step]) -> list[Step]:
    """Collapse adjacent steps that say the same thing.

    The segmenter cuts on evidence of a boundary, not on evidence of a change
    of intent, so one intent regularly spans two segments -- a password typed,
    then the button pressed. Named in isolation, both come back as "the tester
    signs in to the application" and the reader watches the tool stutter.

    The real fix is upstream: SS9.4's prompt now shows the previous step so the
    model differentiates ("places the order again"). This is the safety net for
    when it does not, and it is deliberately narrow -- only an exact textual
    repeat merges, never two steps that merely resemble each other.
    """
    out: list[Step] = []
    for step in steps:
        if out and _normalise(out[-1].text) == _normalise(step.text):
            out[-1] = _absorb(out[-1], step)
            continue
        out.append(step)
    return out


# --------------------------------------------------------------------------
# keyword assignment
# --------------------------------------------------------------------------


def _lay_out(steps: list[Step]) -> list[Line]:
    lines: list[Line] = []
    beat = 0
    previous: str | None = None
    #: True once the scenario has moved past its preconditions.
    acting = False

    for step in steps:
        keyword = _base_keyword(step)

        # `Given` states the world before the test begins, so it belongs to the
        # opening block and nowhere else. Composition can legitimately call a
        # later step `setup` -- going to the checkout page is setup for what
        # follows it -- but rendering that as `Given` after a `Then` produces
        # Given/When/Then in an order no one writes, and reads as the scenario
        # restarting mid-way.
        if keyword == GIVEN and acting:
            keyword = WHEN
        elif keyword != GIVEN:
            acting = True

        # A new action after an expected result opens a new beat, so it reads
        # as a fresh "and then the tester did this" rather than as more of the
        # same block.
        if keyword == WHEN and previous == THEN:
            beat += 1

        lines.append(
            Line(
                keyword=AND if keyword == previous else keyword,
                text=step.text,
                beat=beat,
                step=step,
            )
        )
        previous = keyword

        for assertion in step.assertions:
            if not assertion.accepted:
                continue
            lines.append(
                Line(
                    keyword=AND if previous == THEN else THEN,
                    text=assertion.text,
                    beat=beat,
                    step=step,
                    assertion=assertion,
                )
            )
            previous = THEN
            # An expected result ends the preconditions even when the step that
            # produced it was setup: once the scenario has checked something,
            # nothing after it is describing the world beforehand.
            acting = True

    return lines


def sync_keywords(steps: list[Step]) -> None:
    """Set each step's `keyword` to the one it will actually render as.

    `Step.keyword` is a denormalisation of `role` plus position, and a reviewer
    who sees `Given` in the UI while the feature file says `And` has been shown
    two versions of the same step. Both now come from `build_narrative`, so
    they cannot disagree.
    """
    for line in build_narrative(steps).body:
        if line.step is not None and not line.is_assertion:
            line.step.keyword = line.keyword


def keyword_for_role(role: SegmentRole | None) -> str:
    """The keyword a role implies, before `And` collapsing.

    `exploratory` and `abandoned` map to `When` rather than disappearing:
    pruning them out of the narrative is SS9.3's job and belongs to the
    decomposition stage, which also records them in `omitted` so nothing is
    silently lost. Until that lands they read as ordinary steps.
    """
    return GIVEN if role == SegmentRole.setup else WHEN


def _base_keyword(step: Step) -> str:
    """Role decides the keyword. The model's own guess is the fallback."""
    if step.role is not None:
        return keyword_for_role(step.role)

    keyword = step.keyword.value if isinstance(step.keyword, StepKeyword) else str(step.keyword)
    return keyword if keyword in {GIVEN, WHEN, THEN} else WHEN


def _leading_setup_count(steps: list[Step]) -> int:
    """How many steps at the head are setup -- and only if something follows.

    A scenario whose every step is setup has no test in it; lifting all of them
    into `Background` would leave an empty `Scenario`, which parses but says
    nothing.
    """
    count = 0
    for step in steps:
        if step.role != SegmentRole.setup:
            break
        count += 1
    return count if 0 < count < len(steps) else 0


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------


def _absorb(keeper: Step, other: Step) -> Step:
    """Fold `other` into `keeper`, losing nothing a validator checks."""
    merged = keeper.model_copy(deep=True)

    merged.eventIds = list(dict.fromkeys([*keeper.eventIds, *other.eventIds]))
    merged.fidelity = list(dict.fromkeys([*keeper.fidelity, *other.fidelity]))
    merged.assertions = [*keeper.assertions, *other.assertions]
    merged.confidence = min(
        keeper.confidence, other.confidence, key=lambda c: _CONFIDENCE_ORDER.get(c, 1)
    )
    if not merged.escalation and other.escalation:
        merged.escalation = other.escalation
    if keeper.selectorHints or other.selectorHints:
        merged.selectorHints = [*(keeper.selectorHints or []), *(other.selectorHints or [])]
    if keeper.criticNotes or other.criticNotes:
        merged.criticNotes = [*(keeper.criticNotes or []), *(other.criticNotes or [])]
    return merged


def _keeps_parameters(replacement: str, originals: list[str]) -> bool:
    """Does the merged sentence still name every parameter it replaces?"""
    wanted = {name for text in originals for name in PLACEHOLDER.findall(text)}
    return wanted <= set(PLACEHOLDER.findall(replacement))


def _normalise(text: str) -> str:
    """Two sentences are the same step if they differ only in spacing or a
    trailing full stop. Anything else is left alone."""
    return " ".join((text or "").split()).strip(" .").casefold()


__all__ = [
    "AND",
    "GIVEN",
    "THEN",
    "WHEN",
    "Line",
    "Narrative",
    "apply_merges",
    "build_narrative",
    "keyword_for_role",
    "sync_keywords",
    "merge_repeats",
]
