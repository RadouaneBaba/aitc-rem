import type { RedactionParameter } from '../types/recording';
import {
  EMPTY_PROJECT_CONFIG,
  HEADER_ALLOWLIST,
  HEADER_DENYLIST,
  type ProjectRedactionConfig,
  SENSITIVE_KEYS,
  VALUE_RULES,
} from './rules';

const MAX_BODY_CHARS = 4000;

/**
 * Below this, a known value is too short to replace safely in page text.
 *
 * A tester whose password is `a1` would otherwise have every `a1` on the page
 * -- in a product code, in a URL, mid-word -- turned into `<<password>>`, which
 * is the pattern-scanning mistake in another costume.
 */
const MIN_SECRET_LENGTH = 4;

/**
 * SS7 -- redaction happens in the browser, before anything is written to disk.
 * Raw secrets never exist in a persisted artifact.
 *
 * One Redactor instance per recording session. It owns the placeholder map, so
 * the same email is `<<user_email_1>>` everywhere it appears -- which is what
 * lets the placeholder become a test PARAMETER downstream (SS7.2) instead of
 * noise. That is also why network redaction is done here in the content script
 * rather than in the MAIN world: two worlds would mean two maps and two
 * numberings for one value. Nothing is lost by doing it here, because the page
 * already holds the request bodies it just sent -- the boundary that matters is
 * the one to the service worker and to disk, and nothing crosses that unredacted.
 *
 * ## What is scanned, and what is read exactly
 *
 * The rule is about the tester's INPUT and about transport, never about what the
 * application displayed:
 *
 *   scanned      typed field values, network request/response bodies,
 *                console text, request URLs
 *   read exactly semantic snapshot node names and own text -- what was on screen
 *
 * `redactText` used to run over every node of every snapshot too. On one
 * storefront listing that produced **214 parameters, all classified as phone
 * numbers**, and what the rule actually matches in page text is dates:
 * `"Updated 2026-08-28 14:32"` becomes `<<phone_n>>`. A date on a page is
 * routinely the thing a test asserts on, so the scan was destroying evidence to
 * protect a value the tester never entered.
 *
 * The narrowing is deliberate and it is not a weakening. A secret reaches disk
 * by being typed or by being transported, and both of those paths still scan.
 * `isSecretField` -- password, one-time-code, cc-number, and the name/id
 * heuristic -- decides by CONTEXT rather than by shape, which is why it has
 * never had a false negative worth reporting.
 */
export class Redactor {
  private assigned = new Map<string, string>();
  /** raw value -> placeholder name, for `redactKnownSecrets`. Only values long
   *  enough to be replaced in page text without hitting ordinary words. */
  private known = new Map<string, string>();
  private counts = new Map<string, number>();
  private used = new Map<string, RedactionParameter>();

  constructor(private project: ProjectRedactionConfig = EMPTY_PROJECT_CONFIG) {}

  /** Placeholders actually emitted, for Recording.parameters (SS7.2). */
  parameters(): RedactionParameter[] {
    return [...this.used.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  private placeholderFor(raw: string, base: string, numbered: boolean, category: string): string {
    const key = `${base}::${raw}`;
    let name = this.assigned.get(key);
    if (!name) {
      if (numbered) {
        const n = (this.counts.get(base) ?? 0) + 1;
        this.counts.set(base, n);
        name = `${base}_${n}`;
      } else {
        name = base;
      }
      this.assigned.set(key, name);
      if (raw.length >= MIN_SECRET_LENGTH) this.known.set(raw, name);
    }

    const existing = this.used.get(name);
    if (existing) existing.occurrences += 1;
    else {
      this.used.set(name, {
        name,
        placeholder: `<<${name}>>`,
        category: category as RedactionParameter['category'],
        occurrences: 1,
      });
    }
    return `<<${name}>>`;
  }

  /** A whole field known to be secret by context, e.g. input[type=password]. */
  redactWholeValue(raw: string, base: string, category: string): string {
    if (!raw) return raw;
    return this.placeholderFor(raw, base, false, category);
  }

  /**
   * Replace values ALREADY known to be secret, wherever they appear.
   *
   * This is the scan that page content gets, and it is a different kind of rule
   * from `redactText`: not "does this look like a phone number" -- which ate 214
   * dates on one storefront -- but "is this the exact string the tester typed
   * into a password field". Exact values only, so it cannot touch a price, a
   * product code or a date.
   *
   * It exists because capturing the whole page (2026-08-28) made a case reachable
   * that scoped capture never saw: an application that DISPLAYS a value the
   * tester also typed. A "show password" toggle, a confirmation screen echoing an
   * email, a session id printed on a debug banner -- all of them now land in the
   * snapshot, and none of them match a pattern rule.
   *
   * **The limitation is real and worth stating.** A secret the application
   * displays and the tester never types cannot be recognised by anything here:
   * nothing distinguishes it from ordinary page text. Two answers, and only
   * these two -- a project rule in `ProjectRedactionConfig.sensitive`, which
   * names it up front, or not putting it on the page. Snapshots taken BEFORE the
   * tester first types a value are in the same position, because the value was
   * not a secret yet as far as anything in this file could tell.
   *
   * Longest first, so a value that contains another is replaced whole.
   */
  redactKnownSecrets(text: string): string {
    if (!text || !this.known.size) return text;
    let out = text;
    // Longest first, so a value containing another is replaced whole.
    for (const [raw, name] of [...this.known].sort((a, b) => b[0].length - a[0].length)) {
      if (out.includes(raw)) out = out.split(raw).join(`<<${name}>>`);
    }
    return out;
  }

  /** Scan free text and replace anything a rule recognises. */
  redactText(text: string | null | undefined): string {
    if (!text) return text ?? '';
    let out = text;

    for (const rule of this.project.sensitive) {
      if (!rule.regex) continue;
      out = out.replace(new RegExp(rule.regex, 'g'), (m) =>
        this.placeholderFor(m, rule.placeholder, false, 'custom'),
      );
    }

    for (const rule of VALUE_RULES) {
      const re = new RegExp(rule.pattern.source, rule.pattern.flags.includes('g')
        ? rule.pattern.flags
        : `${rule.pattern.flags}g`);
      out = out.replace(re, (match) => {
        if (rule.validate && !rule.validate(match)) return match;
        return this.placeholderFor(match, rule.base, rule.numbered, rule.category);
      });
    }
    return out;
  }

  /**
   * The value of a form control. `el` decides by context what the text scan
   * cannot: a password field is secret whatever its value looks like.
   */
  redactFieldValue(el: Element | null, raw: string): string {
    if (!raw) return raw;

    if (el) {
      for (const rule of this.project.allowlist) {
        if (rule.selector && safeMatches(el, rule.selector)) return raw;
      }
      for (const rule of this.project.sensitive) {
        if (rule.selector && safeMatches(el, rule.selector)) {
          return this.redactWholeValue(raw, rule.placeholder, 'custom');
        }
      }
      if (isSecretField(el)) return this.redactWholeValue(raw, 'password', 'password');
    }

    return this.redactText(raw);
  }

  /** Recursive key + value scan over a parsed request/response body (SS7.1). */
  redactBody(raw: string | null | undefined): { body: string; truncated: boolean } {
    if (!raw) return { body: '', truncated: false };

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      const scanned = this.redactText(raw);
      return {
        body: scanned.slice(0, MAX_BODY_CHARS),
        truncated: scanned.length > MAX_BODY_CHARS,
      };
    }

    const cleaned = JSON.stringify(this.redactJson(parsed));
    return {
      body: cleaned.slice(0, MAX_BODY_CHARS),
      truncated: cleaned.length > MAX_BODY_CHARS,
    };
  }

  private redactJson(value: unknown, keyHint?: string): unknown {
    if (value === null || value === undefined) return value;

    if (Array.isArray(value)) return value.map((v) => this.redactJson(v, keyHint));

    if (typeof value === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
        out[k] = this.redactJson(v, k);
      }
      return out;
    }

    if (typeof value === 'string') {
      if (keyHint && isSensitiveKey(keyHint)) {
        return this.redactWholeValue(value, normaliseKey(keyHint), 'body_field');
      }
      return this.redactText(value);
    }

    return value;
  }

  /** Headers are allowlisted, and the denylisted ones are never recorded at
   *  all rather than replaced with a placeholder (SS6.4). */
  redactHeaders(headers: Record<string, string>): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [rawKey, value] of Object.entries(headers)) {
      const key = rawKey.toLowerCase();
      if (HEADER_DENYLIST.includes(key)) continue;
      if (!HEADER_ALLOWLIST.includes(key)) continue;
      out[key] = this.redactText(value);
    }
    return out;
  }

  /** Strip credentials that travel in the URL itself. */
  redactUrl(url: string): string {
    try {
      const u = new URL(url, location.href);
      for (const [k] of [...u.searchParams]) {
        if (isSensitiveKey(k)) u.searchParams.set(k, `<<${normaliseKey(k)}>>`);
      }
      u.username = '';
      u.password = '';
      return this.redactText(u.toString());
    } catch {
      return this.redactText(url);
    }
  }
}

function normaliseKey(key: string): string {
  const k = key.toLowerCase().replace(/[^a-z0-9]+/g, '_');
  return k === 'pwd' || k === 'passwd' || k === 'pass' ? 'password' : k;
}

export function isSensitiveKey(key: string): boolean {
  const k = key.toLowerCase().replace(/[^a-z0-9]/g, '');
  return SENSITIVE_KEYS.some((s) => k === s.replace(/[^a-z0-9]/g, '') || k.includes(s.replace(/[^a-z0-9]/g, '')));
}

/** Context-based secret detection: type, autocomplete hint, name and id. */
export function isSecretField(el: Element): boolean {
  const input = el as HTMLInputElement;
  if (input.type === 'password') return true;

  const autocomplete = (el.getAttribute('autocomplete') ?? '').toLowerCase();
  if (autocomplete.includes('password') || autocomplete === 'one-time-code') return true;
  if (autocomplete === 'cc-number' || autocomplete === 'cc-csc') return true;

  const hint = `${el.getAttribute('name') ?? ''} ${el.id ?? ''}`.toLowerCase();
  return isSensitiveKey(hint);
}

function safeMatches(el: Element, selector: string): boolean {
  try {
    return el.matches(selector);
  } catch {
    return false;
  }
}
