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

export interface Evidence {
  literal: string;
  toolCallId: string;
  eventId: string;
  kind: string;
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
  /** SS9.9 -- what the critic said about this step and nothing resolved. Never
   *  in the feature file (its body is prose and nothing else) and never
   *  collapsed by default: an unresolved finding that a reviewer has to go
   *  looking for is one the loop may as well have swallowed. */
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

export interface TestCase {
  id: string;
  kind: 'test_case' | 'bug_report';
  title: string;
  scenarioName?: string;
  description: string;
  objective?: string;
  tags: string[];
  steps: Step[];
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
  metrics?: { groundingRate: number; assertionsTotal: number; toolCallsTotal: number };
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
};
