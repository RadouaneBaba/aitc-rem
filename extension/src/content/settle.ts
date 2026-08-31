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
 *   3. hard timeout at 5000 ms -> flag `settle_timeout`
 *
 * **A URL change is not one of them, and used to be.** It ARMS the window --
 * it decides what the reason will be called -- but it no longer ends it. The
 * old rule fired `finish('url_change')` from inside the MutationObserver, on
 * the FIRST mutation batch after `location.href` differed, with no quiet
 * window and no in-flight check. That was written for a document replacement,
 * where no further mutations arrive. It is exactly wrong for the `pushState`
 * that every faceted commerce listing uses: the URL changes the instant the
 * control is operated and the results arrive from the network hundreds of
 * milliseconds later, so the `after` snapshot captured the OLD list stored
 * under the NEW url -- a wrong snapshot that reads as a right one.
 *
 * Measured on `rec_MTG3YY559C5U` (Fortnum & Mason, sort a tea listing by price
 * high to low): `evt_003` finished as `url_change` after 571 ms with 12
 * mutations and **one request still in flight**, and its `after` holds
 * `14.95, 14.95, 17.95` -- the unsorted order. `evt_007`, the same code path on
 * the same page, happened to wait 1055 ms and got the sorted list. Same rule,
 * different luck. The verdict the tester had marked by hand was then refused
 * for want of evidence that the recorder had thrown away.
 *
 * So the decision now lives only in the quiet timer, which already had the two
 * conditions that matter, and a navigation is subject to both of them. The
 * cost is real and worth naming: a page whose action opens a request that never
 * completes now waits out the full timeout rather than finishing early on the
 * url. That is bounded at 5s, flagged `settle_timeout`, and strictly better
 * than a confident wrong page.
 */

export const QUIET_MS = 300;
export const TIMEOUT_MS = 5000;

export interface SettleHandle {
  /** Resolves once the page is judged to have responded. */
  done: Promise<SettleInfo>;
  /**
   * Stop waiting now and resolve with `reason`.
   *
   * Two callers, both in `content/index.ts`, and neither is optional.
   *
   * `recording_stopped`: the loop below keeps restarting the quiet window while
   * any request from this action is in flight, and for the LAST action of a
   * session there is no next action to bound that window -- so one
   * never-completing analytics beacon holds it to the full 5s timeout. Measured
   * on a public demo site: the final add-to-cart click, the one the recording
   * was about, was still inside its settle window when the tester stopped, and
   * the tab was then frozen in the background so the timer never fired at all.
   *
   * `superseded`: the tester acted again before this window closed. Nothing
   * else bounds it -- `inFlightFor` bounds request ATTRIBUTION by the next
   * action, not the settle -- so the `after` snapshot went on absorbing the
   * page's response to the NEXT action and attributed it to this one. That is
   * worse than an early snapshot, because it is a wrong one that reads as
   * right: it grounds a false assertion that passes every validator.
   *
   * The reason is REQUIRED. It defaulted to `'quiet'`, which is the one value
   * it can never honestly be: `SettleInfo.reason` is what tells a reader
   * whether the `after` snapshot is the page's considered answer or an early
   * one, and a cancelled window labelled `quiet` says the page settled when
   * nobody waited for it to.
   */
  cancel(reason: SettleReason): void;
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

    // No `finish('url_change')` here. A navigation arms the window; it does
    // not end it. See the module docstring -- ending on the first mutation
    // after the url differed is how a sorted list was captured unsorted.
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
      // Quiet is necessary but not sufficient: a request still in flight means
      // the outcome has not arrived yet, so keep waiting rather than capturing
      // a half-updated page.
      //
      // This is the ONE test now, and a navigation gets it too. A single-page
      // application routes by changing the url first and rendering the answer
      // when the network comes back; treating the url as the finish line
      // captured the page it was leaving.
      if (inFlight() > 0) {
        restartQuiet();
        return;
      }
      // A navigation that replaces the document produces no further mutations
      // to observe, so this timer is the only thing that will ever fire for it.
      // Reaching here means the page is quiet AND drained either way; the url
      // only decides what the reason is called.
      finish(urlChanged?.() ? 'url_change' : 'quiet');
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
    cancel: (reason: SettleReason) => finish(reason),
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
