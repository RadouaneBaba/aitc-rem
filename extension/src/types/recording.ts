/* Generated from schema/recording.schema.json. Do not edit. */

export type EventType =
  | "click"
  | "input"
  | "select"
  | "keypress"
  | "navigate"
  | "submit"
  | "file_select"
  | "tab_open"
  | "tab_close"
  | "dialog";
/**
 * One hop in the path from the top document to the element's document. SS6.2.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "FramePathSegment".
 */
export type FramePathSegment = IframeHop | ShadowHop;
/**
 * Path from the top document down to the element's document. Empty means the top-level document.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "FramePath".
 */
export type FramePath = FramePathSegment[];
/**
 * SS6.3 -- scoped by default (nearest landmark/dialog ancestor). 'full' only when get_full_snapshot asked for it, which is itself an agentic decision: cheap view by default, expensive one on demand.
 */
export type SnapshotScope = "scoped" | "full";
export type SettleReason = "quiet" | "live_region" | "url_change" | "timeout";
export type NetworkInitiator = "fetch" | "xhr" | "navigation" | "unknown";
export type ConsoleLevel = "error" | "warning";
export type AnnotationKind = "checkpoint" | "intent_note" | "assertion" | "scenario_break" | "bug_marker";
/**
 * What the recorder could NOT determine. SS6.8. Propagates from event to step and is rendered prominently in review. Degrading loudly is the point.
 */
export type FidelityFlag =
  | "canvas_interaction"
  | "no_accessible_name"
  | "closed_shadow_root"
  | "cross_origin_frame_blocked"
  | "drag_interaction"
  | "file_content_omitted"
  | "rapid_sequence"
  | "settle_timeout"
  | "network_incomplete";
export type DialogKind = "alert" | "confirm" | "prompt" | "beforeunload";
export type RedactionCategory =
  "password" | "email" | "card_number" | "phone" | "national_id" | "custom" | "auth_header" | "body_field";

/**
 * The contract between the Chrome extension and the pipeline (SS5). Everything here has already passed through in-browser redaction (SS7) -- no raw secret ever reaches this document.
 */
export interface Recording {
  schemaVersion: "1.0";
  /**
   * e.g. rec_01J8X2. Stable; referenced by every run artifact.
   */
  id: string;
  projectId: string;
  ownerId: string;
  createdAt: string;
  /**
   * SS6.6 -- the tester's stated objective, verbatim. The one input the tool can never observe, and the primary source for the test case title. Optional; the tool must be fully usable without it.
   */
  objective?: string;
  metadata: RecordingMetadata;
  events: CapturedEvent[];
  /**
   * SS6.6 -- transcribed locally, timestamps anchored to the recorder clock.
   */
  narration: NarrationSegment[];
  /**
   * Session-level annotations. Annotations bound to a specific action also appear on that event.
   */
  annotations: TesterAnnotation[];
  /**
   * SS7.2 -- placeholders that were substituted, by name only. The raw values they replaced are never persisted anywhere.
   */
  parameters: RedactionParameter[];
}
/**
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "RecordingMetadata".
 */
export interface RecordingMetadata {
  capturedAt: string;
  durationMs: number;
  browser: string;
  userAgent?: string;
  viewport: Viewport;
  startUrl: string;
  /**
   * Every distinct origin touched during the recording. Load-bearing: the pipeline's pre-send gate checks these against the allowlist before sending anything to a training-eligible endpoint (SS9.12).
   */
  origins: string[];
  recorderVersion?: string;
  /**
   * SS6.6 -- milliseconds from the recording's zero to the first audio sample. The microphone takes a moment to open, so narration audio does NOT start when the recording does, and transcription timestamps are relative to the audio rather than to the session. Without this every spoken sentence is shifted by however long the mic took, which attributes it to the wrong step. Absent when no audio was captured.
   */
  audioOffsetMs?: number;
  /**
   * Count of each fidelity flag across all events. Lets the review UI warn before the tester opens a single step.
   */
  fidelitySummary?: {
    [k: string]: number;
  };
}
export interface Viewport {
  w: number;
  h: number;
}
/**
 * SS6.2 -- a bundle per user action, not a continuous stream. Scroll, hover and mousemove are context, never steps, and do not appear here.
 *
 * On the three snapshots: `before` is taken at the moment of the action; `after` is taken once the page settles (SS6.5), NOT on the next tick, because snapshotting immediately captures the state before the application has responded and loses the very evidence the assertion needs. `transient` is captured the instant a live region appears, ahead of settle, and is present only when something showed up that might vanish -- a toast that disappears within three seconds is otherwise ungroundable.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "CapturedEvent".
 */
export interface CapturedEvent {
  /**
   * e.g. evt_027. Referenced by every downstream stage.
   */
  id: string;
  seq: number;
  /**
   * ms since recorder start.
   */
  timestamp: number;
  type: EventType;
  /**
   * Document URL at the moment of the action.
   */
  url: string;
  tabId?: number;
  target: EventTarget;
  before: SemanticSnapshot;
  after: SemanticSnapshot;
  transient?: SemanticSnapshot;
  diff: SnapshotDiff;
  settle?: SettleInfo;
  /**
   * Requests in this action's time window.
   */
  network: NetworkCall[];
  /**
   * Errors and warnings only.
   */
  console: ConsoleEntry[];
  /**
   * Path to a PNG on disk. Never sent to a model (SS7.4).
   */
  screenshot?: string;
  annotations?: TesterAnnotation[];
  fidelity: FidelityFlag[];
  /**
   * For keypress events: the key or chord, e.g. 'Enter' or 'Control+S'.
   */
  keys?: string;
  /**
   * For file_select. Bytes are deliberately not captured (SS4 deferred list).
   */
  files?: SelectedFile[];
  dialog?: DialogInfo;
}
/**
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "EventTarget".
 */
export interface EventTarget {
  /**
   * Computed accessible role, not the tag name. Resolved from an explicit role attribute or the implicit-role mapping.
   */
  role: string;
  /**
   * Computed accessible name (dom-accessibility-api) -- the human label. Empty string when the element has none, which also raises no_accessible_name.
   */
  name: string;
  /**
   * Post-redaction. A password field's value is '<<password>>' here and nowhere is it anything else.
   */
  value?: string;
  tagName?: string;
  selectors: SelectorSet;
  frame: FramePath;
  boundingBox?: BoundingBox;
  coordinates?: Coordinates;
}
/**
 * Ranked, most-stable first. SS6.2. Only `css` is guaranteed present -- it is the last resort, not the preference.
 */
export interface SelectorSet {
  /**
   * data-testid / data-test / data-cy value. Highest stability when the app provides one; absent for most apps, which is expected and fine.
   */
  testId?: string;
  /**
   * Serialized role+name locator, e.g. getByRole('button', { name: 'Submit' }).
   */
  role?: string;
  text?: string;
  css: string;
}
export interface IframeHop {
  kind: "iframe";
  url: string;
  index: number;
}
export interface ShadowHop {
  kind: "shadow";
  /**
   * Tag name or selector of the shadow host element.
   */
  host: string;
}
/**
 * Viewport coordinates. Mainly for canvas interactions, where it is all we have.
 */
export interface BoundingBox {
  x: number;
  y: number;
  w: number;
  h: number;
}
/**
 * Click point relative to the target. Only meaningful for canvas_interaction.
 */
export interface Coordinates {
  x: number;
  y: number;
}
/**
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "SemanticSnapshot".
 */
export interface SemanticSnapshot {
  capturedAt: number;
  url: string;
  title: string;
  scope: SnapshotScope;
  scopeRoot?: ScopeRoot;
  root: SemanticNode;
  /**
   * SS6.3 -- every alert/status/log/alertdialog node anywhere in the document, regardless of scope. Outcomes appear far from the click, and this is where most expected results actually live.
   */
  liveRegions: SemanticNode[];
  /**
   * Node budget was hit and the tree was cut. Surfaces rather than silently shortening.
   */
  truncated?: boolean;
}
/**
 * What the scope was anchored to. Absent when scope is 'full'.
 */
export interface ScopeRoot {
  role: string;
  name?: string;
  landmark?: string;
}
/**
 * SS6.3 -- role, accessible name, state. Never raw DOM HTML: 2-6 KB vs 50-200 KB, and the raw form overflows the context window and produces incoherent output on any model.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "SemanticNode".
 */
export interface SemanticNode {
  /**
   * Structural path within this snapshot, e.g. '0.2.1'. Stable for the snapshot; how query_element and the element_exists validator resolve a node.
   */
  ref: string;
  role: string;
  name: string;
  /**
   * Post-redaction.
   */
  value?: string;
  /**
   * disabled, checked, expanded, invalid, selected, required, readonly, busy, ...
   */
  state?: string[];
  /**
   * nav, main, dialog, ... -- for locating the node.
   */
  landmark?: string;
  children?: SemanticNode[];
}
/**
 * Computed at capture time (SS6.2), so the pipeline never has to re-derive it.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "SnapshotDiff".
 */
export interface SnapshotDiff {
  added: DiffNode[];
  removed: DiffNode[];
  changed: NodeChange[];
  urlChanged?: UrlChange;
  titleChanged?: TitleChange;
}
/**
 * A node in a diff, flattened -- no children, to keep diffs small enough to hand to a model whole.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "DiffNode".
 */
export interface DiffNode {
  ref: string;
  role: string;
  name: string;
  value?: string;
  state?: string[];
  /**
   * Human-readable ancestry, e.g. 'main > dialog "Confirm order"'.
   */
  path?: string;
}
export interface NodeChange {
  before: DiffNode;
  after: DiffNode;
  /**
   * Which of name/value/state changed.
   */
  fields: string[];
}
export interface UrlChange {
  from: string;
  to: string;
}
export interface TitleChange {
  from: string;
  to: string;
}
/**
 * SS6.5 -- why the recorder decided the application had finished responding. Diagnostic, and the reason a settle_timeout can be explained rather than merely flagged.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "SettleInfo".
 */
export interface SettleInfo {
  reason: SettleReason;
  waitedMs: number;
  mutationCount?: number;
  inFlightAtEnd?: number;
}
/**
 * SS6.4 -- captured by a fetch/XHR patch in MAIN world. Bodies are redacted in page context before they leave it.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "NetworkCall".
 */
export interface NetworkCall {
  id: string;
  method: string;
  url: string;
  status?: number;
  startTime: number;
  endTime?: number;
  durationMs?: number;
  initiator: NetworkInitiator;
  /**
   * Redacted. Truncated past a size budget.
   */
  requestBody?: string;
  /**
   * Redacted. Truncated past a size budget.
   */
  responseBody?: string;
  /**
   * Allowlisted only. Authorization and Cookie are never recorded (SS6.4).
   */
  requestHeaders?: {
    [k: string]: string;
  };
  responseHeaders?: {
    [k: string]: string;
  };
  failed?: boolean;
  bodyTruncated?: boolean;
}
/**
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "ConsoleEntry".
 */
export interface ConsoleEntry {
  id: string;
  level: ConsoleLevel;
  text: string;
  timestamp: number;
  stack?: string;
  /**
   * An uncaught exception rather than a console.error call. Strong bug signal (SS14.1).
   */
  uncaught?: boolean;
}
/**
 * SS6.7. The tool must be fully usable with zero annotations -- they raise quality, they are never required.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "TesterAnnotation".
 */
export interface TesterAnnotation {
  id: string;
  kind: AnnotationKind;
  /**
   * For intent_note this becomes the step name VERBATIM -- the model does not rewrite it.
   */
  text?: string;
  timestamp: number;
  eventId?: string;
  target?: AnnotationTarget;
}
/**
 * For assertion annotations: the element the tester pointed at.
 */
export interface AnnotationTarget {
  role: string;
  name: string;
  value?: string;
  selectors?: SelectorSet;
}
/**
 * Name/size/MIME only -- bytes are deliberately not captured (SS4). Rendered as <<fixture: name.csv>>.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "SelectedFile".
 */
export interface SelectedFile {
  name: string;
  size: number;
  mime: string;
}
/**
 * For native dialog events (alert/confirm/prompt/beforeunload).
 */
export interface DialogInfo {
  kind: DialogKind;
  message: string;
  accepted?: boolean;
}
/**
 * SS6.6 -- a direct read on the test oracle. Retrieved via get_narration rather than pre-loaded, so an unambiguous step pays nothing for it.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "NarrationSegment".
 */
export interface NarrationSegment {
  id: string;
  startMs: number;
  endMs: number;
  text: string;
  confidence?: number;
}
/**
 * SS7.2 -- placeholders carry forward into the generated test as parameters, which makes Scenario Outline a natural extension rather than a separate feature.
 *
 * This interface was referenced by `Recording`'s JSON-Schema
 * via the `definition` "RedactionParameter".
 */
export interface RedactionParameter {
  /**
   * e.g. user_email_1
   */
  name: string;
  /**
   * e.g. <<user_email_1>>
   */
  placeholder: string;
  category: RedactionCategory;
  occurrences: number;
}
