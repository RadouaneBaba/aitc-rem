"""The model client seam: cassettes, fallback and the budget guard (SS9.12).

The cassette is the piece that makes free-tier development viable, so what it
promises is worth checking: identical requests replay, different ones do not,
and a replay costs no quota.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.llm import (
    AllProvidersExhausted,
    BudgetGuard,
    CassetteClient,
    CassetteMiss,
    CompletionRequest,
    FallbackChain,
    Message,
    RateLimited,
    RateLimiter,
    RetryingClient,
    ScriptedModelClient,
    answer,
    cassette_key,
)
from server.llm.client import ModelUnavailable
from server.llm.gemini import parse_json_answer


def request(text: str = "name this step", model: str = "gemini-2.5-flash") -> CompletionRequest:
    return CompletionRequest(model=model, messages=[Message(role="user", content=text)])


class Counting:
    """Counts real calls, so 'did this hit the provider?' is answerable."""

    name = "counting"

    def __init__(self, reply: str = "ok") -> None:
        self.calls = 0
        self.reply = reply

    def complete(self, req: CompletionRequest):
        self.calls += 1
        return answer(self.reply, model=req.model, provider="counting")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


# --------------------------------------------------------------------------
# cassettes
# --------------------------------------------------------------------------


def test_the_same_request_replays_without_touching_the_provider(tmp_path: Path):
    inner = Counting()
    client = CassetteClient(inner, tmp_path / "cassettes")

    first = client.complete(request())
    second = client.complete(request())

    assert inner.calls == 1, "the second identical request must not reach the provider"
    assert first.text == second.text
    assert first.cached is False
    assert second.cached is True


def test_a_different_request_is_a_different_cassette(tmp_path: Path):
    inner = Counting()
    client = CassetteClient(inner, tmp_path / "cassettes")

    client.complete(request("name step one"))
    client.complete(request("name step two"))
    assert inner.calls == 2

    # And the model matters as much as the prompt.
    client.complete(request("name step one", model="gemini-2.5-pro"))
    assert inner.calls == 3


def test_the_key_ignores_nothing_that_changes_the_answer():
    base = request()
    assert cassette_key(base) == cassette_key(request())

    hotter = request()
    hotter.temperature = 0.7
    assert cassette_key(base) != cassette_key(hotter)

    with_tools = request()
    with_tools.tools = [{"name": "get_diff", "description": "", "parameters": {}}]
    assert cassette_key(base) != cassette_key(with_tools)


def test_read_only_replays_and_refuses_to_call_out(tmp_path: Path):
    directory = tmp_path / "cassettes"
    recorder = CassetteClient(Counting("recorded"), directory, mode="read_write")
    recorder.complete(request())

    inner = Counting()
    offline = CassetteClient(inner, directory, mode="read_only")
    assert offline.complete(request()).text == "recorded"
    assert inner.calls == 0

    # A run pinned to read_only is fully offline and deterministic; an
    # unrecorded prompt is an error rather than a silent network call.
    with pytest.raises(CassetteMiss):
        offline.complete(request("something never recorded"))


def test_off_disables_replay_entirely(tmp_path: Path):
    inner = Counting()
    client = CassetteClient(inner, tmp_path / "cassettes", mode="off")
    client.complete(request())
    client.complete(request())
    assert inner.calls == 2


def test_a_cassette_is_readable_by_a_person(tmp_path: Path):
    # A cache nobody can open is a cache; a record of what the model was
    # actually asked is worth more when debugging a bad step.
    directory = tmp_path / "cassettes"
    client = CassetteClient(Counting("hello"), directory)
    client.complete(request("name this step"))

    stored = json.loads(next(directory.glob("*.json")).read_text(encoding="utf-8"))
    assert stored["request"]["messages"][0]["content"] == "name this step"
    assert stored["response"]["text"] == "hello"


# --------------------------------------------------------------------------
# fallback and budget
# --------------------------------------------------------------------------


class AlwaysLimited:
    name = "limited"

    def complete(self, req: CompletionRequest):
        raise RateLimited("429 RESOURCE_EXHAUSTED")

    def embed(self, texts):
        return []


class Unconfigured:
    name = "unconfigured"

    def complete(self, req: CompletionRequest):
        raise ModelUnavailable("no api key")

    def embed(self, texts):
        return []


def test_a_rate_limit_rolls_to_the_next_provider():
    backup = Counting("from the backup")
    chain = FallbackChain([AlwaysLimited(), backup])

    assert chain.complete(request()).text == "from the backup"
    assert chain.handoffs == {"limited": 1}


def test_an_unconfigured_provider_is_skipped_rather_than_fatal():
    backup = Counting("from the backup")
    chain = FallbackChain([Unconfigured(), backup])
    assert chain.complete(request()).text == "from the backup"


def test_disabling_fallback_pins_the_first_provider():
    # SS9.12 -- the ablation pins one provider and one model, because routing
    # would make it measure provider variance instead of architecture.
    backup = Counting("from the backup")
    chain = FallbackChain([AlwaysLimited(), backup], enabled=False)

    with pytest.raises(AllProvidersExhausted) as excinfo:
        chain.complete(request())
    assert "fallback disabled" in str(excinfo.value)
    assert backup.calls == 0


def test_exhausting_the_chain_says_what_each_provider_did():
    chain = FallbackChain([AlwaysLimited(), Unconfigured()])
    with pytest.raises(AllProvidersExhausted) as excinfo:
        chain.complete(request())
    message = str(excinfo.value)
    assert "limited" in message
    assert "unconfigured" in message


def test_the_budget_guard_counts_only_uncached_calls(tmp_path: Path):
    inner = Counting()
    cassettes = CassetteClient(inner, tmp_path / "cassettes")
    guard = BudgetGuard(cassettes, tmp_path / "budget.json", daily_limit=10)

    guard.complete(request())
    guard.complete(request())  # replayed

    # The binding free-tier limit is requests per day, and a replay costs none.
    assert guard.used_today() == 1
    assert inner.calls == 1


def test_the_budget_guard_warns_before_the_wall(tmp_path: Path):
    guard = BudgetGuard(Counting(), tmp_path / "budget.json", daily_limit=4, warn_at=0.5)
    for i in range(4):
        guard.complete(request(f"prompt {i}"))

    assert guard.used_today() == 4
    assert guard.warnings
    assert "aistudio.google.com/rate-limit" in " ".join(guard.warnings)
    # Advisory, not blocking: stopping halfway leaves a half-written artifact.
    assert guard.complete(request("prompt 5")).text == "ok"


def test_retries_are_bounded_and_visible():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def complete(self, req):
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError("connection reset")
            return answer("eventually")

        def embed(self, texts):
            return []

    flaky = Flaky()
    slept: list[float] = []
    client = RetryingClient(flaky, attempts=3, base_delay=0.01, sleep=slept.append)

    assert client.complete(request()).text == "eventually"
    assert flaky.calls == 3
    # A pipeline that appears slow is usually one sleeping in a backoff loop,
    # so the sleeping is recorded rather than silent (SS9.12).
    assert len(client.log) == 2
    assert slept == [0.01, 0.02]


def test_a_rate_limit_is_not_retried_but_handed_to_the_chain():
    inner = AlwaysLimited()
    client = RetryingClient(inner, attempts=3, base_delay=0.01, sleep=lambda _: None)
    with pytest.raises(RateLimited):
        client.complete(request())


# --------------------------------------------------------------------------
# response parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"text": "the tester submits the order"}',
        '```json\n{"text": "the tester submits the order"}\n```',
        '```\n{"text": "the tester submits the order"}\n```',
        'Sure! {"text": "the tester submits the order"} Hope that helps.',
    ],
)
def test_json_answers_survive_the_ways_models_wrap_them(raw: str):
    assert parse_json_answer(raw)["text"] == "the tester submits the order"


@pytest.mark.parametrize("raw", [None, "", "no json here", "[1, 2, 3]"])
def test_unparseable_answers_yield_nothing_rather_than_raising(raw):
    assert parse_json_answer(raw) == {}


def test_the_scripted_client_says_when_it_runs_out():
    model = ScriptedModelClient([answer("only one")])
    model.complete(request())
    with pytest.raises(AssertionError) as excinfo:
        model.complete(request())
    assert "ran out" in str(excinfo.value)


def test_retry_must_sit_inside_the_chain_to_see_a_rate_limit():
    """Ordering bug, hit in a real run and pinned here.

    A FallbackChain converts RateLimited into AllProvidersExhausted. Wrapped
    the other way round -- retry(chain(provider)) -- the retry only ever sees
    the generic exception, so it backs off for a second or two while the
    provider asked for forty-four, and the run dies on a limit that would have
    cleared on its own.
    """

    class LimitedUntilWaited:
        """Succeeds only once something has slept long enough."""

        name = "limited"

        def __init__(self, waited: list[float]) -> None:
            self.waited = waited

        def complete(self, req):
            if sum(self.waited) >= 44.0:
                return answer("after the wait")
            raise RateLimited("429 quota, per minute", retry_after=44.0)

        def embed(self, texts):
            return []

    # Wrong order: generic backoff never reaches 44s, so it gives up.
    waited: list[float] = []
    wrong = RetryingClient(
        FallbackChain([LimitedUntilWaited(waited)]),
        attempts=3,
        base_delay=0.01,
        sleep=waited.append,
    )
    with pytest.raises(AllProvidersExhausted):
        wrong.complete(request())
    assert sum(waited) < 1.0, "it backed off for a fraction of what was asked"

    # Right order: the provider waits out its own limit and the run continues.
    waited = []
    right = FallbackChain([LimitedUntilWaited(waited)])
    right.clients = [
        RetryingClient(right.clients[0], attempts=3, base_delay=0.01, sleep=waited.append)
    ]
    assert right.complete(request()).text == "after the wait"
    assert waited == [45.0], "it waits the delay the provider asked for, plus a margin"


def test_a_quota_with_no_delay_is_not_retried():
    # A daily quota comes back without a retryDelay. Waiting cannot help, so it
    # goes to the chain instead of burning attempts.
    class DailyLimit:
        name = "daily"

        def __init__(self):
            self.calls = 0

        def complete(self, req):
            self.calls += 1
            raise RateLimited("429 quota exceeded for the day")

        def embed(self, texts):
            return []

    provider = DailyLimit()
    client = RetryingClient(provider, attempts=3, base_delay=0.01, sleep=lambda _: None)
    with pytest.raises(RateLimited):
        client.complete(request())
    assert provider.calls == 1


def test_the_pacer_spaces_requests_to_the_ceiling():
    inner = Counting()
    slept: list[float] = []
    clock = [0.0]
    pacer = RateLimiter(
        inner, requests_per_minute=2, sleep=lambda s: slept.append(s), now=lambda: clock[0]
    )

    pacer.complete(request("a"))
    pacer.complete(request("b"))
    assert slept == []

    # The third within the same minute has to wait for the window to roll.
    pacer.complete(request("c"))
    assert slept and 59 < slept[0] <= 61


def test_a_replay_does_not_occupy_a_rate_limit_slot():
    # The cassette sits outside the pacer for exactly this reason: replaying
    # never touched the provider, so it must not cost a slot.
    inner = Counting()
    slept: list[float] = []
    pacer = RateLimiter(inner, requests_per_minute=1, sleep=slept.append, now=lambda: 0.0)

    class Replayer:
        name = "replayer"

        def complete(self, req):
            r = answer("replayed")
            r.cached = True
            return r

        def embed(self, texts):
            return []

    pacer.inner = Replayer()
    for _ in range(5):
        pacer.complete(request())
    assert slept == []
