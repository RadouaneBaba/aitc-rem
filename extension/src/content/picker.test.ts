/**
 * "Mark what I'm verifying" -- the one input that outranks everything the
 * pipeline infers, and the one that kept producing less than the tester meant.
 *
 * Two defects, one after the other, and these tests pin both fixes.
 *
 * First: a mark with no words came back as `{role: "div", name: ""}`. Both real
 * marks ever made with the first version landed on the same unnamed container
 * (`#ui-id-17`, a commercial site's mini-cart panel): the tester pointed at the
 * bag, believed they had marked it, and the pipeline received an empty target.
 * Twice, with no feedback either time.
 *
 * Then the fix for that refused too much. Anything over 120 characters of text
 * was treated as wordless, so a product CARD was unmarkable -- and a tester
 * asked to show that a list had sorted was refused twice and fell back to
 * marking two bare prices, which reached the author as two identical lines.
 *
 * So: find the words wherever they are, keep the handle a real page string,
 * carry the position, let one session mark several things, and refuse only what
 * genuinely has nothing in it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Redactor } from '../redaction/redact';
import { ElementPicker, type PickResult } from './picker';

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

/** Move the cursor onto an element, which is what arrow-widening works from. */
function hoverOn(element: Element): void {
  const box = element.getBoundingClientRect();
  vi.spyOn(document, 'elementFromPoint').mockReturnValue(element as Element);
  document.dispatchEvent(
    new MouseEvent('mousemove', {
      bubbles: true,
      clientX: box.left + 1,
      clientY: box.top + 1,
    }),
  );
}

function press(key: string): void {
  document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
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
    const marks: PickResult[] = [];
    void picker.start((mark) => marks.push(mark));
    return { picker, marks };
  };

  beforeEach(() => {
    for (const picker of open) picker.cancel();
    open = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('takes the accessible name when the element has one', () => {
    document.body.innerHTML = '<button id="t">Place order</button>';
    const { marks } = picking();

    clickOn(document.getElementById('t')!);

    expect(marks[0]!.target.name).toBe('Place order');
  });

  it('falls back to the visible words when it has no accessible name', () => {
    // The thing worth checking is very often a bare span inside an unnamed
    // wrapper -- a price, a count, a product name. An accessible name is a
    // property of controls and landmarks; the tester points at what they SEE.
    document.body.innerHTML = '<div id="t"><span>Shopping Bag 5 2 items</span></div>';
    const { marks } = picking();

    clickOn(document.getElementById('t')!);

    expect(marks[0]!.target.name).toBe('Shopping Bag 5 2 items');
  });

  it('marks a whole product card, and names it something really on the page', () => {
    // The defect this replaces. A card is title + price + button + copy, which
    // is over the old 120-character cap, so `visibleText` returned "" and the
    // click was refused as wordless. The tester wanted the card.
    //
    // `name` must stay a string that appears on the page verbatim: a truncated
    // half-sentence would be quoted back as a literal and refused by the gate,
    // which is worse than having no name. So the ladder reaches INSIDE for the
    // first named thing -- the product's title -- and `text` carries the rest.
    document.body.innerHTML = `
      <div id="card">
        <h3>Royal Blend Loose Leaf Tea, 250g</h3>
        <p>A malty breakfast tea blended for Edward VII, and the one Fortnum's is
           best known for. Drink it with milk in the morning.</p>
        <span>£14.95</span>
        <button>Add to Bag</button>
      </div>`;
    const { marks } = picking();

    clickOn(document.getElementById('card')!);

    expect(marks).toHaveLength(1);
    expect(marks[0]!.target.name).toBe('Royal Blend Loose Leaf Tea, 250g');
    expect(marks[0]!.target.text).toContain('£14.95');
    expect(marks[0]!.target.name).not.toContain('…');
  });

  it('records which of its siblings the element is, so a sort can be checked', () => {
    // Two prices in a sorted list are two identical marks without this. The
    // css selector always carried `nth-of-type(1)` and nothing downstream could
    // read it.
    document.body.innerHTML = `
      <div id="grid">
        <div class="product"><span id="first">£275.00</span></div>
        <div class="product"><span id="second">£38.50</span></div>
      </div>`;
    const { marks } = picking();

    clickOn(document.getElementById('first')!.parentElement!);
    clickOn(document.getElementById('second')!.parentElement!);

    expect(marks.map((m) => m.target.ordinal)).toEqual([1, 2]);
  });

  it('stays open so several things can be marked as one comparison', () => {
    // A sort, a total and a difference are claims about a RELATION, and one
    // target cannot express one. Marks are emitted as they land rather than on
    // a commit gesture: there is no keystroke to forget and lose them to.
    document.body.innerHTML = '<span id="a">£275.00</span><span id="b">£38.50</span>';
    const { picker, marks } = picking();

    clickOn(document.getElementById('a')!);
    expect(picker.active).toBe(true);
    clickOn(document.getElementById('b')!);

    expect(marks).toHaveLength(2);
    expect(marks[0]!.groupId).toBe(marks[1]!.groupId);
    expect(marks.map((m) => m.index)).toEqual([1, 2]);
    expect(hintText()).toContain('£275.00');

    picker.cancel();
    expect(picker.active).toBe(false);
  });

  it('widens to the parent on arrow up, and shows what it would record', () => {
    // Deliberately manual. Resolving the "meaningful" ancestor automatically
    // would mean the tester clicks one thing and the recorder stores another,
    // which is the class of surprise this feature exists to remove.
    document.body.innerHTML = `
      <div id="card"><h3>Royal Blend</h3><span id="price">£14.95</span></div>`;
    const { marks } = picking();

    hoverOn(document.getElementById('price')!);
    press('ArrowUp');
    clickOn(document.getElementById('price')!);

    expect(marks[0]!.target.name).toBe('Royal Blend');
  });

  it('narrows back on arrow down', () => {
    document.body.innerHTML = `
      <div id="card"><h3>Royal Blend</h3><span id="price">£14.95</span></div>`;
    const { marks } = picking();

    hoverOn(document.getElementById('price')!);
    press('ArrowUp');
    press('ArrowDown');
    clickOn(document.getElementById('price')!);

    expect(marks[0]!.target.name).toBe('£14.95');
  });

  it('refuses an element with no text anywhere in it, and stays open', () => {
    // The original defect, in the shape it actually shipped. Recording an empty
    // target is what taught the tester the feature works. This is now the only
    // thing refused -- an empty wrapper, a spacer, an image with no alt.
    document.body.innerHTML = '<div id="t"></div><span id="ok">Total EUR615</span>';
    const { picker, marks } = picking();

    clickOn(document.getElementById('t')!);

    expect(marks).toHaveLength(0);
    expect(picker.active).toBe(true);
    expect(hintText()).toContain('no text in it');

    // Still open, so the tester can point at the words instead.
    clickOn(document.getElementById('ok')!);
    expect(marks[0]!.target.name).toBe('Total EUR615');
  });

  it('redacts a value the tester typed before the mark is recorded', () => {
    // SS7.1 is absolute: nothing raw is persisted, and a tester may well point
    // at the field they just typed a password into.
    const red = new Redactor();
    document.body.innerHTML = '<input id="p" type="password" />';
    const field = document.getElementById('p') as HTMLInputElement;
    field.value = 'hunter2trombone';
    red.redactFieldValue(field, field.value);

    document.body.innerHTML += '<div id="t"><span>hunter2trombone</span></div>';
    const { marks } = picking(() => red);

    clickOn(document.getElementById('t')!);

    expect(marks[0]!.target.name).not.toContain('hunter2trombone');
    expect(marks[0]!.target.text ?? '').not.toContain('hunter2trombone');
  });
});
