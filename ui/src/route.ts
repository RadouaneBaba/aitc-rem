/**
 * Three destinations, and therefore a router.
 *
 * There was none: one `?confirm=<id>` query parameter, read once in a lazy
 * `useState` initialiser and cleared with `replaceState` on dismiss. That was a
 * defensible shape for two screens where one of them is reached exactly once,
 * from a link on the extension's export page, and it is the mechanism behind
 * the single worst measured number in this project -- **14 expectation sets on
 * disk, all 14 still `inferred`**. A screen you can only arrive at, never
 * return to, is a screen nobody uses twice.
 *
 * Deliberately about forty lines rather than a routing library. There are three
 * routes, they do not nest, and none of them takes more than one parameter;
 * `history.pushState` plus a `popstate` listener is the whole requirement, and
 * a dependency would be more code to read, not less.
 */

import { useEffect, useState } from 'react';

export type Route =
  | { name: 'review' }
  | { name: 'confirm'; recordingId: string }
  | { name: 'help' };

/**
 * Read the address bar.
 *
 * `?confirm=<id>` is still honoured, and permanently: it is what the
 * extension's export page has always linked to, and every recording made before
 * this change carries that URL in a tab somebody may still have open.
 */
export function parseRoute(url: URL = new URL(window.location.href)): Route {
  const legacy = url.searchParams.get('confirm');
  if (legacy) return { name: 'confirm', recordingId: legacy };

  const path = url.pathname.replace(/\/+$/, '');
  if (path.endsWith('/help')) return { name: 'help' };

  const confirm = /\/confirm\/([^/]+)$/.exec(path);
  if (confirm?.[1]) return { name: 'confirm', recordingId: decodeURIComponent(confirm[1]) };

  return { name: 'review' };
}

export function href(route: Route): string {
  if (route.name === 'confirm') return `/confirm/${encodeURIComponent(route.recordingId)}`;
  if (route.name === 'help') return '/help';
  return '/';
}

/** The current route, and a way to change it that leaves history usable.
 *
 * `pushState` rather than `replaceState`: the back button is how somebody
 * returns from the how-to page to the run they were reading, and treating every
 * navigation as a redirect is what made the confirmation screen a dead end. */
export function useRoute(): [Route, (next: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parseRoute());

  useEffect(() => {
    const onPop = () => setRoute(parseRoute());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = (next: Route) => {
    window.history.pushState(null, '', href(next));
    setRoute(next);
  };

  return [route, go];
}
