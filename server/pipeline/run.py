"""The pipeline skeleton (SS9.1).

    "A fixed deterministic skeleton with agentic stages. Each stage reads a
     file and writes a file, so when output is wrong you open the intermediate
     artifact and see exactly which stage lied."

    segment (code) -> name (agentic) -> compose (agentic) -> validate (code)
    -> render

Composition sits between naming and rendering because the document-level
decisions -- what the feature is called, what each step is doing in the test --
need every step in view and none of them need to exist before naming runs. The
ranked assertion stage, the step library, the critic and the repair loop slot
into the same shape without changing it.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    AblationConfig,
    AgentTrace,
    Confidence,
    IRDocument,
    PipelineStage,
    Recording,
    RunConfig,
    RunMetrics,
    SegmentRole,
    SelectorHint,
    StageRecord,
    StageStatus,
    Step,
    TestCaseIR,
    TestCaseMetadata,
    TruncationPolicy,
    ValidatorStatus,
    Warning,
)
from server.pipeline.assertions import ASSERT_BUDGET, AssertionResult, propose_assertions
from server.pipeline.compose import (
    COMPOSE_BUDGET,
    ComposeResult,
    compose_test_case,
    fallback_composition,
)
from server.pipeline.investigate import DEFAULT_BUDGET
from server.pipeline.name import NamingResult, name_segments, split_named
from server.pipeline.narrative import (
    apply_merges,
    apply_splits,
    keyword_for_role,
    merge_repeats,
    sync_keywords,
)
from server.pipeline.segment import segment_recording
from server.pipeline.validators import ValidationContext, ValidationReport, grounding_rate, validate
from server.renderers import trace_md
from server.renderers.gherkin import feature_filename, render_document, trace_filename
from server.storage.paths import RunPaths, Storage


@dataclass
class PipelineOptions:
    """Everything the ablation flips with one flag (SS3.5)."""

    ablation: AblationConfig = AblationConfig.A2
    tools_enabled: bool = True
    critic_enabled: bool = False
    repair_enabled: bool = False
    budget: int = DEFAULT_BUDGET
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.0
    fallback_enabled: bool = True
    cassette_mode: str = "read_write"
    #: House style for the rendered artifacts. Named `project` rather than
    #: `config` because `for_config` already means the ablation configuration,
    #: and two things called config in one signature is how a caller silently
    #: sets the wrong one. Never affects what is true, only how it reads.
    project: ProjectConfig = field(default_factory=ProjectConfig)
    #: Composition runs in every ablation configuration. It makes no assertions
    #: and so cannot move the grounding rate; turning it off for A0 would make
    #: the comparison measure readability instead of architecture.
    compose_enabled: bool = True
    #: Pre-declared for A0, whose whole-context prompt will not fit a long
    #: recording. Silent truncation would make the ablation measure truncation
    #: rather than architecture.
    a0_token_budget: int = 120_000
    #: Called as each stage begins. The run takes minutes -- deliberately, per
    #: SS9.11 -- but "deliberately slow" and "hung" look identical to someone
    #: watching a browser tab, and the second thing they do is press Stop again.
    #: Observation only: a callback that raises must not lose a run, so the
    #: caller's exceptions are swallowed at the call site.
    on_stage: Callable[[PipelineStage], None] | None = None
    #: SS12's approved phrasing, shared by the naming stage and the validator.
    #: `None` is a project with no history, which every project starts as.
    library: Any = None

    @classmethod
    def for_config(cls, config: AblationConfig, **overrides: Any) -> PipelineOptions:
        presets = {
            AblationConfig.A0: {
                "tools_enabled": False,
                "critic_enabled": False,
                "repair_enabled": False,
            },
            AblationConfig.A1: {
                "tools_enabled": True,
                "critic_enabled": False,
                "repair_enabled": False,
            },
            AblationConfig.A2: {
                "tools_enabled": True,
                "critic_enabled": True,
                "repair_enabled": True,
            },
        }
        return cls(ablation=config, **{**presets[config], **overrides})


@dataclass
class PipelineResult:
    recording: Recording
    run: RunPaths
    ir: IRDocument
    trace: AgentTrace
    report: ValidationReport
    rendered: dict[str, str]
    naming: NamingResult
    grounding_rate: float
    duration_ms: float
    compose: ComposeResult | None = None
    assertions: AssertionResult | None = None
    sidecars: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)

    @property
    def tool_calls_per_step(self) -> dict[str, int]:
        """Retrievals per step, summed across every stage that investigated it.

        The x-axis of SS3.4. Read from the trace rather than from any one
        stage: effort is what the run spent on a step, and naming's share of it
        stopped being the whole story when the assertion stage landed.
        """
        return dict(self.trace.metrics.toolCallsPerStep or {}) if self.trace.metrics else {}


def run_pipeline(
    recording: Recording,
    model: ModelClient,
    *,
    storage: Storage,
    run_id: str,
    options: PipelineOptions | None = None,
) -> PipelineResult:
    options = options or PipelineOptions()
    started = time.perf_counter()
    run = storage.run(recording.id, run_id)
    stages: list[StageRecord] = []

    def announce(stage: PipelineStage) -> None:
        """Tell the caller which stage is starting, and never fail because of it.

        A progress callback is the least important thing in this function and
        must not be able to end a run that was otherwise going to succeed.
        """
        if options.on_stage is None:
            return
        with contextlib.suppress(Exception):
            options.on_stage(stage)

    # -- 1. segment (deterministic) ---------------------------------------
    announce(PipelineStage.segment)
    t0 = time.time()
    segments = segment_recording(recording, run_id=run_id)
    path = storage.save_artifact(run, "segments", segments)
    stages.append(
        StageRecord(
            stage=PipelineStage.segment,
            attempt=1,
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    store = EvidenceStore(recording=recording, segments=segments)
    runner = ToolRunner(
        store=store, storage=storage, run=run, stage=PipelineStage.name, library=options.library
    )

    # -- 2. name (agentic) -------------------------------------------------
    announce(PipelineStage.name)
    t0 = time.time()
    naming = name_segments(
        store,
        runner,
        model,
        model_name=options.model_name,
        budget=options.budget,
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
        config=options.project,
    )
    path = storage.save_artifact(run, "naming", naming.to_artifact())
    stages.append(
        StageRecord(
            stage=PipelineStage.name,
            attempt=1,
            inputPath=run.relative(run.artifact("segments")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    # -- 3. assert (agentic) -----------------------------------------------
    announce(PipelineStage.assert_)
    #
    # Before composition, so the roles and the scenario name are decided with
    # the expected results in view: a step that produced a checkable outcome is
    # rarely setup, and the title of a test is largely what it verifies.
    t0 = time.time()
    proposed = _assert(store, runner, model, naming, options)
    path = storage.save_artifact(run, "assertions", proposed.to_artifact())
    stages.append(
        StageRecord(
            stage=PipelineStage.assert_,
            attempt=1,
            inputPath=run.relative(run.artifact("naming")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    # -- 4. compose (agentic) ---------------------------------------------
    announce(PipelineStage.decompose)
    t0 = time.time()
    composed = _compose(store, runner, model, naming, options)

    # A split makes two steps out of one, and neither is the step the assertion
    # stage was asked about. Reconsider just those, and only when it happened:
    # inheriting the old step's expected results is how the successful retry
    # ended up saying nothing while "Order confirmed" -- the outcome the test
    # exists to reach -- went unmentioned.
    if composed.splits:
        naming, resplit = split_named(naming, composed.splits)
        proposed = _merge_assertions(
            proposed,
            propose_assertions(
                store,
                runner,
                model,
                naming,
                model_name=options.model_name,
                budget=ASSERT_BUDGET if options.tools_enabled else 0,
                tools_enabled=options.tools_enabled,
                temperature=options.temperature,
                config=options.project,
                only=resplit,
            ),
            replacing=resplit,
        )

    ir = _assemble(recording, run_id, naming, composed, proposed)
    path = storage.save_artifact(run, "ir", ir)
    stages.append(
        StageRecord(
            stage=PipelineStage.decompose,
            attempt=1,
            inputPath=run.relative(run.artifact("assertions")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.degraded if composed.degraded else StageStatus.ok,
        )
    )

    # -- 5. render ---------------------------------------------------------
    announce(PipelineStage.render)
    t0 = time.time()
    trace = _trace(recording, run_id, options, runner, naming, composed, proposed)
    rendered = render_document(ir, config=options.project)
    sidecars: dict[str, str] = {}
    if options.project.trace == "sidecar":
        sidecars = trace_md.render_document(ir, trace=trace, config=options.project)
    _write_output(run, ir, rendered, sidecars, options.project)
    stages.append(
        StageRecord(
            stage=PipelineStage.render,
            attempt=1,
            outputPath=run.relative(run.root / "features"),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    # -- 6. validate (deterministic gate) ----------------------------------
    announce(PipelineStage.validate)
    t0 = time.time()
    ctx = ValidationContext(
        recording=recording,
        ir=ir,
        trace=trace,
        storage=storage,
        run=run,
        segments=segments,
        rendered=rendered,
        library=options.library,
    )
    report = validate(ctx)
    trace.validatorResults = report.results
    rate = grounding_rate(ctx, report)
    trace.metrics = _metrics(
        ir,
        naming,
        composed,
        proposed,
        report,
        rate,
        time.perf_counter() - started,
        trace.toolCalls,
    )
    stages.append(
        StageRecord(
            stage=PipelineStage.validate,
            attempt=1,
            outputPath=run.relative(run.artifact("trace")),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok if report.ok else StageStatus.failed,
        )
    )

    trace.stages = stages
    trace_path = storage.save_artifact(run, "trace", trace)

    # The output is emitted even when the gate rejects it. Phase 1 has no
    # repair loop, so hiding a rejected draft would leave nothing to inspect --
    # and the report says plainly what is wrong with it. The one exception is a
    # leaked secret, which must not be written at all (SS9.7).
    if report.hard_failed:
        _erase_output(run, ir, options.project)
        rendered, sidecars = {}, {}

    return PipelineResult(
        recording=recording,
        run=run,
        ir=ir,
        trace=trace,
        report=report,
        rendered=rendered,
        sidecars=sidecars,
        naming=naming,
        compose=composed,
        assertions=proposed,
        grounding_rate=rate,
        duration_ms=(time.perf_counter() - started) * 1000,
        artifacts={
            "segments": run.artifact("segments"),
            "naming": run.artifact("naming"),
            "assertions": run.artifact("assertions"),
            "ir": run.artifact("ir"),
            "trace": trace_path,
        },
    )


# --------------------------------------------------------------------------


def _assert(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming: NamingResult,
    options: PipelineOptions,
) -> AssertionResult:
    """Propose ranked expected results (SS9.5)."""
    return propose_assertions(
        store,
        runner,
        model,
        naming,
        model_name=options.model_name,
        budget=min(ASSERT_BUDGET, options.budget),
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
        config=options.project,
    )


def _compose(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming: NamingResult,
    options: PipelineOptions,
) -> ComposeResult:
    """Compose the document, or fall back to something readable.

    A model failure here must not cost the run: naming has already produced the
    expensive, evidence-bound part, and a plainer title is a far better outcome
    than losing it. The fallback is recorded as `degraded` rather than passed
    off as a composition that happened.
    """
    if not options.compose_enabled:
        return _degraded(store, naming)
    try:
        return compose_test_case(
            store,
            runner,
            model,
            naming,
            model_name=options.model_name,
            budget=min(COMPOSE_BUDGET, options.budget),
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
        )
    except Exception:  # noqa: BLE001 - any provider failure, surfaced as degraded
        return _degraded(store, naming)


def _degraded(store: EvidenceStore, naming: NamingResult) -> ComposeResult:
    return fallback_composition(store, naming)


def _assemble(
    recording: Recording,
    run_id: str,
    naming: NamingResult,
    composed: ComposeResult,
    proposed: AssertionResult,
) -> IRDocument:
    """One test case in Phase 1. Decomposition into N is SS9.3."""
    candidates = proposed.by_step()
    steps = [
        Step(
            id=named.step_id,
            keyword=keyword_for_role(composed.roles.get(named.step_id, named.role)),
            role=composed.roles.get(named.step_id, named.role),
            text=named.text,
            eventIds=named.event_ids,
            investigationRef=named.investigation.id,
            assertions=candidates.get(named.step_id, []),
            confidence=named.confidence,
            fidelity=_flags(recording, named.event_ids),
            selectorHints=_selector_hints(recording, named.event_ids),
            **({"escalation": named.escalation} if named.escalation else {}),
            **({"libraryRef": named.library_ref} if named.library_ref else {}),
        )
        for named in naming.steps
    ]

    # Merging happens once, here, so `ir.json` and the rendered feature always
    # show the same steps. Composition supplies the judgment (it read the whole
    # flow); `merge_repeats` is the net for an exact repeat it did not catch.
    # Splits first. A split can turn one step into two that a merge group was
    # never written about, whereas a merge can absorb a step a split was going
    # to cut -- doing it the other way round loses the cut silently.
    steps = merge_repeats(
        apply_merges(
            apply_splits(steps, composed.splits),
            [group.step_ids for group in composed.merges],
            texts={
                sid: group.text for group in composed.merges for sid in group.step_ids if group.text
            },
        )
    )
    # SS9.3 -- a recorded sitting is a person working, and their wrong turns are
    # not test steps. Pruned rather than deleted: `omitted` is rendered where it
    # happened, so a reader knows the narrative is not the whole session and
    # does not trust it for something it never covered.
    steps, omitted = _prune(steps, {n.step_id: n.segment_id for n in naming.steps})
    sync_keywords(steps)

    # Fidelity totals belong with the evidence, not above the Feature line. A
    # reader opening a test case does not need "7 event(s) flagged
    # network_incomplete" before the first step.
    warnings = [
        Warning(
            id=f"warn_{i + 1:03d}",
            source="fidelity",
            severity="warn",
            message=f"{count} event(s) flagged {flag}",
            code=flag,
        )
        for i, (flag, count) in enumerate(
            sorted((recording.metadata.fidelitySummary or {}).items())
        )
    ]

    # SS9.3 -- one recording can hold several test cases. Split here, after
    # merging and splitting, so every case is built from the same final steps
    # the feature file will show.
    groups = _case_groups(steps, composed)
    cases: list[TestCaseIR] = []
    earlier_setup: list[Step] = []
    for index, (scenario, group_steps) in enumerate(groups, start=1):
        cases.append(
            _build_case(
                recording,
                run_id,
                group_steps,
                composed,
                scenario=scenario,
                warnings=warnings,
                index=index,
                of=len(groups),
                inherited_setup=list(earlier_setup),
                omitted=omitted,
            )
        )
        earlier_setup.extend(s for s in group_steps if s.role == SegmentRole.setup)

    return IRDocument(
        schemaVersion="1.0",
        recordingId=recording.id,
        runId=run_id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        testCases=cases,
    )


PRUNED_ROLES = {SegmentRole.exploratory, SegmentRole.abandoned}


def _prune(steps: list[Step], segment_of: dict[str, str]) -> tuple[list[Step], list[dict]]:
    """Separate the wrong turns from the test case (SS9.3).

    Every pruned step is reported with the id of the last step that survived
    before it, so the marker lands where the detour actually happened rather
    than in a footnote. `event_coverage` accepts an event covered by an
    omission, so nothing goes missing -- and `no_pruned_assertion` then has a
    subject: an assertion grounded in pruned evidence is one the reader cannot
    see the basis for, however true it is.
    """
    kept: list[Step] = []
    omitted: list[dict] = []
    for step in steps:
        if step.role not in PRUNED_ROLES:
            kept.append(step)
            continue
        # The SEGMENT id, not the step id: `event_coverage` and
        # `no_pruned_assertion` both resolve an omission back to the segment to
        # find out which events it covered, and a step id resolves to nothing --
        # which would report every pruned event as unaccounted for.
        omitted.append(
            {
                "segmentId": segment_of.get(step.id, step.id),
                "reason": step.role.value,
                "eventCount": len(step.eventIds),
                "summary": step.text,
                "afterStepId": kept[-1].id if kept else "",
            }
        )
    return kept, omitted


def _scenario_from(steps: list[Step], composed: ComposeResult, index: int, of: int) -> str:
    """A name for a case the deterministic split created.

    Composition names the cases it proposes. When the tester's own scenario
    break overrode it, nobody named these -- and reusing composition's one name
    for all of them puts two identical `Scenario:` lines in a suite, which is
    the same defect as a Feature that repeats its Scenario, wearing a new hat.

    So it is named after what it VERIFIES -- its last accepted expected result --
    rather than after what it does. A scenario line that repeats the `When`
    under it is the same defect as a Feature that repeats its Scenario, and a
    reader scanning a list of them learns nothing from either. Falls back to the
    last step only when the case checks nothing, which is itself worth seeing.
    """
    if of == 1:
        return composed.scenario_name

    tested = [s for s in steps if s.role != SegmentRole.setup] or steps
    checks = [a.text for s in tested for a in s.assertions if a.accepted]
    text = (checks[-1] if checks else (tested[-1].text if tested else "")).strip()
    return (text[:1].upper() + text[1:]) if text else composed.scenario_name


def _case_groups(steps: list[Step], composed: ComposeResult) -> list[tuple[str, list[Step]]]:
    """Partition the finished steps into test cases.

    Falls back to one case whenever the decomposition does not account for
    exactly the steps that exist -- which it may not, because merges and splits
    ran after composition decided. A partial decomposition is worse than none:
    the steps left out would vanish from every artifact.
    """
    if not composed.cases:
        return [(composed.scenario_name, steps)]

    by_id = {step.id: step for step in steps}
    groups: list[tuple[str, list[Step]]] = []
    claimed: set[str] = set()
    for group in composed.cases:
        members = [by_id[sid] for sid in group.step_ids if sid in by_id]
        if not members:
            continue
        claimed.update(s.id for s in members)
        groups.append((group.scenario, members))

    if len(groups) < 2 or claimed != set(by_id):
        return [(composed.scenario_name, steps)]
    return groups


def _build_case(
    recording: Recording,
    run_id: str,
    steps: list[Step],
    composed: ComposeResult,
    *,
    scenario: str,
    warnings: list[Warning],
    index: int,
    of: int,
    inherited_setup: list[Step] | None = None,
    omitted: list[dict] | None = None,
) -> TestCaseIR:
    case = TestCaseIR(
        id=f"tc_{recording.id}" if of == 1 else f"tc_{recording.id}_{index:02d}",
        recordingId=recording.id,
        runId=run_id,
        kind="test_case",
        title=composed.title,
        description=composed.description or scenario,
        scenarioName=scenario or _scenario_from(steps, composed, index, of),
        # SS9.3 -- the second test case out of a recording cannot start halfway
        # through a session. The setup earlier cases performed becomes this
        # one's preconditions, which the renderer emits as a `Background`, so
        # every case is runnable on its own. Preconditions rather than steps on
        # purpose: they carry no event ids, so `event_coverage` still accounts
        # for each event exactly once.
        preconditions=[
            {
                "id": f"pre_{i + 1:03d}",
                "text": step.text,
                "shared": True,
                # Kept so a reader can trace a precondition back to the events
                # that established it, exactly as they can a step.
                "eventIds": list(step.eventIds),
            }
            for i, step in enumerate(inherited_setup or [])
        ],
        tags=composed.tags,
        steps=steps,
        parameters=[
            {"name": p.name, "placeholder": p.placeholder, "category": p.category.value}
            for p in recording.parameters
        ],
        omitted=[
            o
            for o in (omitted or [])
            # An omission belongs to the case the pruned work happened inside.
            if o["afterStepId"] in {step.id for step in steps} or not o["afterStepId"]
        ],
        metadata=TestCaseMetadata(
            capturedAt=recording.metadata.capturedAt,
            durationMs=recording.metadata.durationMs,
            browser=recording.metadata.browser,
            viewport={"w": recording.metadata.viewport.w, "h": recording.metadata.viewport.h},
            startUrl=recording.metadata.startUrl,
            projectId=recording.projectId,
            ownerId=recording.ownerId,
        ),
        warnings=warnings,
    )
    if recording.objective:
        case.objective = recording.objective
    return case


def _write_output(
    run: RunPaths,
    ir: IRDocument,
    rendered: dict[str, str],
    sidecars: dict[str, str],
    config: ProjectConfig,
) -> None:
    by_id = {case.id: case for case in ir.testCases}
    for case_id, text in rendered.items():
        (run.root / feature_filename(by_id[case_id], config)).write_text(text, encoding="utf-8")
    for case_id, text in sidecars.items():
        (run.root / trace_filename(by_id[case_id], config)).write_text(text, encoding="utf-8")


def _erase_output(run: RunPaths, ir: IRDocument, config: ProjectConfig) -> None:
    for case in ir.testCases:
        (run.root / feature_filename(case, config)).unlink(missing_ok=True)
        (run.root / trace_filename(case, config)).unlink(missing_ok=True)


def _flags(recording: Recording, event_ids: list[str]) -> list[Any]:
    by_id = {e.id: e for e in recording.events}
    out: list[Any] = []
    for event_id in event_ids:
        for flag in by_id[event_id].fidelity if event_id in by_id else []:
            if flag not in out:
                out.append(flag)
    return out


def _trace(
    recording: Recording,
    run_id: str,
    options: PipelineOptions,
    runner: ToolRunner,
    naming: NamingResult,
    composed: ComposeResult,
    proposed: AssertionResult,
) -> AgentTrace:
    config = RunConfig(
        ablation=options.ablation,
        toolsEnabled=options.tools_enabled,
        criticEnabled=options.critic_enabled,
        repairEnabled=options.repair_enabled,
        defaultInvestigationBudget=options.budget,
        fallbackEnabled=options.fallback_enabled,
        cassetteMode=options.cassette_mode,
        models={
            "name": {"provider": "configured", "model": options.model_name},
            "assert": {"provider": "configured", "model": options.model_name},
            "compose": {"provider": "configured", "model": options.model_name},
        },
    )
    if options.ablation == AblationConfig.A0:
        config.a0Truncation = TruncationPolicy(
            strategy="head_tail", tokenBudget=options.a0_token_budget
        )

    investigations = [*naming.investigations, *proposed.investigations]
    if composed.investigation is not None:
        investigations.append(composed.investigation)

    return AgentTrace(
        schemaVersion="1.0",
        runId=run_id,
        recordingId=recording.id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        config=config,
        toolCalls=runner.calls,
        modelCalls=[*naming.model_calls, *proposed.model_calls, *composed.model_calls],
        investigations=investigations,
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=composed.decisions,
    )


#: Calls made because the process requires them on every step, not because this
#: step was hard. Excluded from the effort metrics below.
ROUTINE_TOOLS = {"search_step_library"}


def _merge_assertions(
    original: AssertionResult, redone: AssertionResult, *, replacing: set[str]
) -> AssertionResult:
    """Swap in freshly proposed results for the steps a split created."""
    merged = AssertionResult(model_calls=[*original.model_calls, *redone.model_calls])
    merged.steps = [s for s in original.steps if s.step_id not in replacing]
    merged.steps.extend(redone.steps)
    return merged


def _selector_hints(recording: Recording, event_ids: list[str]) -> list[SelectorHint]:
    """Carry the recorder's selectors onto the step, ranked.

    `SelectorHint` has existed since Phase 1 and nothing in `server/` had ever
    constructed one, so `selector_resolvable` skipped on every run this project
    has made. The data was always there -- every event's target carries a
    `SelectorSet` -- it just never reached the IR.

    Ranked most-stable first, which is the order a replay should try them in:
    a `data-testid` is put there on purpose and survives a redesign; role and
    accessible name survive a class rename and are the normal case for an
    application that was not built for testing; text is brittle to copy edits;
    a CSS path is the last resort and is why it is last.

    Recording which rank actually resolved is what makes "how robust are these
    selectors" a measurement rather than an opinion.
    """
    by_id = {e.id: e for e in recording.events}
    seen: set[tuple[str, str]] = set()
    hints: list[SelectorHint] = []
    for event_id in event_ids:
        event = by_id.get(event_id)
        if event is None:
            continue
        selectors = event.target.selectors
        for strategy, value, stability in (
            ("testId", selectors.testId, Confidence.high),
            ("role", selectors.role, Confidence.high),
            ("text", selectors.text, Confidence.medium),
            ("css", selectors.css, Confidence.low),
        ):
            if not value or (strategy, value) in seen:
                continue
            seen.add((strategy, value))
            hints.append(SelectorHint(strategy=strategy, value=value, stability=stability))
    return hints


def _calls_per_step(
    naming: NamingResult, proposed: AssertionResult, trace_calls: list | None = None
) -> dict[str, int]:
    """The x-axis of the effort/difficulty correlation (SS3.4).

    Summed across every stage that investigated the step. Effort is what the
    agent spent on a decision about that step, not what one stage spent.

    Search-before-invent (SS12.2) is deliberately NOT counted. The metric it
    feeds is SS3.3's claim that effort varies with difficulty -- "a step with an
    obvious outcome costs zero calls; an ambiguous one costs several" -- and a
    call the process mandates on every step regardless of difficulty is a
    constant added to every reading. Measured: introducing the library lifted
    calls-per-step from 1.56 to 2.17 and collapsed the spread from 1.08 to 0.16,
    which reads as an agent that stopped adapting when nothing of the sort
    happened. `toolCallsTotal` still counts them -- they are real calls that
    cost real quota -- but they are not evidence of investigation.
    """
    routine = {c.id for c in (trace_calls or []) if getattr(c, "tool", None) in ROUTINE_TOOLS}

    def effort(ids: list[str]) -> int:
        return sum(1 for i in ids if i not in routine)

    per_step = {s.step_id: effort(s.investigation.toolCallIds) for s in naming.steps}
    for step in proposed.steps:
        if step.investigation is not None:
            per_step[step.step_id] = per_step.get(step.step_id, 0) + effort(
                step.investigation.toolCallIds
            )
    return per_step


def _metrics(
    ir: IRDocument,
    naming: NamingResult,
    composed: ComposeResult,
    proposed: AssertionResult,
    report: ValidationReport,
    rate: float,
    elapsed: float,
    trace_calls: list | None = None,
) -> RunMetrics:
    total = sum(len(s.assertions) for c in ir.testCases for s in c.steps)
    ungrounded = round(total * (1 - rate))
    checks = [r for r in report.results if r.status != ValidatorStatus.skip]
    first_pass = (
        len([r for r in checks if r.status == ValidatorStatus.pass_]) / len(checks)
        if checks
        else 1.0
    )
    model_calls = [*naming.model_calls, *proposed.model_calls, *composed.model_calls]

    return RunMetrics(
        assertionsTotal=total,
        assertionsGrounded=total - ungrounded,
        groundingRate=rate,
        assertionsUngrounded=ungrounded,
        validatorFirstPassRate=first_pass,
        toolCallsTotal=sum(
            len(i.toolCallIds) for i in [*naming.investigations, *proposed.investigations]
        ),
        toolCallsPerStep=_calls_per_step(naming, proposed, trace_calls),
        promptTokensTotal=sum(m.promptTokens or 0 for m in model_calls),
        completionTokensTotal=sum(m.completionTokens or 0 for m in model_calls),
        uncachedModelCalls=len([m for m in model_calls if not m.cached]),
        durationMs=elapsed * 1000,
    )
