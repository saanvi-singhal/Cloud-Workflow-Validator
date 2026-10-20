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
  EDGE_TYPE_LABELS,
  cycleHighlights,
  edgeKey,
  executionOrderNote,
  labelFor,
  nodeSeverities,
} from '../analysis';

const MIN_W = 200;
const H = 48;
const EDGE = '#64748b';

// Approximate size of the graph panel, used only to choose a layout direction.
const PANEL = { width: 520, height: 448 };

type Direction = 'LR' | 'TB';

function layout(
  nodes: AnalysisResult['graph']['nodes'],
  edges: AnalysisResult['graph']['edges'],
  rankdir: Direction,
) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir, nodesep: rankdir === 'LR' ? 50 : 40, ranksep: rankdir === 'LR' ? 110 : 70 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach(n => g.setNode(n.id, { width: nodeWidth(n.label), height: H }));
  edges.forEach(e => g.setEdge(e.source, e.target)); // source -> target, never reversed
  dagre.layout(g);
  const { width = 1, height = 1 } = g.graph();
  // How large the graph can be drawn when fitted into the panel.
  return { g, rankdir, scale: Math.min(PANEL.width / width, PANEL.height / height) };
}

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
const HIGHLIGHT = '0 0 0 3px rgba(99, 102, 241, 0.65)';

// Typed edge styling (spec 8.3): explicit dependencies are dashed so they stand
// out from references Terraform infers.
const EDGE_DASH: Record<string, string | undefined> = {
  terraform_explicit_dependency: '6 4',
  docker_instruction_order: '2 4',
};

const NODE_NOUN: Record<AnalysisResult['format'], string> = {
  yaml: 'workflow jobs',
  dockerfile: 'build stages',
  terraform: 'Terraform blocks',
};

interface Props {
  result: AnalysisResult;
  /** Nodes to ring, e.g. the selected node or a clicked diagnostic's nodes. */
  highlighted: ReadonlySet<string>;
  onSelectNode: (id: string | null) => void;
}

export default function DependencyGraph({ result, highlighted, onSelectNode }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [flow, setFlow] = useState<ReactFlowInstance | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Track fullscreen changes from the button and from Esc, and re-fit the graph to the new size.
  useEffect(() => {
    function onChange() {
      setIsFullscreen(document.fullscreenElement === containerRef.current);
      requestAnimationFrame(() => flow?.fitView({ padding: 0.15 }));
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

  // Layout depends only on the result, so selecting a node does not re-run it.
  const { g, rankdir, drawable } = useMemo(() => {
    // A line from a box back to itself can't be drawn, so those are shown as a tag on the box.
    const drawable = result.graph.edges.filter(e => e.source !== e.target);
    // Long chains read best left to right, wide fan-outs top to bottom; use
    // whichever layout can be drawn larger in the panel.
    const horizontal = layout(result.graph.nodes, drawable, 'LR');
    const vertical = layout(result.graph.nodes, drawable, 'TB');
    const chosen = vertical.scale > horizontal.scale * 1.1 ? vertical : horizontal;
    return { ...chosen, drawable };
  }, [result]);

  const { nodes, edges, hasCycle, severitiesShown, edgeTypes } = useMemo(() => {
    // Cycle membership and severities come from the backend's diagnostics and
    // recommendations; the frontend does not re-analyse the graph.
    const severities = nodeSeverities(result);
    const cycles = cycleHighlights(result);

    const nodes: Node[] = result.graph.nodes.map(n => {
      const p = g.node(n.id);
      const colors = NODE_COLORS[severities.get(n.id) ?? 'none'];
      const width = nodeWidth(n.label);
      return {
        id: n.id,
        data: {
          label: (
            <div className="leading-tight">
              <div className="text-[9px] uppercase tracking-wide text-slate-400">{n.type}</div>
              <div>{cycles.selfLoops.has(n.id) ? `${n.label}  ↻ self` : n.label}</div>
            </div>
          ),
        },
        position: { x: p.x - width / 2, y: p.y - H / 2 },
        // Edges leave in the layout direction and enter from the opposite side.
        sourcePosition: rankdir === 'LR' ? Position.Right : Position.Bottom,
        targetPosition: rankdir === 'LR' ? Position.Left : Position.Top,
        style: {
          width,
          fontSize: 12,
          padding: '4px 8px',
          cursor: 'pointer',
          border: `2px solid ${colors.border}`,
          background: colors.background,
          boxShadow: highlighted.has(n.id) ? HIGHLIGHT : undefined,
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
        style: {
          stroke: onCycle ? CYCLE_EDGE : EDGE,
          strokeWidth: onCycle ? 2 : 1.5,
          strokeDasharray: EDGE_DASH[e.type],
        },
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
      edgeTypes: [...new Set(drawable.map(e => e.type))].sort(),
    };
  }, [result, g, rankdir, drawable, highlighted]);

  const graphEmpty = result.graph.nodes.length === 0;
  const order = result.execution_order;
  const orderNote = executionOrderNote(result);

  return (
    <div className="mt-4">
      {graphEmpty ? (
        <div className="flex h-[28rem] flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
          <p className="font-medium text-slate-700">Nothing to draw</p>
          <p className="mt-1 max-w-sm text-sm text-slate-500">
            No {NODE_NOUN[result.format]} were found in this file, so there is no dependency graph.
            See the diagnostics below.
          </p>
        </div>
      ) : (
        <div ref={containerRef} className="h-[28rem] overflow-hidden rounded-lg border border-slate-200 bg-white">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            // Fit large graphs fully, but don't blow a single node up to fill the panel.
            fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
            minZoom={0.1}
            nodesConnectable={false}
            onInit={setFlow}
            onNodeClick={(_, node) => onSelectNode(node.id)}
            onPaneClick={() => onSelectNode(null)}
          >
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
        <p>
          Arrows point from a prerequisite to the item that depends on it. Click a box for its
          details.
        </p>
        {edgeTypes.length > 0 && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>Edges:</span>
            {edgeTypes.map(type => (
              <span key={type} className="inline-flex items-center gap-1">
                <svg width="22" height="6" aria-hidden="true">
                  <line
                    x1="0"
                    y1="3"
                    x2="22"
                    y2="3"
                    stroke={EDGE}
                    strokeWidth="1.5"
                    strokeDasharray={EDGE_DASH[type]}
                  />
                </svg>
                {EDGE_TYPE_LABELS[type] ?? type}
              </span>
            ))}
          </p>
        )}
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
