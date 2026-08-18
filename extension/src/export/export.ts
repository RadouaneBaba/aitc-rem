import { validateRecording } from '../schemas/validators.js';
import { allEventRows, allObservations, allScreenshots, getSession } from '../background/store';
import type { ConsoleEntry, NetworkCall, Recording } from '../types/recording';

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

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, b64] = dataUrl.split(',');
  const mime = /:(.*?);/.exec(header ?? '')?.[1] ?? 'image/png';
  const bytes = atob(b64 ?? '');
  const buf = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

async function assemble(): Promise<{ recording: Recording; screenshots: { key: string; dataUrl: string }[] } | null> {
  const session = await getSession();
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
      ...(Object.keys(fidelitySummary).length ? { fidelitySummary } : {}),
    },
    events,
    narration: [],
    annotations: session.annotations,
    parameters: session.parameters,
  };

  return { recording, screenshots };
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

async function main(): Promise<void> {
  const assembled = await assemble();
  if (!assembled) {
    $('summary').innerHTML = '<p class="muted">No recording found. Record something first.</p>';
    $('save').setAttribute('disabled', 'true');
    return;
  }

  const { recording, screenshots } = assembled;
  renderSummary(recording, screenshots.length);

  // A deliberate test seam: the end-to-end suite drives the real extension in a
  // real browser and reads the assembled recording from here, rather than
  // reimplementing assembly or going through the downloads API.
  (window as unknown as { __aitcRecording?: Recording }).__aitcRecording = recording;

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

    try {
      const response = await fetch(`${base}/api/recordings`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(recording),
      });
      if (!response.ok) {
        throw new Error(`${response.status} ${await response.text()}`);
      }

      const { job, unknownOrigins } = await response.json();
      const review = `${base}/`;
      $('sent').innerHTML =
        `Sent. Job <code>${job.id}</code> is running the pipeline — a draft takes a ` +
        `couple of minutes. <a href="${review}" target="_blank">Open the review UI</a>.` +
        (unknownOrigins?.length
          ? `<br /><strong>Note:</strong> ${unknownOrigins.join(', ')} ` +
            `${unknownOrigins.length === 1 ? 'is' : 'are'} not on the allowlist, so this ` +
            `recording will not be sent to a training-eligible model tier.`
          : '');
    } catch (error) {
      // A tester who pressed Send and got silence cannot tell a stopped server
      // from a slow one.
      $('sent').innerHTML =
        `<span class="bad">Could not reach ${base}.</span> Start it with ` +
        `<code>python -m server.cli serve</code>, or save the file below instead. ` +
        `(${(error as Error).message})`;
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
    $('saved').textContent = `Saved to Downloads/${dir}/ (${screenshots.length + 1} files).`;
  });
}

void main();
