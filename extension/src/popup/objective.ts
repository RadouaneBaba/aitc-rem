/**
 * Is this objective a CHECK, or is it a topic?
 *
 * The objective is the strongest single input the tester gives and the one the
 * recorder can never observe for itself -- and `docs/RECORDING.md` holds a
 * measured three-way ablation showing a vague one is **worse than none at
 * all**. It steers the test toward the mechanism it names and away from the
 * outcome; with no objective the tool reads the session and finds the
 * interesting part on its own.
 *
 * Measured again across every recording on disk, against the judge's verdicts:
 *
 *     check if hamper sizes change correctly              -> bad
 *     check if filters are working correctly              -> bad
 *     check if i can add cafe products correctly          -> bad
 *     Exercise the awkward parts of the checkout page     -> bad
 *     Check that an order over EUR500 requires approval   -> good
 *     Check that adding an item updates the cart badge    -> good
 *     Check that an order can be exported after approval  -> needs-work
 *
 * Four of four vague, four of four bad. Five of five sharp, five acceptable.
 *
 * So this is deterministic and runs as the tester types: no model call, no
 * network, no spinner, and nothing to wait for. It NEVER blocks recording and
 * never rewrites what was typed -- the objective is one of the three inputs
 * that outrank the model (SS6.7), and silently improving it inverts the ladder.
 * Same rule as the step library: it recommends, it does not substitute.
 */

export type ObjectiveVerdict = 'empty' | 'sharp' | 'vague' | 'actions';

export interface ObjectiveAdvice {
  verdict: ObjectiveVerdict;
  /** One sentence. Empty when there is nothing worth saying. */
  message: string;
}

/**
 * Words that grade a mechanism instead of naming an outcome. "change
 * correctly" says the tester will know it when they see it; it gives the author
 * nothing to assert on, and it names the mechanism -- sizes changing -- which
 * is what the test then gets written about.
 */
const GRADED = /\b(correctly|properly|appropriately|as expected|works?|working)\b/i;

/** A proposition has one of these. It is what makes an objective checkable. */
const CLAUSE = /\b(that|whether)\b/i;

/** Nouns that name an area of the application rather than a behaviour of it. */
const AREA = /\b(page|flow|form|functionality|feature|section|screen|module|parts?|stuff|behaviou?rs?)\b/i;

/**
 * Verbs that describe a CAPABILITY rather than an outcome. "the checkout
 * handles slow validation" names something the app does in general; it has no
 * state you could look at afterwards and call right or wrong.
 *
 * That is `docs/RECORDING.md`'s own second bad example, and its run produced
 * two expected results -- a redirect and a saved payment method -- that were
 * both true and neither about slow validation.
 *
 * A list, not a theory. Extend it when a real objective escapes it.
 */
const CAPABILITY = /\b(handles?|supports?|manages?|processes|deals with)\b/i;

/** Verbs that say the tester is verifying something. */
const CHECKS = /\b(check|verify|confirm|ensure|assert|make sure|test)\b/i;

/** Verbs that describe doing rather than checking. */
const DOES = /^\s*(sign|log|add|click|open|navigate|go|fill|enter|select|browse|use|exercise|try)\b/i;

export function coachObjective(raw: string): ObjectiveAdvice {
  const text = raw.trim();

  // Silence is a legitimate answer and the ablation says so out loud, so an
  // empty box is never nagged at.
  if (!text) return { verdict: 'empty', message: '' };

  if (GRADED.test(text)) {
    return {
      verdict: 'vague',
      message:
        'This grades a mechanism rather than naming an outcome. Say what should be ' +
        'true — "check that a hamper cannot be upgraded past the largest size" — or ' +
        'clear the box. A vague objective steers the test toward the thing it names ' +
        'and away from the thing you were checking; blank does better than vague.',
    };
  }

  if (!CLAUSE.test(text) && (AREA.test(text) || CAPABILITY.test(text))) {
    return {
      verdict: 'vague',
      message:
        'This names an area of the app, not a check. Which single thing about it ' +
        'should be true? One sentence starting "Check that…". Or clear the box — ' +
        'blank does better than vague here.',
    };
  }

  if (!CHECKS.test(text) && DOES.test(text)) {
    return {
      verdict: 'actions',
      message:
        'This describes what you are going to DO. The recorder can already see ' +
        'that. Say what you are VERIFYING — the one thing that should be true ' +
        'when you are done.',
    };
  }

  return { verdict: 'sharp', message: '' };
}
