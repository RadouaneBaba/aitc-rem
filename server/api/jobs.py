"""The JobRunner seam (SS16).

    "Background job. Stop recording -> notification -> draft ready in 2-5
     minutes. Minutes are permitted deliberately: this is the *permissive*
     constraint that unlocks multi-pass analysis, tool calls and repair loops.
     Testers move on to the next test rather than watching a spinner."

In-process threads now, a queue later. The interface is two methods and it is
fixed here so that swapping the implementation is a swap rather than a rewrite.

A job that fails records why and stays queryable. A tester who pressed Stop and
got silence has no way to tell a crash from a slow run, and the second thing
they do is press Stop again.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


@dataclass
class Job:
    id: str
    recording_id: str
    state: JobState = JobState.queued
    #: Free text for the UI: which stage is running, or what went wrong.
    detail: str = "queued"
    run_id: str | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    result: Any = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recordingId": self.recording_id,
            "state": self.state.value,
            "detail": self.detail,
            "runId": self.run_id,
            "error": self.error,
            "createdAt": self.created_at.isoformat(),
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobRunner:
    """In-process implementation of the SS16 seam."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        #: One lock per recording, so two jobs for the same recording run one
        #: after the other. See `_run` for what happens without it.
        self._per_recording: dict[str, threading.Lock] = {}

    def _recording_lock(self, recording_id: str) -> threading.Lock:
        with self._lock:
            return self._per_recording.setdefault(recording_id, threading.Lock())

    def enqueue(
        self,
        recording_id: str,
        work: Callable[[Job], Any],
        *,
        run_id: str | None = None,
    ) -> Job:
        with self._lock:
            job = Job(
                id=f"job_{len(self._jobs) + 1:04d}",
                recording_id=recording_id,
                run_id=run_id,
            )
            self._jobs[job.id] = job

        thread = threading.Thread(target=self._run, args=(job, work), daemon=True)
        self._threads.append(thread)
        thread.start()
        return job

    def status(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def wait(self, timeout: float | None = None) -> None:
        """Block until every job has settled. For tests and for `--wait`."""
        for thread in list(self._threads):
            thread.join(timeout)

    # ----------------------------------------------------------------------

    def _run(self, job: Job, work: Callable[[Job], Any]) -> None:
        """One job at a time per recording, and the wait is visible.

        Two jobs for the same recording write the SAME run directory -- that is
        `_run_id`'s "one recording, one run", and answering the confirmation
        screen re-runs in place on purpose. Nothing stopped the first job from
        still being in flight when the second started, and then both were
        writing it at once. Each builds its own `ToolRunner`, whose ids restart
        at `tc_0001`, so their retrievals overwrite each other file by file.

        Measured on `rec_MTFTJE9BK2PO`: `tc_0006` was recorded in the trace with
        the hash of the basket page it retrieved, and the file at that path held
        the PREVIOUS page, written by the other job. `resolve_call` re-reads the
        file, did not find the total the author had genuinely seen, and refused
        a true verdict -- telling the tester "nothing this run retrieved
        contains '$49.50'" about a value they had pointed at themselves.

        Serialising is the whole fix, and it keeps the intended behaviour: the
        answered run still replaces the unanswered draft, it just does it after
        that draft has finished rather than on top of it.
        """
        lock = self._recording_lock(job.recording_id)
        if not lock.acquire(blocking=False):
            # Said out loud rather than sat on: a job that looks queued forever
            # is indistinguishable from a hung one, which is what makes a
            # tester press the button again.
            job.detail = "waiting for an earlier run of this recording to finish"
            lock.acquire()
        job.state = JobState.running
        job.detail = "running the pipeline"
        try:
            job.result = work(job)
            job.state = JobState.done
            job.detail = "ready for review"
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            job.state = JobState.failed
            job.error = f"{type(exc).__name__}: {exc}"
            job.detail = "failed"
            # The traceback goes to the job rather than only to stderr: the
            # tester is in a browser, and "it failed" with no cause is the
            # thing that makes them stop trusting the tool.
            job.result = traceback.format_exc()
        finally:
            job.finished_at = datetime.now(UTC)
            lock.release()


__all__ = ["Job", "JobRunner", "JobState"]
