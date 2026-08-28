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

import { useEffect, useState } from 'react';
import { api, type Investigation, type Step, type StepNarration, type Trace } from '../api';

const STAGE_LABEL: Record<string, string> = {
  decompose: 'Writing the test case',
  assert: 'Proving the expected result',
  name: 'Rewriting this step after review',
  critic: 'Reading it back',
  coverage: 'Looking for what was not covered',
};

export function EvidencePanel({
  step,
  trace,
  feature,
  recordingId,
  runId,
  busy,
  onEditFeature,
}: {
  step: Step | undefined;
  trace: Trace | null;
  feature: string;
  recordingId: string;
  runId: string;
  busy: boolean;
  onEditFeature: (text: string) => void;
}) {
  // The feature file first, and the change is the whole of this screen's
  // posture. A reviewer opening a run was landed on the retrieval chain --
  // tool calls, budgets, investigation records -- which is the pipeline's
  // insides and serves whoever is auditing the tool. The tester is here to
  // read what came out of their own session; that is also what the tool is
  // judged on. The proof is one click away rather than in their face.
  const [tab, setTab] = useState<'why' | 'feature'>('feature');

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
        <FeatureEditor text={feature} busy={busy} onSave={onEditFeature} />
      ) : !step ? (
        <p className="muted">Select a step.</p>
      ) : (
        <>
          {/* SS13.3 asks this panel to do "trust AND proof, both
              load-bearing". Only one of those is load-bearing for a TESTER:
              trust comes from the output being right, which they judge by
              reading it. The proof half serves whoever is auditing the tool.
              So the sentence is what shows, and the retrieval chain is one
              click away rather than in their face. */}
          <h3>Why this is here</h3>
          {step.assertions.length === 0 ? (
            <p className="muted">This step claims nothing, so there is nothing to ground.</p>
          ) : (
            <ul className="grounding">
              {step.assertions.map((a) => (
                <li key={a.id}>
                  <p className="grounding-sentence">
                    &ldquo;{a.evidence.literal}&rdquo; was in the recording at{' '}
                    {a.evidence.eventId}.
                  </p>
                  <details>
                    <summary className="muted">Show the retrieval that found it</summary>
                    <Retrieval
                      recordingId={recordingId}
                      runId={runId}
                      toolCallId={a.evidence.toolCallId}
                      trace={trace}
                    />
                  </details>
                </li>
              ))}
            </ul>
          )}

          <Narration step={step} recordingId={recordingId} runId={runId} />

          <details className="telemetry">
            <summary className="muted">What the tool did to work this out</summary>
            {investigations.length === 0 ? (
              <p className="muted">
                Nothing needed looking up for this step. That is the usual answer, and a good
                one.
              </p>
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
          </details>
        </>
      )}
    </aside>
  );
}

/**
 * The feature file, editable (SS13.2).
 *
 * This tab used to display the file and nothing else, so fixing a sentence
 * meant finding its step in the list and using a form. The justification was
 * SS13.5's review record -- and it does not hold, because a diff between the
 * generated file and the approved one yields exactly the same difficulty
 * labels. What the server does with the text is replay it through the same
 * review functions the forms call, so the record is identical either way.
 *
 * Structure is not editable here and the server says so plainly rather than
 * silently ignoring it: a step typed into this box has no recorded actions
 * behind it, and `event_coverage` would reject the run.
 */
function FeatureEditor({
  text,
  busy,
  onSave,
}: {
  text: string;
  busy: boolean;
  onSave: (next: string) => void;
}) {
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);

  const dirty = draft !== text;
  return (
    <div className="featureedit">
      <textarea
        className="feature"
        value={draft}
        spellCheck={false}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="featureedit-actions">
        <span className="muted">
          {dirty ? 'Unsaved changes' : 'Edit the wording here; use the step list to add or remove.'}
        </span>
        <div className="spacer" />
        {dirty && (
          <button disabled={busy} onClick={() => setDraft(text)}>
            Revert
          </button>
        )}
        <button className="primary" disabled={busy || !dirty} onClick={() => onSave(draft)}>
          Save
        </button>
      </div>
    </div>
  );
}

/**
 * SS6.6, SS13.3 -- what the tester said, and the clip that proves it.
 *
 * Narration is the only LOSSY evidence source in this tool. A snapshot node
 * name, a URL, a response body are read exactly; a transcript is a
 * reconstruction. So a mis-heard number becomes a literal that passes
 * `evidence_retrieved` (the string really is in the stored response) AND
 * `assertion_grounding` (it really is in the index) and is still false. No
 * automatic check catches that, and `runners/playwright.py` says so outright by
 * marking narration `not_checkable`.
 *
 * A person listening is the check. That is the entire reason the audio is kept
 * rather than discarded after transcription, and this panel is where it pays
 * for itself.
 */
function Narration({
  step,
  recordingId,
  runId,
}: {
  step: Step;
  recordingId: string;
  runId: string;
}) {
  const [narration, setNarration] = useState<StepNarration | null>(null);

  useEffect(() => {
    let live = true;
    setNarration(null);
    api
      .stepNarration(recordingId, runId, step.id)
      .then((body) => live && setNarration(body))
      // A recording made before narration existed has no endpoint answer worth
      // showing. Silence is right: this is evidence, not a status bar.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [recordingId, runId, step.id]);

  if (!narration?.segments.length) return null;

  return (
    <>
      <h3>What the tester said</h3>
      <ul className="spoken">
        {narration.segments.map((segment) => (
          <li key={segment.id} className={segment.supportsRank ? undefined : 'unsure'}>
            <span className="at">{(segment.startMs / 1000).toFixed(1)}s</span>
            <q>{segment.text}</q>
            {!segment.supportsRank && (
              <em title="A transcription nobody trusts must not outrank an honest inference.">
                too unclear to rank an expected result
              </em>
            )}
          </li>
        ))}
      </ul>
      {narration.hasAudio && (
        <audio
          controls
          preload="none"
          src={api.audioUrl(recordingId)}
          // Seeked to the first thing said in this step, because scrubbing a
          // fifteen-minute session to find one sentence is not a check anybody
          // performs twice.
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = narration.segments[0]!.startMs / 1000;
          }}
        />
      )}
      <p className="muted small">
        Transcribed, not read. If a number here is wrong, the expected result built on it is
        wrong too — reject it, or reword it.
      </p>
    </>
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
