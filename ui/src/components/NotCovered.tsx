/**
 * What this session did not exercise — a prompt for the tester, never an
 * artifact.
 *
 * It used to hold a permanent, always-expanded, full-width footer under every
 * screen, so unverified suggestions took more room than the checked results
 * above them. Nothing here has been checked against anything, which is exactly
 * why it should not be the loudest thing on the page.
 *
 * It is a pane you open now. The quarantine is unchanged and still stated
 * once, at the top, because saying so is the difference between a useful prompt
 * and a false claim.
 */

import type { TestCase } from '../api';

export function NotCovered({
  testCases,
  onBack,
}: {
  testCases: TestCase[];
  onBack: () => void;
}) {
  const rows = testCases.flatMap((c) => (c.suggestions ?? []).map((s) => ({ ...s, case: c })));

  return (
    <section className="notcovered">
      <div className="featureview-head">
        <h2>What this session did not cover</h2>
        <div className="spacer" />
        <button onClick={onBack}>Back to the steps</button>
      </div>

      <p className="muted">
        Not part of the test case and <strong>not verified</strong>. These are things the
        recording revealed about the application that nothing has exercised yet — worth
        recording next, not worth shipping as tests.
      </p>

      {rows.length === 0 ? (
        <p className="muted">Nothing to suggest for this run.</p>
      ) : (
        <ul className="suggestions">
          {rows.map((s) => (
            <li key={s.id}>
              <span className="chip">{s.category.replace(/_/g, ' ')}</span>
              <p className="suggestion-text">{s.text}</p>
              <p className="muted small">{s.rationale}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
