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
}

export interface TestCase {
  id: string;
  title: string;
  scenarioName?: string;
  description: string;
  objective?: string;
  tags: string[];
  steps: Step[];
  parameters: { name: string; placeholder: string; category: string }[];
  omitted: { segmentId: string; reason: string; eventCount: number; summary: string }[];
  warnings: { id: string; severity: string; message: string }[];
}

export interface IRDocument {
  recordingId: string;
  runId: string;
  createdAt: string;
  testCases: TestCase[];
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
}

export interface RunSummary {
  recordingId: string;
  runId: string;
  createdAt: string;
  approved: boolean;
  titles: string[];
  steps: number;
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

  run: (rec: string, run: string) => call<RunBody>(`/api/runs/${rec}/${run}`),

  toolResponse: (rec: string, run: string, id: string) =>
    call<unknown>(`/api/runs/${rec}/${run}/tools/${id}`),

  editStep: (rec: string, run: string, stepId: string, text: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/${stepId}`, patch({ text })),

  deleteStep: (rec: string, run: string, stepId: string) =>
    call<RunBody>(`/api/runs/${rec}/${run}/steps/${stepId}`, { method: 'DELETE' }),

  setAssertion: (rec: string, run: string, stepId: string, id: string, accepted: boolean) =>
    call<RunBody>(
      `/api/runs/${rec}/${run}/steps/${stepId}/assertions/${id}`,
      patch({ accepted }),
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
