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
  'w-full rounded-lg border bg-slate-950/90 p-3.5 font-mono text-xs leading-relaxed text-sky-100 placeholder:text-slate-600 focus:ring-1 focus:outline-hidden';

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
      <section className="aero-glass-panel rounded-xl p-6 shadow-2xl">
        <label className="mb-4 block font-mono text-xs font-semibold uppercase tracking-wider text-sky-300">
          Format
          <select
            aria-label="Compare format"
            value={language === 'mixed' ? 'terraform' : language}
            onChange={e => {
              onLanguageChange(e.target.value as SourceFormat);
              setResults(null);
            }}
            className="mt-1.5 block w-44 rounded-lg border border-slate-700 bg-slate-950 p-2 font-mono text-xs text-sky-200"
          >
            <option value="terraform">Terraform</option>
            <option value="dockerfile">Dockerfile</option>
            <option value="yaml">YAML</option>
          </select>
        </label>
        <div className="grid gap-4 lg:grid-cols-2">
          <label className="block font-mono text-xs font-semibold uppercase tracking-wider text-rose-300">
            Old version
            <textarea
              value={oldCode}
              onChange={e => setOldCode(e.target.value)}
              placeholder="Paste the old configuration here"
              rows={14}
              spellCheck={false}
              className={`${EDITOR} mt-1.5 border-rose-500/40 focus:border-rose-400 focus:ring-rose-400/50`}
            />
          </label>
          <label className="block font-mono text-xs font-semibold uppercase tracking-wider text-emerald-300">
            New version
            <textarea
              value={newCode}
              onChange={e => setNewCode(e.target.value)}
              placeholder="Paste the new configuration here"
              rows={14}
              spellCheck={false}
              className={`${EDITOR} mt-1.5 border-emerald-500/40 focus:border-emerald-400 focus:ring-emerald-400/50`}
            />
          </label>
        </div>
        <button
          type="button"
          onClick={handleCompare}
          disabled={loading}
          className="mt-4 rounded-lg bg-gradient-to-r from-sky-500 to-cyan-400 px-6 py-2.5 font-mono text-xs font-bold uppercase tracking-wider text-slate-950 hover:from-sky-400 hover:to-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Comparing...' : 'Compare graphs'}
        </button>
        {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
      </section>

      {results && diff && (
        <>
          <section className="aero-glass-panel rounded-xl p-6 shadow-2xl">
            <h2 className="font-mono text-base font-semibold uppercase tracking-wider text-white">
              Comparison summary
            </h2>
            <div className="mt-3 flex flex-wrap gap-2 font-mono text-xs font-semibold">
              <span className="rounded bg-emerald-950/60 px-3 py-1.5 text-emerald-300">
                {diff.addedNodes.length} added nodes
              </span>
              <span className="rounded bg-rose-950/60 px-3 py-1.5 text-rose-300">
                {diff.removedNodes.length} removed nodes
              </span>
              <span className="rounded bg-orange-950/60 px-3 py-1.5 text-orange-300">
                {diff.rewiredNodes.length} rewired
              </span>
              <span className="rounded bg-emerald-950/60 px-3 py-1.5 text-emerald-300">
                {diff.addedEdges.length} added edges
              </span>
              <span className="rounded bg-rose-950/60 px-3 py-1.5 text-rose-300">
                {diff.removedEdges.length} removed edges
              </span>
              <span
                className={`rounded px-3 py-1.5 ${diff.newCycles.length ? 'bg-rose-950/60 text-rose-300' : 'bg-slate-900 text-slate-400'}`}
              >
                {diff.newCycles.length} new cycles
              </span>
            </div>
            {diff.newCycles.length > 0 && (
              <div className="mt-4 rounded-lg border border-rose-500/40 bg-rose-950/40 p-3 text-sm text-rose-200">
                <strong>The new version introduces a dependency cycle.</strong>
                <ul className="mt-2 list-disc pl-5">
                  {diff.newCycles.map((cycle, i) => (
                    <li key={i}>{cycle.message}</li>
                  ))}
                </ul>
              </div>
            )}
            {diff.resolvedCycles.length > 0 && (
              <p className="mt-3 text-sm text-emerald-300">
                {diff.resolvedCycles.length} cycle(s) from the old version are resolved.
              </p>
            )}
            {diff.identical && (
              <p className="mt-3 text-sm text-slate-400">No graph changes detected.</p>
            )}
          </section>

          <div className="grid gap-6 xl:grid-cols-2">
            <section className="aero-glass-panel min-w-0 rounded-xl p-4 shadow-2xl">
              <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-rose-300">
                Old version graph
              </h2>
              <DependencyGraph
                result={results[0]}
                highlighted={NO_HIGHLIGHT}
                onSelectNode={() => {}}
                diff={oldHighlight}
              />
            </section>
            <section className="aero-glass-panel min-w-0 rounded-xl p-4 shadow-2xl">
              <h2 className="font-mono text-sm font-semibold uppercase tracking-wider text-emerald-300">
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

          <section className="aero-glass-panel rounded-xl p-6 text-sm text-slate-300 shadow-2xl">
            <h2 className="font-mono text-base font-semibold uppercase tracking-wider text-white">
              Changed nodes and dependencies
            </h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              {(
                [
                  ['Added nodes', diff.addedNodes, 'text-emerald-300'],
                  ['Removed nodes', diff.removedNodes, 'text-rose-300'],
                  ['Rewired', diff.rewiredNodes, 'text-orange-300'],
                  ['Added dependencies', diff.addedEdges, 'text-emerald-300'],
                  ['Removed dependencies', diff.removedEdges, 'text-rose-300'],
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
                    <p className="text-slate-500">None</p>
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
