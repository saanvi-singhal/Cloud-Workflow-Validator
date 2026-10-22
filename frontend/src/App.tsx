import { useState } from 'react';
import type { SourceFormat } from './types';
import AnalyzePage from './pages/AnalyzePage';
import HowItWorksPage from './pages/HowItWorksPage';
import CompareView from './components/CompareView';
import { HREF, useRoute, type Route } from './useRoute';

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
  // Shared so "Compare versions" opens on the format being analysed.
  const [compareFormat, setCompareFormat] = useState<SourceFormat>('terraform');

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <a href={HREF.analyze} className="flex items-center gap-2.5 text-ink">
            <Mark />
            <span className="text-[17px] font-semibold tracking-tight">Cloud Workflow Validator</span>
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
