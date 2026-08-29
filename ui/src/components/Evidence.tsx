/**
 * Where a sentence came from, in three lines and then silence.
 *
 * The evidence used to own a third of the screen and show almost nothing: one
 * sentence and two collapsed disclosure triangles in a pane that was otherwise
 * empty. Meanwhile the thing a reviewer actually needs in order to press accept
 * -- what kind of claim this is, the exact value, and which retrieval returned
 * it -- was three clicks away or not rendered at all.
 *
 * So it lives on the card now: predicate, literal, event, tool. The stored
 * retrieval stays behind one control, because reading raw JSON is an audit and
 * not part of the review loop.
 */

import { useState } from 'react';
import { api, type Predicate, type Trace } from '../api';

/**
 * WHAT is claimed, not merely that a string appeared.
 *
 * This has been in the schema since the predicate work landed and the UI has
 * never shown it, so a reviewer could not tell *"the first product is X"* from
 * *"X is somewhere on the page"* -- which is the exact distinction the judge
 * keeps sending documents back over. `contains` is the historical default and
 * says nothing worth a badge; the other three change what the sentence means.
 */
export function PredicateLabel({ predicate }: { predicate?: Predicate }) {
  if (!predicate || predicate.form === 'contains') return null;

  const where = predicate.container?.name ? ` in ${predicate.container.name}` : '';
  const text =
    predicate.form === 'first_of'
      ? `first${where}`
      : predicate.form === 'absent'
        ? `must not appear${where}`
        : `${predicate.n ?? ''} of them${where}`.trim();

  return (
    <span className={`predicate predicate-${predicate.form}`} title="what this claim actually says">
      {text}
    </span>
  );
}

/** The retrieval itself, not a summary of it. One control, closed by default. */
export function Retrieval({
  recordingId,
  runId,
  toolCallId,
  trace,
}: {
  recordingId: string;
  runId: string;
  toolCallId: string;
  trace: Trace | null;
}) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  const call = trace?.toolCalls.find((c) => c.id === toolCallId);

  const show = async () => {
    const next = !open;
    setOpen(next);
    if (payload || !next) return;
    try {
      setPayload(await api.toolResponse(recordingId, runId, toolCallId));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="retrieval">
      <button className="link" onClick={show} aria-expanded={open}>
        {open ? '▾' : '▸'} what {call ? call.tool : 'the retrieval'} returned
      </button>
      {open &&
        (error ? (
          <p className="error">{error}</p>
        ) : (
          <pre>{payload ? JSON.stringify(payload, null, 2) : 'loading…'}</pre>
        ))}
    </div>
  );
}
