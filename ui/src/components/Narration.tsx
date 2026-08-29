/**
 * What the tester said, and the clip that proves it.
 *
 * Narration is the only LOSSY evidence source in this tool. A snapshot node
 * name, a URL, a response body are read exactly; a transcript is a
 * reconstruction. So a mis-heard number becomes a literal that passes
 * `evidence_retrieved` (the string really is in the stored response) AND
 * `assertion_grounding` (it really is in the index) and is still false. No
 * automatic check catches that, and the replay runner says so outright by
 * marking narration `not_checkable`.
 *
 * A person listening is the check. That is the entire reason the audio is kept
 * rather than discarded after transcription, and this is where it pays for
 * itself -- which is why it now sits beside the step instead of behind a tab
 * nobody opened.
 */

import { useEffect, useState } from 'react';
import { api, type Step, type StepNarration } from '../api';

export function Narration({
  step,
  recordingId,
  runId,
}: {
  step: Step;
  recordingId: string;
  runId: string;
}) {
  const [narration, setNarration] = useState<StepNarration | null>(null);

  useEffect(() => {
    let live = true;
    setNarration(null);
    api
      .stepNarration(recordingId, runId, step.id)
      .then((body) => live && setNarration(body))
      // A recording made before narration existed has no answer worth showing.
      // Silence is right: this is evidence, not a status bar.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [recordingId, runId, step.id]);

  if (!narration?.segments.length) return null;

  return (
    <section className="block">
      <h3 className="eyebrow">What you said here</h3>
      <ul className="spoken">
        {narration.segments.map((segment) => (
          <li key={segment.id} className={segment.supportsRank ? undefined : 'unsure'}>
            <span className="at">{(segment.startMs / 1000).toFixed(1)}s</span>
            <q>{segment.text}</q>
            {!segment.supportsRank && (
              <em title="A transcription nobody trusts must not outrank an honest inference.">
                too unclear to rank an expected result
              </em>
            )}
          </li>
        ))}
      </ul>
      {narration.hasAudio && (
        <audio
          controls
          preload="none"
          src={api.audioUrl(recordingId)}
          // Seeked to the first thing said in this step: scrubbing a
          // fifteen-minute session to find one sentence is not a check anybody
          // performs twice.
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = narration.segments[0]!.startMs / 1000;
          }}
        />
      )}
      <p className="muted small">
        Transcribed, not read. If a number here is wrong, the expected result built on it is
        wrong too — reject it, or reword it.
      </p>
    </section>
  );
}
