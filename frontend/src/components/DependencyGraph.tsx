import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  ControlButton,
  Controls,
  MarkerType,
  Position,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react';
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

const MIN_W = 200;
const H = 44;
const EDGE = '#64748b';

// Wide enough for the label (12px text is roughly 7px per character), so long
// Terraform addresses are not cut off.
function nodeWidth(label: string): number {
  return Math.max(MIN_W, Math.ceil(label.length * 7.2) + 32);
}

const NODE_COLORS: Record<Severity | 'none', { border: string; background: string }> = {
  error: { border: '#ef4444', background: '#fef2f2' },
  warning: { border: '#f59e0b', background: '#fffbeb' },
  info: { border: '#0ea5e9', background: '#f0f9ff' },
  none: { border: '#94a3b8', background: '#ffffff' },
};
const CYCLE_EDGE = '#ef4444';

const NODE_NOUN: Record<AnalysisResult['format'], string> = {
  yaml: 'workflow jobs',
  dockerfile: 'build stages',
  terraform: 'Terraform blocks',
};

export default function DependencyGraph({ result }: { result: AnalysisResult }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Track fullscreen changes from the button and from Esc, and re-fit the graph to the new size.
  useEffect(() => {
    function onChange() {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
      requestAnimationFrame(() => flow?.fitView());
    }
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, [flow]);

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void containerRef.current?.requestFullscreen();
    }
  }

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
    graph.nodes.forEach(n => g.setNode(n.id, { width: nodeWidth(n.label), height: H }));
    drawable.forEach(e => g.setEdge(e.source, e.target)); // source -> target, never reversed
    dagre.layout(g);

    const nodes: Node[] = graph.nodes.map(n => {
      const p = g.node(n.id);
      const colors = NODE_COLORS[severities.get(n.id) ?? 'none'];
      const width = nodeWidth(n.label);
      return {
        id: n.id,
        data: { label: cycles.selfLoops.has(n.id) ? `${n.label}  ↻ self` : n.label },
        position: { x: p.x - width / 2, y: p.y - H / 2 },
        // The layout runs left to right, so edges leave on the right and enter on the left.
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        style: {
          width,
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
        style: { stroke: onCycle ? CYCLE_EDGE : EDGE, strokeWidth: onCycle ? 2 : 1.5 },
        labelStyle: { fontSize: 10 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: onCycle ? CYCLE_EDGE : EDGE,
          width: 18,
          height: 18,
        },
      };
    });

    return {
      nodes,
      edges,
      hasCycle: cycles.nodes.size > 0,
      severitiesShown: new Set(severities.values()),
    };
  }, [result]);

  const graphEmpty = result.graph.nodes.length === 0;
  const order = result.execution_order;
  const orderNote = executionOrderNote(result);

  return (
    <div className="mt-4">
      {graphEmpty ? (
        <div className="flex h-80 flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
          <p className="font-medium text-slate-700">Nothing to draw</p>
          <p className="mt-1 max-w-sm text-sm text-slate-500">
            No {NODE_NOUN[result.format]} were found in this file, so there is no dependency graph.
            See the diagnostics below.
          </p>
        </div>
      ) : (
        <div ref={containerRef} className="h-80 overflow-hidden rounded-lg border border-slate-200 bg-white">
          <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false} onInit={setFlow}>
            <Background />
            <Controls showInteractive={false}>
              <ControlButton
                onClick={toggleFullscreen}
                title={isFullscreen ? 'Exit full screen' : 'Full screen'}
                aria-label={isFullscreen ? 'Exit full screen' : 'Full screen'}
              >
                {/* React Flow's stylesheet fills control icons; this one is an outline. */}
                <svg viewBox="0 0 24 24" style={{ fill: 'none' }} stroke="currentColor" strokeWidth="2.5">
                  {isFullscreen ? (
                    <path d="M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6" />
                  ) : (
                    <path d="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6" />
                  )}
                </svg>
              </ControlButton>
            </Controls>
          </ReactFlow>
        </div>
      )}

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
