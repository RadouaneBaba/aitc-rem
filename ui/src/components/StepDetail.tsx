/**
 * The middle pane: the selected step (SS13.1).
 *
 * Accept/reject is the core loop and must take seconds, so the candidates are
 * checkboxes and nothing else. Each carries its provenance badge, because
 * "the tester pointed at this" and "the agent worked it out" are different
 * claims and SS9.5's whole ranking is about not confusing them.
 */

import { useEffect, useState } from 'react';
import type { Assertion, Step } from '../api';

const PROVENANCE_HINT: Record<string, string> = {
  annotated: 'the tester marked this element while recording',
  narrated: 'the tester said this out loud while recording',
  objective: 'taken from the objective stated before recording',
  inferred: 'the agent worked this out from what changed',
  confirmed: 'you confirmed this when you answered the question',
};

export function StepDetail({
  step,
  busy,
  onEdit,
  onDelete,
  onAssertion,
  onAnswer,
}: {
  step: Step;
  busy: boolean;
  onEdit: (text: string) => void;
  onDelete: () => void;
  onAssertion: (id: string, accepted: boolean) => void;
  onAnswer: (answer: string) => void;
}) {
  const [draft, setDraft] = useState(step.text);
  useEffect(() => setDraft(step.text), [step.id, step.text]);

  return (
    <section className="detail">
      <div className="keyword-row">
        <span className="keyword big">{step.keyword}</span>
        {step.role && <span className="role">{step.role}</span>}
        <span className={`confidence ${step.confidence}`}>{step.confidence} confidence</span>
        <div className="spacer" />
        <button className="danger" disabled={busy} onClick={onDelete}>
          Delete step
        </button>
      </div>

      <textarea
        className="steptext"
        value={draft}
        rows={2}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => draft.trim() && draft !== step.text && onEdit(draft)}
      />
      <p className="muted hint">
        The wording is yours to change. Click away to save.
      </p>

      {step.escalation && <Escalation question={step.escalation} busy={busy} onAnswer={onAnswer} />}

      <h3>Expected results</h3>
      {step.assertions.length === 0 ? (
        <p className="muted">
          Nothing to check here. Most steps are an action, and an omitted expected result is
          the right answer rather than a gap.
        </p>
      ) : (
        <ul className="assertions">
          {step.assertions.map((assertion) => (
            <Candidate
              key={assertion.id}
              assertion={assertion}
              busy={busy}
              onToggle={(accepted) => onAssertion(assertion.id, accepted)}
            />
          ))}
        </ul>
      )}

      {step.fidelity.length > 0 && (
        <>
          <h3>What the recorder could not determine</h3>
          <ul className="fidelity">
            {step.fidelity.map((flag) => (
              <li key={flag}>
                <code>{flag}</code>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Candidate({
  assertion,
  busy,
  onToggle,
}: {
  assertion: Assertion;
  busy: boolean;
  onToggle: (accepted: boolean) => void;
}) {
  return (
    <li className={assertion.accepted ? 'accepted' : ''}>
      <label>
        <input
          type="checkbox"
          checked={assertion.accepted}
          disabled={busy}
          onChange={(e) => onToggle(e.target.checked)}
        />
        <span className="text">{assertion.text}</span>
      </label>
      <div className="meta">
        <span
          className={`provenance ${assertion.provenance}`}
          title={PROVENANCE_HINT[assertion.provenance]}
        >
          {assertion.provenance}
        </span>
        <code className="literal" title="the exact string a retrieval returned">
          {assertion.evidence.literal}
        </code>
      </div>
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

  // SS3.3 -- an agent that says "I cannot tell whether the export succeeded" is
  // more useful than one that guesses, and this is where that pays off: the
  // question is rendered as a question, next to the step.
  return (
    <div className="escalation">
      <p>
        <strong>The agent could not tell:</strong> {question}
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
        <button disabled={busy || !answer.trim()} onClick={() => onAnswer(answer)}>
          Answer
        </button>
      </div>
    </div>
  );
}
