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
        <p className="muted">Demo credentials: tester@example.com / hunter2</p>

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
