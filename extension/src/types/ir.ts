/* Generated from schema/ir.schema.json. Do not edit. */

export type TestCaseKind = "test_case" | "bug_report";
export type StepKeyword = "Given" | "When" | "Then" | "And";
/**
 * SS9.3 -- what this step does in the narrative. Given/When/Then is a property of the whole scenario, not of one step, so the keyword is derived from this deterministically rather than chosen per step by a model.
 */
export type SegmentRole = "setup" | "test_step" | "teardown" | "exploratory" | "abandoned";
export type SelectorStrategy = "testId" | "role" | "text" | "css";
export type Confidence = "high" | "medium" | "low";
/**
 * Where an assertion came from, ranked per SS9.5. annotated/narrated/objective are direct statements of intent; inferred is a guess about it.
 */
export type Provenance = "annotated" | "narrated" | "objective" | "inferred" | "confirmed";
export type EvidenceKind = "semantic_node" | "url" | "network" | "console" | "narration" | "a11y_node";
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
export type OmissionReason = "exploratory" | "abandoned";
export type SuggestionCategory =
  "validation_path" | "api_error_shape" | "boundary_value" | "disabled_state" | "visible_branch";
export type WarningSource = "fidelity" | "critic" | "validator" | "recorder";
export type WarningSeverity = "info" | "warn" | "error";

/**
 * SS10 -- one canonical structure. Gherkin, Excel and Jira are renderers over it: no format is second-class, and a fourth output means writing a renderer, not touching the pipeline. A recording produces an array of test cases (SS9.3).
 */
export interface IRDocument {
  schemaVersion: "1.0";
  recordingId: string;
  /**
   * Links to the agent trace.
   */
  runId: string;
  projectId: string;
  ownerId: string;
  createdAt: string;
  testCases: TestCaseIR[];
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "TestCaseIR".
 */
export interface TestCaseIR {
  id: string;
  recordingId: string;
  runId: string;
  kind: TestCaseKind;
  /**
   * The capability under test, e.g. 'Order approval'. Renders as the Gherkin Feature name. NOT the tester's objective string: a Feature that repeats the Scenario verbatim reads as machine output, which is the first thing a QA lead judges.
   */
  title: string;
  /**
   * One or two sentences of context. Renders as the free-text description block under Feature:, which is where Gherkin natively puts this -- a leading # comment is not.
   */
  description: string;
  /**
   * The specific case this test exercises, e.g. 'An order over EUR500 is held for manager approval'. Renders as the Scenario name. Falls back to `title` only when composition did not run.
   */
  scenarioName?: string;
  /**
   * The tester's stated objective, verbatim (SS6.6).
   */
  objective?: string;
  /**
   * From segments classified 'setup'. Lift into a Gherkin Background when shared across test cases.
   */
  preconditions: Precondition[];
  tags: string[];
  steps: Step[];
  /**
   * From redaction placeholders (SS7.2).
   */
  parameters: Parameter[];
  /**
   * Exploratory/abandoned segments -- shown, not hidden. A verbatim transcript is unusable; silent deletion is untrustworthy.
   */
  omitted: OmittedSegment[];
  /**
   * SS9.8 -- STRICTLY QUARANTINED. Never rendered as steps, never exported as test cases, always labelled unverified.
   */
  suggestions?: CoverageSuggestion[];
  metadata: TestCaseMetadata;
  /**
   * Unresolved fidelity flags and critic findings. Never collapsed by default in the UI.
   */
  warnings: Warning[];
  bug?: BugDetail;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Precondition".
 */
export interface Precondition {
  id: string;
  text: string;
  eventIds: string[];
  /**
   * True when this precondition is common to several test cases and should lift into a Background block.
   */
  shared?: boolean;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Step".
 */
export interface Step {
  id: string;
  keyword: StepKeyword;
  /**
   * Intent, not mechanics. 'Submits the order' beats 'clicks the blue button'.
   */
  text: string;
  role?: SegmentRole;
  /**
   * Traceability into the recording. One of the two backlinks that carry the whole trust story (SS10): this one proves the sentence came from the recording.
   *
   * @minItems 1
   */
  eventIds: [string, ...string[]];
  /**
   * -> StepInvestigation in the trace. Renders as the 'why this step' panel (SS13.3).
   */
  investigationRef: string;
  screenshotRef?: string;
  /**
   * For later automation. Rendered as Gherkin comments, never in step text.
   */
  selectorHints?: SelectorHint[];
  assertions: Assertion[];
  /**
   * Set when reused from the step library. The library_verbatim validator enforces that the text matches the entry exactly.
   */
  libraryRef?: string;
  confidence: Confidence;
  /**
   * A specific question for the human. A first-class outcome, not a failure -- an agent that asks is more useful than one that guesses.
   */
  escalation?: string;
  fidelity: FidelityFlag[];
  criticNotes?: string[];
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "SelectorHint".
 */
export interface SelectorHint {
  strategy: SelectorStrategy;
  value: string;
  stability: Confidence;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Assertion".
 */
export interface Assertion {
  id: string;
  /**
   * Prose -- free. 'the confirmation banner appears'. This is what defuses paraphrase thrash: the model is never forced to write stiff sentences to satisfy a string match.
   */
  text: string;
  provenance: Provenance;
  evidence: Evidence;
  accepted: boolean;
  /**
   * Candidate ordering within the step. Each step gets 2-3 ranked candidates, never one (SS9.5).
   */
  rank?: number;
}
/**
 * SS3.2 -- the single most important structure in the system. A claim is valid only if its literal appeared in a tool response THIS agent actually received during THIS run.
 *
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Evidence".
 */
export interface Evidence {
  /**
   * Exact retrieved string, e.g. 'Order confirmed'. Checked character-for-character by evidence_retrieved.
   */
  literal: string;
  /**
   * The retrieval that produced it, e.g. tc_0447. The second of the two backlinks (SS10): this one proves the agent went and looked. If this id does not resolve in the trace, the assertion is rejected.
   */
  toolCallId: string;
  eventId: string;
  kind: EvidenceKind;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Parameter".
 */
export interface Parameter {
  name: string;
  placeholder: string;
  category: string;
  description?: string;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "OmittedSegment".
 */
export interface OmittedSegment {
  segmentId: string;
  reason: OmissionReason;
  eventCount: number;
  /**
   * e.g. 'browsed the reports page, returned'.
   */
  summary: string;
  /**
   * Which step this omission followed, so the UI can place the '3 exploratory actions omitted' marker.
   */
  afterStepId?: string;
}
/**
 * SS9.8 -- a prompt for the tester, not an artifact. Must never contaminate grounded output.
 *
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "CoverageSuggestion".
 */
export interface CoverageSuggestion {
  id: string;
  text: string;
  rationale: string;
  category: SuggestionCategory;
  /**
   * Event ids or tool call ids the observation rests on. Unverified is not the same as ungrounded.
   */
  basedOn?: string[];
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "TestCaseMetadata".
 */
export interface TestCaseMetadata {
  capturedAt: string;
  durationMs: number;
  browser: string;
  viewport: Viewport;
  startUrl: string;
  projectId: string;
  ownerId: string;
}
export interface Viewport {
  w: number;
  h: number;
}
/**
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Warning".
 */
export interface Warning {
  id: string;
  source: WarningSource;
  severity: WarningSeverity;
  message: string;
  stepId?: string;
  code?: string;
}
/**
 * SS14.2 -- present only when kind is 'bug_report'. `expected` and `actual` are subject to the same evidence binding as any assertion: `actual` must quote something the agent retrieved.
 *
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "BugDetail".
 */
export interface BugDetail {
  failureStepId: string;
  expected: string;
  actual: string;
  actualEvidence?: Evidence;
  consoleErrorIds?: string[];
  failedRequestIds?: string[];
  screenshotAtFailure?: string;
  environment: BugEnvironment;
}
export interface BugEnvironment {
  browser: string;
  viewport: string;
  url: string;
}
