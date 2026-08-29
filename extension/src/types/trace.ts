/* Generated from schema/trace.schema.json. Do not edit. */

/**
 * SS3.5 -- one flag, three configurations, the same recordings. A0 is the shape this project replaces.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "AblationConfig".
 */
export type AblationConfig = "A0" | "A1" | "A2";
/**
 * read_write is the development default: replay when the exact prompt was seen before, call the real API otherwise. read_only makes a run fully offline and deterministic.
 */
export type CassetteMode = "off" | "read_write" | "read_only" | "record_only";
export type TruncationStrategy = "head_tail" | "head" | "none";
/**
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "PipelineStage".
 */
export type PipelineStage = "segment" | "expectations" | "author" | "judge" | "validate" | "coverage" | "render";
export type StopReason = "no_investigation_needed" | "evidence_sufficient" | "budget_exhausted" | "escalated";
/**
 * degraded -- the stage produced usable output by falling back rather than by doing its job. Distinguished from ok because a fallback that reports success is how a quiet failure becomes permanent.
 */
export type StageStatus = "ok" | "failed" | "skipped" | "degraded";
export type ValidatorName =
  "evidence_retrieved" | "event_coverage" | "gherkin_parses" | "no_placeholder_leak" | "suggestions_quarantined";
export type ValidatorStatus = "pass" | "fail" | "warn" | "skip";
/**
 * reject -> regenerate. hard_fail -> do not render at all (no_placeholder_leak only).
 */
export type ValidatorAction = "none" | "reject" | "warn" | "hard_fail";
/**
 * What raised the finding. `critic` is historical -- that stage is deleted -- and is kept so an old trace still validates.
 */
export type RepairTrigger = "validator" | "critic" | "judge";
export type DecompositionKind = "test_case_boundary" | "segment_role" | "shared_setup";
/**
 * SS9.3 -- what role a segment plays in the narrative. exploratory and abandoned are pruned from the test case but kept in the trace, and the review UI shows a marker so nothing is silently lost.
 */
export type SegmentRole = "setup" | "test_step" | "teardown" | "exploratory" | "abandoned";

/**
 * SS9.10 -- a schema'd artifact versioned with the run, designed as a product artifact rather than a log file. Consumed by the validators, the review UI's 'why this step' panel, and the ablation.
 */
export interface AgentTrace {
  schemaVersion: "1.0";
  runId: string;
  recordingId: string;
  projectId: string;
  ownerId: string;
  createdAt: string;
  config: RunConfig;
  /**
   * SS8.2 -- not debug output. This is the substrate evidence_retrieved resolves against, the data behind the review UI's why-panel, and the raw material for the agency proof.
   */
  toolCalls: ToolCall[];
  modelCalls: ModelCall[];
  investigations: StepInvestigation[];
  stages: StageRecord[];
  validatorResults: ValidatorResult[];
  repairAttempts: RepairAttempt[];
  decompositionDecisions: DecompositionDecision[];
  metrics?: RunMetrics;
}
/**
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "RunConfig".
 */
export interface RunConfig {
  ablation: AblationConfig;
  /**
   * False only for A0. Disable tools and the pipeline cannot emit a single valid assertion -- not 'degrades', cannot (SS3.2).
   */
  toolsEnabled: boolean;
  /**
   * Whether this run had an oracle. A0 and A1 do not: they can only restate what the application did, which is the boundary the whole rebuild is about. A1 vs A2 is therefore what asking a human is worth, held against everything else being equal.
   *
   * Replaces criticEnabled and repairEnabled. Those arms measured a loop that raised 9 findings and resolved 1, because five of the survivors were `coherence` and it had no repair route by design.
   */
  expectationsEnabled: boolean;
  defaultInvestigationBudget?: number;
  /**
   * Per stage (SS9.12). The ablation pins one provider and one model across A0/A1/A2 and disables fallback, or it measures provider variance instead of architecture.
   */
  models?: {
    [k: string]: {
      provider: string;
      model: string;
    };
  };
  fallbackEnabled?: boolean;
  cassetteMode?: CassetteMode;
  a0Truncation?: TruncationPolicy;
}
/**
 * Pre-declared for A0, which pre-loads all context with no tools and will not fit a long recording in any context window. If A0 truncates silently the ablation measures truncation rather than architecture, so the policy is stated up front and the dropped volume is reported as a metric.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "TruncationPolicy".
 */
export interface TruncationPolicy {
  strategy: TruncationStrategy;
  tokenBudget: number;
  tokensDropped?: number;
  eventsDropped?: number;
  /**
   * True when the recording did not fit. Reported as an ablation finding, not an error.
   */
  overflowed?: boolean;
}
/**
 * SS3.2 -- every call logged with a content-addressed response.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "ToolCall".
 */
export interface ToolCall {
  /**
   * e.g. tc_0447
   */
  id: string;
  stage: PipelineStage;
  stepId?: string;
  segmentId?: string;
  /**
   * e.g. get_snapshot
   */
  tool: string;
  args: {
    [k: string]: unknown;
  };
  /**
   * runs/<rec>/tools/tc_0447.json, relative to the run root.
   */
  responsePath: string;
  /**
   * sha256 of canonical_json(response). Canonical serialization is load-bearing: any key-order or whitespace variance between write and re-read would reject a CORRECT assertion.
   */
  responseHash: string;
  timestamp: number;
  durationMs?: number;
  /**
   * Set when the tool raised. The call is still logged -- a failed retrieval is evidence too.
   */
  error?: string;
}
/**
 * Token and latency accounting. Feeds the budget guard and the ablation's cost column.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "ModelCall".
 */
export interface ModelCall {
  id: string;
  stage: PipelineStage;
  stepId?: string;
  provider: string;
  model: string;
  /**
   * Position within a multi-turn tool loop.
   */
  turn?: number;
  promptTokens?: number;
  completionTokens?: number;
  latencyMs?: number;
  /**
   * True when served from the cassette rather than the provider. Cached calls consume no quota and no money.
   */
  cached: boolean;
  attempt?: number;
  finishReason?: string;
  error?: string;
  timestamp: number;
}
/**
 * SS3.3 -- agency includes deciding how much work a decision deserves. A step with an obvious outcome should cost zero calls; an ambiguous one should cost eight. That variance is the observable signature of adaptive behaviour.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "StepInvestigation".
 */
export interface StepInvestigation {
  id: string;
  stepId?: string;
  segmentId?: string;
  stage: PipelineStage;
  /**
   * What the agent could not determine up front. Empty means the evidence was already sufficient.
   */
  initialUncertainty: string[];
  toolCallIds: string[];
  budgetUsed: number;
  budgetMax: number;
  stopReason: StopReason;
  stopRationale?: string;
  /**
   * Set when stopReason is 'escalated'. Rendered as a direct question next to the step. A first-class outcome, not a failure.
   */
  escalationQuestion?: string;
  /**
   * Ordered, human-readable trace for the why-panel: what it didn't know, what it looked at, what it found, why it stopped.
   */
  narrative?: string[];
}
/**
 * SS9.1 -- each stage reads a file and writes a file, so when output is wrong you open the intermediate artifact and see exactly which stage lied.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "StageRecord".
 */
export interface StageRecord {
  stage: PipelineStage;
  attempt: number;
  inputPath?: string;
  outputPath: string;
  startedAt: number;
  endedAt?: number;
  status: StageStatus;
  error?: string;
}
/**
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "ValidatorResult".
 */
export interface ValidatorResult {
  validator: ValidatorName;
  status: ValidatorStatus;
  action: ValidatorAction;
  testCaseId?: string;
  stepId?: string;
  assertionId?: string;
  message?: string;
  attempt: number;
  /**
   * Why the validator had no subject, e.g. 'no library entries in Phase 1'. A skip is recorded, never silently omitted.
   */
  skipReason?: string;
}
/**
 * SS9.9 -- findings are not merely reported; the author re-runs with them as input. Bounded at one revision round: the rebuild deleted the routing table that decided WHICH stage re-runs, because the author wrote the document and is the only thing that knows which part of it is wrong.
 *
 * `resolved` was required and is now a deprecated optional -- see its own description.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "RepairAttempt".
 */
export interface RepairAttempt {
  stage: PipelineStage;
  attempt: number;
  trigger: RepairTrigger;
  finding: string;
  targetStepId?: string;
  /**
   * DEPRECATED and no longer written. It was required, and hardcoded `false` at all three construction sites, because what was resolved between two whole-document rewrites is genuinely not knowable -- matching a round-2 finding to the round-1 one it descended from is a guess. The reasoning was right and the field was not: a required boolean that is always false is a column of noise that reads like a measurement. Kept OPTIONAL rather than deleted because every model here is `additionalProperties: false`, so removing it outright stops every trace already on disk from parsing -- which is how it was noticed, when `prove_grounding.py` failed to read thirty existing runs. Nothing writes it; everything still reads it. What is reported instead is `judgeFindings` and `judgeFails`, counts of what is still true of the document that shipped.
   */
  resolved?: boolean;
  /**
   * Budget ran out with the finding unresolved. The step is surfaced to the human with the finding stated plainly -- never silently accepted.
   */
  exhausted?: boolean;
}
/**
 * SS9.3 -- no deterministic rule can tell a false start from a legitimate test step, so the rationale is recorded.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "DecompositionDecision".
 */
export interface DecompositionDecision {
  kind: DecompositionKind;
  segmentId?: string;
  testCaseId?: string;
  role?: SegmentRole;
  rationale: string;
  toolCallIds?: string[];
}
/**
 * SS3.5 -- six of seven ablation metrics come from machinery built for other reasons. These are those.
 *
 * This interface was referenced by `AgentTrace`'s JSON-Schema
 * via the `definition` "RunMetrics".
 */
export interface RunMetrics {
  assertionsTotal?: number;
  assertionsGrounded?: number;
  /**
   * Logged from day one as a free regression signal (SS17.1).
   */
  groundingRate?: number;
  assertionsUngrounded?: number;
  /**
   * SS3.5 -- 'validator pass rate (FIRST attempt)'. Frozen at attempt 1 and never overwritten by the repair loop: a repair that lifted this number would be reporting itself working by hiding that it had to.
   */
  validatorFirstPassRate?: number;
  /**
   * The same gate after the repair loop has finished. Read as a pair with validatorFirstPassRate -- the distance between them is what repair bought.
   */
  validatorFinalPassRate?: number;
  /**
   * How much the judge had to say about the document that SHIPPED: weak and fail together, from the final round. Deliberately not a total across rounds, and not a convergence rate. `Converged` reported 1-of-9 because it measured how much of what the critic said the loop was ALLOWED to act on, and matching a finding in round 2 to the one it descended from in round 1 is a guess rather than a fact -- so this counts what is still true of the artifact instead of claiming to know what was fixed. Replaces criticFindingsRaised, which was read off the repair loop rather than off the critic and was wrong in 10 of 13 runs, in both directions.
   */
  judgeFindings?: number;
  /**
   * Of those, the ones a QA lead would send back rather than sign after an edit. Non-zero here means the document shipped with a finding the loop could not resolve inside its bound, which is the honest reading of SS9.9 rather than an omission -- and it is the number to watch, because it is the one a rate would hide.
   */
  judgeFails?: number;
  /**
   * Author rounds actually run. 1 means the judge and the gate found nothing worth another pass, which is the normal case; 2 means the document was rewritten once. Read beside judgeFails: rounds alone cannot distinguish a document nobody objected to from one whose findings the bound cut off.
   */
  revisionRounds?: number;
  /**
   * Findings handed back to the author across the run, one per (round, finding). A different fact from judgeFindings -- a rejected claim is a repair with no judge finding behind it -- and worth keeping separate now that the two are no longer conflated.
   */
  repairAttempts?: number;
  toolCallsTotal?: number;
  /**
   * Keyed by stepId. The x-axis of the effort/difficulty correlation (SS3.4), and the column that separates an agent from a chain -- a chain is flat by construction.
   */
  toolCallsPerStep?: {
    [k: string]: number;
  };
  /**
   * Collected passively from the review UI (SS13.5).
   */
  stepsEditedByHuman?: number;
  promptTokensTotal?: number;
  completionTokensTotal?: number;
  uncachedModelCalls?: number;
  durationMs?: number;
}
