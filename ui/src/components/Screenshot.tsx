import { useState } from 'react';

/**
 * The page this step happened on (SS13.1).
 *
 * The recorder has been capturing these since Phase 1 and nothing rendered
 * one. It is the cheapest large improvement available here: judging "does this
 * step describe what the tester did" from a sentence and an event id is
 * genuinely hard, and trivial next to the picture.
 *
 * Never sent to a model (SS7.4). This is for the person reviewing, and only
 * for them -- which is also why a missing one is silent rather than an error:
 * an imported recording has none by construction, and a run that predates the
 * upload path has none either.
 *
 * Silent used to mean rendering the `<img>` anyway and hiding it `onError`,
 * which the browser still logs -- one 404 per step click, on every recording
 * without a `screens/` directory. `screens` is the manifest the run body
 * carries so the question is asked once, from disk, instead of over HTTP per
 * step.
 */
export function Screenshot({
  recordingId,
  eventIds,
  screens,
}: {
  recordingId: string;
  eventIds: string[];
  screens: string[];
}) {
  const [failed, setFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);

  // The FIRST event of the step. A step covers an intent, which is often many
  // events, and the picture that helps is the one where the tester acted --
  // the last frame is the page after everything settled, which is what the
  // expected result is about rather than the action.
  const eventId = eventIds[0];
  if (!eventId || failed || !screens.includes(eventId)) return null;

  const src = `/api/recordings/${recordingId}/screens/${eventId}`;

  return (
    <div className={`shot${zoomed ? ' zoomed' : ''}`}>
      <img
        src={src}
        alt={`The page at ${eventId}`}
        loading="lazy"
        onError={() => setFailed(true)}
        onClick={() => setZoomed((v) => !v)}
      />
      <span className="muted shot-hint">
        {zoomed ? 'click to shrink' : 'click to enlarge'} · {eventId}
      </span>
    </div>
  );
}
