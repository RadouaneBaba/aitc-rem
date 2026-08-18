/** Monotonic, human-readable ids. Stability matters: every downstream stage
 *  references events by id, and the trace must stay readable by a person. */
export function counter(prefix: string, width = 3) {
  let n = 0;
  return () => `${prefix}_${String(++n).padStart(width, '0')}`;
}

export function recordingId(): string {
  // Sortable and unambiguous without pulling in a ULID dependency.
  const t = Date.now().toString(36).toUpperCase();
  const r = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `rec_${t}${r}`;
}
