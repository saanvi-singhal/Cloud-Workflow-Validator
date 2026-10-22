import type { AnalysisResult, GraphNode } from '../types';
import { EDGE_TYPE_LABELS, isPartial, labelFor } from '../analysis';
import type { BlastRadius } from '../blastRadius';

// What "depends on it" means for each format, in the user's terms.
const DEPENDENTS: Record<AnalysisResult['format'], string> = {
  terraform: 'blocks that reference it or list it in depends_on',
  yaml: 'jobs that wait for it through needs',
  dockerfile: 'stages built FROM it or copying from it',
  mixed: 'items that depend on it',
};

interface Props {
  result: AnalysisResult;
  node: GraphNode;
  blast: BlastRadius;
  shown: boolean;
  onToggle: () => void;
  onSelectNode: (id: string) => void;
}

/** "Click a node, see what breaks": everything downstream of the node. */
export default function BlastRadiusPanel({ result, node, blast, shown, onToggle, onSelectNode }: Props) {
  const byDepth = new Map<number, typeof blast.affected>();
  for (const item of blast.affected) {
    byDepth.set(item.depth, [...(byDepth.get(item.depth) ?? []), item]);
  }
  const direct = byDepth.get(1)?.length ?? 0;
  const total = blast.affected.length;

  return (
    <section aria-label="Blast radius" className="mt-3 rounded-lg border border-orange-200 bg-orange-50/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold text-ink">Blast radius</div>
        {total > 0 && (
          <button
            type="button"
            onClick={onToggle}
            className="rounded border border-orange-300 bg-surface px-2 py-0.5 text-xs font-medium text-orange-800 hover:bg-orange-100"
          >
            {shown ? 'Hide on graph' : 'Show on graph'}
          </button>
        )}
      </div>

      {total === 0 ? (
        <p className="mt-1 text-xs text-muted">
          Nothing in this graph depends on {node.label}, so changing or removing it affects
          nothing else here.
        </p>
      ) : (
        <>
          <p className="mt-1 text-xs text-muted">
            Changing or removing <span className="font-semibold">{node.label}</span> affects{' '}
            <span className="font-semibold">
              {total} {total === 1 ? 'item' : 'items'}
            </span>
            : {direct} directly
            {total > direct ? `, ${total - direct} through other items` : ''} ({DEPENDENTS[result.format]}).
          </p>
          {[...byDepth].map(([depth, items]) => (
            <div key={depth} className="mt-2">
              <div className="text-[11px] font-semibold text-orange-800">
                {depth === 1 ? 'Directly' : `${depth} steps away`} ({items.length})
              </div>
              <ul className="mt-0.5 space-y-0.5 text-xs">
                {items.map(item => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => onSelectNode(item.id)}
                      className="text-left font-mono text-ink hover:underline"
                    >
                      {labelFor(result, item.id)}
                    </button>
                    <span className="text-faint">
                      {' '}
                      via {labelFor(result, item.via.source)}
                      {item.via.label
                        ? ` (${item.via.label})`
                        : ` (${EDGE_TYPE_LABELS[item.via.type] ?? item.via.type})`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}

      {isPartial(result) && (
        <p className="mt-2 text-xs text-warning">
          The analysis is partial, so some dependents may be missing from this list.
        </p>
      )}
    </section>
  );
}
