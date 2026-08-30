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
from server.llm.gemini import DEFAULT_MODEL
from server.models import (
    AblationConfig,
    AgentTrace,
    BugDetail,
    BugEnvironment,
    Confidence,
    EvidenceStrength,
    ExpectationSet,
    IRDocument,
    PipelineStage,
    Recording,
    RepairAttempt,
    RepairTrigger,
    RunConfig,
    RunMetrics,
    ScenarioExamples,
    SegmentRole,
    SelectorHint,
    StageRecord,
    StageStatus,
    Step,
    StepInvestigation,
    TestCaseIR,
    TestCaseMetadata,
    TruncationPolicy,
    ValidatorAction,
    ValidatorName,
    ValidatorStatus,
    Warning,
)
from server.pipeline.author import (
    AUTHOR_BUDGET,
    AuthoredDocument,
    apply_intent_notes,
    write_document,
)
from server.pipeline.coverage import COVERAGE_BUDGET, CoverageResult, attach, suggest_coverage
from server.pipeline.digest import typed_parameters
from server.pipeline.expectations import empty_set, propose_expectations
from server.pipeline.judge import JUDGE_BUDGET, JudgeResult, judge_document
from server.pipeline.narrative import merge_repeats, normalise, sync_keywords
from server.pipeline.segment import break_openers, segment_recording
from server.pipeline.validators import (
    ValidationContext,
    ValidationReport,
    bug_claim,
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
    budget: int = AUTHOR_BUDGET
    #: Read from the provider module rather than pinned here. It was
    #: `gemini-2.5-flash`, which is no longer served to new keys at all, and
    #: only `cmd_serve` passing `--model` kept that from being fatal -- anything
    #: constructing `PipelineOptions()` directly got a dead model.
    model_name: str = DEFAULT_MODEL
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
    #: SS9.8. Gated on its own flag rather than on an ablation arm, so a
    #: comparison never measures two changes at once. Requires tools --
    #: reasoning about the unobserved still has to rest on something observed.
    suggestions_enabled: bool = True
    #: The oracle, when a caller already has it. `None` means "look beside the
    #: recording, and guess if nothing is there" -- see `_expectations`.
    expectations: ExpectationSet | None = None
    #: Off for A0, whose whole point is no retrieval and no extra model calls,
    #: and for any run that wants to measure the pipeline without an oracle.
    expectations_enabled: bool = True
    #: The judge, and the revision it can trigger. Gated on its own flag for the
    #: same reason `suggestions_enabled` is: a comparison must never measure two
    #: changes at once. Requires tools -- a judge that cannot look cannot answer
    #: "would this survive a broken build", which is the question it exists for.
    judge_enabled: bool = True
    #: Author rounds, total. Two means the document may be rewritten once.
    #:
    #: The old loop was bounded at three attempts PER STAGE across a routing
    #: table, and resolved one finding in nine. What made it fail was not the
    #: bound -- five of the seven survivors had no repair route at all -- but
    #: two is still the right number: every rewrite risks `merge_repeats`
    #: folding two steps into one, and a document nobody signed after one
    #: honest revision is telling you something upstream is wrong.
    max_author_rounds: int = 2

    @classmethod
    def for_config(cls, config: AblationConfig, **overrides: Any) -> PipelineOptions:
        """The three arms, redefined around what the pipeline now has.

        They used to differ by "critic, repair loop", and those are gone: the
        loop raised 9 findings and resolved 1, because five of the survivors
        were `coherence`, which had no repair route by design. Measuring that
        again would measure the same nothing.

        What is worth comparing now is the two things the rebuild added, one at
        a time:

            A0  no retrieval, no oracle -- one shot over the session index
            A1  retrieval, no oracle    -- isolates what LOOKING is worth
            A2  retrieval and oracle    -- isolates what ASKING is worth

        A1 vs A2 is the measurement this project has never been able to make,
        because until now there was nothing to compare an oracle against.

        The judge is NOT one of the three. It is gated on `judge_enabled` and
        runs in every arm that has tools, so an arm is never the difference
        between two changes at once -- and so a judgement exists for A1 and A2
        alike, which is what makes them comparable on quality rather than only
        on provenance. A0 cannot have one: it has no tools, and a judge that
        cannot look cannot answer its own first question.
        """
        presets = {
            AblationConfig.A0: {
                "tools_enabled": False,
                "expectations_enabled": False,
                "judge_enabled": False,
            },
            AblationConfig.A1: {"tools_enabled": True, "expectations_enabled": False},
            AblationConfig.A2: {"tools_enabled": True, "expectations_enabled": True},
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
    document: AuthoredDocument
    grounding_rate: float
    duration_ms: float
    #: What should have happened, as the run understood it. Kept on the result
    #: so a caller can tell a run that was TOLD from a run that guessed.
    expectations: ExpectationSet | None = None
    #: The gate's verdict before anything downstream edited it. The same
    #: document as `report` now that nothing repairs, and kept because SS3.5's
    #: table asks for the first-attempt rate by name -- the coverage stage edits
    #: `report.results` in place, and would otherwise backdate itself into it.
    first_report: ValidationReport | None = None
    #: What the judge sent back, on the FINAL document. A run that revised
    #: carries the second judgement, which is the one that describes what
    #: shipped; `revision_rounds` says whether there was a first.
    judgement: JudgeResult | None = None
    #: Author rounds actually run. 1 is the normal case and means the judge
    #: found nothing worth another pass -- read it beside `judgement.findings`,
    #: or it is the vacuous half of a pair for the eighth time.
    revision_rounds: int = 1
    sidecars: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_calls_per_step(self) -> dict[str, int]:
        """Retrievals per step.

        One stage investigates now, which is the point rather than a
        simplification: SS3.3's claim is that effort lands unevenly, heavily on
        the contested steps and not at all on the obvious ones, and a per-step
        budget spread across five stages could not express that. Read from the
        trace rather than from the author, because effort is what the run spent
        on a step whoever spent it.
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

    announce = _announcer(options)

    # -- 1. segment (deterministic) ---------------------------------------
    #
    # Demoted, deliberately. Its boundaries no longer decide step boundaries --
    # a step is an INTENT and the author groups events into one -- but idle
    # gaps, URL changes and the tester's own checkpoints are real signals about
    # where intents end, and they reach the author as hints in the index.
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
    runner = ToolRunner(store=store, storage=storage, run=run, stage=PipelineStage.author)

    # -- 2. expectations (agentic, retrieves, small budget) ----------------
    #
    # The oracle, and the only stage that says what SHOULD have happened.
    # Everything else here can license claims only about what was observed,
    # which is why the tool was structurally unable to write a test that fails
    # on the build it recorded.
    #
    # It retrieves because the expectation has to name a VALUE for a human to
    # tick, and the index does not always carry one. Bounded at
    # `GUESS_BUDGET`, because the tester is waiting on this screen. Its
    # retrievals go through the same runner and so reach `trace.toolCalls`
    # like any other -- which is correct for `_calls_per_step`, whose whole
    # claim is that effort is what the run spent on a step, whoever spent it.
    announce(PipelineStage.expectations)
    t0 = time.time()
    expectations = _expectations(store, runner, model, storage, options)
    path = storage.save_artifact(run, "expectations", expectations)
    stages.append(
        StageRecord(
            stage=PipelineStage.expectations,
            attempt=1,
            outputPath=run.relative(path),
            startedAt=t0,
            endedAt=time.time(),
            status=StageStatus.ok,
        )
    )

    # -- 3, 4, 5. author, render, gate, judge -- at most twice ------------
    #
    # The author was five stages: draft, split, bind, second chance, bug mode.
    # Every one of them was machinery for catching an author guessing about
    # something it could not see, and it could not see because the recorder
    # captured the landmark around the click rather than the page. Opening the
    # aperture left them with nothing to catch. See `author.py`.
    #
    # The loop around it is not that machinery coming back. There is no routing
    # table: the author wrote the document and is the only thing that knows
    # which part of it is wrong, so everything -- a rejected claim, a judge's
    # finding -- reaches it as one list of sentences and it decides. That is the
    # whole of SS9.9 now, and the old version's record is why: nine findings,
    # one resolved, because five of the survivors had no route in the table.
    feedback: list[str] = []
    repairs: list[RepairAttempt] = []
    judge_investigations: list[StepInvestigation] = []
    judge_model_calls: list[Any] = []
    first_report: ValidationReport | None = None
    judgement: JudgeResult | None = None
    previous: AuthoredDocument | None = None
    attempt = 0

    while True:
        attempt += 1

        announce(PipelineStage.author)
        t0 = time.time()
        document = write_document(
            store,
            runner,
            model,
            model_name=options.model_name,
            budget=options.budget,
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            expectations=expectations,
            feedback=feedback or None,
        )
        # SS6.7 -- where the tester typed the step name themselves, it is
        # theirs. Applied here rather than asked for in the prompt, because the
        # popup makes the tester a promise ("used word for word") and a prompt
        # that asks is not a guarantee.
        apply_intent_notes(store, document)
        # And where they pressed the button, the cut is theirs too.
        # Deterministic, no model consulted, splits only and never joins.
        _split_on_declared_breaks(store, document)

        # A revision that would lose a step is refused, and the previous
        # document ships. `merge_repeats` folds any two ADJACENT steps whose
        # text matches exactly, so a rewrite prompted with "this verdict proves
        # nothing" can make one step's name generic enough to swallow its
        # neighbour -- which changes the step COUNT between two attempts of the
        # same run, breaking SS3.6's promise, and moves `Yield`'s denominator so
        # the metric improves because a step vanished.
        #
        # `narrative.would_collapse` is the same guard for the old loop, which
        # rewrote one step at a time and could ask "would THIS replacement
        # collapse". A whole-document rewrite has no index to ask about, so the
        # question becomes whether the new document contains such a pair at all.
        if previous is not None and _collapsing_pair(document):
            document = previous
            repairs.append(
                RepairAttempt(
                    stage=PipelineStage.author,
                    attempt=attempt,
                    trigger=RepairTrigger.judge,
                    finding=(
                        "the revision put two adjacent steps with identical text in one "
                        "scenario, which merge_repeats would fold into one -- kept the "
                        "previous document"
                    ),
                )
            )

        path = storage.save_artifact(run, "author", document.to_artifact())
        stages.append(
            StageRecord(
                stage=PipelineStage.author,
                attempt=attempt,
                inputPath=run.relative(run.artifact("segments")),
                outputPath=run.relative(path),
                startedAt=t0,
                endedAt=time.time(),
                status=StageStatus.degraded if document.degraded else StageStatus.ok,
                **({"error": document.degraded} if document.degraded else {}),
            )
        )

        # -- render --------------------------------------------------------
        announce(PipelineStage.render)
        t0 = time.time()
        ir = _assemble(recording, run_id, document)
        storage.save_artifact(run, "ir", ir)
        trace = _trace(recording, run_id, options, runner, document)
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

        # -- the facts (deterministic) -------------------------------------
        #
        # Five checks, down from fourteen. The rule for keeping one is not
        # "deterministic or agentic" but **can this check ever be wrong**: a
        # string is or is not in a response, a file does or does not parse, an
        # event was or was not accounted for. Those cost nothing and constrain
        # nothing.
        #
        # The nine that went were judgements written as regexes -- is this claim
        # vacuous, does this name match this scenario, would this catch a
        # regression. A regex guessing whether a sentence is meaningful will
        # always lose to a model reading it, and in 33 runs and 455 executions
        # they produced ONE failure between them while the judge found real
        # defects that all fourteen passed. Those questions are the judge's now,
        # immediately below, which is the other half of that decision.
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
        # SS3.5 asks for the FIRST-attempt rate by name, and it has to be
        # captured here: a second round overwrites `report` entirely, and the
        # distance between the two is the only thing that says what revising
        # bought. A single number reporting the second would be the loop marking
        # its own homework.
        if first_report is None:
            first_report = ValidationReport(results=list(report.results))

        # -- the judge -----------------------------------------------------
        judgement = _judge(
            store, runner, model, ir, storage, run, options, rendered, expectations, attempt
        )
        if judgement is not None:
            judge_investigations.extend(
                [judgement.investigation] if judgement.investigation else []
            )
            judge_model_calls.extend(judgement.model_calls)
            stages.append(
                StageRecord(
                    stage=PipelineStage.judge,
                    attempt=attempt,
                    inputPath=run.relative(run.artifact("ir")),
                    outputPath=run.relative(run.artifact("judge")),
                    startedAt=t0,
                    endedAt=time.time(),
                    status=StageStatus.degraded if judgement.failed else StageStatus.ok,
                    **({"error": judgement.failed} if judgement.failed else {}),
                )
            )

        feedback, triggers = _revision_feedback(report, judgement, document)
        if not feedback or attempt >= max(1, options.max_author_rounds):
            # Findings the loop did not get to act on are still findings. They
            # are recorded as exhausted rather than dropped -- an unresolved
            # thing that vanishes from the trace is how `Converged` came to
            # measure how much of what the critic said the loop was ALLOWED to
            # touch, rather than how much it fixed.
            repairs.extend(
                RepairAttempt(
                    stage=PipelineStage.author,
                    attempt=attempt,
                    trigger=trigger,
                    finding=text,
                    exhausted=True,
                )
                for text, trigger in zip(feedback, triggers, strict=True)
            )
            break

        repairs.extend(
            RepairAttempt(
                stage=PipelineStage.author,
                attempt=attempt,
                trigger=trigger,
                finding=text,
            )
            for text, trigger in zip(feedback, triggers, strict=True)
        )
        previous = document

    trace.repairAttempts = repairs
    trace.investigations.extend(judge_investigations)
    trace.modelCalls.extend(judge_model_calls)
    _sync_calls(trace, runner)

    # -- 6. coverage suggestions (SS9.8) -----------------------------------
    #
    # After the gate has settled, which SS9.8 requires in as many words: a
    # suggestion derived from a document the validators went on to reject would
    # be advice about a test case that no longer exists.
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
        storage.save_artifact(run, "ir", ir)
        if options.project.trace == "sidecar":
            sidecars = trace_md.render_document(ir, trace=trace, config=options.project)
        _write_output(run, ir, rendered, sidecars, options.project)

    rate = grounding_rate(ctx, report)
    _sync_calls(trace, runner)
    trace.validatorResults = report.results
    trace.metrics = _metrics(ir, trace, report, first_report, rate, judgement, attempt)
    trace.stages = stages
    trace_path = storage.save_artifact(run, "trace", trace)

    # The output is emitted even when the gate rejects it: the report says
    # plainly what is wrong with it, and hiding the draft would leave nothing to
    # inspect. The one exception is a leaked secret, which must not be written
    # at all (SS9.7).
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
        document=document,
        expectations=expectations,
        first_report=first_report,
        judgement=judgement,
        revision_rounds=attempt,
        grounding_rate=rate,
        duration_ms=(time.perf_counter() - started) * 1000,
        artifacts={
            "segments": run.artifact("segments"),
            "expectations": run.artifact("expectations"),
            "author": run.artifact("author"),
            "judge": run.artifact("judge"),
            "ir": run.artifact("ir"),
            "trace": trace_path,
            "coverage": run.artifact("coverage"),
        },
    )


# --------------------------------------------------------------------------
# the judge, and the one revision it can ask for
# --------------------------------------------------------------------------
def _announcer(options: PipelineOptions) -> Callable[[PipelineStage], None]:
    """Tell the caller which stage is starting, and never fail because of it.

    A progress callback is the least important thing in this file and must not
    be able to end a run that was otherwise going to succeed.
    """

    def announce(stage: PipelineStage) -> None:
        if options.on_stage is None:
            return
        with contextlib.suppress(Exception):
            options.on_stage(stage)

    return announce


def _judge(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    ir: IRDocument,
    storage: Storage,
    run: RunPaths,
    options: PipelineOptions,
    rendered: dict[str, str],
    expectations: ExpectationSet | None,
    attempt: int,
) -> JudgeResult | None:
    """Ask whether this is a test case a QA lead would sign.

    Degrades rather than fails, the same bargain the coverage stage makes: a
    judgement is worth less than the document it judges, and a run lost to a
    critic is exactly what the rebuild deleted. A judge that did not run says
    so in `failed` instead of returning a clean verdict it never reached.
    """
    if not (options.judge_enabled and options.tools_enabled):
        return None

    announce = _announcer(options)
    announce(PipelineStage.judge)
    try:
        result = judge_document(
            store,
            runner,
            model,
            ir,
            model_name=options.model_name,
            rendered=rendered,
            budget=min(JUDGE_BUDGET, options.budget),
            tools_enabled=options.tools_enabled,
            temperature=options.temperature,
            config=options.project,
            expectations=expectations,
        )
    except Exception as exc:  # noqa: BLE001 - degraded, never fatal
        result = JudgeResult(failed=f"{type(exc).__name__}: {exc}")

    storage.save_artifact(run, "judge", {**result.to_artifact(), "attempt": attempt})
    return result


def _revision_feedback(
    report: ValidationReport,
    judgement: JudgeResult | None,
    document: AuthoredDocument | None = None,
) -> tuple[list[str], list[RepairTrigger]]:
    """What the author is told, and who said it.

    Three sources and one destination. A refused claim and a rejected one are
    facts -- the literal is not in a retrieval this run made -- and a judge's
    `fail` is a judgement, but the author is asked the same thing by all of
    them: this part of your document is wrong, write it again.

    **A refusal used to reach nobody, and that was a hole.** When the author
    quotes a literal it never retrieved, `_attach_claim` drops the claim and
    writes a `whyNot` -- so it never becomes an assertion, so `evidence_retrieved`
    has nothing to reject, so the loop sees a clean gate and stops. Measured on a
    live run: the author wrote two correct verdicts quoting a count that was
    plainly in the session index, made zero tool calls, had both refused, and was
    never told. The gate did its job perfectly and the document shipped with no
    verdicts at all.

    That is the one finding the author can always act on, because the fix is
    entirely in its hands: go and retrieve the thing, or say in `whyNot` that you
    could not. The revision prompt already carries the warning that matters --
    being told a claim proves nothing is not permission to bind a weaker one.

    **Only `fail` travels from the judge.** A `weak` finding is one a QA lead
    would sign after an edit, and rewriting an acceptable document to chase one
    costs an author round and risks losing a step to `merge_repeats`. `weak`
    still reaches the trace and the reviewer; it just does not spend a round.
    """
    out: list[str] = []
    triggers: list[RepairTrigger] = []

    for refusal in (document.refused if document else [])[:6]:
        out.append(
            f"You wrote \"{refusal['claim']}\" and it was dropped, because "
            f"{refusal['reason']}. Retrieve the thing you are claiming and quote "
            f"the answer, or say in whyNot that you could not check it."
        )
        triggers.append(RepairTrigger.validator)

    for result in report.results:
        if result.action in {ValidatorAction.reject, ValidatorAction.hard_fail}:
            out.append(f"{result.validator.value}: {result.message}")
            triggers.append(RepairTrigger.validator)

    for finding in judgement.fails if judgement else []:
        out.append(finding.as_feedback())
        triggers.append(RepairTrigger.judge)

    return out, triggers


def _collapsing_pair(document: AuthoredDocument) -> bool:
    """Does any scenario contain two adjacent steps that say the same thing?

    `merge_repeats` would fold them, deleting a step. See the call site for why
    that is refused rather than allowed and reported.
    """
    for scenario in document.scenarios:
        texts = [normalise(step.text) for step in scenario.steps]
        if any(a and a == b for a, b in zip(texts, texts[1:], strict=False)):
            return True
    return False


# --------------------------------------------------------------------------
# the oracle, and keeping the trace honest
# --------------------------------------------------------------------------
def _expectations(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    storage: Storage,
    options: PipelineOptions,
) -> ExpectationSet:
    """What should have happened. Answered by a human if one has; guessed if not.

    Three ways in, and the order is the point:

    * `options.expectations` -- handed in by a caller that already has them.
    * `expectations.json` beside the recording -- somebody used the confirmation
      screen. Authoritative, and never overwritten.
    * a guess -- one model call, everything `inferred`, scenarios resting on one
      carry `@needs-review`.

    The third path is the one that has to be right, because it is what happens
    when nobody clicks anything. A run must never depend on a screen having been
    visited.
    """
    if options.expectations is not None:
        return options.expectations

    stored = storage.load_expectations(store.recording.id)
    if stored:
        with contextlib.suppress(Exception):
            return ExpectationSet.model_validate(stored)

    if not options.expectations_enabled:
        return empty_set(store.recording.id)

    try:
        guessed = propose_expectations(
            store,
            runner,
            model,
            model_name=options.model_name,
            temperature=options.temperature,
            tools_enabled=options.tools_enabled,
            config=options.project,
        )
    except Exception:  # noqa: BLE001 - a missing oracle degrades, never fails
        # The rest of the pipeline works without this; it just cannot say what
        # should have happened, only what did. Losing a run over the stage that
        # exists to IMPROVE it would be the wrong trade.
        return empty_set(store.recording.id)

    # Saved beside the recording, so the confirmation screen has something to
    # show and a second run inherits the answers.
    with contextlib.suppress(OSError):
        storage.save_expectations(guessed)
    return guessed


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


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def _assemble(recording: Recording, run_id: str, drafted: AuthoredDocument) -> IRDocument:
    """Turn the authored document into the IR.

    Nothing here re-decides anything. The author chose the steps, the scenarios,
    the keywords and which claims survived; this lays them out. `merge_repeats`
    stays as the net for two adjacent steps that came back with identical
    sentences, which is a defect wherever it comes from.
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
                    investigationRef="inv_author",
                    assertions=step.assertions,
                    # The refusal, in the tester's language. Never rendered into
                    # the feature body -- that is prose and nothing else -- but
                    # it is the difference between a scenario that explains why
                    # it has no verdict and one that just stops.
                    whyNot=step.why_not or None,
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
                bug=_bug_detail(recording, scenario, steps),
                scenario=scenario.name,
                warnings=warnings,
                index=index,
                of=len(scenarios),
                examples=scenario.examples,
                extra_tags=scenario.tags,
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


def _bug_detail(recording: Recording, scenario: Any, steps: list[Step]) -> BugDetail | None:
    """A failed expectation, as a bug report (SS14.2).

    Bug mode was a stage with a narrow trigger -- a 5xx, an uncaught exception,
    or the tester's marker -- and it produced two reports in the project's
    history. It is not a stage now because it never needed to be one:
    *"expected 9 products, saw 24"* is the same sentence whether you file it as
    an assertion or as a bug, and the difference is one flag on the step.

    `actual` is bound exactly as tightly as any assertion -- it goes through
    `evidence_retrieved` in `grounding._assertions`, never a branch of its own.
    Where the author could not cite what it claims, there is no report.

    **`environment` is required by the schema and was not being passed**, so
    every construction of this raised a `ValidationError` out of `_assemble` and
    killed the run. The path is only reachable when a step is `bug=True` AND has
    an accepted assertion, which needs a tester to have pressed "Not right" on
    the confirmation screen -- and nobody ever has (14 expectations on disk, all
    `inferred`). A crash nobody could reach is still a crash, and making the
    confirmation screen reachable is what would have found it in production.
    """
    # The first flagged step that actually reached a claim, not simply the first
    # flagged step. One rejected expectation can name several events and
    # `_apply_rejections` marks every step touching one of them, so taking the
    # first and giving up when it has no assertion loses the report whenever the
    # tester's "Not right" spans a step that sets up and a step that checks.
    failing, claim = next(
        (
            (step, accepted)
            for step in scenario.steps
            if step.bug
            for accepted in [next((a for a in step.assertions if a.accepted), None)]
            if accepted is not None
        ),
        (None, None),
    )
    if failing is None or claim is None:
        return None

    rendered = next((s for s in steps if s.id == failing.step_id), None)
    return BugDetail(
        failureStepId=rendered.id if rendered else failing.step_id,
        expected=claim.text,
        actual=failing.actual or "the application did something else",
        actualEvidence=claim.evidence,
        environment=_bug_environment(recording, failing.event_ids),
    )


def _bug_environment(recording: Recording, event_ids: list[str]) -> BugEnvironment:
    """Where the defect was seen: browser, viewport, and the page it happened on.

    The URL is read off the failing step's own last event rather than off
    `metadata.startUrl` -- a bug filed against the page somebody signed in on,
    when it happened three navigations later at checkout, sends whoever picks it
    up to the wrong place.
    """
    url = recording.metadata.startUrl
    if event_ids:
        by_id = {event.id: event for event in recording.events}
        for event_id in reversed(event_ids):
            event = by_id.get(event_id)
            if event is not None and event.url:
                url = event.url
                break
    viewport = recording.metadata.viewport
    return BugEnvironment(
        browser=recording.metadata.browser,
        viewport=f"{viewport.w}x{viewport.h}",
        url=url,
    )


def _split_on_declared_breaks(store: EvidenceStore, drafted: AuthoredDocument) -> None:
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
        groups = []
        current = type(scenario)(name=scenario.name, steps=[])
        for step in scenario.steps:
            opens_break = bool(set(step.event_ids[:1]) & breaks)
            if opens_break and current.steps:
                groups.append(current)
                # Left unnamed on purpose: `_scenario_from` names it after what
                # it verifies. Inventing a name here would be a guess wearing
                # the authority of a deterministic rule.
                current = type(scenario)(name="", steps=[])
            current.steps.append(step)
        if current.steps:
            groups.append(current)

        # The cut invalidates the ORIGINAL name too, and this is the half that
        # was missing. The drafter wrote that name for the whole session; after
        # a break splits it, the first group no longer has the body the name
        # describes, and keeping it produces a scenario whose heading promises
        # something its steps never reach.
        #
        # `twoflows` shipped exactly that: *"An order exceeding the threshold
        # requires approval"* over a body that signs in, adds one item, and
        # asserts a cart badge. Every step true, every claim grounded, and the
        # only thing wrong was the name -- which nothing re-reads once binding
        # has decided what the scenario actually proves.
        if len(groups) > 1:
            groups[0].name = ""
        out.extend(groups)

    if len(out) > len(drafted.scenarios):
        drafted.scenarios = out


def _scenario_from(steps: list[Step], drafted: AuthoredDocument, index: int, of: int) -> str:
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
    drafted: AuthoredDocument,
    *,
    scenario: str,
    warnings: list[Warning],
    index: int,
    of: int,
    inherited_setup: list[Step] | None = None,
    omitted: list[dict] | None = None,
    examples: ScenarioExamples | None = None,
    extra_tags: list[str] | None = None,
    bug: BugDetail | None = None,
) -> TestCaseIR:
    case = TestCaseIR(
        id=f"tc_{recording.id}" if of == 1 else f"tc_{recording.id}_{index:02d}",
        recordingId=recording.id,
        runId=run_id,
        kind="bug_report" if bug else "test_case",
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
        tags=list(
            dict.fromkeys([*drafted.tags, *(extra_tags or []), *(["bug"] if bug else [])])
        ),
        # A `Scenario Outline` the AUTHOR asked for, which is a judgement about
        # test design rather than the rendering setting `parameters` controls.
        examples=examples,
        # SS14.2. Present only on a bug report, and its `actual` carries the
        # same citation any assertion does -- `grounding._assertions` yields it
        # into the same check rather than giving it a branch of its own.
        bug=bug,
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
    written = " ".join([s.text for s in steps] + [a.text for s in steps for a in s.assertions])
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

    # Clear what a PREVIOUS run into this same run id rendered, before writing.
    #
    # The filename carries the case id, and the case id carries the scenario
    # NUMBER, so a re-run that produces a different number of test cases leaves
    # the old ones behind: `checkout` shipped a run directory holding
    # `tc_..._01.feature` and `tc_..._02.feature` from a two-scenario run
    # alongside `tc_....feature` from the one-scenario re-run that replaced it.
    # Three feature files, two of them describing a document that no longer
    # exists, all downloadable through `/files/{name}` and all indistinguishable
    # from the current one.
    #
    # Scoped to this run's own directory and to the three suffixes this
    # function writes -- never a glob wide enough to reach `ir.json` or a tool
    # response, which are what the gate re-reads.
    # Derived from what is about to be WRITTEN, not from what the IR could
    # produce a name for. The feature file is now one per document rather than
    # one per test case, so a set built over `ir.testCases` would keep the very
    # per-case names this change stops writing -- and a run directory that had
    # rendered `tc_..._01.feature` and `tc_..._02.feature` would keep serving
    # both beside the new single file, which is the defect the comment above
    # describes wearing a new costume.
    keep = (
        {run.root / feature_filename(by_id[case_id], config) for case_id in rendered}
        | {run.root / trace_filename(by_id[case_id], config) for case_id in sidecars}
        | {run.root / bug_md.bug_filename(case, config) for case in ir.testCases}
    )
    for suffix in ("*.feature", "*.trace.md", "*.bug.md"):
        for stale in run.root.glob(suffix):
            if stale not in keep:
                stale.unlink(missing_ok=True)

    for case_id, text in rendered.items():
        (run.root / feature_filename(by_id[case_id], config)).write_text(text, encoding="utf-8")
    for case_id, text in sidecars.items():
        (run.root / trace_filename(by_id[case_id], config)).write_text(text, encoding="utf-8")
    # A bug report is never in `rendered` -- Gherkin refuses it (SS14) -- so it
    # would have no artifact at all without this. Always written, like the
    # feature file and for the same reason: the validation gate has already read
    # it, so it is not optional output.
    for case_id, text in bug_md.render_document(ir, config=config).items():
        (run.root / bug_md.bug_filename(by_id[case_id], config)).write_text(text, encoding="utf-8")


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
    document: AuthoredDocument,
) -> AgentTrace:
    """The run, as a record somebody else can audit.

    One author and one oracle call, so the lists this collects are short now.
    They are still collected from the DOCUMENT rather than accumulated stage by
    stage, for the reason the metrics give: a stage that forgets to add itself
    here is a stage that costs quota invisibly.
    """
    models = {"author": {"provider": "configured", "model": options.model_name}}
    if options.expectations_enabled:
        models["expectations"] = {"provider": "configured", "model": options.model_name}

    config = RunConfig(
        ablation=options.ablation,
        toolsEnabled=options.tools_enabled,
        expectationsEnabled=options.expectations_enabled,
        defaultInvestigationBudget=options.budget,
        fallbackEnabled=options.fallback_enabled,
        cassetteMode=options.cassette_mode,
        models=models,
    )
    if options.ablation == AblationConfig.A0:
        config.a0Truncation = TruncationPolicy(
            strategy="head_tail", tokenBudget=options.a0_token_budget
        )

    investigations = [document.investigation] if document.investigation else []

    return AgentTrace(
        schemaVersion="1.0",
        runId=run_id,
        recordingId=recording.id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        config=config,
        toolCalls=runner.calls,
        modelCalls=list(document.model_calls),
        investigations=investigations,
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=[],
    )




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


def _calls_per_step(ir: IRDocument, trace_calls: list) -> dict[str, int]:
    """The x-axis of the effort/difficulty correlation (SS3.4).

    **Attributed by the EVENT a call asked about, not by which stage made it.**
    That is a change, and it is forced: there is one investigation now, covering
    the whole document, so reading `StepInvestigation.stepId` would put every
    retrieval in the same bucket and the column would be a constant. SS3.4 would
    have quietly stopped measuring anything.

    Every tool the author has takes an `eventId`, and every event belongs to
    exactly one step (`event_coverage` is what makes that true). So "how hard
    was this step" is answerable from the log: count the retrievals that asked
    about the events it covers. A call with no event -- a session-wide
    `find_text`, say -- belongs to no step and is in the total only, which is
    correct: it was not spent on any one of them.

    Steps that cost nothing are recorded as 0 rather than omitted. Zero is a
    reading, and the whole claim of SS3.3 is that an obvious step should cost
    nothing while a contested one costs fifteen -- a correlation that silently
    dropped the cheap half would be measuring the expensive half against itself.
    """
    step_of_event: dict[str, str] = {}
    for case in ir.testCases:
        for step in case.steps:
            for event_id in step.eventIds:
                step_of_event.setdefault(event_id, step.id)

    per_step = {step.id: 0 for case in ir.testCases for step in case.steps}
    for call in trace_calls:
        event_id = (getattr(call, "args", None) or {}).get("eventId")
        step_id = step_of_event.get(str(event_id)) if event_id else None
        if step_id:
            per_step[step_id] = per_step.get(step_id, 0) + 1
    return per_step


def _graded_evidence(ir) -> list:
    """Every accepted claim's evidence, bug reports included.

    Kept in step with `validators.grounding.claim_total` and `_assertions` for
    the same reason those are kept in step with each other: a bug report's
    `actual` is bound exactly as tightly as any assertion, so a second walk that
    quietly skipped it would report a document as cleaner than it is.
    """
    out = [a.evidence for c in ir.testCases for s in c.steps for a in s.assertions]
    for case in ir.testCases:
        claim = bug_claim(case)
        if claim is not None:
            out.append(claim[2].evidence)
    return out


def _weakly_resolved(ir) -> int:
    """Claims whose literal names no element in the retrieval it cites.

    Graded, never enforced -- `evidence/strength.py` says why at length. A
    non-zero here is not a failure and nothing was rejected for it; it is the
    count of verdicts whose evidence cannot be told apart from a coincidence.
    """
    return sum(1 for e in _graded_evidence(ir) if e.strength is EvidenceStrength.weak)


def _occurrences_max(ir) -> int:
    """How many ways the weakest verdict here had to pass its containment check.

    The number that moves when a document fills up with decoration: 1 when every
    claim had exactly one thing it could be about, 198 on the recording whose
    cart-badge verdict was bound to the literal `1`.
    """
    counts = [e.occurrences for e in _graded_evidence(ir) if e.occurrences is not None]
    return max(counts) if counts else 0


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
    rate: float,
    judgement: JudgeResult | None = None,
    rounds: int = 1,
) -> RunMetrics:
    """Read from the finished trace rather than from each stage.

    The stage-by-stage version had to be edited every time a stage was added,
    and a stage nobody remembered to add was simply invisible in the numbers.
    The trace already has to hold every model call and every investigation
    (SS9.10), so there is exactly one list to be wrong about.

    The convergence rate is gone with the loop it described, and the judge
    columns that replace it are deliberately not a rate. `Converged` was the
    project's clearest example of a rate read without its denominator: it
    measured how much of what the critic said the loop was ALLOWED to act on,
    and answered 1-of-9 because five of the survivors had no repair route by
    design. Matching a finding in round 2 to the one it descended from in round
    1 is a guess, so what is reported is what is still true of the document that
    SHIPPED -- `judgeFails` non-zero means it went out with something a QA lead
    would send back, which is exactly what a rate would hide.
    """
    total = claim_total(ir)
    ungrounded = round(total * (1 - rate))
    model_calls = trace.modelCalls

    return RunMetrics(
        assertionsTotal=total,
        assertionsGrounded=total - ungrounded,
        groundingRate=rate,
        assertionsUngrounded=ungrounded,
        # Kept as two columns even though nothing repairs, because the coverage
        # stage edits `report.results` in place after the gate has run --
        # `suggestions_quarantined` skips on the first pass and does not on the
        # second, which would move the number for a reason that has nothing to
        # do with the document.
        validatorFirstPassRate=_pass_rate(first_report),
        validatorFinalPassRate=_pass_rate(
            report,
            restrict_to={
                r.validator for r in first_report.results if r.status != ValidatorStatus.skip
            },
        ),
        # Every retrieval the run actually made, read from the log rather than
        # summed over investigations. Summing investigations undercounts by
        # exactly the calls no investigation wrapped.
        toolCallsTotal=len(trace.toolCalls),
        toolCallsPerStep=_calls_per_step(ir, trace.toolCalls),
        # About the document that SHIPPED, never a total across rounds. See the
        # docstring: what was "resolved" between two rounds is not knowable.
        judgeFindings=len(judgement.findings) if judgement else 0,
        judgeFails=len(judgement.fails) if judgement else 0,
        # How much the verdicts that shipped are actually worth. Every rate
        # above is vacuously 1.0 when a configuration abstains and none of them
        # can tell a document of real verdicts from a document of decoration;
        # these two can. Graded at bind time, never acted on.
        assertionsWeaklyResolved=_weakly_resolved(ir),
        evidenceOccurrencesMax=_occurrences_max(ir),
        revisionRounds=rounds,
        repairAttempts=len(trace.repairAttempts),
        promptTokensTotal=sum(m.promptTokens or 0 for m in model_calls),
        completionTokensTotal=sum(m.completionTokens or 0 for m in model_calls),
        uncachedModelCalls=len([m for m in model_calls if not m.cached]),
        durationMs=sum(m.latencyMs or 0 for m in model_calls),
    )


__all__ = [
    "PipelineOptions",
    "PipelineResult",
    "run_pipeline",
]
