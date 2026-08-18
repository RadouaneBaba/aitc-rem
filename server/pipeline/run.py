"""The pipeline skeleton (SS9.1).

    "A fixed deterministic skeleton with agentic stages. Each stage reads a
     file and writes a file, so when output is wrong you open the intermediate
     artifact and see exactly which stage lied."

Phase 1 wires the spine: segment (code) -> name (agentic) -> validate (code)
-> render. Decomposition, assertion ranking, the step library, the critic and
the repair loop slot in later without changing this shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    AblationConfig,
    AgentTrace,
    IRDocument,
    PipelineStage,
    Recording,
    RunConfig,
    RunMetrics,
    StageRecord,
    StageStatus,
    Step,
    TestCaseIR,
    TestCaseMetadata,
    TruncationPolicy,
    ValidatorStatus,
    Warning,
)
from server.pipeline.name import DEFAULT_BUDGET, NamingResult, name_segments
from server.pipeline.segment import segment_recording
from server.pipeline.validators import ValidationContext, ValidationReport, grounding_rate, validate
from server.renderers.gherkin import render_document
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
    #: Pre-declared for A0, whose whole-context prompt will not fit a long
    #: recording. Silent truncation would make the ablation measure truncation
    #: rather than architecture.
    a0_token_budget: int = 120_000

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
    artifacts: dict[str, Path] = field(default_factory=dict)


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

    # -- 1. segment (deterministic) ---------------------------------------
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
    runner = ToolRunner(store=store, storage=storage, run=run, stage=PipelineStage.name)

    # -- 2. name (agentic) -------------------------------------------------
    t0 = time.time()
    naming = name_segments(
        store,
        runner,
        model,
        model_name=options.model_name,
        budget=options.budget,
        tools_enabled=options.tools_enabled,
        temperature=options.temperature,
    )
    ir = _assemble(recording, run_id, naming)
    path = storage.save_artifact(run, "ir", ir)
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

    # -- 3. render ---------------------------------------------------------
    t0 = time.time()
    rendered = render_document(ir)
    for case_id, text in rendered.items():
        (run.root / f"{case_id}.feature").write_text(text, encoding="utf-8")
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

    # -- 4. validate (deterministic gate) ----------------------------------
    t0 = time.time()
    trace = _trace(recording, run_id, options, runner, naming)
    ctx = ValidationContext(
        recording=recording,
        ir=ir,
        trace=trace,
        storage=storage,
        run=run,
        segments=segments,
        rendered=rendered,
    )
    report = validate(ctx)
    trace.validatorResults = report.results
    rate = grounding_rate(ctx, report)
    trace.metrics = _metrics(ir, naming, report, rate, time.perf_counter() - started)
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
        for case_id in rendered:
            (run.root / f"{case_id}.feature").unlink(missing_ok=True)
        rendered = {}

    return PipelineResult(
        recording=recording,
        run=run,
        ir=ir,
        trace=trace,
        report=report,
        rendered=rendered,
        naming=naming,
        grounding_rate=rate,
        duration_ms=(time.perf_counter() - started) * 1000,
        artifacts={
            "segments": run.artifact("segments"),
            "ir": run.artifact("ir"),
            "trace": trace_path,
        },
    )


# --------------------------------------------------------------------------


def _assemble(recording: Recording, run_id: str, naming: NamingResult) -> IRDocument:
    """One test case in Phase 1. Decomposition into N is SS9.3, Phase 2."""
    steps = [
        Step(
            id=named.step_id,
            keyword=named.keyword,
            text=named.text,
            eventIds=named.event_ids,
            investigationRef=named.investigation.id,
            assertions=named.assertions,
            confidence=named.confidence,
            fidelity=_flags(recording, named.event_ids),
            **({"escalation": named.escalation} if named.escalation else {}),
            **({"libraryRef": named.library_ref} if named.library_ref else {}),
        )
        for named in naming.steps
    ]

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

    case = TestCaseIR(
        id=f"tc_{recording.id}",
        recordingId=recording.id,
        runId=run_id,
        kind="test_case",
        title=recording.objective or f"Recorded session {recording.id}",
        description=recording.objective or "Generated from a browser recording.",
        preconditions=[],
        tags=[],
        steps=steps,
        parameters=[
            {"name": p.name, "placeholder": p.placeholder, "category": p.category.value}
            for p in recording.parameters
        ],
        omitted=[],
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

    return IRDocument(
        schemaVersion="1.0",
        recordingId=recording.id,
        runId=run_id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        testCases=[case],
    )


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
) -> AgentTrace:
    config = RunConfig(
        ablation=options.ablation,
        toolsEnabled=options.tools_enabled,
        criticEnabled=options.critic_enabled,
        repairEnabled=options.repair_enabled,
        defaultInvestigationBudget=options.budget,
        fallbackEnabled=options.fallback_enabled,
        cassetteMode=options.cassette_mode,
        models={"name": {"provider": "configured", "model": options.model_name}},
    )
    if options.ablation == AblationConfig.A0:
        config.a0Truncation = TruncationPolicy(
            strategy="head_tail", tokenBudget=options.a0_token_budget
        )

    return AgentTrace(
        schemaVersion="1.0",
        runId=run_id,
        recordingId=recording.id,
        projectId=recording.projectId,
        ownerId=recording.ownerId,
        createdAt=datetime.now(UTC),
        config=config,
        toolCalls=runner.calls,
        modelCalls=naming.model_calls,
        investigations=naming.investigations,
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=[],
    )


def _metrics(
    ir: IRDocument,
    naming: NamingResult,
    report: ValidationReport,
    rate: float,
    elapsed: float,
) -> RunMetrics:
    total = sum(len(s.assertions) for c in ir.testCases for s in c.steps)
    ungrounded = round(total * (1 - rate))
    checks = [r for r in report.results if r.status != ValidatorStatus.skip]
    first_pass = (
        len([r for r in checks if r.status == ValidatorStatus.pass_]) / len(checks)
        if checks
        else 1.0
    )

    return RunMetrics(
        assertionsTotal=total,
        assertionsGrounded=total - ungrounded,
        groundingRate=rate,
        assertionsUngrounded=ungrounded,
        validatorFirstPassRate=first_pass,
        toolCallsTotal=sum(len(s.investigation.toolCallIds) for s in naming.steps),
        toolCallsPerStep=naming.tool_calls_per_step(),
        promptTokensTotal=sum(m.promptTokens or 0 for m in naming.model_calls),
        completionTokensTotal=sum(m.completionTokens or 0 for m in naming.model_calls),
        uncachedModelCalls=len([m for m in naming.model_calls if not m.cached]),
        durationMs=elapsed * 1000,
    )
