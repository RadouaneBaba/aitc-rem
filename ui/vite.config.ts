import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Built into `ui/dist`, which the FastAPI app mounts at `/` when it exists.
// One origin in production means no CORS between the UI and its own API; the
// dev proxy below keeps `pnpm --filter @aitc-rem/ui dev` behaving the same way.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
});
