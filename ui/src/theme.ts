/**
 * Light, dark, or whatever the machine is set to.
 *
 * `tokens.css` has honoured `data-theme` in both directions since it was
 * written, and nothing in the product ever set it -- a complete dark theme,
 * fully specified, reachable only by changing an OS setting. This is the
 * control that was missing, and it is about forty lines.
 *
 * Three states rather than two, and the third is the default: `system` stamps
 * no attribute at all and lets `prefers-color-scheme` decide, which is what
 * every existing install already does. An explicit choice stamps the attribute
 * so it beats the OS in both directions.
 */

import { useCallback, useEffect, useState } from 'react';

export type Theme = 'system' | 'light' | 'dark';

const KEY = 'aitc.theme';

function apply(theme: Theme): void {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

function stored(): Theme {
  try {
    const value = window.localStorage.getItem(KEY);
    if (value === 'light' || value === 'dark' || value === 'system') return value;
  } catch {
    // A private window, or site data blocked. The default is correct and the
    // page must render either way.
  }
  return 'system';
}

/** The theme, and a way to advance it. Cycles system -> light -> dark, because
 *  a three-state control with one button beats a menu for something somebody
 *  sets once. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(stored);

  useEffect(() => {
    apply(theme);
    try {
      window.localStorage.setItem(KEY, theme);
    } catch {
      // Not worth an error: the attribute is already applied and this visit
      // works. Only the memory of the choice is lost.
    }
  }, [theme]);

  const cycle = useCallback(() => {
    setTheme((current) =>
      current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system',
    );
  }, []);

  return [theme, cycle];
}
