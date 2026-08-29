/**
 * One address bar for the whole review screen.
 *
 * The keyboard loop already existed -- j/k to move, a/r to accept or reject --
 * and every other action was a mouse trip to a specific corner of a specific
 * bar. Switching run meant finding the picker; approving meant finding the
 * button; the how-to page was reachable from exactly one control on one screen.
 *
 * Deliberately not a fuzzy matcher and not a dependency: substring matching over
 * a list that is never longer than a few dozen entries, which is the whole
 * requirement.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void;
}

export function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[];
  onClose: () => void;
}) {
  const [query, setQuery] = useState('');
  const [at, setAt] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands.slice(0, 40);
    return commands
      .filter((c) => `${c.group} ${c.label} ${c.hint ?? ''}`.toLowerCase().includes(needle))
      .slice(0, 40);
  }, [commands, query]);

  useEffect(() => setAt(0), [query]);

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    const node = listRef.current?.children[at] as HTMLElement | undefined;
    node?.scrollIntoView({ block: 'nearest' });
  }, [at]);

  const choose = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    command.run();
  };

  return (
    <div className="palette-backdrop" onClick={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Commands"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          className="palette-input"
          placeholder="Jump to a step, switch run, approve…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setAt((i) => Math.min(i + 1, matches.length - 1));
            }
            if (e.key === 'ArrowUp') {
              e.preventDefault();
              setAt((i) => Math.max(i - 1, 0));
            }
            if (e.key === 'Enter') {
              e.preventDefault();
              choose(matches[at]);
            }
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              onClose();
            }
          }}
        />
        {matches.length === 0 ? (
          <p className="palette-empty muted">Nothing matches.</p>
        ) : (
          <ul className="palette-list" ref={listRef}>
            {matches.map((command, i) => (
              <li key={command.id}>
                <button
                  className={i === at ? 'on' : ''}
                  onMouseEnter={() => setAt(i)}
                  onClick={() => choose(command)}
                >
                  <span className="palette-group">{command.group}</span>
                  <span className="palette-label">{command.label}</span>
                  {command.hint && <span className="palette-hint muted">{command.hint}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
