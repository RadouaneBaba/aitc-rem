/**
 * Calibrated against every objective this project has on disk, and against the
 * verdict the judge gave the test case each one produced.
 *
 * That is the discipline the binding rules get, and for the same reason: a
 * checker that flags a GOOD objective is a nag, a nag gets ignored, and an
 * ignored coach is worse than none because it occupies the space where a
 * working one would go. The negative cases below are the ones that matter.
 */

import { describe, expect, it } from 'vitest';
import { coachObjective } from './objective';

/** Real objectives whose runs the judge scored `good` or `needs-work`. */
const SHARP = [
  'Check that an order over EUR500 requires approval',
  'Check that adding an item updates the cart badge',
  'Check that an order can be exported after approval',
  'Check the cart badge, then that a large order needs approval',
  // docs/RECORDING.md's own worked examples of a good objective.
  'Check that removing the last item empties the cart',
  'Check that an expired card is rejected at payment',
  'Check that a hamper cannot be upgraded past the largest size',
];

/** Real objectives whose runs the judge scored `bad`. */
const VAGUE = [
  'check if hamper sizes change correctly',
  'check if filters are working correctly',
  'check if i can add cafe products correctly to the bag',
  'I will test if I can add the coffee products correctly to the cart',
  'Exercise the awkward parts of the checkout page',
  // docs/RECORDING.md's own worked examples of a bad objective.
  'Test the checkout page',
  'Cart stuff',
  'Payment flow',
  'Verify the checkout handles slow server-side validation',
];

describe('the objective coach', () => {
  it.each(SHARP)('leaves a sharp objective alone: %s', (text) => {
    const advice = coachObjective(text);
    expect(advice.verdict).toBe('sharp');
    expect(advice.message).toBe('');
  });

  it.each(VAGUE)('flags an objective that names a topic: %s', (text) => {
    expect(coachObjective(text).verdict).not.toBe('sharp');
  });

  it('says nothing at all about an empty box', () => {
    // Blank beats vague, measured. Nagging someone who left it empty would be
    // pushing them toward the worse of the two.
    for (const empty of ['', '   ', '\n']) {
      expect(coachObjective(empty)).toEqual({ verdict: 'empty', message: '' });
    }
  });

  it('tells a tester describing actions that the recorder can already see them', () => {
    const advice = coachObjective('Sign in and add a widget');
    expect(advice.verdict).toBe('actions');
    expect(advice.message).toMatch(/VERIFYING/);
  });

  it('offers clearing the box, which is the counter-intuitive half', () => {
    // No tester would guess that deleting their objective improves the result.
    // It is the project's own measured finding and the whole reason the coach
    // is worth having rather than being a spellchecker.
    expect(coachObjective('check if filters are working correctly').message).toMatch(/blank/i);
  });

  it('never rewrites what the tester typed', () => {
    // SS6.7: the objective outranks the model. The coach returns advice and a
    // verdict, and no replacement text -- there is nowhere for one to go.
    const advice = coachObjective('Test the checkout page');
    expect(Object.keys(advice).sort()).toEqual(['message', 'verdict']);
  });
});
