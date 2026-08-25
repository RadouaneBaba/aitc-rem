import { describe, expect, it } from 'vitest';
import { MAX_CALLS_PER_EVENT, budgetNetwork } from './budget';
import type { NetworkCall } from '../types/recording';

/**
 * SS6.4 specifies what network capture records and never budgets it. On the
 * fixture app that cost nothing; on a commercial site one click produced 33
 * requests, one of them the application's and thirty-two of them tags, and a
 * 50-second recording came to 8.71 MB.
 *
 * Size is the smaller half. `get_network` hands these to a model, so thirty
 * tracking beacons crowd out the one request that shows what the application
 * did.
 */

const APP = 'https://shop.example.com/checkout';

function call(url: string, method = 'GET', id = url): NetworkCall {
  return {
    id,
    method,
    url,
    status: 200,
    startTime: 0,
    initiator: 'fetch',
  } as NetworkCall;
}

function many(n: number, make: (i: number) => NetworkCall): NetworkCall[] {
  return Array.from({ length: n }, (_, i) => make(i));
}

describe('budgetNetwork', () => {
  it('leaves a normal action untouched', () => {
    const calls = many(4, (i) => call(`https://shop.example.com/api/${i}`));
    expect(budgetNetwork(calls, APP)).toEqual(calls);
  });

  it('keeps the application request when the analytics drown it', () => {
    // The shape of the real failure: one POST that matters, thirty beacons.
    const beacons = many(30, (i) => call(`https://collect.analytics.io/t?e=${i}`, 'POST'));
    const theOne = call('https://shop.example.com/api/orders', 'POST', 'orders');
    const kept = budgetNetwork([...beacons.slice(0, 15), theOne, ...beacons.slice(15)], APP);

    expect(kept).toHaveLength(MAX_CALLS_PER_EVENT);
    expect(kept.map((c) => c.id)).toContain('orders');
  });

  it('is judged against the page, not against wherever this code runs', () => {
    // This function runs on an extension page, so `location.origin` is
    // `chrome-extension://…`. Measured against that, EVERY request in the
    // recording is third-party and the application's own POST is as droppable
    // as a tracking pixel. The page URL is the only thing that says whose
    // request this was.
    const beacons = many(20, (i) => call(`https://collect.analytics.io/t?e=${i}`, 'POST'));
    const ours = call('https://shop.example.com/api/orders', 'POST', 'orders');
    const kept = budgetNetwork([...beacons, ours], APP);

    expect(kept.map((c) => c.id)).toContain('orders');
  });

  it('keeps the original order of whatever survives', () => {
    // A reader still has to be able to follow the sequence. Ranking decides
    // WHAT is kept; it must not decide what order it is read in.
    const calls = [
      call('https://collect.analytics.io/a', 'POST', 'a'),
      call('https://shop.example.com/api/one', 'GET', 'one'),
      call('https://collect.analytics.io/b', 'POST', 'b'),
      call('https://shop.example.com/api/two', 'POST', 'two'),
      ...many(20, (i) => call(`https://collect.analytics.io/x${i}`, 'GET', `x${i}`)),
    ];
    const kept = budgetNetwork(calls, APP);
    const positions = kept.map((c) => calls.findIndex((o) => o.id === c.id));
    expect(positions).toEqual([...positions].sort((x, y) => x - y));
  });

  it('does not drop anything when the page URL is unusable', () => {
    // An unparseable page URL means we cannot tell whose request is whose.
    // Ranking then has no basis, and the cap still applies -- but nothing
    // first-party may be preferentially discarded on a guess.
    const calls = many(20, (i) => call(`https://shop.example.com/api/${i}`, 'POST', `n${i}`));
    const kept = budgetNetwork(calls, 'not a url');
    expect(kept).toHaveLength(MAX_CALLS_PER_EVENT);
    expect(kept.map((c) => c.id)).toEqual(calls.slice(0, MAX_CALLS_PER_EVENT).map((c) => c.id));
  });
});
