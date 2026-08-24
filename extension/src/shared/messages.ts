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

export interface RecorderState {
  type: 'state';
  recording: boolean;
  recordingId?: string;
  objective?: string;
  startedAt?: number;
  eventCount: number;
  origins: string[];
  annotationCount: number;
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
  | QueryState
  | ExportRecording;

export type WorkerOutbound = RecorderState | { type: 'ack' } | { type: 'error'; message: string };
