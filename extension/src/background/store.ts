import type {
  CapturedEvent,
  RedactionLevel,
  RedactionParameter,
  TesterAnnotation,
} from '../types/recording';

/**
 * An MV3 service worker is evicted after roughly 30 seconds of inactivity, and
 * a QA session runs for fifteen minutes. Anything held only in a module-level
 * variable is therefore lost partway through every real recording, so events
 * are written to IndexedDB as they arrive and the worker keeps no authoritative
 * state of its own.
 */

const DB_NAME = 'aitc-rem';
const DB_VERSION = 3;
const EVENTS = 'events';
const SHOTS = 'screenshots';
const META = 'meta';
const OBS = 'observations';
const AUDIO = 'audio';

export interface SessionMeta {
  recordingId: string;
  objective?: string;
  startedAt: number;
  /** Wall-clock start, for Recording.metadata.capturedAt. */
  startedAtIso: string;
  startUrl: string;
  /** The tab the tester pressed Record in. Kept as the origin of the session
   *  even after it opens others -- `startUrl` is this tab's. */
  tabId: number;
  /** Every tab the session is recording, including `tabId`.
   *
   *  SS18 milestone 21. The recorder was pinned to one tab by choice rather
   *  than by limitation: the content script is already injected into every tab
   *  (`<all_urls>`, `all_frames`), the service worker already reads
   *  `sender.tab.id` on every event, and the expensive problem -- ordering
   *  events from separate documents on one clock -- was solved when
   *  `performance.now()` was converted through `timeOrigin`. What was missing
   *  was a set instead of a number.
   *
   *  A plain array rather than a Set because this is stored in IndexedDB. */
  tabIds: number[];
  origins: string[];
  /** How much redaction the tester chose before starting. Absent means `full`,
   *  which is every session recorded before the setting existed. Kept on the
   *  session rather than read at export time because it has to reach the
   *  content script the moment recording starts -- redaction happens before
   *  anything is persisted, so a decision made afterwards is no decision. */
  redaction?: RedactionLevel;
  parameters: RedactionParameter[];
  annotations: TesterAnnotation[];
  eventCount: number;
  /** SS6.6 -- ms from `startedAt` to the first audio sample. The microphone
   *  takes a moment to open, and every transcript timestamp is relative to the
   *  audio rather than to the session, so without this each spoken sentence is
   *  shifted by that delay and attributed to the wrong step. Absent when
   *  narration was off or capture never started. */
  audioOffsetMs?: number;
  /** Stopped sessions are kept, not deleted: the export page still needs them.
   *  Only `startRecording` clears the store. */
  stopped?: boolean;
  /** Session ms at which Stop was pressed. See `ingest`. */
  stoppedAt?: number;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(EVENTS)) db.createObjectStore(EVENTS, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(SHOTS)) db.createObjectStore(SHOTS, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(META)) db.createObjectStore(META, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(OBS)) db.createObjectStore(OBS, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(AUDIO)) db.createObjectStore(AUDIO, { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(store: string, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(store, mode);
        const req = fn(t.objectStore(store));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
        t.oncomplete = () => db.close();
      }),
  );
}

/* ------------------------------ meta ------------------------------ */

export async function getSession(): Promise<SessionMeta | null> {
  const row = await tx<{ key: string; value: SessionMeta } | undefined>(META, 'readonly', (s) =>
    s.get('session'),
  );
  return row?.value ?? null;
}

export async function setSession(value: SessionMeta | null): Promise<void> {
  if (value === null) {
    await tx(META, 'readwrite', (s) => s.delete('session'));
    return;
  }
  await tx(META, 'readwrite', (s) => s.put({ key: 'session', value }));
}

/* ----------------------------- events ----------------------------- */

export interface EventRow {
  key: number;
  event: CapturedEvent;
  /** Which frame reported it. Worker bookkeeping, deliberately not part of the
   *  schema: assembly needs it to attribute network and console observations to
   *  events from the SAME frame, and nothing downstream does. */
  frameId: number;
}

/** Events arrive from several frames concurrently, so the key carries the
 *  worker-assigned order rather than the frame-local sequence number. */
export async function putEvent(order: number, event: CapturedEvent, frameId = 0): Promise<void> {
  await tx(EVENTS, 'readwrite', (s) => s.put({ key: order, event, frameId }));
}

export async function allEventRows(): Promise<EventRow[]> {
  const rows = await tx<EventRow[]>(EVENTS, 'readonly', (s) => s.getAll());
  return rows.sort((a, b) => a.key - b.key);
}

export async function allEvents(): Promise<CapturedEvent[]> {
  return (await allEventRows()).map((r) => r.event);
}

export async function putScreenshot(eventId: string, dataUrl: string): Promise<void> {
  await tx(SHOTS, 'readwrite', (s) => s.put({ key: eventId, dataUrl }));
}

export async function allScreenshots(): Promise<{ key: string; dataUrl: string }[]> {
  return tx<{ key: string; dataUrl: string }[]>(SHOTS, 'readonly', (s) => s.getAll());
}

/**
 * Network calls and console entries, tagged with the frame that saw them.
 * Attribution to events happens at assembly, not here.
 */
export interface Observation {
  key: string;
  frameId: number;
  kind: 'network' | 'console';
  at: number;
  payload: unknown;
}

export async function putObservation(obs: Observation): Promise<void> {
  await tx(OBS, 'readwrite', (s) => s.put(obs));
}

export async function allObservations(): Promise<Observation[]> {
  const rows = await tx<Observation[]>(OBS, 'readonly', (s) => s.getAll());
  return rows.sort((a, b) => a.at - b.at);
}

/* ------------------------------ audio ------------------------------ */

/**
 * SS6.6 -- narration audio, in the order MediaRecorder produced it.
 *
 * Written here by the offscreen document rather than messaged to the worker:
 * both share the extension's IndexedDB, and base64-ing megabytes of Opus
 * through `chrome.runtime.sendMessage` (which serialises to JSON) would be a
 * third of a megabyte of overhead per megabyte of speech for no gain.
 *
 * **Order is load-bearing and the chunks are not independent.** Only the FIRST
 * chunk of a WebM stream carries the header; the rest are continuation
 * clusters. Concatenated out of order, or with one missing, the result is not a
 * file any decoder will open -- so the key is a dense sequence and assembly
 * sorts on it.
 */
export async function putAudioChunk(seq: number, blob: Blob): Promise<void> {
  await tx(AUDIO, 'readwrite', (s) => s.put({ key: seq, blob }));
}

export async function allAudioChunks(): Promise<Blob[]> {
  const rows = await tx<{ key: number; blob: Blob }[]>(AUDIO, 'readonly', (s) => s.getAll());
  return rows.sort((a, b) => a.key - b.key).map((r) => r.blob);
}

export async function audioBlob(): Promise<Blob | null> {
  const chunks = await allAudioChunks();
  return chunks.length ? new Blob(chunks, { type: chunks[0]!.type || 'audio/webm' }) : null;
}

export async function clearAll(): Promise<void> {
  for (const store of [EVENTS, SHOTS, META, OBS, AUDIO]) {
    await tx(store, 'readwrite', (s) => s.clear());
  }
}
