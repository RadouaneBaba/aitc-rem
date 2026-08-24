import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { type BrowserContext, type Page, chromium, expect, test } from '@playwright/test';

import type { Recording } from '../../extension/src/types/recording';

/**
 * Drives the real extension, in a real browser, against the fixture app.
 *
 * This is the test that makes the rest of the pipeline testable. Every stage
 * downstream needs a recording to work on, and hand-recording one before each
 * run is neither repeatable nor something CI can do -- so this produces a
 * deterministic `recording.json` and writes it to tests/fixtures/ for the
 * server-side suites to consume.
 *
 * It runs headed. MV3 extension support in headless Chromium is still uneven,
 * and a recorder that only works headless would be testing the wrong thing.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..');
const EXTENSION = resolve(ROOT, 'extension/dist');
const FIXTURE_OUT = resolve(ROOT, 'tests/fixtures');
const APP = 'http://localhost:5173';

test.describe.configure({ mode: 'serial' });

let context: BrowserContext;
let extensionId: string;

test.beforeAll(async () => {
  context = await chromium.launchPersistentContext('', {
    headless: false,
    args: [`--disable-extensions-except=${EXTENSION}`, `--load-extension=${EXTENSION}`],
  });

  // The service worker registers on first load and tells us the extension id.
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent('serviceworker', { timeout: 30_000 });
  extensionId = new URL(worker.url()).host;
});

test.afterAll(async () => {
  await context?.close();
});

async function startRecording(objective: string): Promise<Page> {
  // Open the application first: the popup is a tab in this harness, and the
  // worker deliberately refuses to record its own UI.
  const page = await context.newPage();
  await page.goto(APP);

  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await popup.fill('#objective', objective);
  await popup.click('#start');
  await expect(popup.locator('#active')).toBeVisible();
  await popup.close();

  await page.bringToFront();
  return page;
}

/**
 * Playwright drives faster than any human, which makes `rapid_sequence` fire on
 * nearly every event and leaves the fixture unrepresentative of what the
 * pipeline will actually see. A short pause between actions is not politeness,
 * it is what makes the recorded fixture resemble a recording.
 */
async function pause(page: Page): Promise<void> {
  await page.waitForTimeout(450);
}

async function stopRecording(): Promise<Recording> {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await popup.click('#stop');
  await popup.close();

  const exportPage = await context.newPage();
  await exportPage.goto(`chrome-extension://${extensionId}/export.html`);
  await exportPage.waitForFunction(() => '__aitcRecording' in window, null, { timeout: 15_000 });

  const recording = (await exportPage.evaluate(
    () => (window as unknown as { __aitcRecording: Recording }).__aitcRecording,
  )) as Recording;

  // The export page runs the generated Ajv validator over what it assembled.
  await expect(exportPage.locator('#validity .ok')).toBeVisible();
  await exportPage.close();
  return recording;
}

test('records a checkout flow into a schema-valid recording.json', async () => {
  const page = await startRecording('Check that an order over EUR500 requires approval');

  // --- sign in -------------------------------------------------------------
  await page.fill('#email', 'tester@example.com');
  await pause(page);
  await page.fill('#password', 'hunter2');
  await pause(page);
  await page.click('button:has-text("Sign in")');
  await pause(page);
  await expect(page.locator('nav.appnav')).toBeVisible();

  // --- add to cart: the outcome is a toast that vanishes in 2.5s -----------
  await page.click('button:has-text("Add Blue Widget to cart")');
  await pause(page);
  await expect(page.locator('.cart-badge')).toHaveText('1');

  // --- checkout ------------------------------------------------------------
  await page.click('nav.appnav button:has-text("Checkout")');
  await pause(page);
  await page.fill('#po', 'PO-4471');
  await pause(page);
  await page.fill('#total', '615');
  await pause(page);
  await page.click('button:has-text("Place order")');
  await pause(page);

  // Over EUR500 without approval: a documented 409 and a role=alert.
  await expect(page.locator('[role=alert]')).toContainText('approval');

  await page.check('input[type=checkbox]');
  await pause(page);
  await page.click('button:has-text("Place order")');
  await pause(page);
  await expect(page.locator('[role=alert].ok')).toHaveText('Order confirmed');

  await page.close();

  // --- assert on the artifact ---------------------------------------------
  const recording = await stopRecording();

  expect(recording.schemaVersion).toBe('1.0');
  expect(recording.objective).toContain('approval');
  expect(recording.events.length).toBeGreaterThan(5);

  // SS7 -- the password must not survive anywhere in the persisted artifact.
  const json = JSON.stringify(recording);
  expect(json).not.toContain('hunter2');
  expect(json).toContain('<<password>>');
  expect(json).not.toContain('tester@example.com');

  // Events are densely ordered, and every one carries both snapshots.
  recording.events.forEach((e, i) => {
    expect(e.seq).toBe(i);
    expect(e.before).toBeTruthy();
    expect(e.after).toBeTruthy();
  });

  // Session time has to actually advance. performance.now() is measured from
  // each document's own time origin, so mixing it with a wall-clock start
  // silently flattens every timestamp to zero and destroys the idle-gap
  // boundary rule the segmenter depends on (SS9.2).
  expect(recording.metadata.durationMs).toBeGreaterThan(100);
  const times = recording.events.map((e) => e.timestamp);
  expect(times[0]).toBeGreaterThanOrEqual(0);
  expect(times[times.length - 1]).toBeGreaterThan(times[0]!);
  expect([...times].sort((a, b) => a - b)).toEqual(times);

  // The confirmation has to be present as retrievable evidence, or no
  // assertion about it could ever be grounded (SS3.2).
  expect(json).toContain('Order confirmed');

  // The mutating request that produced it must have been captured, since
  // mutation_claimed depends on it (SS9.7).
  const mutations = recording.events.flatMap((e) =>
    e.network.filter((n) => n.method === 'POST' && n.url.includes('/api/orders')),
  );
  expect(mutations.length).toBeGreaterThan(0);
  expect(mutations.some((m) => m.status === 201)).toBe(true);
  expect(mutations.some((m) => m.status === 409)).toBe(true);

  // Each mutation belongs to exactly one step. If a request is attributed to
  // every event that happened to be settling when it started, mutation_claimed
  // would pass for steps that mutated nothing (SS9.7).
  expect(mutations).toHaveLength(2);
  const withOrders = recording.events.filter((e) =>
    e.network.some((n) => n.url.includes('/api/orders')),
  );
  expect(withOrders).toHaveLength(2);
  expect(withOrders.every((e) => e.target.name === 'Place order')).toBe(true);

  mkdirSync(FIXTURE_OUT, { recursive: true });
  writeFileSync(
    resolve(FIXTURE_OUT, 'checkout.recording.json'),
    JSON.stringify(recording, null, 2),
    'utf8',
  );
});

test('captures the hard paths: iframe, shadow roots, canvas, slow endpoint', async () => {
  const page = await startRecording('Exercise the awkward parts of the checkout page');

  await page.fill('#email', 'tester@example.com');
  await pause(page);
  await page.fill('#password', 'hunter2');
  await pause(page);
  await page.click('button:has-text("Sign in")');
  await pause(page);
  await page.click('nav.appnav button:has-text("Checkout")');
  await pause(page);

  // Open shadow root -- reachable through composedPath().
  await page
    .locator('delivery-options')
    .locator('input[value=express]')
    .click();

  // Closed shadow root -- unreachable, and must be flagged rather than guessed.
  await page.locator('promo-widget').click({ position: { x: 10, y: 10 } });

  // Cross-origin iframe: served from 127.0.0.1 while the app is on localhost.
  const frame = page.frameLocator('iframe.payment');
  await frame.locator('#cardholder').fill('A Tester');
  await frame.locator('button:has-text("Save payment method")').click();

  // A control with no text, no aria-label and no title: it must be reported
  // as unnameable rather than described.
  await page.locator('form button.secondary >> nth=1').click();
  await pause(page);

  // Canvas -- only coordinates are knowable.
  await page.locator('canvas.signature').click({ position: { x: 40, y: 40 } });

  // Never settles inside the 5s window.
  await page.click('button:has-text("Submit for slow validation")');
  await pause(page);
  await expect(page.locator('text=Slow validation finished')).toBeVisible({ timeout: 15_000 });

  await page.close();
  const recording = await stopRecording();

  const flags = new Set(recording.events.flatMap((e) => e.fidelity));
  const json = JSON.stringify(recording);

  // The card number in the iframe is redacted even though it lives on another
  // origin, in another frame, with its own content script.
  expect(json).not.toContain('4539578763621486');

  // Degrading loudly is the requirement (SS6.8): these must be reported, not
  // silently absent.
  expect(flags).toContain('canvas_interaction');
  expect(flags).toContain('settle_timeout');
  expect(flags).toContain('no_accessible_name');

  // The slow request outlives its own settle window, so it is recorded through
  // the observation stream rather than by the frame that emitted the event.
  // Without that, the one step this scenario is about has no evidence at all.
  const slow = recording.events.find((e) =>
    e.network.some((n) => n.url.includes('/api/slow')),
  );
  expect(slow, 'the slow request must be attributed to a step').toBeTruthy();
  expect(slow!.target.name).toContain('slow validation');

  // Exactly one step should carry it -- not every step that happened to be
  // settling when it started.
  const carriers = recording.events.filter((e) =>
    e.network.some((n) => n.url.includes('/api/slow')),
  );
  expect(carriers).toHaveLength(1);

  // A frame's events carry the path back to the top document, stitched by the
  // service worker because no single frame can see the tree.
  const framed = recording.events.filter((e) => e.target.frame.length > 0);
  expect(framed.length).toBeGreaterThan(0);
  expect(framed[0]!.target.frame[0]).toMatchObject({ kind: 'iframe' });

  mkdirSync(FIXTURE_OUT, { recursive: true });
  writeFileSync(
    resolve(FIXTURE_OUT, 'hardpaths.recording.json'),
    JSON.stringify(recording, null, 2),
    'utf8',
  );
});

/**
 * The annotation path (SS6.7), end to end and in a real browser.
 *
 * This fixture exists because the ranking machinery of SS9.5 had never once
 * been exercised: no recording anywhere contained an annotation or a spoken
 * word, so every assertion the tool has ever made was `inferred` -- a guess at
 * which of the changes on screen was the one under test. `annotated` sits at
 * the top of that ladder and had no UI to produce it at all.
 *
 * Written to its OWN fixture file. Regenerating checkout/hardpaths would
 * invalidate every cassette keyed on their contents, which is ~145 recorded
 * model responses and a day of free-tier quota to rebuild.
 */
test('records what the tester pointed at and what they named', async () => {
  const page = await startRecording('Check that adding an item updates the cart badge');

  await page.fill('#email', 'tester@example.com');
  await pause(page);
  await page.fill('#password', 'hunter2');
  await pause(page);
  await page.click('button:has-text("Sign in")');
  await pause(page);
  await expect(page.locator('nav.appnav')).toBeVisible();

  // The tester names this step themselves. SS6.7 says it is used word for word.
  await annotate('intent_note', 'the tester adds a widget to the cart');
  await page.bringToFront();
  await page.click('button:has-text("Add Blue Widget to cart")');
  await pause(page);
  await expect(page.locator('.cart-badge')).toHaveText('1');

  // ...and then points at the thing they are actually verifying.
  await pick(page, '.cart-badge');

  await page.close();
  const recording = await stopRecording();

  const marked = recording.annotations.filter((a) => a.kind === 'assertion');
  expect(marked).toHaveLength(1);
  // Role and ACCESSIBLE NAME, the same vocabulary every event uses -- an
  // annotation described differently could not be matched to a step or grounded
  // against a snapshot. Note this is the badge's aria-label rather than its
  // visible "1": the accessible name is what `find_text` indexes, so it is the
  // string an assertion quoting this annotation can actually be grounded on.
  expect(marked[0].target?.name).toContain('Cart contains 1');
  expect(marked[0].target?.selectors.css).toBeTruthy();

  const notes = recording.annotations.filter((a) => a.kind === 'intent_note');
  expect(notes).toHaveLength(1);
  expect(notes[0].text).toBe('the tester adds a widget to the cart');

  // Attribution happens at assembly, not in the frame: `assertions.py` reads
  // `CapturedEvent.annotations` to decide whether `annotated` is a claim this
  // recording can support.
  const owning = recording.events.filter((e) =>
    (e.annotations ?? []).some((a) => a.kind === 'assertion'),
  );
  expect(owning).toHaveLength(1);
  // The action that PRODUCED what was marked, not the marking itself. The
  // picker's own click must never be recorded as something the tester did --
  // that would put a step in the test case that never happened.
  expect(owning[0].target.name).toContain('Blue Widget');
  expect(recording.events.some((e) => e.target.name?.includes('Cart contains'))).toBe(false);

  mkdirSync(FIXTURE_OUT, { recursive: true });
  writeFileSync(
    resolve(FIXTURE_OUT, 'annotated.recording.json'),
    JSON.stringify(recording, null, 2),
    'utf8',
  );
});

/** Fire an annotation from the popup, the way a tester would. */
async function annotate(kind: string, text?: string): Promise<void> {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  if (text !== undefined) popup.once('dialog', (d) => void d.accept(text));
  await popup.click(`.ann button[data-kind="${kind}"]`);
  await popup.waitForTimeout(150);
  await popup.close();
}

/**
 * "Mark what I'm verifying": arm the picker from the popup, then click the
 * element in the page. The popup closes itself for the same reason it does for
 * a real tester -- a focused popup swallows the first click on the page.
 */
async function pick(page: Page, selector: string): Promise<void> {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  // The popup closes itself here -- that is the feature, not a race: a focused
  // popup swallows the first click on the page, which is the click that picks.
  await popup.click('#pick').catch(() => undefined);
  await page.waitForTimeout(200);
  if (!popup.isClosed()) await popup.close();

  await page.bringToFront();
  await page.hover(selector);
  await page.click(selector);
  await pause(page);
}

/**
 * Two test cases in one sitting (SS9.3).
 *
 * A tester checks several things in a session -- that is what a session is --
 * and one test case covering all of it is a test nobody can run in isolation
 * and nobody can say has failed for a single reason. Decomposition is the stage
 * that undoes that, and it had never had a recording to do it to: both existing
 * fixtures are a single flow, so "one recording -> N test cases" could be
 * asserted and not shown.
 *
 * The tester presses "New scenario" between the two. That annotation has been
 * in the popup since the beginning and nothing downstream had ever read it.
 */
test('records two flows separated by a scenario break', async () => {
  const page = await startRecording('Check the cart badge, then that a large order needs approval');

  await page.fill('#email', 'tester@example.com');
  await pause(page);
  await page.fill('#password', 'hunter2');
  await pause(page);
  await page.click('button:has-text("Sign in")');
  await pause(page);
  await expect(page.locator('nav.appnav')).toBeVisible();

  // --- first flow: the cart badge ------------------------------------------
  await page.click('button:has-text("Add Blue Widget to cart")');
  await pause(page);
  await expect(page.locator('.cart-badge')).toHaveText('1');

  // The tester says, at the time, that a separate test starts here.
  await annotate('scenario_break');
  await page.bringToFront();

  // --- second flow: the approval rule --------------------------------------
  await page.click('nav.appnav button:has-text("Checkout")');
  await pause(page);
  await page.fill('#po', 'PO-9001');
  await pause(page);
  await page.fill('#total', '900');
  await pause(page);
  await page.click('button:has-text("Place order")');
  await pause(page);
  await expect(page.locator('[role=alert]')).toContainText('approval');

  await page.close();
  const recording = await stopRecording();

  const breaks = recording.annotations.filter((a) => a.kind === 'scenario_break');
  expect(breaks).toHaveLength(1);
  // It lands between the two flows, which is what makes it a boundary rather
  // than a label on one of them.
  const at = breaks[0].timestamp;
  const before = recording.events.filter((e) => e.timestamp < at);
  const after = recording.events.filter((e) => e.timestamp > at);
  expect(before.length).toBeGreaterThan(2);
  expect(after.length).toBeGreaterThan(2);

  mkdirSync(FIXTURE_OUT, { recursive: true });
  writeFileSync(
    resolve(FIXTURE_OUT, 'twoflows.recording.json'),
    JSON.stringify(recording, null, 2),
    'utf8',
  );
});

/**
 * A tester who wanders (SS9.3).
 *
 * A recorded sitting is a person working, and people look for things. Opening
 * Reports while trying to check out is real and is not a test step, and
 * transcribing it into a test case somebody has to execute is how the artifact
 * becomes unusable.
 *
 * `Reports.tsx` says in its own docstring that it exists to be wandered into.
 * Nothing had ever wandered there: `no_pruned_assertion` has skipped on every
 * run this project has made, for want of a recording with a wrong turn in it.
 */
test('records a session with a wrong turn in it', async () => {
  const page = await startRecording('Check that an order over EUR500 requires approval');

  await page.fill('#email', 'tester@example.com');
  await pause(page);
  await page.fill('#password', 'hunter2');
  await pause(page);
  await page.click('button:has-text("Sign in")');
  await pause(page);
  await expect(page.locator('nav.appnav')).toBeVisible();

  // --- the wrong turn ------------------------------------------------------
  // Looking for the order total, finds a reports page, reads it, leaves.
  await page.click('nav.appnav button:has-text("Reports")');
  await pause(page);
  await expect(page.getByRole('heading', { name: 'Reports' })).toBeVisible();
  await page.click('nav.appnav button:has-text("Catalog")');
  await pause(page);

  // --- the actual test -----------------------------------------------------
  await page.click('button:has-text("Add Blue Widget to cart")');
  await pause(page);
  await page.click('nav.appnav button:has-text("Checkout")');
  await pause(page);
  await page.fill('#total', '750');
  await pause(page);
  await page.click('button:has-text("Place order")');
  await pause(page);
  await expect(page.locator('[role=alert]')).toContainText('approval');

  await page.close();
  const recording = await stopRecording();

  // The detour is in the recording -- pruning it is the pipeline's job, and it
  // cannot be judged from a single segment, only against the objective.
  const visited = recording.events.filter((e) => e.url.includes('reports'));
  expect(visited.length).toBeGreaterThan(0);

  mkdirSync(FIXTURE_OUT, { recursive: true });
  writeFileSync(
    resolve(FIXTURE_OUT, 'wander.recording.json'),
    JSON.stringify(recording, null, 2),
    'utf8',
  );
});
