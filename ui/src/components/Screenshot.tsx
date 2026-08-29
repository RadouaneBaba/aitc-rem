import { useEffect, useState } from 'react';

/**
 * The page this step happened on.
 *
 * The recorder has captured these since Phase 1. They were rendered at
 * `max-height: 220px` -- a full commercial page shrunk to a thumbnail you
 * cannot read -- next to a paragraph of body text that took more room. Judging
 * "does this sentence describe what the tester did" from a sentence and an
 * event id is genuinely hard and trivial next to the picture, so the picture
 * gets the width of the pane and a real lightbox.
 *
 * Never sent to a model. This is for the person reviewing, and only for them --
 * which is also why a missing one is silent rather than an error: an imported
 * recording has none by construction, and so does any run whose recording has
 * been cleared. `screens` is the manifest the run body carries, so the question
 * is asked once from disk instead of producing a 404 per step click.
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

  useEffect(() => setFailed(false), [eventIds.join(',')]);

  // The FIRST event of the step. A step covers an intent, which is often many
  // events, and the frame that helps is the one where the tester acted -- the
  // last frame is the page after everything settled, which is what the expected
  // result is about rather than the action.
  const eventId = eventIds[0];
  if (!eventId || failed || !screens.includes(eventId)) return null;

  const src = `/api/recordings/${recordingId}/screens/${eventId}`;

  return (
    <>
      <figure className="shot">
        <button
          className="shot-open"
          onClick={() => setZoomed(true)}
          aria-label={`Enlarge the page at ${eventId}`}
        >
          <img src={src} alt={`The page at ${eventId}`} loading="lazy" onError={() => setFailed(true)} />
        </button>
        <figcaption>
          The page when this happened <span className="muted">· {eventId} · click to enlarge</span>
        </figcaption>
      </figure>

      {zoomed && <Lightbox src={src} eventId={eventId} onClose={() => setZoomed(false)} />}
    </>
  );
}

/** Full-size, on a dimmed ground, dismissed by Escape or by clicking away.
 *  The old control toggled `max-height: none` in place, which pushed the whole
 *  pane down and scrolled the thing you were trying to look at off screen. */
function Lightbox({
  src,
  eventId,
  onClose,
}: {
  src: string;
  eventId: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={`The page at ${eventId}`}>
      <button className="lightbox-close" onClick={onClose} aria-label="Close">
        ×
      </button>
      <img src={src} alt={`The page at ${eventId}`} onClick={onClose} />
    </div>
  );
}
