import { putAudioChunk } from '../background/store';
import type { OffscreenInbound } from '../shared/messages';

/**
 * SS6.6 -- the microphone.
 *
 * This runs in an offscreen document, which is the only MV3 context that can do
 * the job. The alternatives were tried on paper and each fails on something
 * structural rather than fiddly:
 *
 *  - A **content script** gets the microphone permission of the page it is
 *    injected into, so the tester would be prompted once per origin by the
 *    application under test -- and the recorder is black-box (SS6.1); it must
 *    not need anything from the app. It also dies on every navigation, which is
 *    most of a QA session.
 *  - The **popup** closes the moment the tester clicks the page, which is the
 *    first thing they do.
 *  - The **service worker** has no `getUserMedia` at all, and is evicted after
 *    thirty seconds of inactivity.
 *
 * An offscreen document has the extension's own origin, survives navigation,
 * and has no UI to close. What it cannot do is *ask*: Chrome will not show a
 * permission prompt from here, which is why `mic.html` exists.
 *
 * **Nothing is transcribed here.** The audio goes to the local server and
 * `faster-whisper` runs there. Chrome's own on-device recogniser was the
 * obvious alternative and loses on the thing that matters: a transcript is a
 * reconstruction, and keeping the audio is the only way a human can ever check
 * one. Whatever the browser heard would otherwise be all anyone ever has.
 */

/** A chunk every five seconds, so a crashed session keeps everything up to the
 *  last five rather than nothing. */
const CHUNK_MS = 5_000;

/** The meter is the only live feedback there is -- transcription happens after
 *  the run -- so it has to be smooth enough to read as "it can hear me". */
const LEVEL_MS = 150;

let recorder: MediaRecorder | null = null;
let stream: MediaStream | null = null;
let meter: number | undefined;
let audio: AudioContext | null = null;
let seq = 0;

function tell(message: unknown): void {
  // The worker may be evicted between messages; that is normal and not a
  // failure worth surfacing to the tester.
  chrome.runtime.sendMessage(message).catch(() => undefined);
}

async function start(): Promise<void> {
  if (recorder) return;
  seq = 0;

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        // A QA session is one person at a desk. These are the defaults a
        // dictation app would pick, and they are what makes `small` enough.
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
  } catch (err) {
    const denied = err instanceof DOMException && err.name === 'NotAllowedError';
    tell({
      type: 'audio-failed',
      reason: denied ? 'denied' : 'error',
      message: String((err as Error)?.message ?? err),
    });
    return;
  }

  const mime = supportedMime();
  if (!mime) {
    stop();
    tell({ type: 'audio-failed', reason: 'unsupported', message: 'no Opus recording support' });
    return;
  }

  recorder = new MediaRecorder(stream, { mimeType: mime });
  recorder.ondataavailable = (event) => {
    // Zero-length chunks happen at the boundaries and are not silence; writing
    // them would put a gap in a stream whose chunks are not independent.
    if (event.data.size > 0) void putAudioChunk(seq++, event.data);
  };
  recorder.onerror = (event) => {
    tell({ type: 'audio-failed', reason: 'error', message: String((event as ErrorEvent).message) });
  };

  recorder.start(CHUNK_MS);

  // Wall-clock, deliberately: `performance.now()` in this document counts from
  // ITS time origin, not the session's, and mixing the two is the mistake that
  // once flattened every event timestamp to zero. The worker turns this into
  // `audioOffsetMs`.
  tell({ type: 'audio-started', at: Date.now() });
  watchLevel();
}

/**
 * Opus in WebM is what Chrome records and what `faster-whisper` reads through
 * ffmpeg. The list is a fallback chain rather than a single string because
 * `isTypeSupported` has genuinely differed across Chrome builds, and a recorder
 * that throws on construction takes the whole session with it.
 */
function supportedMime(): string | null {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

function watchLevel(): void {
  if (!stream) return;
  audio = new AudioContext();
  const analyser = audio.createAnalyser();
  analyser.fftSize = 512;
  audio.createMediaStreamSource(stream).connect(analyser);

  const samples = new Uint8Array(analyser.frequencyBinCount);
  meter = self.setInterval(() => {
    analyser.getByteTimeDomainData(samples);
    // RMS around the 128 centre. Peak would read as a flicker; this reads as a
    // voice.
    let sum = 0;
    for (const sample of samples) {
      const centred = (sample - 128) / 128;
      sum += centred * centred;
    }
    tell({ type: 'audio-level', level: Math.min(1, Math.sqrt(sum / samples.length) * 4) });
  }, LEVEL_MS);
}

function stop(): void {
  if (meter !== undefined) self.clearInterval(meter);
  meter = undefined;

  // requestData before stop: the tail since the last chunk boundary is the end
  // of the session, which is exactly where a tester says what they were
  // checking.
  if (recorder?.state === 'recording') {
    recorder.requestData();
    recorder.stop();
  }
  recorder = null;

  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  void audio?.close().catch(() => undefined);
  audio = null;
}

function mute(muted: boolean): void {
  // Disabling the track keeps the recording running and writes silence, which
  // keeps the timeline continuous. Stopping it would shift everything after the
  // mute and mis-attribute every later sentence.
  stream?.getAudioTracks().forEach((track) => {
    track.enabled = !muted;
  });
}

chrome.runtime.onMessage.addListener((message: OffscreenInbound, _sender, sendResponse) => {
  switch (message?.type) {
    case 'audio-start':
      void start();
      break;
    case 'audio-stop':
      stop();
      break;
    case 'audio-mute':
      mute(message.muted);
      break;
    default:
      return undefined;
  }
  sendResponse({ type: 'ack' });
  return undefined;
});
