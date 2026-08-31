"""The window in which answering the confirmation screen is free.

`POST /api/recordings` guesses what should have happened and then authors the
document on those guesses, because **a run must never wait on a screen somebody
might not open**. That rule is right and it is not what this file changes.

What it changes is the price of answering. Answering re-runs the recording in
place (`api._run_id`, "one recording, one run"), and a re-run repeats the
expensive half -- the author, up to two rounds, and the judge after each. The
guess itself is not repeated; it is saved beside the recording and re-read. So
the common path -- press Stop, read the screen that opens, answer it -- paid for
the whole authoring stack twice, and on a free tier whose real limit is requests
per day that is most of a day's budget spent on a draft that was about to be
replaced.

The fix is to *hold* rather than to wait: the guess is made and saved (which is
what the screen needs, and it is one model call), authoring stops here for at
most `window` seconds, and then proceeds whatever happened. Three things release
it and all three release the SAME job:

* the tester answers -- authoring reads the answers and there is no second run;
* the tester presses skip -- authoring starts immediately, which is strictly
  better than the old behaviour where skipping meant a run had already begun;
* the window expires -- exactly the old behaviour, and it is what happens when
  nobody opens the screen at all.

**The re-run path stays, untouched.** Somebody who answers an hour later must
still have their answers count, and for them a second run is the only way to get
one. The hold removes the double spend from the common case; it does not remove
the fallback.

## Why a lost update is not possible here

`hold` re-reads `expectations.json` after waking, *whatever* woke it, and the
answer endpoint saves before it releases. Those two orderings together are the
whole argument:

* released inside the window -- the file was written before `release` was
  called, so the re-read sees it.
* timed out, and `release` arrives in the same instant -- `hold` has already
  left `_open`, so `release` returns False and the caller enqueues a re-run.
  The answers are not lost, they are just paid for.
* timed out, `release` won the race and returned True -- then it popped an event
  `hold` had not yet removed, which means `hold` had not yet re-read, and the
  save that preceded the release is on disk before it does.

There is no ordering in which the endpoint reports the answers were folded in
and authoring proceeds without them.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta


class ConfirmGate:
    """Per-recording hold points, and the deadline each one is counting down to.

    One instance per app. Nothing here touches disk: the gate decides *when*
    authoring resumes, and `expectations.json` remains the single record of
    *what* it resumes with.
    """

    def __init__(self, window_seconds: float) -> None:
        #: 0 (or less) disables the hold entirely, which is the old behaviour
        #: and the right setting for a paid endpoint where a second run costs
        #: latency rather than a day's quota.
        self.window = max(0.0, float(window_seconds))
        self._lock = threading.Lock()
        self._open: dict[str, tuple[threading.Event, datetime]] = {}

    # ------------------------------------------------------------------

    def hold(self, recording_id: str) -> bool:
        """Block until answered, skipped, or the window expires.

        Returns whether somebody released it. The caller must re-read the
        expectations from disk either way -- see the module docstring; that
        re-read is what makes the timeout race harmless rather than merely
        unlikely.
        """
        if self.window <= 0:
            return False

        event = threading.Event()
        deadline = datetime.now(UTC) + timedelta(seconds=self.window)
        with self._lock:
            # A second hold for the same recording replaces the first. It
            # cannot happen while `JobRunner` serialises per recording, and if
            # that ever changes, the newer run is the one somebody is watching.
            self._open[recording_id] = (event, deadline)

        try:
            return event.wait(self.window)
        finally:
            with self._lock:
                current = self._open.get(recording_id)
                if current is not None and current[0] is event:
                    del self._open[recording_id]

    def release(self, recording_id: str) -> bool:
        """Answers or a skip arrived. True if a run was still holding for them.

        False means the window had already closed, and the caller owes the
        tester a re-run: their answers are on disk and nothing has read them.
        """
        with self._lock:
            entry = self._open.pop(recording_id, None)
        if entry is None:
            return False
        entry[0].set()
        return True

    def deadline(self, recording_id: str) -> datetime | None:
        """When authoring starts on its own, or None if nothing is holding.

        Sent to the confirmation screen as an instant rather than a duration:
        the screen is often opened seconds after Stop and sometimes minutes
        after, and a countdown from "you have 120s" would be wrong in exactly
        the case the tester most needs it to be right.
        """
        with self._lock:
            entry = self._open.get(recording_id)
        return entry[1] if entry is not None else None


__all__ = ["ConfirmGate"]
