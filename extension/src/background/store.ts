import type { CapturedEvent, RedactionParameter, TesterAnnotation } from '../types/recording';

/**
 * An MV3 service worker is evicted after roughly 30 seconds of inactivity, and
 * a QA session runs for fifteen minutes. Anything held only in a module-level
 * variable is therefore lost partway through every real recording, so events
 * are written to IndexedDB as they arrive and the worker keeps no authoritative
 * state of its own.
 */

const DB_NAME = 'aitc-rem';
const DB_VERSION = 2;
const EVENTS = 'events';
const SHOTS = 'screenshots';
const META = 'meta';
const OBS = 'observations';

export interface SessionMeta {
  recordingId: string;
  objective?: string;
  startedAt: number;
  /** Wall-clock start, for Recording.metadata.capturedAt. */
  startedAtIso: string;
  startUrl: string;
  tabId: number;
  origins: string[];
  parameters: RedactionParameter[];
  annotations: TesterAnnotation[];
  eventCount: number;
  /** Stopped sessions are kept, not deleted: the export page still needs them.
   *  Only `startRecording` clears the store. */
  stopped?: boolean;
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

export async function clearAll(): Promise<void> {
  for (const store of [EVENTS, SHOTS, META, OBS]) {
    await tx(store, 'readwrite', (s) => s.clear());
  }
}
