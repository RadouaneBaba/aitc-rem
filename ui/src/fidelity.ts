/**
 * What the recorder could not determine, said to a tester.
 *
 * SS6.8 wrote this copy, sentence by sentence, and the UI shipped the enum:
 * `rapid_sequence` in a list, in a monospace font, to a QA tester. The spec's
 * own closing line on the table is that "a tool that admits what it doesn't
 * know stays trusted" -- which only works if the admission is in a language the
 * reader speaks.
 *
 * The severity split is the spec's too, and it is load-bearing. Flagging every
 * notice for review is why six of seven steps once carried a marker, which
 * teaches the reader to ignore all of them.
 */

export type FidelitySeverity = 'warn' | 'note';

export interface FidelityCopy {
  severity: FidelitySeverity;
  text: string;
}

const COPY: Record<string, FidelityCopy> = {
  canvas_interaction: {
    severity: 'warn',
    text: 'The tester clicked inside a drawing area, so all I know is where they clicked. Please describe what happened.',
  },
  no_accessible_name: {
    severity: 'warn',
    text: 'This control has no label of any kind, so my description of it may be wrong.',
  },
  closed_shadow_root: {
    severity: 'warn',
    text: 'This component keeps its contents private to the page, so I could not read what was inside it.',
  },
  cross_origin_frame_blocked: {
    severity: 'warn',
    text: 'This step touched an embedded frame from another site, which I am not allowed to read.',
  },
  drag_interaction: {
    severity: 'warn',
    text: 'This was a drag, and I cannot always tell what was dragged where. Read the step carefully.',
  },
  settle_timeout: {
    severity: 'warn',
    text: 'The page was still working five seconds after this action, so the outcome I captured may be incomplete.',
  },
  file_content_omitted: {
    severity: 'note',
    text: 'A file was chosen but its contents were not recorded. Attach the real file before running this test.',
  },
  rapid_sequence: {
    severity: 'note',
    text: 'These actions happened too fast to separate, so they were grouped. Worth checking the step boundaries.',
  },
  network_incomplete: {
    severity: 'note',
    text: 'Some requests may have been missed, so I have been careful about claiming anything was saved.',
  },
};

export function fidelityCopy(flag: string): FidelityCopy {
  // An unknown flag is shown rather than hidden. A new one added to the schema
  // and not to this table is a gap in the copy, and silently dropping it would
  // hide something the recorder went out of its way to tell us.
  return COPY[flag] ?? { severity: 'note', text: flag.replace(/_/g, ' ') };
}
