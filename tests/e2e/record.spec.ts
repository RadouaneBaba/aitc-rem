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
