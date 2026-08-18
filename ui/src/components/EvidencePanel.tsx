/**
 * The right pane: evidence, and why this step says what it says (SS13.3).
 *
 *   "A tester who sees *the tool went and looked, and here is what it found*
 *    accepts the output. A confident sentence with no provenance gets doubted."
 *
 * It does double duty: trust for the tester, and the agency evidence of SS3
 * rendered for a human instead of for a script. The retrieval itself is
 * fetchable -- not a summary of it -- because the claim being auditable per
 * sentence is the product.
 */

import { useState } from 'react';
import { api, type Investigation, type Step, type Trace } from '../api';

const STAGE_LABEL: Record<string, string> = {
  name: 'Writing the step',
  assert: 'Choosing the expected result',
  decompose: 'Composing the document',
};

export function EvidencePanel({
  step,
  trace,
  feature,
  recordingId,
  runId,
}: {
  step: Step | undefined;
  trace: Trace | null;
  feature: string;
  recordingId: string;
  runId: string;
}) {
  const [tab, setTab] = useState<'why' | 'feature'>('why');

  const investigations = (trace?.investigations ?? []).filter(
    (i) => step && i.stepId === step.id,
  );

  return (
    <aside className="evidence">
      <div className="tabs">
        <button className={tab === 'why' ? 'on' : ''} onClick={() => setTab('why')}>
          Why this step
        </button>
        <button className={tab === 'feature' ? 'on' : ''} onClick={() => setTab('feature')}>
          Feature file
        </button>
      </div>

      {tab === 'feature' ? (
        <pre className="feature">{feature}</pre>
      ) : !step ? (
        <p className="muted">Select a step.</p>
      ) : (
        <>
          <h3>Grounding</h3>
          {step.assertions.length === 0 ? (
            <p className="muted">This step claims nothing, so there is nothing to ground.</p>
          ) : (
            <ul className="grounding">
              {step.assertions.map((a) => (
                <li key={a.id}>
                  <code>{a.evidence.literal}</code>
                  <Retrieval
                    recordingId={recordingId}
                    runId={runId}
                    toolCallId={a.evidence.toolCallId}
                    trace={trace}
                  />
                </li>
              ))}
            </ul>
          )}

          <h3>What the agent did</h3>
          {investigations.length === 0 ? (
            <p className="muted">No investigation was recorded for this step.</p>
          ) : (
            investigations.map((investigation) => (
              <Narrative key={investigation.id} investigation={investigation} />
            ))
          )}

          <h3>Events</h3>
          <p className="ids">{step.eventIds.join(', ')}</p>

          {step.selectorHints && step.selectorHints.length > 0 && (
            <>
              <h3>Selectors</h3>
              <ul className="ids">
                {step.selectorHints.map((hint) => (
                  <li key={hint.value}>
                    <code>{hint.strategy}</code> {hint.value}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </aside>
  );
}

function Narrative({ investigation }: { investigation: Investigation }) {
  return (
    <div className="narrative">
      <h4>{STAGE_LABEL[investigation.stage] ?? investigation.stage}</h4>
      {investigation.initialUncertainty.length > 0 && (
        <>
          <p className="muted">Could not determine up front:</p>
          <ul>
            {investigation.initialUncertainty.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </>
      )}
      <ol className="trail">
        {(investigation.narrative ?? []).map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ol>
      <p className="muted">
        Stopped: <code>{investigation.stopReason}</code> after {investigation.budgetUsed} of{' '}
        {investigation.budgetMax} retrievals.
      </p>
    </div>
  );
}

function Retrieval({
  recordingId,
  runId,
  toolCallId,
  trace,
}: {
  recordingId: string;
  runId: string;
  toolCallId: string;
  trace: Trace | null;
}) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  const call = trace?.toolCalls.find((c) => c.id === toolCallId);

  const show = async () => {
    setOpen(!open);
    if (payload || open) return;
    try {
      setPayload(await api.toolResponse(recordingId, runId, toolCallId));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="retrieval">
      <button className="link" onClick={show}>
        {open ? '▾' : '▸'} {call ? `${call.tool}(…)` : toolCallId}
      </button>
      {open &&
        (error ? (
          <p className="error">{error}</p>
        ) : (
          <pre>{payload ? JSON.stringify(payload, null, 2) : 'loading…'}</pre>
        ))}
    </div>
  );
}
