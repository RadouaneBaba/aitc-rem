import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  // The recorder is inherently stateful and the extension is a single global
  // instance, so the specs share one browser context in order.
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  reporter: [['list']],
  webServer: {
    command: 'pnpm --filter @aitc-rem/demo-app dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
