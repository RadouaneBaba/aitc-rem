import type {
  CapturedEvent,
  ConsoleEntry,
  NetworkCall,
  RedactionParameter,
  TesterAnnotation,
} from '../types/recording';

/** Namespaced so the page's own postMessage traffic is never mistaken for ours. */
export const NET_CHANNEL = 'aitc-rem::net';

export interface NetStart {
  channel: typeof NET_CHANNEL;
  kind: 'start';
  id: string;
  method: string;
  url: string;
  startTime: number;
  initiator: 'fetch' | 'xhr';
  requestBody?: string;
  requestHeaders?: Record<string, string>;
}

export interface NetEnd {
  channel: typeof NET_CHANNEL;
  kind: 'end';
  id: string;
  status?: number;
  endTime: number;
  responseBody?: string;
  responseHeaders?: Record<string, string>;
  failed?: boolean;
}

export interface NavSignal {
  channel: typeof NET_CHANNEL;
  kind: 'nav';
  url: string;
  at: number;
}

export interface CaptureGaps {
  channel: typeof NET_CHANNEL;
  kind: 'gaps';
  /** Requests may have been missed: patch installed late, or a service worker
   *  is in control and its requests never reach page-context fetch (SS6.4). */
  networkIncomplete: boolean;
  reason: string;
}

export interface ConsoleSignal {
  channel: typeof NET_CHANNEL;
  kind: 'console';
  level: 'error' | 'warning';
  text: string;
  at: number;
  stack?: string;
  /** An uncaught exception rather than a console.error call. Strong bug
   *  signal, weighted decisively in SS14.1. */
  uncaught: boolean;
}

export type MainWorldMessage = NetStart | NetEnd | NavSignal | CaptureGaps | ConsoleSignal;

/* ------------------------------------------------------------------ */
/* content script  <->  service worker                                 */
/* ------------------------------------------------------------------ */

export interface StartRecording {
  type: 'start';
  recordingId: string;
  objective?: string;
  startedAt: number;
}

export interface StopRecording {
  type: 'stop';
}

/**
 * SS6.6 -- what the microphone is doing, for the popup.
 *
 * `unsupported` and `denied` are separate on purpose. One is a browser that
 * cannot, the other is a person who said no, and telling a tester to "check
 * their microphone" when they deliberately declined is how a tool loses trust.
 */
export type NarrationStatus = 'off' | 'listening' | 'muted' | 'denied' | 'unsupported';

export interface RecorderState {
  type: 'state';
  recording: boolean;
  recordingId?: string;
  objective?: string;
  startedAt?: number;
  eventCount: number;
  origins: string[];
  annotationCount: number;
  /** Whether the tester has asked to narrate. Off unless they turned it on. */
  narrationEnabled: boolean;
  narrationStatus: NarrationStatus;
  /** 0-1, for the level meter. The only live feedback there is: transcription
   *  happens on the server afterwards, so "is it hearing me" has no other
   *  answer until the run finishes. */
  narrationLevel?: number;
}

export interface EventCaptured {
  type: 'event';
  event: CapturedEvent;
  origin: string;
  /** Placeholders this frame has emitted so far, merged by the worker. */
  parameters: RedactionParameter[];
  screenshotWanted: boolean;
}

/**
 * Network and console are reported as they are observed, independently of any
 * event. Attribution happens at assembly, where the whole session is ordered:
 * a frame cannot know when the NEXT action starts, and a request that completes
 * after its own action settled -- which is exactly what a slow endpoint does --
 * would otherwise never be recorded at all.
 */
export interface NetworkObserved {
  type: 'network';
  call: NetworkCall;
}

export interface ConsoleObserved {
  type: 'console';
  entry: ConsoleEntry;
}

export interface AnnotationAdded {
  type: 'annotation';
  annotation: TesterAnnotation;
}

/**
 * SS6.7's assertion annotation: the tester points at the thing they are
 * checking. Sent by the popup, forwarded by the worker to the recording tab,
 * and handled by the content script -- it has to run in the page because the
 * element being pointed at lives there.
 */
export interface StartPicking {
  type: 'pick';
}

/* ------------------------------------------------------------------ */
/* narration (SS6.6)                                                    */
/* ------------------------------------------------------------------ */

/**
 * Turn narration on or off. Off by default and persisted per browser: a
 * recorder that silently opens the microphone is not something to ship, and a
 * tester who turned it on last week should not have to again.
 */
export interface SetNarration {
  type: 'set-narration';
  enabled: boolean;
}

/** Silence the microphone mid-recording, without ending the session. The
 *  escape hatch for "I am about to say something I would rather not have
 *  written down" -- and everything said IS written down. */
export interface ToggleMute {
  type: 'toggle-mute';
}

/**
 * The offscreen document reports that capture actually began.
 *
 * `at` is wall-clock, and the delta from the session start becomes
 * `RecordingMetadata.audioOffsetMs`. The microphone takes a moment to open, so
 * audio does NOT start when the recording does -- and every transcript
 * timestamp is relative to the audio. Without this, every spoken sentence is
 * shifted by however long the mic took and lands on the wrong step.
 */
export interface AudioStarted {
  type: 'audio-started';
  at: number;
}

/** Input level, for the popup's meter. Reported, never stored. */
export interface AudioLevel {
  type: 'audio-level';
  level: number;
}

/** Capture could not start, or stopped on its own. */
export interface AudioFailed {
  type: 'audio-failed';
  reason: 'denied' | 'unsupported' | 'error';
  message?: string;
}

export interface QueryState {
  type: 'query-state';
}

export interface ExportRecording {
  type: 'export';
}

export type WorkerInbound =
  | StartRecording
  | StopRecording
  | EventCaptured
  | NetworkObserved
  | ConsoleObserved
  | AnnotationAdded
  | StartPicking
  | SetNarration
  | ToggleMute
  | AudioStarted
  | AudioLevel
  | AudioFailed
  | QueryState
  | ExportRecording;

/** Worker -> offscreen document. Audio chunks do NOT travel this way: both
 *  contexts share the extension's IndexedDB, so the offscreen document writes
 *  them itself rather than base64-ing megabytes through the message channel. */
export type OffscreenInbound =
  | { type: 'audio-start'; recordingId: string; startedAt: number }
  | { type: 'audio-stop' }
  | { type: 'audio-mute'; muted: boolean };

export type WorkerOutbound = RecorderState | { type: 'ack' } | { type: 'error'; message: string };
