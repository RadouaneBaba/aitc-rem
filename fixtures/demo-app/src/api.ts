export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T;
}

export async function post<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, status: res.status, data: (await res.json()) as T };
}

export async function get<T>(path: string): Promise<ApiResult<T>> {
  const res = await fetch(`/api${path}`);
  return { ok: res.ok, status: res.status, data: (await res.json()) as T };
}

export const PRODUCTS = [
  { sku: 'BW-01', name: 'Blue Widget', price: 120 },
  { sku: 'RW-02', name: 'Red Widget', price: 240 },
  { sku: 'GG-03', name: 'Green Gadget', price: 310 },
  { sku: 'PA-04', name: 'Precision Assembly', price: 615 },
];
