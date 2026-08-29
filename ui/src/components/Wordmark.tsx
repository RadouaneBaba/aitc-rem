/**
 * The one piece of identity in the product.
 *
 * There was none: four surfaces, four unrelated headers, and the closest thing
 * to a logo was the string "AITC-REM Recorder" set in 14px bold. Nothing on any
 * screen said these were one tool.
 *
 * The mark is a record button with a square inside it -- record, and the frame
 * that comes out of recording. It is drawn rather than imported so it inherits
 * the brand token and therefore themes itself, and so the extension can repeat
 * the same shape in plain HTML without a build step.
 */
export function Wordmark({ small }: { small?: boolean }) {
  return (
    <span className={`wordmark${small ? ' wordmark-sm' : ''}`}>
      <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <circle cx="10" cy="10" r="9" className="wordmark-ring" />
        <rect x="6.5" y="6.5" width="7" height="7" rx="1.5" className="wordmark-dot" />
      </svg>
      <b>AITC</b>
    </span>
  );
}
