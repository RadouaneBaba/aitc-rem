import { useMemo, useState } from 'react';

/**
 * The keyhole fixture.
 *
 * This page exists for one reason: to reproduce, on demand and in a test, the
 * defect the 2026-08-28 review found on real commercial sites.
 *
 * `scopeRootFor` (extension/src/content/snapshot.ts) walks from the clicked
 * element to its NEAREST landmark. So the shape below is not decoration --
 * every part of it is load-bearing:
 *
 *   <main>                                   <- landmark
 *     <section aria-labelledby>  role=region <- landmark, and it is SMALL
 *       [ ] In stock                         <- the tester clicks HERE
 *     </section>
 *     <p>Showing 24 of 24 products</p>       <- the thing under test, OUTSIDE
 *     <ul> 24 product cards </ul>            <- also outside
 *   </main>
 *
 * Clicking the checkbox scopes the snapshot to the filter widget, so `before`
 * and `after` are both the widget, the widget did not change, and the diff is
 * EMPTY. The count going 24 -> 9 -- the entire object of the test -- is never
 * captured. Click anywhere in the page body instead and the whole of <main> is
 * captured and the same change is obvious. That is the bug, exactly.
 *
 * Deliberately NO aria-live on the results count. The real storefront had one
 * ("Results updated."), live regions are collected document-wide regardless of
 * scope, and it would half-rescue the broken recorder -- which is how that
 * recording produced a claim that was grounded and said nothing. Without it the
 * regression test is binary: before the capture fix the diff is empty, after it
 * the count change is right there.
 *
 * The numbers are chosen to match the case in docs/REBUILD_PLAN.md: filtering
 * to in-stock takes the list from 24 products to 9.
 */

interface Product {
  sku: string;
  name: string;
  brand: string;
  price: number;
  inStock: boolean;
}

const BRANDS = ['Kestrel', 'Meridian', 'Halcyon'];

/** 24 products, of which exactly 9 are in stock. */
const PRODUCTS: Product[] = Array.from({ length: 24 }, (_, i) => ({
  sku: `SG-${String(i + 1).padStart(3, '0')}`,
  name: `${BRANDS[i % 3]} ${['Tower', 'Console', 'Deck', 'Station'][i % 4]} ${2020 + (i % 5)}`,
  brand: BRANDS[i % 3]!,
  price: 4990 + i * 315,
  // 9 of 24, and exactly 3 of those are Kestrel (indices 0, 9 and 18), so
  // stacking the two filters gives 24 -> 9 -> 3 and each step is a distinct,
  // checkable number. Spread through the list so a truncated capture cannot
  // see them all by accident.
  inStock: [0, 2, 5, 7, 9, 13, 16, 18, 22].includes(i),
}));

export function Storefront() {
  const [inStockOnly, setInStockOnly] = useState(false);
  const [brands, setBrands] = useState<string[]>([]);

  const shown = useMemo(
    () =>
      PRODUCTS.filter(
        (p) => (!inStockOnly || p.inStock) && (brands.length === 0 || brands.includes(p.brand)),
      ),
    [inStockOnly, brands],
  );

  const toggleBrand = (brand: string) =>
    setBrands((current) =>
      current.includes(brand) ? current.filter((b) => b !== brand) : [...current, brand],
    );

  return (
    <main className="page storefront">
      <h2>Store</h2>

      <div className="storefront-layout">
        <div className="filters">
          {/* Landmark #1. Small, self-contained, and the nearest landmark to
              every control inside it. */}
          <section className="card filter-group" aria-labelledby="filter-stock-heading">
            <h3 id="filter-stock-heading">Stock status</h3>
            <label className="check">
              <input
                type="checkbox"
                checked={inStockOnly}
                onChange={(e) => setInStockOnly(e.target.checked)}
              />
              In stock
            </label>
            <label className="check">
              <input type="checkbox" checked={!inStockOnly} onChange={() => setInStockOnly(false)} />
              All products
            </label>
          </section>

          {/* Landmark #2, so the fixture has more than one keyhole. */}
          <section className="card filter-group" aria-labelledby="filter-brand-heading">
            <h3 id="filter-brand-heading">Brand</h3>
            {BRANDS.map((brand) => (
              <label className="check" key={brand}>
                <input
                  type="checkbox"
                  checked={brands.includes(brand)}
                  onChange={() => toggleBrand(brand)}
                />
                {brand}
              </label>
            ))}
          </section>
        </div>

        {/* Everything below is OUTSIDE both landmarks above, and is what the
            scoped capture cannot see. */}
        <section className="card results">
          <p className="result-count">
            Showing {shown.length} of {PRODUCTS.length} products
          </p>
          <ul className="product-grid">
            {shown.map((p) => (
              <li className="product" key={p.sku}>
                <h4>{p.name}</h4>
                <p className="sku">{p.sku}</p>
                <p className="price">{p.price} DH</p>
                <p className={p.inStock ? 'stock in' : 'stock out'}>
                  {p.inStock ? 'In stock' : 'Out of stock'}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
