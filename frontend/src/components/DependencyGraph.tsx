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
import type { DiffHighlight } from '../graphDiff';
import type { BlastRadius } from '../blastRadius';
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

const NODE_COLORS: Record<Severity | 'none', { border: string; background: string; text: string }> = {
  error: { border: '#ef4444', background: '#fef2f2', text: '#991b1b' },
  warning: { border: '#f59e0b', background: '#fffbeb', text: '#92400e' },
  info: { border: '#0284c7', background: '#f0f9ff', text: '#0369a1' },
  none: { border: '#cbd5e1', background: '#ffffff', text: '#0f172a' },
};
const CYCLE_EDGE = '#ef4444';
const INTERFILE_EDGE = '#0284c7';
const HIGHLIGHT = '0 0 0 3px rgba(2, 132, 199, 0.45)';

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
  mixed: 'jobs, build stages or Terraform blocks',
};

interface Props {
  result: AnalysisResult;
  /** Nodes to ring, e.g. the selected node or a clicked diagnostic's nodes. */
  highlighted: ReadonlySet<string>;
  onSelectNode: (id: string | null) => void;
  /** Version comparison: colour what changed (see graphDiff.ts). */
  diff?: DiffHighlight;
  /** Blast radius of one node: colour it and everything downstream. */
  blast?: BlastRadius;
}

// Blast radius: the changed node in red, dependents warmer the closer they are.
const BLAST_SOURCE = { border: '#dc2626', background: '#fee2e2' };
const BLAST_DEPTH = [
  { border: '#ea580c', background: '#ffedd5' },
  { border: '#d97706', background: '#fef3c7' },
  { border: '#ca8a04', background: '#fefce8' },
];
const BLAST_EDGE = '#ea580c';

// Comparison colours: green = added, red = removed, orange = rewired.
const DIFF_COLORS = {
  added: { border: '#16a34a', background: '#dcfce7' },
  removed: { border: '#dc2626', background: '#fee2e2' },
  rewired: { border: '#ea580c', background: '#ffedd5' },
};

export default function DependencyGraph({
  result,
  highlighted,
  onSelectNode,
  diff,
  blast,
}: Props) {
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

  const { nodes, edges, hasCycle, hasInterFile, severitiesShown, edgeTypes } = useMemo(() => {
    // Cycle membership and severities come from the backend's diagnostics and
    // recommendations; the frontend does not re-analyse the graph.
    const severities = nodeSeverities(result);
    const cycles = cycleHighlights(result);

    const nodes: Node[] = result.graph.nodes.map(n => {
      const p = g.node(n.id);
      const depth = blast?.depthOf.get(n.id);
      const outsideBlast = blast !== undefined && depth === undefined && n.id !== blast.source;
      const colors =
        blast?.source === n.id
          ? BLAST_SOURCE
          : depth !== undefined
            ? BLAST_DEPTH[Math.min(depth, BLAST_DEPTH.length) - 1]
            : diff?.changedNodes.has(n.id)
              ? DIFF_COLORS[diff.kind]
              : diff?.rewiredNodes.has(n.id)
                ? DIFF_COLORS.rewired
                : NODE_COLORS[severities.get(n.id) ?? 'none'];
      const width = nodeWidth(n.label);
      const fileBadge = n.source_location?.file ?? (n.metadata?.file as string | undefined);
      return {
        id: n.id,
        data: {
          label: (
            <div className="leading-tight">
              <div className="flex items-center justify-between gap-1 text-[9px] uppercase tracking-wide text-slate-500 font-mono">
                <span>{n.type}</span>
                {fileBadge && (
                  <span className="max-w-[100px] truncate rounded bg-slate-100 px-1 font-mono text-[9px] lowercase text-sky-700 font-semibold border border-slate-200">
                    {fileBadge}
                  </span>
                )}
              </div>
              <div className="font-mono text-xs font-semibold text-slate-900 mt-0.5 truncate">
                {cycles.selfLoops.has(n.id) ? `${n.label}  ↻ self` : n.label}
              </div>
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
          padding: '5px 9px',
          borderRadius: 8,
          cursor: 'pointer',
          border: `1.5px solid ${colors.border}`,
          background: colors.background,
          boxShadow: highlighted.has(n.id) ? HIGHLIGHT : '0 1px 3px rgba(0,0,0,0.06)',
          opacity: outsideBlast ? 0.35 : 1,
        },
      };
    });

    let interFileCount = 0;
    const edges: Edge[] = drawable.map(e => {
      const onCycle = cycles.edges.has(edgeKey(e));
      const isInterFile = Boolean(e.metadata?.is_interfile);
      if (isInterFile) interFileCount++;

      const inBlast = blast?.edges.has(edgeKey(e)) ?? false;
      const diffEdge = inBlast
        ? BLAST_EDGE
        : diff?.changedEdges.has(edgeKey(e))
          ? DIFF_COLORS[diff.kind].border
          : null;
      const strokeColor =
        diffEdge ?? (onCycle ? CYCLE_EDGE : isInterFile ? INTERFILE_EDGE : EDGE);
      const strokeDash = onCycle ? undefined : isInterFile ? '6 3' : EDGE_DASH[e.type];

      return {
        id: edgeKey(e),
        source: e.source,
        target: e.target,
        label: isInterFile
          ? e.label
            ? `${e.label} (inter-file)`
            : 'inter-file'
          : (e.label ?? undefined),
        animated: onCycle || isInterFile || inBlast,
        style: {
          stroke: strokeColor,
          strokeWidth: diffEdge || onCycle || isInterFile ? 2 : 1.5,
          strokeDasharray: strokeDash,
          opacity: blast && !inBlast ? 0.3 : 1,
        },
        labelStyle: {
          fontSize: 10,
          fill: isInterFile ? '#0284c7' : '#475569',
          fontWeight: isInterFile ? 600 : 400,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: 18,
          height: 18,
        },
      };
    });

    return {
      nodes,
      edges,
      hasCycle: cycles.nodes.size > 0,
      hasInterFile: interFileCount > 0,
      severitiesShown: new Set(severities.values()),
      edgeTypes: [...new Set(drawable.map(e => e.type))].sort(),
    };
  }, [result, g, rankdir, drawable, highlighted, diff, blast]);

  const graphEmpty = result.graph.nodes.length === 0;
  const order = result.execution_order;
  const orderNote = executionOrderNote(result);

  return (
    <div className="mt-4">
      {graphEmpty ? (
        <div className="flex h-[28rem] flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
          <p className="font-medium text-slate-700">Nothing to draw</p>
          <p className="mt-1 max-w-sm text-sm text-slate-500">
            No {NODE_NOUN[result.format]} were found in this file, so there is no dependency graph.
            See the diagnostics below.
          </p>
        </div>
      ) : (
        <div ref={containerRef} className="h-[28rem] rounded-xl border border-slate-200 bg-white shadow-xs">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            maxZoom={1.5}
            minZoom={0.1}
            nodesConnectable={false}
            onInit={setFlow}
            onNodeClick={(_, node) => onSelectNode(node.id)}
            onPaneClick={() => onSelectNode(null)}
          >
            <Background color="#e2e8f0" gap={16} />
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
              <span key={type} className="inline-flex items-center gap-1 font-mono text-[11px] text-slate-700">
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
            {hasInterFile && (
              <span className="inline-flex items-center gap-1 font-mono text-[11px] font-medium text-sky-700">
                <svg width="22" height="6" aria-hidden="true">
                  <line
                    x1="0"
                    y1="3"
                    x2="22"
                    y2="3"
                    stroke={INTERFILE_EDGE}
                    strokeWidth="2"
                    strokeDasharray="6 3"
                  />
                </svg>
                Inter-file dependency
              </span>
            )}
          </p>
        )}
        {severitiesShown.size > 0 && (
          <p>
            Box colour shows the most severe issue linked to it:
            {severitiesShown.has('error') && <span className="ml-2 font-medium text-red-600">red = error</span>}
            {severitiesShown.has('warning') && (
              <span className="ml-2 font-medium text-amber-600">amber = warning</span>
            )}
            {severitiesShown.has('info') && <span className="ml-2 font-medium text-sky-600">blue = info</span>}
          </p>
        )}
        {blast && (
          <p className="flex flex-wrap gap-x-3 font-semibold">
            <span className="text-red-600">Red = the selected item</span>
            <span className="text-orange-600">orange to yellow = affected, nearest first</span>
            <span className="text-slate-500">faded = not affected</span>
          </p>
        )}
        {diff && (
          <p className="flex flex-wrap gap-x-3 font-semibold">
            <span className="text-green-500">Green = added</span>
            <span className="text-red-500">Red = removed</span>
            <span className="text-orange-500">Orange = rewired</span>
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
                <span className="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 font-mono text-xs font-medium text-slate-700">
                  {i + 1}. {labelFor(result, id)}
                </span>
                {i < order.length - 1 && <span className="text-slate-400">→</span>}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-slate-500 text-xs">{orderNote}</p>
        )}
      </div>
    </div>
  );
}
