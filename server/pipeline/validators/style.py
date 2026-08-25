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

Every finding is a warning, never a rejection. Style is not correctness, and a
gate that refuses to emit a grounded test case because a sentence starts with
the wrong verb would be trading the valuable thing for the cheap one. What this
does buy is that none of it can regress silently.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from server.models import ValidatorAction, ValidatorName, ValidatorResult, ValidatorStatus
from server.pipeline.validators.base import ValidationContext, passed, result, skipped

KEYWORDS = ("Given", "When", "Then", "And", "But", "*")

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

    findings: list[tuple[str, str]] = []
    for case_id, text in ctx.rendered.items():
        findings.extend((case_id, problem) for problem in _inspect(text))

    for case_id, problem in findings:
        yield result(
            ValidatorName.gherkin_style,
            ValidatorStatus.warn,
            ValidatorAction.warn,
            ctx,
            message=problem,
            test_case_id=case_id,
        )

    if not findings:
        yield passed(
            ValidatorName.gherkin_style,
            ctx,
            f"{len(ctx.rendered)} feature file(s) read as test cases",
        )


def _inspect(text: str) -> list[str]:
    problems: list[str] = []
    steps = _steps(text)

    if not steps:
        return ["the feature file has no steps"]

    # 1. A test case with no expected result is a transcript. This is the one
    #    finding that says something about content rather than phrasing, and it
    #    is the most important of them.
    if not any(keyword in {"Then"} for keyword, _ in steps):
        problems.append(
            "no Then step: this describes what the tester did but never what should "
            "be true afterwards, which is a transcript rather than a test case"
        )

    problems.extend(_inspect_scenarios(text))

    # 2. `And` continues a block; it cannot open one, and `Then` before any
    #    action asserts about a state nothing established.
    first_keyword = steps[0][0]
    if first_keyword in {"And", "But"}:
        problems.append(f"the first step opens with {first_keyword!r}, which continues nothing")

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
            problems.append("a Then step comes before any Given or When")
            break

    # A `Then` reached without any `When` asserts about the preconditions rather
    # than about anything the test did. `narrative._lay_out` prevents it by
    # promoting an assertion-bearing `Given` to `When` -- if it shows up here,
    # that rule has regressed or someone hand-edited the file.
    if "Then" in resolved and "When" not in resolved[: resolved.index("Then")]:
        problems.append(
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
            problems.append(
                f"step {index + 1} opens with Given after an expected result; "
                f"preconditions belong at the top of the scenario"
            )
            break

    previous: str | None = None
    for index, (_keyword, body) in enumerate(steps):
        normalised = _normalise(body)

        # 4. The reader watching the tool stutter.
        if previous is not None and normalised == previous:
            problems.append(f"step {index + 1} repeats the step before it verbatim: {body!r}")
        previous = normalised

        # 5. Mechanics. Quoted values are exempt -- an application may well
        #    have a control named "Click here", and quoting it is correct.
        bare = QUOTED.sub("", body)
        mechanic = MECHANICS.search(bare)
        if mechanic:
            problems.append(
                f"step {index + 1} describes mechanics rather than intent "
                f"({mechanic.group(0)!r}): {body!r}"
            )

        # 6. A step that lists four actions is a segment transcribed rather
        #    than an intent named. It reads badly and it cannot be executed as
        #    a single check, which is what a step is for.
        if _is_run_on(bare):
            problems.append(
                f"step {index + 1} describes several actions at once rather than one "
                f"intent: {body!r}"
            )

        # 7. A step should not end in a full stop -- it is a sentence
        #    fragment whose subject is the keyword. `draft._clean` strips one,
        #    so reaching here means something wrote a step without going
        #    through the drafting stage.
        if body.rstrip().endswith(".") and not body.rstrip().endswith(".."):
            problems.append(
                f"step {index + 1} ends in a full stop; a Gherkin step is a fragment, not a "
                f"sentence: {body!r}"
            )

        # 8. Traceability that belongs in the sidecar.
        leak = LEAKED_TRACE.search(body)
        if leak:
            problems.append(
                f"step {index + 1} carries {leak.group(0)!r} in its text, which breaks "
                f"step-definition matching; traceability belongs in the sidecar"
            )

    # 9. One test case, one person. Checked for self-consistency rather than
    #    against `ProjectConfig.voice`, because a file that calls the same actor
    #    two things is wrong whichever of them the project chose.
    actors = {m.group(1).lower() for m in ACTOR.finditer(" ".join(body for _, body in steps))}
    if len(actors) > 1:
        named = ", ".join(f"the {a}" for a in sorted(actors))
        problems.append(
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


def _inspect_scenarios(text: str) -> list[str]:
    """The checks that are about ONE scenario, not about the file.

    `no Then step` above passes as long as SOMETHING in the file asserts, which
    is why a scenario ending on a dangling `When` shipped: the file had `Then`
    lines, just not in the block that needed one. A scenario is the unit that
    passes or fails, so the unit these are checked over has to be the scenario.
    """
    problems: list[str] = []

    for name, steps in _scenarios(text):
        if not steps:
            continue
        where = f"scenario {name!r}" if name else "the scenario"

        # 2. A scenario that ends on an action has no verdict. There is nothing
        #    to pass or fail, and whoever executes it reaches the last line with
        #    no idea whether what they saw was right.
        resolved = _resolved(steps)
        if resolved and resolved[-1] != "Then":
            problems.append(
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
            if keyword == "Then" and _is_double_claim(line_body):
                problems.append(
                    f"an expected result in {where} checks two things at once, so a failure "
                    f"will not say which: {line_body!r}"
                )

        beats = 0
        previous: str | None = None
        for keyword in resolved:
            if keyword in {"Given", "When"} and previous == "Then":
                beats += 1
            previous = keyword
        if beats + 1 > MAX_BEATS:
            problems.append(
                f"{where} has {beats + 1} action/outcome blocks. A scenario is one "
                f"behaviour with one verdict; this reads as {beats + 1} test cases "
                f"sharing a heading, which is what a reader has to untangle before "
                f"they can run any of it"
            )

    return problems


def _scenarios(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Every `Scenario:` block, as (name, steps).

    A `Background:` block is deliberately not one: it is shared setup, it never
    asserts, and requiring it to end on a `Then` would be requiring it to stop
    being a background.
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
