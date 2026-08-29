/**
 * The review UI.
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │ ◆ AITC   run ▾                    ⌘K  ☾  ?      [Approve]   │
 *   ├────────────────────────────────────────────────────────────┤
 *   │ 3 checks · 9 retrievals · 3 to fix        [Steps][Feature]  │
 *   ├──────────────────┬─────────────────────────────────────────┤
 *   │ steps            │ the selected step, or the feature file   │
 *   └──────────────────┴─────────────────────────────────────────┘
 *
 * Two panes, where there were three plus a footer.
 *
 * The third pane held the feature file and the evidence, and served neither.
 * The feature file -- the artifact this tool is judged on -- was clipped in a
 * 30% column; the evidence was two collapsed triangles in a pane that was
 * otherwise empty. So the feature file became a MODE, at full width, and the
 * evidence moved onto the card where a reviewer accepts or rejects, which is
 * the only place it is load-bearing.
 *
 * The measurement behind all of it: 21 runs on disk, zero review edits, zero
 * approvals, ever. Nobody had finished this loop once.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type Judgement, type RunBody, type RunSummary, type Step, type TestCase } from './api';
import { StepList } from './components/StepList';
import { StepDetail } from './components/StepDetail';
import { FeatureView } from './components/FeatureView';
import { NotCovered } from './components/NotCovered';
import { RunPicker } from './components/RunPicker';
import { StatusLine, type Pane } from './components/StatusLine';
import { ShortcutSheet } from './components/ShortcutSheet';
import { CommandPalette, type Command } from './components/CommandPalette';
import { Wordmark } from './components/Wordmark';
import { Confirm } from './components/Confirm';
import { Help } from './components/Help';
import { useRoute } from './route';
import { useTheme } from './theme';
import { useJobs, usePending } from './live';

export function App() {
  const [route, go] = useRoute();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<RunSummary | null>(null);
  const [body, setBody] = useState<RunBody | null>(null);
  const [judgement, setJudgement] = useState<Judgement | null>(null);
  const [stepId, setStepId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pane, setPane] = useState<Pane>('step');
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const [showKeys, setShowKeys] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [theme, cycleTheme] = useTheme();

  /** Re-read the run list. Called on mount, and again whenever a job settles:
   *  somebody who pressed Send should see the draft appear, not have to reload. */
  const refresh = useCallback(() => {
    api
      .runs()
      .then(({ runs: next }) => {
        setRuns(next);
        setSelected((current) => current ?? next[0] ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refresh, [refresh]);

  const jobs = useJobs(refresh);
  const [pending, dismissPending] = usePending();

  useEffect(() => {
    if (!selected) return;
    let live = true;
    api
      .run(selected.recordingId, selected.runId)
      .then((next) => {
        if (!live) return;
        setBody(next);
        setStepId(next.ir.testCases[0]?.steps[0]?.id ?? null);
        setPane('step');
        setOnlyFlagged(false);
      })
      .catch((e: Error) => live && setError(e.message));

    // Separately, and never fatally: a run with no judgement is normal (A0 has
    // none by construction, and so does every run made before the judge
    // existed). An empty panel is the right answer, not an error banner.
    setJudgement(null);
    api
      .judge(selected.recordingId, selected.runId)
      .then((next) => live && setJudgement(next))
      .catch(() => undefined);

    return () => {
      live = false;
    };
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

  /** Confirmed, because there is no way back: approval is the record of who
   *  signed this off, and nothing in the API withdraws one. */
  const approve = useCallback(() => {
    if (
      window.confirm(
        'Approve this run?\n\nThis records that you signed it off, and it cannot be undone here.',
      )
    ) {
      act((rec, run) => api.approve(rec, run));
    }
  }, [act]);

  const step: Step | undefined = useMemo(
    () => body?.ir.testCases.flatMap((c) => c.steps).find((s) => s.id === stepId),
    [body, stepId],
  );

  /**
   * The case the SELECTED step belongs to, never `testCases[0]`.
   *
   * `StepList` renders every case, so selecting a step in the second scenario
   * left this pointing at the first: the feature file shown was the wrong one,
   * and editing the prose wrote it to the wrong case. Not a rare path -- a bug
   * report is a sibling test case, so any recording with one has two.
   */
  const testCase: TestCase | undefined = useMemo(
    () => body?.ir.testCases.find((c) => c.steps.some((s) => s.id === stepId)),
    [body, stepId],
  );

  const orderedSteps = useMemo(() => body?.ir.testCases.flatMap((c) => c.steps) ?? [], [body]);
  const findings = judgement?.findings ?? [];
  const suggestionCount = useMemo(
    () => (body?.ir.testCases ?? []).reduce((n, c) => n + (c.suggestions ?? []).length, 0),
    [body],
  );

  const move = useCallback(
    (delta: number) => {
      if (!orderedSteps.length) return;
      const at = orderedSteps.findIndex((s) => s.id === stepId);
      const next = Math.min(Math.max((at < 0 ? 0 : at) + delta, 0), orderedSteps.length - 1);
      const target = orderedSteps[next];
      if (target) {
        setStepId(target.id);
        setPane('step');
      }
    },
    [orderedSteps, stepId],
  );

  const verdict = useCallback(
    (accepted: boolean) => {
      if (!step?.assertions.length) return;
      for (const assertion of step.assertions) {
        act((rec, run) => api.setAssertion(rec, run, step.id, assertion.id, accepted));
      }
    },
    [step, act],
  );

  /**
   * The keyboard loop.
   *
   * Two rules keep it out of the way: a key is ignored while focus is in a
   * field, so typing a step never fires a verdict, and nothing destructive is
   * bound, so a mis-key costs a keystroke.
   */
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        !!target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setShowPalette((on) => !on);
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        if (!body?.review.approved) approve();
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      switch (event.key) {
        case 'j': move(1); break;
        case 'k': move(-1); break;
        case 'a': verdict(true); break;
        case 'r': verdict(false); break;
        case 'f': setPane((p) => (p === 'feature' ? 'step' : 'feature')); break;
        case 'e':
          event.preventDefault();
          setPane('step');
          window.setTimeout(() => document.getElementById('step-text')?.focus(), 0);
          break;
        case '?': setShowKeys((on) => !on); break;
        case 'Escape': setShowKeys(false); setShowPalette(false); break;
        default: return;
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [move, verdict, body, approve]);

  const commands: Command[] = useMemo(() => {
    const out: Command[] = [
      { id: 'pane-steps', group: 'View', label: 'Show the steps', run: () => setPane('step') },
      { id: 'pane-feature', group: 'View', label: 'Show the feature file', hint: 'f', run: () => setPane('feature') },
      { id: 'theme', group: 'View', label: `Theme: ${theme} — switch`, run: cycleTheme },
      { id: 'help', group: 'Go', label: 'How to use this', run: () => go({ name: 'help' }) },
      { id: 'keys', group: 'Go', label: 'Keyboard shortcuts', hint: '?', run: () => setShowKeys(true) },
    ];
    if (suggestionCount > 0) {
      out.push({
        id: 'pane-notcovered',
        group: 'View',
        label: 'What this session did not cover',
        run: () => setPane('notcovered'),
      });
    }
    if (body && !body.review.approved) {
      out.push({ id: 'approve', group: 'Run', label: 'Approve this run', hint: '⌘↵', run: approve });
    }
    for (const run of runs) {
      out.push({
        id: `run-${run.recordingId}-${run.runId}`,
        group: 'Open run',
        label: run.titles[0] ?? run.recordingId,
        hint: `${run.runId}${run.judgeFails ? ` · ${run.judgeFails} to fix` : ''}`,
        run: () => setSelected(run),
      });
    }
    for (const s of orderedSteps) {
      out.push({
        id: `step-${s.id}`,
        group: 'Step',
        label: `${s.keyword} ${s.text}`,
        run: () => {
          setStepId(s.id);
          setPane('step');
        },
      });
    }
    return out;
  }, [runs, orderedSteps, body, approve, go, theme, cycleTheme, suggestionCount]);

  // Ahead of the "looking for a run" branch on purpose: somebody arrives here
  // from the export page seconds after pressing Send, when there is no run yet.
  // Showing them a loading string at the one moment they still remember what
  // they were checking is how the most valuable screen in the product goes
  // unused.
  if (route.name === 'confirm') {
    return (
      <Confirm
        recordingId={route.recordingId}
        onDone={() => {
          go({ name: 'review' });
          refresh();
        }}
      />
    );
  }

  if (route.name === 'help') {
    return <Help onBack={() => go({ name: 'review' })} />;
  }

  if (!body || !selected) {
    return (
      <FirstRun
        error={error}
        working={jobs.length > 0}
        onHelp={() => go({ name: 'help' })}
        theme={theme}
        onTheme={cycleTheme}
      />
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <Wordmark />
        <RunPicker runs={runs} selected={selected} onSelect={setSelected} />
        <div className="spacer" />
        <button className="icon" onClick={() => setShowPalette(true)} title="Commands (⌘K)">
          ⌘K
        </button>
        <button
          className="icon"
          onClick={cycleTheme}
          title={`Theme: ${theme}`}
          aria-label={`Theme: ${theme}. Switch.`}
        >
          {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'}
        </button>
        <button className="icon" onClick={() => go({ name: 'help' })} title="How to use this">
          ?
        </button>
        <ExportMenu
          recordingId={selected.recordingId}
          runId={selected.runId}
          testCases={body.ir.testCases}
          onError={setError}
        />
        {body.review.approved ? (
          <span className="chip chip-ok">approved</span>
        ) : (
          <button className="primary" disabled={busy} onClick={approve} title="Approve (⌘↵)">
            Approve
          </button>
        )}
      </header>

      <StatusLine
        trace={body.trace}
        judgement={judgement}
        jobs={jobs}
        pending={pending}
        onOpenConfirm={(recordingId) => go({ name: 'confirm', recordingId })}
        onDismissConfirm={dismissPending}
        pane={pane}
        onPane={setPane}
        onShowFlagged={() => {
          setOnlyFlagged(true);
          setPane('step');
        }}
      />

      {error && (
        <div className="errorbar" role="alert">
          {error}
          <button onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      <main>
        <StepList
          testCases={body.ir.testCases}
          selectedId={stepId}
          onSelect={(id) => {
            setStepId(id);
            setPane('step');
          }}
          edited={new Set(body.review.edits.map((e) => e.stepId).filter(Boolean) as string[])}
          findings={findings}
          onlyFlagged={onlyFlagged}
          onOnlyFlagged={setOnlyFlagged}
          suggestionCount={suggestionCount}
          onOpenSuggestions={() => setPane('notcovered')}
          onRename={(caseId, patch) => act((rec, run) => api.renameCase(rec, run, caseId, patch))}
          onMerge={(ids) => act((rec, run) => api.mergeSteps(rec, run, ids))}
          busy={busy}
        />

        {pane === 'feature' ? (
          <FeatureView
            testCase={testCase}
            /* `feature` is keyed by case id, because the renderer keys it that
               way -- and a bug report is deliberately absent from that map,
               having no `.feature` at all, so the empty fallback is the correct
               answer here rather than a missing one. */
            text={(testCase && body.feature[testCase.id]) ?? ''}
            busy={busy}
            onSave={(text) =>
              testCase && act((rec, run) => api.editFeature(rec, run, testCase.id, text))
            }
          />
        ) : pane === 'notcovered' ? (
          <NotCovered testCases={body.ir.testCases} onBack={() => setPane('step')} />
        ) : step ? (
          <StepDetail
            step={step}
            recordingId={selected.recordingId}
            runId={selected.runId}
            trace={body.trace}
            screens={body.screens ?? []}
            findings={findings}
            busy={busy}
            onEdit={(text) => act((rec, run) => api.editStep(rec, run, step.id, text))}
            onDelete={() => act((rec, run) => api.deleteStep(rec, run, step.id))}
            onAssertion={(id, accepted) =>
              act((rec, run) => api.setAssertion(rec, run, step.id, id, accepted))
            }
            onRewordAssertion={(id, text) =>
              act((rec, run) => api.rewordAssertion(rec, run, step.id, id, text))
            }
            onAnswer={(answer) => act((rec, run) => api.answerEscalation(rec, run, step.id, answer))}
          />
        ) : (
          <section className="detail">
            <p className="muted">Select a step.</p>
          </section>
        )}
      </main>

      {showKeys && <ShortcutSheet onClose={() => setShowKeys(false)} />}
      {showPalette && (
        <CommandPalette commands={commands} onClose={() => setShowPalette(false)} />
      )}
    </div>
  );
}

/**
 * What somebody sees before they have recorded anything.
 *
 * It said "Looking for a run…" -- a loading string, to a person who has just
 * installed the tool and has no idea what to do next. This is the first screen
 * of the product and it should be the shortest possible route to the second.
 */
function FirstRun({
  error,
  working,
  onHelp,
  theme,
  onTheme,
}: {
  error: string | null;
  working: boolean;
  onHelp: () => void;
  theme: string;
  onTheme: () => void;
}) {
  return (
    <div className="firstrun">
      <header className="topbar">
        <Wordmark />
        <div className="spacer" />
        <button className="icon" onClick={onTheme} title={`Theme: ${theme}`}>
          {theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐'}
        </button>
        <button onClick={onHelp}>How to use this</button>
      </header>

      <div className="firstrun-body">
        {error ? (
          <p className="error">{error}</p>
        ) : working ? (
          <>
            <h1>Writing your test case…</h1>
            <p className="muted">
              A couple of minutes. The tool is going back through the recording and checking each
              expected result against what was actually on the page.
            </p>
          </>
        ) : (
          <>
            <h1>No drafts yet</h1>
            <p className="muted">Three steps, and none of them is a terminal.</p>
            <ol className="firstrun-steps">
              <li>
                <b>Load the recorder.</b> Open <code>chrome://extensions</code>, turn on Developer
                mode, choose <b>Load unpacked</b> and pick the <code>extension/dist</code> folder.
              </li>
              <li>
                <b>Record yourself testing.</b> Click the AITC icon, say what you are checking, and
                press <b>Start recording</b>.
              </li>
              <li>
                <b>Press Stop, then Send.</b> The draft appears here on its own.
              </li>
            </ol>
            <button className="primary" onClick={onHelp}>
              Show me how
            </button>
          </>
        )}
      </div>
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
  const [open, setOpen] = useState(false);
  const [fresh, setFresh] = useState<string[]>([]);

  const run = async (formats: string[]) => {
    try {
      const { exports } = await api.exportRun(recordingId, runId, formats);
      setFresh(exports.flatMap((e) => e.files));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  // The feature file and its evidence sidecar always exist; the others are
  // produced on demand so a team that lives in Excel is not handed three files
  // it did not ask for.
  //
  // These used to sit in the header as one unlabelled `.feature` / `evidence`
  // pair PER TEST CASE, so a three-scenario run rendered
  // ".feature evidence .feature evidence .feature evidence" across the top of
  // the screen.
  return (
    <div className="menu">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        Export ▾
      </button>
      {open && (
        <>
          <div className="menu-scrim" onClick={() => setOpen(false)} />
          <div className="menu-list">
            <p className="menu-head">Download</p>
            {testCases.map((c) => (
              <div key={c.id} className="menu-group">
                <span className="menu-label">{c.scenarioName || c.title}</span>
                <a href={api.fileUrl(recordingId, runId, `${c.id}.feature`)} download>
                  Feature file
                </a>
                <a href={api.fileUrl(recordingId, runId, `${c.id}.trace.md`)} download>
                  Evidence sidecar
                </a>
              </div>
            ))}
            <p className="menu-head">Build</p>
            <button onClick={() => run(['xlsx'])}>Excel workbook</button>
            <button onClick={() => run(['jira'])}>Jira issue</button>
            {fresh.map((name) => (
              <a
                key={name}
                href={api.fileUrl(recordingId, runId, name)}
                download
                className="fresh"
              >
                {name}
              </a>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
