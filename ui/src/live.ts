/**
 * The two things on this screen that change without the reviewer doing
 * anything: a run in flight, and guesses nobody has answered.
 *
 * Both used to be full-width banners of their own, stacked above a third
 * (the trust strip), so on a 900px laptop 175px of a 900px viewport was chrome
 * before any content. They carry one sentence each. They are hooks now, and
 * `StatusLine` renders them as chips on the single bar that replaced all three.
 *
 * The polling behaviour is unchanged, deliberately -- both were correct.
 */

import { useEffect, useState } from 'react';
import { api, type Job, type PendingConfirmation } from './api';

/** Slow enough not to hammer a local server, fast enough that a stage change
 *  shows up while somebody is watching for it. */
const POLL_MS = 2500;

const ACTIVE = new Set(['queued', 'running']);

/**
 * A run takes minutes on purpose -- that is the permissive constraint which
 * buys multi-pass analysis and retrieval. But "deliberately slow" and "crashed"
 * look identical from a browser tab, and the second thing a tester does when a
 * tab looks stuck is press Stop again and record the session twice.
 *
 * Failures stay visible after they settle. A job that died silently is the
 * thing that makes somebody stop trusting the tool.
 */
export function useJobs(onFinished: () => void): Job[] {
  const [jobs, setJobs] = useState<Job[]>([]);

  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    // Remembered across polls so the transition to `done` fires the refresh
    // exactly once, rather than on every tick that follows it.
    let running = new Set<string>();

    const tick = async () => {
      try {
        const { jobs: next } = await api.jobs();
        if (!live) return;
        setJobs(next);

        const active = new Set(next.filter((j) => ACTIVE.has(j.state)).map((j) => j.id));
        const settled = [...running].some((id) => !active.has(id));
        running = active;
        if (settled) onFinished();
      } catch {
        // A poll that fails is not worth an error banner: the next one is 2.5s
        // away and the page is perfectly usable meanwhile.
      }
      if (live) timer = window.setTimeout(tick, POLL_MS);
    };

    void tick();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [onFinished]);

  return jobs.filter((j) => ACTIVE.has(j.state) || j.state === 'failed');
}

/**
 * Recordings whose guesses nobody has answered.
 *
 * The number this exists for: 14 expectation sets reached disk and all 14
 * stayed `inferred`, because the confirmation screen opened only on a query
 * parameter read once at mount. Everything downstream had therefore only ever
 * read guesses nobody checked.
 *
 * Never blocking and never a modal. The draft already exists, built on the
 * guesses alone; this is an invitation on a page they are already on.
 */
export function usePending(): [PendingConfirmation[], (recordingId: string) => void] {
  const [pending, setPending] = useState<PendingConfirmation[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Polled, on the same clock as the jobs.
  //
  // This used to fetch once at mount, which meant the invitation only ever
  // appeared for recordings that were already pending when the tab was opened.
  // The common path is the opposite: the tester presses Stop, the run lands
  // while they are watching this screen, and the guesses it just made were
  // exactly the thing to ask them about -- and nothing appeared until they
  // reloaded. It also went stale in the other direction, staying on screen
  // after the confirmation screen had been answered.
  useEffect(() => {
    let live = true;
    let timer = 0;

    const tick = () => {
      api
        .pendingExpectations()
        .then(({ pending: next }) => live && setPending(next))
        // Silent: an unanswered guess is not an error, and a red bar about a
        // failed poll on top of the review screen helps nobody.
        .catch(() => undefined)
        .finally(() => {
          if (live) timer = window.setTimeout(tick, POLL_MS);
        });
    };
    tick();

    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, []);

  // Dismissing hides a row for this visit only. It is not an answer, and
  // storing it as one would turn "I am busy" into "the guess was right" --
  // the one direction the expectations file must never move.
  const dismiss = (recordingId: string) =>
    setDismissed((was) => new Set(was).add(recordingId));

  return [pending.filter((row) => !dismissed.has(row.recordingId)), dismiss];
}
