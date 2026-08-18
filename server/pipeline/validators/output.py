"""Validators over the rendered artifact rather than the IR.

`no_placeholder_leak` is the only one in SS9.7 whose action is `hard_fail`.
Everything else rejects and regenerates; a leaked secret must not be rendered
at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
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
