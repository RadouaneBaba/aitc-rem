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


__all__ = ["Job", "JobRunner", "JobState"]
