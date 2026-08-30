import type { AnnotationKind, RedactionLevel } from '../types/recording';
import type { NarrationStatus, RecorderState, WorkerInbound } from '../shared/messages';
import { coachObjective } from './objective';

function send<T>(message: WorkerInbound | { type: string }): Promise<T> {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/**
 * Where the how-to page lives.
 *
 * The popup cannot know the server address for certain, so it uses the one the
 * send page defaults to and remembers whatever was actually used last. A
 * how-to nobody can reach from the recorder is how the current one ended up
 * reachable from exactly one button on one screen.
 */
const DEFAULT_SERVER = 'http://127.0.0.1:8000';

/**
 * What to say when the microphone is not doing what was asked.
 *
 * `denied` and `unsupported` are different sentences because they are different
 * situations: one is a person who said no, the other is a browser that cannot.
 * Telling somebody to check their microphone when they deliberately declined is
 * how a tool loses their trust.
 */
const MIC_TROUBLE: Partial<Record<NarrationStatus, string>> = {
  denied:
    'Chrome would not give up the microphone. Nothing is being recorded. ' +
    'Open the padlock in the address bar of the permission tab to reset it.',
  unsupported: 'This browser will not record audio here, so narration is off for this session.',
};

/**
 * One poll, and it runs whenever a recording is running.
 *
 * It used to run only while the microphone was live, because the level meter
 * was the only thing that moved. There was no elapsed timer and no recording
 * indicator at all -- the only sign a session was in progress was a number
 * labelled "Events", which is not a state a person can read at a glance.
 */
let poll: number | undefined;

function elapsed(startedAt: number | undefined): string {
  if (!startedAt) return '0:00';
  const total = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

function render(state: RecorderState): void {
  const settingsOpen = !$('settings-pane').hidden;

  $('idle').hidden = state.recording || settingsOpen;
  $('settings-pane').hidden = state.recording || !settingsOpen;
  $('active').hidden = !state.recording;
  $('settings').hidden = state.recording;

  $('count').textContent = String(state.eventCount);
  $('annotations').textContent = String(state.annotationCount);
  $('origins').textContent = state.origins.length ? String(state.origins.length) : '-';
  $('elapsed').textContent = elapsed(state.startedAt);
  ($('narrate') as HTMLInputElement).checked = state.narrationEnabled;

  const trouble = MIC_TROUBLE[state.narrationStatus];
  const live = state.narrationStatus === 'listening' || state.narrationStatus === 'muted';

  $('mic').hidden = !live;
  $('mute').hidden = !live;
  $('micwarn').hidden = !trouble;
  $('micwarn').textContent = trouble ?? '';

  if (live) {
    const muted = state.narrationStatus === 'muted';
    $('recdot').className = muted ? 'recdot muted-dot' : 'recdot';
    $('micmeter').style.width = `${Math.round((state.narrationLevel ?? 0) * 100)}%`;
    $('mute').textContent = muted ? 'Unmute' : 'Mute';
  } else {
    $('recdot').className = 'recdot';
  }

  // Only while something is actually moving. A popup that polls the worker
  // awake every 300ms for nothing is a worker that never gets evicted.
  if (state.recording && poll === undefined) {
    poll = window.setInterval(async () => render(await send<RecorderState>({ type: 'query-state' })), 300);
  } else if (!state.recording && poll !== undefined) {
    window.clearInterval(poll);
    poll = undefined;
  }
}

/**
 * The objective coach, live as they type.
 *
 * Deterministic, so there is no spinner and nothing to wait for, and it NEVER
 * blocks Start -- somebody who disagrees is very often right, and a coach that
 * argues gets switched off. One line, never a paragraph.
 */
const objectiveField = $('objective') as HTMLTextAreaElement;
const objectiveAdvice = $('objective-advice');

function coach(): void {
  const advice = coachObjective(objectiveField.value);
  objectiveField.setAttribute('data-verdict', advice.verdict);
  objectiveAdvice.className = `coach ${advice.verdict}`;

  if (advice.verdict === 'empty') {
    objectiveAdvice.textContent = 'Optional — and the strongest single thing you can give the tool.';
    return;
  }
  // `sharp` carries no message, because there is nothing to correct. Saying so
  // is worth a line: somebody who has just rewritten a vague objective should
  // be told it landed.
  objectiveAdvice.textContent = advice.message || 'Specific enough.';
}

objectiveField.addEventListener('input', coach);
coach();

/**
 * How much to redact, chosen before recording starts.
 *
 * It lives here rather than in `config/project.yaml` because redaction happens
 * in the browser BEFORE anything is persisted -- by the time a server setting
 * could be consulted the decision has already been taken and cannot be
 * revisited. It is also genuinely per-recording: one session of a demo app and
 * one of a system whose order references scan as card numbers can sit in the
 * same project, and the level travels with each recording so the server never
 * has to guess which was which.
 *
 * It was a `<select>` inside a bare `<details>` labelled "Redaction", so the
 * current state was invisible unless you opened it. Three buttons, one of them
 * lit.
 */
const redactionSeg = $('redaction-seg');
const redactionHint = $('redaction-hint');
// Passwords by default, not the pattern scan.
//
// `full` adds a scan that decides by SHAPE, and shape is the half that can be
// wrong about a value nobody typed. On one storefront listing it produced 214
// parameters, every one classified as a phone number, and what it had actually
// matched was dates -- "Updated 2026-08-28 14:32" became `<<phone_n>>`. A date
// or a price on a page is routinely the thing a test asserts on, so on a real
// commercial site the safer-sounding setting is the one that destroys the
// evidence the test needed.
//
// `secrets_only` keeps the half that decides by CONTEXT and cannot be wrong
// that way: a password field is secret whatever its value looks like, and an
// exact string the tester typed is still redacted wherever it is displayed.
let redaction: RedactionLevel = 'secrets_only';

const REDACTION_HINTS: Record<string, string> = {
  full: 'Emails, card numbers, tokens and anything typed into a password field are replaced with a placeholder before anything reaches the disk.',
  secrets_only:
    'For applications whose real data looks sensitive — an order reference that scans as a card number, a code that scans as a phone number. Passwords are still hidden; nothing is guessed at by shape.',
  off: 'Nothing is hidden. Values you type are saved exactly as you type them, and this recording can only be processed against a paid model endpoint that does not train on it.',
};

function describeRedaction(): void {
  redactionHint.textContent = REDACTION_HINTS[redaction] ?? '';
  for (const button of redactionSeg.querySelectorAll('button')) {
    button.setAttribute('aria-pressed', String(button.dataset.level === redaction));
  }
}

void chrome.storage.local.get('redaction').then((stored) => {
  if (typeof stored.redaction === 'string') redaction = stored.redaction as RedactionLevel;
  describeRedaction();
});

for (const button of redactionSeg.querySelectorAll('button')) {
  button.addEventListener('click', () => {
    redaction = (button.dataset.level ?? 'full') as RedactionLevel;
    void chrome.storage.local.set({ redaction });
    describeRedaction();
  });
}

$('settings').addEventListener('click', async () => {
  $('settings-pane').hidden = false;
  render(await send<RecorderState>({ type: 'query-state' }));
});

$('settings-done').addEventListener('click', async () => {
  $('settings-pane').hidden = true;
  render(await send<RecorderState>({ type: 'query-state' }));
});

$('howto').addEventListener('click', async () => {
  const stored = await chrome.storage.local.get('serverUrl');
  const base = typeof stored.serverUrl === 'string' ? stored.serverUrl : DEFAULT_SERVER;
  await chrome.tabs.create({ url: `${base.replace(/\/$/, '')}/help` });
  window.close();
});

$('start').addEventListener('click', async () => {
  const objective = objectiveField.value.trim();
  render(
    await send<RecorderState>({
      type: 'start',
      objective: objective || undefined,
      redaction,
    }),
  );
});

/**
 * One Stop.
 *
 * There were two side by side -- `Stop` and `Stop & export` -- with nothing on
 * screen to say which one you wanted, and no flow in which somebody stops a
 * session and does not want to see what they recorded.
 *
 * The message order is unchanged and load-bearing. `stop` cancels open settle
 * windows, waits for in-flight captures and only then acknowledges; the send
 * page then waits for `session.stopped` before it assembles. Reorder any of
 * that and the recording comes back one event short and looks complete.
 */
$('stop').addEventListener('click', async () => {
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

async function annotate(kind: AnnotationKind, text?: string): Promise<void> {
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
}

/**
 * An intent note names the step VERBATIM -- nothing downstream rewrites it --
 * and it was being collected in a `window.prompt`: no example, no room to see
 * what you typed, and no way to correct it. The one input somebody is asked to
 * write carefully had the worst field in the tool.
 */
const noteForm = $('noteform');
const noteText = $('notetext') as HTMLTextAreaElement;

function showNote(open: boolean): void {
  noteForm.hidden = !open;
  if (open) noteText.focus();
  else noteText.value = '';
}

for (const button of document.querySelectorAll<HTMLButtonElement>('.ann button')) {
  button.addEventListener('click', async () => {
    const kind = button.dataset.kind as AnnotationKind;
    if (kind === 'intent_note') {
      showNote(true);
      return;
    }
    await annotate(kind);
  });
}

$('notesave').addEventListener('click', async () => {
  const text = noteText.value.trim();
  if (!text) return;
  showNote(false);
  await annotate('intent_note', text);
});

$('notecancel').addEventListener('click', () => showNote(false));

$('pick').addEventListener('click', async () => {
  // The popup has to close: the tester is about to click something on the page,
  // and a popup with focus swallows the first click. The picker runs in the
  // content script and reports the annotation back on its own.
  await send({ type: 'pick' });
  window.close();
});

void send<RecorderState>({ type: 'query-state' }).then(render);
