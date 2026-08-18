"""Google Gemini, through the `google-genai` SDK.

SS9.12's budget posture: free tiers first, paid only where free fails. Two
things about the free tier are recorded here because they change how the
pipeline must be used, not merely what it costs:

* Google uses content submitted on the unpaid tier to improve its products, and
  human reviewers may read it. So free-tier runs are for demo and public
  applications only; anything recorded against a real application needs a paid
  endpoint. The pre-send gate enforces that mechanically (SS7.3).
* The binding limit is requests per day, not tokens per minute. The cassette
  cache is what keeps a day of prompt iteration inside it.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    ModelUnavailable,
    RateLimited,
    ToolInvocation,
)

#: Checked against the live model list and real quota errors, August 2026.
#:
#: Gemini 2.5 Flash and 2.5 Flash Lite are no longer served to new API keys,
#: and the current flagship flash (3.7) allows FIVE requests per minute and
#: TWENTY PER DAY on the free tier -- which one recording exhausts before it
#: finishes. The lite line has a workable free allowance and does reliable
#: multi-turn tool calling, which SS9.12 makes the non-negotiable requirement.
#:
#: This is exactly the churn SS9.12 anticipates ("providers, limits and prices
#: move constantly"), and why model choice is per-stage configuration.
DEFAULT_MODEL = "gemini-3.1-flash-lite"


class GeminiClient:
    """Thin adapter. Everything clever lives in the decorators around it."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, *, model: str = DEFAULT_MODEL) -> None:
        self.api_key = (
            api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        self.model = model
        self._client: Any = None

    def _ensure(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise ModelUnavailable(
                "no GEMINI_API_KEY in the environment. Set one, or run with "
                "cassetteMode=read_only to replay recorded responses."
            )
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on an extra
            raise ModelUnavailable(
                "google-genai is not installed. Install the 'models' extra: "
                "pip install -e '.[models]'"
            ) from exc
        self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------------

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        client = self._ensure()
        from google.genai import types  # noqa: PLC0415 - optional dependency

        system, contents = _to_contents(request, types)
        config: dict[str, Any] = {"temperature": request.temperature}
        if system:
            config["system_instruction"] = system
        if request.max_output_tokens:
            config["max_output_tokens"] = request.max_output_tokens
        if request.tools:
            # The tool loop is driven by the naming stage, which logs every call
            # as content-addressed evidence (SS8.2). Letting the SDK execute
            # functions automatically would run retrievals this pipeline never
            # sees, and an assertion could then cite nothing.
            config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                disable=True
            )
            config["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"],
                            description=t["description"],
                            parameters=t["parameters"],
                        )
                        for t in request.tools
                    ]
                )
            ]
        elif request.json_output:
            config["response_mime_type"] = "application/json"

        try:
            raw = client.models.generate_content(
                model=request.model or self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises many shapes
            message = str(exc)
            if "429" in message or "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
                raise RateLimited(message, retry_after=_retry_delay(message)) from exc
            raise

        return _from_response(raw, request, self.name)


def _retry_delay(message: str) -> float | None:
    """Pull `retryDelay: '17s'` out of a 429 body.

    Gemini reports the free-tier request quota per MINUTE, so the delay it asks
    for is usually seconds. Waiting is the correct response; failing over would
    give up a working provider over a transient limit.
    """
    match = re.search(r"retryDelay['\"]?[:=]\s*['\"]?(\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1))
    match = re.search(r"[Pp]lease retry in (\d+(?:\.\d+)?)s", message)
    return float(match.group(1)) if match else None


def _to_contents(request: CompletionRequest, types: Any) -> tuple[str | None, list[Any]]:
    """Translate our neutral messages into Gemini's content list."""
    system: str | None = None
    contents: list[Any] = []

    for message in request.messages:
        if message.role == "system":
            system = message.content
            continue

        if message.role == "tool":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=message.name or "tool",
                            response={"result": message.content or ""},
                        )
                    ],
                )
            )
            continue

        parts: list[Any] = []
        if message.content:
            parts.append(types.Part.from_text(text=message.content))
        for call in message.tool_calls:
            part = types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments))
            # Gemini 3 rejects a replayed function call whose thought signature
            # is missing, so the opaque blob it returned has to come back with
            # it. Dropping it fails the whole multi-turn tool loop, which is
            # the one thing SS9.12 will not compromise on.
            if call.signature:
                part.thought_signature = base64.b64decode(call.signature)
            parts.append(part)
        if parts:
            contents.append(
                types.Content(role="model" if message.role == "assistant" else "user", parts=parts)
            )

    return system, contents


def _from_response(raw: Any, request: CompletionRequest, provider: str) -> CompletionResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolInvocation] = []

    candidates = getattr(raw, "candidates", None) or []
    for index, candidate in enumerate(candidates):
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            call = getattr(part, "function_call", None)
            if call is not None:
                args = dict(getattr(call, "args", None) or {})
                raw_signature = getattr(part, "thought_signature", None)
                tool_calls.append(
                    ToolInvocation(
                        id=f"call_{index}_{len(tool_calls) + 1}",
                        name=call.name,
                        arguments=args,
                        signature=(
                            base64.b64encode(raw_signature).decode("ascii")
                            if raw_signature
                            else None
                        ),
                    )
                )

    usage = getattr(raw, "usage_metadata", None)
    return CompletionResponse(
        text="".join(text_parts) or None,
        tool_calls=tool_calls,
        finish_reason="tool_calls" if tool_calls else "stop",
        prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        completion_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        model=request.model,
        provider=provider,
    )


def parse_json_answer(text: str | None) -> dict[str, Any]:
    """Models fence JSON in markdown often enough to be worth handling here."""
    if not text:
        return {}
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        if stripped.endswith("```"):
            stripped = stripped.rsplit("```", 1)[0]
        stripped = stripped.strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        # Last resort: the first balanced object in the text.
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}
