// Blast radius: everything that depends, directly or through others, on one
// node. It follows the documented edge direction only (A -> B means B depends
// on A, docs/api.md), with the same breadth-first walk as the backend's
// `descendants` (backend/app/analysis/reachability.py); it assigns no new
// meaning to the graph.

import type { AnalysisResult, GraphEdge } from './types';
import { edgeKey } from './analysis';

export interface Affected {
  id: string;
  /** 1 = depends on the source directly, 2 = through one other node, ... */
  depth: number;
  /** The edge through which it was first reached (shortest path). */
  via: GraphEdge;
}

export interface BlastRadius {
  source: string;
  /** In breadth-first order: by depth, then by node id. */
  affected: Affected[];
  /** Node id -> depth, for the graph colouring. */
  depthOf: ReadonlyMap<string, number>;
  /** Keys of the edges on the shortest paths from the source. */
  edges: ReadonlySet<string>;
}

export function blastRadius(result: AnalysisResult, source: string): BlastRadius {
  const outgoing = new Map<string, GraphEdge[]>();
  for (const edge of result.graph.edges) {
    if (edge.source === edge.target) continue;
    const list = outgoing.get(edge.source) ?? [];
    list.push(edge);
    outgoing.set(edge.source, list);
  }
  for (const list of outgoing.values()) {
    list.sort((a, b) => (a.target < b.target ? -1 : a.target > b.target ? 1 : 0));
  }

  const depthOf = new Map<string, number>([[source, 0]]);
  const affected: Affected[] = [];
  const edges = new Set<string>();
  let frontier = [source];
  for (let depth = 1; frontier.length > 0; depth++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const edge of outgoing.get(id) ?? []) {
        if (depthOf.has(edge.target)) continue;
        depthOf.set(edge.target, depth);
        affected.push({ id: edge.target, depth, via: edge });
        edges.add(edgeKey(edge));
        next.push(edge.target);
      }
    }
    frontier = next.sort();
  }
  depthOf.delete(source);
  affected.sort((a, b) => a.depth - b.depth || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return { source, affected, depthOf, edges };
}
