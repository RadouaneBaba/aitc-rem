"""Is the feature file worth reading? (SS11.1)

`gherkin_parses` proves the output is Gherkin. It says nothing about whether the
output is a *test case*, and for a long time it did not need to: the file
parsed perfectly while reading

    When the tester enters the username !!
    When the tester enters the password into the password field !!
    When the tester logs in to the application !!

which is a click log with keywords on it. The `.feature` is the artifact a QA
lead judges the whole tool by, so the properties that make it readable are
checked here rather than left to taste.

Phrasing is a warning. Style is not correctness, and a gate that refuses to
emit a grounded test case because a sentence starts with the wrong verb would
be trading the valuable thing for the cheap one.

SHAPE is not phrasing, and two findings here reject. A scenario with five
action/outcome blocks is not a badly written test case; it is several test
cases sharing a heading, and `MAX_BEATS` is the number the drafting prompt is
told to aim at. A `Background:` that asserts is a block that is not a
background. Neither has a row in `VALIDATOR_REPAIR`, so the rejection is
terminal -- stated to the human rather than re-run -- which is what CLAUDE.md
and the drafting prompt have both claimed all along while the code warned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
from server.pipeline.validators.base import ValidationContext, passed, result, skipped

KEYWORDS = ("Given", "When", "Then", "And", "But", "*")


@dataclass(frozen=True)
class StyleFinding:
    """One thing wrong with the rendered file, and whether it is fatal.

    Severity is per FINDING, not per validator run: a file can be rejected for
    its shape and warned about its phrasing in the same pass, and collapsing
    those to one action would either hide the rejection or inflate the warning.
    """

    message: str
    structural: bool = False


#: Verbs that describe a mouse rather than a test. "Submits the order" beats
#: "clicks the blue button" -- a step that names the mechanism goes stale the
#: moment the button moves, and tells the reader nothing about intent.
MECHANICS = re.compile(
    r"\b(clicks?|taps?|presses|pressed|types?|typed|scrolls?|hovers?|drags?|"
    r"double-clicks?|right-clicks?|checks the (?:box|checkbox))\b",
    re.IGNORECASE,
)

#: Traceability that leaked into a sentence. Cucumber matches step text against
#: a step-definition regex, so an id or a review marker glued to the sentence
#: breaks the glue as well as the reading.
LEAKED_TRACE = re.compile(r"(!!|\bevt_\d+\b|\btc_\d{3,}\b|\bstep_\d+\b|\binv_\w+\b)")

QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'|<[a-z0-9_]+>|<<[a-z0-9_]+>>", re.IGNORECASE)

#: Word boundaries matter here: without them "and" matches inside "brand" and
#: "then" inside "strengthen", and every step with a long word becomes a run-on.
CONJUNCTION = re.compile(r"\b(?:and|then)\b", re.IGNORECASE)

#: How a file refers to the person executing the test. `ProjectConfig.voice`
#: sets one and the naming stage honours it, but assertions are written by a
#: different stage and drift: a real run said "the tester" in every step and
#: "the user is redirected" in an expected result. One document, two people.
ACTOR = re.compile(r"\bthe (tester|user|admin|customer|operator)\b", re.IGNORECASE)


def gherkin_style(ctx: ValidationContext) -> Iterable[ValidatorResult]:
    """Warn about anything that makes the feature file read like machine output."""
    if not ctx.rendered:
        yield skipped(ValidatorName.gherkin_style, ctx, "nothing has been rendered yet")
        return

    findings: list[tuple[str, StyleFinding]] = []
    for case_id, text in ctx.rendered.items():
        findings.extend((case_id, finding) for finding in _inspect(text))

    for case_id, finding in findings:
        yield result(
            ValidatorName.gherkin_style,
            ValidatorStatus.fail if finding.structural else ValidatorStatus.warn,
            ValidatorAction.reject if finding.structural else ValidatorAction.warn,
            ctx,
            message=finding.message,
            test_case_id=case_id,
        )

    if not findings:
        yield passed(
            ValidatorName.gherkin_style,
            ctx,
            f"{len(ctx.rendered)} feature file(s) read as test cases",
        )


def _inspect(text: str) -> list[StyleFinding]:
    problems: list[StyleFinding] = []

    def note(message: str, *, structural: bool = False) -> None:
        problems.append(StyleFinding(message, structural=structural))

    steps = _steps(text)

    if not steps:
        return [StyleFinding("the feature file has no steps", structural=True)]

    # 1. A test case with no expected result is a transcript. This is the one
    #    finding that says something about content rather than phrasing, and it
    #    is the most important of them.
    if not any(keyword in {"Then"} for keyword, _ in steps):
        note(
            "no Then step: this describes what the tester did but never what should "
            "be true afterwards, which is a transcript rather than a test case"
        )

    problems.extend(_inspect_scenarios(text))

    # 2. `And` continues a block; it cannot open one, and `Then` before any
    #    action asserts about a state nothing established.
    first_keyword = steps[0][0]
    if first_keyword in {"And", "But"}:
        note(f"the first step opens with {first_keyword!r}, which continues nothing")

    # `And` continues whatever came before it, so resolve it before reasoning
    # about order -- otherwise "Given / And / Then" looks like it has no
    # preceding keyword at all.
    resolved: list[str] = []
    concrete: str | None = None
    for keyword, _ in steps:
        if keyword in {"Given", "When", "Then"}:
            concrete = keyword
        resolved.append(concrete or keyword)

    seen_action = False
    for keyword in resolved:
        if keyword in {"Given", "When"}:
            seen_action = True
        elif keyword == "Then" and not seen_action:
            note("a Then step comes before any Given or When")
            break

    # A `Then` reached without any `When` asserts about the preconditions rather
    # than about anything the test did. `narrative._lay_out` prevents it by
    # promoting an assertion-bearing `Given` to `When` -- if it shows up here,
    # that rule has regressed or someone hand-edited the file.
    if "Then" in resolved and "When" not in resolved[: resolved.index("Then")]:
        note(
            "an expected result is checked before any When step: the scenario asserts "
            "about its own preconditions rather than about the behaviour under test"
        )

    # 3. `Given` states the world before the test begins, so it belongs to the
    #    opening block. After a `Then` it reads as the scenario restarting.
    checked = False
    for index, (keyword, _) in enumerate(steps):
        if keyword == "Then":
            checked = True
        elif keyword == "Given" and checked:
            note(
                f"step {index + 1} opens with Given after an expected result; "
                f"preconditions belong at the top of the scenario"
            )
            break

    previous: str | None = None
    for index, (_keyword, body) in enumerate(steps):
        normalised = _normalise(body)

        # 4. The reader watching the tool stutter.
        if previous is not None and normalised == previous:
            note(f"step {index + 1} repeats the step before it verbatim: {body!r}")
        previous = normalised

        # 5. Mechanics. Quoted values are exempt -- an application may well
        #    have a control named "Click here", and quoting it is correct.
        bare = QUOTED.sub("", body)
        mechanic = MECHANICS.search(bare)
        if mechanic:
            note(
                f"step {index + 1} describes mechanics rather than intent "
                f"({mechanic.group(0)!r}): {body!r}"
            )

        # 6. A step that lists four actions is a segment transcribed rather
        #    than an intent named. It reads badly and it cannot be executed as
        #    a single check, which is what a step is for.
        if _is_run_on(bare):
            note(
                f"step {index + 1} describes several actions at once rather than one "
                f"intent: {body!r}"
            )

        # 7. A step should not end in a full stop -- it is a sentence
        #    fragment whose subject is the keyword. `draft._clean` strips one,
        #    so reaching here means something wrote a step without going
        #    through the drafting stage.
        if body.rstrip().endswith(".") and not body.rstrip().endswith(".."):
            note(
                f"step {index + 1} ends in a full stop; a Gherkin step is a fragment, not a "
                f"sentence: {body!r}"
            )

        # 8. Traceability that belongs in the sidecar.
        leak = LEAKED_TRACE.search(body)
        if leak:
            note(
                f"step {index + 1} carries {leak.group(0)!r} in its text, which breaks "
                f"step-definition matching; traceability belongs in the sidecar"
            )

    # 9. One test case, one person. Checked for self-consistency rather than
    #    against `ProjectConfig.voice`, because a file that calls the same actor
    #    two things is wrong whichever of them the project chose.
    actors = {m.group(1).lower() for m in ACTOR.finditer(" ".join(body for _, body in steps))}
    if len(actors) > 1:
        named = ", ".join(f"the {a}" for a in sorted(actors))
        note(
            f"the scenario refers to the person executing it in more than one way ({named}); "
            f"set voice in config/project.yaml and use it throughout"
        )

    return problems


#: More action blocks than this in one scenario and it is several test cases
#: sharing a heading. Set from the failure it exists to catch: a real recording
#: produced six `When`/`Then` beats -- navigate, set country, pick basket,
#: upgrade size, change quantity, dismiss warning -- with seven expected results
#: about six unrelated things. No QA engineer writes that; they write three
#: steps and one `Then`. Four is generous for one behaviour with one verdict.
MAX_BEATS = 4


#: Verbs that make a clause a claim about the application. Used to tell one
#: expected result from two joined by "and".
CLAIM_VERB = re.compile(
    r"\b(is|are|was|were|shows?|showed|displays?|displayed|appears?|appeared|"
    r"contains?|contained|becomes?|became|indicates?|indicated|states?|stated|"
    r"reads?|updates?|updated|remains?|reflects?)\b",
    re.IGNORECASE,
)


def _is_double_claim(body: str) -> bool:
    """Does this expected result check two independent things at once?

    "the checkout page updates to reflect the Express delivery fee AND the
    payment method is accepted" is two assertions on one line, and the cost is
    concrete: when it fails, nobody can say which half failed. A `Then` is the
    unit that passes or fails, so it has to be one claim.

    `_is_run_on` does not catch this -- it needs three conjunctions or two
    commas, and this has one "and". The test here is different because the
    thing being detected is different: two clauses that each make a claim.
    """
    parts = re.split(r"\band\b", body, flags=re.IGNORECASE)
    if len(parts) < 2:
        return False
    return sum(1 for part in parts if CLAIM_VERB.search(part)) >= 2


def _restates(body: str, name: str) -> bool:
    """Is this expected result just the scenario's own heading again?

    Seen on `twoflows`: a scenario called *Order requires approval* closing on
    `Then Order requires approval`. It bound to a real literal, so every
    grounding check passed -- and the line adds no verdict, because a heading is
    what the test is called and a `Then` is what it proves.

    Compared on words rather than characters, so casing and punctuation do not
    hide it. Requires a near-total overlap in BOTH directions: a scenario named
    from its own assertion is legitimate and common (`_scenario_from` does it),
    so a `Then` that says more than its heading is fine, and so is a heading
    that says more than its `Then`. What is refused is the two being the same
    sentence.
    """
    if not name.strip():
        return False
    a = set(re.findall(r"[a-z0-9]+", body.lower())) - _FILLER
    b = set(re.findall(r"[a-z0-9]+", name.lower())) - _FILLER
    if len(a) < 2 or len(b) < 2:
        return False
    return a == b


#: Words that carry no claim, so their presence or absence must not decide
#: whether two sentences say the same thing.
_FILLER = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "that", "of", "to", "and"}

#: A verdict with two passing states. "the payment method is displayed as saved
#: OR selected" is satisfied by either, so a run where the save silently failed
#: and the row merely stayed selected passes -- which is the case the step
#: exists to catch. Repair produced this one by hedging a sentence it did not
#: need to hedge.
#:
#: Narrow: an "or" joining two ADJECTIVES or participles at the end of a claim.
#: "the order is refused or held for approval" is caught; "the export fails with
#: an error or warning banner" would be too, and both deserve it. A noun phrase
#: containing "or" -- "the vendor or supplier field" -- is not, because the
#: pattern requires the alternatives to be the last thing in the sentence.
HEDGED = re.compile(r"\b(\w+ed|\w+ing|shown|visible|present)\s+or\s+(\w+ed|\w+ing|\w+)\s*$", re.I)


def _inspect_scenarios(text: str) -> list[StyleFinding]:
    """The checks that are about ONE scenario, not about the file.

    `no Then step` above passes as long as SOMETHING in the file asserts, which
    is why a scenario ending on a dangling `When` shipped: the file had `Then`
    lines, just not in the block that needed one. A scenario is the unit that
    passes or fails, so the unit these are checked over has to be the scenario.
    """
    problems: list[StyleFinding] = []

    def note(message: str, *, structural: bool = False) -> None:
        problems.append(StyleFinding(message, structural=structural))

    problems.extend(_inspect_background(text))

    for name, steps in _scenarios(text):
        if not steps:
            continue
        where = f"scenario {name!r}" if name else "the scenario"

        # 2. A scenario that ends on an action has no verdict. There is nothing
        #    to pass or fail, and whoever executes it reaches the last line with
        #    no idea whether what they saw was right.
        resolved = _resolved(steps)
        if resolved and resolved[-1] != "Then":
            note(
                f"{where} ends on an action rather than an expected result, so it has "
                f"no verdict: the last line is {steps[-1][0]} {steps[-1][1]!r}"
            )

        # 3. Several test cases wearing one heading. Counted as action blocks --
        #    a run of `When`s broken by a `Then` and resumed -- because that is
        #    what a reader sees: this happened and was checked, then this
        #    happened and was checked, six times, about six different things.
        # An expected result is the unit that passes or fails, so it has to be
        # one claim. Checked here rather than in the per-step loop because it
        # applies only to `Then` lines, and only a resolved keyword says which
        # those are -- an `And` after a `Then` is one.
        for keyword, (_raw, line_body) in zip(resolved, steps, strict=True):
            if keyword != "Then":
                continue
            if _is_double_claim(line_body):
                note(
                    f"an expected result in {where} checks two things at once, so a failure "
                    f"will not say which: {line_body!r}"
                )
            if _restates(line_body, name):
                note(
                    f"the expected result in {where} says the same thing as the scenario's "
                    f"own name, so it adds no verdict: {line_body!r}"
                )
            if HEDGED.search(line_body):
                note(
                    f"an expected result in {where} has two passing states, so the failure "
                    f"it is meant to catch also passes: {line_body!r}"
                )

        beats = 0
        previous: str | None = None
        for keyword in resolved:
            if keyword in {"Given", "When"} and previous == "Then":
                beats += 1
            previous = keyword
        if beats + 1 > MAX_BEATS:
            # Rejected, not warned. CLAUDE.md, STATUS.md and the drafting prompt
            # have all said this rejects for as long as they have existed, and
            # the code warned -- so the model was being told to aim at a gate
            # that could not fail it. No row in `VALIDATOR_REPAIR`, so the
            # rejection is terminal: a re-draft could change the step count,
            # which SS3.6 promises it does not. `split.py` is what makes this
            # satisfiable, by cutting the scenario before it is ever rendered.
            note(
                f"{where} has {beats + 1} action/outcome blocks. A scenario is one "
                f"behaviour with one verdict; this reads as {beats + 1} test cases "
                f"sharing a heading, which is what a reader has to untangle before "
                f"they can run any of it",
                structural=True,
            )

    return problems


def _inspect_background(text: str) -> list[StyleFinding]:
    """A `Background:` block is shared setup, so it must not assert.

    `_scenarios` skips the block entirely, under a docstring saying it never
    asserts -- which nothing enforced. It could: `narrative._leading_setup_count`
    cut the block on `role != setup` while `_opening_block` assigned keywords
    and also cut at the first setup step carrying an accepted expected result,
    so a lifted step with an expect landed in the block and rendered there as
    `When` / `Then`. Real Gherkin runners reject that and an Xray import chokes
    on it. The comment is a check now.
    """
    block = _background_block(text)
    if not block:
        return []

    offenders = {keyword for keyword in _resolved(block) if keyword in {"When", "Then"}}
    if not offenders:
        return []
    return [
        StyleFinding(
            f"the Background block contains {' and '.join(sorted(offenders))}. It is shared "
            f"setup for every scenario in the file, so a step in it that acts or asserts "
            f"runs before each one and belongs in a scenario instead",
            structural=True,
        )
    ]


def _background_block(text: str) -> list[tuple[str, str]]:
    """The steps inside `Background:`, if the file has one."""
    out: list[tuple[str, str]] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Background:"):
            inside = True
            continue
        if line.startswith("Scenario:") or line.startswith("Scenario Outline:"):
            inside = False
            continue
        if not inside or not line or line.startswith("#") or line.startswith("|"):
            continue
        head, _, rest = line.partition(" ")
        if head in KEYWORDS and rest.strip():
            out.append((head, rest.strip()))
    return out


def _scenarios(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Every `Scenario:` block, as (name, steps).

    A `Background:` block is deliberately not one: it is shared setup, and
    requiring it to end on a `Then` would be requiring it to stop being a
    background. What it must NOT do is assert -- checked by
    `_inspect_background` rather than here, so that this stays a parser.
    """
    out: list[tuple[str, list[tuple[str, str]]]] = []
    current: list[tuple[str, str]] | None = None
    name = ""

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Scenario:") or line.startswith("Scenario Outline:"):
            if current is not None:
                out.append((name, current))
            name = line.split(":", 1)[1].strip()
            current = []
            continue
        if line.startswith("Background:"):
            if current is not None:
                out.append((name, current))
            current = None
            continue
        if current is None or not line or line.startswith("#") or line.startswith("|"):
            continue
        head, _, rest = line.partition(" ")
        if head in KEYWORDS and rest.strip():
            current.append((head, rest.strip()))

    if current is not None:
        out.append((name, current))
    return out


def _resolved(steps: list[tuple[str, str]]) -> list[str]:
    """Each step's effective keyword, with `And` resolved to what it continues."""
    out: list[str] = []
    concrete: str | None = None
    for keyword, _ in steps:
        if keyword in {"Given", "When", "Then"}:
            concrete = keyword
        out.append(concrete or keyword)
    return out


def _is_run_on(body: str) -> bool:
    """Is this one intent, or a segment read out action by action?

    Two signals, both cheap: clauses separated by commas, and conjunctions.
    Either alone in small doses is fine -- "adds X to the cart and goes to
    checkout" is two actions and reads perfectly. The bar sits where a sentence
    stops naming a goal and starts reading out a segment: three or more actions
    strung together.
    """
    clauses = body.count(",")
    conjunctions = len(CONJUNCTION.findall(body))
    return clauses >= 2 or conjunctions >= 3 or (clauses >= 1 and conjunctions >= 1)


def _steps(text: str) -> list[tuple[str, str]]:
    """Every step line, as (keyword, body). Comments and tables are not steps."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        head, _, rest = line.partition(" ")
        if head in KEYWORDS and rest.strip():
            out.append((head, rest.strip()))
    return out


def _normalise(body: str) -> str:
    return " ".join(body.split()).strip(" .").casefold()


__all__ = ["gherkin_style"]
