import type { AnalysisResult, GraphNode, SourceLocation } from '../types';
import {
  formatLocation,
  metadataEntries,
  nodeDiagnostics,
  stageInstructions,
} from '../analysis';
import type { BlastRadius } from '../blastRadius';
import BlastRadiusPanel from './BlastRadiusPanel';

const SEVERITY_TEXT = {
  error: 'text-error',
  warning: 'text-warning',
  info: 'text-accent-strong',
} as const;

interface Props {
  result: AnalysisResult;
  node: GraphNode;
  onJump: (location: SourceLocation | null) => void;
  onSelectDiagnostic: (index: number) => void;
  onClose: () => void;
  /** Everything downstream of this node (see blastRadius.ts). */
  blast?: BlastRadius;
  blastShown?: boolean;
  onToggleBlast?: () => void;
  onSelectNode?: (id: string) => void;
}

// Details for the selected graph node (spec 8.2 step 7): its metadata, linked
// diagnostics and, for Dockerfile stages, the ordered instructions.
export default function NodeDetails({
  result,
  node,
  onJump,
  onSelectDiagnostic,
  onClose,
  blast,
  blastShown = false,
  onToggleBlast = () => {},
  onSelectNode = () => {},
}: Props) {
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
    <section className="mt-4 rounded-xl border border-line bg-accent-soft/40 p-4 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-accent-strong">
              {node.type}
            </span>
            {node.source_location?.file && (
              <span className="rounded bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent-strong">
                {node.source_location.file}
              </span>
            )}
          </div>
          <h3 className="break-all font-semibold text-ink mt-1">{node.label}</h3>
          <div className="break-all font-mono text-xs text-faint">{node.id}</div>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded border border-line bg-surface px-2.5 py-1 text-xs font-medium text-muted hover:bg-paper hover:text-ink transition-colors "
          aria-label="Close node details"
        >
          Close
        </button>
      </div>

      {where && (
        <button
          onClick={() => onJump(node.source_location)}
          className="mt-2 text-xs font-medium text-accent-strong hover:underline"
        >
          Defined at {where}
        </button>
      )}

      {blast && (
        <BlastRadiusPanel
          result={result}
          node={node}
          blast={blast}
          shown={blastShown}
          onToggle={onToggleBlast}
          onSelectNode={onSelectNode}
        />
      )}

      {interEdges.length > 0 && (
        <div className="mt-3">
          <div className="font-semibold text-ink text-xs">Inter-file Dependencies</div>
          <ul className="mt-1 space-y-1 text-xs">
            {interEdges.map((e, idx) => {
              const isSource = e.source === node.id;
              const otherNodeId = isSource ? e.target : e.source;
              const otherNode = result.graph.nodes.find(n => n.id === otherNodeId);
              const otherFile = isSource
                ? (e.metadata?.target_file as string)
                : (e.metadata?.source_file as string);
              return (
                <li key={idx} className="flex items-center gap-1.5 text-muted">
                  <span className="font-semibold text-accent-strong">
                    {isSource ? 'Required by:' : 'Prerequisite from:'}
                  </span>
                  <span className="font-mono text-ink font-medium">{otherFile ?? 'other file'}</span>
                  <span className="text-faint">({otherNode?.label ?? otherNodeId})</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {issues.length > 0 && (
        <div className="mt-3">
          <div className="font-semibold text-ink">Issues</div>
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
                  <span className="text-muted">{diagnostic.message}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {instructions.length > 0 && (
        <div className="mt-3">
          <div className="font-semibold text-ink">Instructions</div>
          <ol className="mt-1 overflow-hidden rounded-lg border border-line bg-surface font-mono text-xs ">
            {instructions.map(item => (
              <li key={item.start_line} className="border-b border-line-soft last:border-0">
                <button
                  onClick={() => onJump(lineLocation(item.start_line, item.end_line))}
                  className="flex w-full gap-3 px-2.5 py-1.5 text-left hover:bg-accent-soft transition-colors"
                  title="Show in editor"
                >
                  <span className="w-8 shrink-0 text-right text-faint">{item.start_line}</span>
                  <span className="whitespace-pre-wrap break-all text-ink">{item.text}</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {metadata.length > 0 && (
        <div className="mt-3">
          <div className="font-semibold text-ink">Metadata</div>
          <dl className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
            {metadata.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="font-mono text-faint">{k}</dt>
                <dd className="font-mono text-ink truncate">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
