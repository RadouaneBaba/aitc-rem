/**
 * The left pane: test cases and their steps (SS13.1).
 *
 * A step that needs a human is visually distinct and never hidden (SS13.4), and
 * omitted work is shown as an expandable marker rather than deleted -- a
 * verbatim transcript is unusable and a silent deletion is untrustworthy
 * (SS9.3).
 */

import { useState } from 'react';
import type { Step, TestCase } from '../api';

export function StepList({
  testCases,
  selectedId,
  onSelect,
  edited,
  onRename,
  onMerge,
  busy,
}: {
  testCases: TestCase[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  edited: Set<string>;
  onRename: (caseId: string, patch: { title?: string; scenarioName?: string }) => void;
  onMerge: (stepIds: string[]) => void;
  busy: boolean;
}) {
  const [picked, setPicked] = useState<string[]>([]);

  const toggle = (id: string) =>
    setPicked((current) =>
      current.includes(id) ? current.filter((s) => s !== id) : [...current, id],
    );

  return (
    <nav className="steplist">
      {testCases.map((testCase) => (
        <section key={testCase.id}>
          <EditableTitle
            value={testCase.scenarioName || testCase.title}
            onSave={(scenarioName) => onRename(testCase.id, { scenarioName })}
          />
          <p className="muted feature-name">{testCase.title}</p>

          <ol>
            {testCase.steps.map((step, index) => (
              <li
                key={step.id}
                className={[
                  step.id === selectedId ? 'selected' : '',
                  needsReview(step) ? 'attention' : '',
                ].join(' ')}
              >
                <input
                  type="checkbox"
                  checked={picked.includes(step.id)}
                  onChange={() => toggle(step.id)}
                  title="select to merge"
                  aria-label={`select step ${index + 1} to merge`}
                />
                <button onClick={() => onSelect(step.id)}>
                  <span className="keyword">{step.keyword}</span> {step.text}
                  {step.escalation && <span className="flag" title={step.escalation}>?</span>}
                  {step.confidence === 'low' && <span className="flag" title="low confidence">!</span>}
                  {edited.has(step.id) && <span className="edited" title="you edited this">·</span>}
                </button>
              </li>
            ))}
          </ol>

          {picked.length > 1 && (
            <button
              className="merge"
              disabled={busy}
              onClick={() => {
                onMerge(picked);
                setPicked([]);
              }}
            >
              Merge {picked.length} steps
            </button>
          )}

          {testCase.omitted.length > 0 && <Omitted testCase={testCase} />}
        </section>
      ))}
    </nav>
  );
}

function needsReview(step: Step): boolean {
  return Boolean(step.escalation) || step.confidence === 'low';
}

function EditableTitle({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  if (!editing) {
    return (
      <h2 onDoubleClick={() => { setDraft(value); setEditing(true); }} title="double-click to rename">
        {value}
      </h2>
    );
  }
  return (
    <input
      className="titleedit"
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => { setEditing(false); if (draft.trim() && draft !== value) onSave(draft); }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
        if (e.key === 'Escape') { setDraft(value); setEditing(false); }
      }}
    />
  );
}

function Omitted({ testCase }: { testCase: TestCase }) {
  const [open, setOpen] = useState(false);
  const total = testCase.omitted.reduce((sum, o) => sum + o.eventCount, 0);

  return (
    <div className="omitted">
      <button className="link" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {total} action(s) omitted
      </button>
      {open && (
        <ul>
          {testCase.omitted.map((o) => (
            <li key={o.segmentId}>
              <em>{o.reason}</em> — {o.summary}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
