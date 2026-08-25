"""Gherkin renderer (SS11.1).

One of three renderers over the same IR -- no format is second-class, and a
fourth output means writing a renderer rather than touching the pipeline
(SS10).

The `.feature` file is the only artifact most people will ever see, so the body
is kept to what a QA lead would have written by hand: keywords, sentences,
nothing else. Traceability is not lost, it moves -- `trace_md.py` writes it
beside the feature, `ir.json` and `trace.json` hold the machine-readable form,
and the validators read those rather than this. A comment under every step made
the tool look like it was talking to itself.

    "Selectors live in comments and IR metadata, not in step text -- the
     feature file stays human-readable while retaining what automation needs
     later."
"""

from __future__ import annotations

import re
import textwrap

from server.config import ProjectConfig
from server.models import FidelityFlag, IRDocument, Step, TestCaseIR
from server.pipeline.narrative import Line, Narrative, build_narrative
from server.renderers.base import test_cases

INDENT = "  "
GENERATOR = "aitc-rem"
WIDTH = 78

#: SS6.8 splits its flags into warnings and notices. Only the warnings mean
#: "my description may be wrong"; the notices are housekeeping. Marking a step
#: for review on a notice is why six of seven steps once carried the marker,
#: which trains the reader to ignore all of them.
NOTICE_FLAGS = frozenset(
    {
        FidelityFlag.file_content_omitted,
        FidelityFlag.rapid_sequence,
        FidelityFlag.network_incomplete,
        # Raised while BUILDING the snapshot, for any closed shadow root
        # anywhere on the page -- not for the thing the tester acted on. The
        # demo app has one `<promo-widget>` on its checkout page, so six of
        # seven fixtures inherited it and six of seven feature files came out
        # tagged `@needs-review`: precisely the devaluation the paragraph above
        # describes, arriving again by a different route.
        #
        # It is a true statement about the snapshot and a false one about the
        # step. Something on the page was unreadable; that says nothing about
        # whether this step's description is right, and only the second is what
        # the marker means.
        #
        # The better fix is in the recorder: raise it as a warning only when
        # the ACTION TARGET is inside the closed root, which is the case SS6.8
        # actually describes ("contents of this component were not readable").
        # `content/snapshot.ts:buildChildren` is where that would go.
        FidelityFlag.closed_shadow_root,
    }
)

REVIEW_TAG = "needs-review"

#: `<<name>>` as written by redaction (SS7.1), which becomes `<name>` in a
#: Scenario Outline because that is the placeholder syntax Gherkin knows.
PLACEHOLDER = re.compile(r"<<([a-z0-9_]+)>>", re.IGNORECASE)


def render_document(
    ir: IRDocument,
    *,
    generated_on: str | None = None,
    config: ProjectConfig | None = None,
) -> dict[str, str]:
    """Render every test case. Returns testCaseId -> feature text.

    A bug report is skipped, and not as a formatting preference. SS14 makes it a
    different KIND of artifact -- historical and evidentiary, where a test case
    is future-facing and reusable -- and Gherkin is a language for saying what
    should happen. A `.feature` whose scenario is a defect would be run by a
    suite and would fail on purpose. `server/renderers/bug_md.py` writes those.
    """
    return {
        case.id: render_test_case(case, ir=ir, generated_on=generated_on, config=config)
        for case in ir.testCases
        if case.kind != "bug_report"
    }


def render_test_case(
    case: TestCaseIR,
    *,
    ir: IRDocument | None = None,
    generated_on: str | None = None,
    config: ProjectConfig | None = None,
) -> str:
    config = config or ProjectConfig()
    date = generated_on or (ir.createdAt.date().isoformat() if ir else "")

    # SS9.3 -- `Background` is indirection with a single scenario: the whole test
    # reads better top to bottom and a reader has one place to look. It earns
    # its keep only when a recording produced several cases that share setup,
    # which is exactly when repeating the sign-in three times would be worse.
    #
    # Counted over the cases that are actually RENDERED. A bug report shares the
    # document and is not a scenario, so counting it here would lift a Background
    # out of a single-scenario feature -- which is both wrong and, until
    # `_background` was fixed below, silently lossy.
    siblings = len(test_cases(ir)) if ir else 1
    narrative = build_narrative(case.steps, lift_background=siblings > 1)
    outline = _outline_names(case, narrative, config)

    lines: list[str] = []
    lines.extend(_header(case, date, config))
    lines.extend(_tags(case, narrative, config))
    lines.append(f"Feature: {_one_line(_feature_title(case))}")
    lines.extend(_description(case))
    lines.extend(_background(case, narrative, outline))
    lines.extend(_scenario(case, narrative, outline))
    lines.extend(_omissions(case))
    lines.extend(_examples(case, outline))

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def _header(case: TestCaseIR, date: str, config: ProjectConfig) -> list[str]:
    """One line, or none. Where the file came from and where its evidence is.

    Kept because a generated artifact that hides its provenance is worse than
    one that states it, and because a reader who wants the audit trail should
    not have to be told twice where to look.
    """
    if not config.header:
        return []

    parts = [GENERATOR, case.recordingId]
    if date:
        parts.append(date)
    if config.trace == "sidecar":
        parts.append(f"evidence: {trace_filename(case, config)}")
    return [f"# {' - '.join(parts)}", ""]


def _tags(case: TestCaseIR, narrative: Narrative, config: ProjectConfig) -> list[str]:
    tags: list[str] = []
    for tag in [*case.tags, *config.tags]:
        cleaned = tag.strip().lstrip("@")
        if cleaned and cleaned not in tags:
            tags.append(cleaned)

    # A scenario carrying a question for the human says so where CI and a
    # `--tags` filter can both see it, instead of with punctuation glued to a
    # sentence that a step definition has to match.
    if any(needs_review(step) for step in case.steps) and REVIEW_TAG not in tags:
        tags.append(REVIEW_TAG)

    # Xray's feature-file import reads `@TEST_<KEY>` as "update this existing
    # Test rather than creating another one", which is how a re-import stops
    # being a duplicate. Off unless a project asks: for everyone else it is a
    # meaningless tag in a file they have to read.
    if config.xray_test_key:
        key = f"TEST_{config.xray_test_key.lstrip('@').removeprefix('TEST_')}"
        if key not in tags:
            tags.insert(0, key)

    return [" ".join(f"@{t}" for t in tags)] if tags else []


def _feature_title(case: TestCaseIR) -> str:
    return case.title or case.recordingId


def _description(case: TestCaseIR) -> list[str]:
    """Gherkin's own free-text block, which is where this belongs.

    The objective used to ride in a `#` comment above the Feature. A comment is
    for the machine; the description is part of the document, and Cucumber
    reports render it.
    """
    text = _one_line(case.description)
    if not text or _same(text, case.title) or _same(text, _scenario_name(case)):
        return []
    wrapped = textwrap.wrap(text, width=WIDTH - len(INDENT))
    return ["", *[f"{INDENT}{line}" for line in wrapped]]


def _background(case: TestCaseIR, narrative: Narrative, outline: list[str]) -> list[str]:
    """Explicit preconditions only.

    Leading `setup` steps stay inside the scenario: with one scenario a
    `Background` is indirection for no gain, and the test reads better top to
    bottom. Decomposition lifts them once a recording yields several scenarios
    that genuinely share setup (SS9.3).
    """
    lines = ["", f"{INDENT}Background:"]

    # The lifted steps come first, because `build_narrative` has already decided
    # which they are and assigned their keywords.
    #
    # This branch did not exist, and its absence DELETED them: `lift_background`
    # moved the leading setup steps into `narrative.background` and nothing
    # rendered that, so every multi-scenario recording lost its sign-in from the
    # feature file. Nothing caught it -- `event_coverage` reads the IR rather
    # than the rendered output, and a file missing a step still parses.
    if narrative.background:
        for line in narrative.background:
            lines.append(f"{INDENT * 2}{line.keyword} {_step_text(line.text, outline)}")
        return lines

    shared = [p for p in case.preconditions if p.shared] or case.preconditions
    if not shared:
        return []

    for index, precondition in enumerate(shared):
        keyword = "Given" if index == 0 else "And"
        text = _step_text(precondition.text, outline)
        lines.append(f"{INDENT * 2}{keyword} {text}")
    return lines


def _scenario(case: TestCaseIR, narrative: Narrative, outline: list[str]) -> list[str]:
    keyword = "Scenario Outline" if outline else "Scenario"
    lines = ["", f"{INDENT}{keyword}: {_one_line(_scenario_name(case))}"]

    # Blank lines between beats help a long scenario and make a short one look
    # sparse, so they are spent only where there is something to separate.
    spaced = narrative.beats > 1
    previous_beat: int | None = None

    for line in narrative.body:
        if spaced and previous_beat is not None and line.beat != previous_beat:
            lines.append("")
        previous_beat = line.beat
        lines.append(f"{INDENT * 2}{line.keyword} {_step_text(line.text, outline)}")

    return lines


def _omissions(case: TestCaseIR) -> list[str]:
    """Pruned work is marked where it happened.

    Not traceability -- completeness. A reader has to know the narrative is not
    the whole session, or they will trust it for something it does not cover
    (SS9.3).
    """
    lines: list[str] = []
    for omitted in case.omitted:
        anchor = f" after {omitted.afterStepId}" if omitted.afterStepId else ""
        lines.append("")
        lines.append(
            f"{INDENT * 2}# {omitted.eventCount} {omitted.reason.value} action(s) omitted"
            f"{anchor} - {_one_line(omitted.summary)}. See the review UI."
        )
    return lines


def _examples(case: TestCaseIR, outline: list[str]) -> list[str]:
    if not outline:
        return []
    by_name = {p.name: p for p in case.parameters}
    values = [by_name[name].placeholder if name in by_name else f"<<{name}>>" for name in outline]
    return [
        "",
        f"{INDENT * 2}Examples:",
        f"{INDENT * 3}| {' | '.join(outline)} |",
        f"{INDENT * 3}| {' | '.join(values)} |",
    ]


# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------


def _outline_names(case: TestCaseIR, narrative: Narrative, config: ProjectConfig) -> list[str]:
    """Which parameters a `Scenario Outline` would be built from.

    Empty in `inline` mode, which is the default: a tester executing the test
    reads top to bottom, and a single-row `Examples` table makes them look in
    two places to find one value. An Outline earns its keep when a project
    genuinely runs several rows.
    """
    if config.parameters != "outline":
        return []

    body = " ".join(
        [*(line.text for line in narrative.body), *(p.text for p in case.preconditions)]
    )
    found = [m.group(1) for m in PLACEHOLDER.finditer(body)]
    return list(dict.fromkeys(found))


def _step_text(text: str, outline: list[str]) -> str:
    text = _one_line(text)
    if not outline:
        return text
    return PLACEHOLDER.sub(
        lambda m: f"<{m.group(1)}>" if m.group(1) in outline else m.group(0), text
    )


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def needs_review(step: Step) -> bool:
    """Does a human have to look at this step before it can be trusted?

    An escalation or low confidence always. A fidelity flag only when it is one
    of SS6.8's warnings -- `network_incomplete` on a step whose description is
    perfectly sound is a notice, and marking it review-worthy devalues the
    marker everywhere else.
    """
    if step.escalation or step.confidence.value == "low":
        return True
    # A finding nothing resolved. `_annotate` writes every unrepaired critic
    # finding and every claim the gate rejected onto the step as a note, and
    # this did not look at them -- so a step the run itself had said was wrong
    # went out with no marker on it at all. A wrong number shipped that way,
    # confident and untagged, while the same run's `ir.json` recorded that its
    # literal did not appear where it claimed.
    if step.criticNotes:
        return True
    return any(flag not in NOTICE_FLAGS for flag in step.fidelity)


def trace_filename(case: TestCaseIR, config: ProjectConfig | None = None) -> str:
    config = config or ProjectConfig()
    stem = config.feature_stem(case_id=case.id, title=case.title, recording_id=case.recordingId)
    return f"{stem}.trace.md"


def feature_filename(case: TestCaseIR, config: ProjectConfig | None = None) -> str:
    config = config or ProjectConfig()
    stem = config.feature_stem(case_id=case.id, title=case.title, recording_id=case.recordingId)
    return f"{stem}.feature"


def _scenario_name(case: TestCaseIR) -> str:
    if case.scenarioName:
        return case.scenarioName
    if case.description and not _same(case.description, case.title):
        return case.description.splitlines()[0]
    return case.title


def _one_line(text: str) -> str:
    """Gherkin is line-oriented; a newline inside a step would break the file."""
    return " ".join((text or "").split())


def _same(a: str | None, b: str | None) -> bool:
    return _one_line(a or "").rstrip(".").casefold() == _one_line(b or "").rstrip(".").casefold()


__all__ = [
    "Line",
    "feature_filename",
    "needs_review",
    "render_document",
    "render_test_case",
    "trace_filename",
]
