/**
 * Two custom elements whose only job is to be awkward for the recorder.
 *
 * `<delivery-options>` uses an OPEN shadow root: the content script can walk
 * into it via element.shadowRoot, and event.composedPath() reveals the real
 * target, so a step recorded here should read normally.
 *
 * `<promo-widget>` uses a CLOSED shadow root: it is unreachable by any means,
 * including CDP, and must surface as the `closed_shadow_root` fidelity flag
 * rather than as a confident guess (SS6.8).
 */

class DeliveryOptions extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: 'open' });
    root.innerHTML = `
      <style>
        fieldset { border: 1px solid #dfe3e8; border-radius: 8px; padding: 12px 14px; }
        legend { font-size: 13px; font-weight: 600; padding: 0 6px; }
        label { display: flex; gap: 8px; align-items: center; margin: 8px 0; font-size: 14px; }
      </style>
      <fieldset>
        <legend>Delivery speed</legend>
        <label><input type="radio" name="speed" value="standard" checked /> Standard (3-5 days)</label>
        <label><input type="radio" name="speed" value="express" /> Express (next day, +EUR12)</label>
        <label><input type="radio" name="speed" value="pickup" /> Collect in store</label>
      </fieldset>
    `;
    root.addEventListener('change', (e) => {
      const input = e.target as HTMLInputElement;
      this.dispatchEvent(
        new CustomEvent('speedchange', { detail: input.value, bubbles: true, composed: true }),
      );
    });
  }
}

class PromoWidget extends HTMLElement {
  private closedRoot: ShadowRoot | null = null;

  connectedCallback() {
    if (this.closedRoot) return;
    this.closedRoot = this.attachShadow({ mode: 'closed' });
    this.closedRoot.innerHTML = `
      <style>
        .promo { border: 1px dashed #dfe3e8; border-radius: 8px; padding: 12px 14px; }
        input { padding: 8px; border: 1px solid #dfe3e8; border-radius: 6px; }
        button { padding: 8px 12px; border: 0; border-radius: 6px; background: #2f6f4f; color: #fff; cursor: pointer; }
        .msg { margin-top: 8px; font-size: 13px; color: #2f6f4f; }
      </style>
      <div class="promo">
        <label for="code">Promo code</label>
        <div style="display:flex; gap:8px; margin-top:6px;">
          <input id="code" placeholder="Enter code" />
          <button id="apply">Apply</button>
        </div>
        <div class="msg" role="status"></div>
      </div>
    `;
    this.closedRoot.getElementById('apply')?.addEventListener('click', () => {
      const msg = this.closedRoot!.querySelector('.msg')!;
      const code = (this.closedRoot!.getElementById('code') as HTMLInputElement).value;
      msg.textContent = code ? `Code ${code} applied` : 'Enter a code first';
    });
  }
}

if (!customElements.get('delivery-options')) {
  customElements.define('delivery-options', DeliveryOptions);
}
if (!customElements.get('promo-widget')) {
  customElements.define('promo-widget', PromoWidget);
}

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'delivery-options': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>;
      'promo-widget': React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement>;
    }
  }
}

export {};
