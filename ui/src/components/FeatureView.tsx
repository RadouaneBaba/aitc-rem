/**
 * The artifact, at full width.
 *
 * This is the thing the whole tool is judged on, and it was being rendered in a
 * 30%-wide `white-space: pre` textarea in the third column -- so the shipped
 * output read `Then the first product is 'The Autumnal Hamper' pri` with the
 * price cut off, and the header line cut at `evidence:`. The one thing on
 * screen that must not be clipped was the only thing that was.
 *
 * It is a pane of its own now, and it is set in the body face rather than in
 * mono: a feature file is prose with keywords in it, not code. The keywords are
 * coloured, the quoted literals are not, and the result reads like a document a
 * QA lead would sign instead of a log.
 *
 * Structure is not editable here and the server says so plainly rather than
 * silently ignoring it: a step typed into this box has no recorded actions
 * behind it, and `event_coverage` would reject the run.
 */

import { useEffect, useState } from 'react';
import type { TestCase } from '../api';

export function FeatureView({
  testCase,
  text,
  busy,
  onSave,
}: {
  testCase: TestCase | undefined;
  text: string;
  busy: boolean;
  onSave: (next: string) => void;
}) {
  const [draft, setDraft] = useState(text);
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    setDraft(text);
    setEditing(false);
  }, [text]);

  const dirty = draft !== text;

  return (
    <section className="featureview">
      <div className="featureview-head">
        <h2>{testCase?.scenarioName || testCase?.title || 'Feature file'}</h2>
        <div className="spacer" />
        {editing ? (
          <>
            {dirty && (
              <button disabled={busy} onClick={() => setDraft(text)}>
                Revert
              </button>
            )}
            <button className="primary" disabled={busy || !dirty} onClick={() => onSave(draft)}>
              Save
            </button>
            <button
              disabled={busy}
              onClick={() => {
                setDraft(text);
                setEditing(false);
              }}
            >
              Done
            </button>
          </>
        ) : (
          <button onClick={() => setEditing(true)}>Edit the wording</button>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            className="feature-edit"
            value={draft}
            spellCheck={false}
            disabled={busy}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="muted small">
            Reword freely. To add or remove a step, use the step list — a step typed here has no
            recorded actions behind it and the run would be rejected.
          </p>
        </>
      ) : (
        <Gherkin text={text} />
      )}

      {testCase && <Inputs testCase={testCase} />}
      {testCase?.bug && <BugReport testCase={testCase} />}
    </section>
  );
}

const KEYWORDS =
  /^(\s*)(Feature|Background|Scenario Outline|Scenario|Examples|Given|When|Then|And|But|Rule)(:?)(\s|$)/;

/**
 * Gherkin, set as prose.
 *
 * Not a syntax highlighter and deliberately not a dependency: there are eleven
 * keywords, they are always the first word of a line, and a comment is a line
 * starting with `#`. Anything cleverer would be a library shipped to colour
 * eleven words.
 */
function Gherkin({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <div className="gherkin">
      {lines.map((line, i) => {
        if (/^\s*#/.test(line)) {
          return (
            <p key={i} className="g-comment">
              {line}
            </p>
          );
        }
        if (/^\s*@/.test(line)) {
          return (
            <p key={i} className="g-tags">
              {line.trim().split(/\s+/).map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
            </p>
          );
        }
        const match = KEYWORDS.exec(line);
        if (!match) {
          return (
            <p key={i} className={line.trim().startsWith('|') ? 'g-row' : 'g-plain'}>
              {line || ' '}
            </p>
          );
        }
        const indent = match[1] ?? '';
        const keyword = match[2] ?? '';
        const colon = match[3] ?? '';
        const rest = line.slice((indent + keyword + colon).length);
        return (
          <p key={i} className={`g-line g-${keyword.split(' ')[0]!.toLowerCase()}`}>
            <span className="g-indent">{indent}</span>
            <span className="g-keyword">
              {keyword}
              {colon}
            </span>
            <span className="g-rest">{rest}</span>
          </p>
        );
      })}
    </div>
  );
}

/**
 * The test's inputs, which were invisible.
 *
 * Every redacted value became a test PARAMETER: it is rendered in the feature
 * file, it is what `--replay-param` supplies, and it is what somebody has to
 * provide before this test can run anywhere. The review UI has never shown one,
 * so a reviewer approving a test case could not see what it needed to execute.
 *
 * `examples` is the other half and a different fact -- one flow exercised with
 * several sets of values, which is a judgement the author made about test
 * design rather than a consequence of redaction.
 */
function Inputs({ testCase }: { testCase: TestCase }) {
  const parameters = testCase.parameters ?? [];
  const examples = testCase.examples;
  if (!parameters.length && !examples) return null;

  return (
    <div className="inputs">
      {parameters.length > 0 && (
        <div>
          <h3 className="eyebrow">Values this test needs</h3>
          <table className="grid">
            <tbody>
              {parameters.map((p) => (
                <tr key={p.placeholder}>
                  <td>
                    <code>{p.placeholder}</code>
                  </td>
                  <td className="muted">{p.category.replace(/_/g, ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Hidden in the browser before anything was saved. Supply them when the test is run.
          </p>
        </div>
      )}

      {examples && examples.rows.length > 0 && (
        <div>
          <h3 className="eyebrow">Run with each of these</h3>
          <div className="tablewrap">
            <table className="grid">
              <thead>
                <tr>
                  {examples.columns.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {examples.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** A bug report is a sibling test case, not a branch of one -- the same
 *  sentence either way, and `actual` carries its citation because "the server
 *  returned 500" is worth exactly as much as the reader's ability to check it. */
function BugReport({ testCase }: { testCase: TestCase }) {
  const bug = testCase.bug!;
  return (
    <div className="bugreport">
      <h3 className="eyebrow">
        <span className="chip chip-bad">bug report</span> offered alongside this test case
      </h3>
      <p>
        <strong>Expected:</strong> {bug.expected}
      </p>
      <p>
        <strong>Actually:</strong> {bug.actual}
      </p>
      {bug.actualEvidence && (
        <p className="muted small">
          Checked against <code>{bug.actualEvidence.literal}</code> at{' '}
          <code>{bug.actualEvidence.eventId}</code>.
        </p>
      )}
    </div>
  );
}
