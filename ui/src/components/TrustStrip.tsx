/**
 * How much of this run can be trusted, in one line.
 *
 * `trace.metrics` and `trace.validatorResults` were already in every run body
 * the API sent and were rendered NOWHERE. A reviewer opening a draft could see
 * the sentences but not whether fourteen validators had passed on them, which
 * is the one thing that separates this tool from a model writing plausible
 * prose (SS13.3).
 *
 * **A grounding rate is never shown on its own.** It reads 1.0 for a run that
 * claimed nothing, which is the trap this project has now met in five columns,
 * so the count of expected results comes first and the rate qualifies it. A
 * run with no expected results says so in words instead of showing 100%.
 */

import { useState } from 'react';
import type { Trace } from '../api';

export function TrustStrip({ trace }: { trace: Trace | null }) {
  const [open, setOpen] = useState(false);
  if (!trace) return null;

  const results = trace.validatorResults ?? [];
  const failed = results.filter((r) => r.status === 'fail');
  const warned = results.filter((r) => r.status === 'warn');
  const passed = results.filter((r) => r.status === 'pass');
  const notable = [...failed, ...warned];

  const assertions = trace.metrics?.assertionsTotal ?? 0;
  const grounded = trace.metrics?.groundingRate;

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
        {passed.length > 0 && <span className="badge ok">{passed.length} checks passed</span>}
        {warned.length > 0 && <span className="badge warn">{warned.length} warnings</span>}
        {failed.length > 0 && <span className="badge bad">{failed.length} rejected</span>}
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
