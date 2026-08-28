/**
 * The page a real flow opens in a second tab (SS18 milestone 21).
 *
 * Reached only via `target="_blank"` from the confirmation page, which is what
 * sets `openerTabId` -- the signal the service worker follows when deciding
 * whether a new tab belongs to the recording. A tester opening their email
 * mid-session has no opener and is correctly left out.
 *
 * It shows a total the confirmation page does not, so a test that follows the
 * tab can assert something a test that stops at the confirmation cannot. That
 * is the point: a second tab carrying nothing new would prove the plumbing
 * works and prove nothing about the output.
 */
export function Receipt() {
  const reference = new URLSearchParams(location.search).get('ref') ?? 'unknown';

  return (
    <main className="page">
      <section className="card">
        <h2>Receipt</h2>
        <p>
          Order <strong>{reference}</strong>
        </p>
        {/* The value under test. It exists nowhere else in the app, so an
            assertion on it can only come from a recording that followed the
            tab. */}
        <p role="status">Total charged: EUR 615.00</p>
        <p className="muted">Keep this for your records.</p>
      </section>
    </main>
  );
}
