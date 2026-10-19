import { useMemo } from 'react';
import { ReactFlow, Background, Controls, MarkerType, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import type { AnalysisResult, GraphEdge } from '../types';

const W = 200;
const H = 44;
const RED = '#ef4444';

// Finds which nodes and edges sit on a loop (strongly connected components).
function findCycles(nodeIds: string[], edges: GraphEdge[]) {
  const adj = new Map<string, string[]>();
  nodeIds.forEach(id => adj.set(id, []));
  edges.forEach(e => adj.get(e.source)?.push(e.target));

  let counter = 0;
  const idx = new Map<string, number>();
  const low = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const comp = new Map<string, number>();
  let compCount = 0;

  function visit(v: string) {
    idx.set(v, counter);
    low.set(v, counter);
    counter++;
    stack.push(v);
    onStack.add(v);
    for (const w of adj.get(v) ?? []) {
      if (!idx.has(w)) {
        visit(w);
        low.set(v, Math.min(low.get(v)!, low.get(w)!));
      } else if (onStack.has(w)) {
        low.set(v, Math.min(low.get(v)!, idx.get(w)!));
      }
    }
    if (low.get(v) === idx.get(v)) {
      let w: string;
      do {
        w = stack.pop()!;
        onStack.delete(w);
        comp.set(w, compCount);
      } while (w !== v);
      compCount++;
    }
  }
  nodeIds.forEach(id => {
    if (!idx.has(id)) visit(id);
  });

  const size = new Map<number, number>();
  comp.forEach(c => size.set(c, (size.get(c) ?? 0) + 1));

  const selfLoops = new Set(edges.filter(e => e.source === e.target).map(e => e.source));
  const inLoop = (id: string) => (size.get(comp.get(id)!) ?? 0) > 1;

  const cyclicNodes = new Set(nodeIds.filter(id => inLoop(id) || selfLoops.has(id)));
  const isCyclicEdge = (e: GraphEdge) =>
    e.source !== e.target && inLoop(e.source) && comp.get(e.source) === comp.get(e.target);

  return { cyclicNodes, selfLoops, isCyclicEdge };
}

export default function DependencyGraph({ result }: { result: AnalysisResult }) {
  const { nodes, edges, hasCycle } = useMemo(() => {
    const graph = result.graph ?? { nodes: [], edges: [] };
    const flagged = new Set(result.recommendations.flatMap(r => r.related_node_ids));
    const { cyclicNodes, selfLoops, isCyclicEdge } = findCycles(
      graph.nodes.map(n => n.id),
      graph.edges,
    );

    // A line from a box back to itself can't be drawn, so those are shown as a tag on the box.
    const drawable = graph.edges.filter(e => e.source !== e.target);

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 110 });
    g.setDefaultEdgeLabel(() => ({}));
    graph.nodes.forEach(n => g.setNode(n.id, { width: W, height: H }));
    drawable.forEach(e => g.setEdge(e.source, e.target));
    dagre.layout(g);

    const nodes: Node[] = graph.nodes.map(n => {
      const p = g.node(n.id);
      const bad = flagged.has(n.id) || cyclicNodes.has(n.id);
      return {
        id: n.id,
        data: { label: selfLoops.has(n.id) ? `${n.label}  ↻ self` : n.label },
        position: { x: p.x - W / 2, y: p.y - H / 2 },
        style: {
          width: W,
          fontSize: 12,
          border: `2px solid ${bad ? RED : '#94a3b8'}`,
          background: bad ? '#fef2f2' : '#ffffff',
        },
      };
    });

    const edges: Edge[] = drawable.map(e => {
      const cyc = isCyclicEdge(e);
      return {
        id: `${e.source}->${e.target}:${e.type}`,
        source: e.source,
        target: e.target,
        label: e.label ?? undefined,
        animated: cyc,
        style: cyc ? { stroke: RED, strokeWidth: 2 } : undefined,
        labelStyle: { fontSize: 10 },
        markerEnd: { type: MarkerType.ArrowClosed, color: cyc ? RED : undefined },
      };
    });

    return { nodes, edges, hasCycle: cyclicNodes.size > 0 };
  }, [result]);

  const order = result.execution_order;

  return (
    <div className="mt-4">
      <div className="h-80 overflow-hidden rounded-lg border border-slate-200">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      {hasCycle && (
        <p className="mt-2 text-xs text-red-600">
          Red items are part of a dependency cycle. ↻ means a resource depends on itself.
        </p>
      )}

      <div className="mt-3 text-sm">
        <div className="font-semibold text-slate-900">Execution order</div>
        {order ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {order.map((step, i) => (
              <div key={step} className="flex items-center gap-2">
                <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                  {i + 1}. {step}
                </span>
                {i < order.length - 1 && <span className="text-slate-400">→</span>}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-slate-500">
            Not available. Fix the issues below first, then analyze again.
          </p>
        )}
      </div>
    </div>
  );
}