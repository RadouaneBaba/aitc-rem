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
 */

import { nameOf, rawValueOf, roleOf } from './a11y';
import { selectorsFor } from './selectors';
import type { Redactor } from '../redaction/redact';
import type { AnnotationTarget } from '../types/recording';

/** Big enough to sit above anything an application is likely to use. */
const Z = 2147483000;

export interface PickResult {
  target: AnnotationTarget;
}

export class ElementPicker {
  private highlight: HTMLDivElement | null = null;
  private hint: HTMLDivElement | null = null;
  private hovered: Element | null = null;
  private resolve: ((result: PickResult | null) => void) | null = null;

  /** A getter rather than the instance: the recorder builds a fresh
   *  `Redactor` on every `start()`, and a picker holding the previous one
   *  would assign placeholders from a table the recording no longer uses. */
  constructor(private readonly redactor: () => Redactor) {}

  get active(): boolean {
    return this.resolve !== null;
  }

  /** Enter picking mode. Resolves with the chosen element, or null if cancelled. */
  start(): Promise<PickResult | null> {
    if (this.resolve) return Promise.resolve(null);

    this.mount();
    // Capture phase everywhere: the page may well stop propagation on its own
    // handlers, and a tester pointing at a control must not also trigger it.
    document.addEventListener('mousemove', this.onMove, true);
    document.addEventListener('click', this.onClick, true);
    document.addEventListener('keydown', this.onKey, true);

    return new Promise<PickResult | null>((resolve) => {
      this.resolve = resolve;
    });
  }

  cancel(): void {
    this.finish(null);
  }

  // ------------------------------------------------------------------

  private onMove = (event: MouseEvent): void => {
    const element = this.elementUnder(event);
    if (!element || element === this.hovered) return;
    this.hovered = element;
    this.draw(element);
  };

  private onClick = (event: MouseEvent): void => {
    if (!this.resolve) return;
    // The click belongs to the picker, not to the application. Without this a
    // tester marking "the confirmation banner" also navigates away from it.
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const element = this.elementUnder(event);
    this.finish(element ? { target: this.describe(element) } : null);
  };

  private onKey = (event: KeyboardEvent): void => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    this.cancel();
  };

  /** The page's own node under the cursor, never one of ours. */
  private elementUnder(event: MouseEvent): Element | null {
    const found = document.elementFromPoint(event.clientX, event.clientY);
    if (!found || found === this.highlight || found === this.hint) return null;
    if (found === document.documentElement || found === document.body) return null;
    return found;
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
    return {
      role: roleOf(element) || element.tagName.toLowerCase(),
      name: nameOf(element),
      // SS7.1 is absolute: redaction happens in the page, before anything is
      // persisted. A tester may well point at the field they just typed a
      // password into.
      ...(raw ? { value: this.redactor().redactFieldValue(element, raw) } : {}),
      selectors: selectorsFor(element),
    };
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
    this.hint.textContent = 'Click what you are verifying · Esc to cancel';
    Object.assign(this.hint.style, {
      position: 'fixed',
      pointerEvents: 'none',
      zIndex: String(Z + 1),
      top: '12px',
      left: '50%',
      transform: 'translateX(-50%)',
      padding: '6px 12px',
      borderRadius: '6px',
      background: '#1c1f23',
      color: '#fff',
      font: '13px/1.4 system-ui, sans-serif',
      boxShadow: '0 2px 10px rgba(0,0,0,0.25)',
    } satisfies Partial<CSSStyleDeclaration>);

    document.documentElement.append(this.highlight, this.hint);
  }

  private draw(element: Element): void {
    if (!this.highlight) return;
    const box = element.getBoundingClientRect();
    Object.assign(this.highlight.style, {
      display: 'block',
      top: `${box.top}px`,
      left: `${box.left}px`,
      width: `${box.width}px`,
      height: `${box.height}px`,
    });
  }

  private finish(result: PickResult | null): void {
    const resolve = this.resolve;
    this.resolve = null;
    this.hovered = null;

    document.removeEventListener('mousemove', this.onMove, true);
    document.removeEventListener('click', this.onClick, true);
    document.removeEventListener('keydown', this.onKey, true);
    this.highlight?.remove();
    this.hint?.remove();
    this.highlight = null;
    this.hint = null;

    resolve?.(result);
  }
}
