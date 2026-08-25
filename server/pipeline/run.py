"""The pipeline skeleton (SS9.1).

    "A fixed deterministic skeleton with agentic stages. Each stage reads a
     file and writes a file, so when output is wrong you open the intermediate
     artifact and see exactly which stage lied."

    segment (code) -> digest (code) -> draft (agentic) -> bind (agentic)
    -> validate (code) -> render

The shape is the same as it always was. What changed is who writes the test
case. There used to be three agentic stages between segmentation and rendering
-- naming, asserting, composing -- and none of them ever saw the test case:
naming was shown one segment, asserting was shown one step, and composing saw
the flow but was forbidden from touching assertions. The output read like a
document written by three people who never met, because it was.

Now one stage writes the document with the whole session in view, and a second
stage proves every claim it made or deletes the claim. Retrieval effort lands
where a claim is contested instead of being spent evenly on every step, which
is what SS3.3 always said an investigating agent should look like.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    ValidatorAction,
    ValidatorName,
    ValidatorStatus,
    Warning,
)
from server.pipeline.bind import BIND_BUDGET, BindResult, bind_claims
from server.pipeline.bugmode import (
    BUG_BUDGET,
    BugSignals,
    bug_case,
    describe,
    detect,
    repro_steps,
)
from server.pipeline.coverage import COVERAGE_BUDGET, CoverageResult, attach, suggest_coverage
from server.pipeline.critic import CRITIC_BUDGET, CriticResult, critique
from server.pipeline.digest import typed_parameters
from server.pipeline.draft import (
    DRAFT_BUDGET,
    DraftResult,
    apply_intent_notes,
    draft_document,
    repropose_expectations,
    rewrite_steps,
)
from server.pipeline.narrative import merge_repeats, sync_keywords
from server.pipeline.repair import (
    MAX_REPAIR_ATTEMPTS,
    RepairOutcome,
    record,
    still_failing,
    still_flagged,
    targets,
)
from server.pipeline.segment import break_openers, segment_recording
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
    budget: int = DRAFT_BUDGET
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.0
    fallback_enabled: bool = True
    cassette_mode: str = "read_write"
    #: House style for the rendered artifacts. Named `project` rather than
    #: `config` because `for_config` already means the ablation configuration,
    #: and two things called config in one signature is how a caller silently
    #: sets the wrong one. Never affects what is true, only how it reads.
    project: ProjectConfig = field(default_factory=ProjectConfig)
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
    #: SS14. Off by default: on a commercial site the uncaught-exception signal
    #: fires on third-party advertising and consent scripts, and one bug report
    #: that sends a developer to reproduce somebody else's JavaScript costs more
    #: trust than fifty good test cases earn. `bugmode` now checks the script is
    #: first-party, and this stays off until a real recording says it works.
    bug_mode_enabled: bool = False
    #: SS12's approved phrasing, shared by the drafting stage and the validator.
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
    draft: DraftResult
    grounding_rate: float
    duration_ms: float
    bound: BindResult | None = None
    critic: CriticResult | None = None
    repair: RepairOutcome = field(default_factory=RepairOutcome)
    #: The gate's verdict on attempt 1, kept whole. `report` above is the FINAL
    #: verdict, and once a repair loop exists those are different documents --
    #: SS3.5 asks for the first, the reviewer needs the last.
    first_report: ValidationReport | None = None
    sidecars: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_calls_per_step(self) -> dict[str, int]:
        """Retrievals per step, summed across every stage that investigated it.

        The x-axis of SS3.4. Read from the trace rather than from any one
        stage: effort is what the run spent on a step, not what one stage did.
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
    #
    # Demoted, deliberately. Its boundaries no longer decide step boundaries --
    # a step is an INTENT and the drafter groups events into one -- but idle
    # gaps, URL changes and the tester's own checkpoints are real signals about
    # where intents end, and they reach the drafter as hints in the index.
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
        store=store,
        storage=storage,
        run=run,
        stage=PipelineStage.decompose,
        library=options.library,
    )

    # -- 2. draft (agentic) ------------------------------------------------
    announce(PipelineStage.decompose)
    t0 = time.time()
    drafted = draft_document(
        store,
        runner,
        model,
        model_name=options.model_name,
        budget=options.budget,
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
        config=options.project,
    )
    # SS6.7 -- where the tester typed the step name themselves, it is theirs.
    # Applied here rather than asked for in the prompt, because the popup makes
    # the tester a promise ("used word for word") and a prompt that asks is not
    # a guarantee.
    dictated = apply_intent_notes(store, drafted)
    _split_on_declared_breaks(store, drafted)
    path = storage.save_artifact(run, "draft", drafted.to_artifact())
    stages.append(
        StageRecord(
            stage=PipelineStage.decompose,
            attempt=1,
            inputPath=run.relative(run.artifact("segments")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.degraded if drafted.degraded else StageStatus.ok,
            **({"error": drafted.degraded} if drafted.degraded else {}),
        )
    )

    # -- 3. bind (agentic, per contested claim) ----------------------------
    announce(PipelineStage.assert_)
    t0 = time.time()
    bound = _bind(store, runner, model, drafted, options)
    bound = _second_chance(store, runner, model, drafted, bound, options)
    path = storage.save_artifact(run, "assertions", bound.to_artifact())
    stages.append(
        StageRecord(
            stage=PipelineStage.assert_,
            attempt=1,
            inputPath=run.relative(run.artifact("draft")),
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    # -- 4-7. assemble, validate, critique, repair -------------------------
    #
    # SS9.9's cycle: generate -> validate (code) -> critique (model) -> repair
    # -> validate -> ... Bounded at three attempts, after which the finding is
    # stated to the human rather than silently accepted.
    #
    # `runner` outlives the loop; everything downstream of it is rebuilt per
    # attempt. That rebuild is what keeps the trace's retrieval log current --
    # a claim re-bound on attempt 2 cites a `tc_` id minted during the repair,
    # and `evidence_retrieved` can only resolve it if the trace has been
    # re-synced since. See `_sync_calls`, which exists because assuming
    # otherwise cost a real run.
    attempt = 1
    draft = _attempt(
        recording,
        run_id,
        options,
        runner=runner,
        storage=storage,
        run=run,
        segments=segments,
        drafted=drafted,
        bound=bound,
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
    # first-attempt number.
    first_report = ValidationReport(results=list(draft.report.results))
    outcome = RepairOutcome()
    critic: CriticResult | None = None

    if options.critic_enabled:
        critic = _critique(runner, model, draft, options, dictated, storage, run, stages, announce)

    while options.repair_enabled and attempt < MAX_REPAIR_ATTEMPTS:
        pending = targets(
            draft.report,
            critic.findings if critic else [],
            protected=dictated,
            known_steps={s.step_id for s in drafted.steps},
        )
        if not pending:
            break
        attempt += 1
        bound, repaired = _repair_round(
            store, runner, model, drafted, bound, pending, options, attempt
        )
        draft = _attempt(
            recording,
            run_id,
            options,
            runner=runner,
            storage=storage,
            run=run,
            segments=segments,
            drafted=drafted,
            bound=bound,
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
                dictated,
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

    # -- 8. bug mode (SS14) ------------------------------------------------
    #
    # Offered ALONGSIDE the test case, never instead of it: the steps that
    # reached the failure are a test case whether or not the failure is a bug,
    # and SS14.1 leaves the choice to the tester at review time.
    signals = detect(recording)
    storage.save_artifact(run, "bug", signals.to_artifact())
    bugged = False
    if signals.detected and options.tools_enabled and options.bug_mode_enabled:
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

    # -- 9. coverage suggestions (SS9.8) ----------------------------------
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

    # A claim the gate rejected and the repair loop could not fix is DELETED,
    # not shipped with a warning beside it. See `_drop_rejected`.
    dropped = _drop_rejected(ir, report)
    if dropped:
        rendered = render_document(ir, config=options.project)
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

    if annotated or dropped or suggestions is not None or bugged:
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
        draft=drafted,
        bound=bound,
        critic=critic,
        repair=outcome,
        first_report=first_report,
        grounding_rate=rate,
        duration_ms=(time.perf_counter() - started) * 1000,
        artifacts={
            "segments": run.artifact("segments"),
            "draft": run.artifact("draft"),
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


def _attempt(
    recording: Recording,
    run_id: str,
    options: PipelineOptions,
    *,
    runner: ToolRunner,
    storage: Storage,
    run: RunPaths,
    segments: Any,
    drafted: DraftResult,
    bound: BindResult,
    critic: CriticResult | None,
    stages: list[StageRecord],
    announce: Callable[[PipelineStage], None],
    attempt: int,
) -> _Draft:
    """Assemble the IR, render it, and put it through the gate. Once.

    Safe to replay because `_assemble` is a pure function of its inputs.

    The trace is rebuilt rather than reused, and rebuilding is the only thing
    that keeps `toolCalls` current -- which is load-bearing and was got wrong
    once: `AgentTrace(toolCalls=runner.calls)` looks like it aliases the
    runner's live list and does not, because Pydantic validates the field and
    COPIES it. A retrieval made after the trace was built is therefore
    invisible to `evidence_retrieved`, which then rejects the perfectly good
    assertion citing it. Any stage that runs after the last `_attempt` has to
    call `_sync_calls` before it is validated.
    """
    # Never overwrite a superseded draft. SS9.1's whole claim is that you can
    # open the intermediate artifact and see which stage lied; a repair that
    # silently replaced the draft it was repairing would take that away exactly
    # when it is most wanted.
    if attempt > 1:
        _archive(storage, run, attempt - 1, ("draft", "assertions", "ir"))
        storage.save_artifact(run, "draft", drafted.to_artifact())
        storage.save_artifact(run, "assertions", bound.to_artifact())

    announce(PipelineStage.render)
    t0 = time.time()
    ir = _assemble(recording, run_id, drafted, bound)
    storage.save_artifact(run, "ir", ir)
    trace = _trace(recording, run_id, options, runner, drafted, bound, critic)
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
    for name in names:
        source = run.artifact(name)
        if source.exists():
            source.replace(run.artifact(f"{name}.attempt{attempt}"))


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def _bind(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    options: PipelineOptions,
) -> BindResult:
    """Prove every proposed expected result, or delete it (SS9.5)."""
    return bind_claims(
        store,
        runner,
        model,
        drafted,
        model_name=options.model_name,
        budget=min(BIND_BUDGET, options.budget),
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
        config=options.project,
    )


def _second_chance(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    drafted: DraftResult,
    bound: BindResult,
    options: PipelineOptions,
) -> BindResult:
    """Ask again where binding left a scenario with no verdict at all.

    A scenario that ends on an action has nothing to pass or fail. It is the
    defect that shipped on a real recording, and draft-then-bind can produce it
    honestly: the drafter proposes the outcome it expected, the recording shows
    the opposite, and the claim is correctly deleted -- leaving a test case that
    describes what the tester did and never what should be true.

    Deleting was right. Stopping there was not. The run knows exactly why the
    claim failed, and that reason is the most useful thing anyone could hand a
    second attempt: *the export returned 500, so nothing was downloaded.* On a
    session that ended in an error the answer is usually that the error IS the
    expected result.

    Once, and only for a scenario left with nothing. This is not a repair loop
    -- it is the difference between an empty verdict and a real one, and a
    second attempt that also fails costs one call and changes nothing.
    """
    if not options.tools_enabled:
        return bound

    reasons: dict[str, str] = {}
    for scenario in drafted.scenarios:
        if not scenario.steps:
            continue
        step_ids = {s.step_id for s in scenario.steps}
        anything = any(bound.for_step(sid) for sid in step_ids)
        closes = bool(bound.for_step(scenario.steps[-1].step_id))

        # Two ways a scenario ends up with no verdict, and both are worth one
        # more question.
        #
        #   * nothing in it bound at all
        #   * it bound something and then ENDS ON AN ACTION -- which reads as a
        #     test that stops mid-sentence. Seen on a real recording: the
        #     scenario proved the quantity limit and then trailed off with
        #     "the tester opens the shopping bag".
        if anything and closes:
            continue

        target = scenario.steps[-1].step_id if anything else None
        dropped = [c for c in bound.claims if c.step_id in step_ids and c.assertion is None]

        if target is None:
            if not dropped:
                # Nothing was proposed for this scenario in the first place, so
                # there is no evidence to feed back. `gherkin_style` says
                # plainly that the scenario has no verdict, and that is the
                # honest outcome.
                continue
            last = dropped[-1]
            target = last.step_id
            why = (
                f"the expected result {last.text!r} could not be proved: {last.reason}. "
                f"This scenario now has no expected result at all."
            )
        else:
            why = (
                "this is the last step of the scenario and it has no expected result, so "
                "the test ends on an action with nothing to pass or fail."
            )

        reasons[target] = (
            f"{why} Propose one that says what the recording actually shows happened -- "
            f"including a failure, if that is what happened. An empty list is still a "
            f"valid answer if this step genuinely established nothing."
        )

    if not reasons:
        return bound

    changed = repropose_expectations(
        store,
        runner,
        model,
        drafted,
        findings=reasons,
        model_name=options.model_name,
        budget=min(BIND_BUDGET, options.budget),
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
        config=options.project,
        attempt=1,
    )
    if not changed:
        return bound

    retried = _bind(store, runner, model, drafted, options)
    # Keep the record of what was tried and rejected the first time. A reviewer
    # asking "why is there no expected result here" deserves both answers, and
    # SS3.4 counts the retrievals either attempt spent.
    retried.claims = [*bound.claims, *retried.claims]
    retried.investigations = [*bound.investigations, *retried.investigations]
    retried.model_calls = [*bound.model_calls, *retried.model_calls]
    return retried


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
        # A critic failure must not cost the run: the drafting and binding
        # stages have already produced the expensive, evidence-bound part. But
        # it must not read as approval either -- an empty findings list from a
        # critic that crashed and one from a critic that read the output and
        # liked it are the same value and opposite facts.
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
    drafted: DraftResult,
    bound: BindResult,
    pending: list,
    options: PipelineOptions,
    attempt: int,
) -> tuple[BindResult, set[str]]:
    """Re-run the offending stage for the flagged steps only (SS9.9).

    Two repairs, matching the two things a model wrote: the step's sentence and
    the step's expected result. Both edit the DRAFT in place and never touch
    `eventIds` or `step_id` -- that constraint is what keeps `event_coverage`
    and the scenario grouping stable across attempts.

    Returns the ids that actually changed, which is not the same as the ids
    asked about: `rewrite_steps` refuses a rewrite that would collide with a
    neighbour, and a re-proposed expected result can legitimately come back
    empty. A finding whose repair produced no change stays unresolved rather
    than being marked fixed because a stage ran.
    """
    renames = {t.step_id: t.finding for t in pending if t.stage == PipelineStage.name}
    reasserts = {t.step_id: t.finding for t in pending if t.stage == PipelineStage.assert_}
    touched: set[str] = set()

    if renames:
        touched |= rewrite_steps(
            store,
            runner,
            model,
            drafted,
            findings=renames,
            model_name=options.model_name,
            budget=options.budget if options.tools_enabled else 0,
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            attempt=attempt,
        )

    if reasserts:
        # What each flagged step could prove BEFORE the repair. A repair that
        # trades a bound claim for an unbindable one has made the output worse
        # (see `_keep_provable`), and the only way to know is to remember.
        previous = {sid: list(s.expects) for sid, s in _by_id(drafted).items()}
        changed = repropose_expectations(
            store,
            runner,
            model,
            drafted,
            findings=reasserts,
            model_name=options.model_name,
            budget=min(BIND_BUDGET, options.budget) if options.tools_enabled else 0,
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            attempt=attempt,
        )
        touched |= changed
        # Re-bound from scratch, including the claims that were left alone: a
        # rewritten step sentence changes what its expected result has to be
        # about, and binding is cheap for anything the deterministic pass can
        # settle.
        if changed or renames:
            retried = _bind(store, runner, model, drafted, options)
            bound, reverted = _keep_provable(drafted, previous, bound, retried)
            touched -= reverted

    return bound, touched


def _by_id(drafted: DraftResult) -> dict[str, Any]:
    return {step.step_id: step for step in drafted.steps}


def _keep_provable(
    drafted: DraftResult,
    previous: dict[str, list],
    before: BindResult,
    after: BindResult,
) -> tuple[BindResult, set[str]]:
    """A repair may not trade a claim that binds for one that does not.

    Found in an ablation, and it cost real output. On the `hardpaths` fixture
    A1 bound two true expected results -- *the status shows "Payment method
    saved"* and *the page displays "Validating with the finance system..."*.
    The critic then said each checked "a status message rather than the
    successful saving" and "a loading state rather than the completion of the
    validation process": plausible sentences, and both asking for something the
    recording does not contain, because the slow validation never finishes
    inside it. Repair obeyed, binding correctly refused the replacements, and
    A2 shipped a scenario with NO expected results where A1 had two.

    The critic being wrong is not the bug. The critic is allowed to be wrong --
    it is a second opinion, and SS9.9 bounds it precisely because it can be.
    The bug is that repair replaced a proven claim before finding out whether
    the replacement could be proven at all.

    So the swap only stands where it is not a loss. Where it is, the original
    claims come back and the finding is reported unresolved, which is SS9.9's
    designed outcome on exhaustion and an honest description of what happened:
    somebody thought this could be said better, and it could not be said at
    all.
    """
    steps = _by_id(drafted)
    reverted: set[str] = set()

    for step_id, was in previous.items():
        if not before.for_step(step_id) or after.for_step(step_id):
            continue
        reverted.add(step_id)
        if step_id in steps:
            steps[step_id].expects = was

    if not reverted:
        return after, reverted

    # Keep every claim the retry DID settle, and restore the originals for the
    # steps that lost everything. The superseded attempt stays in the record:
    # the run really did spend those retrievals, and SS3.4's effort column
    # under-reporting a step that took two passes would hide exactly the step
    # it exists to find.
    merged = BindResult(
        claims=[c for c in after.claims if c.step_id not in reverted]
        + [c for c in before.claims if c.step_id in reverted]
        + [c for c in after.claims if c.step_id in reverted and c.assertion is None],
        investigations=[*after.investigations],
        model_calls=[*after.model_calls],
    )
    return merged, reverted


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
        `state_jump` need the document re-drafted, and re-drafting can change
        the step count (SS3.6)
      * a finding whose repair ran out of budget
      * a rewrite that was refused because it would have collapsed two steps

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


def _drop_rejected(ir: IRDocument, report: ValidationReport) -> bool:
    """Delete every claim the gate rejected and the repair loop could not fix.

    SS9.7 gives `assertion_grounding` and `evidence_retrieved` the action
    **Reject**, and SS9.5 says "an assertion whose evidence cannot be retrieved
    is not emitted". Neither was true. `reject` only made the REPORT not-ok;
    the repair loop is bounded, so a run could exhaust its attempts and then
    render the claim anyway with a warning recorded beside it in `ir.json`. A
    real feature file shipped

        Then the quantity of the tea selection increases to 18

    while the same run's own warnings said the literal did not appear at the
    event it cited. Two components disagreeing about grounding, resolved in
    favour of shipping, with a clean evidence trail behind a wrong number.

    Under draft-then-bind this is nearly always already handled: an unbindable
    claim is deleted by `bind.py` and never reaches the renderer. This is the
    net for what repair touched afterwards, and for anything a future stage
    adds to the IR without going through binding.

    Deleting the assertion and not the step: the step happened, and the reader
    should still see what the tester did. What is removed is the claim about it
    that nothing supports.
    """
    doomed: set[str] = {
        r.assertionId
        for r in report.results
        if r.assertionId
        and r.status == ValidatorStatus.fail
        and r.action == ValidatorAction.reject
    }
    if not doomed:
        return False

    removed = False
    for case in ir.testCases:
        for step in case.steps:
            keep = [a for a in step.assertions if a.id not in doomed]
            if len(keep) == len(step.assertions):
                continue
            removed = True
            for assertion in step.assertions:
                if assertion.id in doomed:
                    case.warnings.append(
                        Warning(
                            id=f"warn_dropped_{len(case.warnings) + 1:03d}",
                            source="validator",
                            severity="warn",
                            message=(
                                f"an expected result was removed because the run could not "
                                f"prove it: {assertion.text!r}"
                            ),
                            code="unbound_claim_removed",
                            stepId=step.id,
                        )
                    )
            step.assertions = keep
    return removed


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def _assemble(
    recording: Recording,
    run_id: str,
    drafted: DraftResult,
    bound: BindResult,
) -> IRDocument:
    """Turn the drafted document and its bound claims into the IR.

    The drafter decided the steps and the scenarios, so there is nothing here
    that re-decides them. `merge_repeats` stays as the net for two adjacent
    steps that came back with identical sentences, which is a defect wherever
    it comes from.
    """
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

    omitted = [
        {
            "eventIds": list(o.event_ids),
            "reason": o.reason.value,
            "eventCount": len(o.event_ids),
            "summary": o.summary,
            "afterStepId": "",
        }
        for o in drafted.omitted
    ]

    cases: list[TestCaseIR] = []
    scenarios = [s for s in drafted.scenarios if s.steps]
    earlier_setup: list[Step] = []

    for index, scenario in enumerate(scenarios, start=1):
        steps = merge_repeats(
            [
                Step(
                    id=step.step_id,
                    keyword=step.keyword,
                    role=step.role,
                    text=step.text,
                    eventIds=step.event_ids,
                    # Every step points at the one investigation that wrote the
                    # document. The old per-step investigation ref described a
                    # retrieval loop run for that step alone, and there is no
                    # longer any such thing: one author wrote all of them.
                    investigationRef="inv_draft",
                    assertions=bound.for_step(step.step_id),
                    confidence=drafted.confidence,
                    fidelity=_flags(recording, step.event_ids),
                    selectorHints=_selector_hints(recording, step.event_ids),
                )
                for step in scenario.steps
            ]
        )
        sync_keywords(steps)
        cases.append(
            _build_case(
                recording,
                run_id,
                steps,
                drafted,
                scenario=scenario.name,
                warnings=warnings,
                index=index,
                of=len(scenarios),
                inherited_setup=list(earlier_setup),
                omitted=omitted if index == 1 else [],
            )
        )
        earlier_setup.extend(s for s in steps if s.role == SegmentRole.setup)

    return IRDocument(
        schemaVersion="1.0",
        recordingId=recording.id,
        runId=run_id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        testCases=cases,
    )


def _split_on_declared_breaks(store: EvidenceStore, drafted: DraftResult) -> None:
    """Cut where the tester said to, with no model in the loop (SS6.7).

    A scenario break is deterministic and overrides the drafter. Composition
    used to answer this differently on two consecutive runs of the same
    recording, once putting the tester's own boundary inside a single case --
    which is the tool overruling the person who was there.

    Splits only; it never joins. Where the tester declared a boundary the
    drafter already honoured, this does nothing.

    **The break is resolved by TIMESTAMP, not by `eventId`.** It has never had
    one and never will: `export.ts` attaches an annotation to an event only
    when it is a fact ABOUT that event, and a boundary sits between two of
    them. This read `a.eventId` and filtered out everything without one, so the
    set was always empty and the function always returned on its first line --
    a deterministic override that never once fired. `twoflows` exists to prove
    two test cases come out of one recording and had been shipping a single
    scenario with both flows inside it. `segment.break_openers` is the one
    resolution, shared so the two cannot drift apart again.
    """
    breaks = break_openers(store.recording)
    if not breaks:
        return

    out = []
    for scenario in drafted.scenarios:
        current = type(scenario)(name=scenario.name, steps=[])
        for step in scenario.steps:
            opens_break = bool(set(step.event_ids[:1]) & breaks)
            if opens_break and current.steps:
                out.append(current)
                # Left unnamed on purpose: `_scenario_from` names it after what
                # it verifies. Inventing a name here would be a guess wearing
                # the authority of a deterministic rule.
                current = type(scenario)(name="", steps=[])
            current.steps.append(step)
        if current.steps:
            out.append(current)

    if len(out) > len(drafted.scenarios):
        drafted.scenarios = out


def _scenario_from(steps: list[Step], drafted: DraftResult, index: int, of: int) -> str:
    """A name for a scenario the deterministic split created.

    Named after what it VERIFIES -- its last accepted expected result -- rather
    than after what it does. A scenario line that repeats the `When` under it is
    the same defect as a Feature that repeats its Scenario, and a reader
    scanning a list of them learns nothing from either. Falls back to the last
    step only when the case checks nothing, which is itself worth seeing.
    """
    tested = [s for s in steps if s.role != SegmentRole.setup] or steps
    checks = [a.text for s in tested for a in s.assertions if a.accepted]
    text = (checks[-1] if checks else (tested[-1].text if tested else "")).strip()
    if text:
        return text[:1].upper() + text[1:]
    return drafted.title if of == 1 else f"{drafted.title} ({index})"


def _build_case(
    recording: Recording,
    run_id: str,
    steps: list[Step],
    drafted: DraftResult,
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
        title=drafted.title,
        description=drafted.description or scenario,
        scenarioName=scenario or _scenario_from(steps, drafted, index, of),
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
        tags=drafted.tags,
        parameters=_parameters(recording, steps),
        steps=steps,
        omitted=omitted or [],
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


def _parameters(recording: Recording, steps: list[Step]) -> list[dict[str, str]]:
    """The values whoever runs this test actually has to supply (SS7.2).

    Redaction runs over every request and response body on every origin, and
    that is correct: a secret must never reach disk, and a rule that fired only
    on the application's own traffic would miss one leaking through a third
    party. But publishing every placeholder it minted as a required test
    parameter is a different thing entirely, and on a commercial site it is
    badly wrong -- eleven numeric strings inside analytics payloads matched the
    phone pattern and were handed to the tester under a heading telling them to
    supply real values. None of them existed.

    Two filters, and a parameter has to pass one of them: it appears in the
    rendered test, or it stands for something the tester actually typed. The
    first is what makes the list useful; the second keeps a placeholder that a
    step legitimately dropped from vanishing silently.
    """
    written = " ".join(
        [s.text for s in steps] + [a.text for s in steps for a in s.assertions]
    )
    typed = {p.placeholder for p in typed_parameters(recording)}
    return [
        {"name": p.name, "placeholder": p.placeholder, "category": p.category.value}
        for p in recording.parameters
        if p.placeholder and (p.placeholder in written or p.placeholder in typed)
    ]


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
    drafted: DraftResult,
    bound: BindResult,
    critic: CriticResult | None = None,
) -> AgentTrace:
    models = {
        "draft": {"provider": "configured", "model": options.model_name},
        "bind": {"provider": "configured", "model": options.model_name},
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

    investigations = [*bound.investigations, *drafted.repairs]
    if drafted.investigation is not None:
        investigations.insert(0, drafted.investigation)
    if critic is not None:
        investigations.extend(critic.investigations)

    model_calls = [*drafted.model_calls, *bound.model_calls]
    if critic is not None:
        model_calls.extend(critic.model_calls)

    return AgentTrace(
        schemaVersion="1.0",
        runId=run_id,
        recordingId=recording.id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        config=config,
        toolCalls=runner.calls,
        modelCalls=model_calls,
        investigations=investigations,
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=[],
    )


#: Calls made because the process requires them on every step, not because this
#: step was hard. Excluded from the effort metrics below.
#:
#: `search_step_library` is no longer called on every step -- the per-step
#: search went with the naming stage -- but the exclusion stays, because the
#: reason it exists is general: a call the process mandates regardless of
#: difficulty is a constant added to every reading of an adaptive-effort metric.
ROUTINE_TOOLS = {"search_step_library"}


def _selector_hints(recording: Recording, event_ids: list[str]) -> list[SelectorHint]:
    """Carry the recorder's selectors onto the step, ranked.

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

    The drafting investigation carries no step id and so appears only in the
    total, which is correct rather than a gap: it wrote the whole document, and
    charging its retrievals to one step would invent a difficulty signal that
    does not exist. What IS per-step now is what was spent settling that step
    specifically -- binding a contested claim, and repairing a finding -- which
    is a sharper reading of "how hard was this step" than a per-segment naming
    loop that ran whether or not anything about the segment was unclear.

    A call the process mandates on every step regardless of difficulty is a
    constant added to every reading, so `ROUTINE_TOOLS` is excluded. Measured
    when search-before-invent ran per step: it lifted calls-per-step from 1.56
    to 2.17 and collapsed the spread from 1.08 to 0.16, which reads as an agent
    that stopped adapting when nothing of the sort had happened.
    `toolCallsTotal` still counts them -- they are real calls that cost real
    quota -- but they are not evidence of investigation.
    """
    routine = {c.id for c in (trace_calls or []) if getattr(c, "tool", None) in ROUTINE_TOOLS}
    per_step: dict[str, int] = {}

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
    run yet -- and counting it only in the final rate would move the number for
    a reason that has nothing to do with repair.
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
    and a stage nobody remembered to add was simply invisible in the numbers.
    The trace already has to hold every model call and every investigation
    (SS9.10), so there is exactly one list to be wrong about.
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
                r.validator for r in first_report.results if r.status != ValidatorStatus.skip
            },
        ),
        # Never one without the other. A convergence rate over zero findings is
        # vacuously 1.0, exactly the way `groundingRate` is vacuously 1.0 for a
        # configuration that abstains -- the trap this project has now hit in
        # four separate columns.
        criticFindingsRaised=outcome.findings_raised,
        repairConvergenceRate=outcome.convergence_rate,
        # Every retrieval the run actually made, read from the log rather than
        # summed over investigations. Summing investigations undercounts by
        # exactly the calls no investigation wrapped -- which is how this came
        # to exclude composition once, and would now exclude every claim the
        # deterministic pass settled without asking a model.
        toolCallsTotal=len(trace.toolCalls),
        toolCallsPerStep=_calls_per_step(investigations, trace.toolCalls),
        promptTokensTotal=sum(m.promptTokens or 0 for m in model_calls),
        completionTokensTotal=sum(m.completionTokens or 0 for m in model_calls),
        uncachedModelCalls=len([m for m in model_calls if not m.cached]),
        durationMs=elapsed * 1000,
    )


__all__ = [
    "PipelineOptions",
    "PipelineResult",
    "ROUTINE_TOOLS",
    "run_pipeline",
]
