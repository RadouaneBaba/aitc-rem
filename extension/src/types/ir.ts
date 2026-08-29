/* Generated from schema/ir.schema.json. Do not edit. */

export type TestCaseKind = "test_case" | "bug_report";
/**
 * The keyword the author WROTE, read back off the feature file it wrote.
 *
 * It was derived from `role` plus position, which was right while the model was shown one segment at a time and could not know where the scenario turned -- asked for a keyword with no view of the flow it answered `When` every time, and Phase 1 shipped seven of them in a row. An author that writes the whole document in Gherkin has already decided, in the one place where the decision is visible to a reader, so deriving it a second time could only disagree with the file.
 *
 * `But` is here because the author's own parser has always accepted it and this enum did not, which made a perfectly ordinary negative step a validation error waiting for the first model that wrote one.
 */
export type StepKeyword = "Given" | "When" | "Then" | "And" | "But";
/**
 * SS9.3 -- what this step does in the narrative. Setup, the behaviour under test, or teardown. Kept alongside `keyword` because it survives re-rendering: a scenario that gets split still knows which of its steps were preconditions.
 */
export type SegmentRole = "setup" | "test_step" | "teardown" | "exploratory" | "abandoned";
export type SelectorStrategy = "testId" | "role" | "text" | "css";
export type Confidence = "high" | "medium" | "low";
/**
 * Where an assertion came from, ranked per SS9.5. annotated/narrated/objective are direct statements of intent; inferred is a guess about it.
 */
export type Provenance = "annotated" | "narrated" | "objective" | "inferred" | "confirmed";
export type EvidenceKind = "semantic_node" | "url" | "network" | "console" | "narration" | "annotation" | "a11y_node";
/**
 * contains  -- the literal appears in the response. The default, and what every assertion written before this meant.
 * first_of  -- the literal names the FIRST child of `container`, in document order. This is what makes a sort or a ranking checkable.
 * count     -- `container` holds exactly `n` children of role `role`. 'the list drops from 24 products to 9'.
 * absent    -- the literal does NOT appear. The judge's most frequent unmet ask, and the only form whose citation cannot be resolved by searching for its own literal.
 */
export type PredicateForm = "contains" | "first_of" | "count" | "absent";
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
  examples?: ScenarioExamples;
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
   * Empty is legal, and only for a step that exists to CHECK something. An expected result is about what the application did and does not need an action of its own -- `Then the number of free rooms drops from 3 to 2` is a step nobody clicked, and inventing a click to hang it on would put a sentence in the feature file describing something that never happened. Such a step carries its backlink on the assertion's own `evidence.eventId` instead.
   *
   * This was `minItems: 1` and the author's worked example showed a verdict-only step with no events, so the prompt taught a shape the schema rejected -- and it only surfaced the first time a real model took the example at its word, several stages downstream, as a Pydantic error during assembly. Worked examples outweigh rules; when the two disagree the example is usually right and the rule is the thing to change.
   *
   * The net that matters is `event_coverage`, which requires every recorded event to land in exactly one step or in an explicit omission. That is a statement about events, not about steps, and a step with no events cannot violate it.
   */
  eventIds: string[];
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
  confidence: Confidence;
  /**
   * A specific question for the human. A first-class outcome, not a failure -- an agent that asks is more useful than one that guesses.
   */
  escalation?: string;
  fidelity: FidelityFlag[];
  /**
   * Why this step has no expected result, in language the tester can act on: 'the product list was never captured before or after this click, so nothing here shows the order changed'.
   *
   * Refusal used to be something DONE TO the author -- a claim was proposed, could not be proved, and was deleted, so the scenario quietly ended with no `Then` while 27 style warnings said so in a vocabulary nobody outside the pipeline reads. It is now something the author WRITES, which means it can explain itself and a reviewer can close the gap. Never rendered into the feature body, which is prose and nothing else.
   */
  whyNot?: string;
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
   * Candidate ordering within the step. Two or three where the step genuinely produced more than one checkable outcome, one where only one thing mattered, none where nothing observable happened (SS9.5). Forcing a second candidate onto a step with one obvious outcome manufactures exactly the weak incidental assertion the ranking exists to demote.
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
  predicate?: Predicate;
}
/**
 * WHAT is being claimed about the retrieval, not merely that a string is in it.
 *
 * Without this the gate is substring containment, and `Then the first product is 'The Autumnal Hamper'` is proved by that string appearing ANYWHERE in the response. The sentence says FIRST; the check says PRESENT. Sorting, ranking, pagination and every negative assertion are inexpressible, so an author asked for a verdict on a sort could only ever restate that the page still says what the tester set the dropdown to.
 *
 * Absent means `contains`, which is the historical behaviour, so an assertion written before this existed means exactly what it always did.
 *
 * Three things about the design are load-bearing and were each a way to ship this broken:
 *
 * 1. A predicate addresses nodes by ROLE and NAME, never by a css id or a `ref`. The node model is ref/role/name/value/children and there are no ids anywhere; `ref` is a structural path that is stable only WITHIN one snapshot, so a predicate binds to exactly one stored response and cannot be re-pointed to another event the way a bare literal can.
 *
 * 2. It is evaluated against the STORED response, which is the full one. `get_snapshot` renders a capped view to the model, and the ranking that cap uses puts named nodes first -- so `first_of` evaluated against the capped view would return the first NAMED node rather than the first in document order, and on a product grid the nameless wrapper nodes are exactly what ranks to the back. It would confidently return the wrong answer and pass the gate.
 *
 * 3. It has THREE outcomes, not two. A predicate that cannot be evaluated at all -- container absent, role mismatch, the response is not a snapshot -- is neither true nor false, and treating it as either is a different failure. Pass builds a laundering machine that puts a green badge on an unchecked claim; reject silently kills true claims whenever a response shape changes. It goes to `whyNot`.
 *
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "Predicate".
 */
export interface Predicate {
  form: PredicateForm;
  container?: NodeRef;
  /**
   * Which children `count` counts, e.g. 'listitem'. Absent counts every child.
   */
  role?: string;
  /**
   * The expected count, for `count`.
   */
  n?: number;
}
/**
 * Which part of the page the claim is about. Required by first_of and count; meaningless to contains and absent, which are about the whole response.
 */
export interface NodeRef {
  role: string;
  /**
   * The accessible name. Matched case-insensitively, and a container with no name is addressed by role alone.
   */
  name?: string;
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
  /**
   * The segment this omission came from, when a segment is what was omitted. Absent when the drafter omitted a set of events that does not correspond to one segment.
   */
  segmentId?: string;
  /**
   * The events this omission accounts for. event_coverage is the net under the drafter's freedom to choose step boundaries: every recorded event must land in a step or in one of these, so an omission that names no events cannot discharge anything.
   */
  eventIds?: string[];
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
 * A `Scenario Outline`'s table, when the author decided this flow is one behaviour exercised with several sets of values.
 *
 * Distinct from `parameters`, which lifts REDACTION placeholders into an Examples row and is a rendering setting. This is a judgement about test design: a recording that adds 13 items and then 18 comes out as two near-identical scenarios and reads as a transcript, where one outline over two rows reads as a test somebody designed.
 */
export interface ScenarioExamples {
  columns: string[];
  rows: string[][];
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
/**
 * A node named the way the accessibility tree names it. Never a css selector: the recorder is black-box and reads the live accessibility tree, so role plus accessible name is the only address that exists for it -- and it is the address a human reading the test can also check.
 *
 * This interface was referenced by `IRDocument`'s JSON-Schema
 * via the `definition` "NodeRef".
 */
export interface NodeRef1 {
  role: string;
  /**
   * The accessible name. Matched case-insensitively, and a container with no name is addressed by role alone.
   */
  name?: string;
}
