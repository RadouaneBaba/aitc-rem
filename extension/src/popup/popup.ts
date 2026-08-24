import type { AnnotationKind } from '../types/recording';
import type { RecorderState, WorkerInbound } from '../shared/messages';

function send<T>(message: WorkerInbound | { type: string }): Promise<T> {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function render(state: RecorderState): void {
  $('idle').hidden = state.recording;
  $('active').hidden = !state.recording;
  $('count').textContent = String(state.eventCount);
  $('annotations').textContent = String(state.annotationCount);
  $('origins').textContent = state.origins.length ? String(state.origins.length) : '-';
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
