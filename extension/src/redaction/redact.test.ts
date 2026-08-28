import { beforeEach, describe, expect, it } from 'vitest';

import { Redactor, isSecretField } from './redact';
import { luhn } from './rules';

describe('luhn', () => {
  it('accepts real card numbers and rejects lookalikes', () => {
    expect(luhn('4539578763621486')).toBe(true);
    expect(luhn('4539 5787 6362 1486')).toBe(true);
    // The whole point of the check: a 16-digit order reference is not a card.
    expect(luhn('1234567890123456')).toBe(false);
    expect(luhn('12345')).toBe(false);
  });
});

describe('secret field detection', () => {
  it.each([
    ['<input type="password">', true],
    ['<input type="text" autocomplete="current-password">', true],
    ['<input type="text" autocomplete="cc-number">', true],
    ['<input type="text" name="apiKey">', true],
    ['<input type="text" name="user_token">', true],
    ['<input type="email" name="email">', false],
    ['<input type="text" name="poNumber">', false],
  ])('%s -> %s', (html, expected) => {
    document.body.innerHTML = html;
    expect(isSecretField(document.body.firstElementChild!)).toBe(expected);
  });
});

describe('Redactor', () => {
  let r: Redactor;
  beforeEach(() => {
    r = new Redactor();
  });

  it('replaces a password by context, whatever the value looks like', () => {
    document.body.innerHTML = '<input type="password" value="hunter2">';
    const el = document.body.firstElementChild!;
    expect(r.redactFieldValue(el, 'hunter2')).toBe('<<password>>');
    expect(r.redactFieldValue(el, 'correct horse battery staple')).toBe('<<password>>');
  });

  it('numbers distinct emails and keeps each stable across the session', () => {
    expect(r.redactText('write to tester@example.com')).toBe('write to <<user_email_1>>');
    expect(r.redactText('cc: other@example.com')).toBe('cc: <<user_email_2>>');
    // Same value, same placeholder -- this is what makes it a test PARAMETER
    // rather than noise.
    expect(r.redactText('again tester@example.com')).toBe('again <<user_email_1>>');
  });

  it('redacts card numbers but leaves order references alone', () => {
    expect(r.redactText('card 4539578763621486 ok')).toBe('card <<card_number>> ok');
    expect(r.redactText('order 1234567890123456')).toBe('order 1234567890123456');
  });

  it('does not eat the money the assertion is about', () => {
    // A phone pattern that matched "500" or "48812" would quietly destroy the
    // very assertion the test case exists to make.
    expect(r.redactText('Total is EUR500')).toBe('Total is EUR500');
    expect(r.redactText('Order reference #48812')).toBe('Order reference #48812');
    expect(r.redactText('2 minutes ago')).toBe('2 minutes ago');
  });

  it('redacts plausible phone numbers', () => {
    expect(r.redactText('call +44 20 7946 0958')).toContain('<<phone_1>>');
  });

  it('scans request bodies recursively, by key and by value', () => {
    const { body } = r.redactBody(
      JSON.stringify({
        email: 'tester@example.com',
        password: 'hunter2',
        nested: { apiKey: 'sk-live-1234', total: 500 },
        items: [{ note: 'ping tester@example.com' }],
      }),
    );
    const parsed = JSON.parse(body);
    expect(parsed.password).toBe('<<password>>');
    expect(parsed.nested.apiKey).toBe('<<apikey>>');
    expect(parsed.email).toBe('<<user_email_1>>');
    expect(parsed.items[0].note).toBe('ping <<user_email_1>>');
    // Numbers are left alone: an order total is the assertion, not a secret.
    expect(parsed.nested.total).toBe(500);
  });

  it('never records denylisted headers at all', () => {
    const headers = r.redactHeaders({
      Authorization: 'Bearer abc.def.ghi',
      Cookie: 'session=xyz',
      'Content-Type': 'application/json',
      'X-Internal-Trace': 'abc',
    });
    expect(headers).toEqual({ 'content-type': 'application/json' });
    expect(JSON.stringify(headers)).not.toContain('abc.def.ghi');
  });

  it('strips credentials carried in the URL', () => {
    const url = r.redactUrl('https://user:pw@app.local/orders?token=abc123&page=2');
    expect(url).not.toContain('pw@');
    expect(url).not.toContain('abc123');
    expect(url).toContain('page=2');
  });

  it('reports the placeholders it emitted, for Recording.parameters', () => {
    document.body.innerHTML = '<input type="password">';
    r.redactFieldValue(document.body.firstElementChild!, 'hunter2');
    r.redactText('tester@example.com and tester@example.com');

    const params = r.parameters();
    expect(params.map((p) => p.name).sort()).toEqual(['password', 'user_email_1']);
    expect(params.find((p) => p.name === 'user_email_1')!.occurrences).toBe(2);
    // The raw values must not survive anywhere in the reported parameters.
    expect(JSON.stringify(params)).not.toContain('hunter2');
    expect(JSON.stringify(params)).not.toContain('tester@example.com');
  });

  it('honours project rules and the allowlist', () => {
    const rr = new Redactor({
      sensitive: [{ selector: "[data-field='ssn']", placeholder: 'national_id' }],
      allowlist: [{ selector: '.demo-data' }],
    });
    document.body.innerHTML =
      '<input data-field="ssn" value="x"><input class="demo-data" type="password" value="public">';
    const [ssn, demo] = Array.from(document.body.children);
    expect(rr.redactFieldValue(ssn!, '123-45-6789')).toBe('<<national_id>>');
    // The allowlist wins over every rule above it, including type=password.
    expect(rr.redactFieldValue(demo!, 'public')).toBe('public');
  });
});

/**
 * Capturing the whole page (2026-08-28) made a case reachable that scoped
 * capture never saw: the application DISPLAYING a value the tester also typed.
 * The login page of this project's own fixture app prints its demo credentials,
 * and under scoped capture that text was simply outside the snapshot.
 */
describe('secrets the application displays', () => {
  it('replaces an exact value already known to be secret, wherever it appears', () => {
    const r = new Redactor();
    const field = document.createElement('input');
    field.type = 'password';
    r.redactFieldValue(field, 'hunter2swordfish');

    expect(r.redactKnownSecrets('Demo credentials: tester@example.com / hunter2swordfish')).toBe(
      'Demo credentials: tester@example.com / <<password>>',
    );
  });

  it('leaves page content alone, which is the whole reason it is exact', () => {
    const r = new Redactor();
    const field = document.createElement('input');
    field.type = 'password';
    r.redactFieldValue(field, 'hunter2swordfish');

    // The values the pattern scan used to eat. 214 of them on one storefront.
    for (const text of ['4 990,00 DH', 'SG-001', 'Updated 2026-08-28 14:32:10', '9 of 24']) {
      expect(r.redactKnownSecrets(text)).toBe(text);
    }
  });

  it('will not replace a value short enough to collide with ordinary text', () => {
    const r = new Redactor();
    const field = document.createElement('input');
    field.type = 'password';
    r.redactFieldValue(field, 'a1');

    // Every "a1" on the page would otherwise become <<password>> -- the
    // pattern-scanning mistake in another costume.
    expect(r.redactKnownSecrets('Model a1 costs 500')).toBe('Model a1 costs 500');
  });

  it('cannot know about a secret the tester never typed', () => {
    // Stated as a test because it is the boundary of what this can do, and a
    // limitation nobody has written down is one somebody will assume away. The
    // answers are a project rule naming the value up front, or not putting it
    // on the page.
    const r = new Redactor();
    const displayed = 'Your temporary password is swordfish99';
    expect(r.redactKnownSecrets(displayed)).toBe(displayed);
  });
});
