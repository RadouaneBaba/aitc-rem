/**
 * The right pane: one step, and everything about it.
 *
 * It used to be the middle of three, and the two things a reviewer needs most
 * were somewhere else -- the picture of the page was a 220px thumbnail, and
 * what the sentence was checked against lived in a separate pane behind a
 * disclosure triangle. The third pane is gone and both are here.
 *
 * Accept/reject is the core loop and must take seconds, so the candidates are
 * still checkboxes and nothing else. Each carries its provenance, its predicate
 * and its literal, because "the tester pointed at this" and "the agent worked
 * it out" are different claims, and "the first product is X" and "X is on the
 * page" are different claims too.
 */

import { useEffect, useState } from 'react';
import type { Assertion, JudgeFinding, Step, Trace } from '../api';
import { fidelityCopy } from '../fidelity';
import { Screenshot } from './Screenshot';
import { PredicateLabel, Retrieval } from './Evidence';
import { Narration } from './Narration';

const PROVENANCE_HINT: Record<string, string> = {
  annotated: 'you marked this element while recording',
  narrated: 'you said this out loud while recording',
  objective: 'taken from the objective you stated before recording',
  inferred: 'the tool worked this out from what changed',
  confirmed: 'you confirmed this when you answered the question',
};

export function StepDetail({
  step,
  recordingId,
  runId,
  trace,
  screens,
  findings,
  busy,
  onEdit,
  onDelete,
  onAssertion,
  onRewordAssertion,
  onAnswer,
}: {
  step: Step;
  recordingId: string;
  runId: string;
  trace: Trace | null;
  screens: string[];
  findings: JudgeFinding[];
  busy: boolean;
  onEdit: (text: string) => void;
  onDelete: () => void;
  onAssertion: (id: string, accepted: boolean) => void;
  onRewordAssertion: (id: string, text: string) => void;
  onAnswer: (answer: string) => void;
}) {
  const [draft, setDraft] = useState(step.text);
  useEffect(() => setDraft(step.text), [step.id, step.text]);
  const dirty = draft !== step.text;

  const mine = findings.filter((f) => f.stepId === step.id);

  return (
    <section className="detail">
      <div className="detail-head">
        <span className="keyword-lg">{step.keyword}</span>
        {step.role && <span className="role">{step.role.replace(/_/g, ' ')}</span>}
        {step.confidence !== 'high' && (
          <span className={`confidence ${step.confidence}`}>{step.confidence} confidence</span>
        )}
        <div className="spacer" />
        {/* Confirmed, because deleting a step is not undoable from here and the
            control sits a click away from the text you were editing. */}
        <button
          className="ghost danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Delete this step?\n\n${step.text}\n\nThis cannot be undone here.`))
              onDelete();
          }}
        >
          Delete step
        </button>
      </div>

      {/* Save is explicit, and this is a data-loss fix rather than a style
          preference. It used to commit on blur with no dirty state and no undo
          -- and only when the text had changed AND was non-empty, so clearing
          the field to retype it discarded the edit silently, looking exactly
          like a save. A reviewer's wording is the one thing here no re-run can
          reproduce. */}
      <textarea
        className="steptext"
        id="step-text"
        value={draft}
        rows={2}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            setDraft(step.text);
          }
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && dirty && draft.trim()) {
            onEdit(draft);
          }
        }}
      />
      <div className="editbar">
        {dirty ? (
          <>
            <button className="primary" disabled={busy || !draft.trim()} onClick={() => onEdit(draft)}>
              Save
            </button>
            <button disabled={busy} onClick={() => setDraft(step.text)}>
              Cancel
            </button>
            <span className="muted">
              {draft.trim() ? 'Unsaved — ⌘↵ to save, Esc to revert.' : 'A step cannot be empty.'}
            </span>
          </>
        ) : (
          <span className="muted">The wording is yours to change.</span>
        )}
      </div>

      <Screenshot recordingId={recordingId} eventIds={step.eventIds} screens={screens} />

      {step.escalation && <Escalation question={step.escalation} busy={busy} onAnswer={onAnswer} />}

      <section className="block">
        <h3 className="eyebrow">Expected result</h3>
        {step.assertions.length === 0 && step.whyNot ? (
          // The author tried, could not, and said why. That is a different fact
          // from "this step is just an action", and printing the generic line
          // over it threw away the most useful sentence in the run: a reviewer
          // who knows the product list was never captured can act on it, where
          // "nothing to check here" invites them to move on.
          //
          // Not styled as a warning. A refusal is the designed outcome when the
          // recording does not contain a verdict, and a visible gap beats an
          // invisible falsehood.
          <p className="whynot">
            <strong>No check here.</strong> {step.whyNot}
          </p>
        ) : step.assertions.length === 0 ? (
          <p className="muted">Nothing to check — this step is an action.</p>
        ) : (
          <ul className="assertions">
            {step.assertions.map((assertion) => (
              <Candidate
                key={assertion.id}
                assertion={assertion}
                recordingId={recordingId}
                runId={runId}
                trace={trace}
                busy={busy}
                onToggle={(accepted) => onAssertion(assertion.id, accepted)}
                onReword={(text) => onRewordAssertion(assertion.id, text)}
              />
            ))}
          </ul>
        )}
      </section>

      {/* The judge, on the step it is about.
          Every validator passes the documents this catches -- the gate confirms
          a literal came back from a retrieval, and nothing confirmed the
          SENTENCE was about the literal. These sentences have been written to
          `judge.json` on every run since the judge landed and reached nobody. */}
      {mine.length > 0 && (
        <section className="block">
          <h3 className="eyebrow">What a QA lead would send back</h3>
          <ul className="findings">
            {mine.map((finding, i) => (
              <li key={`${finding.check}-${i}`} className={finding.severity}>
                <span className={`chip ${finding.severity === 'fail' ? 'chip-bad' : 'chip-warn'}`}>
                  {finding.severity === 'fail' ? 'would not sign' : 'would sign after an edit'}
                </span>
                <p>{finding.what}</p>
                {finding.fix && (
                  <p className="fix">
                    <strong>Fix</strong> — {finding.fix}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <Narration step={step} recordingId={recordingId} runId={runId} />

      {step.fidelity.length > 0 && (
        <section className="block">
          {/* The spec wrote this copy sentence by sentence and the UI shipped
              the enum -- `rapid_sequence`, in a monospace font, to a QA tester.
              "A tool that admits what it doesn't know stays trusted" only works
              if the admission is in a language the reader speaks. */}
          <h3 className="eyebrow">What the recorder could not be sure of</h3>
          <ul className="fidelity">
            {step.fidelity.map((flag) => {
              const copy = fidelityCopy(flag);
              return (
                <li key={flag} className={copy.severity}>
                  {copy.text}
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </section>
  );
}

function Candidate({
  assertion,
  recordingId,
  runId,
  trace,
  busy,
  onToggle,
  onReword,
}: {
  assertion: Assertion;
  recordingId: string;
  runId: string;
  trace: Trace | null;
  busy: boolean;
  onToggle: (accepted: boolean) => void;
  onReword: (text: string) => void;
}) {
  // Most steps get exactly one candidate, which is the right answer -- inventing
  // a second for a step with one obvious outcome manufactures the weak claim the
  // ranking exists to demote. But it leaves one checkbox, and rejecting it
  // leaves the step with no expected result at all. So the sentence is editable.
  // The literal below it is not: rewording is the reviewer's, grounding is not.
  const [draft, setDraft] = useState<string | null>(null);

  const commit = () => {
    const next = (draft ?? '').trim();
    setDraft(null);
    if (next && next !== assertion.text) onReword(next);
  };

  return (
    <li className={assertion.accepted ? 'accepted' : ''}>
      <label>
        <input
          type="checkbox"
          checked={assertion.accepted}
          disabled={busy}
          onChange={(e) => onToggle(e.target.checked)}
        />
        {draft === null ? (
          <span
            className="text"
            title="click to reword — the evidence below stays as it is"
            onClick={() => setDraft(assertion.text)}
          >
            {assertion.text}
          </span>
        ) : (
          <input
            className="text-edit"
            autoFocus
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit();
              if (e.key === 'Escape') setDraft(null);
            }}
          />
        )}
      </label>

      {/* Three lines, and then it stops. What kind of claim this is, the exact
          value it was checked against, and where that value came from. */}
      <div className="proof">
        <span
          className={`provenance ${assertion.provenance}`}
          title={PROVENANCE_HINT[assertion.provenance]}
        >
          {assertion.provenance}
        </span>
        <PredicateLabel predicate={assertion.evidence.predicate} />
        <code className="literal" title="the exact text a retrieval returned">
          {assertion.evidence.literal}
        </code>
        <span className="muted at-event">at {assertion.evidence.eventId}</span>
      </div>

      <Retrieval
        recordingId={recordingId}
        runId={runId}
        toolCallId={assertion.evidence.toolCallId}
        trace={trace}
      />
    </li>
  );
}

function Escalation({
  question,
  busy,
  onAnswer,
}: {
  question: string;
  busy: boolean;
  onAnswer: (answer: string) => void;
}) {
  const [answer, setAnswer] = useState('');

  // An agent that says "I cannot tell whether the export succeeded" is more
  // useful than one that guesses, and this is where that pays off: the question
  // is rendered as a question, next to the step.
  return (
    <div className="escalation">
      <p>
        <strong>The tool could not tell:</strong> {question}
      </p>
      <div className="row">
        <input
          value={answer}
          disabled={busy}
          placeholder="Answer, and this becomes confirmed rather than inferred"
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && answer.trim()) onAnswer(answer);
          }}
        />
        <button className="primary" disabled={busy || !answer.trim()} onClick={() => onAnswer(answer)}>
          Answer
        </button>
      </div>
    </div>
  );
}
