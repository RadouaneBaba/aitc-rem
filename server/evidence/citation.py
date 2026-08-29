"""Which retrieval licenses this claim?

The one rule the whole architecture exists to enforce:

    A claim is admissible only if it can point at the retrieval that produced
    it, IN THIS RUN.

Not "the string exists in the recording" -- that is a separate, weaker check.
This resolves a literal against the responses the agent actually received, so
the citation is a fact about what it was shown rather than a claim about it.

**The agent never supplies a `toolCallId`.** It names a literal it says it saw
and the pointer is found here, by reading the stored responses back. That is
what makes a fabricated citation inexpressible rather than merely detectable:
in a real run a model asked to cite an id it had never been shown produced
`find_text_0` against a true claim, which the gate correctly rejected -- so the
claim was right, the citation was invented, and the output was worse than if it
had said nothing.

Extracted so there is one implementation. It was `bind._resolve_call`, and
`bind.py` is being deleted.
"""

from __future__ import annotations

from typing import Any

from server.evidence.text import contains_literal
from server.evidence.tools import ToolRunner


def resolve_call(runner: ToolRunner, tool_call_ids: list[str], literal: str) -> str | None:
    """The agent's own retrieval containing this string, or None.

    Read back from the STORED response rather than from anything the model
    said, and read in reverse: when several retrievals contain the literal, the
    most recent is the one it was looking at when it answered.
    """
    by_id = {call.id: call for call in runner.calls}
    for call_id in reversed(tool_call_ids):
        try:
            stored = runner.storage.load_tool_response(runner.run, call_id)
        except OSError:
            continue
        call = by_id.get(call_id)
        if response_supports(stored, getattr(call, "tool", ""), literal):
            return call_id
    return None


def resolve_event_call(runner: ToolRunner, tool_call_ids: list[str], event_id: str) -> str | None:
    """The agent's own retrieval OF this event, or None.

    `resolve_call` finds the retrieval containing a string, which is the right
    question for every claim except one: a claim that something is **absent**
    cannot cite a retrieval containing its own literal, because the whole point
    is that no retrieval contains it. Searching for it would find nothing and the
    claim would be refused for being true.

    So an `absent` claim is licensed differently -- by the retrieval it is about
    rather than by the string it names. That is a weaker licence and it is
    deliberately kept in its own function rather than added as a branch inside
    `resolve_call`: it is the one place where "the agent went and looked" is
    established by the ARGUMENTS of a call instead of by its response, and that
    difference should be visible at every call site.

    Read in reverse for the same reason `resolve_call` is: when several
    retrievals cover the event, the most recent is the one it was looking at.
    `see` is excluded here too -- a description of a picture is not a reading of
    the page, and "I did not see it in the screenshot" is exactly the kind of
    absence claim that must not be admissible.
    """
    by_id = {call.id: call for call in runner.calls}
    for call_id in reversed(tool_call_ids):
        call = by_id.get(call_id)
        if call is None or call.tool == "see" or call.error:
            continue
        if call.args.get("eventId") == event_id:
            return call_id
    return None


def response_supports(stored: Any, tool: str, literal: str) -> bool:
    """Does this response contain the literal because the RECORDING does?

    `find_text` echoes its query back, so a raw containment check on its
    response is true for any string whatsoever -- the literal is present because
    it was in the REQUEST, not because anything was found. An agent that
    searched for a phrase it had invented and then cited the search would
    satisfy `evidence_retrieved` perfectly, which is exactly the fabrication
    this module exists to make impossible.

    `see` is excluded for the same reason and a stronger one: its response is a
    description of a picture, so nothing in it is evidence that a string was on
    the page. A screenshot can tell the author WHERE to look; the citation still
    has to come from something that read the page.
    """
    if tool == "see":
        return False
    if tool == "find_text" and isinstance(stored, dict):
        stored = {key: value for key, value in stored.items() if key != "query"}
    return contains_literal(stored, literal)


__all__ = ["resolve_call", "resolve_event_call", "response_supports"]
