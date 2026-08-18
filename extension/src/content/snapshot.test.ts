import { beforeEach, describe, expect, it } from 'vitest';

import { Redactor } from '../redaction/redact';
import { diffSnapshots } from './diff';
import { cssPath, selectorsFor } from './selectors';
import { buildSnapshot, flattenSnapshot, scopeRootFor } from './snapshot';

const redactor = () => new Redactor();

function find(snapshot: ReturnType<typeof buildSnapshot>['snapshot'], role: string, name?: string) {
  return flattenSnapshot(snapshot).find(
    (n) => n.role === role && (name === undefined || n.name === name),
  );
}

describe('buildSnapshot', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    document.title = 'Checkout';
  });

  it('records roles and accessible names rather than tags and classes', () => {
    document.body.innerHTML = `
      <main>
        <h2>Checkout</h2>
        <button class="css-1x7f2k">Place order</button>
      </main>`;
    const { snapshot } = buildSnapshot(document.querySelector('button'), document, redactor());

    expect(find(snapshot, 'button')?.name).toBe('Place order');
    expect(find(snapshot, 'heading')?.name).toBe('Checkout');
    // The generated class name that a raw-DOM capture would preserve is
    // nowhere in the snapshot.
    expect(JSON.stringify(snapshot)).not.toContain('css-1x7f2k');
  });

  it('scopes to the nearest landmark ancestor', () => {
    document.body.innerHTML = `
      <nav><a href="/reports">Reports</a></nav>
      <main><button>Place order</button></main>`;
    const root = scopeRootFor(document.querySelector('button'), document);
    expect(root.tagName).toBe('MAIN');

    const { snapshot } = buildSnapshot(document.querySelector('button'), document, redactor());
    expect(find(snapshot, 'button')).toBeTruthy();
    // The nav is outside the scope and should not be paid for.
    expect(find(snapshot, 'link', 'Reports')).toBeFalsy();
  });

  it('collects live regions document-wide, outside the scope', () => {
    // The outcome of an action routinely renders far from the element clicked;
    // if this were scoped away the assertion would be ungroundable.
    document.body.innerHTML = `
      <main><button>Place order</button></main>
      <div role="alert">Order confirmed</div>`;
    const { snapshot } = buildSnapshot(document.querySelector('button'), document, redactor());

    expect(snapshot.liveRegions).toHaveLength(1);
    expect(snapshot.liveRegions[0]!.name).toBe('Order confirmed');
  });

  it('reaches into an open shadow root', () => {
    document.body.innerHTML = '<main><div id="host"></div></main>';
    const host = document.getElementById('host')!;
    host.attachShadow({ mode: 'open' }).innerHTML = '<button>Express delivery</button>';

    const { snapshot } = buildSnapshot(host, document, redactor());
    expect(find(snapshot, 'button', 'Express delivery')).toBeTruthy();
  });

  it('flags a closed shadow root instead of describing it', () => {
    document.body.innerHTML = '<main><promo-widget></promo-widget></main>';
    const host = document.querySelector('promo-widget')!;
    host.attachShadow({ mode: 'closed' }).innerHTML = '<button>Apply</button>';

    const { snapshot, flags } = buildSnapshot(host, document, redactor());
    expect(flags).toContain('closed_shadow_root');
    // Nothing from inside the closed root may be invented into the snapshot.
    expect(find(snapshot, 'button', 'Apply')).toBeFalsy();
  });

  it('does not raise no_accessible_name for unnamed nodes merely in scope', () => {
    // SS6.8 frames this flag as a statement about the element that was acted on
    // ("my description of THIS element may be wrong"). Raising it for any
    // unnamed node anywhere in scope flagged 10 of 12 events in a real
    // recording, which conveys exactly as much as flagging none of them.
    document.body.innerHTML = `
      <main>
        <button><span aria-hidden="true">x</span></button>
        <button>Place order</button>
      </main>`;
    const { flags } = buildSnapshot(
      document.querySelectorAll('button')[1]!,
      document,
      redactor(),
    );
    expect(flags).not.toContain('no_accessible_name');
  });

  it('redacts field values inside the snapshot', () => {
    document.body.innerHTML =
      '<main><input type="password" value="hunter2"><input type="email" value="tester@example.com"></main>';
    const { snapshot } = buildSnapshot(document.querySelector('input'), document, redactor());
    const json = JSON.stringify(snapshot);
    expect(json).not.toContain('hunter2');
    expect(json).not.toContain('tester@example.com');
    expect(json).toContain('<<password>>');
  });

  it('does not descend into an iframe', () => {
    // The child frame's own content script reports its contents, under its own
    // FramePath; duplicating them here would double-count every step.
    document.body.innerHTML = '<main><iframe title="Payment details"></iframe></main>';
    const { snapshot } = buildSnapshot(document.querySelector('iframe'), document, redactor());
    expect(find(snapshot, 'iframe')?.name).toBe('Payment details');
  });

  it('stays small by dropping structural wrappers', () => {
    document.body.innerHTML = `<main>${'<div>'.repeat(15)}<button>Save</button>${'</div>'.repeat(15)}</main>`;
    const { snapshot } = buildSnapshot(document.querySelector('button'), document, redactor());
    expect(flattenSnapshot(snapshot).length).toBeLessThan(6);
    expect(find(snapshot, 'button', 'Save')).toBeTruthy();
  });
});

describe('diffSnapshots', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  function snap() {
    return buildSnapshot(document.querySelector('button'), document, redactor()).snapshot;
  }

  it('reports an appearing alert as a single addition', () => {
    document.body.innerHTML = '<main><button>Place order</button></main>';
    const before = snap();
    document.body.insertAdjacentHTML('beforeend', '<div role="alert">Order confirmed</div>');
    const after = snap();

    const diff = diffSnapshots(before, after);
    expect(diff.added.map((n) => n.name)).toContain('Order confirmed');
    expect(diff.removed).toHaveLength(0);
  });

  it('reports a value change as changed, not as add plus remove', () => {
    document.body.innerHTML = '<main><span id="badge" role="status">0</span><button>Add</button></main>';
    const before = snap();
    document.getElementById('badge')!.textContent = '1';
    const after = snap();

    const diff = diffSnapshots(before, after);
    expect(diff.added.some((n) => n.name === '1')).toBe(true);
    expect(diff.removed.some((n) => n.name === '0')).toBe(true);
  });

  it('inserting one row does not report every row below it as changed', () => {
    // Refs are structural paths, so ref-based matching would report a cascade
    // here. Identity matching is what keeps the diff readable.
    document.body.innerHTML =
      '<main><ul><li>Alpha</li><li>Beta</li><li>Gamma</li></ul><button>x</button></main>';
    const before = snap();
    document.querySelector('ul')!.insertAdjacentHTML('afterbegin', '<li>Zero</li>');
    const after = snap();

    const diff = diffSnapshots(before, after);
    expect(diff.added).toHaveLength(1);
    expect(diff.added[0]!.name).toBe('Zero');
    expect(diff.changed).toHaveLength(0);
    expect(diff.removed).toHaveLength(0);
  });
});

describe('selectors', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('prefers a test id when the application provides one', () => {
    document.body.innerHTML = '<button data-testid="submit-order">Place order</button>';
    const set = selectorsFor(document.querySelector('button')!);
    expect(set.testId).toBe('[data-testid="submit-order"]');
    expect(set.role).toBe("getByRole('button', { name: \"Place order\" })");
  });

  it('falls back to role and name when there is no test id', () => {
    // Which is the normal case: most applications under test provide none.
    document.body.innerHTML = '<button class="css-1x7f2k">Place order</button>';
    const set = selectorsFor(document.querySelector('button')!);
    expect(set.testId).toBeUndefined();
    expect(set.role).toContain('Place order');
    expect(set.css).toBeTruthy();
  });

  it('ignores generated class names and ids when building a css path', () => {
    document.body.innerHTML =
      '<div class="css-9a8b7c"><button id="mui-4471" class="sc-AbCdEf">Save</button></div>';
    const path = cssPath(document.querySelector('button')!);
    expect(path).not.toContain('mui-4471');
    expect(path).not.toContain('css-9a8b7c');
    expect(document.querySelectorAll(path)).toHaveLength(1);
  });

  it('produces a css path that actually resolves to one element', () => {
    document.body.innerHTML = `
      <table><tbody>
        <tr><td><button>Add</button></td></tr>
        <tr><td><button>Add</button></td></tr>
      </tbody></table>`;
    const second = document.querySelectorAll('button')[1]!;
    const path = cssPath(second);
    expect(document.querySelectorAll(path)).toHaveLength(1);
    expect(document.querySelector(path)).toBe(second);
  });
});
