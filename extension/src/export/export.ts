import { validateRecording } from '../schemas/validators.js';
import { allEventRows, allObservations, allScreenshots, audioBlob, getSession } from '../background/store';
import type { ConsoleEntry, NetworkCall, Recording } from '../types/recording';
import { budgetNetwork } from './budget';

/**
 * Assembly and export.
 *
 * This runs on an extension PAGE rather than in the service worker for a
 * mundane reason: MV3 workers have no URL.createObjectURL, and a multi-megabyte
 * recording as a base64 data URL is a poor way to move a file. It also gives
 * the redaction preview of SS7.3 somewhere to live.
 */

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function download(filename: string, blob: Blob): Promise<number> {
  const url = URL.createObjectURL(blob);
  return chrome.downloads.download({ url, filename, saveAs: false }).finally(() => {
    // Revoking immediately can cancel an in-flight download.
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  });
}

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, b64] = dataUrl.split(',');
  const mime = /:(.*?);/.exec(header ?? '')?.[1] ?? 'image/png';
  const bytes = atob(b64 ?? '');
  const buf = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

/**
 * Wait until the recorder has actually finished stopping.
 *
 * Three things have to line up for the last action of a session to survive, and
 * this is the third. `capture()` awaits settle before it sends, so the final
 * click is routinely still in flight when Stop is pressed; the content script
 * now drains those before it acknowledges the stop, and the worker marks the
 * session `stopped` only after that acknowledgement. Which means a session
 * without `stopped` is one whose last event has not landed yet.
 *
 * Assembling anyway is what actually cost the event: measured on a public demo
 * site, five actions driven and four assembled, and nothing anywhere reported a
 * problem -- the recording simply did not contain the add-to-cart it was about.
 *
 * Bounded, and it gives up rather than blocking: an export page that will not
 * load is worse than a recording that is honestly one event short. `stopped` is
 * absent for a session still recording, which is a legitimate thing to open
 * this page on.
 */
const STOP_WAIT_MS = 8000;
const STOP_POLL_MS = 100;

async function settledSession(): Promise<Awaited<ReturnType<typeof getSession>>> {
  const deadline = Date.now() + STOP_WAIT_MS;
  let session = await getSession();
  while (session && !session.stopped && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, STOP_POLL_MS));
    session = await getSession();
  }
  return session;
}

async function assemble(): Promise<{ recording: Recording; screenshots: { key: string; dataUrl: string }[] } | null> {
  const session = await settledSession();
  if (!session) return null;

  const rows = await allEventRows();
  const events = rows.map((r) => r.event);
  const screenshots = await allScreenshots();
  const durationMs = events.length ? Math.max(...events.map((e) => e.timestamp)) : 0;

  // Renumber densely: frames number their own events independently, and the
  // downstream stages assume seq is a contiguous session ordering.
  events.forEach((e, i) => {
    e.seq = i;
    e.id = `evt_${String(i + 1).padStart(3, '0')}`;
  });

  attributeObservations(rows, await allObservations());
  attributeAnnotations(events, session.annotations);

  const fidelitySummary: Record<string, number> = {};
  for (const e of events) {
    for (const flag of e.fidelity) fidelitySummary[flag] = (fidelitySummary[flag] ?? 0) + 1;
  }

  const recording: Recording = {
    schemaVersion: '1.0',
    id: session.recordingId,
    // Local-only for now; carried from day one so multi-user needs no
    // migration (SS16).
    projectId: 'local',
    ownerId: 'local',
    createdAt: session.startedAtIso,
    ...(session.objective ? { objective: session.objective } : {}),
    metadata: {
      capturedAt: session.startedAtIso,
      durationMs,
      browser: navigator.userAgent.match(/Chrome\/[\d.]+/)?.[0] ?? 'Chrome',
      userAgent: navigator.userAgent,
      viewport: { w: window.screen.width, h: window.screen.height },
      startUrl: session.startUrl,
      origins: session.origins,
      recorderVersion: chrome.runtime.getManifest().version,
      // What redaction was ACTUALLY in force while this was recorded, so the
      // server never has to infer it from whatever the project is configured to
      // do now. Omitted when it was the default, which keeps every recording
      // made before the setting existed meaning exactly what it always did.
      ...(session.redaction && session.redaction !== 'full'
        ? { redaction: session.redaction }
        : {}),
      // SS6.6. Only present when audio was actually captured -- the mic takes a
      // moment to open, and every transcript timestamp is relative to the audio
      // rather than to the session, so this delta is what puts a spoken
      // sentence on the step it belongs to.
      ...(session.audioOffsetMs !== undefined ? { audioOffsetMs: session.audioOffsetMs } : {}),
      ...(Object.keys(fidelitySummary).length ? { fidelitySummary } : {}),
    },
    events,
    // Narration is transcribed by the local server from the audio posted
    // alongside this, not here: it needs a real ASR model and it is the one
    // step in the chain that is a reconstruction rather than a reading.
    narration: [],
    annotations: session.annotations,
    // Filled in below, once there is a document to check them against.
    parameters: [],
  };
  recording.parameters = liveParameters(session.parameters, recording);

  return { recording, screenshots };
}

/**
 * Keep only the placeholders that actually appear in the recording.
 *
 * SS7.2 makes every redacted value a test PARAMETER: it is rendered in the
 * feature file, it is what `--replay-param` supplies, and it is printed in the
 * redaction preview the tester approves before sending. So a parameter that
 * points at nothing is not harmless noise -- it is a row in the artifact asking
 * somebody to supply a value that is used nowhere.
 *
 * `Redactor` accumulates a placeholder for every value it ever RECOGNISED,
 * across every snapshot pass of every event, whether or not the text survived
 * into the persisted tree. One storefront listing came out with 214 of them and
 * **not one of those placeholders appears anywhere in the recording** -- the
 * only 214 occurrences of `<<` in the file were the parameters array describing
 * itself.
 *
 * Checked against the serialised document rather than by walking it, because
 * a placeholder can legitimately live in a node name, a field value, a URL, a
 * request body, a console line or an annotation, and a walker that forgot one
 * of those would silently drop a real parameter.
 */
function liveParameters(
  parameters: Recording['parameters'],
  recording: Recording,
): Recording['parameters'] {
  const document = JSON.stringify({ events: recording.events, annotations: recording.annotations });
  return parameters.filter((p) => document.includes(p.placeholder));
}

/** Requests may begin slightly before the click that caused them is recorded. */
const LEAD_MS = 120;

/**
 * Attach each network call and console entry to the action that caused it.
 *
 * This cannot be done in the frame that observed it, for two reasons that
 * showed up immediately in real recordings:
 *
 *  - A frame does not know when the NEXT action starts, so a call was attached
 *    to every event still settling when it began -- an order POST landed on
 *    three steps that mutated nothing, which would let `mutation_claimed` pass
 *    for all of them (SS9.7).
 *  - A frame emits its event when settle ends, so a request that outlives its
 *    own settle window was simply never recorded. The slow-endpoint step had
 *    no network evidence at all -- the one thing that step is about.
 *
 * Attribution is per frame: an iframe's requests belong to the iframe's events.
 */
function attributeObservations(
  rows: { event: Recording['events'][number]; frameId: number }[],
  observations: { frameId: number; kind: 'network' | 'console'; at: number; payload: unknown }[],
): void {
  for (const row of rows) {
    row.event.network = [];
    row.event.console = [];
  }

  for (const obs of observations) {
    const candidates = rows.filter((r) => r.frameId === obs.frameId);
    // The owning action is the last one that began at or before this
    // observation (allowing a small lead for the request that the click
    // itself started).
    let owner: (typeof candidates)[number] | undefined;
    for (const row of candidates) {
      if (row.event.timestamp - LEAD_MS <= obs.at) owner = row;
      else break;
    }
    if (!owner) owner = candidates[0];
    if (!owner) continue;

    if (obs.kind === 'network') owner.event.network.push(obs.payload as NetworkCall);
    else owner.event.console.push(obs.payload as ConsoleEntry);
  }

  // The event's own URL, not `location`: this file runs on an extension page,
  // so `location.origin` here is `chrome-extension://…` and every request in
  // the recording would be third-party by that measure.
  for (const row of rows) {
    row.event.network = budgetNetwork(row.event.network, row.event.url);
  }
}

/**
 * Bind each annotation to the action it was about.
 *
 * Same reason network calls are attributed here rather than in the frame: a
 * frame does not know when the next action starts. But the direction is the
 * opposite one. A tester marks what they are verifying AFTER doing the thing
 * that produced it -- they click Place order, the banner appears, then they
 * point at the banner -- so an annotation belongs to the most recent action at
 * or before its timestamp, and a small lead is not enough. `assertions.py`
 * reads `CapturedEvent.annotations`, which nothing populated until now.
 *
 * Session-level annotations stay on the recording too: `checkpoint` and
 * `scenario_break` are boundaries between steps rather than facts about one,
 * and `segment.py` reads them from there.
 */
function attributeAnnotations(
  events: Recording['events'],
  annotations: Recording['annotations'],
): void {
  for (const event of events) delete event.annotations;

  for (const annotation of annotations) {
    // Boundaries are not about any single action.
    if (annotation.kind === 'checkpoint' || annotation.kind === 'scenario_break') continue;

    let owner: Recording['events'][number] | undefined;
    for (const event of events) {
      if (event.timestamp <= annotation.timestamp) owner = event;
      else break;
    }
    if (!owner) owner = events[0];
    if (!owner) continue;

    owner.annotations = [...(owner.annotations ?? []), { ...annotation, eventId: owner.id }];
  }
}

function renderSummary(recording: Recording, shots: number): void {
  const flags = recording.metadata.fidelitySummary ?? {};
  const flagRows = Object.entries(flags)
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join('');

  $('summary').innerHTML = `
    <table>
      <tr><td>Recording</td><td><code>${recording.id}</code></td></tr>
      <tr><td>Events</td><td>${recording.events.length}</td></tr>
      <tr><td>Screenshots</td><td>${shots}</td></tr>
      <tr><td>Annotations</td><td>${recording.annotations.length}</td></tr>
      <tr><td>Duration</td><td>${(recording.metadata.durationMs / 1000).toFixed(1)}s</td></tr>
      <tr><td>Origins</td><td>${recording.metadata.origins.join(', ') || '-'}</td></tr>
      <tr><td>Objective</td><td>${recording.objective ?? '<em>none stated</em>'}</td></tr>
    </table>
    ${flagRows ? `<h3>Fidelity flags</h3><table>${flagRows}</table>` : ''}
  `;

  // SS7.3 -- exactly what will be sent, with redactions applied, before any of
  // it reaches a model.
  const params = recording.parameters;
  $('redaction').innerHTML = params.length
    ? `<table>${params
        .map((p) => `<tr><td><code>${p.placeholder}</code></td><td>${p.category}</td><td>${p.occurrences}&times;</td></tr>`)
        .join('')}</table>`
    : '<p class="muted">No values were redacted in this recording.</p>';
}

/**
 * SS7.3 applied to speech: what the tester is about to hand over, before they
 * hand it over.
 *
 * There is no transcript to show yet -- transcription happens on the server,
 * because it needs a real ASR model. So what this can honestly say is how much
 * audio there is and that everything on it will be written down. That sentence
 * is the point: pattern redaction works on typed values because the recorder
 * knows a field was `type=password`; it cannot know that "my password is
 * hunter two" was a password, and claiming otherwise would be worse than saying
 * nothing.
 */
function renderNarration(audio: Blob | null, offsetMs: number | undefined): void {
  if (!audio) {
    $('narration').innerHTML =
      '<p class="muted">No audio was recorded. Turn on <em>Talk while I record</em> ' +
      'in the popup before you start, if you want to narrate.</p>';
    return;
  }

  const kb = Math.round(audio.size / 1024);
  $('narration').innerHTML = `
    <table>
      <tr><td>Audio</td><td>${kb} KB, <code>${audio.type || 'audio/webm'}</code></td></tr>
      <tr><td>Starts at</td><td>${((offsetMs ?? 0) / 1000).toFixed(1)}s into the recording</td></tr>
    </table>
    <p class="muted">
      Transcribed on the machine running aitc-rem and kept beside the recording, so you can
      play back what you actually said. It is not uploaded anywhere.
    </p>
    <div class="note">
      <strong>Everything you said is written down.</strong> Typed values are redacted because
      the recorder can see that a field was a password. It cannot hear that a sentence was one.
      If you said something you would rather not keep, save the file below instead of sending,
      or record again.
    </div>
    <p><audio controls src="${URL.createObjectURL(audio)}"></audio></p>
  `;
}

/**
 * What the server did with the audio, said out loud on the page the tester is
 * still looking at.
 *
 * A run that quietly dropped the narration is indistinguishable from a tester
 * who did not speak, and the output would simply be worse for a reason nothing
 * on screen explains. `unsure` is surfaced for the same reason: "the tool
 * ignored what I said" deserves an answer, and the answer is that a
 * transcription nobody trusts does not get to outrank an honest inference.
 */
function narrationNote(narration: { status?: string; segments?: number; unsure?: number; reason?: string } | undefined): string {
  if (!narration) return '';
  switch (narration.status) {
    case 'transcribed': {
      const unsure = narration.unsure
        ? ` ${narration.unsure} of them came through unclearly and will not be used to rank an ` +
          `expected result, though you can still read them in the review UI.`
        : '';
      return `<br />Heard ${narration.segments} thing(s) you said.${unsure}`;
    }
    case 'unavailable':
      return (
        `<br /><strong>The audio was not transcribed.</strong> It is saved with the recording, ` +
        `so nothing is lost and it can be transcribed later. ` +
        `<span class="muted">(${narration.reason ?? ''})</span>`
      );
    default:
      return '';
  }
}

async function main(): Promise<void> {
  const assembled = await assemble();
  if (!assembled) {
    $('summary').innerHTML = '<p class="muted">No recording found. Record something first.</p>';
    $('save').setAttribute('disabled', 'true');
    return;
  }

  const { recording, screenshots } = assembled;
  const audio = await audioBlob();
  renderSummary(recording, screenshots.length);
  renderNarration(audio, recording.metadata.audioOffsetMs);

  // A deliberate test seam: the end-to-end suite drives the real extension in a
  // real browser and reads the assembled recording from here, rather than
  // reimplementing assembly or going through the downloads API.
  const globals = window as unknown as {
    __aitcRecording?: Recording;
    __aitcAudio?: { mime: string; base64: string } | null;
  };
  globals.__aitcRecording = recording;
  // Base64 because `page.evaluate` returns JSON: a Blob does not survive the
  // boundary. Only the suite reads this, and only to write the fixture that
  // makes narration testable without a microphone.
  globals.__aitcAudio = audio
    ? { mime: audio.type || 'audio/webm', base64: await toBase64(audio) }
    : null;

  // The recorder validates what it is about to persist. A malformed recording
  // should fail here, at the recorder, not three pipeline stages downstream.
  const valid = validateRecording(recording);
  const errors = validateRecording.errors ?? [];
  $('validity').innerHTML = valid
    ? '<p class="ok">Valid against recording.schema.json.</p>'
    : `<p class="bad">Does NOT validate against recording.schema.json:</p><pre>${errors
        .slice(0, 12)
        .map((e) => `${e.instancePath || '/'} ${e.message ?? ''}`)
        .join('\n')}</pre>`;

  // SS13 -- the tester never touches a terminal. This button is the whole of
  // that promise: the pipeline runs on a local server and the browser opens on
  // a draft. It lives here rather than in the popup on purpose, because SS7.3
  // says the tester sees exactly what will be sent BEFORE it goes, and the
  // redaction preview above is that screen.
  $('send').addEventListener('click', async () => {
    const button = $('send') as HTMLButtonElement;
    const base = ($('server') as HTMLInputElement).value.trim().replace(/\/$/, '');
    button.disabled = true;
    $('sent').textContent = 'Sending…';
    let shotNote = '';

    try {
      // Audio first, and the order is load-bearing: POST /api/recordings
      // enqueues the pipeline job immediately, so audio arriving afterwards
      // would be transcribed for a run that had already started without it --
      // and the recording.json on disk would then disagree with the trace that
      // cites it.
      if (audio) {
        $('sent').textContent = `Sending ${Math.round(audio.size / 1024)} KB of audio…`;
        const posted = await fetch(`${base}/api/recordings/${recording.id}/audio`, {
          method: 'POST',
          headers: { 'content-type': audio.type || 'audio/webm' },
          body: audio,
        });
        if (!posted.ok) throw new Error(`audio: ${posted.status} ${await posted.text()}`);
      }

      $('sent').textContent = 'Sending…';
      const response = await fetch(`${base}/api/recordings`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(recording),
      });
      if (!response.ok) {
        throw new Error(`${response.status} ${await response.text()}`);
      }

      const { job, unknownOrigins, narration } = await response.json();

      // Screenshots last, and deliberately so. The pipeline never reads one
      // (SS7.4 -- they are not sent to a model), so they must not hold up the
      // job; they exist for the human who is about to review the draft, and
      // the draft takes minutes. A failure here is reported and swallowed for
      // the same reason: losing a picture must not cost the recording.
      if (screenshots.length) {
        $('sent').textContent = `Sending ${screenshots.length} screenshot(s)…`;
        let sentShots = 0;
        for (const shot of screenshots) {
          try {
            const posted = await fetch(
              `${base}/api/recordings/${recording.id}/screens/${shot.key}`,
              { method: 'POST', headers: { 'content-type': 'image/png' }, body: dataUrlToBlob(shot.dataUrl) },
            );
            if (posted.ok) sentShots += 1;
          } catch {
            /* the review UI simply shows no picture for that step */
          }
        }
        shotNote = sentShots
          ? `<br />${sentShots} screenshot${sentShots === 1 ? '' : 's'} sent for review.`
          : '';
      }

      // Straight to the confirmation screen, not to the review UI.
      //
      // The pipeline can only ever restate what the application DID; the one
      // thing it cannot know is what it SHOULD have done, and the only person
      // who knows that is about to close this tab. Two minutes from now they
      // are on the next test and the answer is gone. So the link that gets the
      // prominence is the one that asks while they still remember -- the draft
      // is being written either way and will be waiting behind it.
      const confirm = `${base}/?confirm=${encodeURIComponent(recording.id)}`;
      $('sent').innerHTML =
        `Sent. <a href="${confirm}" target="_blank"><strong>Tell us what should have ` +
        `happened</strong></a> — it takes about a minute of clicking and it is the one ` +
        `thing the recording cannot show us. ` +
        `Job <code>${job.id}</code> is writing a draft meanwhile.` +
        narrationNote(narration) +
        shotNote +
        (unknownOrigins?.length
          ? `<br /><strong>Note:</strong> ${unknownOrigins.join(', ')} ` +
            `${unknownOrigins.length === 1 ? 'is' : 'are'} not on the allowlist, so this ` +
            `recording will not be sent to a training-eligible model tier.`
          : '');
    } catch (error) {
      // A tester who pressed Send and got silence cannot tell a stopped server
      // from a slow one. SS13 says they never touch a terminal, so the message
      // must not hand them a command to run -- it tells them what is true and
      // what they can do from here, and the command lives in the developer
      // runbook where somebody who can act on it will find it.
      $('sent').innerHTML =
        `<span class="bad">Nothing is listening at ${base}.</span> The review ` +
        `server is not running &mdash; whoever set this up needs to start it. ` +
        `Your recording is safe: save it below and send it once the server is ` +
        `up. <span class="muted">(${(error as Error).message})</span>`;
    } finally {
      button.disabled = false;
    }
  });

  $('save').addEventListener('click', async () => {
    const dir = `aitc-rem/${recording.id}`;
    await download(
      `${dir}/recording.json`,
      new Blob([JSON.stringify(recording, null, 2)], { type: 'application/json' }),
    );
    for (const shot of screenshots) {
      await download(`${dir}/screens/${shot.key}.png`, dataUrlToBlob(shot.dataUrl));
    }
    // Named so `server/cli.py` finds it beside the recording without a flag.
    if (audio) await download(`${dir}/audio.webm`, audio);

    const files = screenshots.length + 1 + (audio ? 1 : 0);
    $('saved').innerHTML =
      `Saved to Downloads/${dir}/ (${files} files).` +
      (audio
        ? ` Transcribe the audio with <code>python -m server.cli transcribe ` +
          `recording.json --in-place</code>, or just send it above and the server does it.`
        : '');
  });
}

void main();
