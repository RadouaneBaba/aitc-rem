/**
 * SS6.6 -- asking for the microphone, once.
 *
 * This page exists for one narrow reason: **an offscreen document cannot show a
 * permission prompt.** Chrome suppresses it there, so `getUserMedia` from
 * `offscreen.ts` succeeds only if permission was already granted, and fails
 * silently with `NotAllowedError` if it was not. The documented way round it is
 * a real extension page, in a real tab, asking on a real user gesture -- which
 * is this.
 *
 * The prompt is against `chrome-extension://<id>`, so it is granted once for the
 * extension and never again, and never per site. That matters: the recorder is
 * black-box (SS6.1) and must not need the application under test to cooperate,
 * including by hosting a microphone prompt.
 *
 * The stream is stopped the instant it opens. Nothing is recorded here; the
 * only product of this page is the permission itself.
 */

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function show(id: 'asking' | 'granted' | 'denied'): void {
  for (const state of ['asking', 'granted', 'denied'] as const) {
    $(state).hidden = state !== id;
  }
}

async function ask(): Promise<void> {
  show('asking');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    show('granted');
    // Long enough to read the confirmation, short enough not to become a tab
    // the tester has to tidy up.
    setTimeout(() => window.close(), 1600);
  } catch (err) {
    show('denied');
    $('reason').textContent = String((err as Error)?.message ?? err);
    // Narration is turned back off rather than left on and broken. A toggle
    // that says "on" while nothing is being captured is worse than one that
    // admits it was declined.
    await chrome.runtime.sendMessage({ type: 'set-narration', enabled: false }).catch(() => undefined);
  }
}

$('ask').addEventListener('click', () => void ask());
$('cancel').addEventListener('click', () => {
  void chrome.runtime.sendMessage({ type: 'set-narration', enabled: false }).catch(() => undefined);
  window.close();
});
