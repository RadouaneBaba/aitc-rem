import react from '@vitejs/plugin-react';
import type { Connect, Plugin } from 'vite';
import { defineConfig } from 'vite';

/**
 * The demo API, served as dev-server middleware so the whole fixture is one
 * command. Every endpoint here exists to give the recorder something specific
 * to capture -- a status code to correlate, a delay to time out on, an error
 * shape to ground an assertion against.
 */
function demoApi(): Plugin {
  const orders: { reference: string; total: number; approved: boolean }[] = [];
  let cartCount = 0;

  const json = (res: any, status: number, body: unknown, delayMs = 0) => {
    const send = () => {
      res.statusCode = status;
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(body));
    };
    if (delayMs) setTimeout(send, delayMs);
    else send();
  };

  const readBody = (req: Connect.IncomingMessage): Promise<any> =>
    new Promise((resolve) => {
      let raw = '';
      req.on('data', (c) => (raw += c));
      req.on('end', () => {
        try {
          resolve(raw ? JSON.parse(raw) : {});
        } catch {
          resolve({});
        }
      });
    });

  return {
    name: 'demo-api',
    configureServer(server) {
      server.middlewares.use('/api', async (req, res, next) => {
        const url = new URL(req.url ?? '/', 'http://localhost');
        const path = url.pathname;
        const body = req.method === 'POST' ? await readBody(req) : {};

        // Cross-origin iframe content is loaded from 127.0.0.1 while the app
        // runs on localhost -- same server, genuinely different origin.
        res.setHeader('Access-Control-Allow-Origin', '*');

        if (path === '/login' && req.method === 'POST') {
          if (body.password === 'hunter2') {
            // A fresh sign-in starts a fresh session. This is also what keeps
            // the recorded fixture deterministic across runs: the dev server is
            // reused, so state that survived a sign-in would make the cart
            // badge read 2 on the second recording of the same flow.
            cartCount = 0;
            orders.length = 0;
            return json(res, 200, { token: 'demo-token-abc123', user: body.email });
          }
          return json(res, 401, { error: 'Invalid credentials' });
        }

        if (path === '/cart' && req.method === 'POST') {
          cartCount += 1;
          return json(res, 201, { count: cartCount, item: body.name });
        }

        if (path === '/orders' && req.method === 'POST') {
          const total = Number(body.total ?? 0);
          // Documented 409: the boundary at exactly 500 is deliberately
          // untested by the happy path, so coverage suggestions have something
          // real to find later (SS9.8).
          if (total > 500 && !body.approved) {
            return json(res, 409, {
              error: 'Orders over EUR500 require approval',
              code: 'APPROVAL_REQUIRED',
            });
          }
          const reference = `#${48000 + orders.length + 812}`;
          orders.push({ reference, total, approved: !!body.approved });
          return json(res, 201, { reference, total });
        }

        // Never settles inside the 5s window -- drives `settle_timeout`.
        if (path === '/slow' && req.method === 'POST') {
          return json(res, 200, { ok: true }, 6500);
        }

        if (path === '/upload' && req.method === 'POST') {
          return json(res, 200, { received: body.name ?? 'unknown' });
        }

        if (path === '/reports') {
          return json(res, 200, {
            rows: [
              { id: 'r1', label: 'Weekly revenue', value: 18420 },
              { id: 'r2', label: 'Open tickets', value: 37 },
            ],
          });
        }

        if (path === '/boom' && req.method === 'POST') {
          return json(res, 500, { error: 'Internal server error' });
        }

        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), demoApi()],
  server: {
    port: 5173,
    strictPort: true,
    host: true, // bind both localhost and 127.0.0.1 so the iframe is cross-origin
  },
});
