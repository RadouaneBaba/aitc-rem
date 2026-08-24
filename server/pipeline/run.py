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
import json
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
    ValidatorName,
    ValidatorStatus,
    Warning,
)
from server.pipeline.assertions import ASSERT_BUDGET, AssertionResult, propose_assertions
from server.pipeline.bugmode import (
    BUG_BUDGET,
    BugSignals,
    bug_case,
    describe,
    detect,
    repro_steps,
)
from server.pipeline.compose import (
    COMPOSE_BUDGET,
    ComposeResult,
    compose_test_case,
    fallback_composition,
)
from server.pipeline.coverage import COVERAGE_BUDGET, CoverageResult, attach, suggest_coverage
from server.pipeline.critic import CRITIC_BUDGET, CriticResult, critique
from server.pipeline.investigate import DEFAULT_BUDGET
from server.pipeline.name import NamingResult, name_segments, rename_steps, split_named
from server.pipeline.narrative import (
    apply_merges,
    apply_splits,
    keyword_for_role,
    merge_repeats,
    sync_keywords,
)
from server.pipeline.repair import (
    MAX_REPAIR_ATTEMPTS,
    RepairOutcome,
    protected_steps,
    record,
    still_failing,
    still_flagged,
    targets,
)
from server.pipeline.segment import segment_recording
from server.pipeline.validators import (
    ValidationContext,
    ValidationReport,
    claim_total,
    grounding_rate,
    validate,
)
from server.pipeline.validators.output import suggestions_quarantined
from server.renderers import bug_md, trace_md
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
    #: SS9.8. Gated separately from the critic on purpose: SS3.5 defines A1 vs
    #: A2 as differing by "critic, repair loop" and nothing else, so attaching
    #: coverage to the A2 flag would make that comparison measure two changes at
    #: once. Requires tools -- reasoning about the unobserved still has to rest
    #: on something observed.
    suggestions_enabled: bool = True
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
    critic: CriticResult | None = None
    repair: RepairOutcome = field(default_factory=RepairOutcome)
    #: The gate's verdict on attempt 1, kept whole. `report` above is the FINAL
    #: verdict, and once a repair loop exists those are different documents --
    #: SS3.5 asks for the first, the reviewer needs the last.
    first_report: ValidationReport | None = None
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

    stages.append(
        StageRecord(
            stage=PipelineStage.decompose,
            attempt=1,
            inputPath=run.relative(run.artifact("assertions")),
            outputPath=run.relative(run.artifact("ir")),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.degraded if composed.degraded else StageStatus.ok,
        )
    )

    # -- 5-8. draft, validate, critique, repair ---------------------------
    #
    # SS9.9's cycle: generate -> validate (code) -> critique (model) -> repair
    # -> validate -> ... Bounded at three attempts, after which the finding is
    # stated to the human rather than silently accepted.
    #
    # `composed` and `runner` are built once and outlive the loop; everything
    # downstream of them is rebuilt per attempt. That rebuild is what keeps the
    # trace's retrieval log current -- an assertion re-proposed on attempt 2
    # cites a `tc_` id minted during the repair, and `evidence_retrieved` can
    # only resolve it if the trace has been re-synced since. See `_sync_calls`,
    # which exists because assuming otherwise cost a real run.
    attempt = 1
    draft = _draft(
        recording,
        run_id,
        options,
        runner=runner,
        storage=storage,
        run=run,
        segments=segments,
        naming=naming,
        composed=composed,
        proposed=proposed,
        critic=None,
        stages=stages,
        announce=announce,
        attempt=attempt,
    )

    # SS3.5's row is "validator pass rate (FIRST attempt)". Frozen here and
    # never recomputed: a repair loop that lifted this number would be
    # reporting itself working by hiding that it had to.
    #
    # A COPY, not the object. When nothing repairs, `draft.report` is still the
    # live report, and the coverage stage below edits `report.results` in
    # place -- which silently backdated a later validator result into the
    # first-attempt number. It showed up as A1 scoring HIGHER on first-attempt
    # than A2 on identical attempt-1 output, which is impossible and was the
    # only reason anyone looked.
    first_report = ValidationReport(results=list(draft.report.results))
    outcome = RepairOutcome()
    protected = protected_steps(store, naming)
    critic: CriticResult | None = None

    if options.critic_enabled:
        critic = _critique(runner, model, draft, options, protected, storage, run, stages, announce)

    while options.repair_enabled and attempt < MAX_REPAIR_ATTEMPTS:
        pending = targets(
            draft.report,
            critic.findings if critic else [],
            protected=protected,
            known_steps={s.step_id for s in naming.steps},
        )
        if not pending:
            break
        attempt += 1
        naming, proposed, repaired = _repair_round(
            store, runner, model, naming, proposed, pending, options, attempt
        )
        draft = _draft(
            recording,
            run_id,
            options,
            runner=runner,
            storage=storage,
            run=run,
            segments=segments,
            naming=naming,
            composed=composed,
            proposed=proposed,
            critic=critic,
            stages=stages,
            announce=announce,
            attempt=attempt,
        )
        if options.critic_enabled and repaired:
            critic = _critique(
                runner,
                model,
                draft,
                options,
                protected,
                storage,
                run,
                stages,
                announce,
                only=repaired,
                attempt=attempt,
            )
        for target in pending:
            resolved = not still_failing(draft.report, target) and not still_flagged(critic, target)
            record(
                outcome,
                target,
                attempt=attempt,
                resolved=resolved,
                exhausted=not resolved and attempt >= MAX_REPAIR_ATTEMPTS,
            )

    ir, rendered, sidecars, trace, ctx, report = draft.unpack()

    # -- 9. bug mode (SS14) ------------------------------------------------
    #
    # Offered ALONGSIDE the test case, never instead of it: the steps that
    # reached the failure are a test case whether or not the failure is a bug,
    # and SS14.1 leaves the choice to the tester at review time.
    signals = detect(recording)
    storage.save_artifact(run, "bug", signals.to_artifact())
    bugged = False
    if signals.detected and options.tools_enabled:
        announce(PipelineStage.assert_)
        t0 = time.time()
        added = bugged = _bug_report(store, runner, model, recording, ir, signals, options, trace)
        stages.append(
            StageRecord(
                stage=PipelineStage.assert_,
                attempt=attempt,
                outputPath=run.relative(run.artifact("bug")),
                startedAt=t0,
                endedAt=time.time(),
                status=StageStatus.ok if added else StageStatus.degraded,
            )
        )
        if added:
            # A bug report adds steps and a claim, so unlike a coverage
            # suggestion it has to go through the whole gate rather than one
            # validator. Its `actual` is bound exactly as tightly as any
            # expected result (SS14.2), and this is where that is enforced.
            storage.save_artifact(run, "ir", ir)
            rendered = render_document(ir, config=options.project)
            # The describer retrieved, and the gate is about to resolve what it
            # cited. See `_sync_calls`.
            _sync_calls(trace, runner)
            ctx = ValidationContext(
                recording=recording,
                ir=ir,
                trace=trace,
                storage=storage,
                run=run,
                segments=segments,
                rendered=rendered,
                attempt=attempt,
                library=options.library,
                narration_min_confidence=options.project.narration_min_confidence,
            )
            report = validate(ctx)

    # -- 10. coverage suggestions (SS9.8) ---------------------------------
    #
    # After the gate has settled, which SS9.8 requires in as many words. A
    # suggestion derived from a draft the validators went on to reject would be
    # advice about a test case that no longer exists.
    suggestions: CoverageResult | None = None
    if options.suggestions_enabled and options.tools_enabled:
        announce(PipelineStage.coverage)
        t0 = time.time()
        try:
            suggestions = suggest_coverage(
                runner,
                model,
                ir,
                model_name=options.model_name,
                budget=min(COVERAGE_BUDGET, options.budget),
                tools_enabled=options.tools_enabled,
                temperature=options.temperature,
                config=options.project,
                rendered=rendered,
            )
        except Exception as exc:  # noqa: BLE001 - degraded, never fatal
            # Suggestions are the one output nobody runs. Losing them costs a
            # prompt for the tester; losing the test case costs the session.
            suggestions = CoverageResult(failed=f"{type(exc).__name__}: {exc}")
        attach(ir, suggestions)
        # The trace is the one list the metrics read, so a stage that does not
        # add itself here is a stage that costs quota invisibly.
        trace.investigations.extend(suggestions.investigations)
        trace.modelCalls.extend(suggestions.model_calls)
        _sync_calls(trace, runner)
        path = storage.save_artifact(run, "coverage", suggestions.to_artifact())
        stages.append(
            StageRecord(
                stage=PipelineStage.coverage,
                attempt=1,
                inputPath=run.relative(run.artifact("ir")),
                outputPath=run.relative(path),
                startedAt=t0,
                endedAt=time.time(),
                status=StageStatus.degraded if suggestions.failed else StageStatus.ok,
                **({"error": suggestions.failed} if suggestions.failed else {}),
            )
        )
        # The quarantine is a gate, not a convention. Run just that validator
        # rather than the whole pass: nothing else in the report can have
        # changed, because attaching suggestions touches no step, no assertion
        # and no rendered feature.
        report.results = [
            r for r in report.results if r.validator != ValidatorName.suggestions_quarantined
        ]
        report.results.extend(suggestions_quarantined(ctx))

    # The critic's verdict reaches the human here, and only here. SS9.9: an
    # unresolved finding is "surfaced with the finding stated plainly, never
    # silently accepted" -- so it lands on the step and on the case rather than
    # in a log. The `.feature` body is untouched by design (SS11.1: it is prose
    # and nothing else), which is why this needs no re-validation.
    annotated = _annotate(ir, critic, outcome)
    if annotated or suggestions is not None or bugged:
        storage.save_artifact(run, "ir", ir)
        if options.project.trace == "sidecar":
            sidecars = trace_md.render_document(ir, trace=trace, config=options.project)
        _write_output(run, ir, rendered, sidecars, options.project)

    rate = grounding_rate(ctx, report)
    _sync_calls(trace, runner)
    trace.validatorResults = report.results
    trace.repairAttempts = outcome.attempts
    trace.metrics = _metrics(
        ir, trace, report, first_report, outcome, rate, time.perf_counter() - started
    )

    trace.stages = stages
    trace_path = storage.save_artifact(run, "trace", trace)

    # The output is emitted even when the gate rejects it. The repair loop is
    # bounded, so a run can end still rejected -- and hiding the draft would
    # leave nothing to inspect, while the report says plainly what is wrong with
    # it. The one exception is a leaked secret, which must not be written at all
    # (SS9.7) and which no repair is allowed to paper over.
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
        critic=critic,
        repair=outcome,
        first_report=first_report,
        grounding_rate=rate,
        duration_ms=(time.perf_counter() - started) * 1000,
        artifacts={
            "segments": run.artifact("segments"),
            "naming": run.artifact("naming"),
            "assertions": run.artifact("assertions"),
            "ir": run.artifact("ir"),
            "trace": trace_path,
            "coverage": run.artifact("coverage"),
            "critic": run.artifact("critic"),
        },
    )


# --------------------------------------------------------------------------
# one attempt: assemble, render, validate
# --------------------------------------------------------------------------


@dataclass
class _Draft:
    """Everything one attempt produced. Rebuilt from scratch each time."""

    ir: IRDocument
    rendered: dict[str, str]
    sidecars: dict[str, str]
    trace: AgentTrace
    ctx: ValidationContext
    report: ValidationReport

    def unpack(self):
        return self.ir, self.rendered, self.sidecars, self.trace, self.ctx, self.report


def _draft(
    recording: Recording,
    run_id: str,
    options: PipelineOptions,
    *,
    runner: ToolRunner,
    storage: Storage,
    run: RunPaths,
    segments: Any,
    naming: NamingResult,
    composed: ComposeResult,
    proposed: AssertionResult,
    critic: CriticResult | None,
    stages: list[StageRecord],
    announce: Callable[[PipelineStage], None],
    attempt: int,
) -> _Draft:
    """Assemble the IR, render it, and put it through the gate. Once.

    Safe to replay because `_assemble` is a pure function of its inputs and
    never mutates `naming`: `apply_merges` always sees the unmerged list, and
    `apply_splits` no-ops on already-split steps thanks to its
    `0 < cut < len(eventIds)` guard -- which the pipeline already relied on,
    since `split_named` cuts `naming` before `_assemble` cuts it again.

    The trace is rebuilt rather than reused. `_trace` reads
    `naming.investigations` and `proposed.investigations`, and a repair REBINDS
    both objects, so a trace built once would hold stale lists.

    Rebuilding is also the only thing that keeps `toolCalls` current, which is
    load-bearing and was got wrong once: `AgentTrace(toolCalls=runner.calls)`
    looks like it aliases the runner's live list and does not -- Pydantic
    validates the field and COPIES it. A retrieval made after the trace was
    built is therefore invisible to `evidence_retrieved`, which then rejects the
    perfectly good assertion citing it. Any stage that runs after the last
    `_draft` has to call `_sync_calls` before it is validated.
    """
    # Never overwrite a superseded draft. SS9.1's whole claim is that you can
    # open the intermediate artifact and see which stage lied; a repair that
    # silently replaced the draft it was repairing would take that away exactly
    # when it is most wanted.
    if attempt > 1:
        _archive(storage, run, attempt - 1, ("naming", "assertions", "ir"))
        storage.save_artifact(run, "naming", naming.to_artifact())
        storage.save_artifact(run, "assertions", proposed.to_artifact())

    announce(PipelineStage.render)
    t0 = time.time()
    ir = _assemble(recording, run_id, naming, composed, proposed)
    storage.save_artifact(run, "ir", ir)
    trace = _trace(recording, run_id, options, runner, naming, composed, proposed, critic)
    rendered = render_document(ir, config=options.project)
    sidecars: dict[str, str] = {}
    if options.project.trace == "sidecar":
        sidecars = trace_md.render_document(ir, trace=trace, config=options.project)
    _write_output(run, ir, rendered, sidecars, options.project)
    stages.append(
        StageRecord(
            stage=PipelineStage.render,
            attempt=attempt,
            outputPath=run.relative(run.root / "features"),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

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
        attempt=attempt,
        library=options.library,
        narration_min_confidence=options.project.narration_min_confidence,
    )
    report = validate(ctx)
    stages.append(
        StageRecord(
            stage=PipelineStage.validate,
            attempt=attempt,
            outputPath=run.relative(run.artifact("trace")),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok if report.ok else StageStatus.failed,
        )
    )
    return _Draft(ir=ir, rendered=rendered, sidecars=sidecars, trace=trace, ctx=ctx, report=report)


def _sync_calls(trace: AgentTrace, runner: ToolRunner) -> None:
    """Copy the runner's retrievals into the trace, again.

    `AgentTrace(toolCalls=runner.calls)` does not alias the runner's list --
    Pydantic validates the field and copies it -- so every stage that retrieves
    after the trace was built must do this before the gate reads it. Skipping it
    produces the most confusing possible failure: `evidence_retrieved` rejects a
    citation that is true, resolvable and correct, because the call it names is
    in the runner and not in the trace. Found exactly that way, on a real run.
    """
    trace.toolCalls = list(runner.calls)


def _archive(storage: Storage, run: RunPaths, attempt: int, names: tuple[str, ...]) -> None:
    """Keep the superseded draft under `<stage>.attempt<N>.json`."""
    for name in names:
        source = run.artifact(name)
        if source.exists():
            storage.save_artifact(
                run, f"{name}.attempt{attempt}", json.loads(source.read_text(encoding="utf-8"))
            )


def _critique(
    runner: ToolRunner,
    model: ModelClient,
    draft: _Draft,
    options: PipelineOptions,
    protected: set[str],
    storage: Storage,
    run: RunPaths,
    stages: list[StageRecord],
    announce: Callable[[PipelineStage], None],
    *,
    only: set[str] | None = None,
    attempt: int = 1,
) -> CriticResult:
    announce(PipelineStage.critic)
    t0 = time.time()
    try:
        result = critique(
            runner,
            model,
            draft.ir,
            model_name=options.model_name,
            protected=protected,
            budget=min(CRITIC_BUDGET, options.budget),
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            rendered=draft.rendered,
            only=only,
            attempt=attempt,
        )
    except Exception as exc:  # noqa: BLE001 - any provider failure, surfaced as degraded
        # A critic failure must not cost the run: naming and the assert stage
        # have already produced the expensive, evidence-bound part. But it must
        # not read as approval either -- an empty findings list from a critic
        # that crashed and one from a critic that read the output and liked it
        # are the same value and opposite facts.
        result = CriticResult(failed=f"{type(exc).__name__}: {exc}")
    name = "critic" if attempt == 1 else f"critic.attempt{attempt}"
    path = storage.save_artifact(run, name, result.to_artifact())
    stages.append(
        StageRecord(
            stage=PipelineStage.critic,
            attempt=attempt,
            inputPath=run.relative(run.artifact("ir")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.degraded if result.failed else StageStatus.ok,
            **({"error": result.failed} if result.failed else {}),
        )
    )
    return result


def _repair_round(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    naming: NamingResult,
    proposed: AssertionResult,
    pending: list,
    options: PipelineOptions,
    attempt: int,
) -> tuple[NamingResult, AssertionResult, set[str]]:
    """Re-run the offending stages for the flagged steps only (SS9.9).

    Returns the ids that actually changed, which is not the same as the ids
    asked about: `rename_steps` refuses a rewrite that would collide with a
    neighbour, and the assert stage can legitimately come back with nothing. A
    finding whose repair produced no change stays unresolved rather than being
    marked fixed because a stage ran.
    """
    renames = {t.step_id: t.finding for t in pending if t.stage == PipelineStage.name}
    reasserts = {t.step_id: t.finding for t in pending if t.stage == PipelineStage.assert_}
    touched: set[str] = set()

    if renames:
        naming, changed = rename_steps(
            store,
            runner,
            model,
            naming,
            findings=renames,
            model_name=options.model_name,
            budget=options.budget if options.tools_enabled else 0,
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            attempt=attempt,
        )
        touched |= changed

    if reasserts:
        redone = propose_assertions(
            store,
            runner,
            model,
            naming,
            model_name=options.model_name,
            budget=min(ASSERT_BUDGET, options.budget) if options.tools_enabled else 0,
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            only=set(reasserts),
            findings=reasserts,
            previous=proposed.by_step(),
            attempt=attempt,
        )
        proposed = _merge_assertions(proposed, redone, replacing=set(reasserts))
        touched |= set(reasserts)

    return naming, proposed, touched


def _bug_report(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    recording: Recording,
    ir: IRDocument,
    signals: BugSignals,
    options: PipelineOptions,
    trace: AgentTrace,
) -> bool:
    """Attach a bug report to the case that contains the failure (SS14).

    Returns False when the model could not cite what it claimed, and that is a
    correct outcome rather than a degradation: a bug report whose `actual` is
    unsupported sends a developer to reproduce something that never happened,
    which costs more than writing nothing at all.
    """
    for case in list(ir.testCases):
        if case.kind == "bug_report":
            continue
        steps, failure_step_id = repro_steps(case, signals.failure_event_id)
        if failure_step_id is None:
            continue
        if signals.failure_event_id and not any(
            signals.failure_event_id in s.eventIds for s in case.steps
        ):
            # The failure happened in a different test case of this recording.
            continue

        try:
            detail, investigation, model_calls = describe(
                store,
                runner,
                model,
                recording,
                case,
                signals,
                model_name=options.model_name,
                failure_step_id=failure_step_id,
                budget=min(BUG_BUDGET, options.budget),
                tools_enabled=options.tools_enabled,
                temperature=options.temperature,
                config=options.project,
            )
        except Exception:  # noqa: BLE001 - a provider failure must not lose the test case
            return False

        if investigation is not None:
            trace.investigations.append(investigation)
        trace.modelCalls.extend(model_calls)
        if detail is None:
            return False

        ir.testCases.append(bug_case(ir, case, steps, detail))
        return True
    return False


def _annotate(ir: IRDocument, critic: CriticResult | None, outcome: RepairOutcome) -> bool:
    """Put every unresolved finding where a human will see it (SS9.9).

    Three sources, all of them things the loop could not fix:

      * a finding whose kind no stage can act on -- `coherence` and
        `state_jump` need composition, and re-running composition can change
        the step count (SS3.6)
      * a finding whose repair ran out of budget
      * a rewrite the naming stage refused because it would have collapsed two
        steps into one

    None of them are dropped. "The critic found nothing" and "the critic found
    something nobody acted on" are different facts about a run, and only one of
    them is good news.
    """
    unresolved = {(t.step_id, t.finding) for t in outcome.unresolved}
    acted_on = {a.targetStepId for a in outcome.attempts if a.resolved}
    notes: list[tuple[str | None, str, str]] = []

    if critic is not None and critic.failed:
        # Louder than a log line, because the alternative reading of "no
        # findings" is "a second pair of eyes looked and approved this".
        notes.append(
            (
                None,
                "critic_unavailable",
                f"the critic did not run ({critic.failed}), so nothing has reviewed this "
                f"test case for meaning -- only the deterministic gate has checked it",
            )
        )

    for finding in critic.findings if critic else []:
        if finding.step_id in acted_on and (finding.step_id, finding.message) not in unresolved:
            continue
        notes.append((finding.step_id, finding.kind, finding.message))
    for step_id, message in sorted(unresolved):
        if not any(n[0] == step_id and message.endswith(n[2]) for n in notes):
            notes.append((step_id, "unrepaired", message))

    if not notes:
        return False

    for case in ir.testCases:
        steps = {s.id: s for s in case.steps}
        for step_id, kind, message in notes:
            step = steps.get(step_id or "")
            if step is not None:
                step.criticNotes = [*(step.criticNotes or []), f"{kind}: {message}"]
            elif step_id is not None:
                continue
            case.warnings.append(
                Warning(
                    id=f"warn_critic_{len(case.warnings) + 1:03d}",
                    source="critic",
                    severity="warn",
                    message=message,
                    code=kind,
                    **({"stepId": step_id} if step_id else {}),
                )
            )
    return True


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
    # A bug report is never in `rendered` -- Gherkin refuses it (SS14) -- so it
    # would have no artifact at all without this. Always written, like the
    # feature file and for the same reason: the validation gate has already read
    # it, so it is not optional output.
    for case_id, text in bug_md.render_document(ir, config=config).items():
        (run.root / bug_md.bug_filename(by_id[case_id], config)).write_text(
            text, encoding="utf-8"
        )


def _erase_output(run: RunPaths, ir: IRDocument, config: ProjectConfig) -> None:
    for case in ir.testCases:
        (run.root / feature_filename(case, config)).unlink(missing_ok=True)
        (run.root / trace_filename(case, config)).unlink(missing_ok=True)
        # A leaked secret is a leaked secret in whichever artifact it reached,
        # and a bug report quotes what the application said back (SS14.2) --
        # which is exactly where an unredacted value would surface.
        (run.root / bug_md.bug_filename(case, config)).unlink(missing_ok=True)


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
    critic: CriticResult | None = None,
) -> AgentTrace:
    models = {
        "name": {"provider": "configured", "model": options.model_name},
        "assert": {"provider": "configured", "model": options.model_name},
        "compose": {"provider": "configured", "model": options.model_name},
    }
    if options.critic_enabled:
        models["critic"] = {"provider": "configured", "model": options.model_name}
    config = RunConfig(
        ablation=options.ablation,
        toolsEnabled=options.tools_enabled,
        criticEnabled=options.critic_enabled,
        repairEnabled=options.repair_enabled,
        maxRepairAttempts=MAX_REPAIR_ATTEMPTS,
        defaultInvestigationBudget=options.budget,
        fallbackEnabled=options.fallback_enabled,
        cassetteMode=options.cassette_mode,
        models=models,
    )
    if options.ablation == AblationConfig.A0:
        config.a0Truncation = TruncationPolicy(
            strategy="head_tail", tokenBudget=options.a0_token_budget
        )

    investigations = [*naming.investigations, *proposed.investigations]
    if composed.investigation is not None:
        investigations.append(composed.investigation)
    if critic is not None:
        investigations.extend(critic.investigations)

    return AgentTrace(
        schemaVersion="1.0",
        runId=run_id,
        recordingId=recording.id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        config=config,
        toolCalls=runner.calls,
        modelCalls=[
            *naming.model_calls,
            *proposed.model_calls,
            *composed.model_calls,
            *(critic.model_calls if critic else []),
        ],
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
    """Swap in freshly proposed results for the steps a split created.

    The replaced investigations are kept in `superseded` rather than dropped:
    the run really did spend those retrievals on those steps, and both SS9.10's
    trace and SS3.4's effort column would otherwise under-report a step that
    took two passes -- which is exactly the step the effort metric exists to
    find.
    """
    merged = AssertionResult(model_calls=[*original.model_calls, *redone.model_calls])
    merged.steps = [s for s in original.steps if s.step_id not in replacing]
    merged.steps.extend(redone.steps)
    merged.superseded = [
        *original.superseded,
        *redone.superseded,
        *(
            s.investigation
            for s in original.steps
            if s.step_id in replacing and s.investigation is not None
        ),
    ]
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


def _calls_per_step(investigations: list, trace_calls: list | None = None) -> dict[str, int]:
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
    per_step: dict[str, int] = {}

    # Summed over every investigation carrying a step id, INCLUDING the ones a
    # repair superseded. A step that took two passes really did cost the run two
    # passes, and under-reporting that would hide exactly the step SS3.4's
    # correlation exists to find -- the hard one. The critic's own investigation
    # carries no step id (it judges a whole scenario), so it stays out of the
    # per-step column and is counted only in the total.
    for investigation in investigations:
        step_id = getattr(investigation, "stepId", None)
        if not step_id:
            continue
        per_step[step_id] = per_step.get(step_id, 0) + sum(
            1 for i in investigation.toolCallIds if i not in routine
        )
    return per_step


def _pass_rate(report: ValidationReport, restrict_to: set | None = None) -> float:
    """Share of validators that passed, over the ones that had a subject.

    `restrict_to` makes the first and final rates comparable, which they are not
    by default. `suggestions_quarantined` skips on attempt 1 -- coverage has not
    run yet, so it genuinely has nothing to check -- and passes at the end. That
    shifts the denominator between the two measurements, and the resulting
    +0.9 points reads as the repair loop working when the repair loop did
    nothing. Measuring the final rate over the validators that judged the FIRST
    draft means only a repair can move it, which is the whole question the pair
    is there to answer.
    """
    checks = [r for r in report.results if r.status != ValidatorStatus.skip]
    if restrict_to is not None:
        checks = [r for r in checks if r.validator in restrict_to]
    if not checks:
        return 1.0
    return len([r for r in checks if r.status == ValidatorStatus.pass_]) / len(checks)


def _metrics(
    ir: IRDocument,
    trace: AgentTrace,
    report: ValidationReport,
    first_report: ValidationReport,
    outcome: RepairOutcome,
    rate: float,
    elapsed: float,
) -> RunMetrics:
    """Read from the finished trace rather than from each stage.

    The stage-by-stage version had to be edited every time a stage was added,
    and a stage nobody remembered to add was simply invisible in the numbers --
    which is how `toolCallsTotal` came to exclude composition without anyone
    noticing. The trace already has to hold every model call and every
    investigation (SS9.10), so there is exactly one list to be wrong about.
    """
    total = claim_total(ir)
    ungrounded = round(total * (1 - rate))
    model_calls = trace.modelCalls
    investigations = trace.investigations

    return RunMetrics(
        assertionsTotal=total,
        assertionsGrounded=total - ungrounded,
        groundingRate=rate,
        assertionsUngrounded=ungrounded,
        # SS3.5 asks for the FIRST attempt, and only the first. Reading `report`
        # here instead -- which is the final verdict once a repair loop exists --
        # would let the loop report itself working by hiding that it had to.
        validatorFirstPassRate=_pass_rate(first_report),
        validatorFinalPassRate=_pass_rate(
            report,
            restrict_to={
                r.validator
                for r in first_report.results
                if r.status != ValidatorStatus.skip
            },
        ),
        # Never one without the other. A convergence rate over zero findings is
        # vacuously 1.0, exactly the way `groundingRate` is vacuously 1.0 for a
        # configuration that abstains -- the trap this project has now hit in
        # four separate columns.
        criticFindingsRaised=outcome.findings_raised,
        repairConvergenceRate=outcome.convergence_rate,
        toolCallsTotal=sum(len(i.toolCallIds) for i in investigations),
        toolCallsPerStep=_calls_per_step(investigations, trace.toolCalls),
        promptTokensTotal=sum(m.promptTokens or 0 for m in model_calls),
        completionTokensTotal=sum(m.completionTokens or 0 for m in model_calls),
        uncachedModelCalls=len([m for m in model_calls if not m.cached]),
        durationMs=elapsed * 1000,
    )
