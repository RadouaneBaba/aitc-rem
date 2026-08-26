"""Builders for valid pipeline artifacts.

Hand-built fixtures are how the validators get tested without a model in the
loop (plan M7): a real model will not fabricate a broken assertion on command,
so the broken cases have to be constructed here.

Every builder returns something that validates against the schema unless a
caller deliberately breaks it.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.models import (
    Assertion,
    CapturedEvent,
    ConsoleEntry,
    CoverageSuggestion,
    DiffNode,
    EventTarget,
    Evidence,
    IRDocument,
    NetworkCall,
    OmittedSegment,
    Parameter,
    Precondition,
    Recording,
    RecordingMetadata,
    SelectorHint,
    SelectorSet,
    SemanticNode,
    SemanticSnapshot,
    SnapshotDiff,
    Step,
    TestCaseIR,
    TestCaseMetadata,
    TesterAnnotation,
    UrlChange,
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
    Viewport,
)

NOW = datetime(2026, 8, 17, 14, 3, 22, tzinfo=UTC)


def node(ref: str, role: str, name: str, **kw: Any) -> SemanticNode:
    return SemanticNode(ref=ref, role=role, name=name, **kw)


def snapshot(
    *,
    url: str = "https://demo.local/checkout",
    title: str = "Checkout",
    at: float = 0.0,
    root: SemanticNode | None = None,
    live: list[SemanticNode] | None = None,
) -> SemanticSnapshot:
    return SemanticSnapshot(
        capturedAt=at,
        url=url,
        title=title,
        scope="scoped",
        root=root or node("0", "main", "Checkout"),
        liveRegions=live or [],
    )


def target(
    role: str = "button",
    name: str = "Submit order",
    css: str = "button.submit",
    **kw: Any,
) -> EventTarget:
    return EventTarget(role=role, name=name, selectors=SelectorSet(css=css), frame=[], **kw)


def event(
    ident: str = "evt_001",
    seq: int = 0,
    *,
    etype: str = "click",
    at: float = 0.0,
    url: str = "https://demo.local/checkout",
    tgt: EventTarget | None = None,
    before: SemanticSnapshot | None = None,
    after: SemanticSnapshot | None = None,
    diff: SnapshotDiff | None = None,
    network: list[NetworkCall] | None = None,
    console: list[ConsoleEntry] | None = None,
    fidelity: list[str] | None = None,
    **kw: Any,
) -> CapturedEvent:
    return CapturedEvent(
        id=ident,
        seq=seq,
        timestamp=at,
        type=etype,
        url=url,
        target=tgt or target(),
        before=before or snapshot(url=url, at=at),
        after=after or snapshot(url=url, at=at + 100),
        diff=diff or SnapshotDiff(added=[], removed=[], changed=[]),
        network=network or [],
        console=console or [],
        fidelity=fidelity or [],
        **kw,
    )


def confirmation_diff() -> SnapshotDiff:
    """The shape of a successful outcome: a live region appears."""
    return SnapshotDiff(
        added=[DiffNode(ref="0.4", role="alert", name="Order confirmed")],
        removed=[],
        changed=[],
    )


def network_call(
    ident: str = "net_001",
    method: str = "POST",
    url: str = "https://demo.local/api/orders",
    status: int = 201,
    at: float = 10.0,
) -> NetworkCall:
    return NetworkCall(
        id=ident, method=method, url=url, status=status, startTime=at, initiator="fetch"
    )


def recording(
    ident: str = "rec_test01",
    *,
    events: list[CapturedEvent] | None = None,
    objective: str | None = None,
    origins: list[str] | None = None,
    annotations: list[TesterAnnotation] | None = None,
    narration: list[Any] | None = None,
    **kw: Any,
) -> Recording:
    evts = events if events is not None else [event()]
    return Recording(
        schemaVersion="1.0",
        id=ident,
        projectId="proj_test",
        ownerId="owner_test",
        createdAt=NOW,
        objective=objective,
        metadata=RecordingMetadata(
            capturedAt=NOW,
            durationMs=evts[-1].timestamp if evts else 0.0,
            browser="Chrome/140",
            viewport=Viewport(w=1280, h=800),
            startUrl=evts[0].url if evts else "https://demo.local/",
            origins=origins or ["https://demo.local"],
        ),
        events=evts,
        narration=narration or [],
        annotations=annotations or [],
        parameters=[],
        **kw,
    )


def evidence(
    literal: str = "Order confirmed",
    tool_call_id: str = "tc_0447",
    event_id: str = "evt_001",
    kind: str = "semantic_node",
) -> Evidence:
    return Evidence(literal=literal, toolCallId=tool_call_id, eventId=event_id, kind=kind)


def assertion(
    ident: str = "asrt_001",
    text: str = "the confirmation banner appears",
    *,
    provenance: str = "inferred",
    ev: Evidence | None = None,
    accepted: bool = True,
) -> Assertion:
    return Assertion(
        id=ident,
        text=text,
        provenance=provenance,
        evidence=ev or evidence(),
        accepted=accepted,
    )


def step(
    ident: str = "step_001",
    text: str = "the tester submits the order form",
    *,
    keyword: str = "When",
    role: str | None = None,
    event_ids: list[str] | None = None,
    assertions: list[Assertion] | None = None,
    confidence: str = "high",
    **kw: Any,
) -> Step:
    if role is not None:
        kw["role"] = role
    return Step(
        id=ident,
        keyword=keyword,
        text=text,
        eventIds=event_ids or ["evt_001"],
        investigationRef="inv_001",
        assertions=assertions if assertions is not None else [assertion()],
        confidence=confidence,
        fidelity=[],
        **kw,
    )


def test_case(
    ident: str = "tc_case_001",
    *,
    steps: list[Step] | None = None,
    recording_id: str = "rec_test01",
    run_id: str = "run_test01",
    preconditions: list[Precondition] | None = None,
    parameters: list[Parameter] | None = None,
    omitted: list[OmittedSegment] | None = None,
    tags: list[str] | None = None,
    title: str = "Order checkout",
    description: str = "Recorded checkout flow.",
    scenarioName: str = "Submitting a valid order shows the confirmation",
    kind: str = "test_case",
    **kw: Any,
) -> TestCaseIR:
    return TestCaseIR(
        id=ident,
        recordingId=recording_id,
        runId=run_id,
        kind=kind,
        title=title,
        description=description,
        scenarioName=scenarioName,
        preconditions=preconditions or [],
        tags=tags or [],
        steps=steps if steps is not None else [step()],
        parameters=parameters or [],
        omitted=omitted or [],
        metadata=TestCaseMetadata(
            capturedAt=NOW,
            durationMs=1000.0,
            browser="Chrome/140",
            viewport={"w": 1280, "h": 800},
            startUrl="https://demo.local/checkout",
            projectId="proj_test",
            ownerId="owner_test",
        ),
        warnings=[],
        **kw,
    )


def ir_document(
    *,
    test_cases: list[TestCaseIR] | None = None,
    recording_id: str = "rec_test01",
    run_id: str = "run_test01",
) -> IRDocument:
    return IRDocument(
        schemaVersion="1.0",
        recordingId=recording_id,
        runId=run_id,
        projectId="proj_test",
        ownerId="owner_test",
        createdAt=NOW,
        testCases=test_cases if test_cases is not None else [test_case()],
    )


def url_change(
    frm: str = "https://demo.local/cart", to: str = "https://demo.local/checkout"
) -> UrlChange:
    return UrlChange(**{"from": frm, "to": to})


def annotation(
    ident: str = "ann_1",
    kind: str = "checkpoint",
    at: float = 0.0,
    text: str | None = None,
    *,
    role: str | None = None,
    name: str | None = None,
    value: str | None = None,
    event_id: str | None = None,
) -> TesterAnnotation:
    """A tester annotation (SS6.7).

    Pass `role`/`name` to build the `assertion` kind's target -- the element the
    tester pointed at and said "this is what I'm verifying".
    """
    target = (
        {
            "target": {
                "role": role or "alert",
                "name": name or "",
                **({"value": value} if value else {}),
                "selectors": {"css": ".marked"},
            }
        }
        if role or name
        else {}
    )
    return TesterAnnotation(
        id=ident,
        kind=kind,
        timestamp=at,
        **({"text": text} if text else {}),
        **({"eventId": event_id} if event_id else {}),
        **target,
    )


def validator_result(
    name: ValidatorName,
    status: ValidatorStatus = ValidatorStatus.fail,
    *,
    reject: bool = False,
    step_id: str | None = None,
    message: str | None = None,
    attempt: int = 1,
) -> ValidatorResult:
    """One row of the gate's verdict, for testing what reads it.

    `reject` rather than an action argument, because the only distinction the
    repair loop cares about is whether the gate asked for a regeneration.
    """
    out = ValidatorResult(
        validator=name,
        status=status,
        action=ValidatorAction.reject if reject else ValidatorAction.none,
        attempt=attempt,
    )
    if step_id:
        out.stepId = step_id
    if message:
        out.message = message
    return out


def validation_report(results: list[ValidatorResult]) -> Any:
    from server.pipeline.validators import ValidationReport

    return ValidationReport(results=results)


def diff_node(ref: str, role: str, name: str) -> DiffNode:
    return DiffNode(ref=ref, role=role, name=name)


def precondition(
    ident: str = "pre_001",
    text: str = "the tester is signed in",
    event_ids: list[str] | None = None,
) -> Precondition:
    return Precondition(id=ident, text=text, eventIds=event_ids or [])


def selector_hint(
    strategy: str = "css", value: str = "button.submit", stability: str = "medium"
) -> SelectorHint:
    return SelectorHint(strategy=strategy, value=value, stability=stability)


def parameter(
    name: str = "user_email_1", placeholder: str = "<<user_email_1>>", category: str = "email"
) -> Parameter:
    return Parameter(name=name, placeholder=placeholder, category=category)


def omitted_segment(
    segment_id: str = "seg_004",
    reason: str = "exploratory",
    count: int = 3,
    summary: str = "browsed the reports page, returned",
    after_step_id: str | None = None,
) -> OmittedSegment:
    seg = OmittedSegment(segmentId=segment_id, reason=reason, eventCount=count, summary=summary)
    if after_step_id:
        seg.afterStepId = after_step_id
    return seg


def coverage_suggestion(
    ident: str = "sug_001",
    text: str = "an invalid-email path is untested",
    category: str = "validation_path",
    rationale: str = "the field has type=email and a validation message exists",
) -> CoverageSuggestion:
    return CoverageSuggestion(id=ident, text=text, rationale=rationale, category=category)


def validation_context(
    *,
    rendered: dict[str, str] | None = None,
    ir_doc: IRDocument | None = None,
    recording_doc: Recording | None = None,
    runs_dir: Path | None = None,
) -> Any:
    """A minimal gate context, for validators that only read the output.

    The gate's shape is fixed by what the strictest validator needs -- the
    recording, the IR, the trace and the run directory. A validator that only
    reads rendered text should not have to assemble all of that by hand to be
    tested, so this builds the uninteresting parts.
    """
    from server.pipeline.validators.base import ValidationContext
    from server.storage.paths import Storage

    root = Path(runs_dir) if runs_dir else Path(tempfile.mkdtemp())
    storage = Storage(recordings_dir=root / "recordings", runs_dir=root / "runs")
    document = ir_doc or ir_document()
    recorded = recording_doc or recording()

    return ValidationContext(
        recording=recorded,
        ir=document,
        trace=agent_trace(),
        storage=storage,
        run=storage.run(recorded.id, "run_test01"),
        rendered=rendered or {},
    )


def agent_trace(**kw: Any) -> Any:
    from server.models import AgentTrace

    return AgentTrace(
        schemaVersion="1.0",
        runId=kw.pop("run_id", "run_test01"),
        recordingId=kw.pop("recording_id", "rec_test01"),
        projectId="proj_test",
        ownerId="owner_test",
        createdAt=NOW,
        config={
            "ablation": "A2",
            "toolsEnabled": True,
            "criticEnabled": False,
            "repairEnabled": False,
        },
        toolCalls=kw.pop("tool_calls", []),
        modelCalls=[],
        investigations=kw.pop("investigations", []),
        stages=[],
        validatorResults=[],
        repairAttempts=[],
        decompositionDecisions=[],
        **kw,
    )
