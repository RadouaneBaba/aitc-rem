import { Redactor } from '../redaction/redact';
import {
  NET_CHANNEL,
  type EventCaptured,
  type MainWorldMessage,
  type RecorderState,
  type WorkerInbound,
} from '../shared/messages';
import type {
  CapturedEvent,
  ConsoleEntry,
  EventTarget as EventTargetInfo,
  EventType,
  FidelityFlag,
  NetworkCall,
  SelectedFile,
  SemanticSnapshot,
} from '../types/recording';
import { isInteractiveElement, nameOf, rawValueOf, roleOf } from './a11y';
import { diffSnapshots } from './diff';
import { ElementPicker } from './picker';
import { selectorsFor } from './selectors';
import { buildSnapshot } from './snapshot';
import { waitForSettle } from './settle';

/**
 * The recorder proper. Runs in every frame (`all_frames: true`).
 *
 * SS6.2 -- a bundle per user ACTION, not a continuous stream. Scroll, hover and
 * mousemove are recorded as context, never as steps, which here means they are
 * not recorded at all.
 */

const RAPID_SEQUENCE_MS = 150;
const DRAG_THRESHOLD_PX = 12;
const NETWORK_LEAD_MS = 120;

interface PendingInput {
  el: Element;
  initialValue: string;
}

class Recorder {
  private recording = false;
  private startedAt = 0;
  private seq = 0;
  private redactor = new Redactor();

  private netOpen = new Map<string, NetworkCall & { _raw: { req?: string; res?: string } }>();
  /** Start time in session ms, kept for open requests only. */
  private netStarted = new Map<string, number>();
  /** Session ms at which each action began, in order. Lets a settle window
   *  tell its own requests from those a LATER action started while it waited. */
  private actionStarts: number[] = [];
  private consoleSeq = 0;

  private networkIncomplete = false;
  private navPending: { url: string; at: number } | null = null;

  private pendingInput: PendingInput | null = null;
  private lastEventAt = -Infinity;
  private lastClick: { el: Element; at: number } | null = null;
  private pointerDownAt: { x: number; y: number } | null = null;
  private wasDrag = false;

  /** SS6.7's assertion annotation. Shares the recorder's `Redactor` so a value
   *  the tester points at is redacted by the same rules and gets the same
   *  placeholder as the value they typed into it. */
  private picker = new ElementPicker(() => this.redactor);

  /* -------------------------- lifecycle -------------------------- */

  start(startedAt: number): void {
    this.recording = true;
    this.startedAt = startedAt;
    this.redactor = new Redactor();
    this.seq = 0;
  }

  stop(): void {
    this.recording = false;
    this.flushPendingInput();
    this.picker.cancel();
  }

  /**
   * SS6.7 -- "click an element, mark this is what I'm verifying".
   *
   * The result outranks anything the assertion stage could infer (SS9.5), which
   * is the whole point: with nothing but inference the agent has to guess which
   * of the changes on screen was the one under test, and it sometimes picks a
   * true but incidental one.
   *
   * No `eventId` is attached here. A frame does not know which action this
   * belongs to -- the same reason network calls are attributed at assembly
   * rather than in the frame -- so the timestamp is recorded and `export.ts`
   * decides which action owns it.
   */
  async pickAssertion(): Promise<void> {
    if (!this.recording || this.picker.active) return;
    const picked = await this.picker.start();
    if (!picked) return;

    this.report({
      type: 'annotation',
      annotation: {
        // The worker renumbers against the session; this only has to be unique
        // enough to survive the trip.
        id: `ann_${Date.now()}`,
        kind: 'assertion',
        timestamp: this.clock(),
        target: picked.target,
      },
    });
  }

  /**
   * Session time, in ms since the recorder started.
   *
   * performance.now() is measured from each document's OWN time origin, so it
   * is not comparable across frames and is not comparable to the worker's
   * wall-clock start at all. performance.timeOrigin converts it to the one
   * shared base, which is what makes events from an iframe interleave
   * correctly with events from the top document.
   */
  private clock(): number {
    return Math.round(performance.timeOrigin + performance.now() - this.startedAt);
  }

  /** Convert a page-context performance.now() reading to session time. */
  private toSessionTime(perfNow: number): number {
    return Math.round(performance.timeOrigin + perfNow - this.startedAt);
  }

  /* ------------------- page-context signals ---------------------- */

  handleMainWorld(msg: MainWorldMessage): void {
    switch (msg.kind) {
      case 'start': {
        const call: NetworkCall & { _raw: { req?: string; res?: string } } = {
          id: msg.id,
          method: msg.method,
          url: this.redactor.redactUrl(msg.url),
          startTime: this.toSessionTime(msg.startTime),
          initiator: msg.initiator,
          _raw: { req: msg.requestBody },
        };
        const headers = this.redactor.redactHeaders(msg.requestHeaders ?? {});
        if (Object.keys(headers).length) call.requestHeaders = headers;
        this.netOpen.set(msg.id, call);
        this.netStarted.set(msg.id, call.startTime);
        break;
      }
      case 'end': {
        const call = this.netOpen.get(msg.id);
        if (!call) break;
        this.netOpen.delete(msg.id);
        this.netStarted.delete(msg.id);

        const end = this.toSessionTime(msg.endTime);
        call.endTime = end;
        call.durationMs = end - call.startTime;
        if (msg.status !== undefined) call.status = msg.status;
        if (msg.failed) call.failed = true;

        // Bodies are redacted here, in the one place that owns the placeholder
        // map, so the same value gets the same placeholder everywhere.
        if (call._raw.req) {
          const { body, truncated } = this.redactor.redactBody(call._raw.req);
          call.requestBody = body;
          if (truncated) call.bodyTruncated = true;
        }
        if (msg.responseBody) {
          const { body, truncated } = this.redactor.redactBody(msg.responseBody);
          call.responseBody = body;
          if (truncated) call.bodyTruncated = true;
        }
        const headers = this.redactor.redactHeaders(msg.responseHeaders ?? {});
        if (Object.keys(headers).length) call.responseHeaders = headers;

        delete (call as Partial<typeof call>)._raw;
        this.report({ type: 'network', call });
        break;
      }
      case 'nav':
        this.navPending = { url: msg.url, at: this.toSessionTime(msg.at) };
        break;
      case 'gaps':
        this.networkIncomplete = msg.networkIncomplete;
        break;
      case 'console':
        this.report({
          type: 'console',
          entry: {
            id: `con_${String(++this.consoleSeq).padStart(3, '0')}`,
            level: msg.level,
            text: this.redactor.redactText(msg.text),
            timestamp: this.toSessionTime(msg.at),
            ...(msg.stack ? { stack: this.redactor.redactText(msg.stack) } : {}),
            ...(msg.uncaught ? { uncaught: true } : {}),
          },
        });
        break;
    }
  }

  /* ----------------------- user actions -------------------------- */

  /**
   * The element the step should be ABOUT.
   *
   * composedPath() is what sees through open shadow boundaries -- ev.target
   * reports the host instead -- but its first entry is the innermost node,
   * which for `<button><span aria-hidden>x</span></button>` is the span. Taking
   * it verbatim describes the decoration rather than the control: no accessible
   * name, no useful role, and a selector pointing at an icon. Icon buttons are
   * everywhere, so the path is walked outward to the control that was really
   * pressed.
   */
  private targetOf(ev: Event): Element | null {
    const path = typeof ev.composedPath === 'function' ? ev.composedPath() : [];
    const elements = path.filter((n): n is Element => n instanceof Element);

    // Bounded: a few hops reach the enclosing control, but walking all the way
    // up would attribute every click to <main>.
    for (const el of elements.slice(0, 5)) {
      if (isInteractiveElement(el) || el.tagName === 'LABEL') return el;
    }
    return elements[0] ?? (ev.target instanceof Element ? ev.target : null);
  }

  /**
   * True while the tester is choosing an element to mark (SS6.7).
   *
   * The picker cannot suppress these on its own. Both it and the recorder
   * listen on `document` in the capture phase, and listeners on the same
   * target and phase fire in registration order -- the recorder's are attached
   * at module load and the picker's only when it starts, so the recorder sees
   * the click first no matter what the picker does with `stopPropagation`.
   *
   * Without this guard, pointing at the confirmation banner is recorded as the
   * tester having clicked it: a step that never happened, in a test case
   * somebody has to execute.
   */
  private get picking(): boolean {
    return this.picker.active;
  }

  onPointerDown = (ev: PointerEvent): void => {
    if (this.picking) return;
    this.pointerDownAt = { x: ev.clientX, y: ev.clientY };
    this.wasDrag = false;
  };

  onPointerUp = (ev: PointerEvent): void => {
    if (this.picking) return;
    if (!this.pointerDownAt) return;
    const dx = ev.clientX - this.pointerDownAt.x;
    const dy = ev.clientY - this.pointerDownAt.y;
    this.wasDrag = Math.hypot(dx, dy) > DRAG_THRESHOLD_PX;
    this.pointerDownAt = null;
  };

  onClick = (ev: MouseEvent): void => {
    if (this.picking || !this.recording || ev.button !== 0) return;
    const el = this.targetOf(ev);
    if (!el) return;

    // Clicking into a text field is not a step: the value change that follows
    // is. Recording both would double every form interaction.
    if (isTextEntry(el)) return;

    this.lastClick = { el, at: this.clock() };
    this.flushPendingInput();
    void this.capture('click', el, ev);
  };

  onFocusIn = (ev: FocusEvent): void => {
    if (this.picking) return;
    // Moving straight from one field to the next fires no `change` on the
    // first one, so without this flush the earlier edit is simply lost.
    this.flushPendingInput();
    const el = this.targetOf(ev);
    if (!el || !isTextEntry(el)) return;
    this.pendingInput = { el, initialValue: valueOf(el) };
  };

  onChange = (ev: Event): void => {
    if (this.picking || !this.recording) return;
    const el = this.targetOf(ev);
    if (!el) return;

    const tag = el.tagName.toLowerCase();
    const input = el as HTMLInputElement;

    if (tag === 'select') {
      void this.capture('select', el, ev);
      return;
    }
    if (input.type === 'file') {
      void this.capture('file_select', el, ev);
      return;
    }
    // Checkbox and radio changes arrive with their own click event already.
    if (input.type === 'checkbox' || input.type === 'radio') return;

    if (isTextEntry(el)) {
      this.pendingInput = null;
      void this.capture('input', el, ev);
    }
  };

  onSubmit = (ev: Event): void => {
    if (this.picking || !this.recording) return;
    const el = this.targetOf(ev);
    if (!el) return;

    // Clicking "Sign in" fires a click AND a submit for one user action.
    // Recording both yields two steps for one intent, and the click is the
    // better of the two: it carries the button's accessible name, where the
    // submit only knows it happened to a form. Pressing Enter produces a
    // submit with no preceding click, so that case still records.
    if (this.clickTriggeredSubmit(el)) return;

    this.flushPendingInput();
    void this.capture('submit', el, ev);
  };

  /** Was this submit the direct consequence of a click just recorded? */
  private clickTriggeredSubmit(form: Element): boolean {
    const recent = this.lastClick;
    if (!recent) return false;
    if (this.clock() - recent.at > 200) return false;
    if (!form.contains(recent.el) && recent.el !== form) return false;
    const el = recent.el as HTMLInputElement;
    const type = (el.type ?? '').toLowerCase();
    return el.tagName === 'BUTTON' ? type !== 'button' : type === 'submit' || type === 'image';
  }

  onKeyDown = (ev: KeyboardEvent): void => {
    if (this.picking || !this.recording) return;
    // Only keys that mean something on their own. Ordinary typing is captured
    // once, as a value change, rather than as forty keypress steps.
    const meaningful =
      ev.key === 'Enter' || ev.key === 'Escape' || ev.key === 'Tab' || ev.ctrlKey || ev.metaKey;
    if (!meaningful) return;
    if (ev.key === 'Tab') return;

    const el = this.targetOf(ev);
    if (!el) return;
    const chord = [
      ev.ctrlKey ? 'Control' : null,
      ev.metaKey ? 'Meta' : null,
      ev.altKey ? 'Alt' : null,
      ev.shiftKey ? 'Shift' : null,
      ev.key,
    ]
      .filter(Boolean)
      .join('+');
    void this.capture('keypress', el, ev, { keys: chord });
  };

  private flushPendingInput(): void {
    const pending = this.pendingInput;
    this.pendingInput = null;
    if (!pending || !this.recording) return;
    if (valueOf(pending.el) === pending.initialValue) return;
    void this.capture('input', pending.el, null);
  }

  /* --------------------------- capture --------------------------- */

  private async capture(
    type: EventType,
    el: Element,
    ev: Event | null,
    extra: { keys?: string } = {},
  ): Promise<void> {
    const at = this.clock();
    const actionIndex = this.actionStarts.push(at) - 1;
    const flags = new Set<FidelityFlag>();

    if (at - this.lastEventAt < RAPID_SEQUENCE_MS) flags.add('rapid_sequence');
    this.lastEventAt = at;
    if (this.wasDrag) {
      flags.add('drag_interaction');
      this.wasDrag = false;
    }
    if (this.networkIncomplete) flags.add('network_incomplete');

    // `before` is built synchronously, inside the capture-phase listener: by
    // the time an await resolves the application has already begun responding,
    // and the pre-action state is gone.
    const beforeResult = buildSnapshot(el, document, this.redactor, { at });
    beforeResult.flags.forEach((f) => flags.add(f));

    const target = this.describeTarget(el, ev, flags);
    const files = fileListOf(el);
    if (files.length) flags.add('file_content_omitted');

    let transient: SemanticSnapshot | undefined;
    const urlBefore = location.href;

    const handle = waitForSettle({
      doc: document,
      // SS6.5 says "no in-flight request STARTED BY THIS ACTION", and the
      // distinction is load-bearing: a stream, a long poll or any request that
      // simply never completes would otherwise keep the counter above zero for
      // the rest of the session, costing every later step the full 5s timeout
      // and stamping settle_timeout on all of them.
      inFlight: () => this.inFlightFor(actionIndex),
      // Compared by value, not by "did a nav message arrive": frameworks and
      // dev servers call replaceState freely, and treating that as navigation
      // ended settle after ~10ms -- before the application had responded,
      // which is precisely what the settle window exists to prevent.
      urlChanged: () => location.href !== urlBefore,
      onTransient: () => {
        // Captured on appearance regardless of settle: a toast that vanishes in
        // three seconds is otherwise ungroundable (SS6.5).
        transient = buildSnapshot(el, document, this.redactor, { at: this.clock() }).snapshot;
      },
    });

    const settle = await handle.done;
    if (settle.reason === 'timeout') flags.add('settle_timeout');

    const afterResult = buildSnapshot(el, document, this.redactor, { at: this.clock() });
    afterResult.flags.forEach((f) => flags.add(f));

    const event: CapturedEvent = {
      id: `evt_${String(++this.seq).padStart(3, '0')}`,
      seq: this.seq - 1,
      timestamp: at,
      type,
      url: location.href,
      target,
      before: beforeResult.snapshot,
      after: afterResult.snapshot,
      diff: diffSnapshots(beforeResult.snapshot, afterResult.snapshot),
      settle,
      // Populated at assembly from the observation stream, where the session is
      // ordered and late-completing requests have arrived.
      network: [],
      console: [],
      fidelity: [...flags],
    };
    if (transient) event.transient = transient;
    if (extra.keys) event.keys = extra.keys;
    if (files.length) event.files = files;

    this.send(event);
  }

  private describeTarget(el: Element, ev: Event | null, flags: Set<FidelityFlag>): EventTargetInfo {
    const role = roleOf(el);
    const name = nameOf(el);

    const target: EventTargetInfo = {
      role: role || 'generic',
      name,
      tagName: el.tagName.toLowerCase(),
      selectors: selectorsFor(el),
      // Authoritative FramePath is stitched by the service worker, which is the
      // only side that can see the frame tree across origins.
      frame: [],
    };

    const raw = rawValueOf(el);
    if (raw !== null) target.value = this.redactor.redactFieldValue(el, raw);

    if (!name && isInteractiveElement(el)) flags.add('no_accessible_name');

    if (el.tagName.toLowerCase() === 'canvas') {
      flags.add('canvas_interaction');
      const rect = el.getBoundingClientRect();
      target.boundingBox = { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
      if (ev instanceof MouseEvent) {
        target.coordinates = { x: ev.clientX - rect.x, y: ev.clientY - rect.y };
      }
    }

    return target;
  }

  /**
   * Open requests belonging to action `index`.
   *
   * The upper bound is what a plain time window cannot express. Four separate
   * actions were each waiting out their own 5s settle when a later click fired
   * a slow request; every one of them counted it as "in flight" and timed out.
   * A request that started after the NEXT action began is that action's, not
   * this one's.
   */
  private inFlightFor(index: number): number {
    const from = (this.actionStarts[index] ?? 0) - NETWORK_LEAD_MS;
    const to = this.actionStarts[index + 1] ?? Infinity;
    let n = 0;
    for (const started of this.netStarted.values()) {
      if (started >= from && started < to) n += 1;
    }
    return n;
  }

  private report(message: WorkerInbound): void {
    try {
      chrome.runtime.sendMessage(message);
    } catch {
      /* the worker restarts freely; see send() */
    }
  }

  private send(event: CapturedEvent): void {
    const message: EventCaptured = {
      type: 'event',
      event,
      origin: location.origin,
      parameters: this.redactor.parameters(),
      screenshotWanted: window.top === window,
    };
    try {
      chrome.runtime.sendMessage(message satisfies WorkerInbound);
    } catch {
      // The worker restarts freely; a dropped message is preferable to a
      // thrown exception inside the page's own event handler.
    }
  }
}

/* ---------------------------- helpers ---------------------------- */

function isTextEntry(el: Element): boolean {
  const tag = el.tagName.toLowerCase();
  if (tag === 'textarea') return true;
  if ((el as HTMLElement).isContentEditable) return true;
  if (tag !== 'input') return false;
  const type = (el as HTMLInputElement).type;
  return !['checkbox', 'radio', 'file', 'button', 'submit', 'reset', 'image', 'range'].includes(type);
}

function valueOf(el: Element): string {
  const v = (el as HTMLInputElement).value;
  if (typeof v === 'string') return v;
  return (el as HTMLElement).innerText ?? '';
}

function fileListOf(el: Element): SelectedFile[] {
  const input = el as HTMLInputElement;
  if (input.type !== 'file' || !input.files) return [];
  // Name, size and MIME only. Bytes are deliberately not captured (SS4).
  return Array.from(input.files).map((f) => ({
    name: f.name,
    size: f.size,
    mime: f.type || 'application/octet-stream',
  }));
}

/* ------------------------------ wiring ---------------------------- */

const recorder = new Recorder();

window.addEventListener('message', (ev: MessageEvent) => {
  const data = ev.data as MainWorldMessage | undefined;
  if (!data || data.channel !== NET_CHANNEL) return;
  recorder.handleMainWorld(data);
});

document.addEventListener('pointerdown', recorder.onPointerDown, true);
document.addEventListener('pointerup', recorder.onPointerUp, true);
document.addEventListener('click', recorder.onClick, true);
document.addEventListener('focusin', recorder.onFocusIn, true);
document.addEventListener('change', recorder.onChange, true);
document.addEventListener('submit', recorder.onSubmit, true);
document.addEventListener('keydown', recorder.onKeyDown, true);

chrome.runtime.onMessage.addListener((message: WorkerInbound | RecorderState) => {
  if (!message || typeof message !== 'object') return;
  if (message.type === 'start') recorder.start(message.startedAt);
  if (message.type === 'stop') recorder.stop();
  if (message.type === 'pick') void recorder.pickAssertion();
});

// A frame that loads mid-session has to find out that recording is already in
// progress; the worker owns that state.
chrome.runtime.sendMessage({ type: 'query-state' } satisfies WorkerInbound, (state?: RecorderState) => {
  if (chrome.runtime.lastError) return;
  if (state?.recording && state.startedAt !== undefined) recorder.start(state.startedAt);
});
