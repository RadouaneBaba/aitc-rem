import type { NetworkCall } from '../types/recording';

/** How many requests one action may carry into the recording. */
export const MAX_CALLS_PER_EVENT = 12;

/**
 * Keep the requests that say what the application did.
 *
 * SS6.4 specifies what network capture records and never budgets it. On the
 * fixture app that cost nothing -- the only script running was ours. A single
 * click on a commercial home page produced 33 requests, one of them the
 * application's and thirty-two of them tags, and a 50-second recording came to
 * 8.71 MB.
 *
 * Size is the smaller half of the problem. `get_network` hands these to a
 * model, so thirty tracking beacons crowd out the one request that shows the
 * order was placed.
 *
 * The order is the policy. First-party first, because those are the
 * application's; mutating before reads within each group, because a POST is
 * what changes the state a test asserts about; original order within that, so
 * a reader still sees the sequence. Anything past the cap is dropped, and
 * dropping it is safe in a way dropping a snapshot would not be: what goes is
 * third-party reads by construction.
 *
 * Lives in its own file so it can be tested without importing the export page,
 * which calls `chrome.*` at module load.
 */
export function budgetNetwork(calls: NetworkCall[], pageUrl: string): NetworkCall[] {
  if (calls.length <= MAX_CALLS_PER_EVENT) return calls;

  // The PAGE's origin, never `location`. The caller runs on an extension page,
  // so `location.origin` there is `chrome-extension://…` -- measured against
  // that, every request in the recording is third-party and the application's
  // own POST is as droppable as a tracking pixel.
  let pageOrigin = '';
  try {
    pageOrigin = new URL(pageUrl).origin;
  } catch {
    pageOrigin = '';
  }

  const mutating = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
  const rank = (call: NetworkCall): number => {
    let origin = '';
    try {
      origin = new URL(call.url, pageUrl).origin;
    } catch {
      origin = pageOrigin;
    }
    const ours = Boolean(pageOrigin) && origin === pageOrigin;
    if (ours && mutating.has((call.method ?? '').toUpperCase())) return 0;
    if (ours) return 1;
    if (mutating.has((call.method ?? '').toUpperCase())) return 2;
    return 3;
  };

  return calls
    .map((call, index) => ({ call, index, rank: rank(call) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .slice(0, MAX_CALLS_PER_EVENT)
    .sort((a, b) => a.index - b.index)
    .map((entry) => entry.call);
}
