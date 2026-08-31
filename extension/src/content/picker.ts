/**
 * "Mark what I'm verifying" -- the assertion annotation (SS6.7).
 *
 * This is the top of SS9.5's provenance ladder and, until now, the only rung
 * with no way to reach it. The schema has carried `kind: 'assertion'` and an
 * `AnnotationTarget` from the start, the assertion prompt advertises annotations
 * to the model, and the review UI has a tooltip explaining what `annotated`
 * means -- and nothing in the recorder could ever produce one. Every assertion
 * this tool has made has been `inferred`, which is a guess about which of the
 * forty things that changed on screen was the point.
 *
 * The tester knows which one. This is how they say so: point at it.
 *
 * The overlay is a plain fixed-position element rather than anything clever.
 * It must not perturb the page it is measuring -- no layout impact, no focus
 * stealing, and `pointer-events: none` on the highlight so `elementFromPoint`
 * keeps returning the page's own nodes rather than ours.
 *
 * ## Three things a tester could not do, and now can
 *
 * **Point at a container.** The rule was "a mark with no words in it is not a
 * mark", and it was right about the defect it was written for and wrong about
 * everything else: `visibleText` gave up over 120 characters, so a product card
 * -- title, price, button -- was unmarkable, and the click was refused with a
 * hint telling the tester to point at something smaller. Observed on a real
 * session: asked to show that a list had sorted, the tester tried to mark two
 * whole products, was refused, and fell back to marking the two prices.
 *
 * The fix is not a bigger cap. It is that `name` and `text` are different
 * questions. `name` is a short handle a sentence can use, and it is now always
 * a string that genuinely appears on the page -- the element's accessible name,
 * else its own text, else the first named thing INSIDE it, which for a product
 * card is the product's title. `text` carries the words. Neither is invented
 * and neither is a truncated half-sentence somebody might quote as a literal.
 *
 * **Point at something bigger than what is under the cursor.** Arrow up widens
 * the mark to the parent, arrow down narrows it back, and the highlight always
 * outlines what will actually be recorded. Deliberately manual: resolving the
 * "meaningful" ancestor automatically would mean the tester clicks one thing
 * and the recorder stores another, which is the class of surprise this whole
 * feature exists to remove.
 *
 * **Point at more than one thing.** A sort, a total and a difference are all
 * claims about a RELATION, and one target cannot express one. The picker used
 * to resolve on the first click; it now stays open until Escape and emits each
 * mark as it lands, all of them sharing a `groupId` and numbered in the order
 * the tester pointed. Emitting immediately rather than on a commit gesture is
 * the point: there is no keystroke a tester can forget and lose their work to.
 */

import { nameOf, ownText, rawValueOf, roleOf } from './a11y';
import { selectorsFor } from './selectors';
import type { Redactor } from '../redaction/redact';
import type { AnnotationTarget } from '../types/recording';

/** Big enough to sit above anything an application is likely to use. */
const Z = 2147483000;

/**
 * The longest a mark's `name` may be.
 *
 * `name` is the handle -- what a step sentence and the session index call this
 * thing. It is never truncated INTO existence: a candidate longer than this is
 * rejected and the ladder moves on to the next rung, so whatever ends up here
 * is a whole string that was really on the page. A half-sentence ending in an
 * ellipsis would be quoted back as a literal and refused by the gate, which is
 * a worse failure than not having a name at all.
 */
const MAX_MARK_NAME = 120;

/**
 * The longest a mark's `text` may be.
 *
 * This one IS truncated, because it is prose for a reader rather than a string
 * anything will match on. A whole panel is still not a verdict -- but it is
 * useful context for deciding which part of the panel the verdict is about,
 * which is a judgement the author can make and the recorder cannot.
 */
const MAX_MARK_TEXT = 400;

export interface PickResult {
  target: AnnotationTarget;
  /** Shared by every mark made in one picker session. */
  groupId: string;
  /** 1-based, in the order the tester pointed. */
  index: number;
}

export class ElementPicker {
  private highlight: HTMLDivElement | null = null;
  private hint: HTMLDivElement | null = null;
  private hovered: Element | null = null;
  private onMark: ((mark: PickResult) => void) | null = null;
  private resolve: (() => void) | null = null;

  /** How many levels above the hovered node the mark has been widened to. */
  private widen = 0;
  private groupId = '';
  private marks: string[] = [];

  /** A getter rather than the instance: the recorder builds a fresh
   *  `Redactor` on every `start()`, and a picker holding the previous one
   *  would assign placeholders from a table the recording no longer uses. */
  constructor(private readonly redactor: () => Redactor) {}

  get active(): boolean {
    return this.resolve !== null;
  }

  /**
   * Enter picking mode.
   *
   * `onMark` fires once per accepted click and the picker stays open. The
   * promise resolves when the tester leaves picking mode, which is the only
   * thing the caller has to wait for -- every mark has already been reported by
   * then.
   */
  start(onMark: (mark: PickResult) => void): Promise<void> {
    if (this.resolve) return Promise.resolve();

    this.onMark = onMark;
    this.widen = 0;
    this.marks = [];
    this.groupId = `mk_${Date.now().toString(36)}`;

    this.mount();
    // Capture phase everywhere: the page may well stop propagation on its own
    // handlers, and a tester pointing at a control must not also trigger it.
    document.addEventListener('mousemove', this.onMove, true);
    document.addEventListener('click', this.onClick, true);
    document.addEventListener('keydown', this.onKey, true);

    return new Promise<void>((resolve) => {
      this.resolve = resolve;
    });
  }

  cancel(): void {
    this.finish();
  }

  // ------------------------------------------------------------------

  private onMove = (event: MouseEvent): void => {
    const element = this.elementUnder(event);
    if (!element || element === this.hovered) return;
    this.hovered = element;
    // A new element under the cursor is a new decision. Carrying the previous
    // widen level over would outline an ancestor of something the tester has
    // stopped looking at.
    this.widen = 0;
    this.draw();
  };

  private onClick = (event: MouseEvent): void => {
    if (!this.resolve) return;
    // The click belongs to the picker, not to the application. Without this a
    // tester marking "the confirmation banner" also navigates away from it.
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const under = this.elementUnder(event);
    if (under && under !== this.hovered) {
      this.hovered = under;
      this.widen = 0;
    }
    const element = this.marked();
    if (!element) return;

    const target = this.describe(element);

    // A mark with no words in it is still not a mark.
    //
    // What changed is what counts as words. `nameOf` returns "" for an unnamed
    // `<div>`, which is exactly what a commercial site's mini-cart panel is --
    // both real marks made with the first version of this tool came back
    // `{role: "div", name: ""}` on the same `#ui-id-17`, and the tester got no
    // feedback either time. The ladder in `describe` now reaches inside such a
    // container for a string that is really on the page, so this fires only
    // for an element that genuinely contains no text anywhere: an empty
    // wrapper, a spacer, an image with no alt.
    //
    // Refusing is still the honest answer, and the picker still stays open.
    if (!target.name && !target.value) {
      this.say('Nothing to quote there — that element has no text in it at all.');
      return;
    }

    this.marks.push(target.name || target.value || '');
    this.onMark?.({ target, groupId: this.groupId, index: this.marks.length });
    this.draw();
  };

  private onKey = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.cancel();
      return;
    }
    // Widen and narrow. The alternative -- resolving to the nearest
    // "meaningful" ancestor on hover -- means clicking one thing and recording
    // another, and a tester who cannot see what will be stored is back to
    // where this feature started.
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      event.stopPropagation();
      this.widen = Math.max(0, this.widen + (event.key === 'ArrowUp' ? 1 : -1));
      this.draw();
    }
  };

  /** The page's own node under the cursor, never one of ours. */
  private elementUnder(event: MouseEvent): Element | null {
    const found = document.elementFromPoint(event.clientX, event.clientY);
    if (!found || found === this.highlight || found === this.hint) return null;
    if (found === document.documentElement || found === document.body) return null;
    return found;
  }

  /**
   * What would be recorded right now: the hovered node, walked up `widen`
   * levels. Stops before `body`, which is the whole page rather than a thing
   * anybody is verifying.
   */
  private marked(): Element | null {
    if (!this.hovered) return null;
    let element: Element = this.hovered;
    for (let i = 0; i < this.widen; i++) {
      const parent: Element | null = element.parentElement;
      if (!parent || parent === document.body || parent === document.documentElement) break;
      element = parent;
    }
    return element;
  }

  /**
   * What the tester pointed at, in the same vocabulary the recorder uses for
   * everything else: role and accessible name first, selectors as the fallback
   * chain. Reusing `roleOf`/`nameOf`/`selectorsFor` is not tidiness -- an
   * annotation described differently from the events around it could not be
   * matched to a step or grounded against a snapshot.
   */
  private describe(element: Element): AnnotationTarget {
    const raw = rawValueOf(element);
    const name = this.handleFor(element);
    const text = this.visibleText(element);
    const ordinal = ordinalOf(element);

    return {
      role: roleOf(element) || element.tagName.toLowerCase(),
      name,
      // SS7.1 is absolute: redaction happens in the page, before anything is
      // persisted. A tester may well point at the field they just typed a
      // password into.
      ...(raw ? { value: this.redactor().redactFieldValue(element, raw) } : {}),
      ...(text && text !== name ? { text } : {}),
      ...(ordinal !== undefined ? { ordinal } : {}),
      selectors: selectorsFor(element),
    };
  }

  /**
   * A short string that is really on the page and names this thing.
   *
   * Three rungs, and every one of them returns a WHOLE string rather than a
   * truncation. An accessible name is a property of controls and landmarks;
   * the tester points at what they can SEE, and the thing worth checking is
   * very often a bare `<span>` inside an unnamed wrapper -- a price, a count, a
   * product name. The third rung is what makes a container markable: a product
   * card has no name of its own and no text of its own, and the first named
   * thing inside it is the product's title, which is exactly what a reader
   * would call the card.
   *
   * Redacted through the page-content path (`redactKnownSecrets` -- the exact
   * values the tester typed, never a shape scan), because SS7.1 is absolute.
   */
  private handleFor(element: Element): string {
    const own = nameOf(element) || ownText(element);
    const candidate = fits(own) ? own : firstNamedText(element);
    return candidate ? this.redactor().redactKnownSecrets(candidate) : '';
  }

  /**
   * Everything this element says, for a reader rather than for a matcher.
   *
   * Capped and truncated, unlike `handleFor`: nothing quotes this as a literal,
   * so an ellipsis costs nothing and the words are worth having. A whole panel
   * is still not a verdict -- it is the context for deciding which part of the
   * panel the verdict is about.
   */
  private visibleText(element: Element): string {
    const text = (element.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    const capped = text.length > MAX_MARK_TEXT ? `${text.slice(0, MAX_MARK_TEXT - 1)}…` : text;
    return this.redactor().redactKnownSecrets(capped);
  }

  /** Replace the hint, for a click the picker is refusing. */
  private say(message: string): void {
    if (this.hint) this.hint.textContent = message;
  }

  private mount(): void {
    this.highlight = document.createElement('div');
    Object.assign(this.highlight.style, {
      position: 'fixed',
      pointerEvents: 'none',
      zIndex: String(Z),
      border: '2px solid #2f6f4f',
      background: 'rgba(47, 111, 79, 0.12)',
      borderRadius: '3px',
      transition: 'all 60ms ease-out',
      display: 'none',
    } satisfies Partial<CSSStyleDeclaration>);

    this.hint = document.createElement('div');
    Object.assign(this.hint.style, {
      position: 'fixed',
      pointerEvents: 'none',
      zIndex: String(Z + 1),
      top: '12px',
      left: '50%',
      transform: 'translateX(-50%)',
      maxWidth: '70vw',
      padding: '6px 12px',
      borderRadius: '6px',
      background: '#1c1f23',
      color: '#fff',
      font: '13px/1.4 system-ui, sans-serif',
      boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
    } satisfies Partial<CSSStyleDeclaration>);
    this.hint.textContent = this.hintText();

    document.documentElement.append(this.highlight, this.hint);
  }

  /**
   * What the hint bar says.
   *
   * This is the whole feedback surface. The popup has to close when picking
   * starts -- a popup with focus swallows the first click on the page -- so a
   * tester who is told nothing here is told nothing at all, which is how the
   * first version taught somebody that marking worked when it had recorded two
   * empty targets.
   */
  private hintText(): string {
    const keys = 'Esc when done · ↑ ↓ to widen or narrow';
    if (!this.marks.length) return `Click what you are verifying · ${keys}`;
    const listed = this.marks.map((m, i) => `${i + 1}. "${clip(m, 40)}"`).join('   ');
    return `Marked ${listed} · click another to compare them · ${keys}`;
  }

  private draw(): void {
    if (this.hint) this.hint.textContent = this.hintText();
    const element = this.marked();
    if (!this.highlight || !element) return;
    const box = element.getBoundingClientRect();
    Object.assign(this.highlight.style, {
      display: 'block',
      top: `${box.top}px`,
      left: `${box.left}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    });
  }

  private finish(): void {
    const resolve = this.resolve;
    this.resolve = null;
    this.onMark = null;
    this.hovered = null;
    this.widen = 0;

    document.removeEventListener('mousemove', this.onMove, true);
    document.removeEventListener('click', this.onClick, true);
    document.removeEventListener('keydown', this.onKey, true);
    this.highlight?.remove();
    this.hint?.remove();
    this.highlight = null;
    this.hint = null;

    resolve?.();
  }
}

// ---------------------------------------------------------------------------

function fits(text: string): boolean {
  return text.length > 0 && text.length <= MAX_MARK_NAME;
}

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

/**
 * The first thing inside this element that has words of its own.
 *
 * Document order, so on a product card it is the title rather than the price
 * -- which is what a reader would call the card, and what makes "the tester
 * marked THIS product" a sentence somebody can write.
 */
function firstNamedText(element: Element): string {
  for (const child of element.querySelectorAll('*')) {
    const text = nameOf(child) || ownText(child);
    if (fits(text)) return text;
  }
  return '';
}

/**
 * Which of its like-tagged siblings this is, from 1, or undefined when it is
 * the only one.
 *
 * This is the field that makes a sort checkable. The css selector has always
 * carried `div.product:nth-of-type(1)` and nothing downstream could read it, so
 * a tester marking the first and second prices of a sorted list handed the
 * pipeline two identical-looking marks and no position at all.
 */
function ordinalOf(element: Element): number | undefined {
  const parent = element.parentElement;
  if (!parent) return undefined;
  const alike = [...parent.children].filter((child) => child.tagName === element.tagName);
  if (alike.length < 2) return undefined;
  const at = alike.indexOf(element);
  return at < 0 ? undefined : at + 1;
}
