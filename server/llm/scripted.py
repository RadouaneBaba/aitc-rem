"""A model that says exactly what it is told to.

This is the one genuinely fake client in the project, and its job is narrow: to
produce output no real model would produce on command. Milestone 8's done-when
requires proving that a fabricated assertion is rejected, and you cannot ask a
model to reliably fabricate -- so the broken cases are scripted here.

It also drives the pipeline's control-flow tests offline, which is why it lives
in the source tree rather than in `tests/`: the ablation and the repair loop
both need a deterministic model to test their own logic against.

Everything else uses real responses, replayed from cassettes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    ToolInvocation,
)

Script = Iterable[CompletionResponse] | Callable[[CompletionRequest], CompletionResponse]


class ScriptedModelClient:
    """Replays a fixed sequence of responses, or computes one per request."""

    name = "scripted"

    def __init__(self, script: Script, *, model: str = "scripted-1") -> None:
        self._fn: Callable[[CompletionRequest], CompletionResponse] | None = None
        self._queue: list[CompletionResponse] = []
        if callable(script):
            self._fn = script
        else:
            self._queue = list(script)
        self.model = model
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self._fn is not None:
            response = self._fn(request)
        elif self._queue:
            response = self._queue.pop(0)
        else:
            raise AssertionError(
                f"the script ran out after {len(self.requests)} request(s); "
                f"the pipeline asked for more turns than were scripted"
            )
        response.model = response.model or self.model
        response.provider = response.provider or "scripted"
        return response

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic, meaningless, and the right length for a smoke test.
        return [[float(len(t) % 7), float(len(t) % 5), float(len(t) % 3)] for t in texts]


# --------------------------------------------------------------------------
# convenience constructors
# --------------------------------------------------------------------------


def answer(text: str, **kwargs) -> CompletionResponse:
    """A final answer with no tool calls."""
    return CompletionResponse(text=text, finish_reason="stop", **kwargs)


def calls(*invocations: tuple[str, dict], preamble: str | None = None) -> CompletionResponse:
    """A turn that requests tools."""
    return CompletionResponse(
        text=preamble,
        tool_calls=[
            ToolInvocation(id=f"call_{i + 1}", name=name, arguments=args)
            for i, (name, args) in enumerate(invocations)
        ],
        finish_reason="tool_calls",
    )
