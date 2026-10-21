import type { AnalysisResult, GraphNode, SourceLocation } from '../types';
import {
  formatLocation,
  metadataEntries,
  nodeDiagnostics,
  stageInstructions,
} from '../analysis';

const SEVERITY_TEXT = {
  error: 'text-red-700',
  warning: 'text-amber-700',
  info: 'text-sky-700',
} as const;

const SEVERITY_ROW = {
  error: 'border-red-300 bg-red-50 hover:bg-red-100',
  warning: 'border-amber-300 bg-amber-50 hover:bg-amber-100',
  info: 'border-sky-300 bg-sky-50 hover:bg-sky-100',
} as const;

interface Props {
  result: AnalysisResult;
  node: GraphNode;
  onJump: (location: SourceLocation | null) => void;
  onSelectDiagnostic: (index: number) => void;
  onClose: () => void;
}

// Details for the selected graph node (spec 8.2 step 7): its metadata, linked
// diagnostics and, for Dockerfile stages, the ordered instructions.
export default function NodeDetails({ result, node, onJump, onSelectDiagnostic, onClose }: Props) {
  const where = formatLocation(node.source_location);
  const instructions = stageInstructions(node);
  const metadata = metadataEntries(node);
  const issues = nodeDiagnostics(result, node.id);
  const lineLocation = (start: number, end: number): SourceLocation => ({
    file: null,
    start_line: start,
    start_column: null,
    end_line: end,
    end_column: null,
  });

  return (
    <section className="rounded-2xl border-2 border-indigo-200 bg-white p-5 text-base shadow-lg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-bold uppercase tracking-wide text-indigo-600">
            {node.type}
          </div>
          <h3 className="break-all text-xl font-bold text-slate-900">{node.label}</h3>
          <div className="break-all font-mono text-xs text-slate-500">{node.id}</div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-200"
          aria-label="Close node details"
        >
          Close
        </button>
      </div>

      {where && (
        <button
          onClick={() => onJump(node.source_location)}
          className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-700"
        >
          Defined at {where}
        </button>
      )}

      {issues.length > 0 && (
        <div className="mt-4">
          <div className="text-lg font-bold text-slate-900">Issues</div>
          <ul className="mt-2 space-y-2">
            {issues.map(({ index, diagnostic }) => (
              <li key={index}>
                <button
                  onClick={() => onSelectDiagnostic(index)}
                  className={`w-full rounded-lg border-2 p-3 text-left ${SEVERITY_ROW[diagnostic.severity]}`}
                >
                  <span className={`font-bold ${SEVERITY_TEXT[diagnostic.severity]}`}>
                    {diagnostic.severity.toUpperCase()}
                  </span>{' '}
                  <span className="text-slate-800">{diagnostic.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {instructions.length > 0 && (
        <div className="mt-4">
          <div className="text-lg font-bold text-slate-900">Instructions</div>
          <ol className="mt-2 overflow-hidden rounded-lg border-2 border-slate-200 bg-slate-50 font-mono text-sm">
            {instructions.map(item => (
              <li key={item.start_line} className="border-b border-slate-200 last:border-0">
                <button
                  onClick={() => onJump(lineLocation(item.start_line, item.end_line))}
                  className="flex w-full gap-3 px-3 py-2 text-left hover:bg-indigo-50"
                  title="Show in editor"
                >
                  <span className="w-8 shrink-0 text-right text-slate-500">{item.start_line}</span>
                  <span className="whitespace-pre-wrap break-all text-slate-900">{item.text}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {metadata.length > 0 && (
        <div className="mt-4">
          <div className="text-lg font-bold text-slate-900">Metadata</div>
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            {metadata.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-semibold text-slate-600">{key}</dt>
                <dd className="break-all font-mono text-slate-900">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}