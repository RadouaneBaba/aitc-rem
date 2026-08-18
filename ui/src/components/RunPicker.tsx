import type { RunSummary } from '../api';

export function RunPicker({
  runs,
  selected,
  onSelect,
}: {
  runs: RunSummary[];
  selected: RunSummary;
  onSelect: (run: RunSummary) => void;
}) {
  const key = (r: RunSummary) => `${r.recordingId}/${r.runId}`;
  return (
    <label className="runpicker">
      <span className="muted">Run</span>
      <select
        value={key(selected)}
        onChange={(e) => {
          const next = runs.find((r) => key(r) === e.target.value);
          if (next) onSelect(next);
        }}
      >
        {runs.map((run) => (
          <option key={key(run)} value={key(run)}>
            {run.titles[0] ?? run.recordingId} — {run.runId}
            {run.approved ? ' ✓' : ''}
          </option>
        ))}
      </select>
    </label>
  );
}
