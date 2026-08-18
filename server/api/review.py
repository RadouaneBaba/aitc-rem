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

from server.models import (
    IRDocument,
    ReviewDocument,
    ReviewEdit,
    ReviewEditKind,
    Step,
    TestCaseIR,
)
from server.pipeline.narrative import sync_keywords


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


def approve(
    ir: IRDocument, review: ReviewDocument, *, reviewer: str | None = None
) -> ReviewDocument:
    """Approval is what feeds the step library (SS12.2).

    A step enters the library because a human accepted it, never because it was
    generated -- which is the difference between a vocabulary and a pile of
    phrasings.
    """
    del ir
    review.approved = True
    review.approvedAt = datetime.now(UTC)
    if reviewer:
        review.reviewer = reviewer
    review.updatedAt = datetime.now(UTC)
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
    "approve",
    "delete_step",
    "edit_step_text",
    "edited_step_ids",
    "merge_steps",
    "move_step",
    "new_review",
    "rename_case",
    "resync_keywords",
    "set_assertion",
]
