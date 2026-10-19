import { useMemo } from 'react';
import { ReactFlow, Background, Controls, MarkerType, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from '@dagrejs/dagre';
import type { AnalysisResult } from '../types';

const W = 190;
const H = 44;

export default function DependencyGraph({ result }: { result: AnalysisResult }) {
  const { nodes, edges } = useMemo(() => {
    const graph = result.graph ?? { nodes: [], edges: [] };
    const flagged = new Set(result.recommendations.flatMap(r => r.related_node_ids));

    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90 });
    g.setDefaultEdgeLabel(() => ({}));
    graph.nodes.forEach(n => g.setNode(n.id, { width: W, height: H }));
    graph.edges.forEach(e => g.setEdge(e.source, e.target));
    dagre.layout(g);

    const nodes: Node[] = graph.nodes.map(n => {
      const p = g.node(n.id);
      const bad = flagged.has(n.id);
      return {
        id: n.id,
        data: { label: n.label },
        position: { x: p.x - W / 2, y: p.y - H / 2 },
        style: {
          width: W,
          border: `2px solid ${bad ? '#ef4444' : '#94a3b8'}`,
          background: bad ? '#fef2f2' : '#ffffff',
        },
      };
    });

    const edges: Edge[] = graph.edges.map(e => ({
      id: `${e.source}->${e.target}:${e.type}`,
      source: e.source,
      target: e.target,
      label: e.label,
      markerEnd: { type: MarkerType.ArrowClosed },
    }));

    return { nodes, edges };
  }, [result]);

  return (
    <div className="mt-4 h-72 overflow-hidden rounded-lg border border-slate-200">
      <ReactFlow nodes={nodes} edges={edges} fitView nodesConnectable={false}>
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}