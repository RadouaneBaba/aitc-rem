import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Redactor } from '../redaction/redact';
import { isInteractiveElement, roleOf } from './a11y';
import { buildSnapshot, flattenSnapshot } from './snapshot';
import { waitForSettle } from './settle';

describe('role fallbacks', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('keeps controls that the ARIA spec gives no implicit role', () => {
    // Regression: input[type=password] has no implicit role, so it resolved to
    // '' , was treated as a structural wrapper, and vanished from the snapshot
    // entirely -- a login step with no password field in it.
    document.body.innerHTML = `
      <main>
        <label for="pw">Password</label>
        <input id="pw" type="password" value="hunter2">
      </main>`;
    expect(roleOf(document.getElementById('pw')!)).toBe('textbox');

    const { snapshot } = buildSnapshot(document.getElementById('pw'), document, new Redactor());
    const field = flattenSnapshot(snapshot).find((n) => n.role === 'textbox');
    expect(field).toBeTruthy();
    expect(field!.value).toBe('<<password>>');
  });

  it('keeps a file input, which also has no implicit role', () => {
    document.body.innerHTML = '<main><label for="f">Attach a PO</label><input id="f" type="file"></main>';
    expect(roleOf(document.getElementById('f')!)).toBe('button');
  });
});

describe('waitForSettle', () => {
  beforeEach(() => {
    document.body.innerHTML = '<main id="app"></main>';
  });

  /** Drives the state machine on fake timers so the tests do not actually wait. */
  function harness(
    opts: { inFlight?: () => number; timeoutMs?: number; quietMs?: number } = {},
  ) {
    const transient: Element[] = [];
    const handle = waitForSettle({
      doc: document,
      inFlight: opts.inFlight ?? (() => 0),
      onTransient: (el) => transient.push(el),
      timeoutMs: opts.timeoutMs ?? 5000,
      ...(opts.quietMs !== undefined ? { quietMs: opts.quietMs } : {}),
    });
    return { handle, transient };
  }

  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

  it('settles once the page has been quiet for 300ms', async () => {
    vi.useFakeTimers();
    const { handle } = harness();
    await vi.advanceTimersByTimeAsync(320);
    const info = await handle.done;
    expect(info.reason).toBe('quiet');
    vi.useRealTimers();
  });

  it('keeps waiting while a request from this action is still in flight', async () => {
    // Quiet is necessary but not sufficient. Capturing here would snapshot the
    // page before the server answered -- exactly the outcome SS6.5 exists to
    // prevent.
    vi.useFakeTimers();
    let inFlight = 1;
    const { handle } = harness({ inFlight: () => inFlight });

    let settled = false;
    void handle.done.then(() => (settled = true));

    await vi.advanceTimersByTimeAsync(1000);
    expect(settled).toBe(false);

    inFlight = 0;
    await vi.advanceTimersByTimeAsync(400);
    expect(settled).toBe(true);
    vi.useRealTimers();
  });

  it('gives up at the hard timeout and says so', async () => {
    vi.useFakeTimers();
    const { handle } = harness({ inFlight: () => 1, timeoutMs: 5000 });
    await vi.advanceTimersByTimeAsync(5100);
    const info = await handle.done;
    expect(info.reason).toBe('timeout');
    vi.useRealTimers();
  });

  it('reports a live region the moment it appears, ahead of settle', async () => {
    // A toast frequently vanishes within three seconds. Without this early
    // capture, an assertion about it could never be grounded.
    const { handle, transient } = harness();
    document.getElementById('app')!.insertAdjacentHTML(
      'beforeend',
      '<div role="alert">Order confirmed</div>',
    );
    await new Promise((r) => setTimeout(r, 20));

    expect(transient).toHaveLength(1);
    expect(transient[0]!.textContent).toBe('Order confirmed');
    handle.cancel();
  });

  it('notices a live region that already existed and only just gained text', async () => {
    // How most toast implementations actually work: the container is always in
    // the DOM and only its text changes.
    document.getElementById('app')!.innerHTML = '<div role="status" id="toast"></div>';
    const { handle, transient } = harness();
    document.getElementById('toast')!.textContent = 'Blue Widget added to cart';
    await new Promise((r) => setTimeout(r, 20));

    expect(transient).toHaveLength(1);
    handle.cancel();
  });

  it('a window ended by the next action says so, and stops absorbing the page', async () => {
    // The mechanism behind `superseded`. Nothing bounds a settle window by the
    // next action -- `inFlightFor` bounds request ATTRIBUTION, not this -- so
    // an `after` snapshot went on accumulating the page's response to whatever
    // the tester did NEXT and attributed it to this event.
    //
    // Measured on the checkout fixture: evt_007 (enter an order total) and
    // evt_008 (press Place order) are 2 ms apart with a 317 ms quiet window, so
    // evt_007's `after` contained the rejection evt_008 caused. An assertion
    // bound to it passed `evidence_retrieved` AND `contains_at` -- the literal
    // really was in the stored snapshot -- and was false about the moment it
    // named. Only replaying the test case against the app caught it.
    //
    // An early `after` is the price and it is the right one: it can produce an
    // empty diff, which is visible and honest, where the alternative produced a
    // wrong one that reads as right.
    const { handle } = harness();
    let settled = false;
    void handle.done.then(() => (settled = true));

    handle.cancel('superseded');
    const info = await handle.done;
    expect(info.reason).toBe('superseded');
    expect(settled).toBe(true);

    // And it is final: the page continuing to change afterwards must not
    // reopen the window or overwrite the reason.
    document.getElementById('app')!.insertAdjacentHTML(
      'beforeend',
      '<div role="alert">Orders over EUR500 require approval</div>',
    );
    await wait(20);
    expect((await handle.done).reason).toBe('superseded');
  });

  it('mutations postpone settle rather than triggering it', async () => {
    // Real timers: happy-dom delivers MutationObserver records on a task that
    // fake timers do not run, so a faked version of this test would only prove
    // that the observer never fired.
    const { handle } = harness({ quietMs: 60 });
    let settled = false;
    void handle.done.then(() => (settled = true));

    for (let i = 0; i < 4; i++) {
      await wait(30);
      document.getElementById('app')!.insertAdjacentHTML('beforeend', `<p>row ${i}</p>`);
    }
    expect(settled).toBe(false);

    await wait(160);
    expect(settled).toBe(true);
  });
});

describe('target-level fidelity', () => {
  it('recognises which elements are supposed to have a name', () => {
    // The flag rides on the element that was acted on, so this is the check
    // that decides whether a step carries the "no label" warning.
    document.body.innerHTML = `
      <button id="a"><span aria-hidden="true">x</span></button>
      <div id="b">just a container</div>
      <div id="c" role="button">Save</div>`;
    expect(isInteractiveElement(document.getElementById('a')!)).toBe(true);
    expect(isInteractiveElement(document.getElementById('b')!)).toBe(false);
    expect(isInteractiveElement(document.getElementById('c')!)).toBe(true);
  });
});

describe('a11y helpers on real control shapes', () => {
  it('treats an icon-only button as something that should have had a name', () => {
    document.body.innerHTML = '<button><span aria-hidden="true">&#10005;</span></button>';
    const button = document.querySelector('button')!;
    const span = document.querySelector('span')!;

    // The span is what a click's composedPath reports first, and describing it
    // would produce a step about an icon rather than about the control.
    expect(isInteractiveElement(span)).toBe(false);
    expect(isInteractiveElement(button)).toBe(true);
  });
});
