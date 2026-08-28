import { useState } from 'react';

import { post } from '../api';

export function Login({ onSignedIn }: { onSignedIn: (email: string) => void }) {
    // Left empty so a recorded sign-in genuinely includes typing the address:
  // pre-filling it means the value never changes and there is nothing to record.
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <main className="page">
      <section className="card">
        <h2>Sign in</h2>
        {/*
          The password is deliberately NOT printed here.

          The recorder captures the whole page (2026-08-28), so anything on it
          reaches the recording -- and a value the application DISPLAYS but the
          tester never TYPES cannot be recognised as a secret by anything in
          `Redactor`: nothing distinguishes it from ordinary page text. Printing
          a live credential here would commit a plaintext password into
          `tests/fixtures/*.recording.json`, in a project whose one hard failure
          is a redaction hole.

          The boundary itself is pinned in `redact.test.ts` ("cannot know about
          a secret the tester never typed"), which is the right place for it.
          The password is `hunter2`; it is in `fixtures/demo-app/vite.config.ts`
          and in the e2e suite.
        */}
        <p className="muted">Demo user: tester@example.com — password is in the project README.</p>

        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            const res = await post<{ token?: string; error?: string }>('/login', {
              email,
              password,
            });
            setBusy(false);
            if (res.ok) onSignedIn(email);
            else setError(res.data.error ?? 'Sign in failed');
          }}
        >
          <label htmlFor="email">Email address</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && <div role="alert">{error}</div>}

          <div style={{ marginTop: 16 }}>
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'Signing in...' : 'Sign in'}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
