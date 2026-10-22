import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const KEY = 'cwv-theme';

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function storedTheme(): Theme | null {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null; // storage can be blocked; fall back to the system setting
  }
}

/**
 * Light or dark. Follows the system setting until the user picks one; the
 * choice is remembered in this browser. index.html applies it before the
 * first paint so the page does not flash.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // not remembered, but still applied for this visit
    }
  }

  return [theme, toggle];
}
