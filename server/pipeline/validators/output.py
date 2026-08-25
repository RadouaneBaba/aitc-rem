"""Validators over the rendered artifact rather than the IR.

`no_placeholder_leak` is the only one in SS9.7 whose action is `hard_fail`.
Everything else rejects and regenerates; a leaked secret must not be rendered
at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
from server.pipeline.coverage import reads_back_as_step
from server.pipeline.validators.base import ValidationContext, passed, result, skipped, strings_in

#: Redaction happened in the browser (SS7), so anything matching here got into
#: the output some other way: a model invented it, or a rule missed it. Either
#: is a reason not to render.
LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}")),
    # Underscores inside the key itself matter: sk_live_... is the common shape.
    ("api key", re.compile(r"\b(?:sk|pk|api[_-]?key)[_-][A-Za-z0-9_-]{12,}", re.IGNORECASE)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
]

CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

#: A placeholder is the redacted form and must never be reported as a leak.
PLACEHOLDER = re.compile(r"<<[a-z0-9_]+>>", re.IGNORECASE)


def _luhn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19:
        return False
    total, double = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total % 10 == 0


def _scan(text: str) -> list[str]:
    """Everything in `text` that looks like a live secret."""
    stripped = PLACEHOLDER.sub("", text)
    found = [label for label, pattern in LEAK_PATTERNS if pattern.search(stripped)]
    if any(_luhn(m.group()) for m in CARD_CANDIDATE.finditer(stripped)):
        found.append("card number")
    return found


def no_placeholder_leak(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """No unredacted-looking secret anywhere in the IR or the rendered output.

    Hard fail: do not render. SS7 promises that raw secrets never exist in a
    persisted artifact, and a tool that breaks that promise once has broken it
    permanently.
    """
    leaks: list[tuple[str, str]] = []

    for case in ctx.ir.testCases:
        for text in strings_in(case.model_dump(mode="json", exclude_none=True)):
            for label in _scan(text):
                leaks.append((f"test case {case.id}", label))

    for case_id, rendered in ctx.rendered.items():
        for label in _scan(rendered):
            leaks.append((f"rendered output for {case_id}", label))

    if leaks:
        unique = sorted({f"{where}: {what}" for where, what in leaks})
        yield result(
            ValidatorName.no_placeholder_leak,
            ValidatorStatus.fail,
            ValidatorAction.hard_fail,
            ctx,
            message=(
                "output contains something that looks like a live secret, which redaction "
                "should have replaced with a placeholder: " + "; ".join(unique[:6])
            ),
        )
        return

    yield passed(
        ValidatorName.no_placeholder_leak,
        ctx,
        f"no secret-shaped text in {len(ctx.ir.testCases)} test case(s)",
    )


def suggestions_quarantined(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """A coverage suggestion never reaches the grounded output (SS9.8).

    SS9.8 and the decision log both say it in the strongest terms available:
    suggestions "must never contaminate grounded output". Three renderers
    already keep them out by convention. This makes it a gate, because the
    difference matters -- a suggestion is a guess about what a tester might
    check NEXT, and the one thing worse than not offering it is offering it in
    a form a reader mistakes for a step that was verified.

    Also checks `basedOn`. *Unverified is not the same as ungrounded*: a
    suggestion is allowed to be about behaviour nobody exercised, and is not
    allowed to rest on an observation nobody made.
    """
    suggestions = [(c, s) for c in ctx.ir.testCases for s in (c.suggestions or [])]
    if not suggestions:
        yield skipped(
            ValidatorName.suggestions_quarantined, ctx, "no coverage suggestions were proposed"
        )
        return

    # What counts as "an observation somebody made". Events and retrievals are
    # the obvious two. A STEP id is the third and belongs here for the same
    # reason: a step is a group of events this run actually recorded, so a
    # suggestion resting on one rests on something observed -- and the coverage
    # stage is handed the finished test case, where steps are what it can see
    # and events are not. Rejecting a suggestion for citing the thing it was
    # shown would be the gate disagreeing with its own pipeline about what
    # evidence looks like.
    known = (
        {e.id for e in ctx.recording.events}
        | {c.id for c in ctx.trace.toolCalls}
        | {s.id for c in ctx.ir.testCases for s in c.steps}
    )
    offences = 0

    for case, suggestion in suggestions:
        if case.kind == "bug_report":
            offences += 1
            yield result(
                ValidatorName.suggestions_quarantined,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"{case.id} is a bug report and carries a coverage suggestion. A bug "
                    f"report is a historical record of one failure; proposing further "
                    f"testing inside it mixes two different kinds of claim (SS14)."
                ),
                test_case_id=case.id,
            )
            continue

        # The same predicate the coverage stage refuses to emit against. One
        # function, not two, for the reason `supports_narrated` is one function:
        # a gate and the stage it guards disagreeing about what counts is worse
        # than either rule being wrong.
        if reads_back_as_step(suggestion.text, ctx.rendered.get(case.id, "")):
            offences += 1
            yield result(
                ValidatorName.suggestions_quarantined,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"suggestion {suggestion.id!r} reads back as text already in the rendered "
                    f"feature: {suggestion.text!r}. Suggestions are quarantined from the "
                    f"artifact and must not be renderable as steps (SS9.8)."
                ),
                test_case_id=case.id,
            )
            continue

        unknown = [ref for ref in (suggestion.basedOn or []) if ref not in known]
        if unknown:
            offences += 1
            yield result(
                ValidatorName.suggestions_quarantined,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=(
                    f"suggestion {suggestion.id!r} rests on {', '.join(unknown[:4])}, which is "
                    f"neither an event in this recording nor a retrieval in this run. "
                    f"Unverified is not the same as ungrounded."
                ),
                test_case_id=case.id,
            )

    if not offences:
        yield passed(
            ValidatorName.suggestions_quarantined,
            ctx,
            f"{len(suggestions)} suggestion(s) quarantined, none renderable as a step",
        )


def gherkin_parses(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """The rendered feature file must be valid Gherkin.

    Parsed with Cucumber's own parser rather than a regex, because "valid
    Gherkin" means whatever that parser accepts.
    """
    if not ctx.rendered:
        yield skipped(ValidatorName.gherkin_parses, ctx, "nothing has been rendered yet")
        return

    try:
        from gherkin.parser import Parser
    except ImportError:
        yield skipped(
            ValidatorName.gherkin_parses,
            ctx,
            "gherkin-official is not installed; install it to enable this check",
        )
        return

    ok = 0
    for case_id, text in ctx.rendered.items():
        try:
            Parser().parse(text)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - the parser raises its own types
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            yield result(
                ValidatorName.gherkin_parses,
                ValidatorStatus.fail,
                ValidatorAction.reject,
                ctx,
                message=f"rendered feature does not parse: {first}",
                test_case_id=case_id,
            )

    if ok:
        yield passed(ValidatorName.gherkin_parses, ctx, f"{ok} feature file(s) parse")
