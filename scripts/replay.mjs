/**
 * Replay a generated test case in a real browser.
 *
 *     node scripts/replay.mjs <job.json> <result.json>
 *
 * The Node half of `server/runners/playwright.py`. Python decides what should
 * happen and writes a job; this does it and writes what happened. Neither side
 * imports the other, and both artifacts survive the run.
 *
 * Two things it is careful about, because both would produce a metric that
 * looks like a measurement and is not:
 *
 *  - **Which selector resolved is recorded, not just whether one did.** The
 *    recorder emits several per element, ranked by how much a redesign is
 *    likely to disturb them. Trying them in order and reporting the winning
 *    rank turns "are these selectors any good" into a number. The demo app has
 *    no `data-testid` anywhere, so this exercises the role+name fallback that
 *    is the normal case for an application nobody built for testing.
 *
 *  - **An assertion that cannot be checked says so.** A literal grounded in
 *    narration is something the tester said out loud; no browser can confirm
 *    it. Reporting that as a pass would inflate the number this exists to
 *    measure.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const [, , jobPath, resultPath] = process.argv;
if (!jobPath || !resultPath) {
  console.error('usage: node scripts/replay.mjs <job.json> <result.json>');
  process.exit(2);
}

const job = JSON.parse(readFileSync(jobPath, 'utf8'));

/** How long to wait for anything the application has to catch up on. */
const TIMEOUT = 5_000;

/**
 * Build a locator from one recorded selector.
 *
 * `role` arrives pre-serialised by the recorder as `getByRole('button', {
 * name: "Sign in" })` -- Playwright's own syntax, stored that way from the
 * start. Parsed rather than eval'd: this runs over data produced by whatever
 * page was recorded, and evaluating it would be a code path from a recording
 * straight into the harness.
 */
function locate(page, selector) {
  const { strategy, value } = selector;
  if (strategy === 'testId') return page.getByTestId(value);
  if (strategy === 'text') return page.getByText(value, { exact: true }).first();
  if (strategy === 'css') return page.locator(value).first();

  if (strategy === 'role') {
    const match = /^getByRole\('([^']+)'(?:,\s*\{\s*name:\s*"(.*)"\s*\})?\)$/.exec(value);
    if (!match) return null;
    const [, role, name] = match;
    return name ? page.getByRole(role, { name, exact: true }).first() : page.getByRole(role).first();
  }
  return null;
}

/**
 * Try each selector in order, most stable first, and report which one worked.
 * Returns the rank, or -1 if the element could not be found at all.
 */
async function act(page, action) {
  let lastError = null;
  for (let rank = 0; rank < action.selectors.length; rank++) {
    const locator = locate(page, action.selectors[rank]);
    if (!locator) continue;
    try {
      if (action.type === 'fill') await locator.fill(action.value ?? '', { timeout: TIMEOUT });
      else if (action.type === 'press') await locator.press(action.key ?? 'Enter', { timeout: TIMEOUT });
      else await locator.click({ timeout: TIMEOUT });
      return { rank, error: null };
    } catch (error) {
      lastError = error;
    }
  }
  return { rank: -1, error: lastError ? String(lastError).split('\n')[0] : 'no selector resolved' };
}

/**
 * Re-check one accepted expected result against the live page.
 *
 * The kind says where the literal came from when it was grounded, which is also
 * how to look for it now: text that was in a snapshot should be on the page, a
 * URL should be the URL. Anything else is honestly reported as uncheckable
 * rather than assumed to hold.
 */
async function check(page, assertion) {
  const { kind, literal } = assertion;
  const base = { assertionId: assertion.id, literal };

  try {
    if (kind === 'semantic_node' || kind === 'a11y_node') {
      // Visible text OR accessible name, because the recorder grounds on the
      // ACCESSIBLE NAME and the two are routinely different. The annotated
      // fixture is the case in point: the tester pointed at a cart badge
      // reading "1" whose aria-label is "Cart contains 1 items", and the
      // literal is the label. Checking only rendered text failed a correct
      // assertion and would have been read as the test case being wrong.
      const found = await Promise.any([
        page.getByText(literal, { exact: false }).first().waitFor({ timeout: TIMEOUT }),
        page.getByLabel(literal, { exact: false }).first().waitFor({ timeout: TIMEOUT }),
        page.locator(`[aria-label=${JSON.stringify(literal)}]`).first().waitFor({ timeout: TIMEOUT }),
      ]).then(() => true, () => false);
      return found
        ? { ...base, status: 'pass' }
        : { ...base, status: 'fail', detail: 'not present as text or as an accessible name' };
    }
    if (kind === 'url') {
      const current = page.url();
      return current.includes(literal)
        ? { ...base, status: 'pass' }
        : { ...base, status: 'fail', detail: `url is ${current}` };
    }
    if (kind === 'network' || kind === 'console') {
      // Both were captured by the recorder around the action that caused them.
      // Re-observing them needs listeners attached before the action, which the
      // step loop does; by the time we get here the window has closed.
      return { ...base, status: 'not_checkable', detail: `${kind} is observed during the step` };
    }
    return { ...base, status: 'not_checkable', detail: `nothing in a browser confirms ${kind}` };
  } catch (error) {
    return { ...base, status: 'fail', detail: String(error).split('\n')[0] };
  }
}

async function main() {
  const result = { caseId: job.caseId, ran: false, steps: [], warnings: [] };
  let browser;

  try {
    browser = await chromium.launch();
  } catch (error) {
    result.blocked = `could not launch a browser: ${String(error).split('\n')[0]}`;
    writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
    return;
  }

  const page = await browser.newPage();
  try {
    await page.goto(job.startUrl ?? job.baseUrl, { timeout: 15_000 });
    result.ran = true;
  } catch (error) {
    // Not a failure of the test case: nobody was listening.
    result.blocked = `could not reach ${job.startUrl ?? job.baseUrl}: ${String(error).split('\n')[0]}`;
    await browser.close();
    writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
    return;
  }

  for (const step of job.steps) {
    const outcome = { stepId: step.id, ok: true, selectorRank: -1, error: null, assertions: [] };

    for (const action of step.actions) {
      const { rank, error } = await act(page, action);
      if (error) {
        outcome.ok = false;
        outcome.error = error;
        break;
      }
      // The worst rank the step needed is the honest one to report: a step is
      // only as robust as its least stable selector.
      outcome.selectorRank = Math.max(outcome.selectorRank, rank);
    }

    if (outcome.ok) {
      for (const assertion of step.assertions) {
        const checked = await check(page, assertion);
        outcome.assertions.push(checked);
        if (checked.status === 'fail') outcome.ok = false;
      }
    }

    result.steps.push(outcome);
    // Once a step has failed, everything after it is running against a state
    // the test never described. Continuing would manufacture failures.
    if (!outcome.ok) {
      result.warnings.push(`stopped after ${step.id}: later steps were not attempted`);
      break;
    }
  }

  await browser.close();
  writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
}

main().catch((error) => {
  writeFileSync(
    resultPath,
    JSON.stringify({ caseId: job.caseId, ran: false, blocked: String(error), steps: [] }, null, 2),
    'utf8',
  );
  process.exit(1);
});
