"""Gherkin narrative layout. Deterministic, code only, no model.

This module used to DERIVE Given/When/Then from each step's role plus its
position, and that was right for as long as the stage writing steps was shown
one segment at a time: asked for a keyword with no view of the flow, a model
answers `When` every time, which is how Phase 1 shipped seven `When`s in a row.

The drafting stage sees the whole session, so it chooses the keyword and this
module lays out what it chose -- collapsing runs into `And`, placing expected
results after the steps that produced them, and breaking the scenario into
beats. Where a scenario's shape is illegal, `gherkin_style` says so rather than
this module silently rewriting it: a keyword quietly mutated in the renderer is
how every `Given` disappeared from both real recordings without anything
failing.

The one rule still enforced here is positional and cannot be a matter of
opinion: `Given` belongs to the opening block. See `_opening_block`.

Determinism note: `segments.json` is untouched and stays reproducible for the
same recording. The one structural change this module makes -- merging two
adjacent steps that say the same sentence -- unions their `eventIds`, so
`event_coverage` still accounts for every event.
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
        if out and normalise(out[-1].text) == normalise(step.text):
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

    # Where the opening block ends, decided once, up front.
    #
    # Two rules live here, and they were one running flag until a `Given`
    # stopped appearing in real output at all:
    #
    #   * `Given` states the world before the test begins, so it belongs to the
    #     opening block. Rendered after a `Then` it reads as the scenario
    #     restarting, so a `setup` step appearing later becomes `When`.
    #   * A step that produced something worth checking is not a precondition.
    #     `Given ... / Then ...` asserts before the scenario has done anything.
    #
    # Worth being exact about what the flag cost, because the obvious reading
    # is wrong. It latched on the first accepted assertion and never cleared,
    # so a legitimate later precondition could not be `Given` -- but a later
    # precondition is demoted by the first rule anyway, so on the recording
    # where this was found the two agree. What made every `Given` disappear
    # there was the assert stage putting an expected result on a navigation
    # step ("the category page is loaded" -- a claim that the browser works).
    # That is fixed where it was caused: the drafting prompt says not to, and
    # `bind.py` deletes it if it cannot be proved.
    #
    # The flag was still worth removing. A rule about the shape of a scenario
    # that reaches through the whole scenario from one step's assertion is a
    # rule nobody can reason about locally, and this one was invisible for
    # months because every fixture opened with a sign-in nobody asserted on.
    opening = _opening_block(steps)

    for index, step in enumerate(steps):
        keyword = _base_keyword(step)
        if keyword == GIVEN and index >= opening:
            keyword = WHEN

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

    return lines


def _opening_block(steps: list[Step]) -> int:
    """How many steps at the head of the scenario are still preconditions.

    The leading run of `setup` steps that check nothing. It stops at the first
    step that is not setup -- a `setup` step appearing later is real, going to
    the checkout page IS setup for what follows, but it is not a precondition
    of the scenario -- and at the first setup step that carries an accepted
    expected result, because a step worth checking is the test rather than the
    ground it stands on.

    Returning a count rather than setting a flag is the whole fix. The rule
    applies to the step that broke it and to nothing downstream of that step.
    """
    count = 0
    for step in steps:
        if _base_keyword(step) != GIVEN or _asserts(step):
            break
        count += 1
    return count


def _asserts(step: Step) -> bool:
    """Does this step carry an expected result the reader will actually see?

    Rejected candidates do not count: an assertion nobody accepted renders
    nothing, so it cannot make the step read as the thing under test.
    """
    return any(a.accepted for a in step.assertions)


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
    """Role decides, and the stored keyword is only the fallback.

    The drafting stage chooses BOTH -- it knows where the scenario turns from
    arranging to acting -- but they are two spellings of one decision, and only
    one of them can be authoritative or a reviewer's edit has no defined
    meaning. `draft._reconcile` makes the drafter's `Given` mean `setup` at
    parse time, so honouring the role here honours what the drafter wrote.

    Role wins because it is the one that survives re-layout. Deleting a step
    changes which steps are still preconditions, and a keyword denormalised
    onto the step by `sync_keywords` cannot know that -- it is already `And`
    half the time. That is why `resync_keywords` exists at all, and reading the
    stale keyword back would make it a no-op.
    """
    if step.role is not None:
        return keyword_for_role(step.role)

    keyword = step.keyword.value if isinstance(step.keyword, StepKeyword) else str(step.keyword)
    return keyword if keyword in {GIVEN, WHEN} else WHEN


def _leading_setup_count(steps: list[Step]) -> int:
    """How many steps at the head are preconditions -- and only if something follows.

    Defers to `_opening_block`, which is the one positional rule in this module.
    They used to disagree: this cut on `role != setup` alone, while
    `_opening_block` also cuts at the first setup step that CARRIES an accepted
    expected result. `Background` was built from the first and keywords came
    from the second, so a lifted setup step with an expect was moved into the
    block and then rendered there as `When` / `Then` -- a block that never
    asserts, asserting:

        Background:
          Given the tester signs in
          When the tester opens the checkout page
          Then the confirmation banner appears

    Real Gherkin runners reject that and an Xray import chokes on it. Latent
    only because no run had ever produced two scenarios, which is the same
    reason `lift_background` had never rendered at all.

    A scenario whose every step is a precondition has no test in it; lifting all
    of them would leave an empty `Scenario`, which parses but says nothing.
    """
    count = _opening_block(steps)
    return count if 0 < count < len(steps) else 0


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------


def _absorb(keeper: Step, other: Step) -> Step:
    """Fold `other` into `keeper`, losing nothing a validator checks."""
    merged = keeper.model_copy(deep=True)

    merged.eventIds = list(dict.fromkeys([*keeper.eventIds, *other.eventIds]))
    merged.fidelity = list(dict.fromkeys([*keeper.fidelity, *other.fidelity]))
    merged.assertions = dedupe_assertions([*keeper.assertions, *other.assertions])
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


def dedupe_assertions(assertions: list) -> list:
    """Drop expected results that say the same thing, keeping the first.

    Two steps merging is the common cause, and it produced a visible defect: a
    scenario ending

        Then the cart badge shows one item
        And the cart badge shows one item

    Both halves of the merge had independently gone and retrieved the same fact,
    so there really were two assertions -- same sentence, same literal, same
    event, two different `toolCallId`s. Unioning `eventIds` and concatenating
    `assertions` was right for everything except this.

    Deduplicating weakens nothing. Each surviving assertion still points at its
    own retrieval and still has to satisfy the gate; what is dropped is a second
    proof of a claim that was already proven. That is the one kind of thing this
    project is allowed to discard silently, because losing it costs a reader
    nothing and keeping it costs them a sentence they have to read twice.

    Compared on the SENTENCE, not the evidence. What a reader sees repeated is
    the prose, and two citations for one claim are still one line in the file.
    """
    out: list = []
    seen: set[str] = set()
    for assertion in assertions:
        key = " ".join((assertion.text or "").split()).strip(" .").casefold()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(assertion)
    return out


def keeps_parameters(replacement: str, originals: list[str]) -> bool:
    """Does a rewritten sentence still name every parameter it replaces?

    A redaction placeholder is a test PARAMETER (SS7.2) -- the one thing
    telling whoever runs the test what to supply -- so a tidier sentence that
    drops one is worse than the sentence it replaced. Public because the
    drafting stage groups events into steps itself now, and any future path
    that rewrites a step over several events has to answer this question.
    """
    wanted = {name for text in originals for name in PLACEHOLDER.findall(text)}
    return wanted <= set(PLACEHOLDER.findall(replacement))


def would_collapse(texts: list[str], index: int, replacement: str) -> bool:
    """Would rewriting `texts[index]` make `merge_repeats` swallow a step?

    The repair loop (SS9.9) is the only thing that rewrites a step name after
    the narrative has been built, and `merge_repeats` above folds any two
    ADJACENT steps whose text matches exactly. So a repair that makes a name
    more generic -- which is precisely what a repair prompted with "this name is
    too vague" might do -- can silently delete the step next to it.

    That would change the step COUNT between two attempts of the same run, and
    SS3.6 promises a recording produces the same count every time. It would also
    move `Yield`'s denominator mid-run, which is worse: the metric would improve
    because a step vanished.

    Deterministic and here rather than a line in the repair prompt, for the same
    reason `with_subject` is deterministic: the prompt already asks, and a
    prompt that asks is not a guarantee.
    """
    candidate = normalise(replacement)
    if not candidate:
        return False
    return any(
        normalise(texts[i]) == candidate
        for i in (index - 1, index + 1)
        if 0 <= i < len(texts)
    )


def normalise(text: str) -> str:
    """Two sentences are the same step if they differ only in spacing or a
    trailing full stop. Anything else is left alone.

    Public because `split.py` has to refuse a cut between two steps this would
    merge -- `merge_repeats` runs per scenario, so such a cut would change the
    step COUNT. A second copy of this rule is how `supports_narrated` nearly
    came to have two implementations that could disagree.
    """
    return " ".join((text or "").split()).strip(" .").casefold()


__all__ = [
    "AND",
    "GIVEN",
    "THEN",
    "WHEN",
    "Line",
    "Narrative",
    "keeps_parameters",
    "build_narrative",
    "normalise",
    "keyword_for_role",
    "sync_keywords",
    "dedupe_assertions",
    "merge_repeats",
    "would_collapse",
]
