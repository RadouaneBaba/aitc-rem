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
GENERATOR = "AITC"
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
    """Render the recording as ONE feature file. Returns {key: feature text}.

    One file, every scenario -- which is what the author writes, what
    `styles/automation.md` shows it, and what a QA lead expects to open.

    It used to be one file PER TEST CASE, and that is what a reader actually
    saw: `rec_MTEU954A8F5X/run_003` wrote two files with the same `Feature:`
    line, the same description and the same `Background`, and
    `rec_MTE6XZL14IY9/run_001` wrote three. A `Feature:` is a capability and a
    `Scenario` is one way of exercising it, so splitting them made the output
    announce the same capability N times and forced the review UI to swap the
    document under the reader whenever they selected a step in another
    scenario.

    `TestCaseIR` stays one-per-scenario. This is a rendering change only, and
    deliberately so: the replay runner drives `case.preconditions` and
    `case.steps`, and the exporters number their rows per case.

    The key is the FIRST rendered case's id, so every id-addressed path -- the
    filename, `_write_output`'s stale-file sweep, `PATCH .../cases/{id}/feature`
    -- keeps working unchanged.

    A bug report is skipped, and not as a formatting preference. SS14 makes it a
    different KIND of artifact -- historical and evidentiary, where a test case
    is future-facing and reusable -- and Gherkin is a language for saying what
    should happen. A `.feature` whose scenario is a defect would be run by a
    suite and would fail on purpose. `server/renderers/bug_md.py` writes those.
    """
    cases = test_cases(ir)
    if not cases:
        return {}
    return {cases[0].id: _render(cases, ir=ir, generated_on=generated_on, config=config)}


def render_test_case(
    case: TestCaseIR,
    *,
    ir: IRDocument | None = None,
    generated_on: str | None = None,
    config: ProjectConfig | None = None,
) -> str:
    """One case as a whole file. The single-scenario case of `_render`."""
    return _render([case], ir=ir, generated_on=generated_on, config=config)


def _render(
    cases: list[TestCaseIR],
    *,
    ir: IRDocument | None = None,
    generated_on: str | None = None,
    config: ProjectConfig | None = None,
) -> str:
    config = config or ProjectConfig()
    date = generated_on or (ir.createdAt.date().isoformat() if ir else "")
    first = cases[0]

    # SS9.3 -- `Background` is indirection with a single scenario: the whole test
    # reads better top to bottom and a reader has one place to look. It earns
    # its keep only when a recording produced several scenarios that share
    # setup, which is exactly when repeating the sign-in three times would be
    # worse.
    #
    # Lifted from the FIRST scenario only, and this is what removes the
    # duplication rather than merely relocating it. Every later case's
    # `preconditions` ARE the earlier cases' setup steps (`run._build_case`), so
    # rendering both a `Background` of preconditions and the scenario that
    # performed them printed the same two sentences twice in one file --
    # visible on `rec_MTE5BVCZO8QU/run_008`. Here the shared opening is stated
    # once, at the top, and the scenarios below it are what differs.
    narratives = [
        build_narrative(case.steps, lift_background=(index == 0 and len(cases) > 1))
        for index, case in enumerate(cases)
    ]
    outlines = [_outline_names(case, nar, config) for case, nar in zip(cases, narratives, strict=True)]

    lines: list[str] = []
    lines.extend(_header(cases, date, config))
    lines.extend(_tags(cases, config))
    lines.append(f"Feature: {_one_line(_feature_title(first))}")
    lines.extend(_description(first))
    lines.extend(_background(first, narratives[0], outlines[0]))

    for case, narrative, outline in zip(cases, narratives, outlines, strict=True):
        lines.extend(_scenario(case, narrative, outline))
        lines.extend(_unproved(case))
        lines.extend(_omissions(case))
        lines.extend(_examples(case, outline))

    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# blocks
# --------------------------------------------------------------------------


def _header(cases: list[TestCaseIR], date: str, config: ProjectConfig) -> list[str]:
    """One line, or none. Where the file came from and where its evidence is.

    Kept because a generated artifact that hides its provenance is worse than
    one that states it, and because a reader who wants the audit trail should
    not have to be told twice where to look.

    The sidecar is still one per test case while the feature file is one per
    document, so every sidecar is named. Naming only the first would point a
    reader at `tc_..._01.trace.md` for evidence that lives in `_02`, which is a
    provenance line that misleads -- worse than none at all.
    """
    if not config.header:
        return []

    parts = [GENERATOR, cases[0].recordingId]
    if date:
        parts.append(date)
    if config.trace == "sidecar":
        sidecars = ", ".join(trace_filename(case, config) for case in cases)
        parts.append(f"evidence: {sidecars}")
    return [f"# {' - '.join(parts)}", ""]


def document_feature_filename(ir: IRDocument, config: ProjectConfig | None = None) -> str:
    """The one file every scenario of this recording is written to.

    A sidecar points back at its feature file, and with one file per document
    the per-case name it used to compute is wrong for every case but the first.
    """
    config = config or ProjectConfig()
    cases = test_cases(ir)
    return feature_filename(cases[0], config) if cases else ""


def _tags(cases: list[TestCaseIR], config: ProjectConfig) -> list[str]:
    """Feature-level tags: what is true of the whole document.

    `@needs-review` is NOT here. It belongs to the scenario that earned it
    (`_scenario`): a document of four scenarios where one could not be proved
    should send a reader to that one, and a feature-level tag sends them to all
    four. Xray reads a scenario tag onto the Test it creates, so the marker
    also lands on the right issue rather than on every issue.
    """
    tags: list[str] = []
    for tag in [t for case in cases for t in case.tags] + list(config.tags):
        cleaned = tag.strip().lstrip("@")
        if cleaned and cleaned != REVIEW_TAG and cleaned not in tags:
            tags.append(cleaned)

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
    # Inherited preconditions FIRST, then the setup this case lifted out of its
    # own scenario. Both, in that order, and neither optional.
    #
    # This used to `return` after the lifted lines, which dropped
    # `case.preconditions` entirely -- and `_build_case` fills those for case 2
    # onwards with the setup steps of EARLIER cases, precisely so each scenario
    # is runnable standalone. So the second test case out of a recording lost
    # the sign-in the first one performed, whenever its own steps happened to
    # begin with a setup step. Sibling of the bug where `lift_background` moved
    # steps into a list nothing rendered: if you add anything to `Narrative`,
    # check that a renderer reads it.
    shared = [p for p in case.preconditions if p.shared] or case.preconditions
    if not shared and not narrative.background:
        return []

    lines = ["", f"{INDENT}Background:"]
    for index, precondition in enumerate(shared):
        keyword = "Given" if index == 0 else "And"
        lines.append(f"{INDENT * 2}{keyword} {_step_text(precondition.text, outline)}")

    for index, line in enumerate(narrative.background):
        # `build_narrative` assigned these keywords against a block that started
        # empty. Once preconditions precede them, the first one continues that
        # block rather than opening one.
        keyword = "And" if shared and index == 0 and line.keyword == "Given" else line.keyword
        lines.append(f"{INDENT * 2}{keyword} {_step_text(line.text, outline)}")
    return lines


def _scenario(case: TestCaseIR, narrative: Narrative, outline: list[str]) -> list[str]:
    has_table = bool(outline) or bool(case.examples and case.examples.columns)
    keyword = "Scenario Outline" if has_table else "Scenario"
    lines = [""]

    # A scenario carrying a question for the human says so where CI and a
    # `--tags` filter can both see it, instead of with punctuation glued to a
    # sentence that a step definition has to match. On the scenario rather than
    # the feature, so a document of four scenarios points at the one that needs
    # looking at -- see `_tags`.
    if any(needs_review(step) for step in case.steps):
        lines.append(f"{INDENT}@{REVIEW_TAG}")

    lines.append(f"{INDENT}{keyword}: {_one_line(_scenario_name(case))}")

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


def _unproved(case: TestCaseIR) -> list[str]:
    """Verdicts the author wanted and could not prove, named in the file itself.

    A scenario that checks nothing is the one output a reader cannot tell apart
    from a scenario that had nothing worth checking, and `@needs-review` says
    only that something is wrong. This says which sentence and why, in the
    author's own words -- *"the product list was never captured before or after
    this click"* -- so the file that gets imported into Xray and mailed around
    carries the doubt with it. Until now `whyNot` reached `ir.json` (`run._assemble`)
    and was rendered nowhere at all.

    Placed AFTER the scenario body, beside `_omissions` and for the same reason:
    the body is prose and nothing else -- no ids, no markers, no fidelity flags
    interleaved with the steps. A trailing note is not that; it is the same
    completeness contract omissions already have, and it keeps the steps
    themselves readable as a hand-written feature file.

    Keyed on `whyNot` alone, exactly as `needs_review` is, and the two must not
    drift: a marker on a scenario whose file says nothing about why is the
    unclickable red badge this project already removed once. `_attach_claim`
    clears `why_not` when a claim lands, so a step carrying BOTH an accepted
    assertion and a `whyNot` means a second claim was refused -- still a gap,
    still worth naming.
    """
    lines: list[str] = []
    for step in case.steps:
        if not step.whyNot:
            continue
        lines.append("")
        lines.append(f'{INDENT * 2}# unchecked - {_one_line(step.text)}')
        lines.append(f"{INDENT * 2}#   {_one_line(step.whyNot)}")
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
    """The `Examples` table, from whichever of the two sources supplied one.

    The AUTHOR's table wins where it exists, and it is the more interesting of
    the two: it means the author judged that one flow was exercised with several
    sets of values, which is the difference between a recording that reads as a
    transcript and one that reads as test design. A recording that adds 13 items
    and then 18 otherwise comes out as two near-identical scenarios.

    `parameters: outline` is the other source and is a RENDERING setting -- it
    lifts redaction placeholders into a one-row table. One row is not really a
    table, which is why `inline` is the default.
    """
    if case.examples and case.examples.columns and case.examples.rows:
        # Padded to a grid. Gherkin does not require it and every reader does:
        # a ragged table is the difference between a document somebody wrote
        # and a document something emitted.
        grid = [list(case.examples.columns), *(list(r) for r in case.examples.rows)]
        widths = [max(len(row[i]) for row in grid) for i in range(len(grid[0]))]
        rows = [
            f"{INDENT * 3}| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + " |"
            for row in grid
        ]
        return ["", f"{INDENT * 2}Examples:", *rows]

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
    # An author-declared table already decides this, and its columns are its
    # own -- angle-bracket placeholders the author wrote into the step text,
    # not redaction parameters. Returning names here would make `_step_text`
    # rewrite `<<password>>` into `<password>` in a scenario whose table has no
    # such column.
    if case.examples and case.examples.columns:
        return []
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
    # A verdict the author wanted and could not prove.
    #
    # This is the condition that actually fires. `criticNotes` below is the one
    # that was SUPPOSED to, and nothing has written it since the critic was
    # deleted -- `narrative._absorb` merges notes that already exist and no
    # other site sets the field -- so the tag has been unreachable for every run
    # since. `rec_MTEU954A8F5X/run_003` shipped three judge `fail`s and no
    # `@needs-review` on either scenario.
    #
    # `whyNot` is what a refusal leaves behind (`author._refuse`), and reading
    # it here matters for a second reason: `api._save` re-renders this file on
    # every review edit with no access to the run, the report or the author's
    # document, so anything the tag depends on has to survive in `ir.json`.
    if step.whyNot:
        return True
    # A finding nothing resolved. Kept for the artifacts already on disk that
    # carry notes from when the critic existed: every model is
    # `additionalProperties: false`, so a field cannot be deleted, only left
    # unwritten.
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
