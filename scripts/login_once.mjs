#!/usr/bin/env node
/**
 * Sign in once, by hand, and keep the session for every later replay.
 *
 *     node scripts/login_once.mjs https://www.saucedemo.com/ .auth/saucedemo.json
 *     .venv/Scripts/python -m server.cli run <rec.json> --replay \
 *       --storage-state .auth/saucedemo.json
 *
 * Every recording in this repository is of a public site, so replay has always
 * walked the login flow: three recorded events, and the redacted password comes
 * back through `--replay-param`. That stops being reasonable on the
 * applications a team actually tests. Walking a real login on every replay is
 * slow, it is the most brittle part of the flow, and it trips rate limits and
 * multi-factor prompts -- none of which is a fact about the test case under
 * test.
 *
 * `storageState` is Playwright's standard answer: cookies and local storage,
 * captured from a signed-in context and handed to later ones.
 *
 * **Deliberately manual.** This opens a real browser and waits for a human to
 * sign in, rather than scripting the credentials. Automating it would mean a
 * password in a config file or an environment variable read by the replay path,
 * and this project's one rule about secrets is that they are redacted in the
 * browser before anything is persisted. A human typing into a real login form
 * keeps that intact -- the only thing written here is the resulting session.
 *
 * **The output is a live session. Treat it exactly as `.env` is treated:**
 * gitignored, never committed, regenerated when it expires. Anyone holding the
 * file is signed in as you.
 */

import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { createInterface } from 'node:readline';

const [url, out] = process.argv.slice(2);

if (!url || !out) {
  console.error('usage: node scripts/login_once.mjs <url> <state.json>');
  process.exit(2);
}

const target = resolve(out);

// Headed, and it has to be: the whole point is that a person signs in.
const browser = await chromium.launch({ headless: false });
const context = await browser.newContext();
const page = await context.newPage();

await page.goto(url, { timeout: 60_000 });

console.log(`\nA browser is open at ${url}.`);
console.log('Sign in, get to the page a test would start from, then press Enter here.\n');

await new Promise((done) => {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  rl.question('', () => {
    rl.close();
    done();
  });
});

mkdirSync(dirname(target), { recursive: true });
const state = await context.storageState();
writeFileSync(target, JSON.stringify(state, null, 2), 'utf8');
await browser.close();

const cookies = state.cookies?.length ?? 0;
const origins = state.origins?.length ?? 0;
console.log(`\nWrote ${target}`);
console.log(`  ${cookies} cookie(s), local storage for ${origins} origin(s)`);

// Said out loud rather than left to be discovered by a replay that starts
// signed out anyway. An application holding its session in memory -- the
// fixture app does, in React state -- leaves nothing here for storageState to
// restore, and no amount of saving will change that.
if (!cookies && !origins) {
  console.log(
    '\nNothing was saved: this application keeps its session in memory rather than\n' +
      'in cookies or local storage, so there is nothing for storageState to restore.\n' +
      'Replay will have to walk the login flow, which for a recorded session it can.',
  );
}
