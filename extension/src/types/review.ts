/* Generated from schema/review.schema.json. Do not edit. */

export type ReviewEditKind =
  | "step_text"
  | "step_deleted"
  | "steps_merged"
  | "step_split"
  | "step_moved"
  | "assertion_accepted"
  | "assertion_rejected"
  | "assertion_text"
  | "escalation_answered"
  | "case_renamed"
  | "tags_changed";

/**
 * SS13 -- the human gate, and what it left behind. Every edit a reviewer makes is recorded: not as analytics, but because it is the `steps edited by a human` column of the ablation (SS3.5) and the y-axis of the effort/difficulty correlation (SS3.4). Collected for free from normal use, which is the only reason it is affordable.
 */
export interface ReviewDocument {
  schemaVersion: "1.0";
  recordingId: string;
  runId: string;
  projectId: string;
  ownerId: string;
  createdAt: string;
  updatedAt?: string;
  /**
   * Append-only. An edit is never removed, because the record of what a human changed is the measurement.
   */
  edits: ReviewEdit[];
  /**
   * Approval is what feeds the step library (SS12.2) -- a step is stored only once a human has accepted it, never merely because it was generated.
   */
  approved: boolean;
  approvedAt?: string;
  reviewer?: string;
}
/**
 * SS13.5 -- which step, what kind of change, how large.
 *
 * This interface was referenced by `ReviewDocument`'s JSON-Schema
 * via the `definition` "ReviewEdit".
 */
export interface ReviewEdit {
  id: string;
  timestamp: string;
  testCaseId: string;
  stepId?: string;
  assertionId?: string;
  kind: ReviewEditKind;
  before?: string;
  after?: string;
  /**
   * How large the change was, in characters. A one-word fix and a rewrite are different signals about how hard the step was.
   */
  magnitude?: number;
}
