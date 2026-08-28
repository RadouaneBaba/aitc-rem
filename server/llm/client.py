"""The ModelClient seam (SS16) and the shapes that cross it.

SS9.12 leaves the provider deliberately undecided and routes every model call
through one thin client, so model selection per stage is configuration rather
than code. One requirement is not negotiable: the model must support reliable
multi-turn tool calling. SS3.2 makes tool calling the mechanism by which claims
are licensed, so a model that drops calls mid-loop cannot run this pipeline at
all -- it is not "cheaper", it is unusable, and it makes pipeline bugs
indistinguishable from model failures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolInvocation:
    """A tool call the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    #: Opaque provider state that must be echoed back with this call when the
    #: conversation is replayed. Gemini 3 calls it a thought signature and
    #: rejects a multi-turn tool loop that omits it. Base64 so it survives a
    #: cassette round trip; meaningless to everything except the provider that
    #: issued it.
    signature: str | None = None


@dataclass
class ImagePart:
    """Pixels, on their way to a multimodal model.

    The whole point of the accessibility-tree snapshot is that a model can read
    it; the whole point of this is the cases where it cannot. When the tree does
    not say whether a list re-sorted, or a control is a canvas, or the change
    was purely visual, the screenshot does -- and no deterministic system can do
    that at all.

    `digest` rather than the bytes is what identifies this in a cache key. A
    cassette keyed on base64 PNGs would be enormous, and it would miss on a
    re-encode of the same picture, which is a cache that costs storage and
    returns nothing.
    """

    mime: str
    data: bytes = field(repr=False)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class Message:
    role: Role
    content: str | None = None
    #: Images to show alongside `content`. Providers differ on where these are
    #: allowed -- Gemini will not carry bytes inside a function response -- so
    #: each adapter decides how to place them; see `gemini._to_contents`.
    images: list[ImagePart] = field(default_factory=list)
    #: Present on assistant turns that requested tools.
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    #: Present on tool turns, naming the invocation being answered.
    tool_call_id: str | None = None
    name: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            out["content"] = self.content
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "name": c.name,
                    "arguments": c.arguments,
                    **({"signature": c.signature} if c.signature else {}),
                }
                for c in self.tool_calls
            ]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.name:
            out["name"] = self.name
        if self.images:
            # By digest. See `ImagePart`: this is a cache key, not a payload.
            out["images"] = [{"mime": i.mime, "sha256": i.digest} for i in self.images]
        return out


@dataclass
class CompletionRequest:
    model: str
    messages: list[Message]
    tools: list[dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.0
    max_output_tokens: int | None = None
    #: Ask for a JSON object back. Kept separate from `tools` because a turn
    #: either calls tools or answers, never both in our protocol.
    json_output: bool = False

    def cache_key_payload(self) -> dict[str, Any]:
        """Exactly what makes this call distinct, for cassette lookup.

        The provider is deliberately absent: a cassette records the answer to a
        question, and re-asking the same question of the same model should
        replay regardless of which endpoint served it.
        """
        return {
            "model": self.model,
            "messages": [m.to_json() for m in self.messages],
            "tools": self.tools,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "json_output": self.json_output,
        }


@dataclass
class CompletionResponse:
    text: str | None = None
    tool_calls: list[ToolInvocation] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    provider: str = ""
    #: True when served from the cassette rather than the provider. Cached
    #: calls consume no quota and no money.
    cached: bool = False

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [
                {
                    "id": c.id,
                    "name": c.name,
                    "arguments": c.arguments,
                    **({"signature": c.signature} if c.signature else {}),
                }
                for c in self.tool_calls
            ],
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model": self.model,
            "provider": self.provider,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CompletionResponse:
        return cls(
            text=data.get("text"),
            tool_calls=[
                ToolInvocation(
                    id=c["id"],
                    name=c["name"],
                    arguments=c.get("arguments", {}),
                    signature=c.get("signature"),
                )
                for c in data.get("tool_calls", [])
            ],
            finish_reason=data.get("finish_reason", "stop"),
            prompt_tokens=data.get("prompt_tokens", 0),
            completion_tokens=data.get("completion_tokens", 0),
            model=data.get("model", ""),
            provider=data.get("provider", ""),
        )


class RateLimited(Exception):
    """The provider refused for quota reasons.

    `retry_after` carries the delay the provider itself asked for, when it
    supplies one. That distinction decides what to do: a per-MINUTE quota comes
    back with a short delay and is worth waiting out, while a per-day quota
    does not and means rolling to the next provider.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ModelUnavailable(Exception):
    """The provider could not be reached or is not configured."""


@runtime_checkable
class ModelClient(Protocol):
    """SS16 -- provider-agnostic. Hosted API or local endpoint, chosen later."""

    name: str

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
