import type { AnalysisResult, Diagnostic, GraphEdge } from './types';

// Edges have no id, so they are keyed as documented in docs/api.md.
export function diffEdgeKey(e: Pick<GraphEdge, 'source' | 'target' | 'type'>): string {
  return `${e.source}->${e.target}:${e.type}`;
}

export interface GraphDiff {
  /** Node ids that exist only in the new version. */
  addedNodes: string[];
  /** Node ids that exist only in the old version. */
  removedNodes: string[];
  /** Edge keys that exist only in the new version. */
  addedEdges: string[];
  /** Edge keys that exist only in the old version. */
  removedEdges: string[];
  /**
   * Nodes present in both versions whose dependencies changed between nodes
   * that also exist in both versions (a rewire, not just an addition or removal).
   */
  rewiredNodes: string[];
  /** Cycle diagnostics in the new version that the old version did not have. */
  newCycles: Diagnostic[];
  /** Cycle diagnostics in the old version that the new version no longer has. */
  resolvedCycles: Diagnostic[];
  /** True when the two graphs have the same nodes and edges. */
  identical: boolean;
}

const CYCLE_CODE = 'DEPENDENCY_CYCLE';

function onlyIn<T>(a: Set<T>, b: Set<T>): T[] {
  return [...a].filter(x => !b.has(x)).sort();
}

export function diffResults(oldResult: AnalysisResult, newResult: AnalysisResult): GraphDiff {
  const oldNodes = new Set(oldResult.graph.nodes.map(n => n.id));
  const newNodes = new Set(newResult.graph.nodes.map(n => n.id));
  const oldEdges = new Map(oldResult.graph.edges.map(e => [diffEdgeKey(e), e]));
  const newEdges = new Map(newResult.graph.edges.map(e => [diffEdgeKey(e), e]));

  const addedNodes = onlyIn(newNodes, oldNodes);
  const removedNodes = onlyIn(oldNodes, newNodes);
  const addedEdges = onlyIn(new Set(newEdges.keys()), new Set(oldEdges.keys()));
  const removedEdges = onlyIn(new Set(oldEdges.keys()), new Set(newEdges.keys()));

  // A rewire is an edge that changed between two nodes that both exist in both
  // versions. The dependent (the edge's target) is the node that was rewired.
  const inBoth = (id: string) => oldNodes.has(id) && newNodes.has(id);
  const rewired = new Set<string>();
  for (const key of addedEdges) {
    const e = newEdges.get(key)!;
    if (inBoth(e.source) && inBoth(e.target)) rewired.add(e.target);
  }
  for (const key of removedEdges) {
    const e = oldEdges.get(key)!;
    if (inBoth(e.source) && inBoth(e.target)) rewired.add(e.target);
  }

  const cycles = (r: AnalysisResult) => r.diagnostics.filter(d => d.code === CYCLE_CODE);
  const oldCycles = cycles(oldResult);
  const newCycleList = cycles(newResult);
  const oldCycleMessages = new Set(oldCycles.map(d => d.message));
  const newCycleMessages = new Set(newCycleList.map(d => d.message));

  const newCycles = newCycleList.filter(d => !oldCycleMessages.has(d.message));
  const resolvedCycles = oldCycles.filter(d => !newCycleMessages.has(d.message));

  return {
    addedNodes,
    removedNodes,
    addedEdges,
    removedEdges,
    rewiredNodes: [...rewired].sort(),
    newCycles,
    resolvedCycles,
    identical:
      addedNodes.length === 0 &&
      removedNodes.length === 0 &&
      addedEdges.length === 0 &&
      removedEdges.length === 0,
  };
}
/** What one side of a comparison highlights in its DependencyGraph. */
export interface DiffHighlight {
  /** Nodes only on this side: added (new version) or removed (old version). */
  changedNodes: ReadonlySet<string>;
  /** Edge keys only on this side. */
  changedEdges: ReadonlySet<string>;
  rewiredNodes: ReadonlySet<string>;
  kind: 'added' | 'removed';
}

export function highlightFor(diff: GraphDiff, side: 'old' | 'new'): DiffHighlight {
  return side === 'new'
    ? {
        changedNodes: new Set(diff.addedNodes),
        changedEdges: new Set(diff.addedEdges),
        rewiredNodes: new Set(diff.rewiredNodes),
        kind: 'added',
      }
    : {
        changedNodes: new Set(diff.removedNodes),
        changedEdges: new Set(diff.removedEdges),
        rewiredNodes: new Set(diff.rewiredNodes),
        kind: 'removed',
      };
}
