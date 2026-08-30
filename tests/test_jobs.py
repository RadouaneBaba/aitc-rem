"""Two jobs for one recording must not run at once.

`_run_id` deliberately gives both the SAME run directory -- one recording, one
run -- and answering the confirmation screen re-runs in place on top of the
draft that Stop produced. Nothing stopped the first job from still being in
flight when the second started, and each builds its own `ToolRunner` whose ids
restart at `tc_0001`, so their retrievals overwrite each other file by file.

Measured on `rec_MTFTJE9BK2PO`: the trace recorded `tc_0006` with the hash of
the basket page the author had genuinely retrieved, and the file at that path
held the previous page, written by the other job. The claim was refused, and
the tester -- who had pointed at the order total by hand -- was told the run
never retrieved it.
"""

from __future__ import annotations

import threading
import time

from server.api.jobs import JobRunner, JobState


def test_two_jobs_for_one_recording_never_overlap():
    """The property that keeps two writers off one run directory."""
    runner = JobRunner()
    overlapping = []
    inside = threading.Semaphore(0)
    live = 0
    guard = threading.Lock()

    def work(job):
        nonlocal live
        with guard:
            live += 1
            if live > 1:
                overlapping.append(job.id)
        time.sleep(0.05)
        with guard:
            live -= 1
        inside.release()

    runner.enqueue("rec_same", work)
    runner.enqueue("rec_same", work)
    runner.wait(timeout=5)

    assert not overlapping, "two jobs for one recording ran at the same time"
    assert all(j.state is JobState.done for j in runner.all())


def test_a_different_recording_is_not_held_up():
    """The lock is per recording. Serialising everything would turn a shared
    server into a queue of one, and two testers' sessions have no reason to
    wait on each other -- they write different directories."""
    runner = JobRunner()
    started = threading.Event()
    release = threading.Event()

    def blocker(job):
        started.set()
        release.wait(timeout=5)

    def quick(job):
        pass

    runner.enqueue("rec_slow", blocker)
    assert started.wait(timeout=5)
    runner.enqueue("rec_other", quick)

    deadline = time.time() + 5
    other = None
    while time.time() < deadline:
        other = next((j for j in runner.all() if j.recording_id == "rec_other"), None)
        if other and other.state is JobState.done:
            break
        time.sleep(0.01)

    assert other is not None and other.state is JobState.done, (
        "a job for another recording waited on an unrelated one"
    )
    release.set()
    runner.wait(timeout=5)


def test_the_wait_is_visible_rather_than_silent():
    """A job that looks queued forever is indistinguishable from a hung one,
    and the next thing a tester does is press the button again."""
    runner = JobRunner()
    started = threading.Event()
    release = threading.Event()

    def blocker(job):
        started.set()
        release.wait(timeout=5)

    runner.enqueue("rec_same", blocker)
    assert started.wait(timeout=5)
    second = runner.enqueue("rec_same", lambda job: None)

    deadline = time.time() + 5
    while time.time() < deadline and "waiting" not in second.detail:
        time.sleep(0.01)
    assert "waiting" in second.detail, second.detail

    release.set()
    runner.wait(timeout=5)


def test_a_failing_job_still_frees_the_recording():
    """A crash must release the lock, or one bad run wedges that recording for
    the life of the process."""
    runner = JobRunner()

    def boom(job):
        raise RuntimeError("nope")

    runner.enqueue("rec_same", boom)
    runner.wait(timeout=5)

    ran = []
    runner.enqueue("rec_same", lambda job: ran.append(1))
    runner.wait(timeout=5)

    assert ran == [1], "the lock was not released by the failing job"
