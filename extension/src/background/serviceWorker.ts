import {
  type AnnotationAdded,
  type AudioFailed,
  type AudioLevel,
  type AudioStarted,
  type NarrationStatus,
  type RecorderState,
  type SetNarration,
  type StartRecording,
  type EventCaptured,
  type WorkerInbound,
} from '../shared/messages';
import { recordingId as newRecordingId } from '../shared/ids';
import type { AnnotationKind, FramePath, TesterAnnotation } from '../types/recording';
import {
  allEvents,
  allObservations,
  clearAll,
  getSession,
  putEvent,
  putObservation,
  putScreenshot,
  type SessionMeta,
  setSession,
} from './store';

/**
 * Coordination only. The frames do the observing; this decides when recording
 * is on, stitches the frame tree that no single frame can see, and owns the
 * one piece of state that has to outlive a worker eviction.
 */

/** chrome.tabs.captureVisibleTab allows two calls a second. Screenshots are a
 *  review aid, never evidence (SS7.4), so exceeding the budget skips the shot
 *  rather than delaying the recording. */
const SCREENSHOT_MIN_GAP_MS = 600;
let lastShotAt = 0;
let eventOrder = 0;

/* --------------------------- narration ----------------------------- */

/**
 * SS6.6. Off unless the tester turned it on, and remembered once they have.
 *
 * `chrome.storage.local` rather than the session: a recorder that silently
 * opens the microphone is not something to ship, and a tester who opted in last
 * week should not have to opt in again. The status is deliberately NOT
 * persisted -- it describes what the microphone is doing right now, and a
 * remembered `denied` would outlive the refusal it came from.
 */
const NARRATION_KEY = 'narrationEnabled';

let narrationStatus: NarrationStatus = 'off';
let narrationLevel = 0;
let muted = false;

async function narrationEnabled(): Promise<boolean> {
  const stored = await chrome.storage.local.get(NARRATION_KEY);
  return stored[NARRATION_KEY] === true;
}

/** The offscreen document, created on demand and closed with the recording.
 *  Chrome allows exactly one, so creation races have to be tolerated rather
 *  than assumed away -- two `start` messages in flight is a normal thing. */
async function openOffscreen(): Promise<boolean> {
  if (!chrome.offscreen) {
    narrationStatus = 'unsupported';
    return false;
  }
  try {
    if (await chrome.offscreen.hasDocument()) return true;
    await chrome.offscreen.createDocument({
      url: chrome.runtime.getURL('offscreen.html'),
      reasons: [chrome.offscreen.Reason.USER_MEDIA],
      justification:
        'Records the tester speaking while they work, so what they said becomes the ' +
        'expected result of the generated test case.',
    });
    return true;
  } catch {
    // Already open, or the API refused. `hasDocument` is the truth either way.
    return chrome.offscreen.hasDocument().catch(() => false);
  }
}

async function closeOffscreen(): Promise<void> {
  try {
    if (chrome.offscreen && (await chrome.offscreen.hasDocument())) {
      await chrome.offscreen.closeDocument();
    }
  } catch {
    /* already gone */
  }
}

async function startNarration(session: SessionMeta): Promise<void> {
  muted = false;
  narrationLevel = 0;
  if (!(await narrationEnabled())) {
    narrationStatus = 'off';
    return;
  }
  if (!(await openOffscreen())) return;

  narrationStatus = 'listening';
  // `startedAt` travels so the offscreen document reports capture beginning on
  // the same clock the events use. It has its own `performance.now()` origin,
  // and mixing the two is the mistake that once flattened every timestamp.
  await chrome.runtime
    .sendMessage({
      type: 'audio-start',
      recordingId: session.recordingId,
      startedAt: session.startedAt,
    })
    .catch(() => undefined);
}

async function stopNarration(): Promise<void> {
  if (narrationStatus === 'off') return;
  await chrome.runtime.sendMessage({ type: 'audio-stop' }).catch(() => undefined);
  // Long enough for the final `ondataavailable` to reach IndexedDB. The tail
  // since the last chunk boundary is the end of the session, which is where a
  // tester says what they were checking.
  await new Promise((resolve) => setTimeout(resolve, 400));
  await closeOffscreen();
  narrationStatus = 'off';
  narrationLevel = 0;
}

/* --------------------------- frame paths --------------------------- */

/**
 * A cross-origin frame cannot see its own parent, so the FramePath is stitched
 * here from the frame tree. The per-parent index is the frame's position among
 * its siblings ordered by frameId, which matches document order in practice --
 * webNavigation does not expose the true index.
 */
async function framePathFor(tabId: number, frameId: number): Promise<FramePath> {
  if (!frameId) return [];
  try {
    const frames = await chrome.webNavigation.getAllFrames({ tabId });
    if (!frames) return [];

    const byId = new Map(frames.map((f) => [f.frameId, f]));
    const siblingIndex = (id: number, parentId: number) =>
      frames
        .filter((f) => f.parentFrameId === parentId)
        .sort((a, b) => a.frameId - b.frameId)
        .findIndex((f) => f.frameId === id);

    const path: FramePath = [];
    let current = byId.get(frameId);
    while (current && current.frameId !== 0) {
      path.unshift({
        kind: 'iframe',
        url: current.url,
        index: Math.max(0, siblingIndex(current.frameId, current.parentFrameId)),
      });
      current = byId.get(current.parentFrameId);
    }
    return path;
  } catch {
    return [];
  }
}

/* ---------------------------- lifecycle ---------------------------- */

async function startRecording(objective: string | undefined, tab: chrome.tabs.Tab): Promise<SessionMeta> {
  await clearAll();
  eventOrder = 0;

  const session: SessionMeta = {
    recordingId: newRecordingId(),
    objective,
    startedAt: Date.now(),
    startedAtIso: new Date().toISOString(),
    startUrl: tab.url ?? '',
    tabId: tab.id ?? -1,
    origins: tab.url ? [safeOrigin(tab.url)].filter(Boolean) : [],
    parameters: [],
    annotations: [],
    eventCount: 0,
  };
  await setSession(session);

  // performance.now() in each frame is relative to that frame's own origin
  // time, so every frame is given one shared wall-clock zero instead.
  const message: StartRecording = {
    type: 'start',
    recordingId: session.recordingId,
    objective,
    startedAt: session.startedAt,
  };
  await broadcast(session.tabId, message);
  await startNarration(session);
  await chrome.action.setBadgeText({ text: 'REC' });
  await chrome.action.setBadgeBackgroundColor({ color: '#b3261e' });
  return session;
}

async function stopRecording(): Promise<void> {
  await stopNarration();
  const session = await getSession();
  if (session) {
    await broadcast(session.tabId, { type: 'stop' });
    // Marked rather than deleted -- the export page still needs it, but the
    // popup has to return to idle so a second recording can be started.
    await setSession({ ...session, stopped: true });
  }
  await chrome.action.setBadgeText({ text: '' });
}

async function broadcast(tabId: number, message: unknown): Promise<void> {
  if (tabId < 0) return;
  try {
    const frames = await chrome.webNavigation.getAllFrames({ tabId });
    await Promise.all(
      (frames ?? []).map((f) =>
        chrome.tabs.sendMessage(tabId, message, { frameId: f.frameId }).catch(() => undefined),
      ),
    );
  } catch {
    chrome.tabs.sendMessage(tabId, message).catch(() => undefined);
  }
}

/**
 * The tab to record. The active tab is usually right, but not when the popup
 * has been opened as a tab or the user is sitting on a chrome:// page -- and
 * recording the extension's own UI is never what was meant.
 */
function recordable(tab: chrome.tabs.Tab): boolean {
  const url = tab.url ?? '';
  return url.startsWith('http://') || url.startsWith('https://');
}

async function targetTab(): Promise<chrome.tabs.Tab | undefined> {
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active && recordable(active)) return active;

  const candidates = (await chrome.tabs.query({ currentWindow: true })).filter(recordable);
  if (candidates.length) {
    return candidates.sort((a, b) => (b.lastAccessed ?? 0) - (a.lastAccessed ?? 0))[0];
  }
  return (await chrome.tabs.query({})).filter(recordable)[0];
}

function safeOrigin(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return '';
  }
}

/* ----------------------------- ingest ------------------------------ */

async function ingest(message: EventCaptured, sender: chrome.runtime.MessageSender): Promise<void> {
  const session = await getSession();
  // A frame can emit one last event while the stop is still propagating.
  if (!session || session.stopped) return;

  const tabId = sender.tab?.id ?? session.tabId;
  const frameId = sender.frameId ?? 0;

  const event = message.event;
  event.target.frame = await framePathFor(tabId, frameId);

  const order = eventOrder++;

  // Each frame numbers its own events, so an iframe and the top document both
  // emit evt_001. Ids are re-issued here, where the whole session is visible.
  // They have to be unique: every downstream stage references events by id,
  // and `element_exists` resolves against them.
  event.seq = order;
  event.id = `evt_${String(order + 1).padStart(3, '0')}`;

  const key = event.timestamp * 1000 + order;
  await putEvent(key, event, frameId);

  if (message.screenshotWanted) {
    const shot = await captureScreenshot(sender.tab?.windowId);
    if (shot) {
      await putScreenshot(event.id, shot);
      event.screenshot = `screens/${event.id}.png`;
      await putEvent(key, event, frameId);
    }
  }

  // Placeholder maps are per-frame; the union is what the recording reports.
  const params = new Map(session.parameters.map((p) => [p.name, p]));
  for (const p of message.parameters) {
    const existing = params.get(p.name);
    if (existing) existing.occurrences = Math.max(existing.occurrences, p.occurrences);
    else params.set(p.name, { ...p });
  }

  const origins = new Set(session.origins);
  // Only http(s) origins matter to the pre-send gate; the extension's own
  // pages are not part of the application under test.
  if (message.origin.startsWith('http')) origins.add(message.origin);

  await setSession({
    ...session,
    parameters: [...params.values()],
    origins: [...origins],
    eventCount: session.eventCount + 1,
  });
}

async function captureScreenshot(windowId: number | undefined): Promise<string | null> {
  const now = Date.now();
  if (now - lastShotAt < SCREENSHOT_MIN_GAP_MS) return null;
  lastShotAt = now;
  try {
    return await chrome.tabs.captureVisibleTab(windowId ?? chrome.windows.WINDOW_ID_CURRENT, {
      format: 'png',
    });
  } catch {
    return null;
  }
}

/* --------------------------- annotations --------------------------- */

async function addAnnotation(annotation: TesterAnnotation): Promise<void> {
  const session = await getSession();
  if (!session) return;
  await setSession({ ...session, annotations: [...session.annotations, annotation] });
}

const COMMAND_KINDS: Record<string, AnnotationKind> = {
  checkpoint: 'checkpoint',
  'scenario-break': 'scenario_break',
  'bug-marker': 'bug_marker',
};

chrome.commands?.onCommand.addListener(async (command) => {
  const kind = COMMAND_KINDS[command];
  if (!kind) return;
  const session = await getSession();
  if (!session) return;
  await addAnnotation({
    id: `ann_${session.annotations.length + 1}`,
    kind,
    timestamp: Date.now() - session.startedAt,
  });
});

/* ---------------------------- messaging ---------------------------- */

async function currentState(): Promise<RecorderState> {
  const session = await getSession();
  const live = session !== null && !session.stopped;
  return {
    type: 'state',
    recording: live,
    narrationEnabled: await narrationEnabled(),
    narrationStatus: live ? narrationStatus : 'off',
    narrationLevel: muted ? 0 : narrationLevel,
    ...(session
      ? {
          recordingId: session.recordingId,
          objective: session.objective,
          startedAt: session.startedAt,
          eventCount: session.eventCount,
          origins: session.origins,
          annotationCount: session.annotations.length,
        }
      : { eventCount: 0, origins: [], annotationCount: 0 }),
  };
}

chrome.runtime.onMessage.addListener((message: WorkerInbound, sender, sendResponse) => {
  (async () => {
    switch (message.type) {
      case 'start': {
        const tab = await targetTab();
        if (!tab) return sendResponse({ type: 'error', message: 'No recordable tab' });
        await startRecording(message.objective, tab);
        return sendResponse(await currentState());
      }
      case 'stop':
        await stopRecording();
        return sendResponse(await currentState());
      case 'event':
        await ingest(message, sender);
        return sendResponse({ type: 'ack' });
      case 'network':
      case 'console': {
        const session = await getSession();
        if (!session || session.stopped) return sendResponse({ type: 'ack' });
        const frameId = sender.frameId ?? 0;
        const payload = message.type === 'network' ? message.call : message.entry;
        const at = message.type === 'network' ? message.call.startTime : message.entry.timestamp;
        await putObservation({
          key: `${frameId}:${message.type}:${(payload as { id: string }).id}`,
          frameId,
          kind: message.type,
          at,
          payload,
        });
        return sendResponse({ type: 'ack' });
      }
      case 'annotation':
        await addAnnotation((message as AnnotationAdded).annotation);
        return sendResponse(await currentState());
      case 'pick': {
        // Forwarded rather than handled: the element the tester is about to
        // point at lives in the page, so only a content script can see it.
        const session = await getSession();
        if (!session || session.stopped) {
          return sendResponse({ type: 'error', message: 'Not recording' });
        }
        await broadcast(session.tabId, { type: 'pick' });
        return sendResponse({ type: 'ack' });
      }
      /* ------------------------ narration ------------------------ */

      case 'set-narration': {
        const enabled = (message as SetNarration).enabled;
        await chrome.storage.local.set({ [NARRATION_KEY]: enabled });
        if (!enabled) await stopNarration();
        // The prompt cannot come from the offscreen document, so a tab has to
        // ask. Opened on the tester's own click, which is what makes it a user
        // gesture Chrome will honour.
        if (enabled) {
          await chrome.tabs.create({ url: chrome.runtime.getURL('mic.html') });
        }
        return sendResponse(await currentState());
      }
      case 'toggle-mute': {
        muted = !muted;
        narrationLevel = 0;
        narrationStatus = muted ? 'muted' : 'listening';
        await chrome.runtime.sendMessage({ type: 'audio-mute', muted }).catch(() => undefined);
        return sendResponse(await currentState());
      }
      case 'audio-started': {
        const session = await getSession();
        if (!session) return sendResponse({ type: 'ack' });
        // The delta, not the timestamp. The microphone takes a moment to open,
        // and every transcript timestamp is relative to the audio -- so without
        // this each spoken sentence is shifted by that delay and lands on the
        // wrong step. Clamped at zero: capture cannot precede its own session,
        // and a negative offset would push narration before the recording.
        const offset = Math.max(0, (message as AudioStarted).at - session.startedAt);
        await setSession({ ...session, audioOffsetMs: offset });
        narrationStatus = muted ? 'muted' : 'listening';
        return sendResponse({ type: 'ack' });
      }
      case 'audio-level':
        narrationLevel = (message as AudioLevel).level;
        return sendResponse({ type: 'ack' });
      case 'audio-failed': {
        const failure = message as AudioFailed;
        narrationStatus = failure.reason === 'denied' ? 'denied' : 'unsupported';
        narrationLevel = 0;
        return sendResponse({ type: 'ack' });
      }

      case 'query-state':
        return sendResponse(await currentState());
      default:
        return sendResponse({ type: 'error', message: `unknown message ${String(message)}` });
    }
  })().catch((err) => sendResponse({ type: 'error', message: String(err) }));

  // Keeps the message channel open for the async work above.
  return true;
});

/** The export page pulls the assembled artifacts through here rather than
 *  duplicating the store logic. */
chrome.runtime.onMessage.addListener((message: { type: string }, _sender, sendResponse) => {
  if (message?.type !== 'collect') return undefined;
  (async () => {
    sendResponse({
      session: await getSession(),
      events: await allEvents(),
      observations: await allObservations(),
    });
  })().catch(() => sendResponse(null));
  return true;
});
