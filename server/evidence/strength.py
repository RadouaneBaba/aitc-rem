"""How precisely a literal resolves inside the response that licensed it.

## Why this exists

The gate asks one question of a quoted literal: is this string anywhere in the
stored response (`text.contains_literal`, over every string in the decoded
value). That question is the right one for provenance -- it is what makes
"the agent saw this" mean something -- and it is far too coarse to say whether
the resulting verdict is a TEST.

    Then the cart badge shows "1"        literal "1"

passes `evidence_retrieved`, passes `contains_at`, passes every validator, and
is decoration: `1` occurs **198 times** in the snapshot it cites -- in prices,
in element refs, in urls, in dates. The badge could show nothing at all and the
check would still be green. Measured on `rec_MTCUX3Y0XJ9S`, and the same shape
appears as `1` x211 and `2` x64 on the commercial recordings.

Nothing in the system could tell that apart from

    Then the cart badge shows 1 item     literal "Cart contains 1 items"

which occurs once, names an element, and goes red the moment the badge breaks.

## What it does NOT do

It grades. It does not reject, and it does not change what binds: every claim
that binds today binds identically with this module present, with the same
`toolCallId` and the same outcome. That is the whole reason it is safe, and it
is the difference between this and `evidence_discriminates` -- one of the nine
refusal rules deleted for being a regex guessing at whether a sentence is
meaningful. A regex loses that argument to a model reading the sentence. A
COUNT of how many things could have satisfied the check loses no argument,
because it is not making one.

So the honest split is: the ladder below says how precisely the literal
resolves, `occurrences` says how many places satisfied the check that actually
ran, and a human reads the pair. `"1"` comes back `strong` / 198 -- it does name
exactly one element, AND the containment check the gate performed had 198 ways
to pass. Both halves are true and the gap between them is the finding.

## The rungs are about structure, not length

A short literal is not the problem: `$7.99` is five characters, occurs once, and
is a good verdict. What separates a claim about the page from a coincidence is
whether the literal is the NAME OF AN ELEMENT.

    strong   exactly one element in the response is named this
    medium   several elements are, or it is part of one element's name
    weak     no element carries it -- found only in loose text, spanning nodes
             or inside a url or a json body

`None` means there was nothing to grade against: a `get_network` or
`get_narration` response holds no elements, and a status code is not an element
name. Absent is not a criticism of the claim.

## What counts as an element

Any object in the response carrying both a `role` and a `name`, which is the
node shape the recorder writes (`ref` / `role` / `name` / `value` / `children`).
Deliberately structural rather than keyed to one tool: `get_snapshot` nests them
under `root` and `liveRegions`, `get_diff` lists them flat under `added`,
`removed` and `changed`, and both are worth grading. A response shape that
carries no such objects grades to `None` rather than to `weak`.
"""

from __future__ import annotations

from typing import Any

from server.evidence.text import strings_in
from server.models import EvidenceStrength


def page_identity(value: Any) -> list[str]:
    """What the page calls itself: its url and title, however the tool says it.

    Read only from the TOP of a response, and this is the reason the whole
    module is not simply a node walk. *"the application navigates to the
    confirmation page"* cited on `http://localhost:5173/confirmation` is a good
    verdict -- it is exactly the right evidence for a navigation claim -- and a
    url is the name of no node in the tree. Grading elements alone called it
    `weak` on two real runs, which is a false alarm, and a caution a reviewer
    learns to ignore is worse than no caution.

    The two shapes it appears in are not the same:

      get_snapshot   `url` and `title`, flat
      get_diff       `urlChanged: {from_, to}` -- a navigation IS the diff

    Depth matters. Every call in a `get_network` response carries a `url` of its
    own, and collecting those would make a status-code claim gradeable against
    text that has nothing to do with it.
    """
    if not isinstance(value, dict):
        return []
    out: list[str] = []
    if "root" in value or "present" in value:
        for key in ("url", "title"):
            own = value.get(key)
            if isinstance(own, str) and own:
                out.append(own)
    changed = value.get("urlChanged")
    if isinstance(changed, dict):
        out.extend(v for v in changed.values() if isinstance(v, str) and v)
    return out


def element_texts(value: Any) -> list[str]:
    """Every element's own text: its accessible name, and its value.

    An element is an object with both a `role` and a `name` -- see the module
    docstring. `value` is included because a field's contents are as much that
    element's own text as its label is, and a claim about what a box CONTAINS is
    an ordinary thing to want to make.

    A page's `url` and `title` count too, and they are the reason this is not
    simply a node walk. *"the application navigates to the confirmation page"*
    cited on `http://localhost:5173/confirmation` is a good verdict -- it is
    precisely the right evidence for a navigation claim -- and a url is the name
    of nothing in the tree, so grading only elements called it `weak` on two real
    runs. They are read only from the TOP of a page-shaped response: every entry
    in a `get_network` response carries a `url` too, and collecting those would
    make a status-code claim gradeable against text that has nothing to do with
    it.
    """
    out: list[str] = []
    out.extend(page_identity(value))
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if "role" in item and isinstance(item.get("name"), str):
                out.append(item["name"])
                own = item.get("value")
                if isinstance(own, str):
                    out.append(own)
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return out


def occurrences(response: Any, literal: str) -> int:
    """How many strings of the response contain the literal.

    Counted over `strings_in`, the same decomposition `contains_literal` uses,
    rather than over the serialized form -- a substring search across
    `json.dumps` can match over key boundaries and punctuation, which would
    inflate this number with matches no claim could ever have rested on.
    """
    if not literal:
        return 0
    return sum(1 for s in strings_in(response) if literal in s)


def grade(response: Any, literal: str) -> EvidenceStrength | None:
    """Which rung this literal lands on. `None` when there is nothing to grade.

    Exact comparison is case-sensitive and ignores only surrounding whitespace,
    which matches `store.contains_at`: a name differing in case is a different
    name, and the recorder does not invent leading spaces.
    """
    if not literal:
        return None
    texts = element_texts(response)
    if not texts:
        return None

    target = literal.strip()
    exact = sum(1 for t in texts if t.strip() == target)
    if exact == 1:
        return EvidenceStrength.strong
    if exact > 1:
        return EvidenceStrength.medium
    if any(literal in t for t in texts):
        return EvidenceStrength.medium
    return EvidenceStrength.weak


__all__ = ["element_texts", "grade", "occurrences"]
