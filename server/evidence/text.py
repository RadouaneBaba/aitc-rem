"""The one containment primitive.

`contains_literal` is what "the agent saw this string" means everywhere in this
system: `citation.response_supports` uses it to decide which retrieval licenses a
claim, `predicate.evaluate` uses it for the `contains` and `absent` forms, and
`validators.grounding.evidence_retrieved` uses it to re-check the whole thing
against the stored response. Three layers, one implementation, on purpose -- a
second implementation of "is this string in this response" is a second thing that
can disagree with the first.

It lives here, below all three, rather than in `validators/base.py` where it
started. That was fine while the gate was its only caller; once the evidence
layer needed it too, `evidence -> validators -> evidence` was a circular import,
and the honest fix is to notice that a containment check is not a validator.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


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


__all__ = ["contains_literal", "strings_in"]
