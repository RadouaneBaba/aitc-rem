"""Bug report mode (SS14).

    "The same recording, a different artifact. Test cases are future-facing and
     reusable; bug reports are historical and evidentiary."

Two halves with deliberately different natures.

**Detection is code.** SS14.1 gives a weighted signal table, and it is
implemented the way the segmenter is implemented -- deterministically -- for the
same reason: the same recording producing a bug report on Tuesday and a test
case on Wednesday is worse than either answer.

**Description is agentic**, because `actual` has to say what went wrong in a
sentence, and SS14.2 binds it exactly as tightly as any assertion: it must quote
something the agent retrieved. There is no weaker path for it. If anything, the
binding matters more here -- `actual` is the one sentence a developer will read
before deciding whether to reproduce.

The report is produced ALONGSIDE the test case, never instead of it (SS14.1).
The tester chooses at review time, and the session is worth both readings: the
steps that reached the failure are a test case whether or not the failure is a
bug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm.client import ModelClient
from server.models import (
    BugDetail,
    BugEnvironment,
    Evidence,
    IRDocument,
    ModelCall,
    PipelineStage,
    Recording,
    StepInvestigation,
    TestCaseIR,
)
from server.pipeline.investigate import investigate

BUG_BUDGET = 4

#: SS14.1's weights, as numbers. The thresholds matter more than the exact
#: values, and one relationship is load-bearing -- see `THRESHOLD`.
DECISIVE = 100
STRONG = 50
MEDIUM = 15
WEAK = 5

#: Above this, a bug report is offered.
#:
#: Set so that **medium signals alone never reach it, at any quantity**. Four of
#: the five recordings this project tests against contain a 4xx on a
#: state-mutating request, and in every one of them that 4xx IS the thing the
#: test is about -- "orders over EUR500 require approval" is the objective, not
#: a defect. A threshold two mediums could clear would turn `checkout`,
#: `twoflows`, `wander` and `narrated` into bug reports, which is a louder and
#: more damaging failure than detecting nothing at all.
#:
#: So it takes the tester's own marker, an HTTP 5xx, or an uncaught exception.
#: The medium and weak signals exist to be reported as corroboration once one of
#: those has fired, not to fire on their own.
THRESHOLD = STRONG

#: SS14.1's "role=alert with error vocabulary". Vocabulary rather than the role
#: alone, because a `role="alert"` is how a well-built application announces
#: success too -- "Order confirmed" lives in one on the demo app's own
#: confirmation page.
ERROR_WORDS = re.compile(
    r"\b(error|failed|failure|unable|cannot|could not|invalid|denied|"
    r"went wrong|try again|unexpected|problem)\b",
    re.IGNORECASE,
)

#: A request that changed something. A failed GET is usually a missing
#: dashboard widget; a failed POST is usually a lost transaction.
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class Signal:
    kind: str
    weight: int
    detail: str
    event_id: str | None = None


@dataclass
class BugSignals:
    """What the recording says about whether something went wrong, and why."""

    signals: list[Signal] = field(default_factory=list)
    failure_event_id: str | None = None

    @property
    def score(self) -> int:
        return sum(s.weight for s in self.signals)

    @property
    def detected(self) -> bool:
        return self.score >= THRESHOLD

    @property
    def summary(self) -> str:
        return "; ".join(f"{s.kind} ({s.weight}): {s.detail}" for s in self.signals)

    def to_artifact(self) -> dict:
        return {
            "stage": "bug",
            "score": self.score,
            "threshold": THRESHOLD,
            "detected": self.detected,
            "failureEventId": self.failure_event_id,
            "signals": [
                {"kind": s.kind, "weight": s.weight, "detail": s.detail, "eventId": s.event_id}
                for s in self.signals
            ],
        }


def detect(recording: Recording) -> BugSignals:
    """SS14.1's table, applied to one recording.

    Every signal that fired is recorded, including the ones that could never
    have reached the threshold on their own. A tester asking "why does it think
    this is a bug" -- or "why does it NOT" -- gets the arithmetic rather than a
    verdict.
    """
    out = BugSignals()
    app = _app_hosts(recording)
    seen_exceptions: set[str] = set()

    for annotation in recording.annotations or []:
        if annotation.kind == "bug_marker":
            out.signals.append(
                Signal(
                    "bug_marker",
                    DECISIVE,
                    annotation.text or "the tester marked this as a bug",
                    annotation.eventId,
                )
            )

    for event in recording.events:
        for entry in event.console or []:
            if not entry.uncaught:
                continue

            # Whose JavaScript threw this? On a commercial site the answer is
            # almost always "not the application's": ad tags, consent managers
            # and analytics throw constantly and nobody who works on the site
            # can do anything about it. The first bug report this tool ever
            # produced on a real recording said `Uncaught [object Object]` from
            # a third-party script on a shop's home page -- ninety minutes of a
            # developer's time to find nothing, and the tool is dead in that
            # org afterwards.
            #
            # One false report costs more trust than fifty good test cases
            # earn, so an exception with no evidence it came from the
            # application is corroboration, not a trigger.
            key = " ".join((entry.text or "").split())[:160]
            strong = _first_party_stack(entry.stack, app) and _informative(key)
            if key in seen_exceptions:
                # The same exception on every event is one defect, and counting
                # it thirty times makes a single noisy console look like a
                # catastrophe.
                continue
            seen_exceptions.add(key)
            out.signals.append(
                Signal(
                    "uncaught_exception" if strong else "opaque_exception",
                    STRONG if strong else WEAK,
                    key,
                    event.id,
                )
            )

        for call in event.network or []:
            status = call.status or 0
            if status >= 500:
                # Same reasoning, and it matters more here: a 500 from an
                # analytics collector says nothing about the application under
                # test, and it is the single loudest signal in the table.
                strength = STRONG if _host(call.url) in app else WEAK
                out.signals.append(
                    Signal(
                        "http_5xx" if strength == STRONG else "third_party_5xx",
                        strength,
                        f"{call.method} {call.url} -> {status}",
                        event.id,
                    )
                )
            elif 400 <= status < 500 and (call.method or "").upper() in MUTATING:
                out.signals.append(
                    Signal(
                        "http_4xx_on_mutation",
                        MEDIUM,
                        f"{call.method} {call.url} -> {status}",
                        event.id,
                    )
                )

        for node in _alerts(event):
            if ERROR_WORDS.search(node):
                out.signals.append(Signal("error_alert", MEDIUM, node[:160], event.id))

    out.signals.extend(_repeats(recording))
    out.failure_event_id = _failure_event(out, recording)
    return out


def _app_hosts(recording: Recording) -> set[str]:
    """The hosts the application under test is served from.

    Taken from the pages the tester was actually on rather than from a config
    entry, because the recorder is black-box (SS6.1) and must not need to be
    told what it is recording. A session that stays on one site yields one
    host; one that legitimately spans a checkout hand-off yields both.
    """
    hosts = {_host(recording.metadata.startUrl)} if recording.metadata.startUrl else set()
    for event in recording.events:
        hosts.add(_host(event.url))
    return {h for h in hosts if h}


#: An exception message that says nothing. Throwing a non-Error gives
#: `[object Object]`, which is what the first bug report this tool ever wrote
#: on a real recording was grounded in.
OPAQUE = re.compile(r"^\s*(uncaught\s*)?(\[object \w+\]|error|exception)?\s*:?\s*$", re.IGNORECASE)


def _informative(text: str) -> bool:
    """Does this exception tell a developer anything at all?

    A bug report's `actual` is the one sentence somebody reads before deciding
    whether to spend an afternoon reproducing something. "Uncaught [object
    Object]" is not a defect description; it is the absence of one, and it is
    what comes out when code throws a non-Error -- which third-party scripts do
    constantly and which carries no stack either.

    Separate from the first-party test on purpose. Even the application's own
    code throwing an opaque object gives a developer nothing to go on, so this
    holds whoever threw it. The signal is still recorded, at WEAK, so "why is
    this not a bug" has an answer.
    """
    return not OPAQUE.match(text)


def _first_party_stack(stack: str | None, app: set[str]) -> bool:
    """Did this exception come from the application's own code?

    A stack naming no host at all is treated as first-party. Browsers omit the
    source for a same-origin inline script and for a cross-origin script the
    page did not opt into reporting, and refusing to report a real defect
    because the browser was terse would be the wrong failure -- the threshold
    exists to stop obvious third-party noise, not to require proof of guilt.
    """
    if not stack:
        return True
    # The authority is captured directly rather than sliced off a matched URL.
    # A stack frame ends in `:line:column`, so a pattern that stops at the
    # first colon in order to avoid those also stops before the PORT --
    # `http://localhost:5173/...` came back as `localhost`, which matches no
    # app host and made the demo app's own exception look third-party.
    hosts = {h.lower() for h in re.findall(r"https?://([^/\s)]+)", stack)}
    hosts.discard("")
    if not hosts:
        return True
    return bool(hosts & app)


def _host(url: str | None) -> str:
    if not url or "://" not in url:
        return ""
    return url.split("://", 1)[1].split("/", 1)[0].lower()


def describe(
    store: EvidenceStore,
    runner: ToolRunner,
    model: ModelClient,
    recording: Recording,
    case: TestCaseIR,
    signals: BugSignals,
    *,
    model_name: str,
    failure_step_id: str,
    budget: int = BUG_BUDGET,
    tools_enabled: bool = True,
    temperature: float = 0.0,
    config: ProjectConfig | None = None,
) -> tuple[BugDetail | None, StepInvestigation | None, list[ModelCall]]:
    """Write `expected` and `actual`, and bind `actual` to a retrieval (SS14.2).

    Returns `None` when the model cannot cite what it claims. That is the
    correct outcome and not a degradation: a bug report whose `actual` is
    unsupported is precisely the artifact SS3.2 exists to prevent, and a
    developer sent to reproduce something the tool invented has lost more time
    than the tool saved.
    """
    config = config or ProjectConfig()
    enquiry = investigate(
        runner,
        model,
        system_prompt=system_prompt(config),
        user_prompt=_prompt(case, signals, failure_step_id),
        model_name=model_name,
        stage=PipelineStage.assert_,
        label=f"bug_{case.id}",
        budget=budget if tools_enabled else 0,
        tools_enabled=tools_enabled,
        temperature=temperature,
        step_id=failure_step_id,
    )
    enquiry.finish()
    investigation = enquiry.record(
        investigation_id=f"inv_bug_{case.id}",
        stage=PipelineStage.assert_,
        budget=budget,
        step_id=failure_step_id,
    )
    answer = enquiry.answer

    expected = str(answer.get("expected") or "").strip()
    actual = str(answer.get("actual") or "").strip()
    literal = str(answer.get("literal") or "")
    call_id = str(answer.get("toolCallId") or "").strip()
    event_id = str(answer.get("eventId") or "").strip()

    if not (expected and actual and literal and call_id and event_id):
        enquiry.narrative.append(
            "no bug report written: `actual` must quote a retrieval (SS14.2) and the "
            "answer did not carry one"
        )
        return None, investigation, enquiry.model_calls

    detail = BugDetail(
        failureStepId=failure_step_id,
        expected=expected,
        actual=actual,
        actualEvidence=Evidence(
            literal=literal,
            toolCallId=call_id,
            eventId=event_id,
            kind=str(answer.get("kind") or "console"),
        ),
        consoleErrorIds=[s.event_id for s in signals.signals if s.kind == "uncaught_exception"],
        failedRequestIds=[
            s.event_id for s in signals.signals if s.kind in {"http_5xx", "http_4xx_on_mutation"}
        ],
        environment=_environment(recording, case),
    )
    return detail, investigation, enquiry.model_calls


SYSTEM_PROMPT = """\
You are writing the two sentences at the centre of a bug report: what should
have happened, and what did.

The tester recorded a session, something went wrong in it, and the steps that
led there are already written. Your job is only the expected/actual pair.

`expected` -- what should have happened at this step. Take it from what the
tester said they were checking, from anything they said out loud or annotated,
or failing those from what the flow was plainly trying to do. It is allowed to
be a judgement; say it plainly.

`actual` -- what DID happen. This one is not a judgement, and it is bound
exactly as tightly as any expected result in this system: you must quote
something you retrieved.

  * `literal` must appear VERBATIM in a tool response you received in THIS
    conversation. Copy it character for character. Not paraphrased, not
    reformatted, not with the quotes changed.
  * `toolCallId` must be the id that response arrived with. It is inside the
    tool result, in the `toolCallId` field. Do not invent one and do not guess
    at its shape.
  * `eventId` must be the event the literal was found at.

Retrieve first. `get_console` for an exception, `get_network` for a failed
request, `get_snapshot` for what the page said. Then quote what came back.

If you cannot find anything that says what went wrong, say so by returning no
`literal` at all. A bug report with an invented `actual` sends a developer to
reproduce something that never happened, and costs more than writing nothing.

Call at most ONE tool per turn.

When you call tools, put a JSON object in your message text first:
    {"uncertainties": ["what the server actually returned"]}

When you are ready to answer, call no tools and reply with ONLY this JSON:
{
  "expected": "the order is placed and a confirmation reference is shown",
  "actual": "the server returned a 500 and no order was created",
  "literal": "Internal server error",
  "toolCallId": "tc_0007",
  "eventId": "evt_0009",
  "kind": "network"
}

`kind` is one of: semantic_node, url, network, console, narration, annotation,
a11y_node."""


def system_prompt(config: ProjectConfig) -> str:
    return SYSTEM_PROMPT


# --------------------------------------------------------------------------


def _alerts(event) -> list[str]:
    """Text of any live-region node the recorder captured for this event."""
    out: list[str] = []
    for snapshot in (event.after, event.transient):
        for node in (snapshot.liveRegions or []) if snapshot else []:
            if node.name:
                out.append(node.name)
    return out


def _repeats(recording: Recording) -> list[Signal]:
    """SS14.1's weakest signal: the tester did the same thing twice.

    Retry behaviour is evidence of frustration and nothing more, which is
    exactly why it is weighted so that it can never decide anything.
    """
    seen: dict[tuple[str, str], int] = {}
    for event in recording.events:
        key = (event.target.role or "", event.target.name or "")
        if not key[1]:
            continue
        seen[key] = seen.get(key, 0) + 1
    return [
        Signal("repeated_action", WEAK, f"{role} {name!r} used {count} times")
        for (role, name), count in seen.items()
        if count >= 3
    ]


def _failure_event(signals: BugSignals, recording: Recording) -> str | None:
    """Where the failure happened, preferring what the tester pointed at.

    A bug marker is decisive about WHETHER, and it is also the best evidence
    about WHERE -- the tester pressed the key at the moment they saw it. Falling
    back to the strongest automatic signal covers the session where nobody
    pressed anything.
    """
    marker = next((s for s in signals.signals if s.kind == "bug_marker"), None)
    if marker is not None and marker.event_id:
        return marker.event_id
    ranked = sorted(
        (s for s in signals.signals if s.event_id), key=lambda s: -s.weight
    )
    if ranked:
        return ranked[0].event_id
    # A marker pressed with no event attached still means "here", and "here" is
    # the last thing the tester did.
    return recording.events[-1].id if marker is not None and recording.events else None


def _environment(recording: Recording, case: TestCaseIR) -> BugEnvironment:
    metadata = recording.metadata
    viewport = metadata.viewport
    return BugEnvironment(
        browser=metadata.browser or "unknown",
        viewport=f"{viewport.w}x{viewport.h}" if viewport else "unknown",
        url=case.metadata.startUrl if case.metadata else (metadata.startUrl or ""),
    )


def _prompt(case: TestCaseIR, signals: BugSignals, failure_step_id: str) -> str:
    lines: list[str] = []
    if case.objective:
        lines.append(f"What the tester said they were checking: {case.objective}")
        lines.append("")
    lines.append("What the tester did, in order:")
    for step in case.steps:
        mark = "   <- something went wrong here" if step.id == failure_step_id else ""
        lines.append(f"  {step.id}  {step.text}{mark}")
        lines.append(f"           events {', '.join(step.eventIds)}")
    lines.append("")
    lines.append("Why this session looks like a bug rather than a passing test:")
    for signal in signals.signals:
        where = f" at {signal.event_id}" if signal.event_id else ""
        lines.append(f"  - {signal.kind}{where}: {signal.detail}")
    lines.append("")
    lines.append(
        "Those are the detector's reasons, not evidence you may cite. Retrieve what you "
        "are going to quote."
    )
    return "\n".join(lines)


def repro_steps(case: TestCaseIR, failure_event_id: str | None) -> tuple[list, str | None]:
    """The steps up to and including the failure (SS14.2).

    Everything after it is the tester recovering, navigating away, or trying
    again -- none of which is part of reproducing the problem.
    """
    if failure_event_id is None:
        return list(case.steps), case.steps[-1].id if case.steps else None
    out = []
    for step in case.steps:
        out.append(step)
        if failure_event_id in step.eventIds:
            return out, step.id
    return list(case.steps), case.steps[-1].id if case.steps else None


def bug_case(
    ir: IRDocument, case: TestCaseIR, steps: list, detail: BugDetail
) -> TestCaseIR:
    """A second test case, `kind='bug_report'`, alongside the first (SS14.1).

    Its steps are copies with their own ids, so a reviewer editing the test case
    does not silently rewrite the historical record beside it -- and the other
    way round. `event_coverage` unions into a set, so covering the same events
    twice is safe.
    """
    copied = []
    for step in steps:
        clone = step.model_copy(deep=True)
        clone.id = f"bug_{step.id}"
        copied.append(clone)
        if step.id == detail.failureStepId:
            detail.failureStepId = clone.id

    out = case.model_copy(deep=True)
    out.id = f"{case.id}_bug"
    out.kind = "bug_report"
    out.title = f"{case.title} -- fails"
    out.steps = copied
    out.suggestions = []
    out.omitted = []
    out.bug = detail
    return out


__all__ = [
    "BUG_BUDGET",
    "THRESHOLD",
    "BugSignals",
    "Signal",
    "bug_case",
    "describe",
    "detect",
    "repro_steps",
    "system_prompt",
]
