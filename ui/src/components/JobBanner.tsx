/**
 * What the pipeline is doing right now (SS9.11, SS13).
 *
 * A run takes minutes deliberately -- that is the permissive constraint which
 * buys multi-pass analysis, tool calls and a repair loop. But "deliberately
 * slow" and "crashed" look identical from a browser tab, and the second thing a
 * tester does when a tab looks stuck is press Stop again and record it twice.
 *
 * So this says which stage is running, and it says plainly that the waiting is
 * a free-tier rate limit rather than the tool struggling. A tester who knows
 * why they are waiting goes and does something else; one who does not, doubts
 * the tool.
 */

import { useEffect, useState } from 'react';
import { api, type Job } from '../api';

/** Slow enough not to hammer a local server, fast enough that a stage change shows up. */
const POLL_MS = 2500;

const ACTIVE = new Set(['queued', 'running']);

export function JobBanner({ onFinished }: { onFinished: () => void }) {
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
        // away, and the page is still perfectly usable meanwhile.
      }
      if (live) timer = window.setTimeout(tick, POLL_MS);
    };

    void tick();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [onFinished]);

  // Failures stay visible after they settle. A job that died silently is the
  // thing that makes someone stop trusting the tool (SS6.8's posture, applied
  // to the server rather than the recorder).
  const shown = jobs.filter((j) => ACTIVE.has(j.state) || j.state === 'failed');
  if (!shown.length) return null;

  return (
    <div className="jobbanner">
      {shown.map((job) => (
        <div key={job.id} className={`job job-${job.state}`}>
          <span className="job-state">
            {job.state === 'failed' ? 'Failed' : 'Working'}
          </span>
          <span className="job-detail">{job.detail}</span>
          {job.error ? <code className="job-error">{job.error}</code> : null}
          {ACTIVE.has(job.state) ? (
            <span className="muted job-note">
              A few minutes is normal &mdash; the free model tier allows five requests a
              minute and one recording needs about sixteen.
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}
