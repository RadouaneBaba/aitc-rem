import { useState } from 'react';

import { post } from '../api';
import { SignatureCanvas } from '../components/SignatureCanvas';

interface Props {
  cartTotal: number;
  onConfirmed: (reference: string) => void;
}

/**
 * The busiest page on purpose. In one screen it carries a cross-origin iframe,
 * an open shadow root, a closed shadow root, a canvas, a file input, an
 * endpoint that never settles, and an unlabelled control -- so every hard path
 * in SS6.8 can be triggered deliberately instead of waiting for one to appear.
 */
export function Checkout({ cartTotal, onConfirmed }: Props) {
  const [poNumber, setPoNumber] = useState('');
  const [total, setTotal] = useState(cartTotal || 240);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slowState, setSlowState] = useState<'idle' | 'pending' | 'done'>('idle');
  const [attachment, setAttachment] = useState<string | null>(null);
  const [speed, setSpeed] = useState('standard');

  // The iframe is served from 127.0.0.1 while the app runs on localhost: same
  // dev server, different origin.
  const frameSrc = `http://127.0.0.1:${location.port}/embed.html`;

  return (
    <main className="page">
      <section className="card">
        <h2>Checkout</h2>

        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            const res = await post<{ reference?: string; error?: string }>('/orders', {
              total,
              approved,
              poNumber,
              speed,
            });
            if (res.ok && res.data.reference) onConfirmed(res.data.reference);
            else setError(res.data.error ?? 'Could not place the order');
          }}
        >
          <div className="row">
            <div>
              <label htmlFor="po">Purchase order number</label>
              <input id="po" value={poNumber} onChange={(e) => setPoNumber(e.target.value)} />
            </div>
            <div>
              <label htmlFor="total">Order total (EUR)</label>
              <input
                id="total"
                type="number"
                value={total}
                onChange={(e) => setTotal(Number(e.target.value))}
              />
            </div>
          </div>

          <label>
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />{' '}
            Manager approval obtained
          </label>

          <div style={{ marginTop: 16 }}>
            <delivery-options
              onChange={undefined}
              ref={(el: HTMLElement | null) => {
                if (!el || (el as any).__wired) return;
                (el as any).__wired = true;
                el.addEventListener('speedchange', (ev) => setSpeed((ev as CustomEvent).detail));
              }}
            />
          </div>

          <div style={{ marginTop: 16 }}>
            <promo-widget />
          </div>

          <label htmlFor="attachment">Attach a signed PO</label>
          <input
            id="attachment"
            type="file"
            onChange={(e) => setAttachment(e.target.files?.[0]?.name ?? null)}
          />
          {attachment && <p className="muted">Selected: {attachment}</p>}

          <label htmlFor="sig">Signature</label>
          <div id="sig">
            <SignatureCanvas />
          </div>

          {error && <div role="alert">{error}</div>}

          <div style={{ marginTop: 18, display: 'flex', gap: 10 }}>
            <button className="primary" type="submit">
              Place order
            </button>

            <button
              className="secondary"
              type="button"
              onClick={async () => {
                setSlowState('pending');
                await post('/slow', {});
                setSlowState('done');
              }}
            >
              Submit for slow validation
            </button>

            {/* Deliberately unlabelled: no text, no aria-label, no title.
                Must raise `no_accessible_name` rather than be described. */}
            <button className="secondary" type="button" onClick={() => setPoNumber('')}>
              <span aria-hidden="true">&#10005;</span>
            </button>
          </div>

          {slowState === 'pending' && <p className="muted">Validating with the finance system...</p>}
          {slowState === 'done' && (
            <div role="status" className="muted">
              Slow validation finished
            </div>
          )}
        </form>
      </section>

      <section className="card">
        <h2>Payment details</h2>
        <p className="muted">Served from a different origin, in an iframe.</p>
        <iframe className="payment" src={frameSrc} title="Payment details" />
      </section>
    </main>
  );
}
