"""Byte-stable serialization and hashing.

SS3.2 hashes every tool response and `evidence_retrieved` re-verifies that hash
before it will accept an assertion. That makes the serializer load-bearing in a
way it would not normally be: any variation in key order, separator whitespace
or unicode escaping between the write and the re-read produces a hash mismatch,
and the validator rejects a CORRECT assertion. A trust-focused tool failing
closed on true claims is worse than one that never checked.

So there is exactly one way to serialize, used on both sides.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """The single serialization used for hashing and for stored tool responses."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_fallback,
    )


def _fallback(obj: Any) -> Any:
    # Pydantic models and enums reach here when nested inside plain containers.
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"{type(obj).__name__} is not serializable in a tool response")


def response_hash(value: Any) -> str:
    """sha256 of the canonical form, as stored in ToolCall.responseHash."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
