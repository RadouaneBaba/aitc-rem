"""What is being claimed about a retrieval, and whether the retrieval says it.

The gate was substring containment, and only that:

    contains_literal(value, literal) -> any(literal in s for s in strings_in(value))

so `Then the first product is 'The Autumnal Hamper' priced at £120.00` shipped,
proved by that string appearing *somewhere* in the response. **The sentence says
FIRST; the check says PRESENT.** Sorting, ranking, pagination and every negative
assertion were inexpressible, and an author asked for a verdict on a sort could
do nothing better than restate that the page still said what the tester had set
the dropdown to. The judge caught it three times and the revision could not fix
it, because there was nothing to fix it with.

This module is the missing vocabulary. Four forms, all re-evaluated by code
against the stored response -- not four tools. That distinction is the whole
design: a tool named `order()` whose response happens to list twelve products in
order still passes a *containment* check whether the product is first or last,
which launders a presence check as an order check and puts a green badge on it.
The fix has to be a check the validator performs, not a name the model reads.

## Three outcomes, not two

`cannot_evaluate` is a real answer and it is the one that keeps this honest:

* **true** -- the response says it.
* **false** -- the response contradicts it.
* **cannot_evaluate** -- the container is not in this response, the roles do not
  line up, the response is not a snapshot at all. Neither true nor false.

Folding the third into *pass* builds exactly the laundering machine above.
Folding it into *reject* means a change in a response shape silently kills true
claims. It goes to `whyNot`, where a person can read it.

## Addressing

By `role` and accessible `name`, never by a css id or a `ref`. There are no ids
in the node model (`ref` / `role` / `name` / `value` / `children`), and `ref` is
a structural path that is stable only WITHIN one snapshot -- so a predicate is
bound to exactly one stored response and cannot be re-pointed to another event
the way a bare literal can. `author._attach_claim` disables that re-point when a
predicate is present.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from server.evidence.text import contains_literal
from server.models import NodeRef, Predicate, PredicateForm


class Outcome(StrEnum):
    true = "true"
    false = "false"
    cannot_evaluate = "cannot_evaluate"


@dataclass(frozen=True)
class Verdict:
    """What the response said, and a sentence saying how it was read.

    `why` is written for a tester, not for a log: it is what lands in `whyNot`
    when the predicate could not be evaluated, and what a reviewer reads when
    they want to know why a claim was refused.
    """

    outcome: Outcome
    why: str = ""

    @property
    def holds(self) -> bool:
        return self.outcome is Outcome.true

    @property
    def unresolved(self) -> bool:
        return self.outcome is Outcome.cannot_evaluate


def evaluate(response: Any, literal: str, predicate: Predicate | None) -> Verdict:
    """Does this stored response support this claim, in the form it was made?

    `response` is always the STORED response -- the full one. A tool may render a
    smaller view to the model (see `ToolSpec.view`), and evaluating `first_of`
    against such a view would answer a different question: the snapshot view is a
    document-order prefix, and `get_diff`'s ranking reorders outright.
    """
    if predicate is None or predicate.form is PredicateForm.contains:
        return _contains(response, literal)
    if predicate.form is PredicateForm.absent:
        return _absent(response, literal)
    if predicate.form is PredicateForm.first_of:
        return _first_of(response, literal, predicate.container)
    if predicate.form is PredicateForm.count:
        return _count(response, predicate)
    return Verdict(Outcome.cannot_evaluate, f"unknown claim form {predicate.form!r}")


# --------------------------------------------------------------------------
# the forms
# --------------------------------------------------------------------------


def _contains(response: Any, literal: str) -> Verdict:
    """The historical check, unchanged, so an assertion written before this
    module existed means exactly what it always did."""
    if contains_literal(response, literal):
        return Verdict(Outcome.true)
    return Verdict(Outcome.false, f"{_short(literal)} is not in this retrieval")


def _absent(response: Any, literal: str) -> Verdict:
    """The literal is NOT there.

    Note what this cannot do on its own: absence in a retrieval is only evidence
    about the page if the retrieval was of the whole page. A response that
    returned nothing at all satisfies `absent` for every string in the language,
    which is why an empty or errored retrieval is `cannot_evaluate` rather than
    a free pass.
    """
    if not _is_page(response):
        return Verdict(
            Outcome.cannot_evaluate,
            "a claim that something is absent needs a retrieval of the whole page; "
            "this response does not cover one",
        )
    if contains_literal(response, literal):
        return Verdict(Outcome.false, f"{_short(literal)} IS in this retrieval")
    return Verdict(Outcome.true)


def _first_of(response: Any, literal: str, container: NodeRef | None) -> Verdict:
    """The literal names the first child of the container, in document order.

    This is the form the sorting recording needed and could not express.
    """
    if container is None:
        return Verdict(
            Outcome.cannot_evaluate,
            "a claim about what comes first has to say first of WHAT: name the "
            "container by its role and name",
        )
    node = _find(_roots(response), container)
    if node is None:
        return Verdict(
            Outcome.cannot_evaluate,
            f"{_describe(container)} is not in this retrieval, so nothing here "
            "says what came first inside it",
        )
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    if not children:
        return Verdict(
            Outcome.cannot_evaluate,
            f"{_describe(container)} was retrieved but has nothing in it here",
        )

    # Searched WITHIN the first child, subtree and all, rather than on the child
    # node itself. A product in a real grid is an unnamed `listitem` wrapping a
    # link, an image and a price, so the name the claim is about is one or two
    # levels down and matching only the wrapper would refuse every true claim.
    #
    # The discrimination is not lost by that, because it never came from
    # matching shallowly: it comes from the search being confined to the FIRST
    # child. Under plain containment the literal could be the twelfth product
    # and still pass; here the twelfth product is in a different subtree.
    first = children[0]
    if contains_literal(first, literal):
        return Verdict(Outcome.true)
    return Verdict(
        Outcome.false,
        f"the first item in {_describe(container)} is "
        f"{_short(_label(first) or first.get('role') or 'unnamed')}, "
        f"not {_short(literal)}",
    )


def _count(response: Any, predicate: Predicate) -> Verdict:
    """The container holds exactly n children, optionally of one role.

    "the list drops from 24 products to 9" -- the claim `event_coverage` and
    `evidence_retrieved` between them could never express, because both of those
    numbers appear on the page as text either way.
    """
    if predicate.container is None:
        return Verdict(
            Outcome.cannot_evaluate,
            "a count has to say what is being counted: name the container by its "
            "role and name",
        )
    if predicate.n is None:
        return Verdict(Outcome.cannot_evaluate, "a count claim did not say how many")
    node = _find(_roots(response), predicate.container)
    if node is None:
        return Verdict(
            Outcome.cannot_evaluate,
            f"{_describe(predicate.container)} is not in this retrieval, so there "
            "is nothing here to count",
        )
    children = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    if predicate.role:
        wanted = predicate.role.casefold()
        matching = [c for c in children if str(c.get("role") or "").casefold() == wanted]
        if not matching and children:
            return Verdict(
                Outcome.cannot_evaluate,
                f"{_describe(predicate.container)} holds no {predicate.role!r} at "
                "all here, so this is not a count of nothing -- it is a claim "
                "about something the retrieval does not describe",
            )
        children = matching
    actual = len(children)
    if actual == predicate.n:
        return Verdict(Outcome.true)
    return Verdict(
        Outcome.false,
        f"{_describe(predicate.container)} holds {actual} here, not {predicate.n}",
    )


# --------------------------------------------------------------------------
# reading a stored response as a page
# --------------------------------------------------------------------------


def _roots(response: Any) -> list[dict[str, Any]]:
    """Every node tree in a stored response.

    Only `get_snapshot` returns one. A diff is a list of changed nodes with no
    tree between them, and a network or narration response has no page in it at
    all -- so a positional claim against one of those is `cannot_evaluate`, which
    is the correct answer and not a rejection.
    """
    if not isinstance(response, dict):
        return []
    out: list[dict[str, Any]] = []
    root = response.get("root")
    if isinstance(root, dict):
        out.append(root)
    for region in response.get("liveRegions") or []:
        if isinstance(region, dict):
            out.append(region)
    return out


def _is_page(response: Any) -> bool:
    return bool(_roots(response)) and bool(
        isinstance(response, dict) and response.get("present", True)
    )


def _find(roots: list[dict[str, Any]], ref: NodeRef) -> dict[str, Any] | None:
    """The first node matching role, and name when one was given. Document order."""
    role = ref.role.casefold()
    name = (ref.name or "").strip().casefold()

    stack = list(reversed(roots))
    while stack:
        node = stack.pop()
        if str(node.get("role") or "").casefold() == role and (
            not name or name in str(node.get("name") or "").casefold()
        ):
            return node
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(reversed([c for c in children if isinstance(c, dict)]))
    return None


def _label(node: dict[str, Any]) -> str:
    """What to call this node when telling the author what WAS first.

    Its own name if it has one, otherwise the first named thing inside it --
    which for a product tile is the product. Used only for the sentence; the
    check itself searches the whole subtree.
    """
    own = str(node.get("name") or node.get("value") or "").strip()
    if own:
        return own
    stack = [c for c in (node.get("children") or []) if isinstance(c, dict)]
    while stack:
        child = stack.pop(0)
        text = str(child.get("name") or child.get("value") or "").strip()
        if text:
            return text
        stack.extend(c for c in (child.get("children") or []) if isinstance(c, dict))
    return ""


def _describe(ref: NodeRef) -> str:
    return f'the {ref.role} "{ref.name}"' if ref.name else f"the {ref.role}"


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(str(text).split())
    return repr(text if len(text) <= limit else text[:limit] + "...")


__all__ = ["Outcome", "Verdict", "evaluate"]
