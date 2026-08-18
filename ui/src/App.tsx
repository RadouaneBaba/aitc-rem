/**
 * The review UI (SS13.1).
 *
 *   ┌────────────┬──────────────────────────────┬─────────────────────┐
 *   │ Test cases │ Selected step                │ Evidence  ·  Why    │
 *
 * Two things carry the whole design. The middle pane must make accept/reject
 * take seconds, because that is the loop a tester runs dozens of times. The
 * right pane must show that the tool went and looked, because a confident
 * sentence with no provenance gets doubted and rightly (SS13.3).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type RunBody, type RunSummary, type Step, type TestCase } from './api';
import { StepList } from './components/StepList';
import { StepDetail } from './components/StepDetail';
import { EvidencePanel } from './components/EvidencePanel';
import { RunPicker } from './components/RunPicker';

export function App() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<RunSummary | null>(null);
  const [body, setBody] = useState<RunBody | null>(null);
  const [stepId, setStepId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .runs()
      .then(({ runs }) => {
        setRuns(runs);
        setSelected((current) => current ?? runs[0] ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api
      .run(selected.recordingId, selected.runId)
      .then((next) => {
        setBody(next);
        setStepId(next.ir.testCases[0]?.steps[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [selected]);

  /** Every mutation goes through here, so one failure path serves all of them. */
  const act = useCallback(
    async (work: (rec: string, run: string) => Promise<RunBody>) => {
      if (!selected) return;
      setBusy(true);
      setError(null);
      try {
        setBody(await work(selected.recordingId, selected.runId));
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [selected],
  );

  const testCase: TestCase | undefined = body?.ir.testCases[0];
  const step: Step | undefined = useMemo(
    () => body?.ir.testCases.flatMap((c) => c.steps).find((s) => s.id === stepId),
    [body, stepId],
  );

  if (!body || !selected) {
    return (
      <div className="empty">
        {error ? <p className="error">{error}</p> : <p>Looking for a run…</p>}
        {!error && runs.length === 0 && (
          <p className="muted">
            Record something with the extension, or run the pipeline once from the CLI.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="app">
      <header>
        <RunPicker runs={runs} selected={selected} onSelect={setSelected} />
        <div className="spacer" />
        {body.review.approved ? (
          <span className="badge approved">approved</span>
        ) : (
          <button
            className="primary"
            disabled={busy}
            onClick={() => act((rec, run) => api.approve(rec, run))}
          >
            Approve
          </button>
        )}
        <ExportMenu
          recordingId={selected.recordingId}
          runId={selected.runId}
          testCases={body.ir.testCases}
          onError={setError}
        />
      </header>

      {error && (
        <div className="error banner" role="alert">
          {error}
          <button onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      <main>
        <StepList
          testCases={body.ir.testCases}
          selectedId={stepId}
          onSelect={setStepId}
          edited={new Set(body.review.edits.map((e) => e.stepId).filter(Boolean) as string[])}
          onRename={(caseId, patch) => act((rec, run) => api.renameCase(rec, run, caseId, patch))}
          onMerge={(ids) => act((rec, run) => api.mergeSteps(rec, run, ids))}
          busy={busy}
        />

        {step && testCase ? (
          <StepDetail
            step={step}
            busy={busy}
            onEdit={(text) => act((rec, run) => api.editStep(rec, run, step.id, text))}
            onDelete={() => act((rec, run) => api.deleteStep(rec, run, step.id))}
            onAssertion={(id, accepted) =>
              act((rec, run) => api.setAssertion(rec, run, step.id, id, accepted))
            }
            onAnswer={(answer) =>
              act((rec, run) => api.answerEscalation(rec, run, step.id, answer))
            }
          />
        ) : (
          <section className="detail">
            <p className="muted">Select a step.</p>
          </section>
        )}

        <EvidencePanel
          step={step}
          trace={body.trace}
          feature={Object.values(body.feature)[0] ?? ''}
          recordingId={selected.recordingId}
          runId={selected.runId}
        />
      </main>
    </div>
  );
}

function ExportMenu({
  recordingId,
  runId,
  testCases,
  onError,
}: {
  recordingId: string;
  runId: string;
  testCases: TestCase[];
  onError: (message: string) => void;
}) {
  const [files, setFiles] = useState<string[]>([]);

  const run = async (formats: string[]) => {
    try {
      const { exports } = await api.exportRun(recordingId, runId, formats);
      setFiles(exports.flatMap((e) => e.files));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  // The feature file and its evidence sidecar always exist; the others are
  // produced on demand so a team that lives in Excel is not handed three files
  // it did not ask for.
  const always = testCases.flatMap((c) => [`${c.id}.feature`, `${c.id}.trace.md`]);

  return (
    <div className="exports">
      {always.map((name) => (
        <a key={name} href={api.fileUrl(recordingId, runId, name)} download>
          {name.endsWith('.feature') ? '.feature' : 'evidence'}
        </a>
      ))}
      <button onClick={() => run(['xlsx'])}>Excel</button>
      <button onClick={() => run(['jira'])}>Jira</button>
      {files.map((name) => (
        <a key={name} href={api.fileUrl(recordingId, runId, name)} download className="fresh">
          {name}
        </a>
      ))}
    </div>
  );
}
