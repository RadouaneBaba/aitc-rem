/**
 * What the keys do, and what the marks mean.
 *
 * Two problems, one panel. The review loop is now keyboard-first and a
 * shortcut nobody can discover is a shortcut nobody uses. And the step list
 * has always marked steps with a bare `?`, `!` and `·` whose only explanation
 * was a `title` tooltip -- a legend that appears if you hover the right pixel
 * for a second, which is not a legend.
 */

export function ShortcutSheet({ onClose }: { onClose: () => void }) {
  return (
    <div className="sheet-backdrop" onClick={onClose} role="presentation">
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts and what the marks mean"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2>Reviewing with the keyboard</h2>
          <button onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <dl className="keys">
          <dt>
            <kbd>j</kbd> / <kbd>k</kbd>
          </dt>
          <dd>Next step / previous step.</dd>

          <dt>
            <kbd>a</kbd> / <kbd>r</kbd>
          </dt>
          <dd>
            Accept or reject every expected result on this step. Most steps have one, and many
            have none — an action with nothing to check is the normal case.
          </dd>

          <dt>
            <kbd>e</kbd>
          </dt>
          <dd>
            Edit the step's wording. <kbd>Esc</kbd> puts it back, <kbd>⌘</kbd>
            <kbd>↵</kbd> saves.
          </dd>

          <dt>
            <kbd>⌘</kbd>
            <kbd>↵</kbd>
          </dt>
          <dd>Approve the run. Asks first — it cannot be undone.</dd>

          <dt>
            <kbd>?</kbd>
          </dt>
          <dd>This panel.</dd>
        </dl>

        <h3>The marks beside a step</h3>
        <dl className="keys">
          <dt>
            <span className="mark">?</span>
          </dt>
          <dd>
            The tool has a question for you. It could not settle something on its own and said
            so rather than guessing.
          </dd>
          <dt>
            <span className="mark">!</span>
          </dt>
          <dd>Low confidence. Worth reading before you accept anything on it.</dd>
          <dt>
            <span className="mark">·</span>
          </dt>
          <dd>You have already edited this step.</dd>
        </dl>

        <p className="muted">
          Nothing here is destructive. Deleting a step and approving the run both ask first.
        </p>
      </div>
    </div>
  );
}
