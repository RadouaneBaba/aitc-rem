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
      </section>
    </main>
  );
}
