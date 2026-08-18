import { computeAccessibleName, getRole, isInaccessible } from 'dom-accessibility-api';

/**
 * SS6.3 -- the practical replacement for CDP's Accessibility.getFullAXTree.
 * `dom-accessibility-api` implements the W3C accname spec (it is what Testing
 * Library uses) and, since 0.7, also resolves implicit roles, so no separate
 * role table is needed.
 */

const LANDMARK_ROLES = new Set([
  'banner', 'navigation', 'main', 'complementary', 'contentinfo',
  'search', 'form', 'region', 'dialog', 'alertdialog',
]);

/** Roles that convey structure but no meaning; the tree reads better flattened. */
const TRANSPARENT_ROLES = new Set(['generic', 'presentation', 'none', 'paragraph', '']);

/** Where outcomes announce themselves. Collected document-wide regardless of
 *  scope, because an outcome routinely appears far from the click (SS6.3). */
export const LIVE_REGION_ROLES = new Set(['alert', 'status', 'log', 'alertdialog', 'progressbar']);

/**
 * Several form controls have NO implicit ARIA role in the spec -- notably
 * `input[type=password]`, and the date/time and colour pickers. Left at '',
 * they are indistinguishable from a structural wrapper and get flattened out
 * of the snapshot: a login step would carry no password field at all. So the
 * ones a tester plainly perceives as controls are given the role they behave
 * as, which is also the vocabulary SS6.3 uses ("button, textbox, heading,
 * alert, status, row, ...").
 */
const INPUT_ROLE_FALLBACK: Record<string, string> = {
  password: 'textbox',
  date: 'textbox',
  'datetime-local': 'textbox',
  month: 'textbox',
  week: 'textbox',
  time: 'textbox',
  color: 'textbox',
  file: 'button',
};

export function roleOf(el: Element): string {
  try {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.trim().split(/\s+/)[0] ?? '';

    const computed = getRole(el) ?? '';
    if (computed) return computed;

    if (el.tagName === 'INPUT') {
      const type = (el as HTMLInputElement).type?.toLowerCase() ?? 'text';
      return INPUT_ROLE_FALLBACK[type] ?? 'textbox';
    }
    // 'generic' would say nothing about a canvas, and the fidelity warning
    // shown next to the step reads better when the role names what it is.
    if (el.tagName === 'CANVAS') return 'canvas';
    if (el.tagName.includes('-')) return el.tagName.toLowerCase();
    return '';
  } catch {
    return '';
  }
}

/** Form controls are never flattened away, whatever their role resolves to. */
export function isFormControl(el: Element): boolean {
  return ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'OPTION', 'METER', 'PROGRESS'].includes(
    el.tagName,
  );
}

export function nameOf(el: Element): string {
  try {
    return computeAccessibleName(el).trim();
  } catch {
    return '';
  }
}

export function isLandmark(role: string): boolean {
  return LANDMARK_ROLES.has(role);
}

export function isTransparent(role: string): boolean {
  return TRANSPARENT_ROLES.has(role);
}

export function isLiveRegion(el: Element): boolean {
  const role = roleOf(el);
  if (LIVE_REGION_ROLES.has(role)) return true;
  const live = el.getAttribute('aria-live');
  return live === 'polite' || live === 'assertive';
}

export function hidden(el: Element): boolean {
  try {
    return isInaccessible(el);
  } catch {
    // happy-dom and other non-layout environments cannot answer this; treating
    // an unknown as visible keeps the snapshot complete rather than empty.
    return false;
  }
}

/** ARIA and native state, in the vocabulary a tester would use. */
export function stateOf(el: Element): string[] {
  const state: string[] = [];
  const input = el as HTMLInputElement;

  if ((el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true') {
    state.push('disabled');
  }
  if (input.type === 'checkbox' || input.type === 'radio') {
    if (input.checked) state.push('checked');
  }
  const ariaChecked = el.getAttribute('aria-checked');
  if (ariaChecked === 'true') state.push('checked');
  if (ariaChecked === 'mixed') state.push('mixed');

  const expanded = el.getAttribute('aria-expanded');
  if (expanded === 'true') state.push('expanded');
  if (expanded === 'false') state.push('collapsed');

  if (el.getAttribute('aria-invalid') === 'true') state.push('invalid');
  if (el.getAttribute('aria-selected') === 'true') state.push('selected');
  if (el.getAttribute('aria-current')) state.push('current');
  if (el.getAttribute('aria-busy') === 'true') state.push('busy');
  if (input.required || el.getAttribute('aria-required') === 'true') state.push('required');
  if (input.readOnly || el.getAttribute('aria-readonly') === 'true') state.push('readonly');

  return state;
}

/**
 * The visible value of a control, pre-redaction.
 * Returns null when the element has no value concept, so that "no value" and
 * "empty value" stay distinguishable downstream.
 */
export function rawValueOf(el: Element): string | null {
  const tag = el.tagName.toLowerCase();

  if (tag === 'select') {
    const sel = el as HTMLSelectElement;
    return [...sel.selectedOptions].map((o) => o.text).join(', ');
  }
  if (tag === 'input') {
    const input = el as HTMLInputElement;
    if (input.type === 'checkbox' || input.type === 'radio') return null;
    if (input.type === 'file') return null;
    return input.value;
  }
  if (tag === 'textarea') return (el as HTMLTextAreaElement).value;

  if ((el as HTMLElement).isContentEditable) return (el as HTMLElement).innerText?.trim() ?? '';

  return null;
}

/** Text a node contributes when it has no accessible name of its own. */
export function ownText(el: Element): string {
  let text = '';
  for (const child of el.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) text += child.textContent ?? '';
  }
  return text.replace(/\s+/g, ' ').trim();
}

/**
 * Is this an element a tester would expect to carry a label?
 *
 * Drives the `no_accessible_name` flag, which SS6.8 frames as a statement about
 * the element that was acted on rather than about the page around it.
 */
export function isInteractiveElement(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  if (['button', 'a', 'select', 'textarea', 'input'].includes(tag)) return true;
  const role = el.getAttribute('role') ?? '';
  return ['button', 'link', 'checkbox', 'radio', 'tab', 'menuitem', 'switch', 'option'].includes(
    role,
  );
}
