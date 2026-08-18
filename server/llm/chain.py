"""Fallback routing and the daily budget guard (SS9.12).

A 429 rolls to the next provider in the chain instead of failing the job. Two
constraints from the spec are enforced here rather than left to discipline:

* The ablation pins one provider and one model and disables fallback. Routing
  is fine in daily use and fatal to the comparison, which would otherwise
  measure provider variance instead of architecture.
* Free-tier quota is enforced per MINUTE, not merely per day -- Gemini allows
  five requests a minute for the current flash model, and one recording needs
  well over that. So `RateLimiter` paces proactively and `RetryingClient`
  honours the delay the provider asks for, rather than failing over a limit
  that clears in seconds. The guard counts only UNCACHED calls, because a
  cassette replay consumes no quota at all.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from server.llm.client import (
    CompletionRequest,
    CompletionResponse,
    ModelClient,
    ModelUnavailable,
    RateLimited,
)


class AllProvidersExhausted(RuntimeError):
    """Every provider in the chain refused."""


class FallbackChain:
    """Tries each client in turn; rolls forward on rate limits."""

    def __init__(self, clients: list[ModelClient], *, enabled: bool = True) -> None:
        if not clients:
            raise ValueError("a fallback chain needs at least one client")
        self.clients = clients
        self.enabled = enabled
        self.name = "chain(" + ", ".join(getattr(c, "name", "?") for c in clients) + ")"
        #: Provider name -> how many times it handed off. Surfaced in the job
        #: log, because a pipeline that looks slow is usually one sleeping in a
        #: backoff loop (SS9.12).
        self.handoffs: dict[str, int] = {}

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        candidates = self.clients if self.enabled else self.clients[:1]
        problems: list[str] = []

        for client in candidates:
            try:
                return client.complete(request)
            except (RateLimited, ModelUnavailable) as exc:
                label = getattr(client, "name", "?")
                self.handoffs[label] = self.handoffs.get(label, 0) + 1
                problems.append(f"{label}: {type(exc).__name__}: {exc}")

        raise AllProvidersExhausted(
            "every provider refused"
            + (" (fallback disabled)" if not self.enabled else "")
            + ": "
            + "; ".join(problems)
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.clients[0].embed(texts)


class BudgetGuard:
    """Counts real provider calls per day and warns before the wall.

    Deliberately advisory rather than blocking: stopping a run halfway leaves a
    half-written artifact, which is worse than finishing and being told the
    quota is nearly gone.
    """

    def __init__(
        self,
        inner: ModelClient,
        state_file: Path,
        *,
        daily_limit: int = 200,
        warn_at: float = 0.8,
    ) -> None:
        self.inner = inner
        self.state_file = state_file
        self.daily_limit = daily_limit
        self.warn_at = warn_at
        self.name = f"budget({getattr(inner, 'name', 'model')})"
        self.warnings: list[str] = []

    def _load(self) -> dict[str, int]:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def used_today(self) -> int:
        return self._load().get(date.today().isoformat(), 0)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self.inner.complete(request)
        if response.cached:
            # A replay costs nothing, which is the entire point of the cache.
            return response

        state = self._load()
        today = date.today().isoformat()
        state[today] = state.get(today, 0) + 1
        # Keep a fortnight; the file is a counter, not a log.
        for key in sorted(state)[:-14]:
            state.pop(key, None)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

        used = state[today]
        if used >= self.daily_limit:
            self.warnings.append(
                f"{used} provider calls today, at or past the configured daily limit of "
                f"{self.daily_limit}. Expect 429s; the chain will roll over if configured."
            )
        elif used >= self.daily_limit * self.warn_at:
            self.warnings.append(
                f"{used} of ~{self.daily_limit} daily provider calls used. "
                f"Your account's real limit is at aistudio.google.com/rate-limit."
            )
        return response

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)


class RetryingClient:
    """Bounded retry with backoff, for transient failures rather than quota.

    The sleeping is made visible on purpose: a pipeline that appears slow is
    usually a pipeline sitting in a backoff loop (SS9.12).
    """

    def __init__(
        self,
        inner: ModelClient,
        *,
        attempts: int = 4,
        base_delay: float = 1.0,
        max_rate_limit_wait: float = 90.0,
        sleep=time.sleep,
    ) -> None:
        self.inner = inner
        self.attempts = attempts
        self.base_delay = base_delay
        self.max_rate_limit_wait = max_rate_limit_wait
        self._sleep = sleep
        self.name = f"retry({getattr(inner, 'name', 'model')})"
        self.log: list[str] = []

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                return self.inner.complete(request)
            except RateLimited as exc:
                # Not all quotas are alike. Gemini reports the free-tier request
                # limit PER MINUTE and says how long to wait, so waiting is the
                # correct response -- failing over would abandon a working
                # provider over a limit that clears in seconds. A quota with no
                # delay attached is the daily kind, and that does go to the chain.
                last = exc
                delay = exc.retry_after
                if delay is None or delay > self.max_rate_limit_wait or attempt == self.attempts:
                    raise
                self.log.append(
                    f"rate limited; the provider asked for {delay:.0f}s, waiting "
                    f"(attempt {attempt}/{self.attempts})"
                )
                self._sleep(delay + 1.0)
            except Exception as exc:  # noqa: BLE001 - providers raise many shapes
                last = exc
                if attempt == self.attempts:
                    break
                delay = self.base_delay * (2 ** (attempt - 1))
                self.log.append(f"attempt {attempt} failed ({exc}); retrying in {delay:.1f}s")
                self._sleep(delay)
        assert last is not None
        raise last

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)


class RateLimiter:
    """Paces requests to stay under a requests-per-minute ceiling.

    Waiting for a 429 and retrying works, but it wastes a round trip and the
    enforced wait is longer than the one you would have taken voluntarily.
    Gemini's free tier allows five requests per minute for the current flash
    model, and one recording needs well over that, so pacing is not a nicety --
    it is the difference between a run that finishes and a run that thrashes.

    SS9.11 permits minutes per recording deliberately, which is what makes
    trading latency for reliability the right call here.
    """

    def __init__(
        self,
        inner: ModelClient,
        *,
        requests_per_minute: int = 5,
        sleep=time.sleep,
        now=time.monotonic,
    ) -> None:
        self.inner = inner
        self.requests_per_minute = requests_per_minute
        self.name = f"paced({getattr(inner, 'name', 'model')})"
        self._sleep = sleep
        self._now = now
        self._recent: list[float] = []
        self.waited_seconds = 0.0

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if self.requests_per_minute > 0:
            self._wait_for_slot()
        response = self.inner.complete(request)
        # A replay never reached the provider, so it does not occupy a slot.
        if not response.cached:
            self._recent.append(self._now())
        return response

    def _wait_for_slot(self) -> None:
        self._recent = [t for t in self._recent if t > self._now() - 60.0]
        if len(self._recent) < self.requests_per_minute:
            return
        wait = 60.0 - (self._now() - self._recent[0]) + 0.5
        if wait > 0:
            self.waited_seconds += wait
            self._sleep(wait)
        self._recent = [t for t in self._recent if t > self._now() - 60.0]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed(texts)
