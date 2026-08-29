/**
 * "You have guesses nobody has checked."
 *
 * The oracle is the thing the whole rebuild rests on: without it the tool can
 * only restate what the application DID, which is why it could not write a test
 * that fails on the build it recorded. It is filled three ways, cheapest first
 * -- the model guesses, the tester confirms, and anything they said out loud is
 * carried in verbatim -- and the middle one had no route.
 *
 * The number, and it is the reason this component exists: **14 expectation sets
 * on disk, all 14 still `inferred`.** Not one had ever been answered by a human,
 * because the screen opened only on `?confirm=<id>`, linked from one place, read
 * once, and cleared on dismiss. Everything downstream has therefore only ever
 * read unconfirmed guesses.
 *
 * Deliberately not a modal and deliberately not blocking. A run must never wait
 * on a screen somebody might not open -- the draft already exists, built on the
 * guesses alone -- so this is an invitation on a page they are already on.
 */

import { useEffect, useState } from 'react';
import { api, type PendingConfirmation } from '../api';

export function ConfirmBanner({ onOpen }: { onOpen: (recordingId: string) => void }) {
  const [pending, setPending] = useState<PendingConfirmation[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    let live = true;
    api
      .pendingExpectations()
      .then(({ pending }) => live && setPending(pending))
      // Silent: an unanswered guess is not an error, and a red banner about a
      // failed poll on top of the review screen helps nobody.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const [first, ...rest] = pending.filter((row) => !dismissed.has(row.recordingId));
  if (!first) return null;
  const more = rest.length;

  return (
    <div className="banner confirm-banner" role="status">
      <span>
        <strong>{first.count} guesses</strong> about what should have happened in{' '}
        <code>{first.recordingId}</code> are still unchecked.
        {more > 0 && <> {more} other recording{more > 1 ? 's' : ''} too.</>}
      </span>
      <button className="primary" onClick={() => onOpen(first.recordingId)}>
        Check them
      </button>
      {/* Dismissing hides the row for this visit only. It is not an answer, and
          storing it as one would turn "I am busy" into "the guess was right" --
          which is the one direction the expectations file must never move. */}
      <button
        onClick={() => setDismissed((was) => new Set(was).add(first.recordingId))}
        title="Hide until the next reload"
      >
        not now
      </button>
    </div>
  );
}
