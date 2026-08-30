import { describe, expect, it } from 'vitest';
import { Redactor } from '../redaction/redact';

describe('probe', () => {
  it('what does redactKnownSecrets do', () => {
    const red = new Redactor();
    document.body.innerHTML = '<input id="p" type="password" />';
    const f = document.getElementById('p') as HTMLInputElement;
    f.value = 'hunter2trombone';
    const out = red.redactFieldValue(f, f.value);
    console.log('redactFieldValue ->', JSON.stringify(out));
    console.log('redactKnownSecrets ->', JSON.stringify(red.redactKnownSecrets('hunter2trombone')));
    expect(1).toBe(1);
  });
});
