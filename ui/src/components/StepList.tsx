/**
 * The left rail: what is in this run, and which parts want a person.
 *
 * Two things changed and both were about prominence rather than information.
 *
 * **The merge checkbox is gone.** Every row carried one, so the rarest action
 * in the product had permanent visual priority over the action performed
 * constantly -- selecting a step. Range selection is shift-click now, and the
 * merge control appears only once there is something to merge.
 *
 * **A scenario reads as a scenario.** The heading and the step text used to sit
 * at the same size and weight, so a three-scenario run read as one long list.
 *
 * A step that needs a human is still visually distinct and still never hidden,
 * and omitted work is still shown as an expandable marker rather than deleted:
 * a verbatim transcript is unusable and a silent deletion is untrustworthy.
 */

import { useState } from 'react';
import type { JudgeFinding, Step, TestCase } from '../api';

export function StepList({
  testCases,
  selectedId,
  onSelect,
  edited,
  findings,
  onlyFlagged,
  onOnlyFlagged,
  suggestionCount,
  onOpenSuggestions,
  onRename,
  onMerge,
  busy,
}: {
  testCases: TestCase[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  edited: Set<string>;
  findings: JudgeFinding[];
  onlyFlagged: boolean;
  onOnlyFlagged: (on: boolean) => void;
  suggestionCount: number;
  onOpenSuggestions: () => void;
  onRename: (caseId: string, patch: { title?: string; scenarioName?: string }) => void;
  onMerge: (stepIds: string[]) => void;
  busy: boolean;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [anchor, setAnchor] = useState<string | null>(null);

  const failsFor = (stepId: string) =>
    findings.filter((f) => f.stepId === stepId && f.severity === 'fail').length;

  const wants = (step: Step) =>
    Boolean(step.escalation) || step.confidence === 'low' || failsFor(step.id) > 0;

  /** Shift-click extends from the last plain click, inside one scenario. Two
   *  steps in different scenarios cannot be merged, so offering it would be a
   *  selection the server has to refuse. */
  const click = (event: React.MouseEvent, testCase: TestCase, step: Step) => {
    if (!event.shiftKey) {
      setPicked([]);
      setAnchor(step.id);
      onSelect(step.id);
      return;
    }
    event.preventDefault();
    const ids = testCase.steps.map((s) => s.id);
    const from = ids.indexOf(anchor ?? step.id);
    const to = ids.indexOf(step.id);
    if (from < 0 || to < 0) return;
    setPicked(ids.slice(Math.min(from, to), Math.max(from, to) + 1));
  };

  return (
    <nav className="steplist" aria-label="Test cases and steps">
      {testCases.map((testCase) => {
        const shown = onlyFlagged ? testCase.steps.filter(wants) : testCase.steps;
        if (onlyFlagged && !shown.length) return null;

        return (
          <section key={testCase.id} className="scenario">
            <EditableTitle
              value={testCase.scenarioName || testCase.title}
              onSave={(scenarioName) => onRename(testCase.id, { scenarioName })}
            />

            {testCase.tags.length > 0 && (
              <div className="tagrow">
                {testCase.tags.map((tag) => (
                  <span key={tag} className="tag">
                    {tag}
                  </span>
                ))}
              </div>
            )}

            {/* A shared opening lifted into a Background. Without it on screen
                the second scenario reads as starting from nowhere -- its own
                steps begin partway through the flow. */}
            {(testCase.preconditions ?? []).length > 0 && (
              <div className="preconditions">
                <p className="railhead">Background</p>
                <ul>
                  {(testCase.preconditions ?? []).map((p) => (
                    <li key={p.id}>{p.text}</li>
                  ))}
                </ul>
              </div>
            )}

            <ol className="steps">
              {shown.map((step) => {
                const fails = failsFor(step.id);
                return (
                  <li
                    key={step.id}
                    className={[
                      'step',
                      step.id === selectedId ? 'selected' : '',
                      picked.includes(step.id) ? 'picked' : '',
                      wants(step) ? 'wants' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <button onClick={(event) => click(event, testCase, step)}>
                      <span className="keyword">{step.keyword}</span>
                      <span className="steptext-inline">{step.text}</span>
                      <span className="marks">
                        {fails > 0 && (
                          <span className="mark-fail" title={`${fails} to fix on this step`} />
                        )}
                        {step.escalation && (
                          <span className="mark-ask" title={step.escalation}>
                            ?
                          </span>
                        )}
                        {step.confidence === 'low' && (
                          <span className="mark-low" title="low confidence">
                            !
                          </span>
                        )}
                        {edited.has(step.id) && (
                          <span className="mark-edited" title="you edited this" />
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>

            {picked.length > 1 && picked.every((id) => testCase.steps.some((s) => s.id === id)) && (
              <div className="mergebar">
                <span>{picked.length} selected</span>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => {
                    onMerge(picked);
                    setPicked([]);
                  }}
                >
                  Merge
                </button>
                <button onClick={() => setPicked([])}>Cancel</button>
              </div>
            )}

            {testCase.omitted.length > 0 && <Omitted testCase={testCase} />}
          </section>
        );
      })}

      <div className="railfoot">
        <button
          className={`railitem${onlyFlagged ? ' on' : ''}`}
          onClick={() => onOnlyFlagged(!onlyFlagged)}
        >
          {onlyFlagged ? 'Showing only steps that want you' : 'Show only steps that want you'}
        </button>
        {suggestionCount > 0 && (
          <button className="railitem" onClick={onOpenSuggestions}>
            {suggestionCount} thing{suggestionCount === 1 ? '' : 's'} this session did not cover
          </button>
        )}
      </div>
    </nav>
  );
}

function EditableTitle({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  if (!editing) {
    return (
      <h2
        className="scenario-title"
        onDoubleClick={() => {
          setDraft(value);
          setEditing(true);
        }}
        title="double-click to rename"
      >
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
      onBlur={() => {
        setEditing(false);
        if (draft.trim() && draft !== value) onSave(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur();
        if (e.key === 'Escape') {
          setDraft(value);
          setEditing(false);
        }
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
        {open ? '▾' : '▸'} {total} action{total === 1 ? '' : 's'} left out
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
