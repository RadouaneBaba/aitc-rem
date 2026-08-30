/**
 * "Mark what I'm verifying" -- the one input that outranks everything the
 * pipeline infers, and the one that silently produced nothing.
 *
 * A mark becomes an expected result WORD FOR WORD. Both real marks ever made
 * with this tool came back as `{role: "div", name: ""}` on the same unnamed
 * container (`#ui-id-17`, a commercial site's mini-cart panel): the tester
 * pointed at the bag, believed they had marked it, and the pipeline received an
 * empty target. Twice, with no feedback either time.
 *
 * So these tests are about the two halves of that fix -- find the words when
 * they are there, and refuse the click when they are not.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Redactor } from '../redaction/redact';
import { ElementPicker } from './picker';

const redactor = () => new Redactor();

/** Click the centre of an element, the way the picker listens for it. */
function clickOn(element: Element): void {
  const box = element.getBoundingClientRect();
  vi.spyOn(document, 'elementFromPoint').mockReturnValue(element as Element);
  document.dispatchEvent(
    new MouseEvent('click', {
      bubbles: true,
      clientX: box.left + 1,
      clientY: box.top + 1,
    }),
  );
}

function hintText(): string {
  const nodes = [...document.documentElement.children].filter(
    (n) => n instanceof HTMLDivElement && n.textContent,
  );
  return nodes.map((n) => n.textContent).join(' ');
}

describe('the element picker', () => {
  // Every picker listens on `document` in the CAPTURE phase and calls
  // `stopImmediatePropagation`, so one left active outranks the next test's.
  // Cancelling is the same thing `recorder.stop()` does.
  let open: ElementPicker[] = [];

  const picking = (red: () => Redactor = redactor) => {
    const picker = new ElementPicker(red);
    open.push(picker);
    return picker;
  };

  beforeEach(() => {
    for (const picker of open) picker.cancel();
    open = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('takes the accessible name when the element has one', async () => {
    document.body.innerHTML = '<button id="t">Place order</button>';
    const picker = picking();
    const result = picker.start();

    clickOn(document.getElementById('t')!);

    expect((await result)?.target.name).toBe('Place order');
  });

  it('falls back to the visible words when it has no accessible name', async () => {
    // The thing worth checking is very often a bare span inside an unnamed
    // wrapper -- a price, a count, a product name. An accessible name is a
    // property of controls and landmarks; the tester points at what they SEE.
    document.body.innerHTML = '<div id="t"><span>Shopping Bag 5 2 items</span></div>';
    const picker = picking();
    const result = picker.start();

    clickOn(document.getElementById('t')!);

    expect((await result)?.target.name).toBe('Shopping Bag 5 2 items');
  });

  it('refuses a container with no words in it, and stays open', async () => {
    // The defect, in the shape it actually shipped. Recording an empty target
    // is what taught the tester the feature works.
    document.body.innerHTML = '<div id="t"></div><span id="ok">Total EUR615</span>';
    const picker = picking();
    const result = picker.start();

    clickOn(document.getElementById('t')!);

    expect(picker.active).toBe(true);
    expect(hintText()).toContain('no text in it');

    // Still open, so the tester can point at the words instead.
    clickOn(document.getElementById('ok')!);
    expect((await result)?.target.name).toBe('Total EUR615');
  });

  it('refuses a whole panel rather than quoting all of it', async () => {
    // A mark becomes one expected result. A panel's entire contents is not a
    // verdict, it is a screenshot in prose.
    document.body.innerHTML = `<div id="t">${'a very long line of product copy '.repeat(10)}</div>`;
    const picker = picking();
    picker.start();

    clickOn(document.getElementById('t')!);

    expect(picker.active).toBe(true);
    expect(hintText()).toContain('Point at the words');
  });

  it('redacts a value the tester typed before the mark is recorded', async () => {
    // SS7.1 is absolute: nothing raw is persisted, and a tester may well point
    // at the field they just typed a password into.
    const red = new Redactor();
    document.body.innerHTML = '<input id="p" type="password" />';
    const field = document.getElementById('p') as HTMLInputElement;
    field.value = 'hunter2trombone';
    red.redactFieldValue(field, field.value);

    document.body.innerHTML += '<div id="t"><span>hunter2trombone</span></div>';
    const picker = picking(() => red);
    const result = picker.start();

    clickOn(document.getElementById('t')!);

    expect((await result)?.target.name).not.toContain('hunter2trombone');
  });
});
