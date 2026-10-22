import { useState } from 'react';
import type { AnalysisResult, Severity } from '../types';
import { diagnosticNodeIds, formatLocation, severityCounts } from '../analysis';
import PatchBlock from './PatchBlock';
import { splitRule } from '../advisor';

const SEVERITY_LABEL: Record<Severity, string> = {
  error: 'Error',
  warning: 'Warning',
  info: 'Suggestion',
};

const SEVERITY_STYLE: Record<Severity, { bar: string; text: string }> = {
  error: { bar: 'bg-error', text: 'text-error' },
  warning: { bar: 'bg-warning', text: 'text-warning' },
  info: { bar: 'bg-info', text: 'text-info' },
};

const FILTER_LABEL: Record<Severity, string> = {
  error: 'Errors',
  warning: 'Warnings',
  info: 'Suggestions',
};

interface Props {
  result: AnalysisResult;
  activeDiagnostic: number | null;
  /** Highlight the issue's nodes and show it in the editor. */
  onSelect: (index: number) => void;
  /** Switch to the graph with the issue's nodes highlighted. */
  onShowInGraph: (index: number) => void;
}

/**
 * Every diagnostic, with the fix for it directly underneath (recommendations
 * are linked by `diagnostic_index`), instead of two separate lists.
 */
export default function IssuesList({ result, activeDiagnostic, onSelect, onShowInGraph }: Props) {
  const [filter, setFilter] = useState<Severity | 'all'>('all');
  const counts = severityCounts(result);
  const present = (['error', 'warning', 'info'] as Severity[]).filter(s => counts[s] > 0);

  if (result.diagnostics.length === 0) {
    return (
      <div className="px-1 py-6">
        <p className="font-medium text-ink">No issues found.</p>
        <p className="mt-1 text-sm text-muted">
          Nothing in this configuration breaks a check. The graph tab shows how its parts depend
          on each other.
        </p>
      </div>
    );
  }

  const shown = result.diagnostics
    .map((d, index) => ({ d, index }))
    .filter(({ d }) => filter === 'all' || d.severity === filter);

  return (
    <div>
      {present.length > 1 && (
        <div role="group" aria-label="Filter issues" className="mb-3 flex flex-wrap gap-1.5">
          {(['all', ...present] as const).map(key => {
            const active = filter === key;
            return (
              <button
                key={key}
                type="button"
                aria-pressed={active}
                onClick={() => setFilter(key)}
                className={`rounded-full border px-3 py-1 text-sm ${
                  active
                    ? 'border-ink bg-ink text-white'
                    : 'border-line bg-surface text-muted hover:border-faint hover:text-ink'
                }`}
              >
                {key === 'all' ? 'All' : FILTER_LABEL[key]}{' '}
                <span className={active ? 'text-white/70' : 'text-faint'}>
                  {key === 'all' ? result.diagnostics.length : counts[key]}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <ul aria-label="Issues" className="divide-y divide-line-soft overflow-hidden rounded-lg border border-line bg-surface">
        {shown.map(({ d, index }) => {
          const style = SEVERITY_STYLE[d.severity];
          const where = formatLocation(d.source_location);
          const fixes = result.recommendations.filter(r => r.diagnostic_index === index);
          const linked = diagnosticNodeIds(result, index).length > 0;
          const active = activeDiagnostic === index;
          // "[DF_RUNS_AS_ROOT] The final stage..." reads as the sentence, with
          // the rule id shown once below it instead of the generic code.
          const [rule, text] = splitRule(d.message);
          return (
            <li key={index} className={`relative ${active ? 'bg-accent-soft/50' : ''}`}>
              <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${style.bar}`} />
              <button
                type="button"
                onClick={() => onSelect(index)}
                className="block w-full py-3 pr-28 pl-5 text-left hover:bg-paper/60"
              >
                <span className={`text-xs font-semibold ${style.text}`}>{SEVERITY_LABEL[d.severity]}</span>
                <span className="mt-0.5 block text-[15px] leading-snug text-ink">{text}</span>
                <span className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                  <span className="font-mono" title={rule ? d.code : undefined}>
                    {rule ?? d.code}
                  </span>
                  {where && <span>{where}</span>}
                </span>
              </button>
              {linked && (
                <button
                  type="button"
                  onClick={() => onShowInGraph(index)}
                  className="absolute top-3 right-4 rounded px-1.5 py-0.5 text-xs font-medium text-accent hover:bg-accent-soft"
                >
                  Show in graph
                </button>
              )}
              {fixes.length > 0 && (
                <div className="pr-4 pb-3 pl-5">
                  {fixes.map(r => (
                    <details
                      key={r.id}
                      open={active || undefined}
                      className="group mt-1 rounded-md border border-line-soft bg-paper/50 open:bg-surface"
                    >
                      <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium text-ink marker:hidden">
                        <span className="mr-1.5 inline-block text-faint transition-transform group-open:rotate-90">
                          ›
                        </span>
                        Fix: {r.title}
                      </summary>
                      <div className="border-t border-line-soft px-3 py-2.5 text-sm text-muted">
                        <p>{r.explanation}</p>
                        {r.proposed_change && (
                          <>
                            <p className="mt-2 text-ink">{r.proposed_change.description}</p>
                            {r.proposed_change.patch ? (
                              <PatchBlock patch={r.proposed_change.patch} id={r.id} />
                            ) : (
                              r.proposed_change.preview !== null && (
                                <pre
                                  aria-label="Preview"
                                  className="mt-2 overflow-x-auto rounded-md bg-ink p-2.5 font-mono text-xs text-[#cfe9e7]"
                                >
                                  {r.proposed_change.preview}
                                </pre>
                              )
                            )}
                          </>
                        )}
                        {r.fix_kind === 'judgment' && (
                          <p className="mt-2 text-xs text-faint">
                            Review before applying. This tool never changes your files.
                          </p>
                        )}
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
