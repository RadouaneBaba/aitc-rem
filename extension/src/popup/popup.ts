import type { AnnotationKind } from '../types/recording';
import type { NarrationStatus, RecorderState, WorkerInbound } from '../shared/messages';

function send<T>(message: WorkerInbound | { type: string }): Promise<T> {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/**
 * SS6.6 -- what to say when the microphone is not doing what was asked.
 *
 * `denied` and `unsupported` are different sentences because they are different
 * situations: one is a person who said no, the other is a browser that cannot.
 * Telling a tester to check their microphone when they deliberately declined is
 * how a tool loses their trust.
 */
const MIC_TROUBLE: Partial<Record<NarrationStatus, string>> = {
  denied:
    'Chrome would not give up the microphone. Nothing is being recorded. ' +
    'Open the padlock in the address bar of the permission tab to reset it.',
  unsupported: 'This browser will not record audio here, so narration is off for this session.',
};

/** Rendered live, and it has to be: transcription happens on the server after
 *  the run, so the meter is the ONLY answer to "can it hear me". */
let poll: number | undefined;

function render(state: RecorderState): void {
  $('idle').hidden = state.recording;
  $('active').hidden = !state.recording;
  $('count').textContent = String(state.eventCount);
  $('annotations').textContent = String(state.annotationCount);
  $('origins').textContent = state.origins.length ? String(state.origins.length) : '-';
  ($('narrate') as HTMLInputElement).checked = state.narrationEnabled;

  const trouble = MIC_TROUBLE[state.narrationStatus];
  const live = state.narrationStatus === 'listening' || state.narrationStatus === 'muted';

  $('mic').hidden = !live;
  $('micwarn').hidden = !trouble;
  $('micwarn').textContent = trouble ?? '';

  if (live) {
    const muted = state.narrationStatus === 'muted';
    $('micdot').className = muted ? 'dot quiet' : 'dot';
    $('micmeter').style.width = `${Math.round((state.narrationLevel ?? 0) * 100)}%`;
    $('mute').textContent = muted ? 'Unmute' : 'Mute';
  }

  // Only while there is a meter to move. A popup that polls the worker awake
  // every 300ms for nothing is a worker that never gets evicted.
  if (live && poll === undefined) {
    poll = window.setInterval(async () => render(await send<RecorderState>({ type: 'query-state' })), 300);
  } else if (!live && poll !== undefined) {
    window.clearInterval(poll);
    poll = undefined;
  }
}

$('start').addEventListener('click', async () => {
  const objective = ($('objective') as HTMLTextAreaElement).value.trim();
  render(await send<RecorderState>({ type: 'start', objective: objective || undefined }));
});

$('stop').addEventListener('click', async () => {
  render(await send<RecorderState>({ type: 'stop' }));
});

$('export').addEventListener('click', async () => {
  await send({ type: 'stop' });
  await chrome.tabs.create({ url: chrome.runtime.getURL('export.html') });
  window.close();
});

$('narrate').addEventListener('change', async (event) => {
  const enabled = (event.target as HTMLInputElement).checked;
  render(await send<RecorderState>({ type: 'set-narration', enabled }));
  // Turning it on opens the permission tab, which takes focus. The popup is
  // about to close anyway; closing it deliberately avoids the half-second where
  // it is still on screen behind the prompt.
  if (enabled) window.close();
});

$('mute').addEventListener('click', async () => {
  render(await send<RecorderState>({ type: 'toggle-mute' }));
});

for (const button of document.querySelectorAll<HTMLButtonElement>('.ann button')) {
  button.addEventListener('click', async () => {
    const kind = button.dataset.kind as AnnotationKind;
    const text =
      kind === 'intent_note'
        ? // An intent note becomes the step name verbatim; the model does not
          // rewrite it, so it is worth typing carefully (SS6.7).
          window.prompt('Describe this step. It will be used word for word.') ?? undefined
        : undefined;
    if (kind === 'intent_note' && !text) return;

    const state = await send<RecorderState>({ type: 'query-state' });
    await send({
      type: 'annotation',
      annotation: {
        id: `ann_${state.annotationCount + 1}`,
        kind,
        timestamp: state.startedAt ? Date.now() - state.startedAt : 0,
        ...(text ? { text } : {}),
      },
    });
    render(await send<RecorderState>({ type: 'query-state' }));
  });
}

$('pick').addEventListener('click', async () => {
  // The popup has to close: the tester is about to click something on the page,
  // and a popup with focus swallows the first click. The picker runs in the
  // content script and reports the annotation back on its own.
  await send({ type: 'pick' });
  window.close();
});

void send<RecorderState>({ type: 'query-state' }).then(render);
