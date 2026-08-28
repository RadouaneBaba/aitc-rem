export function Confirmation({ reference }: { reference: string }) {
  return (
    <main className="page">
      <section className="card">
        {/* role=alert appears only after the order succeeds: this is the node an
            assertion should end up bound to (SS3.2). */}
        <div role="alert" className="ok">
          Order confirmed
        </div>
        <h2>Thank you</h2>
        <p>
          Your order reference is <strong>{reference}</strong>.
        </p>
        <p className="muted">A confirmation email is on its way.</p>

        {/* SS18 milestone 21. A real flow leaves the tab it started in -- a
            payment provider, a PDF receipt, a carrier's tracking page -- and
            the recorder was pinned to one tab by choice rather than by
            limitation. `target="_blank"` sets `openerTabId`, which is what the
            service worker follows.

            A receipt, deliberately: it carries a value nothing on this page
            shows, so a test that follows the tab can assert something a test
            that stops here cannot. A second tab with nothing new on it would
            demonstrate the plumbing and prove nothing about the output. */}
        <p>
          <a href={`/receipt?ref=${encodeURIComponent(reference)}`} target="_blank" rel="noreferrer">
            Open the receipt in a new tab
          </a>
        </p>
      </section>
    </main>
  );
}
