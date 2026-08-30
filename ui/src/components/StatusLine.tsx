/**
 * One bar, where there were three.
 *
 * The review screen stacked a job banner, a pending-confirmation banner and a
 * trust strip, each full width, each carrying one sentence: 175px of a 900px
 * laptop viewport spent before the first step. All three are here now, as the
 * left half of a single line, with the pane switch on the right.
 *
 * **Nothing is shown unless it can move.** A grounding rate reads 1.0 for a run
 * that claimed nothing, so the count of expected results comes first and the
 * rate qualifies it. The "N checks passed" badge is gone and stays gone: all
 * five validators pass on every run on disk while the judge raised three fails
 * on the one real commercial session, so that badge could only ever say green.
 * A signal that cannot move is decoration that looks like a signal.
 */

import type { Job, Judgement, PendingConfirmation, Trace } from '../api';

export type Pane = 'step' | 'feature' | 'notcovered';

export function StatusLine({
  trace,
  judgement,
  jobs,
  pending,
  recordingId,
  onOpenConfirm,
  onDismissConfirm,
  pane,
  onPane,
  onShowFlagged,
}: {
  trace: Trace | null;
  judgement: Judgement | null;
  jobs: Job[];
  pending: PendingConfirmation[];
  /** The run on screen, so the pending chip can say when it means another one. */
  recordingId: string | undefined;
  onOpenConfirm: (recordingId: string) => void;
  onDismissConfirm: (recordingId: string) => void;
  pane: Pane;
  onPane: (pane: Pane) => void;
  onShowFlagged: () => void;
}) {
  const assertions = trace?.metrics?.assertionsTotal ?? 0;
  const grounded = trace?.metrics?.groundingRate;
  const retrievals = trace?.metrics?.toolCallsTotal;
  const fails = (judgement?.findings ?? []).filter((f) => f.severity === 'fail').length;

  const job = jobs[0];
  const [firstPending] = pending;

  return (
    <div className="statusline">
      <div className="status-facts">
        {assertions === 0 ? (
          // Not a score. A run that checked nothing can be neither trusted nor
          // distrusted, and "100% grounded" here would be a lie of omission
          // wearing a metric's clothes.
          <span className="status-fact">
            <b>No checks</b> in this run
          </span>
        ) : (
          <span className="status-fact">
            <b>
              {assertions} check{assertions === 1 ? '' : 's'}
            </b>
            {grounded !== undefined && grounded < 1 && (
              <> · {Math.round(grounded * 100)}% traced back to a retrieval</>
            )}
          </span>
        )}

        {retrievals !== undefined && (
          <span className="status-fact muted">{retrievals} retrievals</span>
        )}

        {fails > 0 && (
          <button className="chip chip-bad" onClick={onShowFlagged}>
            {fails} to fix
          </button>
        )}
      </div>

      <div className="status-live">
        {job && (
          <span className={`chip ${job.state === 'failed' ? 'chip-bad' : 'chip-work'}`}>
            {job.state === 'failed' ? 'Run failed' : 'Working'}
            <span className="chip-note">{job.error ?? job.detail}</span>
          </span>
        )}

        {/* Which recording, said out loud.
            `GET /api/expectations/pending` is a GLOBAL list, so the newest
            unanswered recording is very often not the one on screen -- while
            reviewing the coffee session this invited the reader to answer the
            checkout session's guesses, with nothing naming either. A prompt
            that silently changes subject reads as a bug, and was reported as
            one. */}
        {firstPending && (
          <span className="chip chip-warn">
            {firstPending.count} unanswered guess{firstPending.count === 1 ? '' : 'es'}
            {firstPending.recordingId !== recordingId && (
              <span className="chip-note">on {firstPending.recordingId}</span>
            )}
            <button className="chip-action" onClick={() => onOpenConfirm(firstPending.recordingId)}>
              Check them
            </button>
            <button
              className="chip-x"
              title="Hide until the next reload"
              aria-label="Hide until the next reload"
              onClick={() => onDismissConfirm(firstPending.recordingId)}
            >
              ×
            </button>
          </span>
        )}
      </div>

      {/* The pane switch. The feature file is a MODE rather than a rail,
          because it is the artifact the whole tool is judged on and it was
          being rendered in a 30% column that clipped it mid-sentence. */}
      <div className="segmented" role="tablist" aria-label="What to show">
        <button role="tab" aria-selected={pane === 'step'} onClick={() => onPane('step')}>
          Steps
        </button>
        <button role="tab" aria-selected={pane === 'feature'} onClick={() => onPane('feature')}>
          Feature file
        </button>
      </div>
    </div>
  );
}
