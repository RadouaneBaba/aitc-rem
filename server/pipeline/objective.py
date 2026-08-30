"""Is the tester's objective a CHECK, or is it a topic?

The recorder already asks this question as the tester types
(`extension/src/popup/objective.ts`) and says so in one line under the box. This
is the same question asked again on the way IN to the model, and it exists
because the coach only ever advised.

`docs/RECORDING.md` holds a three-way ablation whose result is the whole reason
for this module: **a vague objective is worse than no objective at all.** It
steers the test toward the mechanism it names and away from the outcome the
tester was actually checking; with the box empty, the tool reads the session and
finds the interesting part on its own. Measured again across every recording on
disk, against the judge's verdicts:

    check if hamper sizes change correctly              -> bad
    check if filters are working correctly              -> bad
    check if i can add cafe products correctly          -> bad
    Exercise the awkward parts of the checkout page     -> bad
    Check that an order over EUR500 requires approval   -> good
    Check that adding an item updates the cart badge    -> good
    Check that an order can be exported after approval  -> needs-work

Four of four vague, four of four bad. Five of five sharp, five acceptable. The
coffee session that prompted this work was `Check that coffee products can be
added correctly to the bag` -- vague by the first rule below.

## Why here and not in the recorder

The recorder must never rewrite what the tester typed. SS6.7 ranks the
objective above everything the pipeline infers, and a recorder that silently
improved it would invert that ladder; worse, a recording already on disk has to
keep meaning what it meant when it was made. So the string is recorded exactly
as typed and travels on `Recording.objective` forever. What changes is only
whether `digest.py` shows it to the model.

The rules are a port of `objective.ts` and the two must agree -- the tester is
told "this grades a mechanism rather than naming an outcome" and then the run
behaves accordingly. `tests/test_objective.py` runs the same cases as
`objective.test.ts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["empty", "sharp", "vague", "actions"]

#: Words that grade a mechanism instead of naming an outcome. "change
#: correctly" says the tester will know it when they see it; it gives the author
#: nothing to assert on, and it names the mechanism -- sizes changing -- which
#: is what the test then gets written about.
GRADED = re.compile(
    r"\b(correctly|properly|appropriately|as expected|works?|working)\b", re.IGNORECASE
)

#: A proposition has one of these. It is what makes an objective checkable.
CLAUSE = re.compile(r"\b(that|whether)\b", re.IGNORECASE)

#: Nouns that name an area of the application rather than a behaviour of it.
AREA = re.compile(
    r"\b(page|flow|form|functionality|feature|section|screen|module|parts?|stuff|behaviou?rs?)\b",
    re.IGNORECASE,
)

#: Verbs that describe a CAPABILITY rather than an outcome. "the checkout
#: handles slow validation" names something the app does in general; it has no
#: state you could look at afterwards and call right or wrong.
CAPABILITY = re.compile(r"\b(handles?|supports?|manages?|processes|deals with)\b", re.IGNORECASE)

#: Verbs that say the tester is verifying something.
CHECKS = re.compile(r"\b(check|verify|confirm|ensure|assert|make sure|test)\b", re.IGNORECASE)

#: Verbs that describe doing rather than checking.
DOES = re.compile(
    r"^\s*(sign|log|add|click|open|navigate|go|fill|enter|select|browse|use|exercise|try)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Advice:
    verdict: Verdict
    #: One sentence. Empty when there is nothing worth saying.
    message: str


def coach(raw: str | None) -> Advice:
    """Classify an objective. A port of `objective.ts`'s `coachObjective`."""
    text = (raw or "").strip()

    # Silence is a legitimate answer and the ablation says so out loud, so an
    # empty box is never nagged at.
    if not text:
        return Advice("empty", "")

    if GRADED.search(text):
        return Advice(
            "vague",
            "This grades a mechanism rather than naming an outcome.",
        )

    if not CLAUSE.search(text) and (AREA.search(text) or CAPABILITY.search(text)):
        return Advice("vague", "This names an area of the app, not a check.")

    if not CHECKS.search(text) and DOES.match(text):
        return Advice("actions", "This describes what you are going to DO.")

    return Advice("sharp", "")


def usable(raw: str | None) -> str:
    """The objective as the model should see it, which is nothing when it is vague.

    `actions` is NOT dropped. "Sign in and add a hamper" describes what the
    tester did rather than what they were checking, which is weaker than a
    proposition but is still true, still theirs, and still names the part of the
    session they cared about. Only `vague` actively misleads: it names a
    mechanism the test then gets written about instead of the outcome.
    """
    return "" if coach(raw).verdict == "vague" else (raw or "").strip()
