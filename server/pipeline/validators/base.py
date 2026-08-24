"""Shared plumbing for the deterministic validation gate (SS9.7).

    "You have ground truth AND a retrieval log, so hallucination is
     mechanically checkable. This is a rare luxury -- use it."

Every validator is a pure function from a `ValidationContext` to a list of
`ValidatorResult`. They need no model, they are cheap, and they catch the
majority of what would otherwise destroy trust.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from server.evidence.store import EvidenceStore
from server.models import (
    AgentTrace,
    IRDocument,
    Recording,
    SegmentsDocument,
    ValidatorAction,
    ValidatorName,
    ValidatorResult,
    ValidatorStatus,
)
from server.storage.paths import RunPaths, Storage


@dataclass
class ValidationContext:
    """Everything the gate is allowed to look at."""

    recording: Recording
    ir: IRDocument
    trace: AgentTrace
    storage: Storage
    run: RunPaths
    segments: SegmentsDocument | None = None
    #: testCaseId -> rendered Gherkin, when the renderer has already run.
    rendered: dict[str, str] = field(default_factory=dict)
    attempt: int = 1
    #: SS12's approved phrasing. Not evidence -- it is what a team agreed to
    #: call things, and no assertion may be grounded in it. `library_verbatim`
    #: is the only validator that reads it, and it rejects rather than skips
    #: when a step claims reuse and this is absent: a claim that cannot be
    #: checked is not admissible.
    library: Any = None
    #: SS6.6 -- below this, a narration segment is kept and shown but cannot
    #: support the `narrated` rank. A number rather than the ProjectConfig,
    #: because the gate has no business knowing the project's voice: narration
    #: is the one LOSSY evidence source here, and how much of it to trust is the
    #: only setting that bears on admissibility.
    narration_min_confidence: float = 0.5

    _store: EvidenceStore | None = field(default=None, init=False, repr=False)

    @property
    def store(self) -> EvidenceStore:
        if self._store is None:
            self._store = EvidenceStore(recording=self.recording, segments=self.segments)
        return self._store

    def tool_call(self, tool_call_id: str):
        for call in self.trace.toolCalls:
            if call.id == tool_call_id:
                return call
        return None


Validator = Callable[[ValidationContext], Iterable[ValidatorResult]]


def result(
    name: ValidatorName,
    status: ValidatorStatus,
    action: ValidatorAction,
    ctx: ValidationContext,
    *,
    message: str | None = None,
    test_case_id: str | None = None,
    step_id: str | None = None,
    assertion_id: str | None = None,
    skip_reason: str | None = None,
) -> ValidatorResult:
    out = ValidatorResult(validator=name, status=status, action=action, attempt=ctx.attempt)
    if message:
        out.message = message
    if test_case_id:
        out.testCaseId = test_case_id
    if step_id:
        out.stepId = step_id
    if assertion_id:
        out.assertionId = assertion_id
    if skip_reason:
        out.skipReason = skip_reason
    return out


def passed(
    name: ValidatorName, ctx: ValidationContext, message: str | None = None
) -> ValidatorResult:
    return result(name, ValidatorStatus.pass_, ValidatorAction.none, ctx, message=message)


def skipped(name: ValidatorName, ctx: ValidationContext, reason: str) -> ValidatorResult:
    """A validator with nothing to check records a skip.

    Never silently omitted: "this had no subject" and "this was never run" have
    to stay distinguishable, or the gate's coverage is unknowable.
    """
    return result(name, ValidatorStatus.skip, ValidatorAction.none, ctx, skip_reason=reason)


def strings_in(value: Any) -> Iterable[str]:
    """Every string anywhere inside a decoded JSON value.

    Used instead of a substring search over the serialized form: a raw
    `literal in json.dumps(response)` can match across key boundaries and
    punctuation, which would license an assertion no retrieval actually
    supports.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings_in(item)


def contains_literal(value: Any, literal: str) -> bool:
    return any(literal in s for s in strings_in(value))
