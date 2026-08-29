/**
 * The one place the UI talks to the server.
 *
 * Every review action returns the whole {ir, review, feature} triple rather
 * than a patch, because a step edit can change the rendered keyword of the step
 * after it (SS11.1 derives Given/When/And from the whole scenario). A UI that
 * applied a local patch would drift from the file the tester downloads.
 */

export type Confidence = 'high' | 'medium' | 'low';
export type Provenance = 'annotated' | 'narrated' | 'objective' | 'inferred' | 'confirmed';

/**
 * WHAT is claimed about the literal, not just that it appeared.
 *
 * Without this the gate was substring containment, so *"the first product is
 * 'The Autumnal Hamper'"* was proved by that string appearing anywhere on the
 * page: the sentence said FIRST and the check said PRESENT. It has been in the
 * schema since the predicate work landed and the UI has never rendered it, so a
 * reviewer could not tell a positional claim from a presence one -- which is
 * the exact distinction the judge keeps sending documents back over.
 */
export interface Predicate {
  form: 'contains' | 'first_of' | 'count' | 'absent';
  container?: { role?: string; name?: string };
  role?: string;
  n?: number;
}

export interface Evidence {
  literal: string;
  toolCallId: string;
  eventId: string;
  kind: string;
  predicate?: Predicate;
}

export interface Assertion {
  id: string;
  text: string;
  provenance: Provenance;
  evidence: Evidence;
  accepted: boolean;
  rank?: number;
}

export interface Step {
  id: string;
  keyword: string;
  role?: string;
  text: string;
  eventIds: string[];
  investigationRef: string;
  assertions: Assertion[];
  confidence: Confidence;
  escalation?: string;
  fidelity: string[];
  selectorHints?: { strategy: string; value: string; stability: string }[];
  /** Why this step has no expected result, in the tester's own language.
   *
   *  The most valuable thing the author writes and it reached nothing until
   *  now: a claim that could not be proved used to be deleted, the scenario
   *  ended silently without a `Then`, and a style warning said so in a
   *  vocabulary nobody outside the pipeline reads. Never in the feature file --
   *  its body is prose and nothing else -- and never collapsed here, because a
   *  gap a reviewer has to go looking for is one the tool may as well have
   *  hidden. */
  whyNot?: string;
  /** Historical. The critic is deleted; the judge that replaced it hands its
   *  findings to the author and never to the tester. Kept only so an old run
   *  still parses. */
  criticNotes?: string[];
}

/** SS9.8 -- a prompt for the tester, never an artifact. Rendered apart from the
 *  steps and labelled unverified, which is the UI half of the quarantine. */
export interface CoverageSuggestion {
  id: string;
  text: string;
  rationale: string;
  category: string;
  basedOn?: string[];
}

/** SS14.2 -- present only on a bug report. `actual` carries its citation,
 *  because "the server returned 500" is worth exactly as much as the reader's
 *  ability to check it. */
export interface BugDetail {
  failureStepId: string;
  expected: string;
  actual: string;
  actualEvidence?: Evidence;
  environment: { browser: string; viewport: string; url: string };
}

/** A shared opening lifted into a `Background`. The second scenario's own steps
 *  begin partway through the flow, so without these on screen a reviewer reads
 *  scenario 2 as starting from nowhere. */
export interface Precondition {
  id: string;
  text: string;
  eventIds: string[];
  shared?: boolean;
}

export interface TestCase {
  id: string;
  kind: 'test_case' | 'bug_report';
  title: string;
  scenarioName?: string;
  description: string;
  objective?: string;
  tags: string[];
  steps: Step[];
  preconditions?: Precondition[];
  /** One flow exercised with several sets of values -- a judgement about test
   *  design the author makes, distinct from the `parameters: outline` rendering
   *  setting. Two rows minimum: one row is not a table. */
  examples?: { columns: string[]; rows: string[][] };
  parameters: { name: string; placeholder: string; category: string }[];
  omitted: { segmentId: string; reason: string; eventCount: number; summary: string }[];
  warnings: { id: string; source: string; severity: string; message: string; stepId?: string; code?: string }[];
  suggestions?: CoverageSuggestion[];
  bug?: BugDetail;
}

export interface IRDocument {
  recordingId: string;
  runId: string;
  createdAt: string;
  testCases: TestCase[];
}

/**
 * A pipeline run in flight. `detail` is prose for a tester, not a stage name:
 * a run takes minutes on purpose, and the difference between "deliberately
 * slow" and "hung" has to be visible or the tester presses Stop again.
 */
export interface Job {
  id: string;
  recordingId: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  detail: string;
  runId: string | null;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface Investigation {
  id: string;
  stepId?: string;
  stage: string;
  initialUncertainty: string[];
  toolCallIds: string[];
  budgetUsed: number;
  budgetMax: number;
  stopReason: string;
  narrative?: string[];
}

export interface ToolCall {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  stepId?: string;
}

export interface Trace {
  investigations: Investigation[];
  toolCalls: ToolCall[];
  validatorResults: {
    validator: string;
    status: string;
    message?: string;
    stepId?: string;
  }[];
  metrics?: {
    groundingRate: number;
    assertionsTotal: number;
    toolCallsTotal: number;
    /** What the QA read sent back. `judgeFails` is what a lead would refuse to
     *  sign; `judgeFindings` counts those plus the ones they would sign after an
     *  edit. Both are counts and never rates -- a rate over a run that claimed
     *  nothing reads perfect, which is the trap this project has now met in
     *  seven columns. */
    judgeFindings?: number;
    judgeFails?: number;
  };
}

export interface ReviewDoc {
  approved: boolean;
  approvedAt?: string;
  reviewer?: string;
  edits: { id: string; kind: string; stepId?: string; magnitude?: number }[];
}

export interface RunBody {
  ir: IRDocument;
  trace: Trace | null;
  review: ReviewDoc;
  feature: Record<string, string>;
  /** Event ids that actually have a screenshot on disk. Sent with the run so
   *  the step pane can decide whether to render an `<img>` at all -- asking per
   *  step produced a 404 per click on every recording without a `screens/`
   *  directory, which is every imported one. */
  screens?: string[];
}

/**
 * SS6.6 -- what the tester said during a step.
 *
 * `supportsRank` comes from the server rather than being recomputed here: the
 * validators and this panel disagreeing about which sentence counted would be
 * worse than not showing it. Narration is the one lossy evidence source in the
 * tool, and that is exactly why it is shown with its audio.
 */
export interface NarrationSegment {
  id: string;
  startMs: number;
  endMs: number;
  text: string;
  confidence?: number;
  supportsRank: boolean;
}

export interface StepNarration {
  hasAudio: boolean;
  minConfidence?: number;
  segments: NarrationSegment[];
}

export interface RunSummary {
  recordingId: string;
  runId: string;
  createdAt: string;
  approved: boolean;
  titles: string[];
  steps: number;
  /** Everything below is what the run list needs to say which run wants a
   *  human first. All of it is read out of `ir.json`; none of it is new. */
  scenarios?: string[];
  assertions?: number;
  warnings?: number;
  flaggedSteps?: number;
  editedSteps?: number;
  hasBug?: boolean;
  /** How many things a QA lead would refuse to sign. The one number in this
   *  list that is about the OUTPUT rather than about how much of it is
   *  unfinished, which makes it the reason to open one draft before another. */
  judgeFails?: number;
}

/**
 * What a QA lead would send back, and why.
 *
 * `judge.py` has written `judge.json` on every run since it landed and nothing
 * ever read it. The review screen showed the COUNT -- an unclickable red badge
 * reading "3 a QA lead would send back" -- while the sentences saying which
 * three and what to do about them sat on disk.
 *
 * `fail` is what a lead would refuse to sign. `weak` is what they would sign
 * after an edit, which is worth showing to the person making edits even though
 * the pipeline deliberately does not spend a revision round on it.
 */
export interface JudgeFinding {
  check: string;
  severity: 'fail' | 'weak' | string;
  what: string;
  fix?: string;
  scenario?: string;
  stepId?: string;
}

export interface Judgement {
  findings: JudgeFinding[];
  /** Set when the judge call itself failed. The run survives -- a judgement is
   *  worth less than the document it judges -- and the difference between
   *  "nothing was wrong" and "nobody looked" is not one to leave to a blank
   *  panel. */
  failed: string;
}

/**
 * SS-none: this is new. What SHOULD have happened, per action.
 *
 * The pipeline can only license claims about what the application DID. This is
 * the one input that says what it should have done, and it is answered with
 * three buttons rather than a text field because a tester will click and will
 * not write.
 */
export type ExpectationSource = 'inferred' | 'confirmed' | 'corrected' | 'stated' | 'rejected';

export interface Expectation {
  id: string;
  eventIds: string[];
  action: string;
  expected: string;
  observed?: string;
  source: ExpectationSource;
  screenshot?: string;
  note?: string;
}

export interface ExpectationSet {
  schemaVersion: string;
  recordingId: string;
  createdAt: string;
  confirmedAt?: string;
  expectations: Expectation[];
}

export interface ExpectationAnswer {
  id: string;
  source: ExpectationSource;
  expected?: string;
  note?: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { 'content-type': 'application/json' } : undefined,
  });
  if (!response.ok) {
    // The server sends a sentence, not a code. Surfacing it verbatim is the
    // difference between "something went wrong" and "only adjacent steps can
    // be merged".
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
const patch = (body: unknown): RequestInit => ({ method: 'PATCH', body: JSON.stringify(body) });

export const api = {
  runs: () => call<{ runs: RunSummary[] }>('/api/runs'),

  jobs: () => call<{ jobs: Job[] }>('/api/jobs'),

  run: (rec: string, run: string) => call<RunBody>(`/api/runs/${rec}/${run}`),

  toolResponse: (rec: string, run: string, id: string) =>
    call<unknown>(`/api/runs/${rec}/${run}/tools/${id}`),

  /** Absent is not an error -- A0 has no judge by construction, and every run
   *  made before the judge existed has no file. The endpoint answers with an
   *  empty list rather than a 404 so the panel has nothing to special-case. */
  judge: (rec: string, run: string) => call<Judgement>(`/api/runs/${rec}/${run}/judge`),

  /** SS13.2 -- edit the prose where a reader actually reads it. The changes are
   *  replayed through the same review functions the step forms call, so the
   *  SS13.5 record is identical either way. */
  editFeature: (rec: string, run: string, caseId: string, text: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/cases/${caseId}/feature`, {
      method: 'PATCH',
      body: JSON.stringify({ text }),
    }),

  stepNarration: (rec: string, run: string, stepId: string) =>
    call<StepNarration>(`/api/runs/${rec}/${run}/steps/${stepId}/narration`),

  /** The clip itself. A transcript is a reconstruction, and a mis-heard literal
   *  passes every automatic check this project makes -- so the only check left
   *  is a person listening. */
  audioUrl: (rec: string) => `/api/recordings/${rec}/audio`,

  editStep: (rec: string, run: string, stepId: string, text: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/${stepId}`, patch({ text })),

  deleteStep: (rec: string, run: string, stepId: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/${stepId}`, { method: 'DELETE' }),

  setAssertion: (rec: string, run: string, stepId: string, id: string, accepted: boolean) =>
    call<RunBody>(
      `/api/runs/${rec}/${run}/steps/${stepId}/assertions/${id}`,
      patch({ accepted }),
    ),

  /** Reword an expected result. The literal and its toolCallId are not editable
   *  from here at all -- the sentence is the reviewer's, the citation is not. */
  rewordAssertion: (rec: string, run: string, stepId: string, id: string, text: string) =>
    call<RunBody>(
      `/api/runs/${rec}/${run}/steps/${stepId}/assertions/${id}`,
      patch({ text }),
    ),

  answerEscalation: (rec: string, run: string, stepId: string, answer: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/${stepId}/escalation`, json({ answer })),

  mergeSteps: (rec: string, run: string, stepIds: string[], text?: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/merge`, json({ stepIds, text })),

  renameCase: (rec: string, run: string, caseId: string, body: { title?: string; scenarioName?: string }) =>
    call<RunBody>(`/api/runs/${rec}/${run}/cases/${caseId}`, patch(body)),

  approve: (rec: string, run: string, reviewer?: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/approve`, json({ reviewer })),

  exportRun: (rec: string, run: string, formats: string[]) =>
    call<{ exports: { exporter: string; files: string[]; warnings: string[] }[] }>(
      `/api/runs/${rec}/${run}/export`,
      json({ formats }),
    ),

  fileUrl: (rec: string, run: string, name: string) =>
    `/api/runs/${rec}/${run}/files/${encodeURIComponent(name)}`,

  /** 404 while the guess is still running, which is the normal first seconds
   *  after Stop. The confirmation screen retries rather than erroring. */
  expectations: (rec: string) => call<ExpectationSet>(`/api/recordings/${rec}/expectations`),

  /** Answering enqueues a fresh run. The answers are an input to authoring, not
   *  an edit to its output, so the pipeline has to run again to use them. */
  answerExpectations: (rec: string, answers: ExpectationAnswer[]) =>
    call<{ job: Job; expectations: ExpectationSet }>(
      `/api/recordings/${rec}/expectations`,
      json({ answers }),
    ),

  /** Recordings whose guesses nobody has answered yet.
   *
   *  The confirmation screen used to be reachable only from the extension's
   *  export page, via a query parameter read once at mount and cleared on
   *  dismiss -- so missing that one link lost it for good. 14 expectation sets
   *  reached disk and all 14 stayed `inferred`, which means every stage
   *  downstream has only ever read guesses nobody checked. */
  pendingExpectations: () =>
    call<{ pending: PendingConfirmation[] }>('/api/expectations/pending'),
};

export type PendingConfirmation = {
  recordingId: string;
  count: number;
  createdAt?: string;
};
