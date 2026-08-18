"""Record and replay real model responses.

This is not a fake model. It is a tape recorder: the first time a distinct
prompt is sent, the real provider answers and the answer is written to disk;
every later run replays it.

Why it earns its place rather than being test scaffolding:

* Most debugging changes a validator, a renderer, the segmenter or the IR --
  none of which change the model input. Those re-runs cost nothing.
* The test suite runs offline, deterministically, in CI, forever.
* The ablation (SS3.5) replays identically, which is the difference between a
  comparison and an anecdote.

It is a decorator over the `ModelClient` seam SS16 already requires, so it adds
one small file rather than a parallel abstraction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from server.llm.client import CompletionRequest, CompletionResponse, ModelClient
from server.util.canonical import canonical_json

CassetteMode = Literal["off", "read_write", "read_only", "record_only"]


class CassetteMiss(RuntimeError):
    """read_only was asked for something that was never recorded."""


def cassette_key(request: CompletionRequest) -> str:
    return hashlib.sha256(canonical_json(request.cache_key_payload()).encode("utf-8")).hexdigest()


class CassetteClient:
    """Wraps a real client with a disk cache keyed on the exact request."""

    def __init__(
        self,
        inner: ModelClient,
        directory: Path,
        mode: CassetteMode = "read_write",
    ) -> None:
        self.inner = inner
        self.directory = directory
        self.mode = mode
        self.name = f"cassette({getattr(inner, 'name', 'model')})"
        self.hits = 0
        self.misses = 0
        if mode != "off":
            directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.mode == "off":
            return self.inner.complete(request)

        key = cassette_key(request)
        path = self.path_for(key)

        if self.mode in ("read_write", "read_only") and path.exists():
            self.hits += 1
            stored = json.loads(path.read_text(encoding="utf-8"))
            response = CompletionResponse.from_json(stored["response"])
            response.cached = True
            return response

        if self.mode == "read_only":
            raise CassetteMiss(
                f"no cassette for {key[:12]}... and the run is read_only. "
                f"Re-run with cassetteMode=read_write to record it."
            )

        self.misses += 1
        response = self.inner.complete(request)
        # The request is stored alongside the response. A cassette nobody can
        # read is a cache; one you can open and inspect is a record of what the
        # model was actually asked.
        path.write_text(
            json.dumps(
                {"request": request.cache_key_payload(), "response": response.to_json()},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return response

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)
