/* Generated from schema/segments.schema.json. Do not edit. */

/**
 * Why this segment started. Highest priority first, per SS9.2.
 *
 * This interface was referenced by `SegmentsDocument`'s JSON-Schema
 * via the `definition` "BoundaryReason".
 */
export type BoundaryReason =
  | "recording_start"
  | "checkpoint_annotation"
  | "url_change"
  | "form_submit"
  | "state_mutation"
  | "idle_gap"
  | "region_replacement"
  | "hard_cap";
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
/**
 * SS9.3 -- what role a segment plays in the narrative. exploratory and abandoned are pruned from the test case but kept in the trace, and the review UI shows a marker so nothing is silently lost.
 */
export type SegmentRole = "setup" | "test_step" | "teardown" | "exploratory" | "abandoned";

/**
 * SS9.2 -- output of the deterministic segmenter. The same recording always produces the same segment count, which is what makes the audit trail meaningful and merge/split in the review UI predictable.
 */
export interface SegmentsDocument {
  schemaVersion: "1.0";
  recordingId: string;
  runId: string;
  projectId: string;
  ownerId: string;
  createdAt: string;
  segments: Segment[];
  /**
   * Total events in the source recording. Every one is assigned to exactly one segment -- none dropped (SS9.2).
   */
  eventCount: number;
}
/**
 * This interface was referenced by `SegmentsDocument`'s JSON-Schema
 * via the `definition` "Segment".
 */
export interface Segment {
  /**
   * e.g. seg_003
   */
  id: string;
  index: number;
  /**
   * @minItems 1
   */
  eventIds: [string, ...string[]];
  boundaryReason: BoundaryReason;
  startTimestamp: number;
  endTimestamp: number;
  startUrl?: string;
  endUrl?: string;
  /**
   * A cheap deterministic summary, e.g. 'click "Submit" -> POST /api/orders 201'. Lets the decompose stage read the whole session without pulling full snapshots.
   */
  label: string;
  /**
   * Successful state-mutating requests in this segment, e.g. 'POST /api/orders 201'. Used by the mutation_claimed validator.
   */
  mutations?: string[];
  /**
   * Union of the flags on this segment's events.
   */
  fidelity?: FidelityFlag[];
  hasCheckpoint?: boolean;
  hasScenarioBreak?: boolean;
  role?: SegmentRole;
}
