"""The model client seam and everything wrapped around it (SS9.12, SS16)."""

from server.llm.cassette import CassetteClient, CassetteMiss, cassette_key
from server.llm.chain import (
    AllProvidersExhausted,
    BudgetGuard,
    FallbackChain,
    RateLimiter,
    RetryingClient,
)
from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ModelClient,
    ModelUnavailable,
    RateLimited,
    ToolInvocation,
)
from server.llm.scripted import ScriptedModelClient, answer, calls

__all__ = [
    "AllProvidersExhausted",
    "BudgetGuard",
    "CassetteClient",
    "CassetteMiss",
    "CompletionRequest",
    "CompletionResponse",
    "FallbackChain",
    "Message",
    "ModelClient",
    "ModelUnavailable",
    "RateLimited",
    "RateLimiter",
    "RetryingClient",
    "ScriptedModelClient",
    "ToolInvocation",
    "answer",
    "calls",
    "cassette_key",
]
