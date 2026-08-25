import { useMemo, useState } from 'react';
import type { RunSummary } from '../api';

/**
 * Which run to open, and which one needs you first.
 *
 * This was a `<select>` of run ids. It answered "which runs exist" and nothing
 * else, which is fine for one recording and useless for fifteen: a tester
 * opening the tool wants to know where to start, and a dropdown makes them
 * open every run to find out.
 *
 * Everything shown here was already in `ir.json`. Nothing new is computed, and
 * nothing here is a metric about the tool -- it is all about the tester's own
 * work: what this run covers, how much of it is flagged, and whether they have
 * already been through it.
 */
export function RunPicker({
  runs,
  selected,
  onSelect,
}: {
  runs: RunSummary[];
  selected: RunSummary;
  onSelect: (run: RunSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  const key = (r: RunSummary) => `${r.recordingId}/${r.runId}`;
  const label = (r: RunSummary) => r.titles[0] ?? r.recordingId;

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return runs;
    return runs.filter((r) =>
      [label(r), ...(r.scenarios ?? []), r.recordingId, r.runId]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    );
  }, [runs, query]);

  const needsAttention = runs.filter((r) => !r.approved && attention(r) > 0).length;

  return (
    <div className="runpicker">
      <button className="runpicker-current" onClick={() => setOpen((v) => !v)}>
        <span className="runpicker-title">{label(selected)}</span>
        <span className="muted">{selected.runId}</span>
        {needsAttention > 0 && !open && (
          <span className="badge warn">{needsAttention} need a look</span>
        )}
        <span className="muted">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="runpicker-list" role="listbox">
          <input
            className="runpicker-search"
            placeholder={`Search ${runs.length} run${runs.length === 1 ? '' : 's'}…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          {matches.length === 0 && <p className="muted runpicker-empty">Nothing matches.</p>}
          {matches.map((run) => (
            <button
              key={key(run)}
              role="option"
              aria-selected={key(run) === key(selected)}
              className={`runpicker-row${key(run) === key(selected) ? ' current' : ''}`}
              onClick={() => {
                onSelect(run);
                setOpen(false);
                setQuery('');
              }}
            >
              <div className="runpicker-row-main">
                <span className="runpicker-title">{label(run)}</span>
                {run.approved && <span className="badge approved">approved</span>}
                {run.hasBug && <span className="badge warn">bug report</span>}
              </div>
              <div className="runpicker-row-sub muted">
                {(run.scenarios ?? []).slice(0, 2).join(' · ') || run.recordingId}
              </div>
              <div className="runpicker-row-stats muted">
                <span>{run.steps} steps</span>
                <span>
                  {run.assertions ?? 0} expected result
                  {(run.assertions ?? 0) === 1 ? '' : 's'}
                </span>
                {attention(run) > 0 && (
                  <span className="runpicker-attention">{summarise(run)}</span>
                )}
                {(run.editedSteps ?? 0) > 0 && <span>{run.editedSteps} edited</span>}
                <span>{new Date(run.createdAt).toLocaleDateString()}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** How much of this run is asking for a human. */
function attention(run: RunSummary): number {
  return (run.warnings ?? 0) + (run.flaggedSteps ?? 0);
}

function summarise(run: RunSummary): string {
  const parts: string[] = [];
  if (run.flaggedSteps) parts.push(`${run.flaggedSteps} step${run.flaggedSteps === 1 ? '' : 's'} flagged`);
  if (run.warnings) parts.push(`${run.warnings} warning${run.warnings === 1 ? '' : 's'}`);
  return parts.join(', ');
}
