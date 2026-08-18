import { PRODUCTS, post } from '../api';

export function Catalog({ onAdded }: { onAdded: (name: string, count: number) => void }) {
  return (
    <main className="page">
      <section className="card">
        <h2>Catalogue</h2>
        <table>
          <caption className="muted" style={{ captionSide: 'bottom', paddingTop: 8 }}>
            Prices exclude VAT
          </caption>
          <thead>
            <tr>
              <th scope="col">SKU</th>
              <th scope="col">Product</th>
              <th scope="col">Price</th>
              <th scope="col">
                <span aria-hidden="true">&nbsp;</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {PRODUCTS.map((p) => (
              <tr key={p.sku}>
                <td>{p.sku}</td>
                <td>{p.name}</td>
                <td>EUR{p.price}</td>
                <td>
                  <button
                    className="secondary"
                    onClick={async () => {
                      const res = await post<{ count: number }>('/cart', { name: p.name });
                      onAdded(p.name, res.data.count);
                    }}
                  >
                    Add {p.name} to cart
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
