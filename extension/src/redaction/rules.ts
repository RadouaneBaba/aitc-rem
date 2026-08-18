import type { RedactionCategory } from '../types/recording';

export interface ValueRule {
  category: RedactionCategory;
  /** Base placeholder name. Numbered rules append _1, _2, ... per distinct value. */
  base: string;
  pattern: RegExp;
  /** Distinct values get distinct placeholders, stable within a session (SS7.1). */
  numbered: boolean;
  /** Second gate for patterns that over-match on their own. */
  validate?: (value: string) => boolean;
}

/** Luhn check -- the difference between redacting card numbers and redacting
 *  every 16-digit order reference in the application. */
export function luhn(value: string): boolean {
  const digits = value.replace(/\D/g, '');
  if (digits.length < 13 || digits.length > 19) return false;
  let sum = 0;
  let double = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48;
    if (double) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    double = !double;
  }
  return sum % 10 === 0;
}

/**
 * Order matters: the first rule that matches wins, so the specific and
 * validated rules come before the loose ones.
 *
 * These patterns are deliberately conservative. A false positive is not free --
 * turning "EUR 500" into a placeholder would quietly destroy the assertion the
 * test case is actually about -- so patterns that cannot distinguish a phone
 * number from an order total require punctuation or a country code.
 */
export const VALUE_RULES: ValueRule[] = [
  {
    category: 'card_number',
    base: 'card_number',
    numbered: false,
    pattern: /\b(?:\d[ -]*?){13,19}\b/,
    validate: luhn,
  },
  {
    category: 'email',
    base: 'user_email',
    numbered: true,
    pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/,
  },
  {
    category: 'phone',
    base: 'phone',
    numbered: true,
    // Requires a country code or separators: bare digit runs are far more
    // often quantities, totals and identifiers than phone numbers.
    pattern: /(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{2,4}[ .-]?\d{2,4}(?:[ .-]?\d{2,4})?/,
    validate: (v) => {
      const digits = v.replace(/\D/g, '');
      return digits.length >= 9 && digits.length <= 15;
    },
  },
  {
    category: 'national_id',
    base: 'national_id',
    numbered: false,
    // US SSN shape; project rules (SS7.3) cover other jurisdictions.
    pattern: /\b\d{3}-\d{2}-\d{4}\b/,
  },
];

/** Body keys whose VALUE is sensitive regardless of what the value looks like. */
export const SENSITIVE_KEYS = [
  'password', 'passwd', 'pwd', 'pass',
  'secret', 'token', 'accesstoken', 'refreshtoken', 'idtoken',
  'apikey', 'api_key', 'authorization', 'auth', 'credential', 'credentials',
  'ssn', 'socialsecurity', 'nationalid',
  'cardnumber', 'card_number', 'cc', 'cvv', 'cvc', 'pin',
  'sessionid', 'session_id', 'cookie',
];

/** Headers that are never recorded at all, rather than redacted (SS6.4). */
export const HEADER_DENYLIST = ['authorization', 'cookie', 'set-cookie', 'proxy-authorization'];

/** Everything else is dropped: an allowlist fails safe as headers proliferate. */
export const HEADER_ALLOWLIST = [
  'content-type', 'accept', 'accept-language', 'content-length',
  'cache-control', 'x-requested-with', 'location', 'etag',
];

export interface CustomRule {
  /** Elements matching this selector have their value redacted (SS7.3). */
  selector?: string;
  /** Values matching this regex source are redacted. */
  regex?: string;
  placeholder: string;
}

export interface ProjectRedactionConfig {
  sensitive: CustomRule[];
  /** Explicitly NOT sensitive -- wins over every rule above. */
  allowlist: { selector?: string }[];
}

export const EMPTY_PROJECT_CONFIG: ProjectRedactionConfig = { sensitive: [], allowlist: [] };
