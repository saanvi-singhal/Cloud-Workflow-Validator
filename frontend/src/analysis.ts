// Pure helpers that turn an AnalysisResult into what the UI shows.
// Graph meaning (cycles, validity, order) always comes from the backend
// response; nothing here re-analyses the graph (PROJECT_SPEC 8.3, 12.3).

import type {
  AnalysisResult,
  Diagnostic,
  GraphEdge,
  GraphNode,
  Severity,
  SourceLocation,
} from './types';

const RANK: Record<Severity, number> = { error: 0, warning: 1, info: 2 };

export const edgeKey = (e: GraphEdge) => `${e.source}->${e.target}:${e.type}`;

export type StatusTone = 'valid' | 'warning' | 'error';

/** Status badge, driven by the backend's `valid` flag. */
export function getStatus(result: AnalysisResult): { label: string; tone: StatusTone } {
  if (!result.valid) return { label: 'Invalid', tone: 'error' };
  if (result.diagnostics.some(d => d.severity === 'warning')) {
    return { label: 'Valid with warnings', tone: 'warning' };
  }
  return { label: 'Valid', tone: 'valid' };
}

/** Partial analysis: an unsupported construct may hide dependencies. */
export function isPartial(result: AnalysisResult): boolean {
  return result.diagnostics.some(
    d => d.code === 'UNSUPPORTED_CONSTRUCT' && d.severity === 'warning',
  );
}

/** Why execution_order is null, or null when an order is available. */
export function executionOrderNote(result: AnalysisResult): string | null {
  if (result.execution_order !== null) return null;
  if (result.format === 'dockerfile') {
    return 'Not applicable: Dockerfile stages are not given a single execution order.';
  }
  if (!result.valid) return 'Not available until the errors are fixed.';
  if (isPartial(result)) {
    return 'Withheld because the analysis is partial: some dependencies may be missing.';
  }
  return 'Not available for this result.';
}

/** Most severe linked diagnostic for each node, via recommendations' related_node_ids. */
export function nodeSeverities(result: AnalysisResult): Map<string, Severity> {
  const severities = new Map<string, Severity>();
  for (const rec of result.recommendations) {
    const diagnostic = result.diagnostics[rec.diagnostic_index];
    if (!diagnostic) continue;
    for (const id of rec.related_node_ids) {
      const current = severities.get(id);
      if (current === undefined || RANK[diagnostic.severity] < RANK[current]) {
        severities.set(id, diagnostic.severity);
      }
    }
  }
  return severities;
}

/**
 * Nodes and edges on a dependency cycle, as reported by the backend.
 * Each DEPENDENCY_CYCLE recommendation lists the nodes of one cyclic region;
 * every edge between two nodes of the same region lies on a cycle.
 */
export function cycleHighlights(result: AnalysisResult) {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  const selfLoops = new Set<string>();
  for (const rec of result.recommendations) {
    if (rec.diagnostic_code !== 'DEPENDENCY_CYCLE') continue;
    const members = new Set(rec.related_node_ids);
    members.forEach(id => nodes.add(id));
    for (const edge of result.graph.edges) {
      if (!members.has(edge.source) || !members.has(edge.target)) continue;
      if (edge.source === edge.target) selfLoops.add(edge.source);
      else edges.add(edgeKey(edge));
    }
  }
  return { nodes, edges, selfLoops };
}

/**
 * Node ids linked to one diagnostic. Diagnostics carry no node ids (spec 6.1);
 * the link is the recommendations that point at the diagnostic by index.
 */
export function diagnosticNodeIds(result: AnalysisResult, index: number): string[] {
  const ids = new Set<string>();
  for (const rec of result.recommendations) {
    if (rec.diagnostic_index === index) rec.related_node_ids.forEach(id => ids.add(id));
  }
  return [...ids];
}

/** Diagnostics linked to a node, with their index in `diagnostics`. */
export function nodeDiagnostics(
  result: AnalysisResult,
  nodeId: string,
): { index: number; diagnostic: Diagnostic }[] {
  const indexes = new Set<number>();
  for (const rec of result.recommendations) {
    if (rec.related_node_ids.includes(nodeId)) indexes.add(rec.diagnostic_index);
  }
  return [...indexes]
    .sort((a, b) => a - b)
    .filter(index => result.diagnostics[index] !== undefined)
    .map(index => ({ index, diagnostic: result.diagnostics[index] }));
}

export interface StageInstruction {
  instruction: string;
  text: string;
  start_line: number;
  end_line: number;
}

/** A Dockerfile stage's ordered instructions from its metadata (spec 4.2). */
export function stageInstructions(node: GraphNode): StageInstruction[] {
  const raw = node.metadata.instructions;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is StageInstruction =>
      typeof item === 'object' &&
      item !== null &&
      typeof item.instruction === 'string' &&
      typeof item.text === 'string' &&
      typeof item.start_line === 'number',
  );
}

/** Metadata to list in node details: everything except instructions, as text. */
export function metadataEntries(node: GraphNode): [string, string][] {
  return Object.entries(node.metadata)
    .filter(([key, value]) => key !== 'instructions' && value !== null && value !== '')
    .map(([key, value]) => [
      key,
      typeof value === 'object' ? JSON.stringify(value) : String(value),
    ]);
}

/** Readable names for the edge types (spec 3.5). */
export const EDGE_TYPE_LABELS: Record<string, string> = {
  workflow_dependency: 'needs',
  terraform_reference: 'reference',
  terraform_explicit_dependency: 'depends_on',
  docker_stage_base: 'stage dependency (FROM / COPY --from)',
  docker_instruction_order: 'instruction order',
};

/** Human-readable label for a node id (falls back to the id). */
export function labelFor(result: AnalysisResult, id: string): string {
  return result.graph.nodes.find(n => n.id === id)?.label ?? id;
}

/** "line 5, column 21", or null when the location has no line. */
export function formatLocation(loc: SourceLocation | null): string | null {
  if (!loc || loc.start_line === null) return null;
  return loc.start_column !== null
    ? `line ${loc.start_line}, column ${loc.start_column}`
    : `line ${loc.start_line}`;
}

/**
 * Character offsets [start, end) in `text` for a source location, for
 * textarea.setSelectionRange. Uses the exclusive end_column as-is; falls
 * back to the whole start line when columns or the end are missing.
 */
export function selectionRange(
  text: string,
  loc: SourceLocation | null,
): { start: number; end: number } | null {
  if (!loc || loc.start_line === null) return null;
  const lines = text.split('\n');
  if (loc.start_line > lines.length) return null;

  const lineStart = (line: number) =>
    lines.slice(0, line - 1).reduce((sum, l) => sum + l.length + 1, 0);
  const clamp = (offset: number) => Math.min(Math.max(offset, 0), text.length);

  const startLineOffset = lineStart(loc.start_line);
  const wholeLineEnd = startLineOffset + lines[loc.start_line - 1].length;
  const start =
    loc.start_column !== null ? startLineOffset + loc.start_column - 1 : startLineOffset;
  const end =
    loc.end_line !== null && loc.end_column !== null && loc.end_line <= lines.length
      ? lineStart(loc.end_line) + loc.end_column - 1
      : wholeLineEnd;

  return { start: clamp(start), end: clamp(Math.max(end, start)) };
}
