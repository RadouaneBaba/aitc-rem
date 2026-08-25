import { NET_CHANNEL, type MainWorldMessage } from '../shared/messages';

/**
 * SS6.4 -- network capture without CDP.
 *
 * Runs in MAIN world (declared in the manifest, not injected as a <script>
 * tag) so it can see the page's own fetch and XMLHttpRequest. It forwards
 * metadata to the content script, which does the redaction: two worlds would
 * mean two placeholder maps and two numberings for the same email, and nothing
 * is gained by redacting here because the page already holds the bodies it just
 * sent. The boundary that matters is the one to the service worker and to disk.
 *
 * What this misses is stated rather than hidden: requests issued before this
 * script ran, and requests issued by a service worker. Both raise
 * `network_incomplete`, which downgrades the mutation_claimed validator from a
 * rejection to a warning (SS9.7).
 */

const MAX_BODY = 20_000;
let seq = 0;

/**
 * Whose request is this?
 *
 * SS6.4 specifies what network capture records and never budgets it. On the
 * fixture app that cost nothing -- the only script running was ours. On a real
 * commercial site one recording came to 8.71 MB for 50 seconds, ~96 KB per
 * event, because every analytics beacon, ad call and tag-manager round trip
 * had its request AND response body stored in full. `evt_001` alone carried 33
 * requests, twelve of them "mutating" POSTs, essentially all of them tracking.
 *
 * SS17.2 listed "snapshot performance on large enterprise apps" as the main
 * unvalidated capture assumption. Snapshots were fine; network was the thing
 * nobody had budgeted.
 *
 * A third-party request still gets its LINE recorded -- method, url, status --
 * because "this click fired a request to a payment provider" is real evidence
 * about what the application did. What it does not get is its bodies, which is
 * where the megabytes are and which nothing downstream reads: an assertion
 * grounded in an analytics payload is noise by construction (SS9.5), and
 * `bind.NOISE` refuses one anyway.
 */
function isFirstParty(url: string): boolean {
  try {
    return new URL(url, location.href).origin === location.origin;
  } catch {
    // An unparseable URL is a relative one often enough, and relative means
    // same-origin. Erring toward capture: losing a body from the application
    // under test costs evidence, and keeping one extra costs bytes.
    return true;
  }
}

function post(message: MainWorldMessage): void {
  try {
    window.postMessage(message, '*');
  } catch {
    // A body that cannot be structured-cloned is not worth failing the page for.
  }
}

function nextId(): string {
  return `net_${String(++seq).padStart(4, '0')}`;
}

function clip(text: string | undefined | null): string | undefined {
  if (!text) return undefined;
  return text.length > MAX_BODY ? text.slice(0, MAX_BODY) : text;
}

function headersToObject(headers: Headers | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!headers) return out;
  try {
    headers.forEach((value, key) => {
      out[key] = value;
    });
  } catch {
    /* ignore */
  }
  return out;
}

/* ------------------------------ fetch ------------------------------ */

const originalFetch = window.fetch;
if (typeof originalFetch === 'function') {
  window.fetch = async function patchedFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    const id = nextId();
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const url = String(input instanceof Request ? input.url : input);

    const ours = isFirstParty(url);

    let requestBody: string | undefined;
    try {
      if (ours && typeof init?.body === 'string') requestBody = clip(init.body);
    } catch {
      /* ignore */
    }

    post({
      channel: NET_CHANNEL,
      kind: 'start',
      id,
      method,
      url,
      startTime: performance.now(),
      initiator: 'fetch',
      requestBody,
      requestHeaders: headersToObject(
        init?.headers ? new Headers(init.headers) : input instanceof Request ? input.headers : undefined,
      ),
    });

    try {
      const response = await originalFetch.call(this, input as RequestInfo, init);

      // Clone before reading: consuming the caller's body would break the page.
      let responseBody: string | undefined;
      try {
        if (ours) responseBody = clip(await response.clone().text());
      } catch {
        /* opaque or already-consumed responses simply have no body recorded */
      }

      post({
        channel: NET_CHANNEL,
        kind: 'end',
        id,
        status: response.status,
        endTime: performance.now(),
        responseBody,
        responseHeaders: headersToObject(response.headers),
      });
      return response;
    } catch (err) {
      post({
        channel: NET_CHANNEL,
        kind: 'end',
        id,
        endTime: performance.now(),
        failed: true,
      });
      throw err;
    }
  };
}

/* ------------------------- XMLHttpRequest -------------------------- */

const XHR = window.XMLHttpRequest;
if (typeof XHR === 'function') {
  const openOriginal = XHR.prototype.open;
  const sendOriginal = XHR.prototype.send;
  const setHeaderOriginal = XHR.prototype.setRequestHeader;

  const meta = new WeakMap<
    XMLHttpRequest,
    { id: string; method: string; url: string; headers: Record<string, string>; startTime: number }
  >();

  XHR.prototype.open = function patchedOpen(
    this: XMLHttpRequest,
    method: string,
    url: string | URL,
    ...rest: unknown[]
  ) {
    meta.set(this, {
      id: nextId(),
      method: String(method).toUpperCase(),
      url: String(url),
      headers: {},
      startTime: 0,
    });
    // eslint-disable-next-line prefer-rest-params
    return openOriginal.apply(this, arguments as never);
  } as typeof XHR.prototype.open;

  XHR.prototype.setRequestHeader = function patchedSetHeader(
    this: XMLHttpRequest,
    name: string,
    value: string,
  ) {
    const m = meta.get(this);
    if (m) m.headers[name] = value;
    return setHeaderOriginal.call(this, name, value);
  };

  XHR.prototype.send = function patchedSend(
    this: XMLHttpRequest,
    body?: Document | XMLHttpRequestBodyInit | null,
  ) {
    const m = meta.get(this);
    if (m) {
      const ours = isFirstParty(m.url);
      m.startTime = performance.now();
      post({
        channel: NET_CHANNEL,
        kind: 'start',
        id: m.id,
        method: m.method,
        url: m.url,
        startTime: m.startTime,
        initiator: 'xhr',
        requestBody: ours && typeof body === 'string' ? clip(body) : undefined,
        requestHeaders: m.headers,
      });

      this.addEventListener('loadend', () => {
        let responseBody: string | undefined;
        try {
          if (ours && (this.responseType === '' || this.responseType === 'text')) {
            responseBody = clip(this.responseText);
          }
        } catch {
          /* ignore */
        }
        post({
          channel: NET_CHANNEL,
          kind: 'end',
          id: m.id,
          status: this.status || undefined,
          endTime: performance.now(),
          responseBody,
          failed: this.status === 0,
        });
      });
    }
    return sendOriginal.call(this, body);
  };
}

/* --------------------------- navigation ---------------------------- */

// SPA route changes produce no network event and no popstate, but SS9.2 makes a
// URL change a step boundary, so they have to be observable.
for (const method of ['pushState', 'replaceState'] as const) {
  const original = history[method];
  history[method] = function patchedHistory(this: History, ...args: unknown[]) {
    const result = (original as (...a: unknown[]) => unknown).apply(this, args);
    post({ channel: NET_CHANNEL, kind: 'nav', url: location.href, at: performance.now() });
    return result;
  } as typeof history.pushState;
}

window.addEventListener('popstate', () => {
  post({ channel: NET_CHANNEL, kind: 'nav', url: location.href, at: performance.now() });
});

/* ----------------------------- console ----------------------------- */

// The isolated world cannot see the page's console, so errors and warnings are
// forwarded from here. Only those two levels: SS6.2 records errors and warnings,
// not the whole log.
function serialiseArgs(args: unknown[]): string {
  return args
    .map((a) => {
      if (typeof a === 'string') return a;
      if (a instanceof Error) return `${a.name}: ${a.message}`;
      try {
        return JSON.stringify(a);
      } catch {
        return String(a);
      }
    })
    .join(' ')
    .slice(0, 2000);
}

for (const level of ['error', 'warn'] as const) {
  const original = console[level];
  console[level] = function patchedConsole(...args: unknown[]) {
    post({
      channel: NET_CHANNEL,
      kind: 'console',
      level: level === 'warn' ? 'warning' : 'error',
      text: serialiseArgs(args),
      at: performance.now(),
      uncaught: false,
    });
    return original.apply(this, args as never);
  };
}

window.addEventListener('error', (e) => {
  post({
    channel: NET_CHANNEL,
    kind: 'console',
    level: 'error',
    text: e.message || 'Uncaught error',
    at: performance.now(),
    stack: e.error instanceof Error ? e.error.stack?.slice(0, 2000) : undefined,
    uncaught: true,
  });
});

window.addEventListener('unhandledrejection', (e) => {
  const reason = (e as PromiseRejectionEvent).reason;
  post({
    channel: NET_CHANNEL,
    kind: 'console',
    level: 'error',
    text: `Unhandled rejection: ${reason instanceof Error ? reason.message : String(reason)}`,
    at: performance.now(),
    stack: reason instanceof Error ? reason.stack?.slice(0, 2000) : undefined,
    uncaught: true,
  });
});

/* ----------------------- capture completeness ---------------------- */

// Reported once, at install, so the gap is recorded rather than discovered
// later as a mysteriously missing request.
const missedEarly = document.readyState !== 'loading';
const serviceWorkerActive = Boolean(navigator.serviceWorker?.controller);
if (missedEarly || serviceWorkerActive) {
  post({
    channel: NET_CHANNEL,
    kind: 'gaps',
    networkIncomplete: true,
    reason: serviceWorkerActive
      ? 'a service worker is controlling this page; its requests never reach page-context fetch'
      : 'the network patch installed after the document began loading',
  });
}
