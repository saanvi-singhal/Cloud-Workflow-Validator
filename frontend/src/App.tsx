import { useState } from 'react';
import type { SourceFormat } from './types';
import AnalyzePage from './pages/AnalyzePage';
import HowItWorksPage from './pages/HowItWorksPage';
import CompareView from './components/CompareView';
import { HREF, useRoute, type Route } from './useRoute';
import { useTheme } from './useTheme';

const NAV: { route: Route; label: string }[] = [
  { route: 'analyze', label: 'Analyze' },
  { route: 'compare', label: 'Compare versions' },
  { route: 'how-it-works', label: 'How it works' },
];

/** Three nodes joined in order: the dependency graph the tool draws. */
function Mark() {
  return (
    <svg viewBox="0 0 28 28" className="h-7 w-7" aria-hidden="true">
      <path d="M7 8.5 L14 19.5 L21 8.5" fill="none" stroke="var(--color-accent)" strokeWidth="2" />
      <circle cx="7" cy="8.5" r="3.5" fill="var(--color-ink)" />
      <circle cx="21" cy="8.5" r="3.5" fill="var(--color-ink)" />
      <circle cx="14" cy="19.5" r="3.5" fill="var(--color-accent)" />
    </svg>
  );
}

export default function App() {
  const route = useRoute();
  const [theme, toggleTheme] = useTheme();
  // Shared so "Compare versions" opens on the format being analysed.
  const [compareFormat, setCompareFormat] = useState<SourceFormat>('terraform');

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <a href={HREF.analyze} className="flex items-center gap-2.5 text-ink">
            <Mark />
            <span className="text-[17px] font-semibold tracking-tight">
              Cloud Workflow Validator
            </span>
          </a>
          <nav aria-label="Main" className="flex gap-1">
            {NAV.map(item => (
              <a
                key={item.route}
                href={HREF[item.route]}
                aria-current={route === item.route ? 'page' : undefined}
                className={`rounded-md px-3 py-1.5 text-sm ${
                  route === item.route
                    ? 'bg-accent-soft font-medium text-accent-strong'
                    : 'text-muted hover:bg-paper hover:text-ink'
                }`}
              >
                {item.label}
              </a>
            ))}
          </nav>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            className="ml-auto rounded-md border border-line p-2 text-muted hover:bg-paper hover:text-ink"
          >
            {theme === 'dark' ? (
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
              </svg>
            ) : (
              <svg
                viewBox="0 0 24 24"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      <main>
        {/* Analyze stays mounted so switching pages keeps your input and results. */}
        <div hidden={route !== 'analyze'}>
          <AnalyzePage />
        </div>
        {route === 'compare' && (
          <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">Compare versions</h1>
            <p className="mt-1 max-w-prose text-muted">
              Paste the old and the new version of one file to see which dependencies were added,
              removed or rewired, and whether the change introduces a cycle.
            </p>
            <div className="mt-5">
              <CompareView language={compareFormat} onLanguageChange={setCompareFormat} />
            </div>
          </div>
        )}
        {route === 'how-it-works' && <HowItWorksPage />}
      </main>
    </div>
  );
}
