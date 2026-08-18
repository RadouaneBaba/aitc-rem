/* Generated from schema/common.schema.json. Do not edit. */

/**
 * What the recorder could NOT determine. SS6.8. Propagates from event to step and is rendered prominently in review. Degrading loudly is the point.
 *
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "FidelityFlag".
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
 * Where an assertion came from, ranked per SS9.5. annotated/narrated/objective are direct statements of intent; inferred is a guess about it.
 *
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "Provenance".
 */
export type Provenance = "annotated" | "narrated" | "objective" | "inferred" | "confirmed";
/**
 * SS9.3 -- what role a segment plays in the narrative. exploratory and abandoned are pruned from the test case but kept in the trace, and the review UI shows a marker so nothing is silently lost.
 *
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "SegmentRole".
 */
export type SegmentRole = "setup" | "test_step" | "teardown" | "exploratory" | "abandoned";
/**
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "Confidence".
 */
export type Confidence = "high" | "medium" | "low";

/**
 * Types shared across the Recording, IR and Trace schemas.
 *
 * FramePath deliberately does NOT live here despite looking shared: datamodel-code-generator emits a bare `IframeHop | ShadowHop` without importing either name when a oneOf union is reached through a cross-file $ref, producing Python that does not import. Any future union stays in the file that uses it.
 */
export interface Common {
  [k: string]: unknown;
}
/**
 * Ranked, most-stable first. SS6.2. Only `css` is guaranteed present -- it is the last resort, not the preference.
 *
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "SelectorSet".
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
/**
 * SS16 -- carried from day one so multi-user needs no migration. Unused locally.
 *
 * This interface was referenced by `Common`'s JSON-Schema
 * via the `definition` "OwnershipFields".
 */
export interface OwnershipFields {
  projectId: string;
  ownerId: string;
  /**
   * ISO 8601, UTC.
   */
  createdAt: string;
}
