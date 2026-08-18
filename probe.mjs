import { chromium } from '@playwright/test';
import { resolve } from 'node:path';
const EXT = resolve('extension/dist');
const ctx = await chromium.launchPersistentContext('', {
  headless: false,
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});
let [sw] = ctx.serviceWorkers();
if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 30000 });
const id = new URL(sw.url()).host;

const page = await ctx.newPage();
// Watch every request the page makes and whether it finishes.
const open = new Map();
page.on('request', r => open.set(r, { url: r.url(), method: r.method(), t: Date.now() }));
page.on('requestfinished', r => open.delete(r));
page.on('requestfailed', r => open.delete(r));

await page.goto('http://localhost:5173');
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${id}/popup.html`);
await popup.click('#start');
await popup.close();
await page.bringToFront();

await page.fill('#email', 'tester@example.com');
await page.fill('#password', 'hunter2');
await page.click('button:has-text("Sign in")');
await page.waitForTimeout(600);
await page.click('nav.appnav button:has-text("Checkout")');
await page.waitForTimeout(1200);

console.log('--- still-open requests seen by Playwright ---');
for (const v of open.values()) console.log(' ', v.method, v.url, `${Date.now() - v.t}ms ago`);
await ctx.close();
