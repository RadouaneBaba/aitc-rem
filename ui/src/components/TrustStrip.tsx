/**
 * How much of this run can be trusted, in one line.
 *
 * `trace.metrics` and `trace.validatorResults` were already in every run body
 * the API sent and were rendered NOWHERE. A reviewer opening a draft could see
 * the sentences but not whether the gate had passed on them, which is the one
 * thing that separates this tool from a model writing plausible prose (SS13.3).
 *
 * **Nothing here is shown unless it can move.** A grounding rate reads 1.0 for a
 * run that claimed nothing, so the count of expected results comes first and the
 * rate qualifies it; a run with no expected results says so in words instead of
 * showing 100%. The "N checks passed" badge is gone for the same reason and it
 * is the sharper case: all five validators pass on every run on disk and the
 * grounding script reports 100%, while the judge raised three `fail`s on the one
 * real commercial session. A badge that can only ever say green is not a trust
 * signal, it is decoration that looks like one -- and this project has now met
 * that trap in seven columns, so assume it is in the next one too.
 */

import { useState } from 'react';
import type { Trace } from '../api';

export function TrustStrip({ trace }: { trace: Trace | null }) {
  const [open, setOpen] = useState(false);
  if (!trace) return null;

  const results = trace.validatorResults ?? [];
  const failed = results.filter((r) => r.status === 'fail');
  const warned = results.filter((r) => r.status === 'warn');
  const notable = [...failed, ...warned];

  const assertions = trace.metrics?.assertionsTotal ?? 0;
  const grounded = trace.metrics?.groundingRate;
  const judgeFindings = trace.metrics?.judgeFindings ?? 0;
  const judgeFails = trace.metrics?.judgeFails ?? 0;

  return (
    <div className={`trust ${failed.length ? 'bad' : warned.length ? 'warn' : 'ok'}`}>
      <span className="trust-headline">
        {assertions === 0 ? (
          // Not a score. A run that checked nothing cannot be trusted OR
          // distrusted, and saying "100% grounded" here would be a lie of
          // omission dressed as a metric.
          <strong>This run makes no checks.</strong>
        ) : (
          <>
            <strong>
              {assertions} expected result{assertions === 1 ? '' : 's'}
            </strong>
            {grounded !== undefined && (
              <>
                , {grounded >= 1 ? 'each' : `${Math.round(grounded * 100)}%`} traced back to
                something the tool retrieved
              </>
            )}
          </>
        )}
      </span>

      <span className="spacer" />

      <span className="trust-gates">
        {/* "N checks passed" used to live here and it is deliberately gone.
            All five validators pass on every run on disk and the grounding
            script reports 100%, while the judge raised three `fail`s on the one
            real commercial session -- so the count could only ever say green,
            and a badge that cannot move is a trust signal that carries no
            information. The checks stay; they cost nothing and cannot be wrong.
            What is shown instead is every number that CAN move. */}
        {warned.length > 0 && <span className="badge warn">{warned.length} warnings</span>}
        {failed.length > 0 && <span className="badge bad">{failed.length} rejected</span>}
        {judgeFindings > 0 && (
          <span className={`badge ${judgeFails > 0 ? 'bad' : 'warn'}`}>
            {judgeFails > 0
              ? `${judgeFails} a QA lead would send back`
              : `${judgeFindings} note${judgeFindings === 1 ? '' : 's'} from the QA read`}
          </span>
        )}
        {trace.metrics?.toolCallsTotal !== undefined && (
          <span className="muted">{trace.metrics.toolCallsTotal} retrievals</span>
        )}
      </span>

      {notable.length > 0 && (
        <button className="linkish" onClick={() => setOpen(!open)}>
          {open ? 'hide' : 'what was flagged'}
        </button>
      )}

      {open && (
        <ul className="trust-detail">
          {notable.map((r, i) => (
            <li key={`${r.validator}-${i}`} className={r.status}>
              <code>{r.validator}</code> {r.message}
              {r.stepId && <span className="muted"> ({r.stepId})</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
