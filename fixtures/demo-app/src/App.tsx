import { useCallback, useState } from 'react';

import { Toast } from './components/Toast';
import { Catalog } from './pages/Catalog';
import { Checkout } from './pages/Checkout';
import { Confirmation } from './pages/Confirmation';
import { Login } from './pages/Login';
import { Receipt } from './pages/Receipt';
import { Reports } from './pages/Reports';
import { Storefront } from './pages/Storefront';

type Page =
  | 'login'
  | 'catalog'
  | 'checkout'
  | 'reports'
  | 'storefront'
  | 'confirmation'
  | 'receipt';

/**
 * The storefront is reachable directly at /storefront, without signing in.
 *
 * It exists to reproduce the scoped-capture defect (see pages/Storefront.tsx),
 * and a recording of that defect should contain the filter clicks and nothing
 * else -- three sign-in events ahead of them would put the thing under test in
 * the second half of a recording whose first half is noise.
 */
function initialPage(): Page {
  if (location.pathname === '/storefront') return 'storefront';
  // The second tab lands here directly, opened from the confirmation page.
  // It has to be reachable without signing in for the same reason /storefront
  // is: a new tab is a fresh document with none of this one's React state.
  if (location.pathname === '/receipt') return 'receipt';
  return 'login';
}

export default function App() {
  const [page, setPage] = useState<Page>(initialPage);
  const [user, setUser] = useState<string | null>(null);
  const [cartCount, setCartCount] = useState(0);
  const [cartTotal, setCartTotal] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [reference, setReference] = useState('');

  const dismissToast = useCallback(() => setToast(null), []);

  // Route changes go through the History API so the recorder's URL-change
  // detection has something real to observe (SS9.2 boundary trigger 2).
  const go = (next: Page) => {
    history.pushState({ page: next }, '', `/${next}`);
    setPage(next);
  };

  return (
    <>
      <header className="appbar">
        <h1>Northwind Orders</h1>
        {user && (
          <nav className="appnav" aria-label="Main">
            <button aria-current={page === 'catalog' ? 'page' : undefined} onClick={() => go('catalog')}>
              Catalogue
            </button>
            <button aria-current={page === 'checkout' ? 'page' : undefined} onClick={() => go('checkout')}>
              Checkout
            </button>
            <button aria-current={page === 'reports' ? 'page' : undefined} onClick={() => go('reports')}>
              Reports
            </button>
            <button aria-current={page === 'storefront' ? 'page' : undefined} onClick={() => go('storefront')}>
              Store
            </button>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 12 }}>
              <span className="muted">Cart</span>
              <span className="cart-badge" aria-label={`Cart contains ${cartCount} items`}>
                {cartCount}
              </span>
            </span>
          </nav>
        )}
      </header>

      {page === 'login' && (
        <Login
          onSignedIn={(email) => {
            setUser(email);
            go('catalog');
          }}
        />
      )}

      {page === 'catalog' && (
        <Catalog
          onAdded={(name, count) => {
            setCartCount(count);
            setCartTotal((t) => t + 120);
            setToast(`${name} added to cart`);
          }}
        />
      )}

      {page === 'checkout' && (
        <Checkout
          cartTotal={cartTotal}
          onConfirmed={(ref) => {
            setReference(ref);
            go('confirmation');
          }}
        />
      )}

      {page === 'reports' && <Reports />}
      {page === 'storefront' && <Storefront />}
      {page === 'confirmation' && <Confirmation reference={reference} />}
      {page === 'receipt' && <Receipt />}

      {toast && <Toast message={toast} onDone={dismissToast} />}
    </>
  );
}
