"""Builders for valid pipeline artifacts.

Hand-built fixtures are how the validators get tested without a model in the
loop (plan M7): a real model will not fabricate a broken assertion on command,
so the broken cases have to be constructed here.

Every builder returns something that validates against the schema unless a
caller deliberately breaks it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from server.models import (
    Assertion,
    CapturedEvent,
    ConsoleEntry,
    DiffNode,
    EventTarget,
    Evidence,
    IRDocument,
    NetworkCall,
    Recording,
    RecordingMetadata,
    SelectorSet,
    SemanticNode,
    SemanticSnapshot,
    SnapshotDiff,
    Step,
    TestCaseIR,
    TestCaseMetadata,
    TesterAnnotation,
    UrlChange,
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
        narration=[],
        annotations=[],
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
    event_ids: list[str] | None = None,
    assertions: list[Assertion] | None = None,
    confidence: str = "high",
    **kw: Any,
) -> Step:
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
    **kw: Any,
) -> TestCaseIR:
    return TestCaseIR(
        id=ident,
        recordingId=recording_id,
        runId=run_id,
        kind="test_case",
        title="Submitting a valid order shows the confirmation",
        description="Recorded checkout flow.",
        preconditions=[],
        tags=[],
        steps=steps if steps is not None else [step()],
        parameters=[],
        omitted=[],
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
) -> TesterAnnotation:
    return TesterAnnotation(id=ident, kind=kind, timestamp=at, **({"text": text} if text else {}))


def diff_node(ref: str, role: str, name: str) -> DiffNode:
    return DiffNode(ref=ref, role=role, name=name)
