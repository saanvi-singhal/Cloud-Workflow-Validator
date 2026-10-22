import type { AnalysisResult, GraphNode, SourceLocation } from '../types';
import {
  formatLocation,
  metadataEntries,
  nodeDiagnostics,
  stageInstructions,
} from '../analysis';

const SEVERITY_TEXT = {
  error: 'text-rose-400',
  warning: 'text-amber-400',
  info: 'text-sky-400',
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
    file: node.source_location?.file ?? null,
    start_line: start,
    start_column: null,
    end_line: end,
    end_column: null,
  });

  const interEdges = result.graph.edges.filter(
    e => (e.source === node.id || e.target === node.id) && Boolean(e.metadata?.is_interfile)
  );

  return (
    <section className="mt-4 rounded-xl border border-sky-500/30 bg-slate-900/90 p-4 text-sm text-slate-200 shadow-xl backdrop-blur-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-sky-400">
              {node.type}
            </span>
            {node.source_location?.file && (
              <span className="rounded border border-sky-500/30 bg-sky-950/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-sky-300">
                {node.source_location.file}
              </span>
            )}
          </div>
          <h3 className="break-all font-mono font-semibold text-white mt-1">{node.label}</h3>
          <div className="break-all font-mono text-xs text-sky-400/70">{node.id}</div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded border border-slate-700 bg-slate-800 px-2.5 py-1 font-mono text-xs text-slate-300 hover:border-slate-500 hover:text-white transition-colors"
          aria-label="Close node details"
        >
          Close
        </button>
      </div>

      {where && (
        <button
          onClick={() => onJump(node.source_location)}
          className="mt-2 text-xs font-mono font-medium text-cyan-400 hover:underline"
        >
          Defined at {where}
        </button>
      )}

      {interEdges.length > 0 && (
        <div className="mt-3">
          <div className="font-mono text-xs uppercase tracking-wider text-sky-400 font-semibold">Inter-file Dependencies</div>
          <ul className="mt-1 space-y-1 text-xs">
            {interEdges.map((e, idx) => {
              const isSource = e.source === node.id;
              const otherNodeId = isSource ? e.target : e.source;
              const otherNode = result.graph.nodes.find(n => n.id === otherNodeId);
              const otherFile = isSource
                ? (e.metadata?.target_file as string)
                : (e.metadata?.source_file as string);
              return (
                <li key={idx} className="flex items-center gap-1.5 text-slate-300">
                  <span className="font-semibold text-cyan-400 font-mono">
                    {isSource ? 'Required by:' : 'Prerequisite from:'}
                  </span>
                  <span className="font-mono text-sky-200">{otherFile ?? 'other file'}</span>
                  <span className="text-slate-400 font-mono">({otherNode?.label ?? otherNodeId})</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {issues.length > 0 && (
        <div className="mt-3">
          <div className="font-mono text-xs uppercase tracking-wider text-amber-400 font-semibold">Issues</div>
          <ul className="mt-1 space-y-1">
            {issues.map(({ index, diagnostic }) => (
              <li key={index}>
                <button
                  onClick={() => onSelectDiagnostic(index)}
                  className="text-left hover:underline"
                >
                  <span className={`font-mono font-semibold ${SEVERITY_TEXT[diagnostic.severity]}`}>
                    {diagnostic.severity.toUpperCase()}
                  </span>{' '}
                  <span className="text-slate-200">{diagnostic.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {instructions.length > 0 && (
        <div className="mt-3">
          <div className="font-mono text-xs uppercase tracking-wider text-sky-400 font-semibold">Instructions</div>
          <ol className="mt-1 overflow-hidden rounded-lg border border-slate-800 bg-slate-950 font-mono text-xs">
            {instructions.map(item => (
              <li key={item.start_line} className="border-b border-slate-800/80 last:border-0">
                <button
                  onClick={() => onJump(lineLocation(item.start_line, item.end_line))}
                  className="flex w-full gap-3 px-2.5 py-1.5 text-left hover:bg-slate-900 transition-colors"
                  title="Show in editor"
                >
                  <span className="w-8 shrink-0 text-right text-slate-500">{item.start_line}</span>
                  <span className="whitespace-pre-wrap break-all text-sky-100">{item.text}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {metadata.length > 0 && (
        <div className="mt-3">
          <div className="font-mono text-xs uppercase tracking-wider text-sky-400 font-semibold">Metadata</div>
          <dl className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
            {metadata.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="font-mono text-slate-400">{k}</dt>
                <dd className="font-mono text-sky-200 truncate">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
