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
    <section className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50/40 p-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-indigo-600">
            {node.type}
          </div>
          <h3 className="break-all font-semibold text-slate-900">{node.label}</h3>
          <div className="break-all font-mono text-xs text-slate-500">{node.id}</div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-xs text-slate-500 hover:text-slate-800"
          aria-label="Close node details"
        >
          Close
        </button>
      </div>

      {where && (
        <button
          onClick={() => onJump(node.source_location)}
          className="mt-2 text-xs font-medium text-indigo-600 hover:underline"
        >
          Defined at {where}
        </button>
      )}

      {issues.length > 0 && (
        <div className="mt-3">
          <div className="font-medium text-slate-800">Issues</div>
          <ul className="mt-1 space-y-1">
            {issues.map(({ index, diagnostic }) => (
              <li key={index}>
                <button
                  onClick={() => onSelectDiagnostic(index)}
                  className="text-left hover:underline"
                >
                  <span className={`font-semibold ${SEVERITY_TEXT[diagnostic.severity]}`}>
                    {diagnostic.severity.toUpperCase()}
                  </span>{' '}
                  <span className="text-slate-700">{diagnostic.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {instructions.length > 0 && (
        <div className="mt-3">
          <div className="font-medium text-slate-800">Instructions</div>
          <ol className="mt-1 overflow-hidden rounded border border-slate-200 bg-white font-mono text-xs">
            {instructions.map(item => (
              <li key={item.start_line} className="border-b border-slate-100 last:border-0">
                <button
                  onClick={() => onJump(lineLocation(item.start_line, item.end_line))}
                  className="flex w-full gap-3 px-2 py-1 text-left hover:bg-indigo-50"
                  title="Show in editor"
                >
                  <span className="w-8 shrink-0 text-right text-slate-400">{item.start_line}</span>
                  <span className="whitespace-pre-wrap break-all text-slate-800">{item.text}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {metadata.length > 0 && (
        <div className="mt-3">
          <div className="font-medium text-slate-800">Metadata</div>
          <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
            {metadata.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-slate-500">{key}</dt>
                <dd className="break-all font-mono text-slate-800">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
