import type { SettleInfo, SettleReason } from '../types/recording';
import { isLiveRegion } from './a11y';

/**
 * SS6.5 -- the `after` snapshot is NOT taken immediately.
 *
 * Naively snapshotting on the next tick captures the state *before* the
 * application has responded, which is the most common way a recorder loses the
 * very evidence the assertion needs. So the snapshot waits for the earliest of:
 *
 *   1. no DOM mutation for 300 ms AND no in-flight request from this action
 *   2. a new alert/status/alertdialog node appears  (capture now, then again
 *      at settle -- toasts routinely vanish within three seconds, and an
 *      assertion about a toast that disappeared is one the system would
 *      otherwise be unable to ground)
 *   3. a URL change completes
 *   4. hard timeout at 5000 ms -> flag `settle_timeout`
 */

export const QUIET_MS = 300;
export const TIMEOUT_MS = 5000;

export interface SettleHandle {
  /** Resolves once the page is judged to have responded. */
  done: Promise<SettleInfo>;
  /** Called the instant a live region appears, ahead of settle. */
  cancel(): void;
}

export interface SettleDeps {
  doc: Document;
  /** Requests started by this action that have not yet completed. */
  inFlight: () => number;
  /** Fired at most once, as soon as a live region shows up. */
  onTransient?: (el: Element) => void;
  /** Set by the history patch when a navigation completes. */
  urlChanged?: () => boolean;
  quietMs?: number;
  timeoutMs?: number;
  now?: () => number;
  /** Injectable so tests can drive time without real waiting. */
  setTimeoutFn?: (fn: () => void, ms: number) => number;
  clearTimeoutFn?: (id: number) => void;
}

export function waitForSettle(deps: SettleDeps): SettleHandle {
  const {
    doc,
    inFlight,
    onTransient,
    urlChanged,
    quietMs = QUIET_MS,
    timeoutMs = TIMEOUT_MS,
    now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now()),
    setTimeoutFn = ((fn: () => void, ms: number) => setTimeout(fn, ms) as unknown as number),
    clearTimeoutFn = ((id: number) => clearTimeout(id)),
  } = deps;

  const startedAt = now();
  let mutationCount = 0;
  let settled = false;
  let quietTimer: number | undefined;
  let hardTimer: number | undefined;
  let transientFired = false;

  let resolveDone!: (info: SettleInfo) => void;
  const done = new Promise<SettleInfo>((res) => (resolveDone = res));

  const observer = new MutationObserver((records) => {
    mutationCount += records.length;

    if (!transientFired && onTransient) {
      const live = findAddedLiveRegion(records);
      if (live) {
        transientFired = true;
        onTransient(live);
      }
    }

    if (urlChanged?.()) return finish('url_change');
    restartQuiet();
  });

  function finish(reason: SettleReason) {
    if (settled) return;
    settled = true;
    if (quietTimer !== undefined) clearTimeoutFn(quietTimer);
    if (hardTimer !== undefined) clearTimeoutFn(hardTimer);
    observer.disconnect();
    resolveDone({
      reason,
      waitedMs: Math.round(now() - startedAt),
      mutationCount,
      inFlightAtEnd: inFlight(),
    });
  }

  function restartQuiet() {
    if (settled) return;
    if (quietTimer !== undefined) clearTimeoutFn(quietTimer);
    quietTimer = setTimeoutFn(() => {
      // A navigation that replaces the document produces no further mutations
      // to observe, so the check has to happen on the timer as well.
      if (urlChanged?.()) {
        finish('url_change');
        return;
      }
      // Quiet is necessary but not sufficient: a request still in flight means
      // the outcome has not arrived yet, so keep waiting rather than capturing
      // a half-updated page.
      if (inFlight() > 0) {
        restartQuiet();
        return;
      }
      finish('quiet');
    }, quietMs);
  }

  try {
    observer.observe(doc, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
      attributeFilter: ['aria-live', 'aria-busy', 'aria-invalid', 'aria-expanded', 'role', 'value', 'class'],
    });
  } catch {
    // A detached or cross-origin document cannot be observed; fall back to the
    // timers alone rather than failing the capture.
  }

  hardTimer = setTimeoutFn(() => finish('timeout'), timeoutMs);
  restartQuiet();

  return {
    done,
    cancel: () => finish('quiet'),
  };
}

function findAddedLiveRegion(records: MutationRecord[]): Element | null {
  for (const record of records) {
    for (const added of Array.from(record.addedNodes)) {
      if (added.nodeType !== Node.ELEMENT_NODE) continue;
      const el = added as Element;
      if (isLiveRegion(el)) return el;
      const nested = el.querySelector?.('[role=alert],[role=status],[role=alertdialog],[aria-live]');
      if (nested) return nested;
    }
    // A live region that already existed and only just gained text counts too:
    // this is how most toast implementations actually work.
    if (record.type === 'characterData' || record.type === 'childList') {
      const target = record.target.nodeType === Node.ELEMENT_NODE
        ? (record.target as Element)
        : record.target.parentElement;
      if (target && isLiveRegion(target) && (target.textContent ?? '').trim()) return target;
    }
  }
  return null;
}
