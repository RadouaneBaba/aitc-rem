/**
 * esbuild instead of @crxjs/vite-plugin: MV3 needs four entry points with
 * different module formats and no HMR, which is a worse fit for a Vite plugin
 * than for forty lines of bundler config -- and one less compatibility surface
 * between Vite majors.
 *
 * Content scripts and the MAIN-world patch must be classic scripts (IIFE); only
 * the service worker may be an ES module.
 */
import { context, build as esbuild } from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(HERE, 'dist');
const watch = process.argv.includes('--watch');

const common = {
  bundle: true,
  target: 'chrome120',
  logLevel: 'info',
  sourcemap: watch ? 'inline' : false,
  minify: !watch,
  define: { 'process.env.NODE_ENV': JSON.stringify(watch ? 'development' : 'production') },
};

const bundles = [
  { entryPoints: [resolve(HERE, 'src/content/index.ts')], outfile: `${OUT}/content.js`, format: 'iife' },
  { entryPoints: [resolve(HERE, 'src/main-world/netpatch.ts')], outfile: `${OUT}/mainworld.js`, format: 'iife' },
  { entryPoints: [resolve(HERE, 'src/background/serviceWorker.ts')], outfile: `${OUT}/background.js`, format: 'esm' },
  { entryPoints: [resolve(HERE, 'src/popup/popup.ts')], outfile: `${OUT}/popup.js`, format: 'iife' },
  { entryPoints: [resolve(HERE, 'src/export/export.ts')], outfile: `${OUT}/export.js`, format: 'esm' },
  // Narration (SS6.6). Two pages, because an offscreen document can hold the
  // microphone but cannot ask for it -- Chrome suppresses the permission prompt
  // there, so mic.html asks once from a real tab.
  { entryPoints: [resolve(HERE, 'src/offscreen/offscreen.ts')], outfile: `${OUT}/offscreen.js`, format: 'esm' },
  { entryPoints: [resolve(HERE, 'src/offscreen/mic.ts')], outfile: `${OUT}/mic.js`, format: 'esm' },
];

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

if (watch) {
  for (const b of bundles) {
    const ctx = await context({ ...common, ...b });
    await ctx.watch();
  }
  console.log('watching...');
} else {
  await Promise.all(bundles.map((b) => esbuild({ ...common, ...b })));
}

await cp(resolve(HERE, 'manifest.json'), `${OUT}/manifest.json`);
await cp(resolve(HERE, 'src/popup/popup.html'), `${OUT}/popup.html`);
await cp(resolve(HERE, 'src/export/export.html'), `${OUT}/export.html`);
await cp(resolve(HERE, 'src/offscreen/offscreen.html'), `${OUT}/offscreen.html`);
await cp(resolve(HERE, 'src/offscreen/mic.html'), `${OUT}/mic.html`);
console.log(`built -> ${OUT}`);
