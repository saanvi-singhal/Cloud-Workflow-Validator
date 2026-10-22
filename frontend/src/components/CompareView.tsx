import { useMemo, useState } from 'react';
import type { AnalysisResult, SourceFormat } from '../types';
import { analyze } from '../api';
import { diffResults, highlightFor } from '../graphDiff';
import DependencyGraph from './DependencyGraph';

interface Props {
  language: SourceFormat;
  onLanguageChange: (language: SourceFormat) => void;
}

const NO_HIGHLIGHT: ReadonlySet<string> = new Set();

const EDITOR =
  'w-full rounded-lg border bg-surface p-3.5 font-mono text-xs leading-relaxed text-ink placeholder:text-faint focus:ring-1 focus:outline-hidden';

/**
 * Graph diff: analyse an old and a new version of one configuration and draw
 * both graphs with the differences coloured (added, removed, rewired), plus
 * any dependency cycle the new version introduces. Both versions go through
 * the normal API; the comparison itself is done in graphDiff.ts.
 */
export default function CompareView({ language, onLanguageChange }: Props) {
  const [oldCode, setOldCode] = useState('');
  const [newCode, setNewCode] = useState('');
  const [results, setResults] = useState<[AnalysisResult, AnalysisResult] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const diff = useMemo(() => (results ? diffResults(results[0], results[1]) : null), [results]);
  const oldHighlight = useMemo(() => (diff ? highlightFor(diff, 'old') : undefined), [diff]);
  const newHighlight = useMemo(() => (diff ? highlightFor(diff, 'new') : undefined), [diff]);

  async function handleCompare() {
    if (!oldCode.trim() || !newCode.trim()) {
      setError('Enter both the old and the new version first.');
      return;
    }
    setLoading(true);
    setError('');
    setResults(null);
    try {
      const format = language === 'mixed' ? 'terraform' : language;
      setResults(await Promise.all([analyze(format, oldCode), analyze(format, newCode)]));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-line/90 bg-surface p-6 ">
        <label className="mb-4 block text-sm font-medium text-muted">
          Format
          <select
            aria-label="Compare format"
            value={language === 'mixed' ? 'terraform' : language}
            onChange={e => {
              onLanguageChange(e.target.value as SourceFormat);
              setResults(null);
            }}
            className="mt-1 block w-44 rounded-md border border-line bg-surface p-2 text-sm"
          >
            <option value="terraform">Terraform</option>
            <option value="dockerfile">Dockerfile</option>
            <option value="yaml">YAML</option>
          </select>
        </label>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="block text-sm font-semibold text-error">
            Old version
            <textarea
              value={oldCode}
              onChange={e => setOldCode(e.target.value)}
              placeholder="Paste the old configuration here"
              rows={14}
              spellCheck={false}
              className={`${EDITOR} mt-1.5 border-error/30 focus:border-red-400 focus:ring-red-300`}
            />
          </label>
          <label className="block text-sm font-semibold text-ok">
            New version
            <textarea
              value={newCode}
              onChange={e => setNewCode(e.target.value)}
              placeholder="Paste the new configuration here"
              rows={14}
              spellCheck={false}
              className={`${EDITOR} mt-1.5 border-ok/30 focus:border-green-400 focus:ring-green-300`}
            />
          </label>
        </div>
        <button
          type="button"
          onClick={handleCompare}
          disabled={loading}
          className="mt-4 rounded-md bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? 'Comparing...' : 'Compare graphs'}
        </button>
        {error && <p className="mt-3 text-sm text-error">{error}</p>}
      </section>

      {results && diff && (
        <>
          <section className="rounded-xl border border-line/90 bg-surface p-6 ">
            <h2 className="font-semibold text-ink">
              Comparison summary
            </h2>
            <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
              <span className="rounded bg-ok-soft px-3 py-1.5 text-ok">
                {diff.addedNodes.length} added nodes
              </span>
              <span className="rounded bg-error-soft px-3 py-1.5 text-red-800">
                {diff.removedNodes.length} removed nodes
              </span>
              <span className="rounded bg-orange-100 px-3 py-1.5 text-orange-800">
                {diff.rewiredNodes.length} rewired
              </span>
              <span className="rounded bg-ok-soft px-3 py-1.5 text-ok">
                {diff.addedEdges.length} added edges
              </span>
              <span className="rounded bg-error-soft px-3 py-1.5 text-red-800">
                {diff.removedEdges.length} removed edges
              </span>
              <span
                className={`rounded px-3 py-1.5 ${diff.newCycles.length ? 'bg-error-soft text-red-800' : 'bg-paper text-muted'}`}
              >
                {diff.newCycles.length} new cycles
              </span>
            </div>
            {diff.newCycles.length > 0 && (
              <div className="mt-4 rounded-lg border border-error/30 bg-error-soft p-3 text-sm text-red-800">
                <strong>The new version introduces a dependency cycle.</strong>
                <ul className="mt-2 list-disc pl-5">
                  {diff.newCycles.map((cycle, i) => (
                    <li key={i}>{cycle.message}</li>
                  ))}
                </ul>
              </div>
            )}
            {diff.resolvedCycles.length > 0 && (
              <p className="mt-3 text-sm text-ok">
                {diff.resolvedCycles.length} cycle(s) from the old version are resolved.
              </p>
            )}
            {diff.identical && (
              <p className="mt-3 text-sm text-faint">No graph changes detected.</p>
            )}
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <section className="min-w-0 rounded-xl border border-line/90 bg-surface p-4 ">
              <h2 className="text-sm font-semibold text-error">
                Old version graph
              </h2>
              <DependencyGraph
                result={results[0]}
                highlighted={NO_HIGHLIGHT}
                onSelectNode={() => {}}
                diff={oldHighlight}
              />
            </section>
            <section className="min-w-0 rounded-xl border border-line/90 bg-surface p-4 ">
              <h2 className="text-sm font-semibold text-ok">
                New version graph
              </h2>
              <DependencyGraph
                result={results[1]}
                highlighted={NO_HIGHLIGHT}
                onSelectNode={() => {}}
                diff={newHighlight}
              />
            </section>
          </div>

          <section className="rounded-xl border border-line/90 bg-surface p-6 text-sm text-muted ">
            <h2 className="font-semibold text-ink">
              Changed nodes and dependencies
            </h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              {(
                [
                  ['Added nodes', diff.addedNodes, 'text-ok'],
                  ['Removed nodes', diff.removedNodes, 'text-error'],
                  ['Rewired', diff.rewiredNodes, 'text-orange-700'],
                  ['Added dependencies', diff.addedEdges, 'text-ok'],
                  ['Removed dependencies', diff.removedEdges, 'text-error'],
                ] as const
              ).map(([title, items, color]) => (
                <div key={title}>
                  <h3 className={`font-semibold ${color}`}>{title}</h3>
                  {items.length ? (
                    <ul className="list-disc pl-5 font-mono text-xs">
                      {items.map(item => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-faint">None</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
