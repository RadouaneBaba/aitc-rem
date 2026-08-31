"""The hold between guessing and authoring.

`ConfirmGate` decides only WHEN authoring resumes. What it resumes with is
always re-read from `expectations.json`, and these tests are about the three
orderings that re-read has to survive -- released, expired, and both at once.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from server.api.confirm import ConfirmGate


def test_answering_inside_the_window_releases_the_run_immediately() -> None:
    gate = ConfirmGate(window_seconds=10)
    released: list[bool] = []

    def run() -> None:
        released.append(gate.hold("rec_1"))

    thread = threading.Thread(target=run)
    thread.start()
    _until(lambda: gate.deadline("rec_1") is not None)

    assert gate.release("rec_1") is True
    thread.join(2)
    assert released == [True]
    # Ten seconds were available and the wait cost none of them.
    assert not thread.is_alive()


def test_the_window_expiring_is_a_normal_outcome_and_not_a_failure() -> None:
    """A run must never depend on a screen having been opened.

    That rule predates the hold and the hold must not weaken it: the window is
    a bound on the wait, not a dependency on the answer. Nobody releases this
    one and it proceeds anyway.
    """
    gate = ConfirmGate(window_seconds=0.05)
    assert gate.hold("rec_1") is False
    assert gate.deadline("rec_1") is None


def test_a_zero_window_does_not_wait_at_all() -> None:
    """The old behaviour, still reachable, and the right setting on a paid tier.

    There a second run costs latency rather than a day's request quota, and the
    tester should never be asked to wait for a screen to save something that is
    not scarce.
    """
    gate = ConfirmGate(window_seconds=0)
    started = time.monotonic()
    assert gate.hold("rec_1") is False
    assert time.monotonic() - started < 0.5
    assert gate.deadline("rec_1") is None


def test_releasing_nothing_says_so_rather_than_raising() -> None:
    """False is the signal that the caller owes the tester a re-run.

    The window had closed, so the answers are on disk and no run has read them.
    Raising here would turn "you were a little late" into an error page.
    """
    gate = ConfirmGate(window_seconds=10)
    assert gate.release("rec_nobody_is_waiting_for") is False


def test_a_release_that_loses_the_race_reports_that_it_lost() -> None:
    """The ordering that would otherwise silently drop a tester's answers.

    If `release` could return True after the hold had already given up, the
    endpoint would tell the tester their answers were folded into the running
    job while that job authored the guesses -- and nothing anywhere would say
    so. `hold` removes itself from the gate before it returns, so a release
    arriving afterwards reports False and the caller enqueues the re-run.
    """
    gate = ConfirmGate(window_seconds=0.05)
    assert gate.hold("rec_1") is False
    assert gate.release("rec_1") is False


def test_the_deadline_is_an_instant_so_a_late_reader_counts_down_correctly() -> None:
    """The screen is opened seconds after Stop sometimes and minutes after at
    others. A remaining-duration answer would be wrong in exactly the case
    where the tester most needs it to be right -- they open the tab late, are
    told they have two minutes, and the run starts under them.
    """
    gate = ConfirmGate(window_seconds=10)
    thread = threading.Thread(target=lambda: gate.hold("rec_1"))
    thread.start()
    _until(lambda: gate.deadline("rec_1") is not None)

    deadline = gate.deadline("rec_1")
    assert deadline is not None
    remaining = (deadline - datetime.now(UTC)).total_seconds()
    assert 0 < remaining <= 10

    gate.release("rec_1")
    thread.join(2)


def test_two_recordings_hold_independently() -> None:
    """One tester recording two sessions must not have one answer start both."""
    gate = ConfirmGate(window_seconds=10)
    done: list[str] = []

    for rec in ("rec_1", "rec_2"):
        threading.Thread(target=lambda r=rec: (gate.hold(r), done.append(r)), daemon=True).start()
    _until(lambda: gate.deadline("rec_1") and gate.deadline("rec_2"))

    gate.release("rec_1")
    _until(lambda: done == ["rec_1"])
    assert gate.deadline("rec_2") is not None

    gate.release("rec_2")


def _until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition never became true")
