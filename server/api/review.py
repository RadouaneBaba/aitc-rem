"""The human gate (SS13), and the measurement it leaves behind.

    "Every human edit is recorded: which step, what kind of change, how large.
     This is not analytics -- it is the `steps edited by a human` column of the
     ablation (SS3.5) and the y-axis of the effort/difficulty correlation
     (SS3.4), collected for free from normal use."

That second sentence is why this module exists as its own thing rather than as
a handful of mutations inside the API. Every edit goes through `apply`, so the
record cannot drift from what actually changed -- an endpoint that edited the IR
directly would silently cost the project its only source of difficulty labels.

Editing never touches an assertion's evidence. A reviewer can reject a claim,
reword the prose around it or delete the step entirely, but they cannot make an
ungrounded assertion grounded, because `toolCallId` and `literal` are not theirs
to edit (SS3.2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from server.models import (
    IRDocument,
    ReviewDocument,
    ReviewEdit,
    ReviewEditKind,
    Step,
    TestCaseIR,
)
from server.pipeline.narrative import build_narrative, sync_keywords


class ReviewError(ValueError):
    """A request that does not describe a change this IR can accept."""


def new_review(ir: IRDocument) -> ReviewDocument:
    return ReviewDocument(
        schemaVersion="1.0",
        recordingId=ir.recordingId,
        runId=ir.runId,
        projectId=ir.projectId,
        ownerId=ir.ownerId,
        createdAt=datetime.now(UTC),
        edits=[],
        approved=False,
    )


# --------------------------------------------------------------------------
# edits
# --------------------------------------------------------------------------


def edit_step_text(ir: IRDocument, review: ReviewDocument, *, step_id: str, text: str) -> Step:
    """The human always has final say on the sentence (SS13.2)."""
    case, step = _locate(ir, step_id)
    before = step.text
    after = " ".join(text.split())
    if not after:
        raise ReviewError("a step cannot be left with no text")

    step.text = after
    _record(
        review,
        kind=ReviewEditKind.step_text,
        case=case,
        step_id=step_id,
        before=before,
        after=after,
    )
    return step


def set_assertion(
    ir: IRDocument, review: ReviewDocument, *, step_id: str, assertion_id: str, accepted: bool
) -> Step:
    """The core review loop, and it must take seconds (SS13.2).

    Accepting does not upgrade provenance to `confirmed` on its own -- that is
    reserved for a human answering a question the agent asked. Ticking a box
    the tool proposed is agreement, not testimony.
    """
    case, step = _locate(ir, step_id)
    assertion = next((a for a in step.assertions if a.id == assertion_id), None)
    if assertion is None:
        raise ReviewError(f"step {step_id} has no assertion {assertion_id}")

    if assertion.accepted == accepted:
        return step

    assertion.accepted = accepted
    _record(
        review,
        kind=(ReviewEditKind.assertion_accepted if accepted else ReviewEditKind.assertion_rejected),
        case=case,
        step_id=step_id,
        assertion_id=assertion_id,
        after=assertion.text,
    )
    return step


def edit_assertion_text(
    ir: IRDocument, review: ReviewDocument, *, step_id: str, assertion_id: str, text: str
) -> Step:
    """Reword an expected result, keeping the evidence it was bound to.

    The assertion stage proposes one candidate for most steps, which is right --
    manufacturing a second for a step with one obvious outcome produces exactly
    the weak incidental claim the ranking exists to demote. But it leaves the
    reviewer with a single checkbox: reject it and the step has no expected
    result at all, and SS13.2's loop assumes there is something to choose.

    So the reviewer may say the same thing better. What they may not do is
    change `literal` or `toolCallId` (SS3.2): the sentence is prose and free,
    the citation is what makes it checkable, and making an ungrounded assertion
    grounded is not a reviewer's to give.
    """
    case, step = _locate(ir, step_id)
    assertion = next((a for a in step.assertions if a.id == assertion_id), None)
    if assertion is None:
        raise ReviewError(f"step {step_id} has no assertion {assertion_id}")
    if not text.strip():
        raise ReviewError("an expected result cannot be empty")

    before = assertion.text
    if before == text.strip():
        return step

    assertion.text = text.strip()
    _record(
        review,
        kind=ReviewEditKind.assertion_text,
        case=case,
        step_id=step_id,
        assertion_id=assertion_id,
        before=before,
        after=assertion.text,
    )
    return step


def answer_escalation(ir: IRDocument, review: ReviewDocument, *, step_id: str, answer: str) -> Step:
    """SS13.2 -- turns the agent's question into `confirmed` provenance.

    This is the one path that may raise an assertion's provenance, because it
    is the only one where a human states something rather than agreeing with
    something. The evidence binding is untouched: what changes is who vouches
    for the claim, not what it points at.
    """
    case, step = _locate(ir, step_id)
    if not step.escalation:
        raise ReviewError(f"step {step_id} has no open question")
    if not answer.strip():
        raise ReviewError("an answer cannot be empty")

    question = step.escalation
    step.escalation = None
    step.confidence = "high"
    for assertion in step.assertions:
        if assertion.accepted:
            assertion.provenance = "confirmed"

    _record(
        review,
        kind=ReviewEditKind.escalation_answered,
        case=case,
        step_id=step_id,
        before=question,
        after=answer.strip(),
    )
    return step


def delete_step(ir: IRDocument, review: ReviewDocument, *, step_id: str) -> TestCaseIR:
    """Segmentation will sometimes be wrong, and a step that describes nothing
    the test needs is noise a reviewer should be able to remove."""
    case, step = _locate(ir, step_id)
    if len(case.steps) == 1:
        raise ReviewError("a test case cannot be left with no steps")

    case.steps = [s for s in case.steps if s.id != step_id]
    _record(
        review,
        kind=ReviewEditKind.step_deleted,
        case=case,
        step_id=step_id,
        before=step.text,
    )
    return case


def merge_steps(
    ir: IRDocument, review: ReviewDocument, *, step_ids: list[str], text: str | None = None
) -> Step:
    """Merge adjacent steps the segmenter split (SS13.2).

    Adjacent only, and event ids are unioned rather than dropped, so
    `event_coverage` still accounts for every event after a human edit exactly
    as it did after the pipeline.
    """
    if len(step_ids) < 2:
        raise ReviewError("merging needs at least two steps")

    case, _ = _locate(ir, step_ids[0])
    index = {s.id: i for i, s in enumerate(case.steps)}
    if any(sid not in index for sid in step_ids):
        raise ReviewError("every step in a merge must belong to the same test case")

    positions = sorted(index[sid] for sid in step_ids)
    if positions[-1] - positions[0] != len(positions) - 1:
        raise ReviewError("only adjacent steps can be merged")

    keeper = case.steps[positions[0]]
    before = keeper.text
    for position in positions[1:]:
        other = case.steps[position]
        keeper.eventIds = list(dict.fromkeys([*keeper.eventIds, *other.eventIds]))
        keeper.fidelity = list(dict.fromkeys([*keeper.fidelity, *other.fidelity]))
        keeper.assertions = [*keeper.assertions, *other.assertions]

    if text and text.strip():
        keeper.text = " ".join(text.split())

    absorbed = {case.steps[p].id for p in positions[1:]}
    case.steps = [s for s in case.steps if s.id not in absorbed]

    _record(
        review,
        kind=ReviewEditKind.steps_merged,
        case=case,
        step_id=keeper.id,
        before=before,
        after=keeper.text,
    )
    return keeper


def move_step(
    ir: IRDocument, review: ReviewDocument, *, step_id: str, to_case_id: str, position: int
) -> Step:
    """Decomposition will sometimes be wrong (SS13.2)."""
    case, step = _locate(ir, step_id)
    target = next((c for c in ir.testCases if c.id == to_case_id), None)
    if target is None:
        raise ReviewError(f"no test case {to_case_id}")
    if case.id == to_case_id and len(case.steps) == 1:
        return step
    if case.id != to_case_id and len(case.steps) == 1:
        raise ReviewError("a test case cannot be left with no steps")

    case.steps = [s for s in case.steps if s.id != step_id]
    target.steps.insert(max(0, min(position, len(target.steps))), step)

    _record(
        review,
        kind=ReviewEditKind.step_moved,
        case=target,
        step_id=step_id,
        before=case.id,
        after=f"{to_case_id}[{position}]",
    )
    return step


def rename_case(
    ir: IRDocument,
    review: ReviewDocument,
    *,
    case_id: str,
    title: str | None = None,
    scenario_name: str | None = None,
) -> TestCaseIR:
    case = next((c for c in ir.testCases if c.id == case_id), None)
    if case is None:
        raise ReviewError(f"no test case {case_id}")

    before = f"{case.title} / {case.scenarioName or ''}".strip(" /")
    if title and title.strip():
        case.title = " ".join(title.split())
    if scenario_name and scenario_name.strip():
        case.scenarioName = " ".join(scenario_name.split())

    _record(
        review,
        kind=ReviewEditKind.case_renamed,
        case=case,
        before=before,
        after=f"{case.title} / {case.scenarioName or ''}".strip(" /"),
    )
    return case


def apply_feature_text(
    ir: IRDocument,
    review: ReviewDocument,
    *,
    case_id: str,
    text: str,
    rendered: str,
) -> TestCaseIR:
    """Take a hand-edited feature file and put its changes through the IR.

    SS13.2 requires accept/reject, edit, merge, split, reorder and move. The UI
    had a Feature tab that DISPLAYED the file, and every edit had to go through
    a step-shaped form -- which is a slow way to fix a sentence, and the reason
    given for it does not hold: SS13.5 needs a difficulty label per step, and a
    diff between the generated file and the approved one yields exactly the
    same label. The form was an assumption, not a requirement.

    What is a requirement is that every edit lands in the review record, so
    this parses the text back and replays it through the same functions the
    forms call. Nothing writes to the IR directly, and SS13.5's record stays
    the project's only source of difficulty labels.

    STRUCTURE IS NOT EDITABLE HERE, and refusing is the honest answer rather
    than a limitation to apologise for. A step typed into this box has no
    `eventIds`, so it is a sentence about something nobody recorded --
    `event_coverage` would reject the run, and rightly. Adding, deleting and
    reordering steps have their own controls, which keep the events attached.
    """
    case = next((c for c in ir.testCases if c.id == case_id), None)
    if case is None:
        raise ReviewError(f"no test case {case_id}")

    was = _feature_lines(rendered)
    now = _feature_lines(text)

    if len(was) != len(now):
        raise ReviewError(
            f"this edit changes the number of steps ({len(was)} to {len(now)}). "
            f"A step typed in here has no recorded actions behind it, so the run would be "
            f"rejected for dropping an event. Use the step controls to add, delete or "
            f"reorder, then edit the wording here."
        )

    # Steps and assertions in render order, which is the order `_feature_lines`
    # walked. Built from the same narrative the renderer used, so the two
    # cannot drift.
    narrative = build_narrative(case.steps)
    targets = [line for line in narrative.body if line.text.strip()]
    if len(targets) != len(now):
        raise ReviewError(
            "this feature file does not line up with the test case it came from. "
            "Reload the run and try again."
        )

    changed = 0
    for line, (_keyword, after) in zip(targets, now, strict=True):
        before = " ".join(line.text.split())
        after = " ".join(after.split())
        if before == after or not after:
            continue
        changed += 1
        if line.assertion is not None and line.step is not None:
            edit_assertion_text(
                ir, review, step_id=line.step.id, assertion_id=line.assertion.id, text=after
            )
        elif line.step is not None:
            edit_step_text(ir, review, step_id=line.step.id, text=after)

    if changed:
        resync_keywords(ir)
    return case


def _feature_lines(text: str) -> list[tuple[str, str]]:
    """Every step and expected-result line, as (keyword, body).

    A `Background` line is included: it is a step, it belongs to a case, and a
    reviewer editing one means it.
    """
    keywords = ("Given", "When", "Then", "And", "But", "*")
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        head, _, rest = line.partition(" ")
        if head in keywords and rest.strip():
            out.append((head, rest.strip()))
    return out


def approve(
    ir: IRDocument,
    review: ReviewDocument,
    *,
    reviewer: str | None = None,
    library: Any = None,
) -> ReviewDocument:
    """Approval is what feeds the step library (SS12.2).

    A step enters the library because a human accepted it, never because it was
    generated -- which is the difference between a vocabulary and a pile of
    phrasings. It is also what makes the library the project's memory: the only
    thing that gets remembered is work somebody signed off.

    Approving is the whole gesture. There is no separate "add to library"
    button, because a reviewer who has just read a test case and said yes has
    already made the only judgement the library needs, and asking twice would
    get the second answer wrong.
    """
    review.approved = True
    review.approvedAt = datetime.now(UTC)
    if reviewer:
        review.reviewer = reviewer
    review.updatedAt = datetime.now(UTC)

    if library is not None:
        for case in ir.testCases:
            for step in case.steps:
                library.add(
                    step.text,
                    role=step.role.value if step.role else None,
                    recording_id=ir.recordingId,
                    run_id=ir.runId,
                )
    return review


# --------------------------------------------------------------------------
# keeping the IR coherent
# --------------------------------------------------------------------------


def resync_keywords(ir: IRDocument) -> None:
    """Keep `Step.keyword` showing what the step will actually render as.

    Deleting or merging a step changes the keyword of the one after it -- a
    `When` promoted out of an `And` block, say -- so this runs after every edit.
    A reviewer who sees `Given` in the UI while the feature file says `And` has
    been shown two versions of the same step.
    """
    for case in ir.testCases:
        sync_keywords(case.steps)


def edited_step_ids(review: ReviewDocument) -> set[str]:
    """Which steps a human touched -- SS3.4's y-axis."""
    return {e.stepId for e in review.edits if e.stepId}


# --------------------------------------------------------------------------


def _locate(ir: IRDocument, step_id: str) -> tuple[TestCaseIR, Step]:
    for case in ir.testCases:
        for step in case.steps:
            if step.id == step_id:
                return case, step
    raise ReviewError(f"no step {step_id} in this run")


def _record(
    review: ReviewDocument,
    *,
    kind: ReviewEditKind,
    case: TestCaseIR,
    step_id: str | None = None,
    assertion_id: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> ReviewEdit:
    edit = ReviewEdit(
        id=f"edit_{len(review.edits) + 1:04d}",
        timestamp=datetime.now(UTC),
        testCaseId=case.id,
        kind=kind,
        magnitude=_magnitude(before, after),
    )
    if step_id:
        edit.stepId = step_id
    if assertion_id:
        edit.assertionId = assertion_id
    if before is not None:
        edit.before = before
    if after is not None:
        edit.after = after

    review.edits.append(edit)
    review.updatedAt = datetime.now(UTC)
    return edit


def _magnitude(before: str | None, after: str | None) -> int:
    """How large the change was.

    A one-word fix and a rewrite say different things about how hard the step
    was, and SS3.4 plots the difference.
    """
    if before is None and after is None:
        return 0
    if before is None or after is None:
        return len(before or after or "")

    import difflib

    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return sum(
        max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"
    )


__all__ = [
    "ReviewError",
    "answer_escalation",
    "apply_feature_text",
    "approve",
    "delete_step",
    "edit_assertion_text",
    "edit_step_text",
    "edited_step_ids",
    "merge_steps",
    "move_step",
    "new_review",
    "rename_case",
    "resync_keywords",
    "set_assertion",
]
