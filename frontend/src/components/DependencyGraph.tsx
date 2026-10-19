import { useMemo } from 'react';
import { ReactFlow, Background, Controls, MarkerType, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import type { AnalysisResult, Severity } from '../types';
import {
  cycleHighlights,
  edgeKey,
  executionOrderNote,
  labelFor,
  nodeSeverities,
} from '../analysis';

const W = 200;
const H = 44;

const NODE_COLORS: Record<Severity | 'none', { border: string; background: string }> = {
  error: { border: '#ef4444', background: '#fef2f2' },
  warning: { border: '#f59e0b', background: '#fffbeb' },
  info: { border: '#0ea5e9', background: '#f0f9ff' },
  none: { border: '#94a3b8', background: '#ffffff' },
};
const CYCLE_EDGE = '#ef4444';

export default function DependencyGraph({ result }: { result: AnalysisResult }) {
  const { nodes, edges, hasCycle, severitiesShown } = useMemo(() => {
    const graph = result.graph;
    // Cycle membership and severities come from the backend's diagnostics and
    // recommendations; the frontend does not re-analyse the graph.
    const severities = nodeSeverities(result);
    const cycles = cycleHighlights(result);

    // A line from a box back to itself can't be drawn, so those are shown as a tag on the box.
    const drawable = graph.edges.filter(e => e.source !== e.target);

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 110 });
    g.setDefaultEdgeLabel(() => ({}));
    graph.nodes.forEach(n => g.setNode(n.id, { width: W, height: H }));
    drawable.forEach(e => g.setEdge(e.source, e.target)); // source -> target, never reversed
    dagre.layout(g);

    const nodes: Node[] = graph.nodes.map(n => {
      const p = g.node(n.id);
      const colors = NODE_COLORS[severities.get(n.id) ?? 'none'];
      return {
        id: n.id,
        data: { label: cycles.selfLoops.has(n.id) ? `${n.label}  ↻ self` : n.label },
        position: { x: p.x - W / 2, y: p.y - H / 2 },
        style: {
          width: W,
          fontSize: 12,
          border: `2px solid ${colors.border}`,
          background: colors.background,
        },
      };
    });

    const edges: Edge[] = drawable.map(e => {
      const onCycle = cycles.edges.has(edgeKey(e));
      return {
        id: edgeKey(e),
        source: e.source,
        target: e.target,
        label: e.label ?? undefined,
        animated: onCycle,
        style: onCycle ? { stroke: CYCLE_EDGE, strokeWidth: 2 } : undefined,
        labelStyle: { fontSize: 10 },
        markerEnd: { type: MarkerType.ArrowClosed, color: onCycle ? CYCLE_EDGE : undefined },
      };
    });

    return {
      nodes,
      edges,
      hasCycle: cycles.nodes.size > 0,
      severitiesShown: new Set(severities.values()),
    };
  }, [result]);

  const order = result.execution_order;
  const orderNote = executionOrderNote(result);

  return (
    <div className="mt-4">
      <div className="h-80 overflow-hidden rounded-lg border border-slate-200">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <div className="mt-2 space-y-1 text-xs text-slate-600">
        <p>Arrows point from a prerequisite to the item that depends on it.</p>
        {severitiesShown.size > 0 && (
          <p>
            Box colour shows the most severe issue linked to it:
            {severitiesShown.has('error') && <span className="ml-2 text-red-600">red = error</span>}
            {severitiesShown.has('warning') && (
              <span className="ml-2 text-amber-600">amber = warning</span>
            )}
            {severitiesShown.has('info') && <span className="ml-2 text-sky-600">blue = info</span>}
          </p>
        )}
        {hasCycle && (
          <p className="text-red-600">
            Animated red arrows form a dependency cycle. ↻ means an item depends on itself.
          </p>
        )}
      </div>

      <div className="mt-3 text-sm">
        <div className="font-semibold text-slate-900">Execution order</div>
        {order ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {order.map((id, i) => (
              <div key={id} className="flex items-center gap-2">
                <span className="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                  {i + 1}. {labelFor(result, id)}
                </span>
                {i < order.length - 1 && <span className="text-slate-400">→</span>}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-slate-500">{orderNote}</p>
        )}
      </div>
    </div>
  );
}
