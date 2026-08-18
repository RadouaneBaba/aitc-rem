import type { SelectorSet } from '../types/recording';
import { nameOf, ownText, roleOf } from './a11y';

/**
 * SS6.2 -- ranked, most-stable first. Only `css` is guaranteed present, and it
 * is the last resort rather than the preference.
 *
 * The ranking matters because these are what a later automation pass would use.
 * A `data-testid` is the most durable thing an application can offer, but most
 * applications offer none, so role+name carries the real weight: it survives
 * restyling and refactoring in a way that a generated class name
 * (`css-1x7f2k`) does not.
 */

const TEST_ID_ATTRS = [
  'data-testid',
  'data-test-id',
  'data-test',
  'data-cy',
  'data-qa',
  'data-automation-id',
];

/** Class names that are clearly machine-generated carry no stability. */
const GENERATED_CLASS = /^(css-[a-z0-9]+|sc-[A-Za-z0-9]+|jsx-\d+|[a-z]+_[a-zA-Z0-9]{5,}|_[a-zA-Z0-9]{5,})$/;

export function selectorsFor(el: Element): SelectorSet {
  const set: SelectorSet = { css: cssPath(el) };

  const testId = testIdOf(el);
  if (testId) set.testId = testId;

  const role = roleOf(el);
  const name = nameOf(el) || ownText(el);
  if (role && name) {
    set.role = `getByRole('${role}', { name: ${JSON.stringify(truncate(name, 80))} })`;
  } else if (role) {
    set.role = `getByRole('${role}')`;
  }

  const text = (name || ownText(el)).trim();
  if (text) set.text = truncate(text, 80);

  return set;
}

function testIdOf(el: Element): string | undefined {
  for (const attr of TEST_ID_ATTRS) {
    const value = el.getAttribute(attr);
    if (value) return `[${attr}="${cssEscape(value)}"]`;
  }
  return undefined;
}

/**
 * A CSS path that actually resolves, built shortest-first: stop as soon as the
 * accumulated selector is unique. Shadow boundaries terminate the path -- the
 * FramePath on the event records how to get through them.
 */
export function cssPath(el: Element): string {
  const root = el.getRootNode() as Document | ShadowRoot;
  const parts: string[] = [];
  let current: Element | null = el;

  while (current && current.nodeType === Node.ELEMENT_NODE) {
    if (current.id && isStableId(current.id)) {
      parts.unshift(`#${cssEscape(current.id)}`);
      break;
    }

    parts.unshift(segmentFor(current));

    const candidate = parts.join(' > ');
    if (isUnique(root, candidate)) break;

    const parent: Element | null = current.parentElement;
    if (!parent) break;
    current = parent;
  }

  return parts.join(' > ');
}

function segmentFor(el: Element): string {
  const tag = el.tagName.toLowerCase();

  const stableClasses = Array.from(el.classList)
    .filter((c) => !GENERATED_CLASS.test(c))
    .slice(0, 2);
  let segment = tag + stableClasses.map((c) => `.${cssEscape(c)}`).join('');

  // Disambiguate against siblings that would match the same segment.
  const parent = el.parentElement;
  if (parent) {
    const twins = Array.from(parent.children).filter((c) => c.tagName === el.tagName);
    if (twins.length > 1) {
      segment += `:nth-of-type(${twins.indexOf(el) + 1})`;
    }
  }
  return segment;
}

function isUnique(root: Document | ShadowRoot, selector: string): boolean {
  if (!selector) return false;
  try {
    return root.querySelectorAll(selector).length === 1;
  } catch {
    return false;
  }
}

/** React and friends mint ids like `mui-4471` that change every mount. */
function isStableId(id: string): boolean {
  if (/^[a-z]+-?\d{3,}$/i.test(id)) return false;
  if (/^:r[0-9a-z]+:$/i.test(id)) return false; // React useId
  if (/^[0-9a-f]{8}-[0-9a-f]{4}/i.test(id)) return false; // uuid
  return true;
}

function cssEscape(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(value);
  return value.replace(/([^\w-])/g, '\\$1');
}

function truncate(s: string, n: number): string {
  const flat = s.replace(/\s+/g, ' ').trim();
  return flat.length > n ? `${flat.slice(0, n - 1)}…` : flat;
}
