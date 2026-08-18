import { useEffect, useState } from 'react';

import { get } from '../api';

/** Somewhere for a tester to wander. Recorded segments here should be
 *  classified `exploratory` and pruned from the narrative (SS9.3). */
export function Reports() {
  const [rows, setRows] = useState<{ id: string; label: string; value: number }[]>([]);

  useEffect(() => {
    get<{ rows: typeof rows }>('/reports').then((r) => setRows(r.data.rows));
  }, []);

  return (
    <main className="page">
      <section className="card">
        <h2>Reports</h2>
        <table>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.label}</td>
                <td>{r.value.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
